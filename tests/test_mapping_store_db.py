"""The decisions file is backed by SQLite: saves, history, refusals and crash recovery.

Works on a copy of the first two slots of the live file (read-only use) in a temporary folder.
"""
import copy
import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import mapping_db, mapping_store  # noqa: E402

LIVE = ROOT / "mappings" / "manual_mappings.json"


class DatabaseBackedStoreTests(unittest.TestCase):
    def setUp(self):
        if not LIVE.exists():
            self.skipTest("needs the live mappings file as a valid v3 template")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        doc = json.loads(LIVE.read_bytes().decode("utf-8"))
        doc["slots"] = doc["slots"][:2]
        self.path = self.root / "manual_mappings.json"
        self.path.write_bytes(mapping_db.serialize(doc))
        self.db = mapping_db.db_path_for(self.path)
        self.doc, self.sha = mapping_store.load(self.path)  # creates the database

    def tearDown(self):
        self._tmp.cleanup()

    def edited_notes(self, text):
        new = copy.deepcopy(self.doc)
        new["slots"][1]["notes"] = text  # notes are not part of any approved object
        return new

    def db_export(self):
        conn = mapping_db.open_existing(self.db)
        try:
            return mapping_db.export_bytes(conn), mapping_db.check_derived_columns(conn)
        finally:
            conn.close()

    def history_rows(self):
        conn = mapping_db.open_existing(self.db)
        try:
            return conn.execute("SELECT mapping_id, before_body IS NULL, after_body FROM slot_history").fetchall()
        finally:
            conn.close()

    def test_save_updates_database_history_and_json_together(self):
        new = self.edited_notes("nota de prueba")
        new_sha = mapping_store.save(self.path, new, self.sha, history_dir=self.root / "h")
        data = mapping_db.serialize(new)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(new_sha, hashlib.sha256(data).hexdigest())
        self.assertEqual(self.db_export(), (data, []))
        rows = self.history_rows()
        self.assertEqual([(mid, added) for mid, added, _ in rows], [(self.doc["slots"][1]["mapping_id"], 0)])
        self.assertIn("nota de prueba", rows[0][2])
        self.assertEqual(len(list((self.root / "h").glob("manual_mappings.*.json"))), 1)  # file backup kept

    def test_the_stored_export_hash_matches_the_export(self):
        # Reads trust meta.export_sha256 instead of re-exporting; this keeps that value honest.
        conn = mapping_db.open_existing(self.db)
        try:
            self.assertEqual(mapping_db.meta_get(conn, "export_sha256"),
                             mapping_db.sha256(mapping_db.export_bytes(conn)))
        finally:
            conn.close()

    def test_a_hand_edit_is_refused_not_overwritten(self):
        edited = mapping_db.serialize(self.edited_notes("editado a mano"))
        self.path.write_bytes(edited)
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.load(self.path)
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.save(self.path, self.edited_notes("otra"), self.sha)
        self.assertEqual(self.path.read_bytes(), edited)  # the owner's bytes are left alone

    def test_an_interrupted_json_write_is_finished_on_the_next_read(self):
        # The database committed the save, then the process stopped before the JSON write.
        new = self.edited_notes("guardado antes del corte")
        conn = mapping_db.open_existing(self.db)
        try:
            mapping_db.replace_slots(conn, new, "2026-10-10T12:00:00")
        finally:
            conn.close()
        doc, sha = mapping_store.load(self.path)
        self.assertEqual(doc, new)
        self.assertEqual(self.path.read_bytes(), mapping_db.serialize(new))
        self.assertEqual(sha, hashlib.sha256(mapping_db.serialize(new)).hexdigest())

    def test_a_stale_save_is_refused(self):
        mapping_store.save(self.path, self.edited_notes("uno"), self.sha)
        with self.assertRaises(mapping_store.StaleError):
            mapping_store.save(self.path, self.edited_notes("dos"), self.sha)

    def test_a_non_canonical_file_is_never_imported(self):
        other = Path(self.root / "b")
        other.mkdir()
        path = other / "manual_mappings.json"
        path.write_text(json.dumps(self.doc, indent=4), encoding="utf-8")  # 4-space indent: not the Studio format
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.load(path)
        self.assertFalse(mapping_db.db_path_for(path).exists())


