"""Remote access (docs/remote-access.md): accounts, sessions, CSRF, listener permissions, per-line concurrency,
the change feed, audio ranges and peaks, and the built-page server. Synthetic data in a temporary root
(the fixtures of test_m4.py); nothing touches the real mappings or the game.

Run: python -m unittest tests.test_remote_access
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import m4_server  # noqa: E402
import studio_auth  # noqa: E402
from live_feed import LiveFeed  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from studio_auth import Authenticator, LoginThrottle, SessionStore, UserStore  # noqa: E402
from studio_net import ConfigError, HostPolicy, load_server_config  # noqa: E402
from test_m4 import make_root, write_wav  # noqa: E402

FAST = dict(n=1 << 10, r=8, p=1)  # cheap scrypt cost for tests only
PASSWORD = "correct horse battery"


class PasswordAndSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hash_verify_and_salt(self):
        a, b = studio_auth.hash_password("pw-1234567", **FAST), studio_auth.hash_password("pw-1234567", **FAST)
        self.assertNotEqual(a, b)  # salted
        self.assertTrue(studio_auth.verify_password("pw-1234567", a))
        self.assertFalse(studio_auth.verify_password("pw-1234568", a))
        self.assertFalse(studio_auth.verify_password("x", "garbage"))
        self.assertNotIn("pw-1234567", a)

    def test_password_and_name_rules(self):
        with self.assertRaises(ValueError):
            studio_auth.check_password_strength("short")
        with self.assertRaises(ValueError):
            studio_auth.check_username("Bad Name")
        self.assertEqual(studio_auth.check_username("andy.o"), "andy.o")

    def test_sessions_store_only_hashes_and_expire(self):
        store = SessionStore(self.dir / "s.sqlite", idle_hours=1, max_days=1)
        token, csrf = store.create("andy", "stamp", "1.2.3.4", "ua")
        self.assertEqual(store.lookup(token)["username"], "andy")
        self.assertNotIn(token.encode(), (self.dir / "s.sqlite").read_bytes())
        self.assertIsNone(store.lookup("nope"))
        store.idle_s = -1  # everything is now idle
        self.assertIsNone(store.lookup(token))

    def test_changed_password_ends_sessions(self):
        users = UserStore(self.dir / "u.json")
        users.write({"andy": {"role": "editor", "password": studio_auth.hash_password(PASSWORD, **FAST)}})
        auth = Authenticator(users, SessionStore(self.dir / "s.sqlite"))
        token, _csrf, _u = auth.login("andy", PASSWORD, "1.1.1.1", "ua")
        self.assertIsNotNone(auth.session(token))
        time.sleep(0.01)
        users.write({"andy": {"role": "editor", "password": studio_auth.hash_password("another pass 1", **FAST)}})
        os.utime(users.path, None)
        self.assertIsNone(auth.session(token))

    def test_throttle_locks_after_failures(self):
        users = UserStore(self.dir / "u.json")
        users.write({"andy": {"role": "editor", "password": studio_auth.hash_password(PASSWORD, **FAST)}})
        auth = Authenticator(users, SessionStore(self.dir / "s.sqlite"), LoginThrottle(limit=3))
        studio_auth.time.sleep, orig = (lambda s: None), studio_auth.time.sleep
        try:
            for _ in range(3):
                with self.assertRaises(studio_auth.AuthError) as e:
                    auth.login("andy", "wrong password", "9.9.9.9", "")
                self.assertEqual(e.exception.status, 401)
            with self.assertRaises(studio_auth.AuthError) as e:
                auth.login("andy", PASSWORD, "9.9.9.9", "")  # even the right password, for a while
            self.assertEqual(e.exception.status, 429)
        finally:
            studio_auth.time.sleep = orig


class ConfigTests(unittest.TestCase):
    def test_unknown_keys_and_public_local_host_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_server_config(tmp, overrides={"remote": {"enabeld": True}})
            with self.assertRaises(ConfigError):
                load_server_config(tmp, overrides={"local": {"host": "0.0.0.0"}})
            with self.assertRaises(ConfigError):
                load_server_config(tmp, overrides={"remote": {"enabled": True, "port": 8765}})
            cfg = load_server_config(tmp)
            self.assertFalse(cfg["remote"]["enabled"])  # off unless asked for

    def test_host_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_server_config(tmp, overrides={"allowed_hosts": ["pc.tail1.ts.net"]})
            local, remote = HostPolicy(cfg, "local", 8765), HostPolicy(cfg, "remote", 8766)
            self.assertTrue(local.host_ok("127.0.0.1:8765"))
            self.assertFalse(local.host_ok("192.168.1.10:8765"))
            self.assertTrue(remote.host_ok("pc.tail1.ts.net"))
            self.assertFalse(remote.host_ok("evil.example:8766"))
            self.assertTrue(remote.origin_ok("https://pc.tail1.ts.net", "127.0.0.1:8766"))
            self.assertFalse(remote.origin_ok("https://evil.example", "pc.tail1.ts.net"))
            self.assertFalse(remote.origin_ok("null", "pc.tail1.ts.net"))


class PerLineConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        self.app = M4App(self.root, today=lambda: "2026-10-11", run_validator=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_computers_on_different_lines_both_save(self):
        a, b = self.app.slot("es:Z10_010_keyes#0"), self.app.slot("es:Z10_020_cortana#0")
        self.assertTrue(self.app.save({"slot_id": a["slot_id"], "loaded_slot_sha256": a["sha256"]["slot"],
                                       "notes": "from PC 1"})["saved"])
        # b was loaded before that save: the file hash is stale, its own line is not.
        r = self.app.save({"slot_id": b["slot_id"], "loaded_slot_sha256": b["sha256"]["slot"], "notes": "from PC 2",
                           "loaded_sha256": b["sha256"]["mappings"]})
        self.assertTrue(r["saved"])
        self.assertEqual(r["slot"]["mapping"]["notes"], "from PC 2")
        self.assertEqual(self.app.slot(a["slot_id"])["mapping"]["notes"], "from PC 1")  # not overwritten

    def test_stale_line_is_refused_and_nothing_written(self):
        a = self.app.slot("es:Z10_010_keyes#0")
        self.app.save({"slot_id": a["slot_id"], "loaded_slot_sha256": a["sha256"]["slot"], "notes": "first"})
        before = (self.root / "mappings/manual_mappings.json").read_bytes()
        with self.assertRaises(ApiError) as e:
            self.app.save({"slot_id": a["slot_id"], "loaded_slot_sha256": a["sha256"]["slot"], "notes": "second"})
        self.assertEqual(e.exception.status, 409)
        self.assertEqual((self.root / "mappings/manual_mappings.json").read_bytes(), before)

    def test_whole_file_check_still_applies_without_a_line_version(self):
        a = self.app.slot("es:Z10_010_keyes#0")
        self.app.save({"slot_id": a["slot_id"], "loaded_sha256": a["sha256"]["mappings"], "notes": "x"})
        with self.assertRaises(ApiError) as e:
            self.app.save({"slot_id": "es:Z10_020_cortana#0", "loaded_sha256": a["sha256"]["mappings"], "notes": "y"})
        self.assertEqual(e.exception.status, 409)

    def test_feed_sees_the_change(self):
        feed = LiveFeed(self.root / "mappings/manual_mappings.db")
        feed.poll_once()  # starting point
        q = feed.subscribe()
        a = self.app.slot("es:Z10_010_keyes#0")
        feed.note_author(a["slot_id"], "sofia")
        self.app.save({"slot_id": a["slot_id"], "loaded_slot_sha256": a["sha256"]["slot"], "notes": "x"})
        ev = feed.poll_once()
        self.assertEqual(ev["slots"], [a["slot_id"]])
        self.assertEqual(ev["by"], {a["slot_id"]: "sofia"})
        self.assertEqual(q.get_nowait()["seq"], ev["seq"])
        self.assertIsNone(feed.poll_once())


class ListenerTests(unittest.TestCase):
    """Both listeners of the real handler, on ephemeral loopback ports."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        clip = self.root / "work/clip.wav"
        write_wav(clip)

        class StubAudio:  # a decoded clip; the decoding itself is tested in test_m4
            def wav(self, *_a):
                return clip
        self.app = M4App(self.root, today=lambda: "2026-10-11", run_validator=False, mcc_audio=StubAudio(),
                         ce_audio=StubAudio())
        dist = self.root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
        (dist / "assets" / "app-1234.js").write_text("console.log(1)" * 200, encoding="utf-8")
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config" / "secret.json").write_text("{}", encoding="utf-8")
        cfg = load_server_config(self.root, overrides={
            "remote": {"enabled": True, "host": "127.0.0.1", "port": 1},
            "static_dir": str(dist), "users_file": "config/users.json", "sessions_file": "work/studio/s.sqlite"})
        users = UserStore(cfg["users_path"])
        users.write({"ed": {"role": "editor", "password": studio_auth.hash_password(PASSWORD, **FAST)},
                     "boss": {"role": "admin", "password": studio_auth.hash_password(PASSWORD, **FAST)}})
        auth = Authenticator(users, SessionStore(cfg["sessions_path"]))
        self.feed = LiveFeed(self.root / "mappings/manual_mappings.db", interval_s=0.05)
        self.feed.start()
        shared = m4_server.Shared(self.root, cfg, self.feed)
        self.servers = {}
        for kind in ("local", "remote"):
            lst = m4_server.Listener(kind, cfg, 0, auth=auth if kind == "remote" else None)
            srv = m4_server.StudioHTTPServer(("127.0.0.1", 0),
                                             m4_server.make_handler(self.app, quiet=True, listener=lst, shared=shared))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers[kind] = srv

    def tearDown(self):
        self.feed.stop()
        for srv in self.servers.values():
            srv.shutdown()
            srv.server_close()
        self.tmp.cleanup()

    def req(self, kind, path, body=None, headers=None, method=None):
        base = f"http://127.0.0.1:{self.servers[kind].server_address[1]}"
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if body is not None else {}
        r = urllib.request.Request(base + path, data=data, headers={**h, **(headers or {})}, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def login(self, user="ed"):
        st, body, headers = self.req("remote", "/api/login", {"username": user, "password": PASSWORD})
        self.assertEqual(st, 200, body)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        token = cookie.split(";")[0]
        return {"Cookie": token, "X-Studio-CSRF": json.loads(body)["csrf"]}

    def test_unauthenticated_remote_requests_are_blocked(self):
        for path in ("/api/state", "/api/slots?level=z10", "/api/slot?id=es%3AZ10_010_keyes%230",
                     "/audio/mcc?level=z10&lang=spanish&index=0", "/api/events", "/api/network",
                     "/audio/peaks?src=%2Faudio%2Fmcc%3Flevel%3Dz10%26lang%3Dspanish%26index%3D0"):
            self.assertEqual(self.req("remote", path)[0], 401, path)
        self.assertEqual(self.req("remote", "/api/save", {"slot_id": "x"})[0], 401)
        st, body, _ = self.req("remote", "/api/session")
        self.assertEqual((st, json.loads(body)["authenticated"]), (200, False))
        self.assertEqual(self.req("remote", "/api/login", {"username": "ed", "password": "nope nope nope"})[0], 401)
        self.assertEqual(self.req("remote", "/api/state", headers={"Cookie": "studio_session=forged"})[0], 401)

    def test_signed_in_editor_can_match_but_not_administer(self):
        h = self.login("ed")
        st, body, _ = self.req("remote", "/api/slot?id=es%3AZ10_010_keyes%230", headers=h)
        self.assertEqual(st, 200)
        version = json.loads(body)["sha256"]["slot"]
        save = {"slot_id": "es:Z10_010_keyes#0", "loaded_slot_sha256": version, "notes": "remote note"}
        self.assertEqual(self.req("remote", "/api/save", save, headers={"Cookie": h["Cookie"]})[0], 403)  # no CSRF
        self.assertEqual(self.req("remote", "/api/save", save, headers={**h, "X-Studio-CSRF": "x" * 43})[0], 403)
        st, body, _ = self.req("remote", "/api/save", save, headers=h)
        self.assertEqual(st, 200, body)
        self.assertEqual(self.req("remote", "/api/save", save, headers=h)[0], 409)  # same stale version
        for path in ("/api/data/export", "/api/builds/start", "/api/settings/export"):
            self.assertEqual(self.req("remote", path, {"confirm": True}, headers=h)[0], 403, path)
        audit = (self.root / "work/studio/audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"user": "ed"', audit)
        self.assertNotIn(PASSWORD, audit)

    def test_game_install_is_never_possible_remotely(self):
        h = self.login("boss")  # even an admin
        for path in ("/api/deploy/install", "/api/deploy/restore", "/api/settings/mcc"):
            st, body, _ = self.req("remote", path, {"build": "x", "confirm": True, "mcc_folder": "C:/"}, headers=h)
            self.assertEqual(st, 403, path)
            self.assertIn("host computer", json.loads(body)["error"])
        st, body, _ = self.req("remote", "/api/session", headers=h)
        perms = json.loads(body)["permissions"]
        self.assertEqual((perms["admin"], perms["install"]), (True, False))
        st, body, _ = self.req("local", "/api/session")
        self.assertTrue(json.loads(body)["permissions"]["install"])

    def test_local_listener_refuses_proxied_and_foreign_requests(self):
        self.assertEqual(self.req("local", "/api/state", headers={"X-Forwarded-For": "8.8.8.8"})[0], 403)
        self.assertEqual(self.req("local", "/api/state", headers={"Tailscale-User-Login": "a@b"})[0], 403)
        self.assertEqual(self.req("local", "/api/state", headers={"Host": "192.168.1.10:8765"})[0], 403)
        self.assertEqual(self.req("local", "/api/state")[0], 200)
        h = self.login()
        self.assertEqual(self.req("remote", "/api/state", headers={**h, "Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("remote", "/api/state", headers={**h, "Origin": "https://evil.example"})[0], 403)

    def test_no_arbitrary_files(self):
        h = self.login()
        for path in ("/../config/secret.json", "/%2e%2e/config/secret.json", "/assets/..%2f..%2fconfig/secret.json",
                     "/mappings/manual_mappings.db", "/mappings/manual_mappings.json", "/work/studio/s.sqlite",
                     "/config/users.json", "/..%5cconfig%5csecret.json"):
            st, body, _ = self.req("remote", path, headers=h)
            self.assertEqual(st, 404, path)
        st, _, _ = self.req("remote", "/audio/peaks?src=" + urllib.request.quote("file:///C:/Windows/win.ini"), headers=h)
        self.assertEqual(st, 400)
        st, _, _ = self.req("remote", "/audio/peaks?src=" + urllib.request.quote("/api/state"), headers=h)
        self.assertEqual(st, 400)
        self.assertIn(self.req("remote", "/audio/preview?key=../../x&kind=edited", headers=h)[0], (400, 503))
        self.assertEqual(self.req("remote", "/classic", headers=h)[0], 404)  # the classic page stays on the host
        self.assertEqual(self.req("local", "/classic")[0], 200)

    def test_built_page_and_assets(self):
        st, body, headers = self.req("remote", "/")
        self.assertEqual(st, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        st, body, headers = self.req("remote", "/assets/app-1234.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual((st, headers["Content-Encoding"]), (200, "gzip"))
        self.assertIn("immutable", headers["Cache-Control"])
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))

    def test_audio_ranges_and_peaks(self):
        h = self.login()
        url = "/audio/mcc?level=z10&lang=spanish&index=0"
        st, full, headers = self.req("remote", url, headers=h)
        self.assertEqual((st, headers["Content-Type"], headers["Accept-Ranges"]), (200, "audio/wav", "bytes"))
        st, part, headers = self.req("remote", url, headers={**h, "Range": "bytes=100-199"})
        self.assertEqual((st, part), (206, full[100:200]))
        st, part, headers = self.req("remote", url, headers={**h, "Range": "bytes=-50"})
        self.assertEqual((st, part), (206, full[-50:]))
        self.assertEqual(self.req("remote", url, headers={**h, "Range": f"bytes={len(full) + 5}-"})[0], 416)
        st, _, _ = self.req("remote", url, headers={**h, "If-None-Match": headers["ETag"]})
        self.assertEqual(st, 304)
        st, body, _ = self.req("remote", "/audio/peaks?src=" + urllib.request.quote(url), headers=h)
        peaks = json.loads(body)
        self.assertEqual(st, 200)
        self.assertAlmostEqual(peaks["duration"], 0.1, places=3)
        self.assertTrue(all(0 <= p <= 1 for p in peaks["peaks"]))

    def test_events_stream_a_change_from_another_session(self):
        h = self.login()
        port = self.servers["remote"].server_address[1]
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/events", headers={"Cookie": h["Cookie"]})
        resp = conn.getresponse()
        self.assertEqual(resp.getheader("Content-Type"), "text/event-stream; charset=utf-8")
        self.assertIn(b"event: hello", resp.readline() + resp.readline() + resp.readline())
        time.sleep(0.15)  # the feed has its starting point
        st, body, _ = self.req("local", "/api/slot?id=es%3AZ10_020_cortana%230")
        self.req("local", "/api/save", {"slot_id": "es:Z10_020_cortana#0",
                                        "loaded_slot_sha256": json.loads(body)["sha256"]["slot"], "notes": "x"})
        line = b""
        deadline = time.time() + 5
        while b"Z10_020_cortana" not in line and time.time() < deadline:
            line = resp.readline()
        event = json.loads(line.decode().removeprefix("data: "))
        self.assertEqual((event["slots"], event["by"]), (["es:Z10_020_cortana#0"], {"es:Z10_020_cortana#0": "host"}))
        conn.close()

    def test_logout_ends_the_session(self):
        h = self.login()
        self.assertEqual(self.req("remote", "/api/logout", {}, headers=h)[0], 200)
        self.assertEqual(self.req("remote", "/api/state", headers=h)[0], 401)


if __name__ == "__main__":
    unittest.main()
