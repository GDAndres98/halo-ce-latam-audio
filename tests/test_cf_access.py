"""Cloudflare Access mode of the remote listener (docs/deploy-cloudflare.md): the token verifier (signature,
issuer, audience, type, times, accounts), the settings checks, and the real handler behind it (every request
needs a valid token, CSRF on writes, no password sign-in, no game installs, the local listener refuses
proxied requests). Synthetic keys and data; nothing touches the network, the real mappings or the game.

Run: python -m unittest tests.test_cf_access
"""
import base64
import hashlib
import json
import random
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cf_access  # noqa: E402
import m4_server  # noqa: E402
from cf_access import AccessError, AccessVerifier, rsa_pkcs1_sha256_ok  # noqa: E402
from live_feed import LiveFeed  # noqa: E402
from m4_app import M4App  # noqa: E402
from studio_net import ConfigError, load_server_config  # noqa: E402
from test_m4 import make_root, write_wav  # noqa: E402

TEAM = "example-team.cloudflareaccess.com"
AUD = "a" * 64
OWNER = "owner@example.com"


# --------------------------------------------------------------------------- a throw-away RSA key (tests only)
def _probable_prime(bits, rng):
    while True:
        n = rng.getrandbits(bits) | (3 << (bits - 2)) | 1  # top two bits: p*q has exactly 2*bits bits
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and _miller_rabin(n, rng):
            return n


