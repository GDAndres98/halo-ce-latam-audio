"""SQLite mapping storage: round trip, derived columns, refusals.

The live-file test only reads mappings/manual_mappings.json. Everything else works
on copies in a temporary directory.
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

from common import mapping_db  # noqa: E402

LIVE = ROOT / "mappings" / "manual_mappings.json"


def load_live():
    raw = LIVE.read_bytes()
    return raw, json.loads(raw.decode("utf-8"))


class MappingDbTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, doc, name="m.sqlite"):
        path = self.tmp / name
        conn = mapping_db.create(path)
        try:
            mapping_db.import_document(conn, doc, mapping_db.sha256(mapping_db.serialize(doc)))
        finally:
            conn.close()
        return path

    def test_live_file_round_trips_byte_for_byte(self):
        if not LIVE.exists():
            self.skipTest("no live mappings file in this checkout")
        raw, doc = load_live()
        conn = mapping_db.open_existing(self.build(doc))
        try:
            exported = mapping_db.export_document(conn)
        finally:
            conn.close()
        self.assertEqual(mapping_db.serialize(exported), raw)

    def test_unicode_notes_survive_the_round_trip(self):
        if not LIVE.exists():
            self.skipTest("no live mappings file in this checkout")
        _, doc = load_live()
        doc = copy.deepcopy(doc)
        doc["slots"][0]["notes"] = "Ñandú — «prueba» 🎧"
        conn = mapping_db.open_existing(self.build(doc))
        try:
            exported = mapping_db.export_document(conn)
        finally:
            conn.close()
        self.assertEqual(exported, doc)

    def test_indexed_columns_follow_the_slot_bodies(self):
        if not LIVE.exists():
            self.skipTest("no live mappings file in this checkout")
        _, doc = load_live()
        path = self.build(doc)
        conn = mapping_db.open_existing(path)
        try:
            self.assertEqual(mapping_db.check_derived_columns(conn), [])
            count = conn.execute(
                "SELECT COUNT(*) FROM slots WHERE audio_status = 'approved'").fetchone()[0]
            self.assertEqual(count, sum(1 for s in doc["slots"] if s["audio"]["status"] == "approved"))
        finally:
            conn.close()

    def test_a_drifted_indexed_column_is_reported(self):
        _, doc = self.synthetic_doc()
        path = self.build(doc)
        raw = sqlite3.connect(path)
        raw.execute("UPDATE slots SET audio_status = 'corrupted' WHERE position = 1")  # never a valid status
        raw.commit()
        raw.close()
        conn = mapping_db.open_existing(path)
        try:
            self.assertEqual(mapping_db.check_derived_columns(conn), [1])
        finally:
            conn.close()

    def test_refuses_wrong_source_schema_and_double_import(self):
        _, doc = self.synthetic_doc()
        bad = copy.deepcopy(doc)
        bad["schema"] = "manual-mappings/2"
        conn = mapping_db.create(self.tmp / "a.sqlite")
        sha = mapping_db.sha256(mapping_db.serialize(doc))
        try:
            with self.assertRaises(mapping_db.MappingDbError):
                mapping_db.import_document(conn, bad, sha)
            mapping_db.import_document(conn, doc, sha)
            with self.assertRaises(mapping_db.MappingDbError):
                mapping_db.import_document(conn, doc, sha)  # never merge into an existing database
        finally:
            conn.close()

    def test_refuses_to_overwrite_and_checks_version(self):
        _, doc = self.synthetic_doc()
        path = self.build(doc)
        with self.assertRaises(mapping_db.MappingDbError):
            mapping_db.create(path)
        raw = sqlite3.connect(path)
        raw.execute("PRAGMA user_version = 99")
        raw.commit()
        raw.close()
        with self.assertRaises(mapping_db.MappingDbError):
            mapping_db.open_existing(path)

    def synthetic_doc(self):
        """Two-slot document in the real v3 shape. Built from the live file when present."""
        if LIVE.exists():
            raw, doc = load_live()
            doc = copy.deepcopy(doc)
            doc["slots"] = doc["slots"][:2]
            return raw, doc
        self.skipTest("needs the live mappings file for a valid v3 template")


if __name__ == "__main__":
    unittest.main()