class UserDocumentTests(unittest.TestCase):
    """mission_progress.json and manual_mappings.local.json: stored in the database, same guarantees."""

    def setUp(self):
        if not LIVE.exists():
            self.skipTest("needs the live mappings file to create the database")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "mappings").mkdir()
        doc = json.loads(LIVE.read_bytes().decode("utf-8"))
        doc["slots"] = doc["slots"][:2]
        self.decisions = self.root / "mappings" / "manual_mappings.json"
        self.decisions.write_bytes(mapping_db.serialize(doc))
        mapping_store.load(self.decisions)  # decisions first, as at the cutover
        self.progress = self.root / "mappings" / "mission_progress.json"
        self.db = mapping_db.db_path_for(self.decisions)

    def tearDown(self):
        self._tmp.cleanup()

    def level_doc(self, status):
        return {"schema": "mission-progress/1",
                "levels": [{"mcc_level": "a10", "status": status, "updated_at": "2026-10-10",
                            "verification": None, "note": ""}]}

    def test_missing_file_loads_as_the_default(self):
        doc, sha = mapping_store.load_or_default(self.progress, {"schema": "mission-progress/1", "levels": []})
        self.assertEqual(doc["levels"], [])
        self.assertEqual(sha, mapping_store.EMPTY_SHA256)
        self.assertFalse(self.progress.exists())  # reading creates nothing on disk

    def test_save_writes_the_database_history_and_the_file(self):
        doc, sha = mapping_store.load_or_default(self.progress, {"schema": "mission-progress/1", "levels": []})
        new = self.level_doc("in_progress")
        mapping_store.save_user_file(self.progress, new, sha, "mission-progress-1",
                                     history_dir=self.root / "h", now=dt.datetime(2026, 10, 10, 12))
        self.assertEqual(self.progress.read_bytes(), mapping_db.serialize(new))
        conn = mapping_db.open_existing(self.db)
        try:
            body, export_sha, pending = mapping_db.document_get(conn, "mission_progress.json")
            history = conn.execute("SELECT COUNT(*) FROM document_history WHERE name = 'mission_progress.json'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(body, mapping_db.serialize(new))
        self.assertEqual(export_sha, mapping_db.sha256(mapping_db.serialize(new)))
        self.assertFalse(pending)
        self.assertEqual(history, 1)

    def test_a_stale_user_save_is_refused(self):
        _doc, sha = mapping_store.load_or_default(self.progress, {"schema": "mission-progress/1", "levels": []})
        mapping_store.save_user_file(self.progress, self.level_doc("in_progress"), sha, "mission-progress-1")
        with self.assertRaises(mapping_store.StaleError):
            mapping_store.save_user_file(self.progress, self.level_doc("reviewed"), sha, "mission-progress-1")

    def test_a_hand_edited_user_file_is_refused(self):
        _doc, sha = mapping_store.load_or_default(self.progress, {"schema": "mission-progress/1", "levels": []})
        mapping_store.save_user_file(self.progress, self.level_doc("in_progress"), sha, "mission-progress-1")
        edited = mapping_db.serialize(self.level_doc("reviewed"))
        self.progress.write_bytes(edited)
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.load(self.progress)
        self.assertEqual(self.progress.read_bytes(), edited)

    def test_an_interrupted_user_file_write_is_finished_on_the_next_read(self):
        new = self.level_doc("in_progress")
        conn = mapping_db.open_existing(self.db)
        try:
            mapping_db.document_put(conn, "mission_progress.json", mapping_db.serialize(new),
                                    "2026-10-10T12:00:00", pending=True)
        finally:
            conn.close()
        doc, _sha = mapping_store.load(self.progress)
        self.assertEqual(doc, new)
        self.assertEqual(self.progress.read_bytes(), mapping_db.serialize(new))


if __name__ == "__main__":
    unittest.main()
