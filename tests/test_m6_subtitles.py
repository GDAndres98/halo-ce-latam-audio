"""M6 subtitle builds: approved subtitle decisions -> what SU and SP get (common/m6_build.subtitle_plan), the
install guard's comparison, and writing both tables from a plan (build_tables). Synthetic data only.

Run: python -m unittest tests.test_m6_subtitles
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

from common.mcc_loc import parse_mcc_loc  # noqa: E402
from common.m6_build import build_tables, compare_subtitle_plans, subtitle_plan, table_changes  # noqa: E402
from build_api import BuildBoard, conflict_details  # noqa: E402
from m4_app import M4App  # noqa: E402
from test_m3_validation import mcc_record  # noqa: E402
from test_m4 import T, make_root  # noqa: E402
from test_mcc_loc_writer import canonical  # noqa: E402

KEYES0, KEYES1, CORTANA, STEREO = "es:Z10_010_keyes#0", "es:Z10_010_keyes#1", "es:Z10_020_cortana#0", "es:Z10_030_stereo#0"
APPROVE = [{"action": "approve", "field": "subtitle"}]


class SubtitleFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        cat = self.root / "work/mcc/catalog/z10.jsonl"
        recs = [json.loads(x) for x in cat.read_text().splitlines()]
        # a second take of z10_010_keyes (one tag, two slots, one subtitle key) and a line with no subtitle entry
        take = dict(recs[0]["samples"]["spanish"][0], index=3, subsong=4, name_occurrence_in_bank=1, ordinal_in_tag=1,
                    slot_id=KEYES1)
        recs[0]["samples"]["spanish"].append(take)
        recs[0]["slot_ids"].append(KEYES1)
        recs.append(mcc_record("Z10_030_stereo", T + "z10_030_stereo", index=2, data="e"))
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.app = M4App(self.root, today=lambda: "2026-10-09", run_validator=False)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, slot, **body):
        detail = self.app.slot(slot)
        body.update(slot_id=slot, loaded_sha256=detail["sha256"]["mappings"], local_sha256=detail["sha256"]["local"])
        return self.app.save(body)

    def doc(self):
        return json.loads((self.root / "mappings/manual_mappings.json").read_text(encoding="utf-8"))

    def local(self):
        p = self.root / "mappings/manual_mappings.local.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def plan(self, doc=None, local=None):
        return subtitle_plan(doc or self.doc(), {"z10"}, slot_index=self.app.slot_index, ce_lines=self.app.ce_lines,
                             ce_idx=self.app.ce_idx, mcc_idx=self.app.mcc_idx, local=local or self.local(),
                             tables={t: self.app.loc[t] for t in ("SU", "SP")})

    @staticmethod
    def rows(plan):
        return {r["slot_id"]: r for r in plan["rows"]}

    def ce_text(self, slot, ref="line_a#0"):
        self.save(slot, subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": ref, "culture": "es-MX"}},
                  actions=APPROVE)


class SubtitlePlanTests(SubtitleFixture):
    def test_only_approved_decisions_are_written(self):
        self.ce_text(KEYES0)
        self.save(CORTANA, subtitle={"source": "custom", "custom_text": "Texto propio"})   # a draft
        before = (self.root / "mappings/manual_mappings.json").read_bytes()
        p = self.plan()
        r = self.rows(p)
        self.assertEqual((r[KEYES0]["category"], r[KEYES0]["text"]), ("write", "Jefe Maestro, despierte"))
        self.assertEqual(r[CORTANA]["category"], "excluded")
        self.assertIn("draft", r[CORTANA]["result"])
        self.assertEqual({t: len(table_changes(p, t)) for t in ("SU", "SP")}, {"SU": 1, "SP": 1})
        self.assertEqual(p["summary"]["approved_subtitles"], 1)
        self.assertEqual((self.root / "mappings/manual_mappings.json").read_bytes(), before)   # read-only

    def test_needs_rework_and_drift_are_excluded(self):
        self.ce_text(KEYES0)
        self.save(KEYES0, actions=[{"action": "needs_rework", "field": "subtitle"}])
        r = self.rows(self.plan())
        self.assertEqual(r[KEYES0]["category"], "excluded")
        self.assertIn("needs_rework", r[KEYES0]["result"])
        self.ce_text(CORTANA)
        drift = copy.deepcopy(self.doc())
        m = next(s for s in drift["slots"] if s["slot_id"] == CORTANA)
        m["subtitle"]["fingerprint"] = {"tampered": True}
        r = self.rows(self.plan(drift))
        self.assertIn("drift", r[CORTANA]["result"])
        self.assertEqual(table_changes(self.plan(drift), "SU"), {})

    def test_custom_text_and_no_subtitle(self):
        self.save(KEYES0, subtitle={"source": "custom", "custom_text": "¿Listo?\r\nVamos, Jefe."}, actions=APPROVE)
        self.save(CORTANA, subtitle={"source": "none"}, actions=APPROVE)
        p = self.plan()
        r = self.rows(p)
        self.assertEqual(r[KEYES0]["text"], "¿Listo?\nVamos, Jefe.")                    # stored with LF only
        self.assertEqual((r[CORTANA]["category"], r[CORTANA]["text"]), ("write", ""))     # approved: no subtitle
        self.assertEqual(p["summary"]["empty_entries"], 1)

    def test_takes_of_one_line_must_agree(self):
        self.ce_text(KEYES0)
        self.ce_text(KEYES1)                                                    # same text: one entry, two slots
        p = self.plan()
        self.assertEqual(len(table_changes(p, "SU")), 1)
        self.assertEqual(next(k for k in p["keys"] if k["action"] == "write")["slots"], [KEYES0, KEYES1])
        self.save(KEYES1, actions=[{"action": "needs_rework", "field": "subtitle"}])
        self.save(KEYES1, subtitle={"source": "keep_original"}, actions=APPROVE)  # keep next to a change
        p = self.plan()
        self.assertEqual([c["code"] for c in p["conflicts"]], ["keep_and_change_for_one_subtitle_key"])
        self.assertEqual(table_changes(p, "SU"), {})                             # left unchanged, never guessed
        self.assertEqual({self.rows(p)[s]["category"] for s in (KEYES0, KEYES1)}, {"conflict"})
        self.save(KEYES1, actions=[{"action": "needs_rework", "field": "subtitle"}])
        self.ce_text(KEYES1, "line_b#0")                                         # a different text
        self.assertEqual([c["code"] for c in self.plan()["conflicts"]], ["different_texts_for_one_subtitle_key"])

    def test_a_line_without_a_subtitle_key_is_never_added(self):
        self.ce_text(STEREO)
        p = self.plan()
        self.assertEqual(self.rows(p)[STEREO]["category"], "missing_key")
        self.assertEqual(p["summary"]["missing_keys"], {"SU": 1, "SP": 1})
        self.assertEqual(table_changes(p, "SU"), {})

    def test_install_guard_sees_changed_and_new_subtitles(self):
        self.save(KEYES0, subtitle={"source": "custom", "custom_text": "Primera versión"}, actions=APPROVE)
        built = self.plan()
        self.assertEqual(compare_subtitle_plans(built, self.plan()), {"changed_or_revoked": [], "newly_eligible": []})
        self.ce_text(CORTANA)
        diff = compare_subtitle_plans(built, self.plan())
        self.assertEqual(diff["changed_or_revoked"], [])
        self.assertEqual(len(diff["newly_eligible"]), 2)                         # SU and SP
        self.save(KEYES0, actions=[{"action": "needs_rework", "field": "subtitle"}])
        self.assertEqual(len(compare_subtitle_plans(built, self.plan())["changed_or_revoked"]), 2)

    def test_both_tables_are_written_from_the_plan(self):
        self.ce_text(KEYES0)
        self.save(CORTANA, subtitle={"source": "custom", "custom_text": "Una línea mucho más larga que antes, ¿no?"},
                  actions=APPROVE)
        p = self.plan()
        originals = {}
        for t in ("SU", "SP"):  # canonical copies of the fixture's tables (the shipped layout)
            entries = self.app.loc[t]
            originals[t] = canonical(sorted(entries), [entries[k] for k in sorted(entries)], f"{t}_Halo1".encode())
        out = build_tables(originals, p)
        for t, (cand, info, checks) in out.items():
            self.assertTrue(all(checks.values()), (t, [k for k, v in checks.items() if not v]))
            got = parse_mcc_loc(cand)["entries"]
            self.assertEqual(sorted(got.values()), sorted(["Jefe Maestro, despierte",
                                                           "Una línea mucho más larga que antes, ¿no?"]))
            self.assertEqual(parse_mcc_loc(cand)["name"], f"{t}_Halo1")


class ConflictListTests(SubtitleFixture):
    """The Build & Test page lists subtitle conflicts take by take (build_api.conflict_details): POST
    /api/builds/preview and GET /api/builds/detail. Read-only: built from the planner's rows."""

    def preview(self):
        board = BuildBoard(self.root, lambda: set(self.app.levels), runner=lambda *_: (0, ""), app=self.app)
        before = (self.root / "mappings/manual_mappings.json").read_bytes()
        out = board.preview({"scope": "levels", "levels": ["z10"]})["subtitles"]
        self.assertEqual((self.root / "mappings/manual_mappings.json").read_bytes(), before)  # read-only
        return out

    def test_preview_lists_what_each_take_would_write(self):
        self.save(KEYES0, subtitle={"source": "custom", "custom_text": "Texto propio"}, actions=APPROVE)
        self.save(KEYES1, subtitle={"source": "keep_original"}, actions=APPROVE)
        subs = self.preview()
        self.assertEqual(subs["conflicts"], 1)
        (c,) = subs["conflict_list"]
        self.assertEqual((c["code"], c["level"], c["key_hex"]), ("keep_and_change_for_one_subtitle_key", "z10",
                                                                  f"0x{c['key']:08X}"))
        self.assertTrue(c["mcc_tag"].endswith("z10_010_keyes"))
        takes = {t["slot_id"]: t for t in c["takes"]}
        self.assertEqual(list(takes), [KEYES0, KEYES1])
        self.assertEqual({k: takes[KEYES0][k] for k in ("level", "outcome", "text", "source", "status")},
                         {"level": "z10", "outcome": "text", "text": "Texto propio", "source": "custom",
                          "status": "approved"})
        self.assertEqual((takes[KEYES1]["outcome"], takes[KEYES1]["text"]), ("keep", None))
        # the rows stay in excluded_rows (category "conflict"); the page lists them under Conflicts only
        self.assertEqual({r["slot_id"] for r in subs["excluded_rows"] if r["category"] == "conflict"},
                         {KEYES0, KEYES1})

    def test_different_texts_and_no_subtitle_outcomes(self):
        self.ce_text(KEYES0)
        self.save(KEYES1, subtitle={"source": "none"}, actions=APPROVE)
        (c,) = self.preview()["conflict_list"]
        self.assertEqual(c["code"], "different_texts_for_one_subtitle_key")
        self.assertEqual([(t["outcome"], t["text"]) for t in c["takes"]],
                         [("text", "Jefe Maestro, despierte"), ("empty", None)])

    def test_no_subtitle_not_agreed_names_the_other_takes(self):
        self.save(KEYES0, subtitle={"source": "none"}, actions=APPROVE)    # KEYES1 has no decision at all
        (c,) = self.preview()["conflict_list"]
        self.assertEqual(c["code"], "empty_subtitle_not_agreed_by_every_take")
        self.assertEqual([(t["slot_id"], t["outcome"], t["level"]) for t in c["takes"]],
                         [(KEYES0, "empty", "z10"), (KEYES1, "not_approved", "z10")])

    def test_build_detail_uses_the_manifest_rows(self):
        self.ce_text(KEYES0)
        self.ce_text(KEYES1, "line_b#0")
        plan = self.plan()
        folder = self.root / "work/m6/subs_test"
        folder.mkdir(parents=True)
        (folder / "build_manifest.json").write_text(json.dumps(
            {"name": "subs_test", "kind": "subtitles", "levels": ["z10"], "subtitles": dict(plan, enabled=True)}))
        board = BuildBoard(self.root, lambda: {"z10"}, runner=lambda *_: (0, ""))
        (c,) = board.build_detail("subs_test")["conflicts"]
        self.assertEqual(c, conflict_details(plan["conflicts"], plan["rows"])[0])
        self.assertEqual([t["outcome"] for t in c["takes"]], ["text", "text"])
        self.assertEqual(len({t["text"] for t in c["takes"]}), 2)
        # without the planner's rows the conflict is still listed, its outcomes unknown (never guessed)
        self.assertEqual(conflict_details(plan["conflicts"], [])[0]["takes"][0]["outcome"], "unknown")


if __name__ == "__main__":
    unittest.main()
