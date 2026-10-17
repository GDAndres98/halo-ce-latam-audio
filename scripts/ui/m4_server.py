"""Localization Studio server: the JSON API, the audio, and the built Studio page (stdlib http.server).

    python scripts/ui/m4_server.py                 # this computer only: http://127.0.0.1:8765
    python scripts/ui/m4_server.py --lan           # also other computers (sign-in required), port 8766
    python scripts/ui/m4_server.py --port 8770 --no-open

Two listeners share one application and one decisions database (docs/remote-access.md):

- **local** (127.0.0.1:8765, loopback only): the host computer's own Studio. No sign-in; the only address
  that may install into or restore the game, or change the MCC folder.
- **remote** (off by default; `--lan`, or "remote": {"enabled": true} in config/studio_server.json): for
  other computers on the LAN or through Tailscale. Every API and audio request needs a signed-in account
  (scripts/ui/studio_users.py); writes need the session's CSRF token. Game installs are refused whatever the
  role; builds, the level setting and data import/export need the admin role.
  With "remote": {"auth": "cloudflare_access"} the remote listener sits behind a Cloudflare Tunnel: every
  request, the page's own files included, must carry a Cloudflare Access token that this server verifies
  (cf_access.py; docs/deploy-cloudflare.md). There is no password sign-in on it then.
- **public** (off by default; `--public`, or "public": {"enabled": true}): a read-only view for anonymous
  visitors through a tunnel on this computer (docs/public-access.md). No identity is read at all; only the
  allowlisted, sanitised metadata of public_view.py is served. No writes, no audio, no downloads.

Stop a running server cleanly: python scripts/ui/m4_server.py --stop (or scripts/deploy/studio.ps1 stop).

The built Studio (frontend/dist, `npm run build`) is served at / on both; the classic page is at /classic on
the local listener only. Never matches anything by itself. Saves only through mapping_store, and decodes
audio on demand into work/ with the approved vgmstream-cli. Design: docs/m4-matching-ui-design.md.

API (all JSON unless noted):
    GET  /api/session                             who is signed in, role, permissions, CSRF token
    POST /api/login                               {username, password} (remote listener)
    POST /api/logout
    GET  /api/sso/continue                        Cloudflare Access mode: back to the Studio after signing in
    GET  /api/events                             Server-Sent Events: decisions changed (any client, any tool)
    GET  /api/network                             listeners and the addresses to connect from another computer
    GET  /api/state                               levels + progress, CE missions, file hashes
    GET  /api/slots?level=a10|all&status=&q=      slot list (status: undecided|matched|no_equivalent|
                                                  deferred|needs_rework|audio_pending|subtitle_pending|
                                                  radio|fits|edited|stereo); q: words and "quoted phrases"
    GET  /api/slot?id=<slot_id>                   slot detail, SU/SP text, decision, verifications
    GET  /api/ce?mission=all|mapped|M01&level=&q=&subs=missing|present&hide_used=1&keep_slot=&offset=&limit=
                                                  CE lines in catalog order, filtered by q only
    GET  /api/ce_line?ref=<ce_line_ref>
    GET  /audio/mcc?level=&lang=spanish|english&index=     WAV (decoded on demand; Range requests)
    GET  /audio/ce?ref=&lang=Spanish(Mexico)|English(US)|Spanish(Spain)&k=0
    GET  /audio/preview?key=&kind=edited|encoded  a rendered editor preview (WAV, immutable)
    GET  /audio/peaks?src=<one of the audio URLs above>    waveform peaks (JSON)
    POST /api/edit/preview                        {slot_id, ce_line_ref, language, edit} -> render as M6
                                                  would; writes only work/m4/preview/, never mappings
    POST /api/save                                see M4App.save; 409 = stale or protected
    POST /api/progress                            {level, status, note, verification, confirm, loaded_sha256}
    POST /api/validate                            run the read-only validator
    GET  /api/data/status                         manual_mappings.json vs the database
    POST /api/data/import/preview | /api/data/import | /api/data/export          (admin)
    POST /api/builds/start | /api/builds/preview  (start: admin)
    GET  /api/builds, /api/builds/detail?name=, /api/builds/log?name=, /api/job?id=
    GET  /api/deploy/status | /api/deploy/plan?build= | /api/deploy/history
    POST /api/deploy/install | /api/deploy/restore | /api/settings/mcc          (local listener only)
    GET|POST /api/settings/export                 the build level setting (POST: admin)
"""
import argparse
import datetime as dt
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import queue
import secrets
import shutil
import socket
import ssl
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.celt011 import DEFAULT_DLL, Celt011  # noqa: E402
from common.edit_preview import EditPreview  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.ondemand_audio import CeAudio, MccAudio, ce_source_reader, vgmstream_decoder  # noqa: E402
from common.wav_peaks import PeakCache  # noqa: E402
from build_api import BuildBoard  # noqa: E402
from common.export_config import ConfigError, load_export_config, save_global_gain  # noqa: E402
from live_feed import LiveFeed  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from cf_access import HEADER as ACCESS_HEADER, AccessError, AccessVerifier  # noqa: E402
from public_previews import PreviewStore  # noqa: E402
from public_view import (PUBLIC_GETS as PUBLIC_LISTENER_GETS, PUBLIC_PREVIEW, Limited, PublicLimiter,  # noqa: E402
                         sanitize)
from studio_auth import AuthError, Authenticator, SessionStore, UserStore, csrf_ok  # noqa: E402
from studio_net import ConfigError as NetConfigError, HostPolicy, connection_info, load_server_config  # noqa: E402

HOST = "127.0.0.1"
PAGE = Path(__file__).resolve().parent / "m4.html"
DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")
MAX_BODY = 1 << 20
COOKIE = "studio_session"
GZIP_MIN = 1400
CHUNK = 64 * 1024

