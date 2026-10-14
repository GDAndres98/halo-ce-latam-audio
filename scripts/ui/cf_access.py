"""Cloudflare Access identity for the Studio's remote listener (docs/deploy-cloudflare.md).

When the remote listener runs behind a Cloudflare Tunnel protected by a Cloudflare Access application, every
request Cloudflare forwards carries the signed-in visitor's Access token in the `Cf-Access-Jwt-Assertion`
header. The Studio does not trust that the request came through Access: it verifies the token itself, on every
request, and refuses anything else (fail closed). Checked, following Cloudflare's "Validate JWTs" guide
(https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/):

- the signature: RS256 only (RSASSA-PKCS1-v1_5 with SHA-256, RFC 8017 §8.2.2), against the team's public keys
  from https://<team>.cloudflareaccess.com/cdn-cgi/access/certs (fetched over verified HTTPS, cached, fetched
  again for an unknown key id because Cloudflare rotates them);
- `iss` is the team domain, `aud` contains this application's AUD tag, `type` is "app" (Cloudflare also signs
  "meta" tokens for visitors who are *not* signed in), and `exp` / `nbf` / `iat` hold, with 60 s of leeway;
- the `email` claim is one of the accounts listed in config/studio_server.json, which gives the role.

Standard library only (like the rest of the server): the RSA check is `pow(signature, e, n)` and a constant-time
comparison with the expected EMSA-PKCS1-v1_5 encoding.
"""
import base64
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.request

HEADER = "Cf-Access-Jwt-Assertion"
LEEWAY_S = 60
MIN_RSA_BITS = 2048
REFETCH_MIN_S = 60  # an unknown key id fetches the keys again at most this often
REFRESH_S = 3600  # known keys are refreshed in the background of a request at most this often
TEAM_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$")
AUD_RE = re.compile(r"^[0-9a-f]{64}$")
# DER DigestInfo prefix for SHA-256 (RFC 8017 §9.2, note 1).
SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


class AccessError(Exception):
    """Why a request was refused. status 401: no or invalid token; 403: valid token, account not allowed."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def b64url(data):
    if not isinstance(data, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", data):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _int(b64):
    return int.from_bytes(b64url(b64), "big")


def rsa_pkcs1_sha256_ok(n, e, message, signature, min_bits=MIN_RSA_BITS):
    """RSASSA-PKCS1-v1_5 verification with SHA-256 (RFC 8017 §8.2.2)."""
    k = (n.bit_length() + 7) // 8
    if n.bit_length() < min_bits or e < 3 or e % 2 == 0 or len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_DIGESTINFO + hashlib.sha256(message).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def check_settings(ca):
    """Raises ValueError for settings that cannot work (the server then refuses to start)."""
    team = ca.get("team_domain") or ""
    if not TEAM_RE.match(team):
        raise ValueError("cloudflare_access.team_domain must be <team>.cloudflareaccess.com")
    aud = ca.get("aud")
    if not isinstance(aud, list) or not aud or not all(isinstance(a, str) and AUD_RE.match(a) for a in aud):
        raise ValueError("cloudflare_access.aud must list the Access application's AUD tag (64 hex characters)")
    users = ca.get("users")
    if not isinstance(users, dict) or not users:
        raise ValueError("cloudflare_access.users must map at least one e-mail address to a role")
    for email, role in users.items():
        if "@" not in email or email != email.strip().lower():
            raise ValueError(f"cloudflare_access.users: {email!r} must be a lower-case e-mail address")
        if role not in ("editor", "admin"):
            raise ValueError(f"cloudflare_access.users[{email!r}] must be \"editor\" or \"admin\"")


def fetch_certs(team_domain, timeout=10):
    """The team's signing keys: {kid: (n, e)}. Verified HTTPS (the default context checks the certificate)."""
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - fixed https URL
        doc = json.loads(r.read(1 << 20).decode("utf-8"))
    keys = {}
    for jwk in doc.get("keys") or []:
        if jwk.get("kty") == "RSA" and jwk.get("kid") and jwk.get("alg", "RS256") == "RS256" \
                and jwk.get("use", "sig") == "sig":
            keys[jwk["kid"]] = (_int(jwk["n"]), _int(jwk["e"]))
    if not keys:
        raise AccessError(503, "Cloudflare Access returned no signing keys")
    return keys


