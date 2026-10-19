"""Added takes (docs/added-takes-design.md): the decision, its storage (database + JSON export), the approval
rules, the validator and the Studio backend. Synthetic data only (temporary roots).

Run: python -m unittest tests.test_added_takes
"""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import mapping_db, mapping_store  # noqa: E402
from common.mapping_store import ProtectedError, UserAction  # noqa: E402
from common.project_validation import added_take_findings, level_progress, own_set_findings  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from test_m3_validation import mcc_record  # noqa: E402
from test_m4 import T, make_root  # noqa: E402

DEATH = T + "z10_030_death"          # no subtitle entry: added takes allowed
KEYES = T + "z10_010_keyes"          # has a subtitle entry: refused
MX = "Spanish(Mexico)"


class AddedTakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        cat = self.root / "work/mcc/catalog/z10.jsonl"
        recs = [json.loads(x) for x in cat.read_text().splitlines()]
        recs.append(mcc_record("Z10_030_death", DEATH, index=2, data="e"))
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.app = M4App(self.root, today=lambda: "2026-10-17", run_validator=False)
        self.path = self.root / "mappings/manual_mappings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def version(self, tag=DEATH):
        return self.app.sound(tag)["version"]

    def sv(self, tag=DEATH):
        return self.app.sound(tag)["sound_version"]

    def add(self, ref="line_a#0", **extra):
        return self.app.take_save({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(),
                                   "audio": {"ce_line_ref": ref, "language": MX}, **extra})

    def act(self, tid, action):
        return self.app.take_save({"mcc_tag": DEATH, "take_id": tid, "loaded_takes_sha256": self.version(),
                                   "actions": [{"action": action, "field": "audio"}]})

    def doc(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ rules
    def test_only_mono_sounds_without_a_subtitle_entry(self):
        self.assertEqual(self.app.take_rule(DEATH), (True, ""))
        allowed, reason = self.app.take_rule(KEYES)
        self.assertFalse(allowed)
        self.assertIn("subtitle", reason)
        with self.assertRaises(ApiError) as e:
            self.app.take_save({"mcc_tag": KEYES, "loaded_takes_sha256": self.version(KEYES),
                                "audio": {"ce_line_ref": "line_a#0", "language": MX}})
        self.assertEqual(e.exception.status, 409)

    # ------------------------------------------------------------------ the decision and its storage
    def test_add_take_is_stored_in_the_database_and_exported(self):
        before = self.path.read_bytes()
        r = self.add()
        self.assertTrue(r["saved"])
        self.assertEqual(r["take_id"], "t-000001")
        t = self.doc()["added_takes"][0]
        self.assertEqual((t["mcc_tag"], t["position"], t["audio"]["status"], t["audio"]["sources"][0]["ce_line_ref"]),
                         (DEATH, 1, "draft", "line_a#0"))
        self.assertEqual(self.doc()["slots"], json.loads(before)["slots"])  # lines untouched
        conn = sqlite3.connect(self.root / "mappings/manual_mappings.db")
        try:
            self.assertEqual(conn.execute("SELECT take_id, audio_status FROM added_takes").fetchall(),
                             [("t-000001", "draft")])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM added_take_history").fetchone()[0], 1)
        finally:
            conn.close()
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")
        sound = self.app.sound(DEATH)
        self.assertEqual((sound["total_takes"], len(sound["spain_takes"]), sound["added_takes"][0]["take_id"]),
                         (2, 1, "t-000001"))

    def test_approve_lock_rework_and_change(self):
        self.add()
        self.act("t-000001", "approve")
        a = self.doc()["added_takes"][0]["audio"]
        self.assertEqual((a["status"], a["revision"]), ("approved", 1))
        self.assertEqual(a["fingerprint"]["mcc"]["mcc_tag"], DEATH)
        with self.assertRaises(ApiError) as e:  # approved: read-only
            self.app.take_save({"mcc_tag": DEATH, "take_id": "t-000001", "loaded_takes_sha256": self.version(),
                                "audio": {"ce_line_ref": "line_b#0", "language": MX}})
        self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ApiError):
            self.app.take_remove({"mcc_tag": DEATH, "take_id": "t-000001", "loaded_takes_sha256": self.version()})
        self.act("t-000001", "needs_rework")
        self.app.take_save({"mcc_tag": DEATH, "take_id": "t-000001", "loaded_takes_sha256": self.version(),
                            "audio": {"ce_line_ref": "line_b#0", "language": MX}})
        a = self.doc()["added_takes"][0]["audio"]
        self.assertEqual((a["status"], a["revision"], a["sources"][0]["ce_line_ref"]), ("needs_rework", 2, "line_b#0"))

    def test_reorder_remove_and_never_store_an_empty_list(self):
        before = self.path.read_bytes()
        self.add("line_a#0")
        self.add("line_b#0")
        self.app.take_move({"mcc_tag": DEATH, "take_id": "t-000002", "direction": -1,
                            "loaded_takes_sha256": self.version()})
        order = [t["take_id"] for t in sorted(self.doc()["added_takes"], key=lambda t: t["position"])]
        self.assertEqual(order, ["t-000002", "t-000001"])
        for tid in ("t-000001", "t-000002"):
            self.app.take_remove({"mcc_tag": DEATH, "take_id": tid, "loaded_takes_sha256": self.version()})
        self.assertNotIn("added_takes", self.doc())
        self.assertEqual(self.path.read_bytes(), before)  # byte-identical to before any take
        self.add("line_a#0")
        self.assertEqual(self.doc()["added_takes"][0]["take_id"], "t-000003")  # IDs are never reused

    def test_add_several_in_one_save(self):
        self.add("line_a#0")
        r = self.app.take_add_many({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "audio_list": [
            {"ce_line_ref": "line_a#0", "language": MX},   # already a take: skipped
            {"ce_line_ref": "line_b#0", "language": MX},
            {"ce_line_ref": "line_b#0", "language": MX}]})  # listed twice: skipped
        self.assertEqual((r["saved"], r["added"], r["skipped"]), (True, ["t-000002"], ["line_a#0", "line_b#0"]))
        takes = sorted(self.doc()["added_takes"], key=lambda t: t["position"])
        self.assertEqual([(t["take_id"], t["position"], t["audio"]["status"]) for t in takes],
                         [("t-000001", 1, "draft"), ("t-000002", 2, "draft")])
        again = self.app.take_add_many({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(),
                                        "audio_list": [{"ce_line_ref": "line_b#0", "language": MX}]})
        self.assertFalse(again["saved"])
        before = self.path.read_bytes()
        for bad, status in (([{"ce_line_ref": "aa_early#0", "language": MX}, {"ce_line_ref": "nope#9", "language": MX}], 400),
                            ([], 400)):
            with self.assertRaises(ApiError) as e:
                self.app.take_add_many({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "audio_list": bad})
            self.assertEqual(e.exception.status, status)
        self.assertEqual(self.path.read_bytes(), before)  # all or nothing
        with self.assertRaises(ApiError) as e:
            self.app.take_add_many({"mcc_tag": KEYES, "loaded_takes_sha256": self.version(KEYES),
                                    "audio_list": [{"ce_line_ref": "line_a#0", "language": MX}]})
        self.assertEqual(e.exception.status, 409)

    # ------------------------------------------------------------------ own take sets (docs/custom-take-set-design.md)
    def line_save(self, **body):
        return self.app.save({"slot_id": "es:Z10_030_death#0", "loaded_sha256": mapping_store.load(self.path)[1],
                              **body})

    def test_own_set_on_clears_the_line_decisions_through_needs_rework(self):
        self.line_save(match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                       audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0", "language": MX}]})
        self.line_save(actions=[{"action": "approve", "field": "audio"}])
        mid = self.doc()["slots"][-1]["mapping_id"]
        self.assertEqual(self.doc()["slots"][-1]["audio"]["status"], "approved")
        with self.assertRaises(ApiError) as e:  # the page must name exactly what it clears
            self.app.own_set_on({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "loaded_sound_sha256": self.sv(DEATH), "clear_mapping_ids": [],
                                 "audio_list": [{"ce_line_ref": "line_a#0", "language": MX}]})
        self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ApiError) as e:  # replacing every take with nothing
            self.app.own_set_on({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "loaded_sound_sha256": self.sv(DEATH), "clear_mapping_ids": [mid]})
        self.assertEqual(e.exception.status, 400)
        r = self.app.own_set_on({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "loaded_sound_sha256": self.sv(DEATH), "clear_mapping_ids": [mid],
                                 "audio_list": [{"ce_line_ref": "line_b#0", "language": MX},
                                                {"ce_line_ref": "line_b#0", "language": MX}]})
        self.assertEqual((r["saved"], r["cleared"], r["reworked"]), (True, [mid], [f"{mid}/audio"]))
        self.assertEqual((r["added"], r["skipped"]), (["t-000001"], ["line_b#0"]))
        self.assertEqual([(t["take_id"], t["audio"]["status"]) for t in self.doc()["added_takes"]], [("t-000001", "draft")])
        doc = self.doc()
        self.assertEqual([s for s in doc["slots"] if s["mcc_tag"] == DEATH], [])
        own = doc["own_sets"][0]
        self.assertEqual((own["mcc_tag"], own["set_at"], own["provenance"]["kind"]), (DEATH, "2026-10-17", "replace"))
        # The cleared decision is recorded exactly as it was (approved), and the set lists the take it created.
        self.assertEqual([m["audio"]["status"] for m in own["provenance"]["slots"]], ["approved"])
        self.assertEqual([{k: t[k] for k in ("take_id", "origin", "from_mapping_ids")} for t in own["provenance"]["takes"]],
                         [{"take_id": "t-000001", "origin": "created", "from_mapping_ids": []}])
        self.assertEqual(r["sound"]["own_set"], {"mcc_tag": DEATH, "set_at": "2026-10-17"})
        conn = sqlite3.connect(self.root / "mappings/manual_mappings.db")  # one save: approved -> removed
        rows = conn.execute("SELECT before_body, after_body, reason FROM slot_history WHERE mapping_id = ? ORDER BY id",
                            (mid,)).fetchall()
        self.assertEqual((json.loads(rows[-1][0])["audio"]["status"], rows[-1][1], rows[-1][2][:16]),
                         ("approved", None, "take-set:replace"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM own_set_history").fetchone()[0], 1)
        conn.close()
        with self.assertRaises(ApiError) as e:  # its lines can't be decided while the set is on
            self.line_save(match={"status": "matched", "ce_line_refs": ["line_a#0"]})
        self.assertEqual(e.exception.status, 409)
        row = self.app.slots("z10")["slots"]
        self.assertEqual(next(x for x in row if x["slot_id"] == "es:Z10_030_death#0")["own_set"],
                         {"takes": 1, "approved": 0, "needs_rework": 0})
        ids = lambda st: [x["slot_id"] for x in self.app.slots("z10", status=st)["slots"]]  # noqa: E731
        self.assertIn("es:Z10_030_death#0", ids("matched"))  # filtered by its sound's takes, not as undecided
        self.assertNotIn("es:Z10_030_death#0", ids("undecided"))
        self.assertIn("es:Z10_030_death#0", ids("draft"))
        self.act("t-000001", "approve")
        self.assertIn("es:Z10_030_death#0", ids("approved"))

    def test_own_set_rules_progress_and_off(self):
        with self.assertRaises(ApiError) as e:
            self.app.own_set_on({"mcc_tag": KEYES, "loaded_takes_sha256": self.version(KEYES), "loaded_sound_sha256": self.sv(KEYES), "clear_mapping_ids": []})
        self.assertEqual(e.exception.status, 409)  # subtitled sound
        before = self.path.read_bytes()
        self.app.own_set_on({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "loaded_sound_sha256": self.sv(DEATH), "clear_mapping_ids": [], "audio_list": [{"ce_line_ref": "line_a#0", "language": MX}]})
        mcc = self.app.mcc_idx
        keys = self.app._subtitle_keys()
        self.assertEqual([f["code"] for f in own_set_findings(self.doc(), mcc=mcc, subtitle_keys=keys)],
                         ["own_set_without_approved_take"])
        p = level_progress(["es:Z10_030_death#0"], self.doc(), [DEATH], {"es:Z10_030_death#0": DEATH})
        self.assertEqual((p["own_sets"], p["own_set_lines"], p["decided"], p["audio_approved"]), (1, 1, 1, 0))
        self.act("t-000001", "approve")
        self.assertEqual(own_set_findings(self.doc(), mcc=mcc, subtitle_keys=keys), [])
        p = level_progress(["es:Z10_030_death#0"], self.doc(), [DEATH], {"es:Z10_030_death#0": DEATH})
        self.assertTrue(p["ready_for_build"])
        bad = copy.deepcopy(self.doc())
        bad["slots"].append({"mapping_id": "m-000999", "slot_id": "es:Z10_030_death#0", "mcc_tag": DEATH})
        bad["own_sets"].append({"mcc_tag": KEYES, "set_at": "2026-10-17"})
        codes = {f["code"] for f in own_set_findings(bad, mcc=mcc, subtitle_keys=keys)}
        self.assertTrue({"own_set_with_line_decisions", "own_set_on_subtitled_sound"} <= codes)
        self.app.own_set_off({"mcc_tag": DEATH, "loaded_takes_sha256": self.version()})
        self.assertNotIn("own_sets", self.doc())
        self.app.take_save({"mcc_tag": DEATH, "take_id": "t-000001", "loaded_takes_sha256": self.version(),
                            "actions": [{"action": "needs_rework", "field": "audio"}]})
        self.app.take_remove({"mcc_tag": DEATH, "take_id": "t-000001", "loaded_takes_sha256": self.version()})
        self.assertEqual(self.path.read_bytes(), before)  # byte-identical to before (never stored empty)

    def test_a_save_made_from_an_old_version_is_refused(self):
        old = self.version()
        self.add()
        with self.assertRaises(ApiError) as e:
            self.app.take_save({"mcc_tag": DEATH, "loaded_takes_sha256": old,
                                "audio": {"ce_line_ref": "line_b#0", "language": MX}})
        self.assertEqual(e.exception.status, 409)

    # ------------------------------------------------------------------ store and validator
    def test_tools_never_approve_and_approved_takes_are_immutable(self):
        self.add()
        doc, sha = mapping_store.load(self.path)
        forged = copy.deepcopy(doc)
        forged["added_takes"][0]["audio"]["status"] = "approved"
        forged["added_takes"][0]["audio"]["approved_at"] = "2026-10-17"
        forged["added_takes"][0]["audio"]["fingerprint"] = {}
        with self.assertRaises(ProtectedError):
            mapping_store.save(self.path, forged, sha)
        self.act("t-000001", "approve")
        doc, sha = mapping_store.load(self.path)
        gone = {k: v for k, v in doc.items() if k != "added_takes"}
        with self.assertRaises(ProtectedError):
            mapping_store.save(self.path, gone, sha)
        edited = copy.deepcopy(doc)
        edited["added_takes"][0]["audio"]["edit"]["trim_start_s"] = 0.1
        with self.assertRaises(ProtectedError):
            mapping_store.save(self.path, edited, sha, user_actions=[UserAction("approve", "t-000001", "audio")])

    def test_validator_rules(self):
        self.add()
        doc = self.doc()
        t = doc["added_takes"][0]
        bad = copy.deepcopy(doc)
        bad["added_takes"].append(dict(copy.deepcopy(t), take_id="t-000002"))  # same position
        bad["added_takes"].append(dict(copy.deepcopy(t), take_id="t-000003", position=3, mcc_tag=KEYES))
        codes = {f["code"] for f in added_take_findings(bad, ce=self.app.ce_idx, mcc=self.app.mcc_idx, local=None,
                                                        subtitle_keys=self.app._subtitle_keys())}
        self.assertIn("duplicate_take_position", codes)
        self.assertIn("added_take_on_subtitled_sound", codes)
        self.assertEqual(added_take_findings(doc, ce=self.app.ce_idx, mcc=self.app.mcc_idx, local=None,
                                             subtitle_keys=self.app._subtitle_keys()), [])

    def test_progress_counts_takes_separately(self):
        self.add()
        self.act("t-000001", "approve")
        p = level_progress(["es:Z10_030_death#0"], self.doc(), [DEATH])
        self.assertEqual((p["added_takes"], p["added_takes_approved"], p["matched"], p["decided"]), (1, 1, 0, 0))
        rows = self.app.slots("z10", status="takes")["slots"]
        self.assertEqual([(r["slot_id"], r["added_takes"]) for r in rows], [("es:Z10_030_death#0", 1)])

    def test_export_bytes_from_bodies_equal_a_full_encode(self):
        self.add()
        self.add("line_b#0")
        conn = mapping_db.open_existing(self.root / "mappings/manual_mappings.db")
        try:
            self.assertEqual(mapping_db.export_bytes(conn), mapping_db.serialize(self.doc()))
            self.assertEqual(mapping_db.export_bytes(conn), self.path.read_bytes())
        finally:
            conn.close()


class InsertBuildTests(unittest.TestCase):
    """M6 side: insert_takes / insert_checks on a synthetic bank + index, compare_inserts."""

    def bank_and_index(self):
        from common.mcc_lst import build_lst
        from test_m6_build import five_sample_bank
        # sounds: a = samples 0-1, b = sample 2, c = samples 3-4
        return five_sample_bank(), build_lst(1, [("sound\\dialog\\x\\a", 0, 2), ("sound\\dialog\\x\\b", 1 + 1, 1),
                                                  ("sound\\dialog\\x\\c", 3, 2)])

    def test_inserted_takes_follow_their_sound_and_everything_else_shifts(self):
        from common.m6_build import insert_checks, insert_takes
        from common.mcc_lst import parse_lst
        from test_fsb5_writer import celt_stream
        bank, lst = self.bank_and_index()
        items = [{"take_id": "t-000001", "mcc_tag": "sound\\dialog\\x\\a", "stream": celt_stream(2, 370, 80),
                  "sample_count": 1024},
                 {"take_id": "t-000002", "mcc_tag": "sound\\dialog\\x\\a", "stream": celt_stream(1, 370, 81),
                  "sample_count": 512},
                 {"take_id": "t-000003", "mcc_tag": "sound\\dialog\\x\\c", "stream": celt_stream(3, 370, 82),
                  "sample_count": 1536}]
        cand, new_lst, index_map, new_index = insert_takes(bank, lst, items)
        self.assertEqual(index_map, [0, 1, 4, 5, 6])
        self.assertEqual(new_index, {"t-000001": 2, "t-000002": 3, "t-000003": 7})
        self.assertEqual([r[1:] for r in parse_lst(new_lst)["records"]], [(0, 4), (4, 1), (5, 3)])
        checks = insert_checks(bank, cand, lst, new_lst, index_map, new_index, items)
        self.assertTrue(all(checks.values()), {k: v for k, v in checks.items() if not v})
        self.assertEqual(insert_takes(bank, lst, items)[0], cand)  # deterministic
        bad = insert_checks(bank, cand, lst, new_lst, index_map, {**new_index, "t-000003": 6}, items)
        self.assertFalse(bad["insert:inserted_streams_and_counts"])

    def test_an_own_set_sound_holds_only_its_inserted_takes(self):
        from common.m6_build import insert_checks, insert_takes
        from common.mcc_lst import parse_lst
        from test_fsb5_writer import celt_stream
        bank, lst = self.bank_and_index()
        items = [{"take_id": "t-000001", "mcc_tag": "sound\\dialog\\x\\a", "stream": celt_stream(2, 370, 80),
                  "sample_count": 1024},
                 {"take_id": "t-000002", "mcc_tag": "sound\\dialog\\x\\a", "stream": celt_stream(1, 370, 81),
                  "sample_count": 512},
                 {"take_id": "t-000003", "mcc_tag": "sound\\dialog\\x\\c", "stream": celt_stream(3, 370, 82),
                  "sample_count": 1536}]
        drop = ["sound\\dialog\\x\\a"]
        cand, new_lst, index_map, new_index = insert_takes(bank, lst, items, drop)
        self.assertEqual(index_map, [None, None, 2, 3, 4])
        self.assertEqual(new_index, {"t-000001": 0, "t-000002": 1, "t-000003": 5})
        self.assertEqual([r[1:] for r in parse_lst(new_lst)["records"]], [(0, 2), (2, 1), (3, 3)])
        checks = insert_checks(bank, cand, lst, new_lst, index_map, new_index, items, drop)
        self.assertTrue(all(checks.values()), {k: v for k, v in checks.items() if not v})
        self.assertEqual(insert_takes(bank, lst, items, drop)[0], cand)  # deterministic
        with self.assertRaises(ValueError):  # never an empty sound
            insert_takes(bank, lst, items, ["sound\\dialog\\x\\b"])
        kept = insert_takes(bank, lst, items)  # a check made for "no drop" fails on a dropping build
        self.assertFalse(insert_checks(bank, cand, lst, new_lst, index_map, new_index, items)["insert:sample_count"])
        self.assertNotEqual(kept[0], cand)

    def test_compare_inserts(self):
        from common.m6_build import compare_inserts
        built = [{"take_id": "t-1", "action": "insert", "ce_line_ref": "x#0", "language": "L", "media": {"wem_sha256": "h"}}]
        self.assertEqual(compare_inserts(built, built), {"changed_or_revoked": [], "newly_eligible": []})
        self.assertEqual(compare_inserts(built, [dict(built[0], action="skip")])["changed_or_revoked"], ["t-1"])
        self.assertEqual(compare_inserts([], built)["newly_eligible"], ["t-1"])


class InsertPlanTests(AddedTakeTests):
    """plan_inserts on the Studio fixture (inherits its setUp; the AddedTakeTests tests are not repeated)."""

    def plan(self):
        from common.m6_build import plan_inserts
        return plan_inserts(self.doc(), ["z10"], slot_index=self.app.slot_index, ce_lines=self.app.ce_lines,
                            ce_idx=self.app.ce_idx, mcc_idx=self.app.mcc_idx, subtitle_keys=self.app._subtitle_keys())

    def test_only_approved_drift_free_takes_are_inserted(self):
        self.add("line_a#0")
        self.add("line_b#0")
        self.act("t-000001", "approve")
        by = {e["take_id"]: e for e in self.plan()}
        self.assertEqual((by["t-000001"]["action"], by["t-000001"]["ce_line_ref"], by["t-000001"]["ref_slot_id"]),
                         ("insert", "line_a#0", "es:Z10_030_death#0"))
        self.assertEqual(by["t-000002"]["action"], "skip")
        doc = self.doc()
        doc["added_takes"][0]["audio"]["fingerprint"]["mcc"]["spanish"][0]["data_sha256"] = "0" * 64
        from common.m6_build import plan_inserts
        e = plan_inserts(doc, ["z10"], slot_index=self.app.slot_index, ce_lines=self.app.ce_lines,
                         ce_idx=self.app.ce_idx, mcc_idx=self.app.mcc_idx)[0]
        self.assertIn("drift", e["reason"])

    def test_own_set_drops_spain_only_with_a_take_to_insert(self):
        from common.m6_build import BUILT_ACTIONS, compare_plans, own_set_drops, plan_audio
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        self.app.own_set_on({"mcc_tag": DEATH, "loaded_takes_sha256": self.version(), "loaded_sound_sha256": self.sv(DEATH), "clear_mapping_ids": [], "audio_list": [{"ce_line_ref": "line_a#0", "language": MX}]})
        self.assertEqual(own_set_drops(self.doc(), self.plan()), [])  # a draft take: Spain's takes stay
        e = next(x for x in plan_audio(self.doc(), ["z10"], **idx)["entries"] if x["slot_id"] == "es:Z10_030_death#0")
        self.assertEqual(e["action"], "keep_original")
        self.assertIn("own take set", e["reason"])
        self.act("t-000001", "approve")
        drops = own_set_drops(self.doc(), self.plan())
        self.assertEqual(drops, [DEATH])
        self.assertTrue(all(x["own_set"] for x in self.plan()))
        built = plan_audio(self.doc(), ["z10"], dropped_tags=drops, **idx)["entries"]
        e = next(x for x in built if x["slot_id"] == "es:Z10_030_death#0")
        self.assertEqual(e["action"], "dropped")
        self.assertIn("dropped", BUILT_ACTIONS)
        # turned off after the build: the install check sees the change and refuses
        self.app.own_set_off({"mcc_tag": DEATH, "loaded_takes_sha256": self.version()})
        now = plan_audio(self.doc(), ["z10"], dropped_tags=own_set_drops(self.doc(), self.plan()), **idx)["entries"]
        self.assertIn("es:Z10_030_death#0", compare_plans(built, now)["changed_or_revoked"])


for _name in [n for n in dir(AddedTakeTests) if n.startswith("test_")]:
    setattr(InsertPlanTests, _name, None)  # run the inherited fixture only, not the tests twice


if __name__ == "__main__":
    unittest.main()
