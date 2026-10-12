"""Network settings of the Studio server: listeners, allowed host names and origins, connection info.

The server has two kinds of listener (docs/remote-access.md):
- **local**: the host computer's own address (127.0.0.1 by default). It is the trusted local administrator
  context: no sign-in, and the only place where the game can be installed into or restored.
- **remote** (off unless enabled): the LAN / Tailscale address. Every API and audio request needs a signed-in
  account; installing into or restoring the game is refused whatever the role.

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
    "remote": {"enabled": False, "host": "0.0.0.0", "port": 8766, "tls_cert": None, "tls_key": None},
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
            out[k] = _merge(base[k], v, f"{where}.{k}")
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
    if cfg["secure_cookies"] not in ("auto", True, False):
        raise ConfigError("secure_cookies must be \"auto\", true or false")
    if cfg["remote"]["enabled"] and cfg["remote"]["port"] == cfg["local"]["port"]:
        raise ConfigError("the remote listener needs its own port")
    if bool(cfg["remote"]["tls_cert"]) != bool(cfg["remote"]["tls_key"]):
        raise ConfigError("remote.tls_cert and remote.tls_key go together")
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
        urls = [{"url": f"{scheme}://{a}:{rc['port']}/", "kind": describe_address(a) if a[0].isdigit() else "name",
                 "encrypted": scheme == "https"} for a in hosts]
    if cfg.get("public_url"):
        urls.insert(0, {"url": cfg["public_url"], "kind": "public_url",
                        "encrypted": cfg["public_url"].startswith("https://")})
    return {
        "local_url": f"http://{cfg['local']['host']}:{cfg['local']['port']}/",
        "remote": {"enabled": bool(rc["enabled"]), "running": remote_running, "host": rc["host"],
                   "port": rc["port"], "tls": bool(cfg["tls"])},
        "urls": urls,
        "addresses": [{"address": a, "kind": describe_address(a)} for a in addrs],
        "hostname": socket.gethostname(),
        "allowed_hosts": sorted(cfg["allowed_hosts"]),
        "allowed_origins": sorted(cfg["allowed_origins"]),
        "public_url": cfg.get("public_url"),
        "config_file": CONFIG_REL if cfg["config_found"] else None,
        "session": cfg["session"],
    }
