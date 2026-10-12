"""Studio accounts and sessions for remote access (the network listener of m4_server.py).

What this module does, and why it is built this way:

- **Accounts** live in config/studio_users.json (git-ignored), managed with scripts/ui/studio_users.py.
  Passwords are stored as scrypt hashes (hashlib.scrypt, RFC 7914; a memory-hard KDF from the standard
  library), each with its own random salt. A password is never written, logged or returned.
- **Sessions** are random 256-bit tokens (secrets.token_urlsafe) sent in an HttpOnly, SameSite=Strict
  cookie. Only the SHA-256 of a token is stored (work/studio/sessions.sqlite), so a copy of that file does
  not let anyone sign in. Sessions expire after an idle period and after an absolute lifetime, and are
  dropped when the account is removed, its password changes or its role changes.
- **CSRF**: every state-changing request must carry the session's own CSRF token in the X-Studio-CSRF
  header (compared in constant time). Cross-site pages cannot read it, and the SameSite=Strict cookie is
  not sent on cross-site requests anyway; the server also checks Origin (studio_net.py).
- **Throttling**: repeated failed sign-ins from one address or for one account are slowed down and then
  refused for a while.

Roles: "editor" (matching: browse, listen, edit, save, approve, needs rework, flags, notes, level status)
and "admin" (also builds, the audio level setting, data import/export). Installing into or restoring the
game is never granted by a role: only the host's local listener can do it (see m4_server.py).
"""
import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ROLES = ("editor", "admin")
USERS_SCHEMA = "studio-users/1"
USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
MIN_PASSWORD = 10

# scrypt cost: N=2^17, r=8, p=1, the minimum the OWASP Password Storage Cheat Sheet recommends (128 MiB per hash,
# a few tenths of a second). At most two hashes run at once, so a burst of sign-ins cannot exhaust memory.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 17, 8, 1
SCRYPT_MAXMEM = 256 * 1024 * 1024
_SCRYPT_SLOTS = threading.BoundedSemaphore(2)


class AuthError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


# --------------------------------------------------------------------------- passwords
def hash_password(password, *, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P):
    salt = os.urandom(16)
    with _SCRYPT_SLOTS:
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${n}${r}${p}${b64(salt)}${b64(digest)}"


def verify_password(password, stored):
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        want = base64.b64decode(digest)
        if int(n) > 1 << 20 or int(r) > 32 or int(p) > 4:
            return False  # a stored cost this high is not one this module writes
        with _SCRYPT_SLOTS:
            got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                 maxmem=SCRYPT_MAXMEM, dklen=len(want))
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(got, want)


# A hash to verify against when the account does not exist, so a wrong name takes as long as a wrong password.
_DUMMY_HASH = None


def _dummy_hash():
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def check_username(name):
    if not name or len(name) > 40 or not set(name) <= USERNAME_CHARS:
        raise ValueError("user names use 1-40 characters: lower-case letters, digits, '.', '_' or '-'")
    return name


def check_password_strength(password, username=""):
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"passwords need at least {MIN_PASSWORD} characters")
    if username and password.lower() == username.lower():
        raise ValueError("the password must differ from the user name")
    return password


# --------------------------------------------------------------------------- accounts file
class UserStore:
    """config/studio_users.json: {"schema": "studio-users/1", "users": {name: {role, password, changed_at}}}.
    Read again whenever the file changes, so studio_users.py takes effect without a restart."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._stamp, self._users = None, {}

    def _load(self):
        with self._lock:
            try:
                st = self.path.stat()
                stamp = (st.st_mtime_ns, st.st_size)
            except FileNotFoundError:
                self._stamp, self._users = None, {}
                return self._users
            if stamp != self._stamp:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
                if doc.get("schema") != USERS_SCHEMA or not isinstance(doc.get("users"), dict):
                    raise AuthError(500, f"{self.path.name} is not a {USERS_SCHEMA} file")
                self._users = {k: v for k, v in doc["users"].items() if v.get("role") in ROLES}
                self._stamp = stamp
            return self._users

    def users(self):
        return dict(self._load())

    def get(self, name):
        return self._load().get(name)

    def count(self):
        return len(self._load())

    # Writing (used by studio_users.py, never by the server)
    def write(self, users):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"schema": USERS_SCHEMA, "users": users}, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)  # POSIX hosts: readable by the owner only (no effect on Windows ACLs)
        except OSError:
            pass


def account_stamp(user):
    """Changes whenever the password or role changes: sessions made before that stop working."""
    return hashlib.sha256(f"{user.get('role')}|{user.get('password')}".encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- sessions
SESSION_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    token_sha256  TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    account_stamp TEXT NOT NULL,
    csrf          TEXT NOT NULL,
    created_at    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    address       TEXT,
    user_agent    TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (username);
"""


def _token_hash(token):
    return hashlib.sha256(token.encode("ascii", "replace")).hexdigest()