# What each kind of request needs. Everything not listed needs a signed-in account (any role) on the remote
# listener. "local" = only the host computer's own listener, whatever the account.
ADMIN_POSTS = {"/api/settings/export", "/api/builds/start", "/api/builds/dry-run", "/api/data/import/preview",
               "/api/data/import", "/api/data/export"}
LOCAL_ONLY_POSTS = {"/api/deploy/install", "/api/deploy/restore", "/api/settings/mcc"}
PUBLIC_GETS = {"/api/session"}
PUBLIC_POSTS = {"/api/login", "/api/logout"}

# Content types for the built Studio (the Windows registry can map .js to text/plain).
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
                ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".webp": "image/webp",
                ".txt": "text/plain; charset=utf-8", ".map": "application/json",
                ".webmanifest": "application/manifest+json"}  # the installable app's manifest (docs/mobile.md)
COMPRESSIBLE = ("application/json", "text/", "image/svg+xml")
# The built page only loads its own files (fonts and scripts are bundled); media may be a blob URL (WaveSurfer).
STUDIO_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
              "media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
              "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
AUDIO_PATHS = ("/audio/mcc", "/audio/ce", "/audio/preview")
ACCESS_LOGOUT = "/cdn-cgi/access/logout"  # Cloudflare Access ends its own session at this path of the app's host
# Headers a proxy adds. The trusted local listener refuses requests that carry any of them.
PROXY_HEADERS = ("X-Forwarded-For", "Forwarded", "X-Forwarded-Host", "Tailscale-User-Login", "Cf-Connecting-Ip",
                 "Cf-Ray", ACCESS_HEADER)
STOP_FILE = "server.stop"  # in the state folder (work/studio/): its appearance shuts the server down cleanly


class Listener:
    """What one listening address allows. kind "local": the host's own trusted address; "remote": sign-in;
    "public": anonymous, read-only (public_view.py)."""

    def __init__(self, kind, cfg, port, auth=None, secure_tls=False, access=None, csrf_key=None, limiter=None):
        if kind not in ("local", "remote", "public"):
            raise ValueError(f"unknown listener kind {kind!r}")
        self.kind, self.cfg, self.port, self.auth, self.tls = kind, cfg, port, auth, secure_tls
        self.access, self.csrf_key = access, csrf_key  # Cloudflare Access mode: the verifier and the CSRF key
        self.limiter = limiter or (PublicLimiter() if kind == "public" else None)
        self.policy = HostPolicy(cfg, kind, port)

    @property
    def remote(self):
        """Not the host's own trusted address. The public listener counts as remote too, so it can never get the
        local listener's trust by accident."""
        return self.kind != "local"

    @property
    def public(self):
        return self.kind == "public"

    @property
    def public_previews(self):
        """The owner let visitors play the published edited previews of approved lines ("previews": true)."""
        return self.public and self.cfg["public"].get("previews") is True

    @property
    def sign_in_url(self):
        """Where a visitor signs in to edit (the Cloudflare Access protected address)."""
        return self.cfg["public"].get("sign_in_url") or self.cfg.get("public_url")


