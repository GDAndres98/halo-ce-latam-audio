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
from common.project_validation import added_take_findings, level_progress  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
