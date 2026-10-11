"""Variable-length MCC string-table writer (common/mcc_loc_writer.py).

Synthetic tables in the canonical layout, plus the hash-verified copies of the shipped SU/SP tables when they
are present locally (work/mcc/loc/copies/, git-ignored; those tests are skipped elsewhere). Nothing is written
outside memory.

Run: python -m unittest tests.test_mcc_loc_writer
"""
import hashlib
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common.mcc_loc import MAGIC, crc32_mpeg2, loc_key, parse_mcc_loc  # noqa: E402
from common.mcc_loc_writer import (TableError, normalize_text, serialize, table_model, text_problems,  # noqa: E402
                                   verify_table, write_table)

COPIES = ROOT / "work" / "mcc" / "loc" / "copies"
PINS = {"SU": "247d25298af3d5f990cd20ff5177e05078173347b7bdf395c3995a59c60244d0",
        "SP": "794deac326d401a1fb6f5de50f8979f921159a412b095a368ef5424ed4342dda"}


def canonical(keys, strings, name=b"SU_Halo1"):
    """A table as the shipped ones are laid out: LF slack inside L, zero padding to 8 bytes."""
    enc = [s.encode("utf-8") for s in strings]
    L = sum(len(s) + 1 for s in enc) + sum(s.count(b"\n") for s in enc)
    body = struct.pack(f"<{len(keys)}I", *keys) + b"".join(s + b"\0" for s in enc) + b"\0" * sum(s.count(b"\n") for s in enc)
    pad = (-(0x80 + len(body))) % 8
    b = bytearray(0x80)
    size = 0x80 + len(body) + pad
    struct.pack_into("<III", b, 0, MAGIC, size - 16, size - 16)
    struct.pack_into("<I", b, 0x28, crc32_mpeg2(name.upper()))
    struct.pack_into("<I", b, 0x40, MAGIC)
    b[0x44:0x44 + len(name)] = name
    struct.pack_into("<I", b, 0x68, 8 + 4 * len(keys) + L)
    struct.pack_into("<I", b, 0x70, 8)
    struct.pack_into("<II", b, 0x78, 4 * len(keys), L)
    return bytes(b) + body + b"\0" * pad


TAG = "sound\\dialog\\a10\\a10_350_captkeyes"
K1, K2, K3, K4, K5 = sorted([0x10, loc_key(TAG), 0x9000_0000, 0xA000_0000, 0xFFEE_B88E])
TEXTS = {K1: "Menú", K2: "Jefe Maestro, ¿qué tal?", K3: "", K4: "Línea uno\nLínea dos", K5: "Señal\tfin"}


def table(name=b"SU_Halo1"):
    return canonical(sorted(TEXTS), [TEXTS[k] for k in sorted(TEXTS)], name)


class ModelTests(unittest.TestCase):
    def test_canonical_tables_round_trip(self):
        t = table()
        self.assertEqual(serialize(table_model(t)), t)
        self.assertEqual(len(t) % 8, 0)
        self.assertEqual(parse_mcc_loc(t)["entries"], TEXTS)

    def test_refuses_tables_outside_the_verified_layout(self):
        t = bytearray(table())
        struct.pack_into("<I", t, 0x7C, struct.unpack_from("<I", t, 0x7C)[0] - 1)  # LF slack missing
        with self.assertRaises(TableError):
            table_model(bytes(t))
        with self.assertRaises(TableError):
            table_model(table() + b"\0" * 8)                     # extra padding
        with self.assertRaises(TableError):
            table_model(b"\0" * 0x100)                           # not a table
        unsorted = canonical([K2, K1], ["a", "b"])
        with self.assertRaises(TableError):
            table_model(unsorted)