class SessionStore:
    def __init__(self, path, idle_hours=72, max_days=14):
        self.path = Path(path)
        self.idle_s, self.max_s = idle_hours * 3600, max_days * 86400
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SESSION_DDL)

    @contextlib.contextmanager
    def _conn(self):
        """One connection per operation, committed and always closed (Windows keeps open files locked)."""
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, username, stamp, address, user_agent):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), time.time()
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM sessions WHERE last_seen < ? OR created_at < ?", (now - self.idle_s, now - self.max_s))
            c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                      (_token_hash(token), username, stamp, csrf, now, now, address, (user_agent or "")[:200]))
        return token, csrf

    def lookup(self, token):
        """-> {username, account_stamp, csrf, created_at} or None (unknown or expired)."""
        if not token or len(token) > 100:
            return None
        h, now = _token_hash(token), time.time()
        with self._lock, self._conn() as c:
            row = c.execute("SELECT username, account_stamp, csrf, created_at, last_seen FROM sessions "
                            "WHERE token_sha256 = ?", (h,)).fetchone()
            if row is None:
                return None
            if row[4] < now - self.idle_s or row[3] < now - self.max_s:
                c.execute("DELETE FROM sessions WHERE token_sha256 = ?", (h,))
                return None
            if now - row[4] > 60:  # refresh the idle timer at most once a minute
                c.execute("UPDATE sessions SET last_seen = ? WHERE token_sha256 = ?", (now, h))
        return {"username": row[0], "account_stamp": row[1], "csrf": row[2], "created_at": row[3]}

    def delete(self, token):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM sessions WHERE token_sha256 = ?", (_token_hash(token or ""),))

    def delete_user(self, username):
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM sessions WHERE username = ?", (username,)).rowcount

    def active(self):
        now = time.time()
        with self._lock, self._conn() as c:
            return [dict(zip(("username", "address", "created_at", "last_seen"), r)) for r in c.execute(
                "SELECT username, address, created_at, last_seen FROM sessions WHERE last_seen >= ? AND "
                "created_at >= ? ORDER BY last_seen DESC", (now - self.idle_s, now - self.max_s))]


# --------------------------------------------------------------------------- throttling
class LoginThrottle:
    """Failed sign-ins per address and per account: after `limit` failures within `window_s`, further attempts
    are refused for `lock_s`. In memory: a restart clears it, which only helps the owner."""

    def __init__(self, limit=5, window_s=900, lock_s=900):
        self.limit, self.window_s, self.lock_s = limit, window_s, lock_s
        self._fail = {}
        self._lock = threading.Lock()

    def _recent(self, key, now):
        times = [t for t in self._fail.get(key, []) if t > now - max(self.window_s, self.lock_s)]
        self._fail[key] = times
        return times

    def blocked_for(self, *keys):
        now = time.time()
        with self._lock:
            waits = []
            for key in keys:
                times = [t for t in self._recent(key, now) if t > now - self.window_s]
                if len(times) >= self.limit:
                    waits.append(int(times[-1] + self.lock_s - now) + 1)
            return max(waits, default=0)

    def failed(self, *keys):
        now = time.time()
        with self._lock:
            for key in keys:
                self._recent(key, now).append(now)

    def succeeded(self, *keys):
        with self._lock:
            for key in keys:
                self._fail.pop(key, None)


# --------------------------------------------------------------------------- the authenticator
class Authenticator:
    def __init__(self, users, sessions, throttle=None):
        self.users, self.sessions = users, sessions
        self.throttle = throttle or LoginThrottle()

    def login(self, username, password, address, user_agent):
        """-> (token, csrf, user). Raises AuthError(401/429). The same message for any wrong name or password."""
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
            raise AuthError(400, "user name and password are required")
        username = username.strip().lower()
        wait = self.throttle.blocked_for(f"ip:{address}", f"user:{username}")
        if wait:
            raise AuthError(429, f"too many failed sign-ins; try again in {wait // 60 + 1} minute(s)")
        user = self.users.get(username)
        ok = verify_password(password, user["password"] if user else _dummy_hash())
        if not (ok and user):
            self.throttle.failed(f"ip:{address}", f"user:{username}")
            time.sleep(0.4)
            raise AuthError(401, "wrong user name or password")
        self.throttle.succeeded(f"ip:{address}", f"user:{username}")
        token, csrf = self.sessions.create(username, account_stamp(user), address, user_agent)
        return token, csrf, {"username": username, "role": user["role"]}

    def session(self, token):
        """-> {username, role, csrf} for a valid session whose account still exists unchanged, else None."""
        s = self.sessions.lookup(token)
        if not s:
            return None
        user = self.users.get(s["username"])
        if not user or account_stamp(user) != s["account_stamp"]:
            self.sessions.delete(token)
            return None
        return {"username": s["username"], "role": user["role"], "csrf": s["csrf"]}

    def logout(self, token):
        self.sessions.delete(token)


def csrf_ok(session, header_value):
    return bool(session and header_value) and hmac.compare_digest(session["csrf"], header_value)
