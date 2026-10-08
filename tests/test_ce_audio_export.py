"""M1b export logic tests. All inputs are synthetic: fake catalog records,
fake .wem bytes, and a fake decoder that writes tiny generated WAVs. No game
data is read or stored, and vgmstream is not run.

Run: python -m unittest discover -s tests
"""
import hashlib
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common.ce_audio_export import (  # noqa: E402
    DECODE_FAILED, EMPTY, OK, SILENT, SOURCE_HASH_MISMATCH, SOURCE_MISSING, UNREADABLE, coverage, export_units,
    inspect_wav, manual_review_items, plan, recommend, ref_stem)

MX, EN = "Spanish(Mexico)", "English(US)"


def wem_bytes(media_id):
    return f"synthetic-wem-{media_id}".encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def media(ids):
    return {"evidence": "explicit", "media": [
        {"media_id": i, "vfs_path": f"Media/{i}.wem", "container": "lang.pak", "wem_sha256": sha(wem_bytes(i)),
         "wem_bytes": len(wem_bytes(i)), "source_name": f"{i}.wav"} for i in ids]}


def record(rid, family="scripted", flags=(), mx=None, en=None, speaker="TESTER", table="T", key=None):
    key = key or rid.upper()
    subs = {c: ({"evidence": "explicit", "namespace": table, "key": key, "text": f"{c} text {rid}"} if speaker
                else {"evidence": "unresolved", "reason": "no transcription reference"}) for c in ("es-MX", "en")}
    return {"record_id": rid, "family": family, "flags": sorted(flags), "entries": [{
        "ce_line_ref": f"{rid}#0",
        "media": {MX: mx, EN: en},
        "event": {"package": f"/Game/Events/{rid}/Play_{key}"},
        "transcription": {"metadata": {"Character": speaker} if speaker else {}, "string_table": table,
                          "line_key": key if speaker else None},
        "subtitles": subs}]}