class WriteTests(unittest.TestCase):
    def test_shorter_longer_unicode_and_several_entries(self):
        original = table()
        changes = {K1: "M",                                                       # shorter
                   K2: "¡Jefe Maestro! ¿Está listo? Ñandú, pingüino — «cita» … 漢字",  # longer, Unicode
                   K4: "Una sola línea",                                           # loses its LF
                   K5: "Primera\nSegunda\nTercera"}                                # gains LFs
        cand, info = write_table(original, changes)
        self.assertEqual(parse_mcc_loc(cand)["entries"], {**TEXTS, **changes})
        checks = verify_table(original, cand, changes)
        self.assertTrue(all(checks.values()), [k for k, v in checks.items() if not v])
        self.assertEqual(len(cand) % 8, 0)
        self.assertEqual(serialize(table_model(cand)), cand)                      # canonical again
        self.assertEqual(info["changed"][K1]["old_bytes"], len("Menú".encode()))
        self.assertEqual(parse_mcc_loc(cand)["entries"][K3], "")                  # untouched empty entry

    def test_empty_entry_and_no_change(self):
        original = table()
        cand, _ = write_table(original, {K2: ""})
        self.assertEqual(parse_mcc_loc(cand)["entries"][K2], "")
        self.assertEqual(write_table(original, {})[0], original)                  # no changes: identical bytes
        self.assertEqual(write_table(original, {K2: TEXTS[K2]})[0], original)     # same text: identical bytes

    def test_deterministic_and_order_independent(self):
        changes = {K5: "fin", K1: "inicio largo largo", K2: "medio"}
        a = write_table(table(), changes)[0]
        b = write_table(table(), dict(reversed(list(changes.items()))))[0]
        self.assertEqual(hashlib.sha256(a).digest(), hashlib.sha256(b).digest())

    def test_each_table_keeps_its_own_header(self):
        su, sp = table(b"SU_Halo1"), table(b"SP_Halo1")
        for t, name in ((su, "SU_Halo1"), (sp, "SP_Halo1")):
            cand, _ = write_table(t, {K2: "texto nuevo y más largo que antes"})
            p = parse_mcc_loc(cand)
            self.assertEqual(p["name"], name)
            self.assertTrue(p["name_hash_matches"] and p["size_fields_match"] and p["payload_size_matches"])

    def test_refuses_unknown_keys_and_invalid_text(self):
        for changes in ({0x12345678: "x"}, {K1: "a\0b"}, {K1: "bell\x07"}, {K1: "x" * 3000},
                        {K1: "cor&idKEYEShola"}):
            with self.assertRaises(TableError, msg=repr(changes)[:60]):
                write_table(table(), changes)

    def test_text_normalisation(self):
        self.assertEqual(normalize_text("a\r\nb\rc")[0], "a\nb\nc")
        self.assertEqual(normalize_text("canción")[0], "canción")       # NFD -> NFC
        self.assertEqual(normalize_text("¿Qué?")[1], [])
        cand, info = write_table(table(), {K1: "uno\r\ndos"})
        self.assertEqual(parse_mcc_loc(cand)["entries"][K1], "uno\ndos")
        self.assertIn("line breaks normalised to LF", info["changed"][K1]["notes"])
        self.assertEqual(text_problems(""), [])
        self.assertEqual(text_problems("tab\tand\nnewline"), [])

    def test_verify_catches_collateral_damage(self):
        original = table()
        changes = {K2: "nuevo"}
        cand, _ = write_table(original, changes)
        other, _ = write_table(original, {K2: "nuevo", K5: "cambiado"})          # a change nobody asked for
        checks = verify_table(original, other, changes)
        self.assertFalse(checks["untouched_entries_byte_identical"])
        self.assertFalse(checks["all_entries_expected"])
        self.assertFalse(verify_table(original, cand, {K2: "otro"})["replaced_entries_expected"])
        bad = bytearray(cand)
        struct.pack_into("<I", bad, 0x70, 9)                                     # a fixed header field
        self.assertFalse(verify_table(original, bytes(bad), changes)["fixed_header_bytes_identical"])


@unittest.skipUnless(all((COPIES / f"{t}_Halo1.bin").is_file() for t in PINS), "game table copies not present")
class ShippedTableTests(unittest.TestCase):
    """The verified layout on the real SU/SP copies (read-only)."""

    def tables(self):
        out = {t: (COPIES / f"{t}_Halo1.bin").read_bytes() for t in PINS}
        for t, data in out.items():
            self.assertEqual(hashlib.sha256(data).hexdigest(), PINS[t], f"{t} copy is not the pinned original")
        return out

    def test_identity_and_multi_entry_rewrite(self):
        for t, data in self.tables().items():
            self.assertEqual(serialize(table_model(data)), data, t)
            keys = parse_mcc_loc(data)["keys"]
            changes = {keys[0]: "", loc_key(TAG): "¡Jefe! ¿Listo? Ñ — «cita» …",
                       keys[1700]: "Corta", keys[-1]: "Una línea larga.\nCon salto de línea. " * 8}
            cand, info = write_table(data, changes)
            checks = verify_table(data, cand, changes)
            self.assertTrue(all(checks.values()), (t, [k for k, v in checks.items() if not v]))
            self.assertNotEqual(len(cand), len(data))
            self.assertEqual(info["entries"], 3400)


if __name__ == "__main__":
    unittest.main()
