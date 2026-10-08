"""M2 tests: FSB5 + lst.bin parsing and the MCC catalog logic. All inputs are
synthetic bytes built here (tiny fake banks with fake "CELT" payloads); no
game data is read or stored, and vgmstream is not run.

Run: python -m unittest discover -s tests
"""
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common.ce_audio_export import inspect_wav, sha256_file  # noqa: E402
from common.fsb5_lib import FsbBank  # noqa: E402
from common.mcc_catalog import (  # noqa: E402
    BankIndex, build_level, coverage, export_plan, export_units, parse_tag_name, recommend)
from common.mcc_lst import check_ranges, parse_lst  # noqa: E402


def build_fsb5(samples, mode=12):
    """samples: [(name, sample_count, payload_bytes, chunk_or_None)] -> FSB5 v1 bytes."""
    headers, data = b"", b""
    for name, count, payload, chunk in samples:
        off = len(data)
        assert off % 16 == 0
        val = (1 if chunk else 0) | (8 << 1) | (0 << 5) | ((off // 16) << 6) | (count << 34)  # 44100 Hz mono
        headers += struct.pack("<Q", val)
        if chunk:
            ctype, cbody = chunk
            headers += struct.pack("<I", (len(cbody) << 1) | (ctype << 25)) + cbody
        data += payload + b"\0" * (-len(payload) % 16)
    strings, offs = b"", []
    base = 4 * len(samples)
    for name, *_ in samples:
        offs.append(base + len(strings))
        strings += name.encode() + b"\0"
    names = struct.pack(f"<{len(samples)}I", *offs) + strings
    names += b"\0" * (-len(names) % 16)
    head = b"FSB5" + struct.pack("<IIIIII", 1, len(samples), len(headers), len(names), len(data), mode) + bytes(32)
    return head + headers + names + data


def build_lst(records):
    out = struct.pack("<II", 1, len(records))
    for tag, start, count in records:
        raw = tag.encode("ascii") + b"\0"
        out += struct.pack("<I", len(raw)) + raw + struct.pack("<II", start, count)
    return out


T = "sound\\dialog\\z10\\"


def write_bank(d, fname, samples):
    p = Path(d) / fname
    p.write_bytes(build_fsb5(samples))
    return FsbBank(p)


class Fsb5Tests(unittest.TestCase):
    def test_header_samples_names_and_chunks(self):
        with tempfile.TemporaryDirectory() as d:
            b = write_bank(d, "x.fsb", [("Z10_010_Keyes", 44100, b"A" * 20, (3, b"\1" * 8)),
                                        ("Z10_020_Cortana", 22050, b"B" * 7, None)])
        self.assertEqual((b.header["num_samples"], b.header["mode_name"]), (2, "CELT"))
        self.assertEqual(b.names, ["Z10_010_Keyes", "Z10_020_Cortana"])
        self.assertEqual(b.samples[0]["chunks"], [(3, 8)])
        self.assertEqual((b.samples[1]["frequency"], b.samples[1]["channels"], b.samples[1]["data_offset"]),
                         (44100, 1, 32))
        self.assertEqual(b.find("z10_020_cortana"), 1)
        self.assertAlmostEqual(b.duration_seconds(1), 0.5)

    def test_bad_magic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.fsb"
            p.write_bytes(b"FSB4" + bytes(100))
            with self.assertRaises(ValueError):
                FsbBank(p)


class LstTests(unittest.TestCase):
    def test_parse_and_range_checks(self):
        recs = [(T + "z10_010_keyes", 0, 1), (T + "z10_020_cortana", 1, 2)]
        parsed = parse_lst(build_lst(recs))
        self.assertEqual(parsed, {"version": 1, "records": recs})
        self.assertEqual(check_ranges(recs, 3), {"contiguous_from_zero": True, "sample_total": 3, "bank_samples": 3,
                                                 "total_matches_bank": True})
        self.assertFalse(check_ranges([(T + "a", 0, 1), (T + "b", 2, 1)], 3)["contiguous_from_zero"])

    def test_rejects_truncated_and_trailing(self):
        data = build_lst([(T + "z10_010_keyes", 0, 1)])
        with self.assertRaises(ValueError):
            parse_lst(data[:-3])
        with self.assertRaises(ValueError):
            parse_lst(data + b"\0")


class TagNameTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(parse_tag_name(T + "a10_350_captkeyes"),
                         {"level": "a10", "kind": "scripted", "sequence": "350", "speaker_from_name": "captkeyes"})
        self.assertEqual(parse_tag_name(T + "a10_flavor_110_captkeyes")["kind"], "flavor")
        self.assertEqual(parse_tag_name(T + "a30_insert_020_lifeboatpilot")["kind"], "insert")
        self.assertEqual(parse_tag_name("sound\\dialog\\captain\\pain_major")["kind"], "other")


class CatalogTests(unittest.TestCase):
    """English and Spanish banks deliberately use different orders, counts and casing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        en = [("Z10_010_Keyes", 100, b"en-keyes", (3, b"\0" * 8)),
              ("Z10_020_Cortana", 200, b"en-cortana", (3, b"\0" * 8)),
              ("Z10_030_Aussie", 300, b"same-bytes", None),
              ("Z10_flavor_040_Cortana", 400, b"en-flav", None),
              ("Z99_010_other", 50, b"other", None)]
        es = [("Z10_020_cortana", 210, b"es-cortana", (3, b"\0" * 8)),   # index differs from English
              ("Z10_010_keyes", 110, b"es-keyes", (3, b"\0" * 8)),
              ("Z10_030_aussie", 300, b"same-bytes", None),              # identical data in both languages
              ("Z10_flavor_040_cortana", 410, b"es-flav-a", None),       # two permutations in Spanish
              ("Z10_flavor_040_cortana", 420, b"es-flav-b", None),
              ("Z10_999_stray", 10, b"stray", None)]                     # level sample owned by no tag
        self.banks = {"english": BankIndex(write_bank(d, "en.fsb", en), "english", "en.fsb"),
                      "spanish": BankIndex(write_bank(d, "es.fsb", es), "spanish", "es.fsb")}
        self.lst_en = [(T + "z10_010_keyes", 0, 1), (T + "z10_020_cortana", 1, 1), (T + "z10_030_aussie", 2, 1),
                       (T + "z10_flavor_040_cortana", 3, 1), ("sound\\dialog\\z99\\z99_010_other", 4, 1)]
        self.lst_es = [(T + "z10_010_keyes", 0, 1), (T + "z10_020_cortana", 1, 1), (T + "z10_030_aussie", 2, 1),
                       (T + "z10_flavor_040_cortana", 3, 2)]
        self.records, self.issues = build_level("z10", self.lst_en, self.lst_es, self.banks, {"test": True})
        self.by = {r["tag_name"]: r for r in self.records}

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_from_each_banks_own_names(self):
        k = self.by["z10_010_keyes"]
        self.assertEqual([s["index"] for s in k["samples"]["english"]], [0])
        self.assertEqual([s["index"] for s in k["samples"]["spanish"]], [1])
        self.assertIn("index_differs_between_languages", k["flags"])
        self.assertIn("name_case_differs_between_languages", k["flags"])
        self.assertEqual(k["slot_ids"], ["es:Z10_010_keyes#0"])
        s = k["samples"]["spanish"][0]
        self.assertEqual((s["codec"], s["freq"], s["channels"], s["sample_count"], s["subsong"]),
                         ("CELT", 44100, 1, 110, 2))
        self.assertEqual(s["metadata_chunks"], [{"type": 3, "size": 8}])

    def test_lst_cross_check_flags_disagreement(self):
        k = self.by["z10_010_keyes"]
        self.assertTrue(k["lst"]["english"]["agrees_with_name_table"])
        self.assertFalse(k["lst"]["spanish"]["agrees_with_name_table"])  # lst says 0, the name table says 1
        self.assertIn("lst_disagrees_with_names:spanish", k["flags"])

    def test_permutations_get_occurrence_slot_ids(self):
        f = self.by["z10_flavor_040_cortana"]
        self.assertEqual(f["slot_ids"], ["es:Z10_flavor_040_cortana#0", "es:Z10_flavor_040_cortana#1"])
        self.assertTrue({"permutations", "sample_count_differs_between_languages",
                         "name_repeats_in_bank:spanish"} <= set(f["flags"]))

    def test_identical_data_stray_samples_and_subtitles(self):
        self.assertIn("identical_data_es_en", self.by["z10_030_aussie"]["flags"])
        codes = {i["code"]: i for i in self.issues}
        self.assertEqual(codes["bank_samples_without_tag"]["samples"], [{"index": 5, "name": "Z10_999_stray"}])
        self.assertNotIn("z99_010_other", self.by)
        self.assertTrue(all(r["subtitle"]["evidence"] == "unresolved" and r["subtitle"]["key_hash"] is None
                            for r in self.records))

    def test_missing_language_is_reported(self):
        lst_es = self.lst_es + [(T + "z10_050_ghost", 6, 1)]
        recs, issues = build_level("z10", self.lst_en + [(T + "z10_050_ghost", 5, 1)], lst_es, self.banks, {})
        g = next(r for r in recs if r["tag_name"] == "z10_050_ghost")
        self.assertEqual(g["samples"], {"spanish": [], "english": []})
        self.assertTrue({"missing:spanish", "missing:english"} <= set(g["flags"]))
        self.assertEqual(len(g["unresolved"]), 2)
        cov = coverage("z10", recs, issues)
        self.assertEqual(cov["languages"]["spanish"]["tags_missing"], [T + "z10_050_ghost"])

    def test_duplicate_data_within_language(self):
        lst = [(T + "z10_010_keyes", 0, 1), (T + "z10_030_aussie", 2, 1)]
        with tempfile.TemporaryDirectory() as d:
            b = BankIndex(write_bank(d, "d.fsb", [("Z10_010_keyes", 1, b"dup", None), ("x", 1, b"q", None),
                                                  ("Z10_030_aussie", 1, b"dup", None)]), "spanish", "d.fsb")
            _, issues = build_level("z10", lst, lst, {"spanish": b, "english": b}, {})
        self.assertIn({"code": "duplicate_sample_data", "language": "spanish", "index_groups": [[0, 2]]}, issues)

    def test_export_plan_names_and_decode_statuses(self):
        units = export_plan(self.records)
        paths = {u["key"]: u["wav_path"] for u in units}
        self.assertEqual(paths["spanish:1"], "spanish/z10_010_keyes__0.wav")
        self.assertEqual(paths["spanish:4"], "spanish/z10_flavor_040_cortana__1.wav")

        def decode(u, tmp):
            if u["key"] == "english:1":
                return False, "synthetic failure"
            frames = u["header_sample_count"] if u["key"] != "spanish:2" else 1  # one length mismatch
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(struct.pack(f"<{frames}h", *([500] * frames)))
            return True, ""
        with tempfile.TemporaryDirectory() as d:
            export_units(units, Path(d), decode, inspect_wav, sha256_file)
            left = sorted(p.name for p in Path(d).rglob("*"))
        st = {u["key"]: u for u in units}
        self.assertEqual(st["english:1"]["status"], "decode_failed")
        self.assertFalse(st["spanish:2"]["frames_match_header"])
        self.assertTrue(st["spanish:1"]["frames_match_header"])
        self.assertEqual(st["spanish:1"]["wav"]["sample_rate"], 44100)
        self.assertFalse(any(n.endswith(".tmp") for n in left))
        picks = recommend(self.records, units)
        self.assertEqual(picks, recommend(list(reversed(self.records)), units))
        self.assertNotIn(T + "z10_020_cortana", [p["mcc_tag"] for p in picks["picks"]])  # English decode failed
        self.assertLessEqual(len(picks["picks"]), 5)


if __name__ == "__main__":
    unittest.main()
