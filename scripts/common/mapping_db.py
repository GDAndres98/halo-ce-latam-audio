"""SQLite storage for the manual-mapping decisions.

Why this shape:
- Each slot is stored as its exact JSON document (`body`), in file order. The
  export rebuilds the original `manual-mappings/3` document from those bodies, so
  the export can be proven byte-for-byte against mappings/manual_mappings.json
  instead of "equivalent after normalisation".
- The indexed columns (statuses, flags, ids) are derived from `body` by one
  function, `slot_columns()`. Queries use them; nothing else may write them.
- `slot_history` keeps the before/after body of every slot a save changes. It
  replaces the full-file copies in mappings/.history/ for this file (each copy
  was 1.3 MB; 715 of them took 409 MB).
- The JSON file is a derived export, written only by scripts/common/mapping_store.py
  after the database commit. `pending_json_write` marks the window between the two
  writes, so a crash in that window is repaired on the next read instead of being
  mistaken for a hand edit.
- `PRAGMA user_version` is the database schema version. A later version adds
  tables through explicit migrations here; it never reshapes rows silently.

This module does not check approval rules. Those stay in scripts/common/mapping_store.py.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

from .jsonschema_lite import load_schema, validate

DB_SCHEMA_VERSION = 3
SOURCE_SCHEMA = "manual-mappings/3"

DDL = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE slots (
    position        INTEGER PRIMARY KEY,            -- order in the file
    mapping_id      TEXT NOT NULL UNIQUE,
    slot_id         TEXT NOT NULL UNIQUE,
    mcc_tag         TEXT NOT NULL,
    match_status    TEXT NOT NULL,
    audio_status    TEXT NOT NULL,
    subtitle_status TEXT NOT NULL,
    radio_needed    INTEGER NOT NULL,
    body            TEXT NOT NULL                   -- exact slot JSON as stored in the file
);
CREATE INDEX slots_match_status    ON slots (match_status);
CREATE INDEX slots_audio_status    ON slots (audio_status);
CREATE INDEX slots_subtitle_status ON slots (subtitle_status);
CREATE INDEX slots_radio_needed    ON slots (radio_needed);
CREATE INDEX slots_mcc_tag         ON slots (mcc_tag);
CREATE TABLE slot_history (
    id          INTEGER PRIMARY KEY,
    changed_at  TEXT NOT NULL,
    mapping_id  TEXT NOT NULL,
    before_body TEXT,                               -- NULL when the slot was added
    after_body  TEXT                                -- NULL when the slot was removed
);
CREATE INDEX slot_history_mapping ON slot_history (mapping_id);
CREATE TABLE documents (
    name               TEXT PRIMARY KEY,            -- e.g. manual_mappings.local.json
    body               TEXT NOT NULL,               -- exact file text (canonical JSON): the source of truth
    export_sha256      TEXT NOT NULL,               -- hash of the file the store last wrote or verified
    pending_json_write INTEGER NOT NULL             -- 1 between a database commit and its JSON write
);
CREATE TABLE document_history (
    id          INTEGER PRIMARY KEY,
    changed_at  TEXT NOT NULL,
    name        TEXT NOT NULL,
    before_body TEXT,                               -- NULL on the first import
    after_body  TEXT
);
"""

# Version 2 -> 3 only adds the two document tables. Nothing existing is touched.
DDL_V3_DOCUMENTS = DDL[DDL.index("CREATE TABLE documents"):]


class MappingDbError(Exception):
    pass


DB_FILE = "manual_mappings.db"


def db_path_for(path):
    """The one database of the mapping folder, whichever file of it is asked about (git-ignored).
    Every user file lives in the same database, so the name must not follow the file's own name."""
    return Path(path).with_name(DB_FILE)


