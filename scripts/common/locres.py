"""Read-only parser for Unreal .locres (versions 0-3).

Returns {namespace: {key: {"text": str, "source_hash": int}}}. Keys and
namespaces are the stable identifiers; the per-entry hashes are lookup
accelerators and are only kept for diagnostics.
"""
from .binreader import Reader

LOCRES_MAGIC = bytes.fromhex("0e147475674a03fc4a15909dc3377f1b")


def parse_locres(data):
    r = Reader(data)
    if data[:16] == LOCRES_MAGIC:
        r.pos = 16
        version = r.u8()
    else:
        version = 0  # legacy files have no magic
    strings = None
    if version >= 1:
        array_offset = r.i64()
        if version >= 2:
            r.u32()  # total entry count (informational)
        if array_offset != -1:
            save = r.pos
            r.pos = array_offset
            strings = []
            for _ in range(r.i32()):
                s = r.fstring()
                if version >= 2:
                    r.i32()  # ref count
                strings.append(s)
            r.pos = save
    out = {}
    for _ in range(r.u32()):
        if version >= 2:
            r.u32()  # namespace hash
        ns = r.fstring()
        entries = out.setdefault(ns, {})
        for _ in range(r.u32()):
            if version >= 2:
                r.u32()  # key hash
            key = r.fstring()
            source_hash = r.u32()
            text = strings[r.i32()] if version >= 1 else r.fstring()
            entries[key] = {"text": text, "source_hash": source_hash}
    return version, out
