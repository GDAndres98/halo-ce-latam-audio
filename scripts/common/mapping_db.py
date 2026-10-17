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
  tables or columns through explicit migrations here; it never reshapes rows silently.
  v2 -> v3: the documents tables. v3 -> v4: slot_history.reason (why a row was written:
  NULL for an ordinary Studio save, "import:<sha256>" for an explicit JSON import).
- SQLite is the source of truth. The JSON file is rewritten from it after every save; a file
  that differs (a git checkout, an editor) is never read back silently. The owner either
  re-exports the database over it or imports it explicitly (mapping_store.preview_import /
  import_json), which shows the differences first and records every changed slot here.

This module does not check approval rules. Those stay in scripts/common/mapping_store.py.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

from .jsonschema_lite import load_schema, validate

DB_SCHEMA_VERSION = 5
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
    after_body  TEXT,                               -- NULL when the slot was removed
    reason      TEXT                                -- NULL: Studio save; "import:<sha256>": JSON import
);
CREATE INDEX slot_history_mapping ON slot_history (mapping_id);
CREATE TABLE added_takes (
    position     INTEGER PRIMARY KEY,               -- order in the file's added_takes list
    take_id      TEXT NOT NULL UNIQUE,
    mcc_tag      TEXT NOT NULL,
    audio_status TEXT NOT NULL,
    body         TEXT NOT NULL                      -- exact take JSON as stored in the file
);
CREATE INDEX added_takes_mcc_tag ON added_takes (mcc_tag);
CREATE TABLE added_take_history (
    id          INTEGER PRIMARY KEY,
    changed_at  TEXT NOT NULL,
    take_id     TEXT NOT NULL,
    before_body TEXT,                               -- NULL when the take was added
    after_body  TEXT,                               -- NULL when the take was removed
    reason      TEXT
);
CREATE INDEX added_take_history_take ON added_take_history (take_id);
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
DDL_V5_TAKES = DDL[DDL.index("CREATE TABLE added_takes"):DDL.index("CREATE TABLE documents")]


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


def _list_block(bodies):
    """A top-level list as json.dumps(indent=2) writes it, from bodies encoded at depth 0."""
    if not bodies:
        return "[]"
    return "[\n" + ",\n".join("    " + b.replace("\n", "\n    ") for b in bodies) + "\n  ]"


def serialize_from_bodies(schema, pins, bodies, take_bodies=()):
    """serialize({"schema", "pins", "slots"[, "added_takes"]}) built from the stored bodies instead of encoding
    every slot again. Byte-identical: json.dumps(indent=2) writes a slot at depth 2 exactly as body_of() writes
    it at depth 0, with every line indented four more spaces (tests/test_mapping_sync.py checks it on the live
    file). Python's indenting encoder is pure Python; encoding 536 slots took ~70 ms per save. added_takes is
    written only when there is at least one (an empty list is never stored), so files without added takes are
    byte-identical to before."""
    head = json.dumps({"schema": schema, "pins": pins, "slots": []}, indent=2, ensure_ascii=False)
    assert head.endswith('"slots": []\n}')
    text = head[:-len("[]\n}")] + _list_block(bodies)
    if take_bodies:
        text += ',\n  "added_takes": ' + _list_block(take_bodies)
    return (text + "\n}\n").encode("utf-8")


def take_columns(take):
    """Indexed columns of one added take."""
    return take["take_id"], take["mcc_tag"], take["audio"]["status"]


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
        version = 3
    if version == 3:
        upgrade_v3_to_v4(conn)
        version = 4
    if version == 4:
        upgrade_v4_to_v5(conn)
        version = 5
    if version != DB_SCHEMA_VERSION:
        conn.close()
        raise MappingDbError(f"{path}: database schema {version}, this build expects {DB_SCHEMA_VERSION}")
    return conn


def upgrade_v2_to_v3(conn):
    """Adds the documents tables (user files: custom subtitles, mission progress). Additive only."""
    conn.executescript(DDL_V3_DOCUMENTS.replace("CREATE TABLE documents", "CREATE TABLE IF NOT EXISTS documents")
                       .replace("CREATE TABLE document_history", "CREATE TABLE IF NOT EXISTS document_history"))
    conn.execute("PRAGMA user_version = 3")
    conn.commit()


