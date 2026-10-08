"""Minimal, deterministic one-entry patcher for MCC string tables (B1 PoC step 2).

Pure functions on bytes: nothing here reads or writes files. Layout per mcc_loc.py
(docs/subtitle-research.md B.4). Only same-byte-length replacement is supported, so the
file size and every header field stay unchanged and the only differing bytes lie inside
the target entry. Variable-length edits are a later, separately approved step.
"""
import struct

from .mcc_loc import parse_mcc_loc

HEADER_FIELDS = {"size_a": 0x04, "size_b": 0x08, "name_hash": 0x28, "payload": 0x68, "field_70": 0x70,
                 "key_bytes": 0x78, "string_bytes": 0x7C}


def header_fields(data):
    return {k: struct.unpack_from("<I", data, off)[0] for k, off in HEADER_FIELDS.items()}


def raw_entries(data):
    """-> (parsed, [(start, end)] byte spans of each string, excluding its NUL)."""
    t = parse_mcc_loc(data)
    pos = t["pool_offset"]
    spans = []
    for _ in range(t["key_count"]):
        end = data.index(b"\0", pos)
        spans.append((pos, end))
        pos = end + 1
    return t, spans


def find_key_once(keys, key):
    hits = [i for i, k in enumerate(keys) if k == key]
    if len(hits) != 1:
        raise ValueError(f"key 0x{key:08X} found {len(hits)} times (need exactly 1)")
    return hits[0]


def rebuild(data, replace=None):
    """Re-serialise a table from its model (header template, keys, raw strings, filler).

    `replace` = {index: new_bytes}. Size fields (0x04, 0x08, 0x68, 0x7C) are recomputed;
    other header bytes are copied. With replace=None the result must equal `data`.
    """
    t, spans = raw_entries(data)
    strings = [data[s:e] for s, e in spans]
    for i, b in (replace or {}).items():
        strings[i] = b
    pool_start = t["pool_offset"]
    used_orig = spans[-1][1] + 1 - pool_start if spans else 0
    inner_filler = t["string_data_length"] - used_orig
    tail = len(data) - (pool_start + t["string_data_length"])
    pool = b"".join(s + b"\0" for s in strings)
    string_bytes = len(pool) + inner_filler
    body = data[0x80:pool_start] + pool + b"\0" * inner_filler + b"\0" * tail
    head = bytearray(data[:0x80])
    size = 0x80 + len(body)
    struct.pack_into("<II", head, 0x04, size - 16, size - 16)
    struct.pack_into("<I", head, 0x68, 8 + t["key_count"] * 4 + string_bytes)
    struct.pack_into("<I", head, 0x7C, string_bytes)
    return bytes(head) + body


def marker_bytes(marker, length, pad=b"."):
    """ASCII marker padded with `pad` to exactly `length` bytes."""
    m = marker.encode("ascii")
    if b"\0" in m or len(m) > length:
        raise ValueError(f"marker must be NUL-free and at most {length} bytes")
    return m + pad * (length - len(m))


def patch_entry_same_length(data, key, new_bytes):
    """Replace the entry for `key` with `new_bytes` (same UTF-8 byte length). -> (patched, info)."""
    if b"\0" in new_bytes:
        raise ValueError("replacement contains NUL")
    new_bytes.decode("utf-8")  # must be valid UTF-8
    t, spans = raw_entries(data)
    i = find_key_once(t["keys"], key)
    start, end = spans[i]
    if len(new_bytes) != end - start:
        raise ValueError(f"replacement is {len(new_bytes)} bytes, entry is {end - start} (same length required)")
    patched = data[:start] + new_bytes + data[end:]
    if rebuild(data, {i: new_bytes}) != patched:
        raise AssertionError("splice and model rebuild disagree")
    return patched, {"entry_index": i, "entry_offset": start, "entry_bytes": end - start}


def verify_patch(original, patched, key, expected):
    """Independent checks of a candidate. -> dict of named booleans (all must be True)."""
    o, o_spans = raw_entries(original)
    p, p_spans = raw_entries(patched)
    i = find_key_once(p["keys"], key)
    s, e = p_spans[i]
    diff = [n for n, (a, b) in enumerate(zip(original, patched)) if a != b]
    checks = {
        "unmodified_rebuild_identical": rebuild(original) == original,
        "patched_rebuild_identical": rebuild(patched) == patched,
        "same_size": len(original) == len(patched),
        "header_fields_identical": header_fields(original) == header_fields(patched),
        "header_ok": all(p[k] for k in ("name_hash_matches", "size_fields_match", "payload_size_matches",
                                        "keys_ascending", "filler_is_zero")),
        "table_name_unchanged": o["name"] == p["name"],
        "keys_identical": o["keys"] == p["keys"],
        "key_found_once": True,  # find_key_once raised otherwise
        "same_entry_index": i == find_key_once(o["keys"], key),
        "target_is_expected": patched[s:e] == expected,
        "other_entries_identical": all(original[a:b] == patched[c:d]
                                       for n, ((a, b), (c, d)) in enumerate(zip(o_spans, p_spans)) if n != i),
        "spans_identical": o_spans == p_spans,
        "diff_inside_target_entry": bool(diff) and s <= diff[0] and diff[-1] < e,
        "target_utf8_valid": _utf8_ok(patched[s:e]),
    }
    return checks, {"entry_index": i, "entry_offset": s, "entry_bytes": e - s, "differing_bytes": len(diff),
                    "first_diff": diff[0] if diff else None, "last_diff": diff[-1] if diff else None}


def _utf8_ok(b):
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
