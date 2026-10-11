"""Explicit JSON <-> SQLite sync: status, line endings, preview, confirmed import and export, schema v4.

Works on a copy of the first three slots of the live file (read-only use) in a temporary folder.
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

from common import mapping_db, mapping_store  # noqa: E402

LIVE = ROOT / "mappings" / "manual_mappings.json"


class SyncTests(unittest.TestCase):
    def setUp(self):
        if not LIVE.exists():
            self.skipTest("needs the live mappings file as a valid v3 template")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.hist = self.root / "h"
        doc = json.loads(LIVE.read_bytes().decode("utf-8"))
        doc["slots"] = doc["slots"][:3]
        self.path = self.root / "manual_mappings.json"
        self.path.write_bytes(mapping_db.serialize(doc))
        self.db = mapping_db.db_path_for(self.path)
        self.doc, self.sha = mapping_store.load(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def external(self, mutate):
        """Write the file as an outside tool would (the database is not told)."""
        doc = copy.deepcopy(self.doc)
        mutate(doc)
        data = mapping_db.serialize(doc)
        self.path.write_bytes(data)
        return doc, data

    def db_doc(self):
        conn = mapping_db.open_existing(self.db)
        try:
            return mapping_db.export_document(conn)
        finally:
            conn.close()

    def test_in_sync_after_load(self):
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")

    def test_crlf_with_the_same_content_is_not_an_external_edit(self):
        lf = self.path.read_bytes()
        self.path.write_bytes(lf.replace(b"\n", b"\r\n"))
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "line_endings")
        doc, sha = mapping_store.load(self.path)  # no error, canonical bytes
        self.assertEqual((doc, sha), (self.doc, self.sha))
        new = copy.deepcopy(doc)
        new["slots"][0]["notes"] = "guardado tras CRLF"
        mapping_store.save(self.path, new, sha, history_dir=self.hist)
        self.assertNotIn(b"\r\n", self.path.read_bytes())  # the save writes LF again
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")

    def test_a_real_external_edit_is_reported_and_never_read(self):
        self.external(lambda d: d["slots"][1].__setitem__("notes", "editado fuera"))
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "external_edit")
        with self.assertRaises(mapping_store.StoreError) as e:
            mapping_store.load(self.path)
        self.assertIn("Nothing was overwritten", str(e.exception))
        self.assertNotEqual(self.db_doc()["slots"][1].get("notes"), "editado fuera")

    def test_preview_lists_slot_and_approval_changes_without_writing(self):
        def unapprove(d):
            s = d["slots"][0]
            s["notes"] = "cambio"
        before_file, before_db = self.path.read_bytes(), self.db.read_bytes()
        self.external(unapprove)
        file_now = self.path.read_bytes()
        p = mapping_store.preview_import(self.path)
        self.assertEqual([c["mapping_id"] for c in p["changes"]], [self.doc["slots"][0]["mapping_id"]])
        self.assertEqual(p["changes"][0]["fields"], ["notes"])
        self.assertEqual(self.path.read_bytes(), file_now)
        self.assertEqual(self.db.read_bytes(), before_db)
        self.assertNotEqual(before_file, file_now)

    def test_import_replaces_the_database_records_history_and_backs_up(self):
        doc, data = self.external(lambda d: d["slots"][2].__setitem__("notes", "importado"))
        self.path.write_bytes(data.replace(b"\n", b"\r\n"))  # as git would leave it
        p = mapping_store.preview_import(self.path)
        out = mapping_store.import_json(self.path, p["file_sha256"], p["db_export_sha256"], history_dir=self.hist)
        self.assertEqual(out["changed_slots"], 1)
        self.assertEqual(self.db_doc(), doc)
        self.assertEqual(self.path.read_bytes(), data)  # canonical LF, same content
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")
        self.assertEqual(mapping_store.load(self.path)[0], doc)
        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT mapping_id, reason FROM slot_history").fetchall()
        conn.close()
        self.assertEqual(rows, [(doc["slots"][2]["mapping_id"], f"import:{p['file_sha256']}")])
        backups = list(self.hist.glob("manual_mappings.*.before-import.db"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(len(list(self.hist.glob("*.imported.json"))), 1)  # the CRLF bytes, kept
        old = sqlite3.connect(backups[0])
        self.assertEqual(old.execute("SELECT COUNT(*) FROM slots").fetchone()[0], 3)
        old.close()
        self.assertEqual(mapping_store.sync_status(self.path)["last_import"]["changed_slots"], 1)

    def test_import_refuses_when_the_file_or_database_changed_after_the_preview(self):
        self.external(lambda d: d["slots"][0].__setitem__("notes", "uno"))
        p = mapping_store.preview_import(self.path)
        self.external(lambda d: d["slots"][0].__setitem__("notes", "dos"))
        with self.assertRaises(mapping_store.StaleError):
            mapping_store.import_json(self.path, p["file_sha256"], p["db_export_sha256"], history_dir=self.hist)
        p2 = mapping_store.preview_import(self.path)
        with self.assertRaises(mapping_store.StaleError):
            mapping_store.import_json(self.path, p2["file_sha256"], "0" * 64, history_dir=self.hist)
        self.assertNotEqual(self.db_doc()["slots"][0].get("notes"), "dos")

    def test_import_refuses_invalid_or_non_canonical_files(self):
        self.path.write_bytes(b"{not json")
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.preview_import(self.path)
        bad = copy.deepcopy(self.doc)
        bad["slots"][0]["audio"]["status"] = "maybe"
        self.path.write_bytes(mapping_db.serialize(bad))
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.preview_import(self.path)
        self.path.write_bytes(json.dumps(self.doc).encode("utf-8"))  # valid but not the Studio's format
        with self.assertRaises(mapping_store.StoreError):
            mapping_store.preview_import(self.path)

    def test_export_writes_the_database_over_an_external_edit_and_keeps_it(self):
        _doc, data = self.external(lambda d: d["slots"][0].__setitem__("notes", "perder no"))
        seen = mapping_db.sha256(data)
        with self.assertRaises(mapping_store.StaleError):
            mapping_store.export_json(self.path, "0" * 64, history_dir=self.hist)
        mapping_store.export_json(self.path, seen, history_dir=self.hist)
        self.assertEqual(mapping_store.load(self.path)[0], self.doc)
        kept = list(self.hist.glob("*.replaced-by-export.json"))
        self.assertEqual([k.read_bytes() for k in kept], [data])

    def test_export_recreates_a_missing_file(self):
        self.path.unlink()
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "missing")
        mapping_store.export_json(self.path, None, history_dir=self.hist)
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")

    def test_a_v3_database_upgrades_to_v4_keeping_its_history(self):
        doc = copy.deepcopy(self.doc)
        doc["slots"][0]["notes"] = "antes de v4"
        self.sha = mapping_store.save(self.path, doc, self.sha, history_dir=self.hist)
        raw = sqlite3.connect(self.db)
        raw.executescript("CREATE TABLE h2 AS SELECT id, changed_at, mapping_id, before_body, after_body FROM slot_history;"
                          "DROP TABLE slot_history; ALTER TABLE h2 RENAME TO slot_history; PRAGMA user_version = 3;")
        raw.close()
        conn = mapping_db.open_existing(self.db)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT COUNT(*), MAX(reason) FROM slot_history").fetchone(), (1, None))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
