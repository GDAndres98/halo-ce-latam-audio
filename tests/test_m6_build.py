"""M6 batch-build tests: eligibility planning from M4 decisions, the subtitle dry run, and
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

    def test_subtitle_dry_run_is_independent_and_reports_lengths(self):
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
        self.assertEqual(s["summary"]["generation"], "disabled")
        self.assertEqual(s["summary"]["variable_length"], {"SU": 1, "SP": 1})


if __name__ == "__main__":
    unittest.main()