def _miller_rabin(n, rng, rounds=24):
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(rounds):
        x = pow(rng.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def make_key(bits=1024, seed=1):
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = _probable_prime(bits // 2, rng), _probable_prime(bits // 2, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


KEY = make_key()
OTHER_KEY = make_key(seed=2)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(claims, key=KEY, kid="k1", alg="RS256"):
    n, _e, d = key
    head = b64u(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    body = b64u(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    t = cf_access.SHA256_DIGESTINFO + hashlib.sha256(f"{head}.{body}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{head}.{body}.{b64u(sig)}"


def claims(**over):
    now = time.time()
    c = {"aud": [AUD], "email": OWNER, "exp": now + 600, "iat": now - 5, "nbf": now - 5, "iss": f"https://{TEAM}",
         "type": "app", "sub": "user-1"}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


SETTINGS = {"team_domain": TEAM, "aud": [AUD], "users": {OWNER: "admin", "ed@example.com": "editor"}}


def verifier(keys=None, fetch_log=None):
    def fetch():
        if fetch_log is not None:
            fetch_log.append(1)
        return dict(keys) if keys is not None else {"k1": KEY[:2]}
    return AccessVerifier(SETTINGS, fetch=fetch, min_bits=1024)


class VerifierTests(unittest.TestCase):
    def test_valid_token(self):
        self.assertEqual(verifier().verify(sign(claims())), {"email": OWNER, "role": "admin", "sub": "user-1"})
        self.assertEqual(verifier().verify(sign(claims(email="Ed@Example.com")))["role"], "editor")
        self.assertEqual(verifier().verify(sign(claims(aud=AUD)))["email"], OWNER)  # aud as a single string

    def test_refused_tokens(self):
        v = verifier()
        cases = {
            "missing": (None, 401), "garbage": ("a.b", 401), "not json": ("e30.!!!.e30", 401),
            "wrong audience": (sign(claims(aud=["b" * 64])), 401),
            "wrong issuer": (sign(claims(iss="https://evil.cloudflareaccess.com")), 401),
            "meta token": (sign(claims(type="meta")), 401),
            "no type": (sign(claims(type=None)), 401),
            "expired": (sign(claims(exp=time.time() - 120)), 401),
            "not yet valid": (sign(claims(nbf=time.time() + 600)), 401),
            "issued in the future": (sign(claims(iat=time.time() + 600)), 401),
            "no exp": (sign(claims(exp=None)), 401),
            "other key": (sign(claims(), key=OTHER_KEY), 401),
            "unknown kid": (sign(claims(), kid="k9"), 401),
            "HS256": (sign(claims(), alg="HS256"), 401),
            "no email (service token)": (sign(claims(email=None)), 403),
            "not an account": (sign(claims(email="stranger@example.com")), 403),
        }
        for name, (token, status) in cases.items():
            with self.assertRaises(AccessError, msg=name) as cm:
                v.verify(token)
            self.assertEqual(cm.exception.status, status, name)
        good = sign(claims())
        head, body, sig = good.split(".")
        tampered = b64u(json.dumps(claims(email="ed@example.com")).encode())
        with self.assertRaises(AccessError):
            v.verify(f"{head}.{tampered}.{sig}")
        with self.assertRaises(AccessError):  # alg "none", no signature
            v.verify(f"{b64u(json.dumps({'alg': 'none', 'kid': 'k1'}).encode())}.{body}.")

    def test_rsa_rejects_short_keys_and_bad_lengths(self):
        n, e, _ = KEY
        msg, token = b"x", sign(claims())
        sig = cf_access.b64url(token.split(".")[2])
        msg = ".".join(token.split(".")[:2]).encode()
        self.assertTrue(rsa_pkcs1_sha256_ok(n, e, msg, sig, min_bits=1024))
        self.assertFalse(rsa_pkcs1_sha256_ok(n, e, msg, sig))  # 1024 bits < the 2048 minimum in production
        self.assertFalse(rsa_pkcs1_sha256_ok(n, e, msg, sig[1:], min_bits=1024))
        self.assertFalse(rsa_pkcs1_sha256_ok(n, e, msg + b"!", sig, min_bits=1024))

    def test_unknown_key_fetches_again_but_rate_limited(self):
        log = []
        keys = {"k1": KEY[:2]}
        v = verifier(keys, log)
        v.verify(sign(claims()))
        self.assertEqual(len(log), 1)
        keys["k2"] = OTHER_KEY[:2]  # rotated: a new key id appears
        with self.assertRaises(AccessError):
            v.verify(sign(claims(), key=OTHER_KEY, kid="k2"))  # within REFETCH_MIN_S: no new fetch
        self.assertEqual(len(log), 1)
        v._tried_at -= cf_access.REFETCH_MIN_S
        self.assertEqual(v.verify(sign(claims(), key=OTHER_KEY, kid="k2"))["email"], OWNER)
        self.assertEqual(len(log), 2)

    def test_fetch_failure_fails_closed(self):
        def broken():
            raise OSError("offline")
        v = AccessVerifier(SETTINGS, fetch=broken, min_bits=1024)
        with self.assertRaises(AccessError) as cm:
            v.verify(sign(claims()))
        self.assertEqual(cm.exception.status, 503)

    def test_settings_are_checked(self):
        bad = [dict(SETTINGS, team_domain="evil.example.com"), dict(SETTINGS, aud=[]), dict(SETTINGS, aud=["x"]),
               dict(SETTINGS, users={}), dict(SETTINGS, users={OWNER: "root"}),
               dict(SETTINGS, users={"Owner@Example.com": "admin"})]
        for ca in bad:
            with self.assertRaises(ValueError, msg=ca):
                cf_access.check_settings(ca)


class ConfigTests(unittest.TestCase):
    def cfg(self, tmp, **remote):
        return load_server_config(tmp, overrides={
            "remote": {"enabled": True, "host": "127.0.0.1", "port": 8080, "auth": "cloudflare_access", **remote},
            "public_url": "https://studio.example.com", "cloudflare_access": SETTINGS})

    def test_cloudflare_mode_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self.cfg(tmp)
            self.assertEqual(cfg["cloudflare_access"]["users"][OWNER], "admin")
            with self.assertRaises(ConfigError):
                self.cfg(tmp, host="0.0.0.0")  # reachable from the LAN: refused
            with self.assertRaises(ConfigError):
                self.cfg(tmp, auth="magic")
            with self.assertRaises(ConfigError):
                load_server_config(tmp, overrides={"remote": {"enabled": True, "host": "127.0.0.1",
                                                              "auth": "cloudflare_access"},
                                                   "public_url": "https://studio.example.com"})  # no AUD, no users
            with self.assertRaises(ConfigError):
                load_server_config(tmp, overrides={"remote": {"enabled": True, "host": "127.0.0.1",
                                                              "auth": "cloudflare_access"},
                                                   "cloudflare_access": SETTINGS})  # no https public_url


class CloudflareListenerTests(unittest.TestCase):
    """The real handler: a Cloudflare Access remote listener and the local listener, on ephemeral ports."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        clip = self.root / "work/clip.wav"
        write_wav(clip)

        class StubAudio:
            def wav(self, *_a):
                return clip
        self.app = M4App(self.root, today=lambda: "2026-10-14", run_validator=False, mcc_audio=StubAudio(),
                         ce_audio=StubAudio())
        dist = self.root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
        (dist / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
        cfg = load_server_config(self.root, overrides={
            "remote": {"enabled": True, "host": "127.0.0.1", "port": 1, "auth": "cloudflare_access"},
            "public_url": "https://studio.example.com", "cloudflare_access": SETTINGS,
            "static_dir": str(dist), "sessions_file": "work/studio/s.sqlite"})
        self.feed = LiveFeed(self.root / "mappings/manual_mappings.db", interval_s=0.05)
        self.feed.start()
        shared = m4_server.Shared(self.root, cfg, self.feed)
        key = m4_server._access_csrf_key(self.root / "work/studio")
        self.servers = {}
        for kind in ("local", "remote"):
            lst = m4_server.Listener(kind, cfg, 0, access=verifier() if kind == "remote" else None, csrf_key=key)
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

    def req(self, kind, path, body=None, headers=None, token=None, host="studio.example.com"):
        base = f"http://127.0.0.1:{self.servers[kind].server_address[1]}"
        h = {"Host": host, **({"Content-Type": "application/json"} if body is not None else {})}
        if token:
            h[cf_access.HEADER] = token
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(base + path, data=data, headers={**h, **(headers or {})})
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(r, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_everything_needs_a_valid_access_token(self):
        for path in ("/", "/index.html", "/assets/app-1234.js", "/api/session", "/api/state", "/api/slots?level=z10",
                     "/audio/mcc?level=z10&lang=spanish&index=0", "/api/events", "/manifest.webmanifest"):
            self.assertEqual(self.req("remote", path)[0], 401, path)
            self.assertEqual(self.req("remote", path, token=sign(claims(aud=["b" * 64])))[0], 401, path)
        self.assertEqual(self.req("remote", "/api/state", token=sign(claims(email="x@example.com")))[0], 403)
        self.assertEqual(self.req("remote", "/api/save", {"slot_id": "x"})[0], 401)
        # forged studio cookies or headers do not stand in for the token
        self.assertEqual(self.req("remote", "/api/state", headers={"Cookie": "studio_session=x",
                                                                   "Cf-Access-Authenticated-User-Email": OWNER})[0], 401)

    def test_signed_in_owner_uses_the_studio(self):
        tok = sign(claims())
        self.assertEqual(self.req("remote", "/", token=tok)[0], 200)
        self.assertEqual(self.req("remote", "/assets/app-1234.js", token=tok)[0], 200)
        st, body, _ = self.req("remote", "/api/session", token=tok)
        info = json.loads(body)
        self.assertEqual((st, info["authenticated"], info["user"], info["role"], info["sso"]),
                         (200, True, OWNER, "admin", "cloudflare_access"))
        self.assertFalse(info["permissions"]["install"])
        st, body, _ = self.req("remote", "/audio/mcc?level=z10&lang=spanish&index=0", token=tok,
                               headers={"Range": "bytes=0-9"})
        self.assertEqual((st, len(body)), (206, 10))
        st, body, _ = self.req("remote", "/api/slot?id=es%3AZ10_010_keyes%230", token=tok)
        version = json.loads(body)["sha256"]["slot"]
        save = {"slot_id": "es:Z10_010_keyes#0", "loaded_slot_sha256": version, "notes": "from the phone"}
        self.assertEqual(self.req("remote", "/api/save", save, token=tok)[0], 403)  # no CSRF token
        st, body, _ = self.req("remote", "/api/save", save, token=tok, headers={"X-Studio-CSRF": info["csrf"]})
        self.assertEqual(st, 200, body)
        st, body, _ = self.req("remote", "/api/save", {**save, "notes": "x"}, token=tok,
                               headers={"X-Studio-CSRF": info["csrf"], "Origin": "https://evil.example"})
        self.assertEqual(st, 403)
        # an editor's CSRF token is not the owner's
        ed = json.loads(self.req("remote", "/api/session", token=sign(claims(email="ed@example.com")))[1])
        self.assertNotEqual(ed["csrf"], info["csrf"])
        self.assertEqual(self.req("remote", "/api/data/export", {"confirm": True}, token=sign(
            claims(email="ed@example.com")), headers={"X-Studio-CSRF": ed["csrf"]})[0], 403)  # admin only
        audit = (self.root / "work/studio/audit.jsonl").read_text(encoding="utf-8")
        self.assertIn(OWNER, audit)

    def test_no_password_sign_in_and_no_game_installs(self):
        tok = sign(claims())
        csrf = json.loads(self.req("remote", "/api/session", token=tok)[1])["csrf"]
        self.assertEqual(self.req("remote", "/api/login", {"username": "a", "password": "b"}, token=tok)[0], 404)
        for path in ("/api/deploy/install", "/api/deploy/restore", "/api/settings/mcc"):
            self.assertEqual(self.req("remote", path, {"build": "a10"}, token=tok,
                                      headers={"X-Studio-CSRF": csrf})[0], 403, path)
        self.assertEqual(self.req("remote", "/classic", token=tok)[0], 404)
        st, body, _ = self.req("remote", "/api/logout", {}, token=tok, headers={"X-Studio-CSRF": csrf})
        self.assertEqual(json.loads(body)["logout_url"], "/cdn-cgi/access/logout")
        st, _, headers = self.req("remote", "/api/sso/continue", token=tok)
        self.assertEqual((st, headers["Location"]), (302, "/#/match"))

    def test_bad_host_and_traversal(self):
        tok = sign(claims())
        self.assertEqual(self.req("remote", "/api/state", token=tok, host="evil.example")[0], 403)
        for path in ("/../config/studio_server.json", "/%2e%2e/mappings/manual_mappings.db", "/assets/..%5c..%5cx"):
            self.assertIn(self.req("remote", path, token=tok)[0], (400, 404), path)

    def test_local_listener_refuses_tunnel_requests(self):
        tok = sign(claims())
        for h in ({cf_access.HEADER: tok}, {"Cf-Connecting-Ip": "203.0.113.9"}, {"Cf-Ray": "abc"}):
            st, _, _ = self.req("local", "/api/state", headers=h, host="localhost")
            self.assertEqual(st, 403, h)
        self.assertEqual(self.req("local", "/api/state", host="localhost")[0], 200)
        self.assertEqual(self.req("local", "/api/state")[0], 403)  # the public name is not the local listener's


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


if __name__ == "__main__":
    unittest.main()