def write_wav(path, samples, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def fixture():
    """x0 line + its x1 replay (shared media), a test-event lipsync variant, a cross-family line,
    a cinematic line, a line whose es-MX media is unresolved, and one with two media items."""
    return [
        record("line_00940", mx=media([11]), en=media([21]), speaker="CORTANA"),
        record("line_00941", flags=("no_transcription", "event_package_folder_mismatch", "no_lipsync"),
               mx=media([11]), en=media([21]), speaker=None),
        record("line_00490_lipsync", flags=("test_event", "lipsync_variant_folder"),
               mx={"evidence": "unresolved", "reason": "language not in EventLanguageMap"},
               en={"evidence": "unresolved", "reason": "language not in EventLanguageMap"}),
        record("cin_00341", family="cinematic", flags=("foreign_string_table",), mx=media([12]), en=media([22]),
               speaker="MENDOZA", table="VO_SYS_X"),
        record("cin_00010", family="cinematic", flags=("no_lipsync",), mx=media([13]), en=media([23]), speaker="KEYES"),
        record("line_00500", mx={"evidence": "unresolved", "reason": "1 of 1 media not in the language pak"},
               en=media([24]), speaker="CRYOTECH"),
        record("line_00600", mx=media([14, 15]), en=media([25]), speaker="DUBBO"),
    ]


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.units, self.refs = plan(fixture())
        self.by = {(r["ce_line_ref"], r["language"]): r for r in self.refs}

    def test_repeated_media_is_one_unit_named_after_primary(self):
        u = self.units[f"{MX}:11"]
        self.assertEqual(u["references"], ["line_00940#0", "line_00941#0"])
        self.assertEqual(u["primary_ref"], "line_00940#0")  # the replay (secondary flags) never names the file
        self.assertTrue(u["deduplicated"])
        self.assertEqual(u["wav_path"], f"{MX}/line_00940__0.wav")
        self.assertEqual(self.by[("line_00941#0", MX)]["units"], [f"{MX}:11"])  # reference preserved

    def test_test_event_is_excluded_not_missing(self):
        r = self.by[("line_00490_lipsync#0", MX)]
        self.assertEqual(r["status"], "excluded:test_event")
        self.assertEqual(r["units"], [])

    def test_unresolved_catalog_media_is_missing_not_substituted(self):
        r = self.by[("line_00500#0", MX)]
        self.assertEqual((r["status"], r["units"]), ("missing_in_catalog", []))
        self.assertEqual(self.by[("line_00500#0", EN)]["status"], "linked")

    def test_multi_media_entry_gets_suffixes_and_ref_stem(self):
        self.assertEqual({self.units[f"{MX}:14"]["wav_path"], self.units[f"{MX}:15"]["wav_path"]},
                         {f"{MX}/line_00600__0__m0.wav", f"{MX}/line_00600__0__m1.wav"})
        self.assertEqual(ref_stem("folder/name#2"), "folder__name__2")

    def test_catalog_hash_conflict_is_recorded(self):
        recs = fixture()
        recs[1]["entries"][0]["media"][MX]["media"][0]["wem_sha256"] = "00" * 32
        units, _ = plan(recs)
        self.assertEqual(units[f"{MX}:11"]["catalog_conflicts"][0]["ce_line_ref"], "line_00941#0")

    def test_plan_is_order_independent(self):
        u2, r2 = plan(list(reversed(fixture())))
        self.assertEqual((u2, r2), (self.units, self.refs))


class InspectWavTests(unittest.TestCase):
    def test_ok_empty_silent_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write_wav(d / "ok.wav", [0, 1200, -3000, 5] * 1200)
            write_wav(d / "empty.wav", [])
            write_wav(d / "silent.wav", [0] * 4800)
            (d / "bad.wav").write_bytes(b"not a wav")
            ok = inspect_wav(d / "ok.wav")
            self.assertEqual((ok["status"], ok["sample_rate"], ok["channels"], ok["frames"], ok["peak"]),
                             (OK, 48000, 1, 4800, 3000))
            self.assertEqual(ok["duration_s"], 0.1)
            self.assertEqual(inspect_wav(d / "empty.wav")["status"], EMPTY)
            self.assertEqual(inspect_wav(d / "silent.wav")["status"], SILENT)
            self.assertEqual(inspect_wav(d / "bad.wav")["status"], UNREADABLE)


class ExportTests(unittest.TestCase):
    def run_export(self, recs, read=None, decode=None):
        units, refs = plan(recs)
        calls = []

        def default_read(u):
            return wem_bytes(u["media_id"])

        def default_decode(wem, wav):
            calls.append(wem.name)
            write_wav(wav, [100, -100] * 2400)
            return True, ""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            export_units(units, d / "audio", d / "media", read or default_read, decode or default_decode)
            wems = {p.relative_to(d / "media").as_posix(): p.read_bytes() for p in (d / "media").rglob("*.wem")}
            wavs = sorted(p.relative_to(d / "audio").as_posix() for p in (d / "audio").rglob("*"))
        return units, refs, calls, wems, wavs

    def test_decodes_each_unique_media_once_and_keeps_wem_identical(self):
        units, _, calls, wems, wavs = self.run_export(fixture())
        self.assertEqual(len(calls), len(units))  # dedup: media 11 / 21 decoded once
        self.assertEqual(calls.count("11.wem"), 1)
        self.assertEqual(wems[f"{MX}/11.wem"], wem_bytes(11))
        self.assertTrue(all(u["status"] == OK for u in units.values()))
        self.assertNotIn(True, [w.endswith(".tmp") for w in wavs])
        self.assertEqual(units[f"{MX}:11"]["wav"]["duration_s"], 0.1)
        self.assertEqual(len(units[f"{MX}:11"]["wav_sha256"]), 64)

    def test_missing_source_hash_mismatch_and_decode_failure(self):
        def read(u):
            if u["media_id"] == 12:
                return None
            if u["media_id"] == 13:
                return b"tampered"
            return wem_bytes(u["media_id"])

        def decode(wem, wav):
            if wem.name == "14.wem":
                wav.write_bytes(b"partial")  # a failed decoder may leave junk behind
                return False, "synthetic decoder error"
            write_wav(wav, [7] * 480)
            return True, ""
        units, _, _, wems, wavs = self.run_export(fixture(), read, decode)
        self.assertEqual(units[f"{MX}:12"]["status"], SOURCE_MISSING)
        self.assertEqual(units[f"{MX}:13"]["status"], SOURCE_HASH_MISMATCH)
        self.assertNotIn(f"{MX}/13.wem", wems)  # mismatching media is neither copied nor decoded
        self.assertEqual(units[f"{MX}:14"]["status"], DECODE_FAILED)
        self.assertIn("synthetic decoder error", units[f"{MX}:14"]["reason"])
        self.assertFalse(any("line_00600__0__m0" in w for w in wavs))  # nothing left under the final or temp name


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.recs = fixture()
        self.units, self.refs = plan(self.recs)
        for u in self.units.values():  # pretend a clean export with distinct durations
            u.update(status=OK, wav_sha256=sha(u["key"].encode()),
                     wav={"sample_rate": 48000, "channels": 1, "frames": 1, "peak": 1,
                          "duration_s": 1.0 + (u["media_id"] % 10) / 10 + (0.5 if u["language"] == MX else 0)})

    def test_coverage_counts(self):
        cov = coverage(self.units, self.refs)
        mx = cov["languages"][MX]
        self.assertEqual(mx["references"], 7)
        self.assertEqual(mx["reference_status"], {"excluded:test_event": 1, "linked": 5, "missing_in_catalog": 1})
        self.assertEqual(mx["references_with_ok_audio"], 5)
        self.assertEqual((mx["units"], mx["deduplicated_units"], mx["references_saved_by_dedup"]), (5, 1, 1))
        self.assertEqual(mx["sample_rates"], {48000: 5})
        self.assertEqual(cov["excluded"], {"excluded:test_event": 2})
        self.assertEqual([m["ce_line_ref"] for m in cov["missing_in_catalog"]], ["line_00500#0"])
        self.assertEqual(cov["problem_units"], [])
        self.assertTrue(cov["all_references_accounted_for"])

    def test_identical_audio_under_different_media_ids_is_reported(self):
        self.units[f"{MX}:12"]["wav_sha256"] = self.units[f"{MX}:13"]["wav_sha256"]
        cov = coverage(self.units, self.refs)
        self.assertEqual(cov["identical_audio_different_media_id"], [[f"{MX}:12", f"{MX}:13"]])

    def test_manual_review_keeps_cross_family_relationship(self):
        items = manual_review_items(self.recs)
        self.assertEqual([(i["ce_line_ref"], i["string_table"]) for i in items], [("cin_00341#0", "VO_SYS_X")])

    def test_recommendations_are_varied_deterministic_and_skip_verified(self):
        a = recommend(self.recs, self.units, self.refs, already_verified={"cin_00010#0"})
        b = recommend(list(reversed(self.recs)), self.units, self.refs, already_verified={"cin_00010#0"})
        self.assertEqual(a, b)
        refs = [p["ce_line_ref"] for p in a["picks"]]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertLessEqual(len(refs), 5)
        self.assertNotIn("cin_00010#0", refs)
        self.assertNotIn("line_00490_lipsync#0", refs)  # excluded test event never recommended
        self.assertNotIn("line_00500#0", refs)          # needs audio in both languages
        self.assertIn("cin_00341#0", refs)              # manual-review item
        self.assertIn("line_00941#0", refs)             # a deduplicated reference
        dup = next(p for p in a["picks"] if p["ce_line_ref"] == "line_00941#0")
        self.assertEqual(dup["audio"][MX]["wav_path"], f"{MX}/line_00940__0.wav")
        self.assertEqual(dup["subtitles"]["es-MX"]["evidence"], "unresolved")  # never borrowed from line_00940


if __name__ == "__main__":
    unittest.main()