def upgrade_v3_to_v4(conn):
    """Adds slot_history.reason. Additive only: existing history rows keep NULL (ordinary saves)."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(slot_history)")]
    if "reason" not in columns:
        conn.execute("ALTER TABLE slot_history ADD COLUMN reason TEXT")
    conn.execute("PRAGMA user_version = 4")
    conn.commit()


def upgrade_v4_to_v5(conn):
    """Adds the added_takes tables (docs/added-takes-design.md). Additive only: no existing row changes."""
    conn.executescript(DDL_V5_TAKES.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ")
                       .replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS "))
    conn.execute("PRAGMA user_version = 5")
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
    conn.executemany(
        "INSERT INTO added_takes (position, take_id, mcc_tag, audio_status, body) VALUES (?, ?, ?, ?, ?)",
        [(position, *take_columns(t), body_of(t)) for position, t in enumerate(doc.get("added_takes", []))])
    conn.commit()


def replace_slots(conn, doc, changed_at, reason=None, data=None):
    """store_document() for callers that only need the number of history rows written."""
    return store_document(conn, doc, changed_at, reason=reason, data=data)[0]


def store_document(conn, doc, changed_at, *, reason=None, data=None, changed_ids=None):
    """Store the whole document in one transaction and record each changed slot in slot_history.
    Only rows that changed are written (a save usually changes one slot); unchanged rows and their
    history are untouched. Sets pending_json_write=1: the caller must write the JSON file and then call
    mark_json_synced(). reason: see slot_history.reason. data: serialize(doc) if the caller already has it.
    changed_ids: the mapping_ids the caller knows changed (by comparing with the document it loaded from
    this database); every other slot keeps its stored body without being encoded again.
    -> (history rows written, the export bytes = serialize(doc))"""
    old = {mid: (pos, body) for pos, mid, body in conn.execute("SELECT position, mapping_id, body FROM slots")}

    def body(slot):
        mid = slot["mapping_id"]
        if changed_ids is not None and mid not in changed_ids and mid in old:
            return old[mid][1]
        return body_of(slot)

    new = [(position, slot, body(slot)) for position, slot in enumerate(doc["slots"])]
    new_ids = {slot["mapping_id"] for _, slot, _ in new}
    history, upserts = [], []
    for position, slot, body in new:
        mid = slot["mapping_id"]
        before = old.get(mid)
        if before is None or before[1] != body:
            history.append((changed_at, mid, None if before is None else before[1], body, reason))
        if before is None or before != (position, body):
            upserts.append((position, *slot_columns(slot), body))
    removed = [mid for mid in old if mid not in new_ids]
    history += [(changed_at, mid, old[mid][1], None, reason) for mid in removed]
    # Added takes: a small list, rewritten as a whole; history for each take that changed.
    old_takes = {tid: body for tid, body in conn.execute("SELECT take_id, body FROM added_takes")}
    new_takes = [(position, t, body_of(t)) for position, t in enumerate(doc.get("added_takes", []))]
    take_history = [(changed_at, t["take_id"], old_takes.get(t["take_id"]), b, reason)
                    for _, t, b in new_takes if old_takes.get(t["take_id"]) != b]
    kept = {t["take_id"] for _, t, _ in new_takes}
    take_history += [(changed_at, tid, b, None, reason) for tid, b in old_takes.items() if tid not in kept]
    if data is None:
        data = serialize_from_bodies(doc["schema"], doc["pins"], [b for _, _, b in new],
                                     [b for _, _, b in new_takes])
    export_sha = sha256(data)
    try:
        conn.execute("BEGIN")
        conn.executemany("DELETE FROM slots WHERE mapping_id = ?", [(mid,) for mid in removed])
        if any(old.get(u[1], (None,))[0] != u[0] for u in upserts):
            # Positions move (a slot added or removed in the middle): rewrite the rows that moved without
            # colliding on the position key.
            conn.executemany("DELETE FROM slots WHERE mapping_id = ?", [(u[1],) for u in upserts])
        conn.executemany(
            "INSERT INTO slots (position, mapping_id, slot_id, mcc_tag, match_status, audio_status, "
            "subtitle_status, radio_needed, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(mapping_id) DO UPDATE SET position = excluded.position, slot_id = excluded.slot_id, "
            "mcc_tag = excluded.mcc_tag, match_status = excluded.match_status, audio_status = excluded.audio_status, "
            "subtitle_status = excluded.subtitle_status, radio_needed = excluded.radio_needed, body = excluded.body",
            upserts)
        conn.executemany("INSERT INTO slot_history (changed_at, mapping_id, before_body, after_body, reason) "
                         "VALUES (?, ?, ?, ?, ?)", history)
        stored = [(tid, body) for tid, body in conn.execute("SELECT take_id, body FROM added_takes ORDER BY position")]
        if stored != [(t["take_id"], b) for _, t, b in new_takes]:  # any change, removal or new order
            conn.execute("DELETE FROM added_takes")
            conn.executemany("INSERT INTO added_takes (position, take_id, mcc_tag, audio_status, body) "
                             "VALUES (?, ?, ?, ?, ?)", [(p, *take_columns(t), b) for p, t, b in new_takes])
            conn.executemany("INSERT INTO added_take_history (changed_at, take_id, before_body, after_body, reason) "
                             "VALUES (?, ?, ?, ?, ?)", take_history)
        _write_meta(conn, [
            ("source_schema", doc["schema"]),
            ("pins", json.dumps(doc["pins"], ensure_ascii=False)),
            ("export_sha256", export_sha),
            ("pending_json_write", "1"),
        ])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(history), data


def mark_json_synced(conn, json_sha256):
    _write_meta(conn, [("json_sha256", json_sha256), ("pending_json_write", "0")])
    conn.commit()


def export_document(conn):
    """Rebuild the manual-mappings/3 document from the stored slot bodies, in file order."""
    pins, schema = meta_get(conn, "pins"), meta_get(conn, "source_schema")
    if pins is None or schema is None:
        raise MappingDbError("database has no pins or schema")
    slots = [json.loads(body) for (body,) in conn.execute("SELECT body FROM slots ORDER BY position")]
    doc = {"schema": schema, "pins": json.loads(pins), "slots": slots}
    takes = [json.loads(body) for (body,) in conn.execute("SELECT body FROM added_takes ORDER BY position")]
    if takes:
        doc["added_takes"] = takes
    return doc


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
