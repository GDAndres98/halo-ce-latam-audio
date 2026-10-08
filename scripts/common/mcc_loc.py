"""Read-only parser for MCC shell string tables (Data/ui/localization/<LANG>_<Game>.bin).

What is VERIFIED vs INFERRED is spelled out per field; see
docs/subtitle-research.md. The key -> string association is NOT known, so
this module deliberately exposes keys and the string pool separately and
never pairs them.
"""
import struct

MAGIC = 0x90CE6B7A
SPEAKER_SEP = ""  # private-use separator between speaker label and line (EN only)


def parse_mcc_loc(data):
    magic0, = struct.unpack_from("<I", data, 0)
    magic1, = struct.unpack_from("<I", data, 0x40)
    if magic0 != MAGIC or magic1 != MAGIC:
        raise ValueError("not an MCC localization table")
    name = data[0x44:0x68].split(b"\0")[0].decode("ascii")
    payload_size, = struct.unpack_from("<I", data, 0x68)
    field_70, = struct.unpack_from("<I", data, 0x70)
    last_key_offset, = struct.unpack_from("<I", data, 0x78)
    # INFERRED: 0x78 holds the byte offset of the last key relative to 0x7C,
    # so key_count = offset/4 + 1. Verified only by the keys being strictly
    # ascending and the string pool starting right after them.
    if last_key_offset % 4:
        raise ValueError("unexpected key-table size field")
    count = last_key_offset // 4 + 1
    keys = list(struct.unpack_from(f"<{count}I", data, 0x7C))
    if any(b <= a for a, b in zip(keys, keys[1:])):
        raise ValueError("key table is not strictly ascending")
    pool_start = 0x7C + 4 * count
    pool = data[pool_start:]
    segments = pool.split(b"\0")
    if segments and segments[-1] == b"":
        segments = segments[:-1]
    strings = [s.decode("utf-8", errors="replace") for s in segments]
    return {
        "name": name,
        "payload_size_field": payload_size,
        "field_0x70": field_70,
        "key_count": count,
        "keys": keys,
        "pool_offset": pool_start,
        "pool_bytes": len(pool),
        "strings": strings,
    }


def split_speaker(s):
    """'cor&idCORTANA\\ue900text' -> ('cor', 'CORTANA', 'text'); None if no speaker label."""
    if SPEAKER_SEP not in s:
        return None
    label, text = s.split(SPEAKER_SEP, 1)
    if "&id" not in label:
        return None
    abbr, display = label.split("&id", 1)
    return abbr, display, text
