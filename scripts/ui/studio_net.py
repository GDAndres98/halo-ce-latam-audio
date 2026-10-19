"""Network settings of the Studio server: listeners, allowed host names and origins, connection info.

The server has two kinds of listener (docs/remote-access.md):
- **local**: the host computer's own address (127.0.0.1 by default). It is the trusted local administrator
  context: no sign-in, and the only place where the game can be installed into or restored.
- **remote** (off unless enabled): the LAN / Tailscale address. Every API and audio request needs a signed-in
  account; installing into or restoring the game is refused whatever the role.
- **public** (off unless enabled; docs/public-access.md): a read-only view for anonymous visitors, reached only
  through a tunnel on this computer (loopback). No identity at all: never edits, never streams audio.

Settings come from config/studio_server.json (git-ignored; see config/studio_server.example.json), then the
command-line options. Unknown keys are refused, so a typo never silently leaves a default in place.
"""
import copy
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlparse

CONFIG_REL = "config/studio_server.json"
SCHEMA = "studio-server/1"
DEFAULTS = {
    "schema": SCHEMA,
    "local": {"host": "127.0.0.1", "port": 8765},
    # auth "password": Studio accounts (studio_users.py). "cloudflare_access": the remote listener sits behind a
    # Cloudflare Tunnel + Access application and every request must carry a valid Access token for one of
    # cloudflare_access.users (cf_access.py, docs/deploy-cloudflare.md); password sign-in is then off.
    "remote": {"enabled": False, "host": "0.0.0.0", "port": 8766, "tls_cert": None, "tls_key": None,
               "auth": "password"},
    # The public read-only listener for anonymous visitors (public_view.py, docs/public-access.md). Loopback only
    # (a Cloudflare Tunnel on this computer reaches it). url: the public https address visitors open (its own
    # host, never the remote listener's). sign_in_url: where "Sign in to edit" goes (default: public_url).
    # previews: visitors may play the published edited previews of APPROVED lines (public_previews.py; published by
    # scripts/build/publish_previews.py). Never the original recordings. Off by default: anything a browser plays
    # can be saved (docs/public-access.md §2.1).
    # originals: visitors may also play the original recordings (MCC Spain / English, unedited Campaign Evolved) and
    # see waveforms (owner request 2026-10-17). Off by default.
    "public": {"enabled": False, "host": "127.0.0.1", "port": 8081, "url": None, "sign_in_url": None,
               "previews": False, "originals": False},
    # Extra host names the remote listener answers to (e.g. "studio-pc.tail1234.ts.net"). The machine's own
    # names and addresses are always accepted.
    "allowed_hosts": [],
    # Extra browser origins allowed to send requests (e.g. "https://studio-pc.tail1234.ts.net").
    "allowed_origins": [],
    # The address remote users should open, shown on the Network page (e.g. the Tailscale HTTPS URL).
    "public_url": None,
    "session": {"idle_hours": 72, "max_days": 14},
    # "auto": Secure cookies over HTTPS (TLS listener, or an HTTPS proxy on this computer); true / false force it.
    "secure_cookies": "auto",
    "users_file": "config/studio_users.json",
    "sessions_file": "work/studio/sessions.sqlite",
    # Append-only log of write requests (who, from where, what, result).
    "audit_file": "work/studio/audit.jsonl",
    "static_dir": "frontend/dist",
    # Cloudflare Access application (public values, not secrets): the team domain, the application's AUD tag,
    # and the Access e-mail addresses allowed in, each with a Studio role.
    "cloudflare_access": {"team_domain": None, "aud": [], "users": {}},
}


class ConfigError(Exception):
    pass


def _merge(base, over, where="config"):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k not in base:
            raise ConfigError(f"{where}: unknown setting {k!r}")
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                raise ConfigError(f"{where}.{k} must be an object")
            # An empty default object is a free-form map (cloudflare_access.users: e-mail -> role).
            out[k] = _merge(base[k], v, f"{where}.{k}") if base[k] else copy.deepcopy(v)
        else:
            out[k] = v
    return out


def _port(value, name):
    if not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigError(f"{name} must be a port number (1-65535)")
    return value


