"""Central audio export settings shared by the M6 build and the M4 preview.

    config/audio_export.json   (optional; schema audio-export-config/1)
    {"schema": "audio-export-config/1", "global_gain_db": 3.0}

`global_gain_db` is applied once to every Campaign Evolved replacement, after the edit recipe and
the optional loudness match, before CELT encoding (common/audio_edit.render). Without the file the
default (+3 dB, owner decision 2026-10-09) is used. Mappings are never touched by this setting.
"""
import hashlib
import json
from pathlib import Path

from .jsonschema_lite import load_schema, validate

CONFIG = "config/audio_export.json"
SCHEMA = "audio-export-config-1"
DEFAULT_GLOBAL_GAIN_DB = 3.0
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