def serialize(doc):
    """The exact bytes the store writes. Used to prove the export is byte-identical to the file."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def body_of(slot):
    """How a slot is stored. Diffing and history compare these strings."""
    return json.dumps(slot, ensure_ascii=False, indent=2)


def slot_columns(slot):
    """Indexed columns derived from one slot document. The only place they are computed."""
    return (
        slot["mapping_id"],
        slot["slot_id"],
        slot["mcc_tag"],
        slot["match"]["status"],
        slot["audio"]["status"],
        slot["subtitle"]["status"],
        1 if slot["radio_effect"]["needed"] else 0,
    )


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
    if version == 2:
        upgrade_v2_to_v3(conn)
        version = DB_SCHEMA_VERSION
    if version != DB_SCHEMA_VERSION:
        conn.close()
        raise MappingDbError(f"{path}: database schema {version}, this build expects {DB_SCHEMA_VERSION}")
    return conn


def upgrade_v2_to_v3(conn):
    """Adds the documents tables (user files: custom subtitles, mission progress). Additive only."""
    conn.executescript(DDL_V3_DOCUMENTS.replace("CREATE TABLE documents", "CREATE TABLE IF NOT EXISTS documents")
                       .replace("CREATE TABLE document_history", "CREATE TABLE IF NOT EXISTS document_history"))
    conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    conn.commit()


def is_imported(path):
    """True when the decisions have been imported into this database (it may exist before that)."""
    if not Path(path).exists():
        return False
    conn = open_existing(path)
    try:
        return meta_get(conn, "source_schema") is not None
    finally:
        conn.close()


def meta_get(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def _write_meta(conn, values):
    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", values)


def import_document(conn, doc, json_sha256):
    """Load a validated manual-mappings/3 document into an empty database.
    json_sha256: hash of the file the document was read from (the export must match it)."""
    if doc.get("schema") != SOURCE_SCHEMA:
        raise MappingDbError(f"expected {SOURCE_SCHEMA}, got {doc.get('schema')!r}")
    errors = validate(doc, load_schema("manual-mappings-3"))
    if errors:
        raise MappingDbError("source fails schema: " + "; ".join(errors[:5]))
    if conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]:
        raise MappingDbError("refusing to import into a database that already holds slots")
    _write_meta(conn, [
        ("source_schema", doc["schema"]),
        # Key order is kept as in the file: the export must be byte-identical to it.
        ("pins", json.dumps(doc["pins"], ensure_ascii=False)),
        ("export_sha256", sha256(serialize(doc))),
        ("json_sha256", json_sha256),
        ("pending_json_write", "0"),
    ])
    conn.executemany(
        "INSERT INTO slots (position, mapping_id, slot_id, mcc_tag, match_status, audio_status, "
        "subtitle_status, radio_needed, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(position, *slot_columns(slot), body_of(slot)) for position, slot in enumerate(doc["slots"])],
    )
    conn.commit()


def replace_slots(conn, doc, changed_at):
    """Replace the whole document in one transaction and record each changed slot in slot_history.
    Sets pending_json_write=1: the caller must write the JSON file and then call mark_json_synced().
    Unchanged slots keep their rows, so their history is untouched."""
    old = {mid: body for mid, body in conn.execute("SELECT mapping_id, body FROM slots")}
    new = {slot["mapping_id"]: body_of(slot) for slot in doc["slots"]}
    history = []
    for mid in old.keys() | new.keys():
        before, after = old.get(mid), new.get(mid)
        if before != after:
            history.append((changed_at, mid, before, after))
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM slots")
        conn.executemany(
            "INSERT INTO slots (position, mapping_id, slot_id, mcc_tag, match_status, audio_status, "
            "subtitle_status, radio_needed, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(position, *slot_columns(slot), body_of(slot)) for position, slot in enumerate(doc["slots"])],
        )
        conn.executemany("INSERT INTO slot_history (changed_at, mapping_id, before_body, after_body) "
                         "VALUES (?, ?, ?, ?)", history)
        _write_meta(conn, [
            ("source_schema", doc["schema"]),
            ("pins", json.dumps(doc["pins"], ensure_ascii=False)),
            ("export_sha256", sha256(serialize(doc))),
            ("pending_json_write", "1"),
        ])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(history)


def mark_json_synced(conn, json_sha256):
    _write_meta(conn, [("json_sha256", json_sha256), ("pending_json_write", "0")])
    conn.commit()


def export_document(conn):
    """Rebuild the manual-mappings/3 document from the stored slot bodies, in file order."""
    pins, schema = meta_get(conn, "pins"), meta_get(conn, "source_schema")
    if pins is None or schema is None:
        raise MappingDbError("database has no pins or schema")
    slots = [json.loads(body) for (body,) in conn.execute("SELECT body FROM slots ORDER BY position")]
    return {"schema": schema, "pins": json.loads(pins), "slots": slots}


def export_bytes(conn):
    return serialize(export_document(conn))


def check_derived_columns(conn):
    """Positions whose indexed columns no longer match their body. Empty when consistent."""
    bad = []
    rows = conn.execute("SELECT position, mapping_id, slot_id, mcc_tag, match_status, audio_status, "
                        "subtitle_status, radio_needed, body FROM slots ORDER BY position")
    for position, *columns, body in rows:
        if tuple(columns) != slot_columns(json.loads(body)):
            bad.append(position)
    return bad


# --------------------------------------------------------------------------- user documents
# Small user-owned files (custom subtitles, mission progress). Same contract as the decisions:
# the row body is the source, the file is an export, and every change is recorded in document_history.

def document_get(conn, name):
    """-> (body bytes, export sha256, pending flag) or None when the document was never stored."""
    row = conn.execute("SELECT body, export_sha256, pending_json_write FROM documents WHERE name = ?",
                       (name,)).fetchone()
    if row is None:
        return None
    return row[0].encode("utf-8"), row[1], row[2] == 1


def document_put(conn, name, data, changed_at, *, pending):
    """Store the exact file bytes in one transaction, with a history row when they change.
    pending=True means the JSON file still has to be written (document_mark_synced)."""
    body = data.decode("utf-8")
    old = conn.execute("SELECT body FROM documents WHERE name = ?", (name,)).fetchone()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO documents (name, body, export_sha256, pending_json_write) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET body = excluded.body, export_sha256 = excluded.export_sha256, "
            "pending_json_write = excluded.pending_json_write",
            (name, body, sha256(data), 1 if pending else 0))
        if old is None or old[0] != body:
            conn.execute("INSERT INTO document_history (changed_at, name, before_body, after_body) "
                         "VALUES (?, ?, ?, ?)", (changed_at, name, None if old is None else old[0], body))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def document_mark_synced(conn, name):
    conn.execute("UPDATE documents SET pending_json_write = 0 WHERE name = ?", (name,))
    conn.commit()
