"""Central audio export settings shared by the M6 build and the M4 preview.

    config/audio_export.json   (optional; schema audio-export-config/1)
    {"schema": "audio-export-config/1", "global_gain_db": 4.0, "level_mode": "global_gain"}

`level_mode` chooses how every Campaign Evolved replacement's level is set, after the edit recipe and before
CELT encoding (common/audio_edit.render):
  global_gain  (default) `global_gain_db` is applied once, linearly, never limited. Without the file the default
               +4 dB is used (owner decisions: +3 dB on 2026-10-09, raised to +4 dB on 2026-10-10).
  match_spain  each line is matched to the loudness of the Spain recording it replaces, with a look-ahead
               limiter capped at audio_edit.MATCH_MAX_LIMITING_DB (owner, 2026-10-11, after the
               measurements in docs/m6-build.md §2.3). The global gain is kept but not used.
Both are build-level settings, never part of a mapping. Mappings are never touched by them.
"""
import hashlib
import json
from pathlib import Path

from .jsonschema_lite import load_schema, validate

CONFIG = "config/audio_export.json"
SCHEMA = "audio-export-config-1"
DEFAULT_GLOBAL_GAIN_DB = 4.0
GAIN_RANGE_DB = (-12.0, 12.0)
LEVEL_MODES = ("global_gain", "match_spain")
DEFAULT_LEVEL_MODE = "global_gain"


class ConfigError(ValueError):
    pass


def load_export_config(root):
    """-> {"global_gain_db", "level_mode", "source", "sha256"}. source is the file path, or "default" without
    a file."""
    p = Path(root) / CONFIG
    if not p.is_file():
        return {"global_gain_db": DEFAULT_GLOBAL_GAIN_DB, "level_mode": DEFAULT_LEVEL_MODE, "source": "default",
                "sha256": None}
    data = p.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise ConfigError(f"{CONFIG}: invalid JSON ({e})")
    errs = validate(doc, load_schema(SCHEMA))
    if errs:
        raise ConfigError(f"{CONFIG}: " + "; ".join(errs[:3]))
    return {"global_gain_db": float(doc.get("global_gain_db", DEFAULT_GLOBAL_GAIN_DB)),
            "level_mode": doc.get("level_mode", DEFAULT_LEVEL_MODE), "source": CONFIG,
            "sha256": hashlib.sha256(data).hexdigest()}


def save_global_gain(root, gain_db, loaded_sha256, *, level_mode=None, now=None):
    """Writes config/audio_export.json with a new global gain and/or level mode. The Studio's only way to
    change them. gain_db None keeps the current gain (then level_mode is required); level_mode None keeps the
    current mode.

    loaded_sha256 is the hash of the file the caller read (None for "no file yet"): a file that changed
    since is refused, as for the decisions. The previous file is kept in config/.history/. Returns the
    new settings as load_export_config reports them."""
    now_cfg = load_export_config(root)
    if gain_db is None and level_mode is None:
        raise ConfigError("nothing to save: give a global gain or a level mode")
    gain = now_cfg["global_gain_db"] if gain_db is None else float(gain_db)
    mode = now_cfg["level_mode"] if level_mode is None else level_mode
    if not (GAIN_RANGE_DB[0] <= gain <= GAIN_RANGE_DB[1]):
        raise ConfigError(f"global gain must be between {GAIN_RANGE_DB[0]:g} and {GAIN_RANGE_DB[1]:g} dB")
    if mode not in LEVEL_MODES:
        raise ConfigError(f"level mode must be one of {', '.join(LEVEL_MODES)}")
    path = Path(root) / CONFIG
    current = path.read_bytes() if path.is_file() else None
    current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
    if current_sha != loaded_sha256:
        raise ConfigError(f"{CONFIG} changed since it was loaded; reload the settings and try again")
    data = (json.dumps({"schema": "audio-export-config/1", "global_gain_db": gain, "level_mode": mode},
                       indent=2) + "\n").encode("utf-8")
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
