"""The Studio's public read-only listener (docs/public-access.md): what an anonymous visitor may see.

The public listener has no identity at all: it never reads cookies, Cloudflare Access tokens or identity
headers, so nothing a visitor sends can make it more than a visitor. What it serves is an allowlist (fail
closed: an endpoint added to the server later is refused here until it is listed):

- the built page (frontend/dist), and
- the read-only metadata in PUBLIC_GETS, each passed through `sanitize`, which removes what a visitor must not
  see: local file system paths, the game folder, build file locations and logs, notes, and anything that looks
  like an absolute path in free text.

Refused (401, "sign in to edit"): every write (any method but GET/HEAD), all audio (streams, waveform peaks,
editor previews, the interference reference: proprietary recordings are never sent to a visitor), the change
feed (it names who saved), configuration, data status, network details, jobs, the game folder status and
install plans, and build logs.

Anonymous traffic is also bounded (PublicLimiter): requests per address per minute and API requests at once,
so visitors cannot starve the owner's own listeners.
"""
import copy
import re
import threading
import time

# GET (and HEAD) API paths a visitor may request. Everything else under /api/ or /audio/ is refused.
PUBLIC_GETS = frozenset({
    "/api/session", "/api/state", "/api/slots", "/api/slot", "/api/ce", "/api/ce_line",
    "/api/builds", "/api/builds/detail", "/api/deploy/history",
})

# Keys removed wherever they appear in a public answer: file system locations, the game folder, logs, notes.
DENY_KEYS = frozenset({
    "mcc_root", "mcc_folder", "path", "installed_path", "backup_folder", "backup_root", "backup", "candidate",
    "bank_copy", "subtitle_copies", "log", "log_tail", "state_dir", "notes", "hashed_files_changed", "config_file",
})

# Absolute paths in free text (Windows drive or UNC paths, and common POSIX roots).
_PATH_RE = re.compile(r"(?i)(?:\b[a-z]:[\\/]|\\\\[^\\\s]+\\)[^\s\"'<>|]*|(?<![\w.])/(?:users|home|root|tmp|mnt|var|opt)/\S*")
HIDDEN = "[path hidden]"


def scrub(value):
    """A deep copy without DENY_KEYS and with absolute paths in strings replaced."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in DENY_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return _PATH_RE.sub(HIDDEN, value)
    return value


def sanitize(path, obj):
    """The public form of one allowed answer."""
    obj = copy.deepcopy(obj)
    if path == "/api/state" and isinstance(obj.get("validation"), dict):
        v = obj["validation"]  # counts only: findings can name files
        obj["validation"] = {"summary": v.get("summary"), "at": v.get("at")} if "summary" in v else None
    elif path == "/api/slot":
        obj["interference"] = {}  # the Victor 933 lane and its MCC reference are listening tools
    elif path == "/api/builds":
        for b in obj.get("builds", []):
            b["has_log"] = False
            b["install_files"] = [{k: f.get(k) for k in ("install_rel", "candidate_sha256", "size")}
                                  for f in b.get("install_files", [])]
    elif path == "/api/builds/detail":
        obj["install_files"] = [{k: f.get(k) for k in ("install_rel", "candidate_sha256", "size")}
                                for f in obj.get("install_files", [])]
    elif path == "/api/deploy/history":
        keep = ("at", "action", "result", "build", "kind", "message")
        obj["events"] = [dict({k: e.get(k) for k in keep},
                              files=[{k: f.get(k) for k in ("install_rel", "candidate_sha256", "installed_sha256")}
                                     for f in e.get("files") or []])
                         for e in obj.get("events", [])]
    out = scrub(obj)
    if path == "/api/slot" and isinstance(out.get("mapping"), dict):
        out["mapping"]["notes"] = ""  # the owner's own notes: scrub drops them; the page expects the field
    return out


class Limited(Exception):
    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


class PublicLimiter:
    """Bounds anonymous traffic: at most `per_minute` API requests per address in any minute, and at most
    `concurrent` API requests being answered at once (the rest wait up to `wait_s`, then get 503). Static files
    are not limited (they are small, cached and immutable)."""

    def __init__(self, per_minute=240, concurrent=8, wait_s=5.0, max_addresses=10000, clock=time.monotonic):
        self.per_minute, self.wait_s, self.max_addresses, self._clock = per_minute, wait_s, max_addresses, clock
        self._slots = threading.BoundedSemaphore(concurrent)
        self._hits = {}
        self._lock = threading.Lock()

    def admit(self, address):
        now = self._clock()
        with self._lock:
            if len(self._hits) > self.max_addresses:  # forget idle addresses (bounded memory)
                self._hits = {a: t for a, t in self._hits.items() if t and t[-1] > now - 60}
            times = [t for t in self._hits.get(address, []) if t > now - 60]
            if len(times) >= self.per_minute:
                self._hits[address] = times
                raise Limited(429, "too many requests; wait a minute", int(times[0] + 60 - now) + 1)
            times.append(now)
            self._hits[address] = times

    def slot(self):
        limiter = self

        class _Slot:
            def __enter__(self):
                if not limiter._slots.acquire(timeout=limiter.wait_s):
                    raise Limited(503, "the Studio is busy; try again shortly", 5)

            def __exit__(self, *exc):
                limiter._slots.release()
        return _Slot()
