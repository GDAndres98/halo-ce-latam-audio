"""Focused parser tests. All inputs are synthetic bytes built here --
no game data is read or stored by these tests.

Run: python -m unittest discover -s tests
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common.asset_metadata import fnv1_32  # noqa: E402
from common.binreader import Reader  # noqa: E402
from common.env import load_env  # noqa: E402
from common.iostore import TOC_MAGIC, parse_header  # noqa: E402
from common.locres import LOCRES_MAGIC, parse_locres  # noqa: E402
from common.mcc_loc import MAGIC as MCC_MAGIC, crc32_mpeg2, loc_key, parse_mcc_loc, split_speaker  # noqa: E402
from common.pak import FOOTER_SIZE, PAK_MAGIC, decode_entry, parse_footer  # noqa: E402
from common.usmap import PROPERTY_TYPES, Usmap  # noqa: E402
from common.zen import ZenPackage  # noqa: E402


def fstr(s):
    b = s.encode("utf-8") + b"\0"
    return struct.pack("<i", len(b)) + b


def fstr16(s):
    b = s.encode("utf-16-le") + b"\0\0"
    return struct.pack("<i", -(len(b) // 2)) + b


class ReaderTests(unittest.TestCase):
    def test_fstring_utf8_and_utf16(self):
        r = Reader(fstr("abc") + fstr16("ñé") + struct.pack("<i", 0))
        self.assertEqual(r.fstring(), "abc")
        self.assertEqual(r.fstring(), "ñé")
        self.assertEqual(r.fstring(), "")

    def test_read_past_end_raises(self):
        with self.assertRaises(ValueError):
            Reader(b"\x01").bytes(2)


class EnvTests(unittest.TestCase):
    def test_malformed_line_reported_and_windows_path_kept(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("A=C:\\x\\y\nUSMAP_FILEC:\\bad\n# c\n", encoding="utf-8")
            env, problems = load_env(p)
        self.assertEqual(env["A"], "C:\\x\\y")
        self.assertNotIn("USMAP_FILEC", env)
        self.assertEqual(len(problems), 1)


class LocresTests(unittest.TestCase):
    def build_v3(self, entries):
        strings = sorted({t for ns in entries.values() for t in ns.values()})
        body = struct.pack("<I", len(entries))
        for ns, keys in entries.items():
            body += struct.pack("<I", 0) + fstr(ns) + struct.pack("<I", len(keys))
            for k, t in keys.items():
                body += struct.pack("<I", 0) + fstr(k) + struct.pack("<I", 123) + struct.pack("<i", strings.index(t))
        head_len = 16 + 1 + 8 + 4
        array_off = head_len + len(body)
        arr = struct.pack("<i", len(strings)) + b"".join(fstr(s) + struct.pack("<i", 1) for s in strings)
        return LOCRES_MAGIC + bytes([3]) + struct.pack("<qI", array_off, 2) + body + arr

    def test_v3_namespace_key_lookup(self):
        data = self.build_v3({"VO_NS": {"VO_KEY_A": "hola", "VO_KEY_B": "adiós"}})
        version, table = parse_locres(data)
        self.assertEqual(version, 3)
        self.assertEqual(table["VO_NS"]["VO_KEY_A"]["text"], "hola")
        self.assertEqual(table["VO_NS"]["VO_KEY_B"]["text"], "adiós")
        self.assertEqual(table["VO_NS"]["VO_KEY_A"]["source_hash"], 123)


def build_usmap(names, enums, structs):
    """Minimal v4 usmap. structs: [(name, super, prop_count, [(idx, dim, pname, type_bytes)])]."""
    ni = {n: i for i, n in enumerate(names)}
    body = struct.pack("<I", len(names)) + b"".join(struct.pack("<H", len(n)) + n.encode() for n in names)
    body += struct.pack("<I", len(enums))
    for en, vals in enums:
        body += struct.pack("<IH", ni[en], len(vals))
        for v, vn in vals:
            body += struct.pack("<QI", v, ni[vn])
    body += struct.pack("<I", len(structs))
    for sn, sup, count, props in structs:
        body += struct.pack("<IIHH", ni[sn], ni[sup] if sup else 0xFFFFFFFF, count, len(props))
        for idx, dim, pn, tb in props:
            body += struct.pack("<HBI", idx, dim, ni[pn]) + tb
    return struct.pack("<HB", 0x30C4, 4) + struct.pack("<i", 0) + struct.pack("<BII", 0, len(body), len(body)) + body


T = {n: i for i, n in enumerate(PROPERTY_TYPES)}


def ty(name, *extra):
    return bytes([T[name]]) + b"".join(extra)


class UsmapAndUnversionedTests(unittest.TestCase):
    def setUp(self):
        names = ["Base", "Line", "Inner", "EKind", "Kind_A", "Kind_B", "Flag", "Count", "Key", "Items",
                 "Kind", "Dims", "Child", "Tag"]
        ni = {n: i for i, n in enumerate(names)}
        u32 = lambda v: struct.pack("<I", v)  # noqa: E731
        data = build_usmap(
            names,
            [("EKind", [(0, "Kind_A"), (1, "Kind_B")])],
            [
                ("Base", None, 1, [(0, 1, "Flag", ty("BoolProperty"))]),
                ("Inner", None, 1, [(0, 1, "Tag", ty("NameProperty"))]),
                ("Line", "Base", 6, [
                    (0, 1, "Count", ty("IntProperty")),
                    (1, 1, "Key", ty("StrProperty")),
                    (2, 1, "Items", ty("ArrayProperty", ty("StructProperty", u32(ni["Inner"])))),
                    (3, 1, "Kind", ty("EnumProperty", ty("ByteProperty"), u32(ni["EKind"]))),
                    (4, 2, "Dims", ty("FloatProperty")),
                ]),
            ])
        self.usmap = Usmap(data)

    def test_usmap_flattening_includes_super_and_array_dim(self):
        flat = self.usmap.flattened("Line")
        self.assertEqual([f[0] if f else None for f in flat],
                         ["Flag", "Count", "Key", "Items", "Kind", "Dims", "Dims"])
        self.assertEqual(flat[6][2], 1)
        self.assertEqual(self.usmap.enums["EKind"][1], "Kind_B")

    def make_pkg(self):
        pkg = object.__new__(ZenPackage)
        pkg.usmap = self.usmap
        pkg.names = ["None", "Hello"]
        return pkg

    @staticmethod
    def frag(skip, num, zeroes=False, last=False):
        return struct.pack("<H", skip | (0x80 if zeroes else 0) | (0x100 if last else 0) | (num << 9))

    def test_unversioned_fragments_zero_mask_nested_and_arrays(self):
        # schema: 0 Flag, 1 Count, 2 Key, 3 Items, 4 Kind, 5 Dims[0], 6 Dims[1]
        # serialize: skip Flag; Count(zero), Key, Items, Kind present; skip Dims[0]; Dims[1]
        inner = self.frag(0, 1, last=True) + struct.pack("<II", 1, 0)  # Inner{Tag=Hello}
        data = (self.frag(1, 4, zeroes=True) + self.frag(1, 1, last=True)
                + bytes([0b0001])                     # zero mask: first of the 4 (Count) is zero
                + fstr("VO_SCR_X")                    # Key
                + struct.pack("<i", 1) + inner        # Items
                + bytes([1])                          # Kind -> Kind_B
                + struct.pack("<f", 2.5))             # Dims[1]
        props = self.make_pkg().read_struct(Reader(data), "Line")
        self.assertEqual(props["Count"], {"_default": True})
        self.assertEqual(props["Key"], "VO_SCR_X")
        self.assertEqual(props["Items"], [{"Tag": {"name": "Hello"}}])
        self.assertEqual(props["Kind"], "Kind_B")
        self.assertEqual(props["Dims[1]"], 2.5)
        self.assertNotIn("Flag", props)
        self.assertNotIn("Dims", props)

    def test_text_string_table_entry(self):
        pkg = self.make_pkg()
        data = struct.pack("<Ib", 0, 11) + struct.pack("<II", 1, 0) + fstr("VO_KEY")
        self.assertEqual(pkg._text(Reader(data)),
                         {"text_history": "StringTableEntry", "flags": 0, "table_id": "Hello", "key": "VO_KEY"})


class PakTests(unittest.TestCase):
    def test_footer_parse_and_magic_check(self):
        names = b"Oodle".ljust(32, b"\0") + bytes(32 * 4)
        tail = bytes(16) + b"\0" + struct.pack("<IiQQ", PAK_MAGIC, 11, 1000, 50) + bytes(20) + names
        self.assertEqual(len(tail), FOOTER_SIZE)
        f = parse_footer(tail)
        self.assertEqual((f["version"], f["index_offset"], f["index_size"]), (11, 1000, 50))
        self.assertFalse(f["encrypted_index"])
        self.assertEqual(f["compression_methods"], ["Oodle"])
        with self.assertRaises(ValueError):
            parse_footer(tail[:17] + bytes(4) + tail[21:])

    def test_encoded_entry_uncompressed_32bit(self):
        flags = (1 << 31) | (1 << 30) | (1 << 29)
        enc = struct.pack("<III", flags, 4096, 777)
        e = decode_entry(enc, 0)
        self.assertEqual((e["offset"], e["usize"], e["size"], e["method"], e["encrypted"]), (4096, 777, 777, 0, False))
        self.assertEqual(e["header_size"], 53)

    def test_encoded_entry_flags_encryption(self):
        enc = struct.pack("<III", (1 << 31) | (1 << 30) | (1 << 22), 0, 10)
        self.assertTrue(decode_entry(enc, 0)["encrypted"])


class IoStoreHeaderTests(unittest.TestCase):
    def header(self, flags):
        b = bytearray(144)
        b[0:16] = TOC_MAGIC
        b[16] = 8
        struct.pack_into("<9I", b, 20, 144, 3, 0, 12, 1, 32, 65536, 0, 1)
        b[80] = flags
        return bytes(b)

    def test_flags(self):
        h = parse_header(self.header(0x09))
        self.assertTrue(h["compressed"] and h["indexed"])
        self.assertFalse(h["encrypted"])
        self.assertTrue(parse_header(self.header(0x02))["encrypted"])
        with self.assertRaises(ValueError):
            parse_header(b"x" * 144)


class WwiseIdTests(unittest.TestCase):
    def test_fnv1_matches_ids_observed_in_game_data(self):
        # Pairs observed in Campaign Evolved (bank/event IDs vs their names).
        self.assertEqual(fnv1_32("VO_SCR_M01"), 1447133044)
        self.assertEqual(fnv1_32("vo_sys_johnson"), 1422995586)
        self.assertEqual(fnv1_32("Play_VO_SCR_M01_00460_CryoTech"), 3768155368)


class MccLocTests(unittest.TestCase):
    """Synthetic tables in the layout verified 2026-10-08 (docs/subtitle-research.md B.4)."""

    def build(self, keys, strings, name=b"EN_Halo1", inner_pad=3, tail_pad=2):
        data = b"".join(s.encode("utf-8") + b"\0" for s in strings) + b"\0" * inner_pad
        body = struct.pack(f"<{len(keys)}I", *keys) + data + b"\0" * tail_pad
        b = bytearray(0x80)
        size = 0x80 + len(body)
        struct.pack_into("<III", b, 0, MCC_MAGIC, size - 16, size - 16)
        struct.pack_into("<I", b, 0x28, crc32_mpeg2(name.upper()))
        struct.pack_into("<I", b, 0x40, MCC_MAGIC)
        b[0x44:0x44 + len(name)] = name
        struct.pack_into("<I", b, 0x68, 8 + 4 * len(keys) + len(data))
        struct.pack_into("<I", b, 0x70, 8)
        struct.pack_into("<II", b, 0x78, 4 * len(keys), len(data))
        return bytes(b) + body

    def test_string_i_belongs_to_key_i_and_header_fields(self):
        t = parse_mcc_loc(self.build([5, 9, 0xFFFFFFF0], ["MENU", "cor&idCORTANA\ue900Hola", ""]))
        self.assertEqual(t["name"], "EN_Halo1")
        self.assertEqual(t["keys"], [5, 9, 0xFFFFFFF0])
        self.assertEqual(t["strings"], ["MENU", "cor&idCORTANA\ue900Hola", ""])
        self.assertEqual(t["entries"][9], "cor&idCORTANA\ue900Hola")
        self.assertEqual(t["pool_offset"], 0x80 + 12)
        self.assertTrue(t["name_hash_matches"] and t["size_fields_match"] and t["payload_size_matches"])
        self.assertTrue(t["filler_is_zero"])
        self.assertEqual(t["filler_bytes"], 5)

    def test_non_ascending_keys_rejected_unless_allowed(self):
        data = self.build([9, 5], ["a", "b"])
        with self.assertRaises(ValueError):
            parse_mcc_loc(data)
        self.assertFalse(parse_mcc_loc(data, allow_unsorted=True)["keys_ascending"])

    def test_too_few_strings_rejected(self):
        with self.assertRaises(ValueError):
            parse_mcc_loc(self.build([1, 2, 3], ["only one"], inner_pad=0, tail_pad=0))

    def test_key_hash_is_crc32_mpeg2_of_uppercase_label(self):
        self.assertEqual(crc32_mpeg2(b"123456789"), 0x0376E6E7)  # published CRC-32/MPEG-2 check value
        self.assertEqual(loc_key("sound\\dialog\\z10\\z10_010_test"), loc_key("SOUND\\DIALOG\\Z10\\Z10_010_TEST"))
        self.assertEqual(loc_key("abc"), crc32_mpeg2(b"ABC"))

    def test_split_speaker(self):
        self.assertEqual(split_speaker("cor&idCORTANA\ue900Hola"), ("cor", "CORTANA", "Hola"))
        self.assertIsNone(split_speaker("LOOK SENSITIVITY"))


if __name__ == "__main__":
    unittest.main()
