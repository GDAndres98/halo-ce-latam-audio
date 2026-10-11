"""M6 batch-build tests: eligibility planning from M4 decisions, the subtitle plan, and
multi-sample bank replacement. Synthetic data only (temporary roots, fake banks).

Run: python -m unittest discover -s tests
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.fsb5_writer import build, decompose, sample_spans  # noqa: E402
from common.m6_build import assemble, multi_structural_checks, plan_audio, subtitle_plan  # noqa: E402
from m4_app import M4App  # noqa: E402
from test_fsb5_writer import celt_stream, fsb, loop  # noqa: E402
from test_m3_validation import mcc_record  # noqa: E402
from test_m4 import T, make_root  # noqa: E402


def five_sample_bank():
    return fsb([(8, 0, 1024, [loop(1024)], celt_stream(2, 370, 1)),
                (8, 0, 1536, [loop(1536)], celt_stream(3, 370, 2)),
                (8, 0, 512, [loop(512)], celt_stream(1, 370, 3)),
                (8, 1, 512, [loop(512)], celt_stream(1, 464, 4)),
                (8, 0, 2048, [loop(2048)], celt_stream(4, 370, 5))],
               [b"a", b"b", b"c", b"stereo", b"e"])


class MultiReplaceTests(unittest.TestCase):
    def test_several_replacements_of_different_lengths(self):
        original = five_sample_bank()
        repl = {0: (celt_stream(5, 370, 50), 2560),   # grows, first sample
                2: (celt_stream(1, 370, 51), 512),    # same length, middle
                4: (celt_stream(2, 370, 52), 1024)}   # shrinks, last sample
        cand = assemble(original, repl)
        checks = multi_structural_checks(original, cand, repl)
        self.assertTrue(all(checks.values()), {k: v for k, v in checks.items() if not v})
        self.assertEqual(assemble(original, repl), cand)                       # deterministic
        self.assertEqual(assemble(original, dict(reversed(list(repl.items())))), cand)  # order-independent
        m = decompose(cand)
        self.assertEqual([s["sample_count"] for s in m["samples"]], [2560, 1536, 512, 512, 1024])
        so, sc = sample_spans(original), sample_spans(cand)
        self.assertEqual(original[so[1][0]:so[1][1]], cand[sc[1][0]:sc[1][1]])   # untouched, moved
        self.assertEqual(original[so[3][0]:so[3][1]], cand[sc[3][0]:sc[3][1]])

    def test_checks_catch_collateral_damage(self):
        original = five_sample_bank()
        repl = {1: (celt_stream(4, 370, 60), 2048), 3: (celt_stream(1, 464, 61), 512)}
        cand = assemble(original, repl)
        self.assertTrue(all(multi_structural_checks(original, cand, repl).values()))
        m = decompose(cand)
        m["samples"][2] = dict(m["samples"][2], stream=celt_stream(1, 370, 99))  # a sample nobody asked for
        bad = build(m)
        c = multi_structural_checks(original, bad, repl)
        self.assertFalse(c["untouched_payloads_byte_identical"])
        self.assertFalse(c["untouched_sample_headers_identical"])
        wrong = dict(repl)
        wrong[1] = (repl[1][0], 1536)
        self.assertFalse(multi_structural_checks(original, cand, wrong)["targets_sample_counts"])
        self.assertFalse(multi_structural_checks(original, cand, {1: repl[1]})["untouched_payloads_byte_identical"])

    def test_no_replacements_is_an_identity_rebuild(self):
        original = five_sample_bank()
        self.assertEqual(assemble(original, {}), original)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        # a third, stereo slot in the same level
        recs = [json.loads(x) for x in (self.root / "work/mcc/catalog/z10.jsonl").read_text().splitlines()]
        st = mcc_record("Z10_030_stereo", T + "z10_030_stereo", index=2, data="e")
        st["samples"]["spanish"][0]["channels"] = 2
        (self.root / "work/mcc/catalog/z10.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs + [st]))
        self.app = M4App(self.root, today=lambda: "2026-10-09", run_validator=False)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, slot, **body):
        body["slot_id"] = slot
        body["loaded_sha256"] = self.app.slot(slot)["sha256"]["mappings"]
        return self.app.save(body)

    def doc(self):
        return json.loads((self.root / "mappings/manual_mappings.json").read_text(encoding="utf-8"))

    def plan(self, doc=None):
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        return plan_audio(doc or self.doc(), ["z10"], **idx), idx

    def test_categories(self):
        k, c, st = "es:Z10_010_keyes#0", "es:Z10_020_cortana#0", "es:Z10_030_stereo#0"
        self.save(k, match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0"}]},
                  radio_effect={"needed": True}, actions=[{"action": "approve", "field": "audio"}])
        self.save(c, match={"status": "matched", "ce_line_refs": ["line_b#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_b#0"}]})        # draft
        self.save(st, match={"status": "matched", "ce_line_refs": ["line_b#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_b#0"}]},
                  actions=[{"action": "approve", "field": "audio"}])
        before = (self.root / "mappings/manual_mappings.json").read_bytes()
        plan, _ = self.plan()
        by = {e["slot_id"]: e for e in plan["entries"]}
        self.assertEqual((by[k]["action"], by[k]["ce_line_ref"], by[k]["spanish_index"], by[k]["radio_effect"]),
                         ("replace", "line_a#0", 0, True))
        self.assertEqual(by[c]["action"], "keep_original")
        self.assertIn("draft", by[c]["reason"])
        self.assertEqual(by[st]["action"], "not_eligible")
        self.assertIn("stereo", by[st]["reason"])
        self.assertEqual(plan["conflicts"], [])
        self.assertEqual((self.root / "mappings/manual_mappings.json").read_bytes(), before)  # read-only

    def test_drift_unsupported_and_conflicts(self):
        k = "es:Z10_010_keyes#0"
        self.save(k, match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0"}]},
                  actions=[{"action": "approve", "field": "audio"}])
        doc = self.doc()
        drift = copy.deepcopy(doc)
        drift["slots"][0]["audio"]["fingerprint"]["sources"][0]["media"][0]["wem_sha256"] = "0" * 64
        e = self.plan(drift)[0]["entries"][0]
        self.assertEqual(e["action"], "not_eligible")
        self.assertIn("drift", e["reason"])
        concat = copy.deepcopy(doc)
        concat["slots"][0]["audio"]["source"] = "ce_concat"
        self.assertIn("ce_concat", self.plan(concat)[0]["entries"][0]["reason"])
        dup = copy.deepcopy(doc)
        dup["slots"].append(dict(copy.deepcopy(doc["slots"][0]), mapping_id="m-000009"))
        plan = self.plan(dup)[0]
        self.assertEqual(plan["conflicts"][0]["code"], "duplicate_mapping_for_slot")
        self.assertEqual(plan["entries"][0]["action"], "not_eligible")

    def test_subtitle_plan_is_independent_and_reports_lengths(self):
        k = "es:Z10_010_keyes#0"
        self.save(k, match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "line_a#0", "culture": "es-MX"}},
                  actions=[{"action": "approve", "field": "subtitle"}])       # audio stays a draft
        _, idx = self.plan()
        s = subtitle_plan(self.doc(), {"z10"}, local=None, tables={t: self.app.loc[t] for t in ("SU", "SP")}, **idx)
        row = s["rows"][0]
        self.assertTrue(row["change"])
        self.assertTrue(row["SU"]["key_found"] and row["SP"]["key_found"])
        self.assertEqual(row["new_utf8_bytes"], len("Jefe Maestro, despierte".encode()))
        self.assertFalse(row["SU"]["same_length"])
        self.assertEqual(s["summary"]["generation"], "enabled")
        self.assertEqual(s["summary"]["variable_length"], {"SU": 1, "SP": 1})


class FolderAndMissionTests(unittest.TestCase):
    def test_map_tag_path_scan(self):
        sys.path.insert(0, str(ROOT / "scripts" / "catalog"))
        from build_level_folders import tag_paths
        blob = (b"\x00junk sound\\dialog\\x10\\x10_010_keyes\x00 more sound\\dialog\\a10\\a10_350_captkeyes\x00"
                b"sound\\dialog\\marines\\aussie\\conditional\\aussie\x00sound\\dialog\\\x00")
        self.assertEqual(tag_paths(blob), {"sound\\dialog\\x10\\x10_010_keyes", "sound\\dialog\\a10\\a10_350_captkeyes",
                                           "sound\\dialog\\marines\\aussie\\conditional\\aussie"})

    def test_mission_folders_take_only_cinematics_used_by_that_map(self):
        from common.m6_build import mission_folders
        lf = {"levels": {"a10": {"evidence": "derived:map_tag_path_scan", "map_sha256": "x",
                                 "folders": {"a10": {}, "x10": {}, "x20": {}, "marines": {}, "x99": {}}}},
              "folders": {"a10": {"used_by": ["a10"]}, "x10": {"used_by": ["a10"]}, "x20": {"used_by": ["a10"]},
                          "marines": {"used_by": ["a10", "a30"]}, "x99": {"used_by": ["a10", "c10"]}}}
        r = mission_folders(lf, "a10")
        self.assertEqual(r["selected"], ["a10", "x10", "x20"])
        self.assertEqual(r["shared_not_selected"], ["marines", "x99"])
        with self.assertRaises(ValueError):
            mission_folders(lf, "b30")

    def test_folder_summary_groups(self):
        from common.m6_build import folder_summary
        base = {"channels": 1, "mapping_id": "m-000001"}
        entries = [dict(base, level="x20", action="replace", reason="approved CE audio"),
                   dict(base, level="x20", action="keep_original", reason="approved: keep Spain audio", channels=2),
                   dict(base, level="x20", action="keep_original", reason="audio draft (not approved): Spain audio stays"),
                   dict(base, level="x20", action="keep_original", reason="no mapping", mapping_id=None),
                   dict(base, level="x20", action="not_eligible", reason="unsupported: stereo slot", channels=2),
                   dict(base, level="a10", action="not_eligible", reason="invalid: drift")]
        s = folder_summary(entries)
        self.assertEqual({k: v for k, v in s["x20"].items() if v},
                         {"replace": 1, "approved_keep_spain": 1, "not_approved": 1, "unmapped": 1,
                          "unsupported": 1, "slots": 5, "stereo": 2})
        self.assertEqual(s["a10"]["invalid"], 1)

    def test_compare_plans_flags_revoked_lines_but_only_notes_new_ones(self):
        from common.m6_build import compare_plans
        built = [{"slot_id": "a", "action": "replace", "mapping_id": "m-1", "ce_line_ref": "x#0", "language": "L",
                  "media": {"wem_sha256": "h"}},
                 {"slot_id": "b", "action": "keep_original", "mapping_id": None}]
        self.assertEqual(compare_plans(built, copy.deepcopy(built)), {"changed_or_revoked": [], "newly_eligible": []})
        revoked = copy.deepcopy(built)
        revoked[0].update(action="keep_original", reason="audio needs_rework")
        self.assertEqual(compare_plans(built, revoked)["changed_or_revoked"], ["a"])
        other = copy.deepcopy(built)
        other[0]["ce_line_ref"] = "y#0"
        self.assertEqual(compare_plans(built, other)["changed_or_revoked"], ["a"])
        newer = copy.deepcopy(built)
        newer[1].update(action="replace", mapping_id="m-2")
        self.assertEqual(compare_plans(built, newer), {"changed_or_revoked": [], "newly_eligible": ["b"]})


if __name__ == "__main__":
    unittest.main()
