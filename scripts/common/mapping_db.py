"""SQLite storage for the manual-mapping decisions (migration step 3 of the Studio plan).

Why this shape:
- Each slot is stored as its exact JSON document (`body`), in file order. The
  export rebuilds the original `manual-mappings/3` document from those bodies, so
  the migration can be proven byte-for-byte against mappings/manual_mappings.json
  instead of "equivalent after normalisation".
- The indexed columns (statuses, flags, ids) are derived from `body` by one
  function, `slot_columns()`. Queries use them; nothing else may write them.
  That keeps one source of truth per slot while still allowing indexed search.
- `PRAGMA user_version` is the database schema version. Later versions add tables
  through explicit migrations here; they never reshape existing rows silently.

This module does not touch mappings/. It is storage only; approval rules stay in
scripts/common/mapping_store.py and are not duplicated here.
"""
import json
import sqlite3
from pathlib import Path

from .jsonschema_lite import load_schema, validate

DB_SCHEMA_VERSION = 1
SOURCE_SCHEMA = "manual-mappings/3"

DDL = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE slots (
    position        INTEGER PRIMARY KEY,            -- order in the source file
    mapping_id      TEXT NOT NULL UNIQUE,
    slot_id         TEXT NOT NULL UNIQUE,
    mcc_tag         TEXT NOT NULL,
    match_status    TEXT NOT NULL,
    audio_status    TEXT NOT NULL,
    subtitle_status TEXT NOT NULL,
    radio_needed    INTEGER NOT NULL,
    body            TEXT NOT NULL                   -- exact slot JSON as stored in the source
);
CREATE INDEX slots_match_status    ON slots (match_status);
CREATE INDEX slots_audio_status    ON slots (audio_status);
CREATE INDEX slots_subtitle_status ON slots (subtitle_status);
CREATE INDEX slots_radio_needed    ON slots (radio_needed);
CREATE INDEX slots_mcc_tag         ON slots (mcc_tag);
"""


class MappingDbError(Exception):
    pass


def serialize(doc):
    """The exact bytes mapping_store writes. Used to prove the export is byte-identical."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def slot_columns(slot):
    """Indexed columns derived from one slot document. The only place they are computed."""
    return {
        "mapping_id": slot["mapping_id"],
        "slot_id": slot["slot_id"],
        "mcc_tag": slot["mcc_tag"],
        "match_status": slot["match"]["status"],
        "audio_status": slot["audio"]["status"],
        "subtitle_status": slot["subtitle"]["status"],
        "radio_needed": 1 if slot["radio_effect"]["needed"] else 0,
    }


def create(path):
    """Create an empty database at `path`. Refuses to overwrite an existing file."""
    path = Path(path)
    if path.exists():
        raise MappingDbError(f"{path} already exists; choose a new file")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    conn.commit()
    return conn


def open_existing(path):
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=rw", uri=True)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != DB_SCHEMA_VERSION:
        conn.close()
        raise MappingDbError(f"{path}: database schema {version}, this build expects {DB_SCHEMA_VERSION}")
    return conn


def import_document(conn, doc):
    """Load a validated manual-mappings/3 document into an empty database."""
    if doc.get("schema") != SOURCE_SCHEMA:
        raise MappingDbError(f"expected {SOURCE_SCHEMA}, got {doc.get('schema')!r}")
    errors = validate(doc, load_schema("manual-mappings-3"))
    if errors:
        raise MappingDbError("source fails schema: " + "; ".join(errors[:5]))
    if conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]:
        raise MappingDbError("refusing to import into a database that already holds slots")
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        # Key order is kept as in the file: the export must be byte-identical to it.
        [("source_schema", doc["schema"]), ("pins", json.dumps(doc["pins"], ensure_ascii=False))],
    )
    conn.executemany(
        "INSERT INTO slots (position, mapping_id, slot_id, mcc_tag, match_status, audio_status, "
        "subtitle_status, radio_needed, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                position,
                *slot_columns_tuple(slot),
                json.dumps(slot, ensure_ascii=False, indent=2, sort_keys=False),
            )
            for position, slot in enumerate(doc["slots"])
        ],
    )
    conn.commit()


def slot_columns_tuple(slot):
    c = slot_columns(slot)
    return (c["mapping_id"], c["slot_id"], c["mcc_tag"], c["match_status"], c["audio_status"],
            c["subtitle_status"], c["radio_needed"])


def export_document(conn):
    """Rebuild the manual-mappings/3 document from the stored slot bodies, in file order."""
    pins = dict(
        (k, v) for k, v in conn.execute("SELECT key, value FROM meta WHERE key = 'pins'")
    )
    if "pins" not in pins:
        raise MappingDbError("database has no pins")
    source_schema = conn.execute("SELECT value FROM meta WHERE key = 'source_schema'").fetchone()
    if source_schema is None:
        raise MappingDbError("database has no source schema")
    slots = [json.loads(body) for (body,) in conn.execute("SELECT body FROM slots ORDER BY position")]
    return {"schema": source_schema[0], "pins": json.loads(pins["pins"]), "slots": slots}


def check_derived_columns(conn):
    """Every indexed column must equal what slot_columns() derives from its body."""
    bad = []
    rows = conn.execute("SELECT position, mapping_id, slot_id, mcc_tag, match_status, audio_status, "
                        "subtitle_status, radio_needed, body FROM slots ORDER BY position")
    for row in rows:
        position, *columns, body = row
        expected = slot_columns_tuple(json.loads(body))
        if tuple(columns) != expected:
            bad.append(position)
    return bad
