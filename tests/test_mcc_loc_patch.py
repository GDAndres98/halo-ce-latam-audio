"""Synthetic tests for the one-entry MCC string-table patcher (no game data)."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common.mcc_loc import MAGIC, crc32_mpeg2, loc_key, parse_mcc_loc  # noqa: E402
from common.mcc_loc_patch import (header_fields, marker_bytes, patch_entry_same_length,  # noqa: E402
                                  raw_entries, rebuild, verify_patch)


def build(keys, strings, name=b"SU_Halo1", inner_pad=3, tail_pad=2):
    """Synthetic table in the layout verified 2026-10-08 (docs/subtitle-research.md B.4)."""
    data = b"".join(s.encode("utf-8") + b"\0" for s in strings) + b"\0" * inner_pad
    body = struct.pack(f"<{len(keys)}I", *keys) + data + b"\0" * tail_pad
    b = bytearray(0x80)
    size = 0x80 + len(body)
    struct.pack_into("<III", b, 0, MAGIC, size - 16, size - 16)
    struct.pack_into("<I", b, 0x28, crc32_mpeg2(name.upper()))
    struct.pack_into("<I", b, 0x40, MAGIC)
    b[0x44:0x44 + len(name)] = name
    struct.pack_into("<I", b, 0x68, 8 + 4 * len(keys) + len(data))
    struct.pack_into("<I", b, 0x70, 8)
    struct.pack_into("<II", b, 0x78, 4 * len(keys), len(data))
    return bytes(b) + body


TAG = "sound\\dialog\\a10\\a10_350_captkeyes"
KEY = loc_key(TAG)
KEYS = sorted([0x00000010, KEY, 0x9000_0000, 0xFFEE_B88E])
TEXTS = {0x00000010: "Menú", KEY: "Jefe Maestro, ¿qué tal?", 0x9000_0000: "", 0xFFEE_B88E: "Señal\tfin"}


def table(name=b"SU_Halo1"):
    return build(KEYS, [TEXTS[k] for k in KEYS], name=name)


class PatchTests(unittest.TestCase):
    def test_key_rule_matches_pinned_value(self):
        self.assertEqual(KEY, 0x26FA1B53)

    def test_rebuild_unmodified_is_byte_identical(self):
        for pads in ((0, 0), (3, 2), (7, 13)):
            data = build(KEYS, [TEXTS[k] for k in KEYS], inner_pad=pads[0], tail_pad=pads[1])
            self.assertEqual(rebuild(data), data)

    def test_rebuild_recomputes_size_fields_for_variable_length(self):
        data = table()
        i = KEYS.index(KEY)
        longer = rebuild(data, {i: b"a much longer replacement text"})
        t = parse_mcc_loc(longer)
        self.assertTrue(t["size_fields_match"] and t["payload_size_matches"] and t["filler_is_zero"])
        self.assertEqual(t["entries"][KEY], "a much longer replacement text")

    def test_same_length_patch_changes_only_target_entry(self):
        data = table()
        _, spans = raw_entries(data)
        n = spans[KEYS.index(KEY)][1] - spans[KEYS.index(KEY)][0]
        new = marker_bytes("[B1-SU] a10_350", n)
        patched, info = patch_entry_same_length(data, KEY, new)
        checks, diff = verify_patch(data, patched, KEY, new)
        self.assertTrue(all(checks.values()), checks)
        self.assertEqual(len(patched), len(data))
        self.assertEqual(header_fields(patched), header_fields(data))
        t = parse_mcc_loc(patched)
        self.assertEqual(t["entries"][KEY], new.decode("ascii"))
        for k in KEYS:
            if k != KEY:
                self.assertEqual(t["entries"][k], TEXTS[k])
        self.assertTrue(info["entry_offset"] <= diff["first_diff"] <= diff["last_diff"]
                        < info["entry_offset"] + info["entry_bytes"])

    def test_patch_is_deterministic(self):
        data = table()
        n = len(TEXTS[KEY].encode("utf-8"))
        a, _ = patch_entry_same_length(data, KEY, marker_bytes("[B1-SP] a10_350", n))
        b, _ = patch_entry_same_length(data, KEY, marker_bytes("[B1-SP] a10_350", n))
        self.assertEqual(a, b)

    def test_each_table_patched_independently_with_own_name(self):
        su, sp = table(b"SU_Halo1"), table(b"SP_Halo1")
        n = len(TEXTS[KEY].encode("utf-8"))
        psu, _ = patch_entry_same_length(su, KEY, marker_bytes("[B1-SU] a10_350", n))
        psp, _ = patch_entry_same_length(sp, KEY, marker_bytes("[B1-SP] a10_350", n))
        self.assertEqual(parse_mcc_loc(psu)["name"], "SU_Halo1")
        self.assertEqual(parse_mcc_loc(psp)["name"], "SP_Halo1")
        self.assertTrue(parse_mcc_loc(psu)["name_hash_matches"] and parse_mcc_loc(psp)["name_hash_matches"])
        self.assertTrue(parse_mcc_loc(psu)["entries"][KEY].startswith("[B1-SU]"))
        self.assertTrue(parse_mcc_loc(psp)["entries"][KEY].startswith("[B1-SP]"))

    def test_refuses_wrong_length_nul_missing_and_duplicate_keys(self):
        data = table()
        with self.assertRaises(ValueError):
            patch_entry_same_length(data, KEY, b"short")
        n = len(TEXTS[KEY].encode("utf-8"))
        with self.assertRaises(ValueError):
            patch_entry_same_length(data, KEY, b"\0" * n)
        with self.assertRaises(ValueError):
            patch_entry_same_length(data, 0x12345678, b"x" * n)
        dup = build([1, KEY, KEY, 0xF0000000], ["a", "b", "c", "d"])
        with self.assertRaises(ValueError):  # not strictly ascending -> parser refuses
            patch_entry_same_length(dup, KEY, b"x")

    def test_refuses_invalid_utf8(self):
        data = table()
        n = len(TEXTS[KEY].encode("utf-8"))
        with self.assertRaises(UnicodeDecodeError):
            patch_entry_same_length(data, KEY, b"\xff" * n)

    def test_marker_padding(self):
        self.assertEqual(marker_bytes("[B1-SU] a10_350", 20), b"[B1-SU] a10_350.....")
        with self.assertRaises(ValueError):
            marker_bytes("[B1-SU] a10_350", 5)
        with self.assertRaises(UnicodeEncodeError):
            marker_bytes("señal", 10)

    def test_verify_detects_collateral_change(self):
        data = table()
        n = len(TEXTS[KEY].encode("utf-8"))
        new = marker_bytes("[B1-SU] a10_350", n)
        patched, _ = patch_entry_same_length(data, KEY, new)
        _, spans = raw_entries(patched)
        s = spans[0][0]
        tampered = patched[:s] + b"X" + patched[s + 1:]  # alter another entry
        checks, _ = verify_patch(data, tampered, KEY, new)
        self.assertFalse(checks["other_entries_identical"])
        self.assertFalse(checks["diff_inside_target_entry"])


if __name__ == "__main__":
    unittest.main()