def load_server_config(root, path=None, overrides=None):
    """-> the merged settings, with absolute paths added (users_path, sessions_path, static_path, ...)."""
    root = Path(root)
    p = Path(path) if path else root / CONFIG_REL
    doc = {}
    if p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ConfigError(f"{p}: {e}")
        if doc.get("schema", SCHEMA) != SCHEMA:
            raise ConfigError(f"{p}: schema {doc.get('schema')!r}, expected {SCHEMA}")
    cfg = _merge(DEFAULTS, doc, p.name)
    cfg = _merge(cfg, overrides or {}, "command line")
    _port(cfg["local"]["port"], "local.port")
    _port(cfg["remote"]["port"], "remote.port")
    _port(cfg["public"]["port"], "public.port")
    if cfg["secure_cookies"] not in ("auto", True, False):
        raise ConfigError("secure_cookies must be \"auto\", true or false")
    if cfg["remote"]["enabled"] and cfg["remote"]["port"] == cfg["local"]["port"]:
        raise ConfigError("the remote listener needs its own port")
    if bool(cfg["remote"]["tls_cert"]) != bool(cfg["remote"]["tls_key"]):
        raise ConfigError("remote.tls_cert and remote.tls_key go together")
    if cfg["remote"]["auth"] not in ("password", "cloudflare_access"):
        raise ConfigError("remote.auth must be \"password\" or \"cloudflare_access\"")
    if cfg["remote"]["enabled"] and cfg["remote"]["auth"] == "cloudflare_access":
        from cf_access import check_settings  # noqa: PLC0415
        try:
            check_settings(cfg["cloudflare_access"])
        except ValueError as e:
            raise ConfigError(str(e))
        # cloudflared runs on this computer: the listener must not be reachable any other way.
        if not _is_loopback(cfg["remote"]["host"]):
            raise ConfigError("with remote.auth \"cloudflare_access\", remote.host must be 127.0.0.1 (cloudflared "
                              "connects locally; nothing else may reach the listener)")
        if cfg["remote"]["tls_cert"]:
            raise ConfigError("with remote.auth \"cloudflare_access\", Cloudflare terminates HTTPS: leave tls_cert unset")
        if not str(cfg.get("public_url") or "").startswith("https://"):
            raise ConfigError("with remote.auth \"cloudflare_access\", public_url must be the https:// address")
    if cfg["public"]["enabled"]:
        pub = cfg["public"]
        if not _is_loopback(pub["host"]):
            raise ConfigError("public.host must be 127.0.0.1: only the tunnel on this computer may reach the public "
                              "read-only listener")
        if pub["port"] == cfg["local"]["port"] or (cfg["remote"]["enabled"] and pub["port"] == cfg["remote"]["port"]):
            raise ConfigError("the public listener needs its own port")
        for key in ("previews", "originals"):
            if not isinstance(pub[key], bool):
                raise ConfigError(f"public.{key} must be true or false")
        for key in ("url", "sign_in_url"):
            if pub[key] is not None and not (str(pub[key]).startswith("https://") and urlparse(pub[key]).hostname):
                raise ConfigError(f"public.{key} must be an https:// address")
        own = (urlparse(pub["url"] or "").hostname or "").lower()
        if own and own == (urlparse(cfg.get("public_url") or "").hostname or "").lower():
            raise ConfigError("public.url must be its own host name, not the remote listener's public_url (the "
                              "editing address keeps its Cloudflare Access protection)")
    if not _is_loopback(cfg["local"]["host"]):
        raise ConfigError("local.host must be a loopback address (127.0.0.1, ::1 or localhost): it is the "
                          "no-sign-in administrator address; use the remote listener for other computers")
    for o in cfg["allowed_origins"]:
        u = urlparse(o)
        if u.scheme not in ("http", "https") or not u.hostname or u.path not in ("", "/"):
            raise ConfigError(f"allowed_origins: {o!r} is not an origin like https://name.example")
    rel = lambda v: None if v is None else (Path(v) if Path(v).is_absolute() else root / v)  # noqa: E731
    cfg["config_path"] = str(p)
    cfg["config_found"] = p.is_file()
    cfg["users_path"] = rel(cfg["users_file"])
    cfg["sessions_path"] = rel(cfg["sessions_file"])
    cfg["audit_path"] = rel(cfg["audit_file"])
    cfg["static_path"] = rel(cfg["static_dir"])
    cfg["tls"] = (rel(cfg["remote"]["tls_cert"]), rel(cfg["remote"]["tls_key"])) if cfg["remote"]["tls_cert"] else None
    return cfg


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# --------------------------------------------------------------------------- this computer's addresses
def local_addresses():
    """IPv4 addresses of this computer (LAN, Tailscale ...), best effort and without sending anything."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:  # the address of the default route (UDP connect sends no packet)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def describe_address(addr):
    ip = ipaddress.ip_address(addr)
    if ip in TAILSCALE_NET:
        return "tailscale"
    if ip.is_private:
        return "lan"
    return "public"


# --------------------------------------------------------------------------- request checks
class HostPolicy:
    """Which Host headers and Origins a listener accepts (DNS-rebinding and cross-site protection).

    local listener: only localhost names. remote listener: localhost, this computer's names and addresses,
    and the configured extra hosts / origins."""

    def __init__(self, cfg, kind, port):
        self.kind, self.port = kind, port
        names = {"localhost", "127.0.0.1", "::1"}
        self.origins = set()
        if kind == "public":  # the tunnel's public name only; never the machine's LAN names or addresses
            url = cfg["public"]["url"]
            self.hosts = {n for n in names | {(urlparse(url or "").hostname or "").lower()} if n}
            if url:
                u = urlparse(url)
                self.origins.add(f"{u.scheme}://{u.netloc}".lower())
            return
        if kind == "remote":
            host = socket.gethostname().lower()
            names |= {host, f"{host}.local", *local_addresses()}
            names |= {h.lower() for h in cfg["allowed_hosts"]}
            if cfg.get("public_url"):
                names.add((urlparse(cfg["public_url"]).hostname or "").lower())
            bound = cfg["remote"]["host"]
            if bound not in ("0.0.0.0", "::", ""):
                names.add(bound.lower())
        self.hosts = {n for n in names if n}
        self.origins = {o.rstrip("/").lower() for o in cfg["allowed_origins"]}
        if cfg.get("public_url"):
            u = urlparse(cfg["public_url"])
            self.origins.add(f"{u.scheme}://{u.netloc}".lower())

    def refresh_addresses(self):
        """Addresses change (DHCP, VPN up): accept the current ones too."""
        if self.kind == "remote":
            self.hosts |= set(local_addresses())

    @staticmethod
    def _hostname(host_header):
        h = (host_header or "").strip().lower()
        if h.startswith("["):  # [::1]:8765
            return h[1:h.index("]")] if "]" in h else h
        return h.rsplit(":", 1)[0] if h.count(":") == 1 else h

    def host_ok(self, host_header):
        name = self._hostname(host_header)
        if name in self.hosts:
            return True
        if self.kind == "remote" and name[:1].isdigit():  # an address this computer may have gained since
            self.refresh_addresses()
            return name in self.hosts
        return False

    def origin_ok(self, origin, host_header):
        if not origin:
            return True  # same-origin GETs and non-browser clients send none; POSTs need the CSRF token anyway
        if origin == "null":
            return False
        o = origin.rstrip("/").lower()
        if o in self.origins:
            return True
        u = urlparse(o)
        # Same origin as the address the browser used (Host), or an accepted host of this computer.
        return (u.netloc == (host_header or "").lower()) or (u.hostname or "") in self.hosts


def connection_info(cfg, remote_running):
    """What the Network page shows: how to reach the Studio from another computer."""
    rc = cfg["remote"]
    scheme = "https" if cfg["tls"] else "http"
    addrs = local_addresses()
    urls = []
    if remote_running:
        hosts = addrs if rc["host"] in ("0.0.0.0", "::", "") else [rc["host"]]
        if rc["auth"] == "cloudflare_access":
            hosts = []  # only the public https address works: direct requests have no Access token
        urls = [{"url": f"{scheme}://{a}:{rc['port']}/", "kind": describe_address(a) if a[0].isdigit() else "name",
                 "encrypted": scheme == "https"} for a in hosts]
    if cfg.get("public_url"):
        urls.insert(0, {"url": cfg["public_url"], "kind": "public_url",
                        "encrypted": cfg["public_url"].startswith("https://")})
    return {
        "local_url": f"http://{cfg['local']['host']}:{cfg['local']['port']}/",
        "remote": {"enabled": bool(rc["enabled"]), "running": remote_running, "host": rc["host"],
                   "port": rc["port"], "tls": bool(cfg["tls"]), "auth": rc["auth"]},
        "urls": urls,
        "addresses": [{"address": a, "kind": describe_address(a)} for a in addrs],
        "hostname": socket.gethostname(),
        "allowed_hosts": sorted(cfg["allowed_hosts"]),
        "allowed_origins": sorted(cfg["allowed_origins"]),
        "public_url": cfg.get("public_url"),
        "config_file": CONFIG_REL if cfg["config_found"] else None,
        "session": cfg["session"],
        "public": {"enabled": bool(cfg["public"]["enabled"]), "url": cfg["public"]["url"]},
    }
