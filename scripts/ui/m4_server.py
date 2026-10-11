"""M4: local manual matching UI (stdlib http.server, 127.0.0.1 only).

    python scripts/ui/m4_server.py                 # http://127.0.0.1:8765
    python scripts/ui/m4_server.py --port 8770 --no-open

Serves scripts/ui/m4.html and a small JSON API over scripts/ui/m4_app.py.
Never matches anything by itself. Saves only through mapping_store, and
decodes audio on demand into work/ with the approved vgmstream-cli.
Design: docs/m4-matching-ui-design.md; usage: docs/m4-user-guide.md.

API (all JSON unless noted):
    GET  /api/state                               levels + progress, CE missions, file hashes
    GET  /api/slots?level=a10|all&status=&q=      slot list (status: undecided|matched|no_equivalent|
                                                  deferred|needs_rework|audio_pending|subtitle_pending|
                                                  radio|fits|edited|stereo); q: words and "quoted phrases"
    GET  /api/slot?id=<slot_id>                   slot detail, SU/SP text, decision, verifications
    GET  /api/ce?mission=all|mapped|M01&level=&q=&subs=missing|present&hide_used=1&keep_slot=&offset=&limit=
                                                  CE lines in catalog order, filtered by q only
    GET  /api/ce_line?ref=<ce_line_ref>
    GET  /audio/mcc?level=&lang=spanish|english&index=     WAV (decoded on demand)
    GET  /audio/ce?ref=&lang=Spanish(Mexico)|English(US)|Spanish(Spain)&k=0
    GET  /audio/preview?key=&kind=edited|encoded  a rendered editor preview (WAV)
    POST /api/edit/preview                        {slot_id, ce_line_ref, language, edit} -> render as M6
                                                  would; writes only work/m4/preview/, never mappings
    POST /api/save                                see M4App.save; 409 = stale or protected
    POST /api/progress                            {level, status, note, verification, confirm, loaded_sha256}
    POST /api/validate                            run the read-only validator
"""
import argparse
import json
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.celt011 import DEFAULT_DLL, Celt011  # noqa: E402
from common.edit_preview import EditPreview  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.ondemand_audio import CeAudio, MccAudio, ce_source_reader, vgmstream_decoder  # noqa: E402
from build_api import BuildBoard  # noqa: E402
from common.export_config import ConfigError, load_export_config, save_global_gain  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402

HOST = "127.0.0.1"
PAGE = Path(__file__).resolve().parent / "m4.html"
DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")
MAX_BODY = 1 << 20


def make_handler(app, quiet=False, builds=None):
    builds = builds or BuildBoard(app.root, lambda: set(app.levels))

    class Handler(BaseHTTPRequestHandler):
        server_version = "M4/1"

        def log_message(self, fmt, *args):  # one line per error response only
            if not quiet and len(args) > 1 and str(getattr(args[1], "value", args[1])).startswith(("4", "5")):
                sys.stderr.write("%s %s\n" % (self.command, fmt % args))

        def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _wav(self, path):
            data = Path(path).read_bytes()
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else 0
                end = min(int(b) if b else len(data) - 1, len(data) - 1)
                if start > end:
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{len(data)}"})
                return self._send(206, data[start:end + 1], "audio/wav",
                                  {"Content-Range": f"bytes {start}-{end}/{len(data)}", "Accept-Ranges": "bytes"})
            self._send(200, data, "audio/wav", {"Accept-Ranges": "bytes"})

        def _guard_origin(self):
            """Reject cross-site requests: the page and the API share one local origin."""
            host = (self.headers.get("Host") or "").split(":")[0]
            origin = self.headers.get("Origin")
            if host not in ("127.0.0.1", "localhost"):
                raise ApiError(403, "bad Host header")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                raise ApiError(403, "cross-origin request refused")

        def _route(self):
            self._guard_origin()
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if self.command in ("GET", "HEAD"):
                if u.path in ("/", "/index.html"):
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    return self._json(200, app.state())
                if u.path == "/api/slots":
                    return self._json(200, app.slots(q.get("level", ""), q.get("status") or None, q.get("q")))  # level=all ok
                if u.path == "/api/slot":
                    return self._json(200, app.slot(q.get("id", "")))
                if u.path == "/api/ce":
                    return self._json(200, app.ce(q.get("mission", "all"), q.get("q"), q.get("offset", 0),
                                                  q.get("limit", 100), q.get("level"), q.get("subs") or None,
                                                  q.get("hide_used") == "1", q.get("keep_slot") or None))
                if u.path == "/api/ce_line":
                    return self._json(200, app.ce_line(q.get("ref", "")))
                if u.path == "/audio/mcc":
                    return self._wav(app.mcc_wav(q.get("level", ""), q.get("lang", ""), q.get("index", -1)))
                if u.path == "/audio/ce":
                    return self._wav(app.ce_wav(q.get("ref", ""), q.get("lang", ""), q.get("k", 0)))
                if u.path == "/api/settings/export":
                    return self._json(200, load_export_config(app.root))
                if u.path == "/api/builds":
                    return self._json(200, builds.list_builds())
                if u.path == "/api/job":
                    return self._json(200, builds.job(q.get("id", "")))
                if u.path == "/audio/preview":
                    return self._wav(app.preview_wav(q.get("key", ""), q.get("kind", "")))
                raise ApiError(404, "not found")
            if self.command == "POST":
                if (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
                    raise ApiError(415, "JSON body required")
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise ApiError(413, "body too large")
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                except ValueError:
                    raise ApiError(400, "invalid JSON")
                if u.path == "/api/settings/export":
                    try:
                        saved = save_global_gain(app.root, body.get("global_gain_db"), body.get("loaded_sha256"))
                    except (ConfigError, TypeError, ValueError) as e:
                        raise ApiError(409 if "changed since" in str(e) else 400, str(e))
                    return self._json(200, saved)
                if u.path == "/api/builds/dry-run":
                    return self._json(202, builds.start_dry_run(body.get("levels") or [], body.get("name")))
                if u.path == "/api/save":
                    return self._json(200, app.save(body))
                if u.path == "/api/edit/preview":
                    return self._json(200, app.edit_preview(body))
                if u.path == "/api/progress":
                    return self._json(200, app.set_progress(body))
                if u.path == "/api/validate":
                    return self._json(200, app.validate() or {})
                raise ApiError(404, "not found")
            raise ApiError(405, "method not allowed")

        def _handle(self):
            try:
                self._route()
            except ApiError as e:
                self._json(e.status, {"error": e.message, "details": e.details})
            except (ValueError, TypeError) as e:
                self._json(400, {"error": f"bad request: {e}"})
            except Exception as e:  # noqa: BLE001 - report, never crash the server
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        do_GET = do_HEAD = do_POST = _handle

    return Handler


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--oodle-dll", type=Path)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"), help="for the audio editor (owner-approved)")
    ap.add_argument("--celt-dll", type=Path, default=DEFAULT_DLL, help="libcelt-0110.dll (from vgmstream)")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()
    app = make_app(args.root, args.vgmstream_cli, args.oodle_dll, args.ffmpeg, args.celt_dll)
    if not app.levels or not app.missions:
        raise SystemExit("no catalogs under work/; build them first (docs/m4-user-guide.md §1)")
    threading.Thread(target=app.validate, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, args.port), make_handler(app))
    url = f"http://{HOST}:{args.port}/"
    print(f"M4 matching UI on {url}  ({len(app.levels)} MCC levels, {len(app.missions)} CE missions; Ctrl+C stops)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
