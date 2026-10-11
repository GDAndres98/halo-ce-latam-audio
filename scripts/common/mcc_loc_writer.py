"""Variable-length writer for MCC string tables (<LANG>_Halo1.bin): replace any entry's text.

Pure functions on bytes; nothing here reads or writes files. The layout is mcc_loc.py's
(docs/subtitle-research.md B.4). Two serialisation rules were found on 2026-10-11 and hold for all 25
shipped tables (Halo1, Global, Debug, DBG; B.13):

  1. L (0x7C, string-data bytes) = sum(len(utf8) + 1 for every string) + number of LF bytes in the
     strings. The extra bytes are zeros right after the last string's NUL: the original tool counted
     each LF as CRLF. SU_Halo1 has 500 LFs and 500 slack bytes, SP_Halo1 539 and 539.
  2. After the L bytes, zeros pad the file to a multiple of 8.

The header is copied from the original except the four derived fields: 0x04 = 0x08 = file size - 16,
0x68 = 8 + 4n + L, 0x7C = L. Keys and their order never change, so string i still belongs to key i.

`table_model` refuses any input that its own serialiser does not reproduce byte for byte, so a table
with an unexpected structure is never rewritten. `write_table` changes only the requested entries,
and `verify_table` re-parses the result and checks it independently of the writer.
"""
import struct
import unicodedata

from .mcc_loc import MAGIC, crc32_mpeg2, parse_mcc_loc

WRITER = "mcc-loc-writer/1"
MAX_ENTRY_BYTES = 2048  # the longest shipped Halo1 entry is 811 bytes (SU); more is refused, not truncated
ALIGN = 8
DERIVED_FIELDS = {"size_a": 0x04, "size_b": 0x08, "payload": 0x68, "string_bytes": 0x7C}
FIXED_FIELDS = {"magic": 0x00, "name_hash": 0x28, "magic2": 0x40, "field_70": 0x70, "key_bytes": 0x78}
SPEAKER_SEP = ""


class TableError(ValueError):
    """The table, or a requested change, is not something this writer supports. Nothing is written."""


def table_model(data):
    """-> {"header": bytes(0x80), "name", "keys": [...], "strings": [bytes, ...]} for a canonical table.

    Raises TableError unless serialize(model) == data: magic, ascending unique keys, n strings, the LF
    slack and the 8-byte padding must all be exactly as rules 1 and 2 say."""
    try:
        t = parse_mcc_loc(data)
    except ValueError as e:
        raise TableError(f"not a supported MCC string table: {e}") from e
    if len(set(t["keys"])) != len(t["keys"]):
        raise TableError("duplicate keys in the table")
    pos, strings = t["pool_offset"], []
    for _ in range(t["key_count"]):
        end = data.index(b"\0", pos)
        strings.append(bytes(data[pos:end]))
        pos = end + 1
    model = {"header": bytes(data[:0x80]), "name": t["name"], "keys": list(t["keys"]), "strings": strings}
    if not (t["name_hash_matches"] and t["size_fields_match"] and t["payload_size_matches"]):
        raise TableError("header fields are inconsistent (name hash, size or payload field)")
    if serialize(model) != data:
        raise TableError("the table does not follow the verified layout (LF slack / 8-byte padding); "
                         "refusing to rewrite it")
    return model


def string_data_length(strings):
    return sum(len(s) + 1 for s in strings) + sum(s.count(b"\n") for s in strings)


def serialize(model):
    """Model -> table bytes, recomputing the four derived header fields."""
    keys, strings = model["keys"], model["strings"]
    if len(keys) != len(strings):
        raise TableError("key and string counts differ")
    L = string_data_length(strings)
    pool = b"".join(s + b"\0" for s in strings) + b"\0" * sum(s.count(b"\n") for s in strings)
    body = struct.pack(f"<{len(keys)}I", *keys) + pool
    pad = (-(0x80 + len(body))) % ALIGN
    head = bytearray(model["header"])
    size = 0x80 + len(body) + pad
    struct.pack_into("<II", head, 0x04, size - 16, size - 16)
    struct.pack_into("<I", head, 0x68, 8 + 4 * len(keys) + L)
    struct.pack_into("<I", head, 0x78, 4 * len(keys))
    struct.pack_into("<I", head, 0x7C, L)
    return bytes(head) + body + b"\0" * pad


def normalize_text(text):
    """Owner text -> (text as stored, notes). CRLF/CR become LF (the tables hold LF only) and the text is
    NFC-normalised so accents are single code points. Nothing else changes."""
    notes = []
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    if t != text:
        notes.append("line breaks normalised to LF")
    n = unicodedata.normalize("NFC", t)
    if n != t:
        notes.append("Unicode normalised to NFC")
    return n, notes