class AccessVerifier:
    """Verifies Cloudflare Access tokens for one application. Thread-safe; keys are cached in memory."""

    def __init__(self, ca, fetch=None, clock=time.time, min_bits=MIN_RSA_BITS):
        check_settings(ca)
        self.team = ca["team_domain"]
        self.issuer = f"https://{self.team}"
        self.aud = set(ca["aud"])
        self.users = dict(ca["users"])
        self._fetch = fetch or (lambda: fetch_certs(self.team))
        self._clock, self._min_bits = clock, min_bits
        self._keys, self._fetched_at, self._tried_at = {}, 0.0, 0.0
        self._lock = threading.Lock()

    def _key(self, kid):
        now = self._clock()
        with self._lock:
            stale = now - self._fetched_at > REFRESH_S
            if (kid not in self._keys or stale) and now - self._tried_at >= REFETCH_MIN_S:
                self._tried_at = now
                try:
                    self._keys, self._fetched_at = self._fetch(), now
                except Exception as e:  # noqa: BLE001 - network or format: keep the cached keys, if any
                    if not self._keys:
                        raise AccessError(503, f"cannot fetch the Cloudflare Access keys ({type(e).__name__})")
            return self._keys.get(kid)

    def warm(self):
        """Fetch the keys now (at start-up), so a configuration problem shows before the first visitor."""
        with self._lock:
            self._keys, self._fetched_at = self._fetch(), self._clock()
            self._tried_at = self._fetched_at
        return len(self._keys)

    def verify(self, token):
        """-> {"email", "role", "sub"}. Raises AccessError."""
        if not token:
            raise AccessError(401, "this address only answers requests that come through Cloudflare Access")
        if len(token) > 16384 or token.count(".") != 2:
            raise AccessError(401, "invalid Cloudflare Access token")
        h64, p64, s64 = token.split(".")
        try:
            header, payload = json.loads(b64url(h64)), json.loads(b64url(p64))
            signature = b64url(s64)
        except (ValueError, UnicodeDecodeError):
            raise AccessError(401, "invalid Cloudflare Access token")
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise AccessError(401, "invalid Cloudflare Access token")
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AccessError(401, "Cloudflare Access token: unexpected algorithm")
        key = self._key(header["kid"])
        if key is None or not rsa_pkcs1_sha256_ok(key[0], key[1], f"{h64}.{p64}".encode("ascii"), signature,
                                                  self._min_bits):
            raise AccessError(401, "Cloudflare Access token: bad signature")
        now = self._clock()
        if payload.get("iss") != self.issuer:
            raise AccessError(401, "Cloudflare Access token: wrong issuer")
        aud = payload.get("aud")
        aud = [aud] if isinstance(aud, str) else aud
        if not isinstance(aud, list) or not self.aud.intersection(a for a in aud if isinstance(a, str)):
            raise AccessError(401, "Cloudflare Access token: issued for another application")
        if payload.get("type") != "app":
            raise AccessError(401, "Cloudflare Access token: not a signed-in application token")
        for claim in ("exp", "iat"):
            if not isinstance(payload.get(claim), (int, float)):
                raise AccessError(401, f"Cloudflare Access token: no {claim}")
        if payload["exp"] < now - LEEWAY_S:
            raise AccessError(401, "Cloudflare Access sign-in expired")
        if payload["iat"] > now + LEEWAY_S or payload.get("nbf", 0) > now + LEEWAY_S:
            raise AccessError(401, "Cloudflare Access token: not valid yet")
        email = payload.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise AccessError(403, "Cloudflare Access token without an e-mail address (service tokens are not "
                                   "accepted)")
        email = email.strip().lower()
        role = self.users.get(email)
        if role is None:
            raise AccessError(403, f"signed in to Cloudflare Access as {email}, which is not a Studio account; "
                                   "the owner adds it under cloudflare_access.users in config/studio_server.json")
        return {"email": email, "role": role, "sub": str(payload.get("sub") or "")}