class Shared:
    """State shared by every listener: the feed, peaks, the audit log, the network description."""

    def __init__(self, root, cfg, feed=None):
        self.root, self.cfg = Path(root), cfg
        self.feed = feed
        self.peaks = PeakCache()
        self.remote_running = False
        self._audit_lock = threading.Lock()
        self._static_gz = {}
        self.users = self.sessions = None  # set when the remote listener runs

    def audit(self, entry):
        """audit_file (work/studio/audit.jsonl): one line per write request (who, from where, what, result).
        Append only."""
        p = Path(self.cfg["audit_path"])
        line = json.dumps(dict(entry, at=dt.datetime.now().isoformat(timespec="seconds")), ensure_ascii=False)
        with self._audit_lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def make_handler(app, quiet=False, builds=None, listener=None, shared=None):
    builds = builds or BuildBoard(app.root, lambda: set(app.levels), app=app)
    if listener is None:  # tests and the original single-listener use: the trusted local listener
        cfg = load_server_config(app.root, overrides={})
        listener = Listener("local", cfg, cfg["local"]["port"])
    shared = shared or Shared(app.root, listener.cfg)
    static_dir = listener.cfg.get("static_path")
    previews = PreviewStore(app.root)  # published previews of approved lines (public view only)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Studio/2"
        protocol_version = "HTTP/1.1"  # keep-alive: one connection carries many requests (remote latency)
        timeout = 120  # an idle or stalled connection is closed (keeps threads from piling up)

        def log_message(self, fmt, *args):  # one line per error response only
            if not quiet and len(args) > 1 and str(getattr(args[1], "value", args[1])).startswith(("4", "5")):
                sys.stderr.write("%s %s %s\n" % (listener.kind, self.command, fmt % args))

        # ------------------------------------------------------------ responses
        def _accepts_gzip(self):
            return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

        def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
            extra = dict(extra or {})
            if (len(body) >= GZIP_MIN and ctype.startswith(COMPRESSIBLE) and self._accepts_gzip()
                    and "Content-Encoding" not in extra):
                body = gzip.compress(body, compresslevel=5)
                extra["Content-Encoding"] = "gzip"
                extra["Vary"] = "Accept-Encoding"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", extra.pop("Cache-Control", "no-store"))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in extra.items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, obj, extra=None):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), extra=extra)

        def _wav(self, path, immutable=False):
            """A WAV with ETag revalidation and single byte-range requests (seeking while streaming)."""
            path = Path(path)
            st = path.stat()
            size = st.st_size
            etag = f'"{size:x}-{st.st_mtime_ns:x}"'
            # Previews are content-addressed (the key is a hash of what they were rendered from): they never
            # change. Decoded clips come from pinned banks; the browser keeps them briefly, then revalidates.
            cache = {"Cache-Control": "private, max-age=31536000, immutable" if immutable else "private, max-age=600",
                     "ETag": etag, "Accept-Ranges": "bytes"}
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, b"", "audio/wav", cache)
            start, end = 0, size - 1
            status = 200
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes=") and "," not in rng and self.headers.get("If-Range", etag) == etag:
                a, _, b = rng[6:].strip().partition("-")
                try:
                    if a == "":  # suffix: the last b bytes
                        start, end = max(0, size - int(b)), size - 1
                    else:
                        start, end = int(a), min(int(b) if b else size - 1, size - 1)
                except ValueError:
                    start, end = 0, size - 1
                else:
                    if start > end or start >= size:
                        return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                    status = 206
                    cache["Content-Range"] = f"bytes {start}-{end}/{size}"
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in cache.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def _static(self, rel):
            """A file of the built Studio. Only files inside static_dir; hashed assets are immutable."""
            if not static_dir or not (static_dir / "index.html").is_file():
                return False
            rel = unquote(rel).lstrip("/") or "index.html"
            if "\\" in rel or "\x00" in rel or any(part in ("", ".", "..") for part in rel.split("/")):
                raise ApiError(404, "not found")
            base = static_dir.resolve()
            p = (base / rel).resolve()
            if not p.is_relative_to(base) or not p.is_file():
                return False
            ctype = STATIC_TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            st = p.stat()
            key = (str(p), st.st_mtime_ns, st.st_size)
            extra = {"Cache-Control": "public, max-age=31536000, immutable" if rel.startswith("assets/")
                     else "no-cache"}
            if p.name == "index.html":
                extra["Content-Security-Policy"] = STUDIO_CSP
            etag = f'"{st.st_size:x}-{st.st_mtime_ns:x}"'
            extra["ETag"] = etag
            if self.headers.get("If-None-Match") == etag:
                self._send(304, b"", ctype, extra)
                return True
            data = p.read_bytes()
            if ctype.startswith(COMPRESSIBLE) and len(data) >= GZIP_MIN and self._accepts_gzip():
                gz = shared._static_gz.get(key)
                if gz is None:
                    gz = shared._static_gz[key] = gzip.compress(data, compresslevel=9)
                extra.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
                data = gz
            self._send(200, data, ctype, extra)
            return True

        # ------------------------------------------------------------ who is asking
        def _peer(self):
            ip = self.client_address[0]
            cf = self.headers.get("Cf-Connecting-Ip")
            if (listener.access or listener.public) and cf and ip in ("127.0.0.1", "::1"):  # cloudflared, here
                return cf.strip()[:64]
            fwd = self.headers.get("X-Forwarded-For")
            if fwd and ip in ("127.0.0.1", "::1"):  # a proxy on this computer (tailscale serve) names the client
                return fwd.split(",")[0].strip()[:64]
            return ip

        def _https(self):
            if listener.tls:
                return True
            return (self.client_address[0] in ("127.0.0.1", "::1")
                    and (self.headers.get("X-Forwarded-Proto") or "").lower() == "https")

        def _cookie_token(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    return v
            return None

        def _session(self):
            if listener.public:
                return None  # anonymous by construction: no cookie, token or header is ever read here
            if not listener.remote:
                return {"username": "host", "role": "admin", "csrf": None, "local": True}
            if listener.access:  # verified in _guard on every request
                who = self._access_identity
                csrf = hmac.new(listener.csrf_key, f"csrf|{who['email']}".encode(), hashlib.sha256).hexdigest()
                return {"username": who["email"], "role": who["role"], "csrf": csrf, "local": False}
            s = listener.auth.session(self._cookie_token())
            return dict(s, local=False) if s else None

        def _set_cookie(self, token, max_age):
            secure = listener.cfg["secure_cookies"]
            secure = self._https() if secure == "auto" else bool(secure)
            return (f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
                    + ("; Secure" if secure else ""))

        def _permissions(self, s):
            local = not listener.remote
            # audio: stream recordings, waveforms and editor previews; download: save them as files.
            return {"edit": bool(s), "admin": bool(s) and (local or s["role"] == "admin"),
                    "install": local, "settings_mcc": local, "audio": bool(s), "download": bool(s),
                    "previews": listener.public_previews}  # published previews of approved lines (public view)

        def _session_info(self, s):
            if listener.public:
                return {"listener": "public", "auth_required": False, "authenticated": False, "visitor": True,
                        "user": None, "role": None, "csrf": None, "local_admin": False, "https": self._https(),
                        "sso": None, "logout_url": None, "sign_in_url": listener.sign_in_url,
                        "permissions": self._permissions(None)}
            return {"listener": listener.kind, "visitor": False, "auth_required": listener.remote, "authenticated": bool(s),
                    "user": s and s["username"], "role": s and s["role"], "csrf": s and s.get("csrf"),
                    "local_admin": not listener.remote, "https": self._https(),
                    "sso": "cloudflare_access" if listener.access else None,
                    "logout_url": ACCESS_LOGOUT if listener.access else None,
                    "permissions": self._permissions(s)}

        # ------------------------------------------------------------ checks
        def _guard(self, path):
            """Host and Origin of every request (DNS rebinding and cross-site requests)."""
            if not listener.policy.host_ok(self.headers.get("Host")):
                raise ApiError(403, "bad Host header (add the name to allowed_hosts in config/studio_server.json)")
            if not listener.policy.origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
                raise ApiError(403, "cross-origin request refused")
            if not listener.remote:
                # The trusted local listener must not be reached through a proxy (that would make a remote
                # visitor look local): forwarded requests are refused here; proxies belong on the remote port.
                for h in PROXY_HEADERS:
                    if self.headers.get(h):
                        raise ApiError(403, "the local administrator address does not accept proxied requests; "
                                            "point the proxy at the remote listener's port")
            elif listener.access:
                # Behind Cloudflare Access: every request, static files included, needs a valid Access token.
                # Fail closed: no token, a bad one, or one for an account not in the settings is refused.
                try:
                    self._access_identity = listener.access.verify(self.headers.get(ACCESS_HEADER))
                except AccessError as e:
                    raise ApiError(e.status, e.message)

        def _authorize(self, path, s):
            if self.command in ("GET", "HEAD"):
                if path in PUBLIC_GETS or not (path.startswith("/api/") or path.startswith("/audio/")):
                    return
            elif path in PUBLIC_POSTS:
                if listener.access and path == "/api/login":
                    raise ApiError(404, "sign-in is through Cloudflare Access on this address")
                return
            if not s:
                raise ApiError(401, "sign in first")
            if self.command == "POST":
                if path in LOCAL_ONLY_POSTS and listener.remote:
                    raise ApiError(403, "installing into or restoring the game, and changing the MCC folder, are "
                                        "only possible on the host computer's own Studio (http://127.0.0.1:"
                                        f"{listener.cfg['local']['port']}/)")
                if listener.remote and not csrf_ok(s, self.headers.get("X-Studio-CSRF")):
                    raise ApiError(403, "missing or wrong CSRF token; reload the page")
                if path in ADMIN_POSTS and not self._permissions(s)["admin"]:
                    raise ApiError(403, "this needs an admin account")

        def _body(self):
            if (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
                raise ApiError(415, "JSON body required")
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY or n < 0:
                raise ApiError(413, "body too large")
            try:
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except ValueError:
                raise ApiError(400, "invalid JSON")

        # ------------------------------------------------------------ audio
        def _audio_path(self, path, q):
            """The file behind one of the audio URLs. Only catalog entries and preview keys: never a path."""
            if listener.public:  # defence in depth: the public route never gets here
                raise self._visitor_refused("Recordings need the owner's sign-in")
            if path == "/audio/mcc":
                return app.mcc_wav(q.get("level", ""), q.get("lang", ""), q.get("index", -1)), False
            if path == "/audio/ce":
                return app.ce_wav(q.get("ref", ""), q.get("lang", ""), q.get("k", 0)), False
            if path == "/audio/preview":
                return app.preview_wav(q.get("key", ""), q.get("kind", "")), True
            raise ApiError(404, "not an audio URL")

        def _peaks(self, q):
            src = urlparse(q.get("src", ""))
            if src.scheme or src.netloc or src.path not in AUDIO_PATHS:
                raise ApiError(400, "src must be one of the Studio's audio URLs")
            inner = {k: v[0] for k, v in parse_qs(src.query).items()}
            wav, immutable = self._audio_path(src.path, inner)
            per_second = max(50, min(2000, int(q.get("per_second", 400))))
            data = shared.peaks.get(wav, per_second)
            st = Path(wav).stat()
            etag = f'"p{per_second:x}-{st.st_size:x}-{st.st_mtime_ns:x}"'
            extra = {"ETag": etag,
                     "Cache-Control": "private, max-age=31536000, immutable" if immutable else "private, max-age=600"}
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, b"", "application/json", extra)
            self._json(200, data, extra)

        # ------------------------------------------------------------ events
        def _events(self, s):
            if listener.public or not s:  # the feed names who saved: never anonymous
                raise self._visitor_refused("Live updates need the owner's sign-in")
            if not shared.feed:
                raise ApiError(503, "change notifications are not running")
            self.close_connection = True
            q = shared.feed.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                hello = {"type": "hello", "seq": shared.feed.seq, "user": s["username"]}
                self.wfile.write(f"retry: 3000\nevent: hello\ndata: {json.dumps(hello)}\n\n".encode())
                self.wfile.flush()
                token = self._cookie_token()
                access_token = self.headers.get(ACCESS_HEADER)
                while True:
                    try:
                        ev = q.get(timeout=20)
                        self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                    except queue.Empty:
                        if listener.access:
                            try:
                                listener.access.verify(access_token)
                            except AccessError:
                                return  # the Access sign-in expired: the page reconnects through Access
                        elif listener.remote and not listener.auth.session(token):
                            return  # signed out or expired: the page sees the 401 on its next request
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except OSError:
                pass  # the page closed
            finally:
                shared.feed.unsubscribe(q)

        # ------------------------------------------------------------ routing
        def _route(self):
            u = urlparse(self.path)
            path = u.path
            self._guard(path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if listener.public:
                return self._public_route(path, q)
            s = self._session()
            self._authorize(path, s)
            if self.command in ("GET", "HEAD"):
                return self._get(path, q, s)
            if self.command == "POST":
                body = self._body()
                status = 500
                try:
                    status, obj, extra = self._post(path, body, s)
                    self._json(status, obj, extra)
                except ApiError as e:
                    status = e.status
                    raise
                finally:
                    if path not in ("/api/edit/preview", "/api/builds/preview", "/api/data/import/preview"):
                        entry = {"listener": listener.kind, "user": (s or {}).get("username"),
                                 "from": self._peer(), "path": path, "status": status}
                        if path == "/api/save":
                            entry.update(slot_id=body.get("slot_id"), actions=body.get("actions") or [])
                        if path == "/api/login":
                            entry["user"] = str(body.get("username") or "")[:40]
                        shared.audit(entry)
                return
            raise ApiError(405, "method not allowed")

        # ------------------------------------------------------------ the public read-only listener
        def _stored_mapping(self, slot_id):
            """The line's saved decision (None if it has none); unknown slots are 404."""
            if slot_id not in app.slot_index:
                raise ApiError(404, "unknown line")
            return next((m for m in app._mappings()[0]["slots"] if m["slot_id"] == slot_id), None)

        def _visitor_refused(self, what="This public view is read-only"):
            url = listener.sign_in_url
            return ApiError(401, f"{what}. Sign in to edit" + (f" at {url}." if url else "."))

        def _public_route(self, path, q):
            """Anonymous visitors: an allowlist of GETs (public_view.PUBLIC_GETS), each answer sanitised, and the
            built page. Everything else is refused before any work is done (fail closed)."""
            if self.command not in ("GET", "HEAD"):
                raise self._visitor_refused()
            if path == PUBLIC_PREVIEW:
                if not listener.public_previews:
                    raise self._visitor_refused("Previews are not published in this view")
                try:
                    listener.limiter.admit(self._peer())
                    with listener.limiter.slot():  # a lookup only: nothing is ever rendered for a visitor
                        sid = q.get("slot", "")
                        wav, why = previews.lookup(sid, self._stored_mapping(sid))
                except Limited as e:
                    return self._json(e.status, {"error": e.message}, {"Retry-After": str(e.retry_after or 5)})
                if wav is None:
                    raise ApiError(404, f"No public preview: {why}.")
                return self._wav(wav)
            if path.startswith(("/api/", "/audio/")):
                if path not in PUBLIC_LISTENER_GETS:
                    raise self._visitor_refused("Recordings and downloads need the owner's sign-in"
                                                if path.startswith("/audio/") else "Not available in the public view")
                try:
                    listener.limiter.admit(self._peer())
                    with listener.limiter.slot():
                        obj = self._public_get(path, q)
                except Limited as e:
                    return self._json(e.status, {"error": e.message}, {"Retry-After": str(e.retry_after or 5)})
                return self._json(200, sanitize(path, obj))
            if path == "/classic":
                raise ApiError(404, "not found")
            if not self._has_studio():
                return self._send(200, NO_BUILD_PAGE, "text/html; charset=utf-8")
            if self._static(path):
                return
            raise ApiError(404, "not found")

        def _public_get(self, path, q):
            if path == "/api/session":
                return self._session_info(None)
            if path == "/api/state":
                return app.state()
            if path == "/api/slots":
                return app.slots(q.get("level", ""), q.get("status") or None, q.get("q"))
            if path == "/api/slot":
                d = app.slot(q.get("id", ""), with_interference=False)  # no on-demand audio decoding
                if listener.public_previews:
                    d["public_preview"] = previews.status(d["slot_id"], d["mapping"])
                return d
            if path == "/api/ce":
                return app.ce(q.get("mission", "all"), q.get("q"), q.get("offset", 0), q.get("limit", 100),
                              q.get("level"), q.get("subs") or None, q.get("hide_used") == "1",
                              q.get("keep_slot") or None)
            if path == "/api/ce_line":
                return app.ce_line(q.get("ref", ""))
            if path == "/api/builds":
                return builds.list_builds()
            if path == "/api/builds/detail":
                return builds.build_detail(q.get("name", ""))
            if path == "/api/deploy/history":
                return builds.history()
            raise self._visitor_refused("Not available in the public view")

        def _get(self, path, q, s):
            if path == "/classic" or (path in ("/", "/index.html") and not self._has_studio()):
                # The classic page sends no CSRF token: it stays on the host's own address.
                if not listener.remote:
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if path == "/classic":
                    raise ApiError(404, "not found")
                return self._send(200, NO_BUILD_PAGE, "text/html; charset=utf-8")
            if path == "/api/session":
                return self._json(200, self._session_info(s))
            if path == "/api/sso/continue" and listener.access:
                # Opened as a page after Cloudflare Access signed the visitor in again; a fixed target only.
                return self._send(302, b"", "text/plain", {"Location": "/#/match"})
            if path == "/api/events":
                return self._events(s)
            if path == "/api/network":
                info = connection_info(listener.cfg, shared.remote_running)
                info.update(this_listener=listener.kind, https=self._https(), remote_users=None, signed_in=None)
                if listener.access and self._permissions(s)["admin"]:
                    info["remote_users"] = sorted(f"{k} ({v})" for k, v in listener.access.users.items())
                elif shared.sessions and self._permissions(s)["admin"]:  # who can sign in and who is: admins only
                    info["remote_users"] = sorted(f"{k} ({v['role']})" for k, v in shared.users.users().items())
                    info["signed_in"] = [{"user": x["username"], "from": x["address"], "last_seen": x["last_seen"]}
                                         for x in shared.sessions.active()]
                return self._json(200, info)
            if path == "/api/state":
                return self._json(200, app.state())
            if path == "/api/slots":
                return self._json(200, app.slots(q.get("level", ""), q.get("status") or None, q.get("q")))
            if path == "/api/slot":
                return self._json(200, app.slot(q.get("id", "")))
            if path == "/api/ce":
                return self._json(200, app.ce(q.get("mission", "all"), q.get("q"), q.get("offset", 0),
                                              q.get("limit", 100), q.get("level"), q.get("subs") or None,
                                              q.get("hide_used") == "1", q.get("keep_slot") or None))
            if path == "/api/interference/reference":
                return self._json(200, app.interference_reference(q.get("slot", ""), q.get("lang", "spanish")))
            if path == "/api/ce_line":
                return self._json(200, app.ce_line(q.get("ref", "")))
            if path in AUDIO_PATHS:
                wav, immutable = self._audio_path(path, q)
                return self._wav(wav, immutable)
            if path == "/audio/peaks":
                return self._peaks(q)
            if path == "/api/settings/export":
                return self._json(200, load_export_config(app.root))
            if path == "/api/data/status":
                return self._json(200, app.data_status())
            if path == "/api/builds":
                return self._json(200, builds.list_builds())
            if path == "/api/job":
                return self._json(200, builds.job(q.get("id", "")))
            if path == "/api/deploy/status":
                return self._json(200, builds.deploy_status())
            if path == "/api/deploy/plan":
                return self._json(200, builds.install_plan(q.get("build", "")))
            if path == "/api/deploy/history":
                return self._json(200, builds.history())
            if path == "/api/builds/detail":
                return self._json(200, builds.build_detail(q.get("name", "")))
            if path == "/api/builds/log":
                return self._json(200, builds.build_log(q.get("name", "")))
            if not path.startswith(("/api/", "/audio/")) and self._static(path):
                return
            raise ApiError(404, "not found")

        def _has_studio(self):
            return bool(static_dir) and (static_dir / "index.html").is_file()

        def _post(self, path, body, s):
            """-> (status, response object, extra headers)."""
            if listener.public or not (s or path in PUBLIC_POSTS):  # defence in depth: _authorize refused already
                raise self._visitor_refused()
            if path == "/api/login":
                if not listener.remote:
                    return 200, self._session_info(s), None
                try:
                    token, csrf, user = listener.auth.login(body.get("username"), body.get("password"),
                                                            self._peer(), self.headers.get("User-Agent"))
                except AuthError as e:
                    raise ApiError(e.status, e.message)
                max_age = int(listener.cfg["session"]["max_days"] * 86400)
                info = self._session_info(dict(user, csrf=csrf))
                return 200, info, {"Set-Cookie": self._set_cookie(token, max_age)}
            if path == "/api/logout":
                if listener.access:  # the Access session is Cloudflare's: the page goes to its logout address
                    return 200, {"signed_out": False, "logout_url": ACCESS_LOGOUT}, None
                if listener.remote:
                    token = self._cookie_token()
                    if token:
                        listener.auth.logout(token)
                    return 200, {"signed_out": True}, {"Set-Cookie": self._set_cookie("", 0)}
                return 200, {"signed_out": False}, None
            if path == "/api/settings/export":
                try:
                    saved = save_global_gain(app.root, body.get("global_gain_db"), body.get("loaded_sha256"),
                                             level_mode=body.get("level_mode"))
                except (ConfigError, TypeError, ValueError) as e:
                    raise ApiError(409 if "changed since" in str(e) else 400, str(e))
                return 200, saved, None
            if path == "/api/builds/start":
                return 202, builds.start_build(body), None
            if path == "/api/builds/preview":
                return 200, builds.preview(body), None
            if path == "/api/deploy/install":
                return 202, builds.start_install(body), None
            if path == "/api/deploy/restore":
                return 202, builds.start_restore(body), None
            if path == "/api/settings/mcc":
                return 200, builds.set_mcc_folder(body.get("mcc_folder")), None
            if path == "/api/builds/dry-run":
                return 202, builds.start_dry_run(body.get("levels") or [], body.get("name")), None
            if path == "/api/data/import/preview":
                return 200, app.data_preview_import(), None
            if path == "/api/data/import":
                return 200, app.data_import(body), None
            if path == "/api/data/export":
                return 200, app.data_export(body), None
            if path == "/api/save":
                result = app.save(body)
                if shared.feed and result.get("saved"):
                    shared.feed.note_author(body.get("slot_id"), s["username"])
                return 200, result, None
            if path == "/api/edit/preview":
                return 200, app.edit_preview(body), None
            if path == "/api/progress":
                return 200, app.set_progress(body), None
            if path == "/api/validate":
                return 200, app.validate() or {}, None
            raise ApiError(404, "not found")

        def _handle(self):
            try:
                self._route()
            except ApiError as e:
                self.close_connection = True  # the request body may be unread: never reuse this connection
                self._json(e.status, {"error": e.message, "details": e.details})
            except (ValueError, TypeError) as e:
                self.close_connection = True
                self._json(400, {"error": f"bad request: {e}"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True  # the browser cancelled (a newer preview, a skipped clip)
            except Exception as e:  # noqa: BLE001 - report, never crash the server
                self.close_connection = True
                try:
                    self._json(500, {"error": f"{type(e).__name__}: {e}"})
                except OSError:
                    pass

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _handle  # the others: 405

    return Handler


NO_BUILD_PAGE = (b"<!doctype html><meta charset=utf-8><title>Localization Studio</title>"
                 b"<p>The Studio page is not built on the host yet. On the host computer run "
                 b"<code>npm run build</code> in <code>frontend/</code>, then reload.")


def make_app(root, vgmstream, oodle_dll=None, ffmpeg=None, celt_dll=DEFAULT_DLL):
    decode = vgmstream_decoder(vgmstream) if Path(vgmstream).is_file() else None
    if decode is None:
        print(f"warning: vgmstream-cli not found at {vgmstream}; only already-decoded audio will play")

        def decode(*_a, **_k):
            return False, "vgmstream-cli not configured"
    editor = None
    if ffmpeg and Path(celt_dll).is_file():
        editor = EditPreview(root, ffmpeg, lambda: Celt011(celt_dll))
    else:
        print(f"warning: audio editor disabled (ffmpeg {'ok' if ffmpeg else 'not found'}, "
              f"libcelt {'ok' if Path(celt_dll).is_file() else 'not found at ' + str(celt_dll)})")
    return M4App(root, mcc_audio=MccAudio(root, decode),
                 ce_audio=CeAudio(root, decode, ce_source_reader(oodle_dll)), editor=editor)


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    ssl_context = None

    def get_request(self):
        sock, addr = super().get_request()
        if self.ssl_context:  # the TLS handshake happens in the request's own thread (finish_request)
            sock = self.ssl_context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def finish_request(self, request, client_address):
        if self.ssl_context:
            try:
                request.settimeout(30)
                request.do_handshake()
                request.settimeout(None)
            except (ssl.SSLError, OSError):
                return  # a client that does not speak TLS (or gave up): nothing to answer
        super().finish_request(request, client_address)


def _bind(host, port, handler):
    if ":" in host:  # IPv6
        class V6(StudioHTTPServer):
            address_family = socket.AF_INET6
        return V6((host, port), handler)
    return StudioHTTPServer((host, port), handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, help="local listener port (default 8765)")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--config", type=Path, help="server settings (default config/studio_server.json)")
    ap.add_argument("--lan", action="store_true", help="also listen for other computers (sign-in required)")
    ap.add_argument("--remote-host", help="remote listener address (default 0.0.0.0: every network)")
    ap.add_argument("--remote-port", type=int, help="remote listener port (default 8766)")
    ap.add_argument("--public", action="store_true", help="also serve the read-only public view (loopback, port 8081)")
    ap.add_argument("--public-port", type=int, help="public read-only listener port (default 8081)")
    ap.add_argument("--allowed-host", action="append", default=[], help="extra host name for the remote listener")
    ap.add_argument("--allowed-origin", action="append", default=[], help="extra browser origin (https://name)")
    ap.add_argument("--static-dir", type=Path, help="the built Studio (default frontend/dist)")
    ap.add_argument("--state-dir", type=Path, help="TESTS: keep sessions and the audit log here instead of work/studio/")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--oodle-dll", type=Path)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"), help="for the audio editor (owner-approved)")
    ap.add_argument("--celt-dll", type=Path, default=DEFAULT_DLL, help="libcelt-0110.dll (from vgmstream)")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    ap.add_argument("--mcc-root", type=Path, help="TESTS ONLY: a throw-away copy of the game folder to install into")
    ap.add_argument("--deploy-state", type=Path, help="TESTS ONLY: backups and install state for --mcc-root")
    ap.add_argument("--stop", action="store_true", help="stop the running server cleanly, then exit")
    args = ap.parse_args()
    if args.stop:
        raise SystemExit(request_stop(args.root, args.config))

    over = {"local": {}, "remote": {}, "public": {}}
    if args.public:
        over["public"]["enabled"] = True
    if args.public_port:
        over["public"]["port"] = args.public_port
    if args.port:
        over["local"]["port"] = args.port
    if args.lan:
        over["remote"]["enabled"] = True
    if args.remote_host:
        over["remote"]["host"] = args.remote_host
    if args.remote_port:
        over["remote"]["port"] = args.remote_port
    if args.static_dir:
        over["static_dir"] = str(args.static_dir.resolve())
    if args.state_dir:
        over["sessions_file"] = str((args.state_dir / "sessions.sqlite").resolve())
        over["audit_file"] = str((args.state_dir / "audit.jsonl").resolve())
    try:
        cfg = load_server_config(args.root, args.config, over)
    except NetConfigError as e:
        raise SystemExit(f"server settings: {e}")
    cfg["allowed_hosts"] = list(cfg["allowed_hosts"]) + args.allowed_host
    cfg["allowed_origins"] = list(cfg["allowed_origins"]) + args.allowed_origin

    app = make_app(args.root, args.vgmstream_cli, args.oodle_dll, args.ffmpeg, args.celt_dll)
    if not app.levels or not app.missions:
        raise SystemExit("no catalogs under work/; build them first (docs/m4-user-guide.md §1)")
    threading.Thread(target=app.validate, daemon=True).start()
    builds = BuildBoard(app.root, lambda: set(app.levels), mcc_root=args.mcc_root, deploy_state=args.deploy_state,
                        app=app)
    feed = LiveFeed(Path(args.root) / "mappings" / "manual_mappings.db")
    feed.start()
    shared = Shared(args.root, cfg, feed)

    servers = []
    local = Listener("local", cfg, cfg["local"]["port"])
    servers.append(_bind(cfg["local"]["host"], cfg["local"]["port"],
                         make_handler(app, builds=builds, listener=local, shared=shared)))
    url = f"http://{HOST if cfg['local']['host'] in ('127.0.0.1', 'localhost') else cfg['local']['host']}:" \
          f"{cfg['local']['port']}/"
    print(f"Studio on {url}  (this computer; {len(app.levels)} MCC levels, {len(app.missions)} CE missions)")
    if not (cfg["static_path"] / "index.html").is_file():
        print(f"note: {cfg['static_path']} has no built Studio; run `npm run build` in frontend/ "
              "(the classic page is served at / meanwhile)")

    access = None
    if cfg["remote"]["enabled"] and cfg["remote"]["auth"] == "cloudflare_access":
        access = AccessVerifier(cfg["cloudflare_access"])
        try:
            print(f"Cloudflare Access: {access.warm()} signing key(s) from {access.team}")
        except Exception as e:  # noqa: BLE001 - offline at start-up: requests are refused until keys arrive
            print(f"warning: cannot fetch the Cloudflare Access keys yet ({type(e).__name__}); every remote "
                  "request is refused until they can be fetched")
        remote = Listener("remote", cfg, cfg["remote"]["port"], access=access,
                          csrf_key=_access_csrf_key(Path(cfg["sessions_path"]).parent))
        srv = _bind(cfg["remote"]["host"], cfg["remote"]["port"],
                    make_handler(app, builds=builds, listener=remote, shared=shared))
        servers.append(srv)
        shared.remote_running = True
        print(f"Remote access on http://{cfg['remote']['host']}:{cfg['remote']['port']} for the Cloudflare Tunnel "
              f"only (Cloudflare Access verified on every request; {len(access.users)} account(s)).\n"
              f"  Public address: {cfg['public_url']}")
    elif cfg["remote"]["enabled"]:
        users = UserStore(cfg["users_path"])
        if users.count() == 0:
            raise SystemExit("remote access needs at least one account; create one first:\n"
                             "  python scripts/ui/studio_users.py add <name> --role admin")
        auth = Authenticator(users, SessionStore(cfg["sessions_path"], cfg["session"]["idle_hours"],
                                                 cfg["session"]["max_days"]))
        remote = Listener("remote", cfg, cfg["remote"]["port"], auth=auth, secure_tls=bool(cfg["tls"]))
        srv = _bind(cfg["remote"]["host"], cfg["remote"]["port"],
                    make_handler(app, builds=builds, listener=remote, shared=shared))
        if cfg["tls"]:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(str(cfg["tls"][0]), str(cfg["tls"][1]))
            srv.ssl_context = ctx
        servers.append(srv)
        shared.remote_running = True
        shared.users, shared.sessions = users, auth.sessions
        info = connection_info(cfg, True)
        print(f"Remote access on {cfg['remote']['host']}:{cfg['remote']['port']} "
              f"({'HTTPS' if cfg['tls'] else 'HTTP'}; sign-in required, {users.count()} account(s)). Open from "
              "another computer:")
        for u in info["urls"]:
            print(f"  {u['url']}  ({u['kind']}{'' if u['encrypted'] else ', not encrypted'})")
        if not cfg["tls"] and not cfg.get("public_url"):
            print("  Plain HTTP: use it on a trusted network or through Tailscale (docs/remote-access.md).")

    if cfg["public"]["enabled"]:
        pub = Listener("public", cfg, cfg["public"]["port"])
        servers.append(_bind(cfg["public"]["host"], cfg["public"]["port"],
                             make_handler(app, builds=builds, listener=pub, shared=shared)))
        print(f"Public read-only view on http://{cfg['public']['host']}:{cfg['public']['port']} for a tunnel only "
              f"(anonymous; no edits, audio or downloads).\n  Public address: {cfg['public']['url'] or '(not set)'}; "
              f"sign in to edit at: {pub.sign_in_url or '(not set)'}")

    for srv in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True, name="extra-listener").start()
    state_dir = Path(cfg["sessions_path"]).parent
    stop_file = state_dir / STOP_FILE
    stop_file.unlink(missing_ok=True)
    _write_pid_file(state_dir, cfg, bool(access))
    threading.Thread(target=_watch_stop_file, args=(stop_file, servers[0], builds), daemon=True,
                     name="stop-watch").start()
    if not args.no_open:
        webbrowser.open(url)
    print("Ctrl+C stops (or: python scripts/ui/m4_server.py --stop).", flush=True)
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feed.stop()
        for srv in servers:
            srv.server_close()
        (state_dir / "server.json").unlink(missing_ok=True)
        print("Studio stopped.", flush=True)


def _access_csrf_key(state_dir):
    """A random key kept in the state folder (git-ignored work/studio/): CSRF tokens in Cloudflare Access mode
    are HMAC(key, account), so they survive a server restart and differ per account."""
    p = Path(state_dir) / "access_csrf.key"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.is_file() or p.stat().st_size != 32:
        p.write_bytes(secrets.token_bytes(32))
    return p.read_bytes()


def _write_pid_file(state_dir, cfg, access):
    """work/studio/server.json: which process serves which addresses (scripts/deploy/studio.ps1 reads it)."""
    info = {"pid": os.getpid(), "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "local": f"http://{cfg['local']['host']}:{cfg['local']['port']}/",
            "remote": (f"http://{cfg['remote']['host']}:{cfg['remote']['port']}/" if cfg["remote"]["enabled"]
                       else None),
            "remote_auth": cfg["remote"]["auth"] if cfg["remote"]["enabled"] else None,
            "public_url": cfg.get("public_url") if access else None,
            "public": (f"http://{cfg['public']['host']}:{cfg['public']['port']}/" if cfg["public"]["enabled"]
                       else None),
            "public_view_url": cfg["public"]["url"] if cfg["public"]["enabled"] else None}
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "server.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def _watch_stop_file(stop_file, server, builds):
    """Clean shutdown on request (`--stop` creates the file): waits for a running build or install to end first,
    so an install's backup / rollback is never cut short."""
    while True:
        time.sleep(1)
        if not stop_file.exists():
            continue
        if any(j.get("state") == "running" for j in list(builds._jobs.values())):
            continue  # stop as soon as the job is over
        stop_file.unlink(missing_ok=True)
        print("stop requested; shutting down", flush=True)
        server.shutdown()
        return


def request_stop(root, config=None, timeout=60):
    """`--stop`: ask the running server to shut down and wait for it. -> exit code."""
    try:
        cfg = load_server_config(root, config, {})
    except NetConfigError as e:
        raise SystemExit(f"server settings: {e}")
    state_dir = Path(cfg["sessions_path"]).parent
    pid_file = state_dir / "server.json"
    if not pid_file.is_file():
        print("no Studio server is running (work/studio/server.json is absent)")
        return 0
    (state_dir / STOP_FILE).write_text("stop\n", encoding="utf-8")
    end = time.time() + timeout
    while time.time() < end:
        if not pid_file.exists():
            print("Studio stopped.")
            return 0
        time.sleep(0.5)
    print(f"the server did not stop within {timeout} s (a build or install may still be running); "
          f"{STOP_FILE} stays, so it stops when that ends")
    return 1


if __name__ == "__main__":
    main()