def text_problems(text):
    """Reasons a text cannot go into a table (empty list = acceptable). The empty string is allowed: it is
    an approved "no subtitle" decision, and the shipped tables hold about 60 empty entries."""
    out = []
    if "\0" in text:
        out.append("contains NUL")
    bad = sorted({f"U+{ord(c):04X}" for c in text if (unicodedata.category(c) == "Cc" and c not in "\n\t")
                  or unicodedata.category(c) == "Cs" or c == SPEAKER_SEP})
    if bad:
        out.append("contains control or reserved characters " + ", ".join(bad))
    try:
        b = text.encode("utf-8")
    except UnicodeEncodeError:
        return out + ["not encodable as UTF-8"]
    if len(b) > MAX_ENTRY_BYTES:
        out.append(f"{len(b)} UTF-8 bytes (limit {MAX_ENTRY_BYTES})")
    return out


def write_table(data, changes):
    """changes: {key: text (str)} -> (new table bytes, info). Every key must exist exactly once; texts are
    normalised (normalize_text) and must pass text_problems. Untouched entries keep their exact bytes."""
    model = table_model(data)
    index = {k: i for i, k in enumerate(model["keys"])}
    strings = list(model["strings"])
    applied = {}
    for key in sorted(changes):
        if key not in index:
            raise TableError(f"key 0x{key:08X} is not in {model['name']}")
        text, notes = normalize_text(changes[key])
        problems = text_problems(text)
        if problems:
            raise TableError(f"key 0x{key:08X}: " + "; ".join(problems))
        i = index[key]
        new = text.encode("utf-8")
        applied[key] = {"index": i, "old_bytes": len(strings[i]), "new_bytes": len(new), "notes": notes,
                        "unchanged": new == strings[i]}
        strings[i] = new
    out = serialize(dict(model, strings=strings))
    return out, {"table": model["name"], "entries": len(model["keys"]), "changed": applied,
                 "size_before": len(data), "size_after": len(out)}


def verify_table(original, candidate, expected):
    """Independent checks that `candidate` is `original` with exactly the entries in `expected` ({key: text,
    already normalised}) replaced. -> dict of named booleans (all must be True). Uses mcc_loc's parser."""
    o, c = parse_mcc_loc(original), parse_mcc_loc(candidate)
    oraw, craw = _raw(original, o), _raw(candidate, c)
    idx = {k: i for i, k in enumerate(c["keys"])}
    want = {k: v.encode("utf-8") for k, v in expected.items()}
    exp_strings = [want.get(k, s) for k, s in zip(o["keys"], oraw)]
    L = string_data_length(craw)
    hdr = lambda d, off: struct.unpack_from("<I", d, off)[0]  # noqa: E731
    try:
        rebuilt = serialize(table_model(candidate)) == candidate
    except TableError:
        rebuilt = False
    return {
        "magic_and_name": hdr(candidate, 0) == MAGIC and hdr(candidate, 0x40) == MAGIC and c["name"] == o["name"],
        "name_hash_matches": c["name_hash_matches"] and hdr(candidate, 0x28) == crc32_mpeg2(o["name"].upper().encode()),
        "fixed_header_bytes_identical": all(original[a:b] == candidate[a:b] for a, b in
                                            ((0x00, 0x04), (0x0C, 0x68), (0x6C, 0x7C))),
        "size_fields": c["size_fields_match"],
        "payload_size_field": c["payload_size_matches"],
        "string_data_length_rule": c["string_data_length"] == L,
        "file_8_byte_aligned": len(candidate) % ALIGN == 0,
        "padding_is_zero": c["filler_is_zero"],
        "keys_identical_and_ordered": c["keys"] == o["keys"] and c["keys_ascending"],
        "key_count_unchanged": c["key_count"] == o["key_count"],
        "expected_keys_present": all(k in idx for k in want),
        "replaced_entries_expected": all(craw[idx[k]] == b for k, b in want.items() if k in idx),
        "untouched_entries_byte_identical": all(a == b for k, a, b in zip(o["keys"], oraw, craw) if k not in want),
        "all_entries_expected": craw == exp_strings,
        "utf8_valid": all(_utf8(s) for s in craw),
        "no_nul_in_entries": all(b"\0" not in s for s in craw),
        "reserialises_identically": rebuilt,
        "parser_entries_match": c["entries"] == {k: s.decode("utf-8") for k, s in zip(o["keys"], exp_strings)},
    }


def _raw(data, parsed):
    pos, out = parsed["pool_offset"], []
    for _ in range(parsed["key_count"]):
        end = data.index(b"\0", pos)
        out.append(bytes(data[pos:end]))
        pos = end + 1
    return out


def _utf8(b):
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def charset(tables):
    """Every character used in the given parsed tables (to warn about glyphs MCC may not have)."""
    return {ch for t in tables if t for s in t["strings"] for ch in s}
