"""The public read-only listener (docs/public-access.md), tested against the real handler: anonymous visitors
can browse the allowlisted, sanitised metadata and the built page, and nothing else. No writes, no audio, no
downloads, no settings, no live feed, no game-folder details; forged identity headers or tokens change nothing.
The Cloudflare Access listener beside it keeps full editing for the owner, and an expired sign-in loses it.

Synthetic data in a temporary root (test_m4 fixtures) and synthetic RSA keys (test_cf_access); nothing touches
the network, the real mappings or the game.

Run: python -m unittest tests.test_public_access
"""
import hashlib
import json
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

import cf_access  # noqa: E402
import m4_server  # noqa: E402
import public_previews  # noqa: E402
import public_view  # noqa: E402
from live_feed import LiveFeed  # noqa: E402
from m4_app import M4App  # noqa: E402
from studio_net import ConfigError, load_server_config  # noqa: E402
from test_cf_access import OWNER, SETTINGS, NoRedirect, claims, sign, verifier  # noqa: E402
from test_m4 import make_root, write_wav  # noqa: E402

PUBLIC_HOST = "studio.example.com"
ADMIN_HOST = "admin.example.com"
SLOT = "es:Z10_010_keyes#0"
GAME = r"D:\Games\SteamLibrary\steamapps\common\Halo The Master Chief Collection"

# Every write the server knows (m4_server's API list), and every GET a visitor must not reach.
POSTS = ("/api/save", "/api/progress", "/api/validate", "/api/edit/preview", "/api/login", "/api/logout",
         "/api/settings/export", "/api/settings/mcc", "/api/builds/start", "/api/builds/preview", "/api/builds/dry-run",
         "/api/deploy/install", "/api/deploy/restore", "/api/data/import/preview", "/api/data/import",
         "/api/data/export")
AUDIO_SRC = "%2Faudio%2Fmcc%3Flevel%3Dz10%26lang%3Dspanish%26index%3D0"
REFUSED_GETS = ("/audio/mcc?level=z10&lang=spanish&index=0", "/audio/mcc?level=z10&lang=english&index=0",
                "/audio/ce?ref=line_a%230&lang=Spanish(Mexico)", "/audio/preview?key=abc&kind=edited",
                f"/audio/peaks?src={AUDIO_SRC}", "/audio/anything", "/api/events", "/api/network",
                "/api/settings/export", "/api/data/status", "/api/job?id=1", "/api/deploy/status",
                "/api/deploy/plan?build=b1", "/api/builds/log?name=b1", "/api/sso/continue",
                "/api/interference/reference?slot=x&lang=spanish", "/api/unknown")


class PublicListenerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        clip = self.root / "work/clip.wav"
        write_wav(clip)
        self.decoded = []

        class StubAudio:
            def wav(inner, *a):
                self.decoded.append(a)
                return clip

            def cached(inner, *a):
                return None
        self.app = M4App(self.root, today=lambda: "2026-10-17", run_validator=False, mcc_audio=StubAudio(),
                         ce_audio=StubAudio())
        # A build and an install history that name local paths (as the real ones do).
        b = self.root / "work/m6/b1"
        b.mkdir(parents=True)
        (b / "build_manifest.json").write_text(json.dumps({
            "schema": "m6-build-manifest/1", "name": "b1", "kind": "audio", "levels": ["z10"],
            "built_at": "2026-10-17T10:00:00", "inputs": {"mappings_sha256": "0" * 64, "bank_copy": "D:\\x\\bank.fsb"},
            "install_files": [{"install_rel": "halo1/sound/pc/sounds_dialogs_spanish.fsb",
                               "candidate": "work/m6/b1/sounds_dialogs_spanish.fsb", "candidate_sha256": "1" * 64,
                               "size": 10}]}), encoding="utf-8")
        (self.root / "work/m6/b1_build.log").write_text(f"built from {GAME}\n", encoding="utf-8")
        (self.root / "work/m6/deploy_history.jsonl").write_text(json.dumps({
            "at": "2026-10-17T11:00:00", "action": "install", "result": "failed", "build": "b1", "kind": "audio",
            "mcc_root": GAME, "message": f"could not write {GAME}\\halo1\\sound\\pc\\x.fsb",
            "files": [{"install_rel": "halo1/sound/pc/sounds_dialogs_spanish.fsb", "candidate_sha256": "1" * 64,
                       "installed_sha256": "2" * 64, "backup": "C:\\Users\\owner\\backup"}]}) + "\n", encoding="utf-8")
        dist = self.root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
        (dist / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
        self.cfg = load_server_config(self.root, overrides={
            "remote": {"enabled": True, "host": "127.0.0.1", "port": 1, "auth": "cloudflare_access"},
            "public_url": f"https://{ADMIN_HOST}", "cloudflare_access": SETTINGS,
            "public": {"enabled": True, "host": "127.0.0.1", "port": 2, "url": f"https://{PUBLIC_HOST}"},
            "static_dir": str(dist), "sessions_file": "work/studio/s.sqlite"})
        self.feed = LiveFeed(self.root / "mappings/manual_mappings.db", interval_s=0.05)
        self.feed.start()
        shared = m4_server.Shared(self.root, self.cfg, self.feed)
        key = m4_server._access_csrf_key(self.root / "work/studio")
        self.servers = {}
        for kind in ("local", "remote", "public"):
            lst = m4_server.Listener(kind, self.cfg, 0, access=verifier() if kind == "remote" else None, csrf_key=key)
            srv = m4_server.StudioHTTPServer(("127.0.0.1", 0), m4_server.make_handler(
                self.app, quiet=True, listener=lst, shared=shared))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers[kind] = srv

    def tearDown(self):
        self.feed.stop()
        for srv in self.servers.values():
            srv.shutdown()
            srv.server_close()
        self.tmp.cleanup()

    def req(self, kind, path, body=None, headers=None, token=None, host=None, method=None):
        host = host or {"public": PUBLIC_HOST, "remote": ADMIN_HOST, "local": "localhost"}[kind]
        base = f"http://127.0.0.1:{self.servers[kind].server_address[1]}"
        h = {"Host": host, **({"Content-Type": "application/json"} if body is not None else {})}
        if token:
            h[cf_access.HEADER] = token
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(base + path, data=data, headers={**h, **(headers or {})}, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(r, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def get(self, path, **kw):
        st, body, _ = self.req("public", path, **kw)
        self.assertEqual(st, 200, (path, body[:200]))
        return json.loads(body)

    def data_hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((self.root / "mappings").glob("*")) if p.is_file()}

    # ------------------------------------------------------------------ browsing
    def test_anonymous_visitor_browses_the_studio(self):
        self.assertEqual(self.req("public", "/")[0], 200)
        self.assertEqual(self.req("public", "/assets/app-1234.js")[0], 200)
        info = self.get("/api/session")
        self.assertEqual((info["listener"], info["visitor"], info["authenticated"], info["user"], info["csrf"]),
                         ("public", True, False, None, None))
        self.assertEqual(info["sign_in_url"], f"https://{ADMIN_HOST}")
        previews = self.cfg["public"]["previews"]  # off by default; PublicPreviewTests turns it on
        originals = self.cfg["public"]["originals"]  # off by default; PublicOriginalsTests turns it on
        self.assertEqual(info["permissions"], {"edit": False, "admin": False, "install": False, "settings_mcc": False,
                                               "audio": originals, "download": False, "previews": previews})
        state = self.get("/api/state")
        self.assertEqual([lv["level"] for lv in state["levels"]], ["z10"])
        rows = self.get("/api/slots?level=z10")["slots"]
        self.assertIn(SLOT, [r["slot_id"] for r in rows])
        self.assertIn(SLOT, [r["slot_id"] for r in self.get("/api/slots?level=all&q=keyes")["slots"]])
        self.assertEqual(self.get(f"/api/slot?id={SLOT.replace(':', '%3A').replace('#', '%23')}")["slot_id"], SLOT)
        self.assertGreater(self.get("/api/ce?mission=all")["total"], 0)
        self.assertEqual(self.get("/api/ce_line?ref=line_a%230")["ce_line_ref"], "line_a#0")
        self.assertEqual([b["name"] for b in self.get("/api/builds")["builds"]], ["b1"])
        self.assertEqual(self.get("/api/builds/detail?name=b1")["name"], "b1")
        self.assertEqual(len(self.get("/api/deploy/history")["events"]), 1)
        self.assertEqual(self.decoded, [], "browsing decoded audio")

    def test_answers_are_sanitised(self):
        builds = self.get("/api/builds")["builds"][0]
        self.assertFalse(builds["has_log"])
        self.assertEqual(set(builds["install_files"][0]), {"install_rel", "candidate_sha256", "size"})
        events = self.get("/api/deploy/history")["events"]
        for blob in (json.dumps(events), json.dumps(self.get("/api/builds/detail?name=b1")), json.dumps(builds)):
            self.assertNotIn("SteamLibrary", blob)
            self.assertNotIn("Users", blob)
            self.assertNotIn("mcc_root", blob)
        self.assertIn(public_view.HIDDEN, events[0]["message"])
        # the owner's notes are not public; the decision itself is
        sid = SLOT.replace(":", "%3A").replace("#", "%23")
        tok = sign(claims())
        csrf = json.loads(self.req("remote", "/api/session", token=tok)[1])["csrf"]
        version = json.loads(self.req("remote", f"/api/slot?id={sid}", token=tok)[1])["sha256"]["slot"]
        st, body, _ = self.req("remote", "/api/save", {"slot_id": SLOT, "loaded_slot_sha256": version,
                                                       "notes": "private remark"}, token=tok,
                               headers={"X-Studio-CSRF": csrf})
        self.assertEqual(st, 200, body)
        slot = self.get(f"/api/slot?id={sid}")
        self.assertIsNotNone(slot["mapping"])
        self.assertEqual(slot["mapping"]["notes"], "")
        self.assertNotIn("private remark", json.dumps(slot))
        self.assertEqual(slot["interference"], {})

    # ------------------------------------------------------------------ refused
    def test_no_writes_of_any_kind(self):
        before = self.data_hashes()
        for path in POSTS:
            st, body, _ = self.req("public", path, {"slot_id": SLOT, "notes": "x", "confirm": True, "build": "b1"})
            self.assertEqual(st, 401, path)
            self.assertIn("read-only", json.loads(body)["error"])
            self.assertIn(f"https://{ADMIN_HOST}", json.loads(body)["error"])
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.req("public", "/api/save", {"slot_id": SLOT}, method=method)[0], 401, method)
        self.assertEqual(self.data_hashes(), before)
        self.assertFalse((self.root / "work/studio/audit.jsonl").exists(), "an anonymous request wrote the audit log")

    REFUSED = REFUSED_GETS  # PublicOriginalsTests narrows it

    def test_no_audio_downloads_settings_or_feed(self):
        for path in self.REFUSED:
            for method in ("GET", "HEAD"):
                st, _, _ = self.req("public", path, method=method)
                self.assertEqual(st, 401, (method, path))
        self.assertEqual(self.decoded, [])

    def test_forged_identity_grants_nothing(self):
        valid = sign(claims())  # even a genuine owner token is ignored on the public listener
        forged = {"Cf-Access-Authenticated-User-Email": OWNER, "Cookie": "studio_session=abc; CF_Authorization=x",
                  "X-Studio-CSRF": "x", "X-Forwarded-For": "127.0.0.1", "Cf-Connecting-Ip": "127.0.0.1",
                  "X-Forwarded-User": OWNER, "Remote-User": OWNER, "Authorization": "Bearer " + valid}
        info = json.loads(self.req("public", "/api/session", token=valid, headers=forged)[1])
        self.assertEqual((info["visitor"], info["user"], info["permissions"]["edit"]), (True, None, False))
        self.assertEqual(self.req("public", "/api/save", {"slot_id": SLOT, "notes": "x"}, token=valid,
                                  headers=forged)[0], 401)
        self.assertEqual(self.req("public", "/audio/preview?key=abc&kind=edited", token=valid,
                                  headers=forged)[0], 401)  # editor previews: refused even with originals on
        self.assertEqual(self.req("public", "/api/state?role=admin&edit=1", headers=forged)[0], 200)

    def test_host_traversal_and_classic(self):
        self.assertEqual(self.req("public", "/api/state", host="evil.example")[0], 403)
        self.assertEqual(self.req("public", "/api/state", host=ADMIN_HOST)[0], 403)  # not this listener's name
        self.assertEqual(self.req("public", "/api/state", host="localhost")[0], 200)
        self.assertEqual(self.req("public", "/classic")[0], 404)
        for path in ("/../config/studio_server.json", "/%2e%2e/mappings/manual_mappings.db", "/assets/..%5c..%5cx",
                     "/mappings/manual_mappings.json", "/work/m6/b1_build.log", "/work/studio/access_csrf.key"):
            self.assertIn(self.req("public", path)[0], (400, 404), path)
        st, _, headers = self.req("public", "/api/state")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_rate_limit(self):
        lim = public_view.PublicLimiter(per_minute=3)
        for _ in range(3):
            lim.admit("203.0.113.5")
        with self.assertRaises(public_view.Limited) as e:
            lim.admit("203.0.113.5")
        self.assertEqual(e.exception.status, 429)
        lim.admit("203.0.113.6")  # per address
        # through the handler: the tunnel's Cf-Connecting-Ip names the visitor
        lst =m4_server.Listener("public", self.cfg, 0, limiter=public_view.PublicLimiter(per_minute=2))
        s2 = m4_server.StudioHTTPServer(("127.0.0.1", 0), m4_server.make_handler(self.app, quiet=True, listener=lst))
        threading.Thread(target=s2.serve_forever, daemon=True).start()
        try:
            self.servers["limited"] = s2
            codes = [self.req("limited", "/api/state", host=PUBLIC_HOST, headers={"Cf-Connecting-Ip": "198.51.100.7"})[0]
                     for _ in range(3)]
            self.assertEqual(codes, [200, 200, 429])
            self.assertEqual(self.req("limited", "/", host=PUBLIC_HOST)[0], 200)  # the page itself is not limited
        finally:
            self.servers.pop("limited")
            s2.shutdown()
            s2.server_close()

    # ------------------------------------------------------------------ the owner, beside it
    def test_owner_still_edits_and_expiry_removes_it(self):
        tok = sign(claims())
        info = json.loads(self.req("remote", "/api/session", token=tok)[1])
        self.assertEqual((info["visitor"], info["user"], info["permissions"]["edit"], info["permissions"]["audio"]),
                         (False, OWNER, True, True))
        self.assertEqual(self.req("remote", "/audio/mcc?level=z10&lang=spanish&index=0", token=tok)[0], 200)
        sid = SLOT.replace(":", "%3A").replace("#", "%23")
        version = json.loads(self.req("remote", f"/api/slot?id={sid}", token=tok)[1])["sha256"]["slot"]
        save = {"slot_id": SLOT, "loaded_slot_sha256": version, "notes": "owner edit"}
        st, body, _ = self.req("remote", "/api/save", save, token=tok, headers={"X-Studio-CSRF": info["csrf"]})
        self.assertEqual(st, 200, body)
        expired = sign(claims(exp=time.time() - 3600, iat=time.time() - 7200))
        for path, body in (("/api/save", save), ("/api/state", None), ("/audio/mcc?level=z10&lang=spanish&index=0",
                                                                      None)):
            self.assertEqual(self.req("remote", path, body, token=expired, headers={"X-Studio-CSRF": info["csrf"]})[0],
                             401, path)
        # the editing address still refuses anonymous requests and game installs
        self.assertEqual(self.req("remote", "/api/state")[0], 401)
        self.assertEqual(self.req("remote", "/api/deploy/install", {"build": "b1"}, token=tok,
                                  headers={"X-Studio-CSRF": info["csrf"]})[0], 403)
        # and the public host name does not reach it
        self.assertEqual(self.req("remote", "/api/state", token=tok, host=PUBLIC_HOST)[0], 403)


class PublicPreviewTests(PublicListenerTests):
    """The owner turned on "public": {"previews": true}: visitors play the published edited previews of APPROVED
    lines, pre-rendered by publish_previews.py. Never originals, drafts, reworked lines or editor previews, and
    nothing is ever rendered for a visitor. Re-runs every PublicListenerTests check."""

    def setUp(self):
        super().setUp()
        self.cfg["public"]["previews"] = True  # the listeners read it per request
        self.renders = []
        clip = self.root / "work/clip.wav"
        out = self.root / "work/rendered.wav"
        out.write_bytes(clip.read_bytes() + b"")

        def edit_preview(body):  # the real renderer is tested in test_m4 / test_audio_edit
            self.renders.append(body)
            return {"key": "k" * 64, "summary": "no edits", "urls": {}}
        self.app.edit_preview = edit_preview
        self.app.preview_wav = lambda key, kind: out

    def save(self, **body):
        body.setdefault("slot_id", SLOT)
        body.setdefault("loaded_sha256", self.app.slot(SLOT)["sha256"]["mappings"])
        return self.app.save(body)

    def approve(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"}]})
        self.save(actions=[{"action": "approve", "field": "audio"}])

    def publish(self):
        return public_previews.publish(self.app, self.root, log=lambda *_: None)

    def preview_info(self):
        return self.get(f"/api/slot?id={SLOT.replace(':', '%3A').replace('#', '%23')}")["public_preview"]

    URL = "/audio/public?slot=es%3AZ10_010_keyes%230"

    def test_approved_line_plays_after_publishing(self):
        info = self.get("/api/session")
        self.assertEqual((info["permissions"]["previews"], info["permissions"]["audio"]),
                         (True, self.cfg["public"]["originals"]))
        self.assertEqual(self.req("public", self.URL)[0], 404)  # nothing decided yet
        self.assertIn("no decision", self.preview_info()["reason"])
        self.approve()
        self.assertEqual(self.req("public", self.URL)[0], 404)  # approved but not published
        self.assertEqual(self.renders, [], "a visitor request rendered audio")
        summary = self.publish()
        self.assertEqual((summary["published"], summary["rendered"]), (1, 1))
        self.assertEqual(self.renders[0]["ce_line_ref"], "line_a#0")
        p = self.preview_info()
        self.assertEqual((p["available"], p["url"]), (True, self.URL))
        st, body, headers = self.req("public", self.URL, headers={"Range": "bytes=0-9"})
        self.assertEqual((st, len(body), headers["Content-Type"]), (206, 10, "audio/wav"))
        self.assertIn("private", headers["Cache-Control"])  # never cached by Cloudflare
        st, body, _ = self.req("public", self.URL)
        self.assertEqual(st, 200)
        self.assertEqual(self.publish()["reused"], 1)  # unchanged: not rendered again
        self.assertEqual(len(self.renders), 1)
        blob = json.dumps(self.get(f"/api/slot?id={SLOT.replace(':', '%3A').replace('#', '%23')}"))
        self.assertNotIn(".wav", blob)  # no file names or keys leave the server

    def test_rework_or_change_stops_the_preview_at_once(self):
        self.approve()
        self.publish()
        self.assertEqual(self.req("public", self.URL)[0], 200)
        self.save(actions=[{"action": "needs_rework", "field": "audio"}])
        st, body, _ = self.req("public", self.URL)
        self.assertEqual(st, 404)
        self.assertIn("not approved", json.loads(body)["error"])
        self.assertFalse(self.preview_info()["available"])
        s = self.publish()  # republishing removes it and its file
        self.assertEqual((s["published"], s["removed"]), (0, [SLOT]))
        self.assertEqual(list((self.root / public_previews.STORE_REL).glob("*.wav")), [])

    def test_drafts_and_tampered_index_are_never_served(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"}]})
        self.assertEqual(self.publish()["published"], 0)  # drafts are not published
        store = self.root / public_previews.STORE_REL
        store.mkdir(parents=True, exist_ok=True)
        m = next(x for x in self.app._mappings()[0]["slots"] if x["slot_id"] == SLOT)
        for name in ("../../mappings/manual_mappings.json", "x" * 64 + ".wav"):
            (store / "index.json").write_text(json.dumps({"schema": public_previews.SCHEMA, "entries": {
                SLOT: {"file": name, "audio_key": public_previews.audio_key(m)}}}), encoding="utf-8")
            self.assertEqual(self.req("public", self.URL)[0], 404, name)  # a draft, whatever the index says
        self.save(actions=[{"action": "approve", "field": "audio"}])
        m = next(x for x in self.app._mappings()[0]["slots"] if x["slot_id"] == SLOT)
        (store / "index.json").write_text(json.dumps({"schema": public_previews.SCHEMA, "entries": {
            SLOT: {"file": "../../mappings/manual_mappings.json", "audio_key": public_previews.audio_key(m)}}}),
            encoding="utf-8")
        self.assertEqual(self.req("public", self.URL)[0], 404)  # approved, but not a store file name
        for path in ("/audio/public?slot=..%2F..%2Fmappings", "/audio/public?slot=", "/audio/public"):
            self.assertEqual(self.req("public", path)[0], 404, path)

    def test_originals_and_editor_previews_stay_private(self):
        self.approve()
        self.publish()
        for path in REFUSED_GETS:
            self.assertEqual(self.req("public", path)[0], 401, path)
        self.assertEqual(self.req("public", "/api/edit/preview", {"slot_id": SLOT})[0], 401)
        self.assertEqual(self.req("public", self.URL, method="POST")[0], 401)
        self.assertEqual(self.decoded, [])

    def test_previews_off_means_none(self):
        self.approve()
        self.publish()
        self.cfg["public"]["previews"] = False
        self.assertEqual(self.req("public", self.URL)[0], 401)
        self.assertNotIn("public_preview", self.get(f"/api/slot?id={SLOT.replace(':', '%3A').replace('#', '%23')}"))

    def test_preview_requests_are_rate_limited(self):
        self.approve()
        self.publish()
        lst = m4_server.Listener("public", self.cfg, 0, limiter=public_view.PublicLimiter(per_minute=1))
        s2 = m4_server.StudioHTTPServer(("127.0.0.1", 0), m4_server.make_handler(self.app, quiet=True, listener=lst))
        threading.Thread(target=s2.serve_forever, daemon=True).start()
        self.servers["limited"] = s2
        self.assertEqual([self.req("limited", self.URL, host=PUBLIC_HOST)[0] for _ in range(2)], [200, 429])


class PublicOriginalsTests(PublicPreviewTests):
    """The owner also turned on "public": {"originals": true} (2026-10-17): visitors play the original recordings
    (MCC Spain / English, unedited Campaign Evolved) and see waveforms of whatever they may hear. Downloads, editor
    previews, rendering, the interference reference, writes, settings and the live feed stay refused, and nothing
    is rendered for a visitor. Re-runs every PublicPreviewTests check (the private-originals one is replaced)."""

    MCC = ("/audio/mcc?level=z10&lang=spanish&index=0", "/audio/mcc?level=z10&lang=english&index=0")
    CE = "/audio/ce?ref=line_a%230&lang=Spanish(Mexico)"
    STILL_REFUSED = ("/audio/preview?key=abc&kind=edited", "/audio/peaks?src=%2Faudio%2Fpreview%3Fkey%3Dabc",
                     "/audio/peaks?src=https%3A%2F%2Fevil.example%2Faudio%2Fmcc", "/audio/peaks?src=",
                     "/audio/anything", "/api/events", "/api/network", "/api/settings/export", "/api/data/status",
                     "/api/job?id=1", "/api/deploy/status", "/api/deploy/plan?build=b1", "/api/builds/log?name=b1",
                     "/api/interference/reference?slot=x&lang=spanish", "/api/unknown")
    REFUSED = STILL_REFUSED

    def setUp(self):
        super().setUp()
        self.cfg["public"]["originals"] = True

    @staticmethod
    def peaks(url):
        return "/audio/peaks?src=" + urllib.request.quote(url, safe="")

    def test_originals_and_waveforms_play(self):
        info = self.get("/api/session")
        self.assertEqual((info["permissions"]["audio"], info["permissions"]["download"]), (True, False))
        for path in (*self.MCC, self.CE):
            st, body, headers = self.req("public", path)
            self.assertEqual((st, headers["Content-Type"]), (200, "audio/wav"), path)
            self.assertIn("private", headers["Cache-Control"])
            st, body, headers = self.req("public", path, headers={"Range": "bytes=0-9"})
            self.assertEqual((st, len(body)), (206, 10), path)
        self.assertEqual(len(self.decoded), 6)  # decoded on demand, as for the owner
        self.approve()
        self.publish()
        for src in (*self.MCC, self.CE, self.URL):
            st, body, _ = self.req("public", self.peaks(src))
            self.assertEqual(st, 200, (src, body[:200]))
            self.assertIsInstance(json.loads(body), dict)

    def test_originals_and_editor_previews_stay_private(self):  # replaces the previews-only check
        self.approve()
        self.publish()
        for path in self.STILL_REFUSED:
            self.assertEqual(self.req("public", path)[0], 401, path)
        for path in POSTS:
            self.assertEqual(self.req("public", path, {"slot_id": SLOT})[0], 401, path)
        for path in (*self.MCC, self.CE):
            self.assertEqual(self.req("public", path, method="POST")[0], 401, path)
        self.assertEqual(self.renders[1:], [], "a visitor request rendered audio")  # [0] is the owner's publish

    def test_originals_off_means_none(self):
        self.cfg["public"]["originals"] = False
        for path in (*self.MCC, self.CE, self.peaks(self.MCC[0]), self.peaks(self.CE)):
            self.assertEqual(self.req("public", path)[0], 401, path)
        self.assertFalse(self.get("/api/session")["permissions"]["audio"])
        self.assertEqual(self.decoded, [])

    def test_original_requests_are_rate_limited(self):
        lst = m4_server.Listener("public", self.cfg, 0, limiter=public_view.PublicLimiter(per_minute=2))
        s2 = m4_server.StudioHTTPServer(("127.0.0.1", 0), m4_server.make_handler(self.app, quiet=True, listener=lst))
        threading.Thread(target=s2.serve_forever, daemon=True).start()
        self.servers["limited"] = s2
        self.assertEqual([self.req("limited", p, host=PUBLIC_HOST)[0]
                          for p in (self.MCC[0], self.peaks(self.CE), self.CE)], [200, 200, 429])


class PublicConfigTests(unittest.TestCase):
    def cfg(self, tmp, **public):
        return load_server_config(tmp, overrides={
            "remote": {"enabled": True, "host": "127.0.0.1", "port": 8080, "auth": "cloudflare_access"},
            "public_url": f"https://{ADMIN_HOST}", "cloudflare_access": SETTINGS,
            "public": {"enabled": True, "url": f"https://{PUBLIC_HOST}", **public}})

    def test_settings_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(load_server_config(tmp)["public"]["enabled"])  # off unless asked for
            self.assertEqual(self.cfg(tmp)["public"]["port"], 8081)
            self.assertFalse(self.cfg(tmp)["public"]["previews"])  # silent unless the owner turns it on
            self.assertFalse(self.cfg(tmp)["public"]["originals"])
            self.assertTrue(self.cfg(tmp, originals=True)["public"]["originals"])
            for bad in ({"host": "0.0.0.0"}, {"host": "192.168.1.5"}, {"port": 8080}, {"port": 8765},
                        {"url": "http://studio.example.com"}, {"url": f"https://{ADMIN_HOST}"},
                        {"sign_in_url": "javascript:alert(1)"}, {"surprise": 1}, {"previews": "yes"},
                        {"originals": "yes"}, {"originals": 1}, {"audio": True}):
                with self.assertRaises(ConfigError, msg=bad):
                    self.cfg(tmp, **bad)

    def test_unknown_listener_kind_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                m4_server.Listener("guest", load_server_config(tmp), 0)


class ScrubTests(unittest.TestCase):
    def test_paths_and_keys(self):
        out = public_view.scrub({"a": r"failed: D:\Games\x.fsb and \\server\share\y", "path": "work/x",
                                 "b": ["see /home/me/file", "C:/Users/me", "sound\\dialog\\a10\\a10_350_captkeyes"],
                                 "notes": "x", "nested": {"mcc_folder": "D:\\g"}})
        self.assertEqual(out, {"a": f"failed: {public_view.HIDDEN} and {public_view.HIDDEN}",
                               "b": [f"see {public_view.HIDDEN}", public_view.HIDDEN,
                                     "sound\\dialog\\a10\\a10_350_captkeyes"], "nested": {}})

    def test_every_allowed_get_has_a_route(self):
        # an allowed path without a route would answer 401 instead of the data: keep the list and the code in step
        src = (ROOT / "scripts/ui/m4_server.py").read_text(encoding="utf-8")
        body = src[src.index("def _public_get"):src.index("def _get(")]
        for path in public_view.PUBLIC_GETS:
            self.assertIn(f'"{path}"', body, path)


if __name__ == "__main__":
    unittest.main()
