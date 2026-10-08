"""Read-only parser for MCC shell string tables (Data/ui/localization/<LANG>_<Game>.bin).

Layout (VERIFIED 2026-10-08 on 25 shipped tables, see docs/subtitle-research.md
B.4; every Halo1/DBG/Debug table rebuilds byte-identically from this model):

    0x00 u32 magic 0x90CE6B7A      0x04 u32 file_size-16   0x08 u32 file_size-16
    0x28 u32 crc32_mpeg2(upper(table name))
    0x40 u32 magic 0x90CE6B7A      0x44 char[36] table name ("SP_Halo1")
    0x68 u32 8 + 4n + L            0x70 u32 8 (meaning unknown)
    0x78 u32 4n (key-table bytes)  0x7C u32 L (string-data bytes)
    0x80 u32 key[n]                strictly ascending (Halo1/DBG tables)
    ...  n NUL-terminated UTF-8 strings: string i belongs to key i
    ...  zero filler (inside L and after it) to the end of the file

key = crc32_mpeg2(upper(label), UTF-8). For Halo 1 dialogue subtitles the
label is the dialogue tag path, e.g. 'sound\\dialog\\a10\\a10_350_captkeyes'.
That rule is DERIVED (exact hash equality), not a game reference field, so a
catalog must label it that way and a human must confirm it in game before it
drives a build.

The *_Global tables share the header but their keys are not sorted; they are
only partly understood, and `allow_unsorted=True` is required to read them.
"""
import struct

MAGIC = 0x90CE6B7A
SPEAKER_SEP = ""  # private-use separator between speaker label and line (EN only)


def crc32_mpeg2(data):
    """CRC-32/MPEG-2: poly 0x04C11DB7, init 0xFFFFFFFF, no reflection, no final XOR."""
    c = 0xFFFFFFFF
    for x in data:
        c ^= x << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    return c


def loc_key(label):
    """Key of a string label in an MCC localization table."""
    return crc32_mpeg2(label.upper().encode("utf-8"))


def parse_mcc_loc(data, allow_unsorted=False):
    magic0, = struct.unpack_from("<I", data, 0)
    magic1, = struct.unpack_from("<I", data, 0x40)
    if magic0 != MAGIC or magic1 != MAGIC:
        raise ValueError("not an MCC localization table")
    name = data[0x44:0x68].split(b"\0")[0].decode("ascii")
    size_a, size_b = struct.unpack_from("<II", data, 4)
    name_hash, = struct.unpack_from("<I", data, 0x28)
    payload_size, = struct.unpack_from("<I", data, 0x68)
    field_70, = struct.unpack_from("<I", data, 0x70)
    key_bytes, string_bytes = struct.unpack_from("<II", data, 0x78)
    if key_bytes % 4:
        raise ValueError("unexpected key-table size field")
    n = key_bytes // 4
    keys = list(struct.unpack_from(f"<{n}I", data, 0x80))
    ascending = all(b > a for a, b in zip(keys, keys[1:]))
    if not ascending and not allow_unsorted:
        raise ValueError("key table is not strictly ascending")
    pool_start = 0x80 + key_bytes
    raw = data[pool_start:pool_start + string_bytes].split(b"\0")
    if len(raw) - 1 < n:
        raise ValueError(f"{n} keys but only {len(raw) - 1} strings")
    strings = [s.decode("utf-8", errors="replace") for s in raw[:n]]
    used = sum(len(s) + 1 for s in raw[:n])
    filler = data[pool_start + used:]
    return {
        "name": name,
        "name_hash_field": name_hash,
        "name_hash_matches": name_hash == crc32_mpeg2(name.upper().encode("ascii")),
        "size_fields_match": size_a == size_b == len(data) - 16,
        "payload_size_field": payload_size,
        "payload_size_matches": payload_size == 8 + key_bytes + string_bytes,
        "field_0x70": field_70,
        "key_count": n,
        "keys": keys,
        "keys_ascending": ascending,
        "pool_offset": pool_start,
        "string_data_length": string_bytes,
        "pool_bytes": len(data) - pool_start,    # string data + filler (kept for older callers)
        "strings": strings,                      # strings[i] belongs to keys[i]
        "entries": dict(zip(keys, strings)),
        "filler_bytes": len(filler),
        "filler_is_zero": not filler.strip(b"\0"),
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
