"""Central audio export settings shared by the M6 build and the M4 preview.

    config/audio_export.json   (optional; schema audio-export-config/1)
    {"schema": "audio-export-config/1", "global_gain_db": 4.0}

`global_gain_db` is applied once to every Campaign Evolved replacement, after the edit recipe and
before CELT encoding (common/audio_edit.render). Without the file the
default (+4 dB; owner decisions: +3 dB on 2026-10-09, raised to +4 dB on 2026-10-10) is used. Mappings are never touched by this setting.
"""
import hashlib
import json
from pathlib import Path

from .jsonschema_lite import load_schema, validate

CONFIG = "config/audio_export.json"
SCHEMA = "audio-export-config-1"
DEFAULT_GLOBAL_GAIN_DB = 4.0
GAIN_RANGE_DB = (-12.0, 12.0)


class ConfigError(ValueError):
    pass


def load_export_config(root):
    """-> {"global_gain_db", "source", "sha256"}. source is the file path, or "default" without a file."""
    p = Path(root) / CONFIG
    if not p.is_file():
        return {"global_gain_db": DEFAULT_GLOBAL_GAIN_DB, "source": "default", "sha256": None}
    data = p.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise ConfigError(f"{CONFIG}: invalid JSON ({e})")
    errs = validate(doc, load_schema(SCHEMA))
    if errs:
        raise ConfigError(f"{CONFIG}: " + "; ".join(errs[:3]))
    return {"global_gain_db": float(doc.get("global_gain_db", DEFAULT_GLOBAL_GAIN_DB)), "source": CONFIG,
            "sha256": hashlib.sha256(data).hexdigest()}


def save_global_gain(root, gain_db, loaded_sha256, *, now=None):
    """Writes config/audio_export.json with a new global gain. The Studio's only way to change it.

    loaded_sha256 is the hash of the file the caller read (None for "no file yet"): a file that changed
    since is refused, as for the decisions. The previous file is kept in config/.history/. Returns the
    new settings as load_export_config reports them."""
    gain = float(gain_db)
    if not (GAIN_RANGE_DB[0] <= gain <= GAIN_RANGE_DB[1]):
        raise ConfigError(f"global gain must be between {GAIN_RANGE_DB[0]:g} and {GAIN_RANGE_DB[1]:g} dB")
    path = Path(root) / CONFIG
    current = path.read_bytes() if path.is_file() else None
    current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
    if current_sha != loaded_sha256:
        raise ConfigError(f"{CONFIG} changed since it was loaded; reload the settings and try again")
    data = (json.dumps({"schema": "audio-export-config/1", "global_gain_db": gain}, indent=2) + "\n").encode("utf-8")
    if current is not None:
        import datetime as dt
        history = path.parent / ".history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = (now or dt.datetime.now()).strftime("%Y%m%dT%H%M%S%f")
        (history / f"audio_export.{stamp}.{current_sha[:12]}.json").write_bytes(current)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return load_export_config(root)
