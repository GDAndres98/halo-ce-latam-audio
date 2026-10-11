"""Protected write path for mappings/manual_mappings.json (milestone M3).

The M4 matching UI (scripts/ui/m4_app.py) saves through this, and nothing
else may write the file. `save_user_file` gives the other user-owned files
(manual_mappings.local.json, mission_progress.json) the same stale-check,
schema check, backup and atomic write. Guarantees (docs/dialogue-catalog-design.md
§5.4):

1. Stale-save refusal: the on-disk bytes must still hash to what was loaded.
2. Tools never approve: an object may only become `approved` through an
   explicit `UserAction("approve", ...)`.
3. Approved objects are immutable: they may only change through
   `UserAction("needs_rework", ...)`, which must bump `revision` by exactly 1.
   Mappings holding an approved object can't be deleted or retargeted.
4. The new document must pass the current schema (manual-mappings/3) and
   keep the loaded document's schema version; version changes go only
   through `migrate()`, which proves approved decisions survive unchanged.
5. The previous bytes are backed up to mappings/.history/ before every save,
   then written atomically (temp file, fsync, rename).
"""
import datetime as dt
import hashlib
import copy
import json
import os
from collections import namedtuple
from pathlib import Path

from . import mapping_db
from .jsonschema_lite import load_schema, validate

UserAction = namedtuple("UserAction", "action mapping_id field")  # action: approve | needs_rework
SCHEMA_ID = "manual-mappings/3"
SCHEMA_NAME = "manual-mappings-3"
OWNER_FLAGS = ("radio_effect", "different_but_fits", "needs_recording")  # slot-level flags outside the approved objects
DB_MANAGED = "manual_mappings.json"  # the decisions file: SQLite is its writer, this JSON is the export
DOCUMENT_FILES = ("manual_mappings.local.json", "mission_progress.json")  # user files stored as documents


class StoreError(Exception):
    pass


class StaleError(StoreError):
    pass


class ProtectedError(StoreError):
    pass


def load(path):
    data = _current(path)
    return json.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()


def load_or_default(path, default):
    """Like load(), but a file that does not exist yet loads as `default` (sha of empty bytes)."""
    data = _current(path)
    if not data:
        return copy.deepcopy(default), EMPTY_SHA256
    return json.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()


def _current(path):
    """Bytes of a store-managed file as the store sees them.

    manual_mappings.json: the export of the decisions in mappings/manual_mappings.db.
    manual_mappings.local.json and mission_progress.json: documents stored in the same database.
    Created from the file on first use, after the canonical-format check. Other files are read as they are.

    A file that differs from what the database holds is refused, not overwritten: it was edited outside
    the Studio, and the owner decides what to keep."""
    path = Path(path)
    if path.name not in (DB_MANAGED, *DOCUMENT_FILES):
        return path.read_bytes() if path.exists() else b""
    db = mapping_db.db_path_for(path)
    if path.name in DOCUMENT_FILES:
        return _document_current(path, db)
    if not mapping_db.is_imported(db):
        if not path.exists():
            return b""
        raw = path.read_bytes()
        try:
            _import_decisions(path, db, raw)
        except mapping_db.MappingDbError:
            # Not a valid current-schema file (an older schema, or pre-migration fields). Return it as
            # it is: the migration tools read and upgrade it, and the database is created afterwards.
            return raw
    conn = mapping_db.open_existing(db)
    try:
        if mapping_db.meta_get(conn, "pending_json_write") == "1":
            # The database committed a save but the JSON write did not finish: finish it now.
            data = mapping_db.export_bytes(conn)
            _atomic_write(path, data)
            mapping_db.mark_json_synced(conn, mapping_db.sha256(data))
            return data
        # Compare hashes, not a fresh export: the database stored the export's hash in the same
        # transaction as the rows. Re-serialising 536 slots on every read cost ~50 ms per request.
        return _verified_file(path, mapping_db.meta_get(conn, "export_sha256"), db)
    finally:
        conn.close()


def _document_current(path, db):
    if not db.exists() and not path.exists():
        return b""  # nothing stored and nothing on disk: don't create a database just to say so
    conn = _open_or_create(db)
    try:
        row = mapping_db.document_get(conn, path.name)
        if row is None:
            if not path.exists():
                return b""
            raw = path.read_bytes()
            _check_document_schema(path, raw)
            mapping_db.document_put(conn, path.name, raw, _now_stamp(None), pending=False)
            return raw
        data, expected_sha, pending = row
        if pending:
            _atomic_write(path, data)
            mapping_db.document_mark_synced(conn, path.name)
            return data
        return _verified_file(path, expected_sha, db)
    finally:
        conn.close()


def _verified_file(path, expected_sha, db):
    on_disk = path.read_bytes() if path.exists() else None
    if on_disk is not None and mapping_db.sha256(on_disk) == expected_sha:
        return on_disk
    if on_disk is not None and mapping_db.sha256(_lf(on_disk)) == expected_sha:
        # Same content, Windows line endings (git checkout with core.autocrlf, or an editor). Not an
        # edit: read the canonical bytes. The next save writes the file back with LF.
        return _lf(on_disk)
    raise StoreError(f"{path.name} differs from {db.name}: it was changed outside the Studio. Nothing was "
                     "overwritten. Open Data in the Studio (or run python scripts/validate/mapping_sync.py "
                     "status) to see the differences, then import the file or export the database over it.")


def _lf(data):
    return data.replace(b"\r\n", b"\n")


def _check_document_schema(path, raw):
    name = {"manual_mappings.local.json": "manual-mappings-local-1", "mission_progress.json": "mission-progress-1"}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise StoreError(f"{path.name} is not valid JSON: {e}")
    errs = validate(doc, load_schema(name[path.name]))
    if errs:
        raise StoreError(f"{path.name} schema: " + "; ".join(errs[:5]))
    if mapping_db.serialize(doc) != raw:
        raise StoreError(f"{path.name} is not in the canonical format the Studio writes; nothing was imported")


def _open_or_create(db):
    return mapping_db.open_existing(db) if db.exists() else mapping_db.create(db)


def _now_stamp(now):
    return (now or dt.datetime.now()).isoformat(timespec="microseconds")


def _import_decisions(path, db, raw):
    """First use of manual_mappings.json: import it into the database (the same import that
    scripts/validate/migrate_mappings_db.py verifies). Nothing is written unless the canonical check
    passes first."""
    doc = json.loads(raw.decode("utf-8"))
    if doc.get("schema") != mapping_db.SOURCE_SCHEMA:  # an older file: the caller's migration handles it
        raise mapping_db.MappingDbError(f"{path.name} is {doc.get('schema')}, not {mapping_db.SOURCE_SCHEMA}")
    if mapping_db.serialize(doc) != raw:
        raise StoreError(f"{path.name} is not in the canonical format the Studio writes "
                         "(key order, indentation or line endings differ); nothing was imported")
    conn = _open_or_create(db)
    try:
        mapping_db.import_document(conn, doc, mapping_db.sha256(raw))
    finally:
        conn.close()


def _atomic_write(path, data):
    """Temp file, fsync, then rename: the file is either the old bytes or the new bytes."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _write_database_backed(path, doc, now, *, data=None, changed_ids=None):
    """Save the decisions: commit SQLite first (with slot history), then write the JSON export.
    data: exact bytes to write (a restore); otherwise the export is built from the stored slot bodies."""
    changed_at = (now or dt.datetime.now()).isoformat(timespec="microseconds")
    conn = mapping_db.open_existing(mapping_db.db_path_for(path))
    try:
        _, data = mapping_db.store_document(conn, doc, changed_at, data=data, changed_ids=changed_ids)
        _atomic_write(path, data)
        mapping_db.mark_json_synced(conn, mapping_db.sha256(data))
    finally:
        conn.close()
    return mapping_db.sha256(data)


def _write_document(path, data, now):
    """Save a user document: database first (with history), then the file, then clear the pending flag."""
    conn = _open_or_create(mapping_db.db_path_for(path))
    try:
        mapping_db.document_put(conn, path.name, data, _now_stamp(now), pending=True)
        _atomic_write(path, data)
        mapping_db.document_mark_synced(conn, path.name)
    finally:
        conn.close()
    return mapping_db.sha256(data)


def changed_mapping_ids(old_doc, new_doc):
    """mapping_ids whose slot is new or differs from old_doc (dict comparison, no serialisation)."""
    old = {s["mapping_id"]: s for s in old_doc.get("slots", [])}
    return {s["mapping_id"] for s in new_doc.get("slots", []) if old.get(s["mapping_id"]) != s}


def schema_errors(doc, schema, only_mapping_ids=None):
    """Schema errors of a manual-mappings document. With only_mapping_ids, the top-level fields and just those
    slots are checked, at their real positions (error paths stay /slots/<index>/...).

    That is equivalent to checking the whole document when every other slot is unchanged from a document
    the store already validated: the schema puts no constraint on the slots array as a whole (no
    uniqueItems, minItems or contains), only on each item. Saves check the 1 slot they change instead
    of all 536 (~150 ms per save)."""
    if only_mapping_ids is None:
        return validate(doc, schema)
    errs = validate({**doc, "slots": []}, schema)
    for i, slot in enumerate(doc.get("slots", [])):
        if slot.get("mapping_id") in only_mapping_ids:
            errs += validate(slot, schema["properties"]["slots"]["items"], schema, ("slots", i))
    return errs


def check_transition(old_doc, new_doc, user_actions=()):
    """Raise ProtectedError for any change the rules forbid. Pure."""
    allowed = {(a.mapping_id, a.field): a.action for a in user_actions}
    old = {s["mapping_id"]: s for s in old_doc.get("slots", [])}
    new = {s["mapping_id"]: s for s in new_doc.get("slots", [])}
    problems = []
    for mid, os_ in old.items():
        approved = [f for f in ("audio", "subtitle") if os_[f]["status"] == "approved"]
        if not approved:
            continue
        ns = new.get(mid)
        if ns is None:
            problems.append(f"{mid}: cannot delete a mapping with an approved decision")
            continue
        if ns["slot_id"] != os_["slot_id"]:
            problems.append(f"{mid}: cannot retarget an approved mapping")
        for f in approved:
            if ns[f] == os_[f]:
                continue
            ok = (allowed.get((mid, f)) == "needs_rework" and ns[f]["status"] == "needs_rework"
                  and ns[f]["revision"] == os_[f]["revision"] + 1)
            if not ok:
                problems.append(f"{mid}/{f}: approved decisions are immutable (only a user 'needs_rework' "
                                "action with revision + 1 may change them)")
    for mid, ns in new.items():
        for f in ("audio", "subtitle"):
            was = old.get(mid, {}).get(f, {}).get("status")
            if ns[f]["status"] == "approved" and was != "approved" and allowed.get((mid, f)) != "approve":
                problems.append(f"{mid}/{f}: only an explicit user 'approve' action can approve")
    for mid, ns in new.items():  # owner flags are independent of approvals, but every change is counted
        for flag in OWNER_FLAGS:
            oflag, nflag = old.get(mid, {}).get(flag), ns.get(flag)
            if oflag and nflag and oflag != nflag and nflag["revision"] != oflag["revision"] + 1:
                problems.append(f"{mid}/{flag}: a change must bump its revision by exactly 1")
    unused = [k for k, a in allowed.items() if a not in ("approve", "needs_rework")]
    if unused:
        problems.append(f"unknown user actions {unused}")
    if problems:
        raise ProtectedError("; ".join(problems))


def save(path, new_doc, loaded_sha256, *, user_actions=(), history_dir=None, now=None, schema=None):
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded; reload and re-apply your edit")
    old_doc = json.loads(current.decode("utf-8")) if current else {"slots": []}
    if current and old_doc.get("schema") != new_doc.get("schema"):
        raise StoreError(f"schema version change {old_doc.get('schema')} -> {new_doc.get('schema')}: "
                         "use mapping_store.migrate()")
    check_transition(old_doc, new_doc, user_actions)
    # The stored document passed this schema when it was written, so only the slots this save changes
    # need checking (schema_errors explains why that is the same result).
    only = changed_mapping_ids(old_doc, new_doc) if current else None
    errs = schema_errors(new_doc, schema or load_schema(SCHEMA_NAME), only)
    if errs:
        raise StoreError("schema: " + "; ".join(errs[:5]))
    return _write(path, current, new_doc, loaded_sha256, history_dir, now, changed_ids=only)


def _write(path, current, new_doc, loaded_sha256, history_dir, now, raw=None, changed_ids=None):
    """Back up the previous bytes to .history/, then write atomically. -> new sha256.
    raw: exact bytes to write instead of serializing new_doc (restore). changed_ids: see store_document."""
    history = Path(history_dir) if history_dir else path.parent / ".history"
    if current:  # every save keeps the previous bytes (M3 rule 5), also for the decisions file
        history.mkdir(parents=True, exist_ok=True)
        stamp = (now or dt.datetime.now()).strftime("%Y%m%dT%H%M%S%f")
        (history / f"{path.stem}.{stamp}.{loaded_sha256[:12]}.json").write_bytes(current)
    if path.name == DB_MANAGED and mapping_db.is_imported(mapping_db.db_path_for(path)):
        # Database first (with per-slot history), then the JSON export. Without an imported decisions
        # table (the schema migration, or a brand-new file) the JSON is written directly; the import
        # happens on the next read.
        doc = new_doc if raw is None else json.loads(raw.decode("utf-8"))
        return _write_database_backed(path, doc, now, data=raw, changed_ids=changed_ids if raw is None else None)
    data = raw if raw is not None else mapping_db.serialize(new_doc)
    if path.name in DOCUMENT_FILES:
        return _write_document(path, data, now)
    _atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()  # loaded hash of a file that doesn't exist yet


def save_user_file(path, new_doc, loaded_sha256, schema_name, *, history_dir=None, now=None):
    """Same stale-check, schema check, backup and atomic write for the other user-owned files
    (manual_mappings.local.json, mission_progress.json). They hold no approvals."""
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded; reload and re-apply your edit")
    errs = validate(new_doc, load_schema(schema_name))
    if errs:
        raise StoreError(f"{path.name} schema: " + "; ".join(errs[:5]))
    return _write(path, current, new_doc, loaded_sha256, history_dir, now)


# --------------------------------------------------------------------------- migrations
def migrate_doc(doc, today=None):
    """manual-mappings/2 -> /3 (pure). audio.fx_request == "radio" becomes radio_effect.needed.
    Returns (new_doc, changed). Any other version is returned unchanged."""
    if doc.get("schema") != "manual-mappings/2":
        return doc, False
    new = json.loads(json.dumps(doc))
    new["schema"] = SCHEMA_ID
    for s in new["slots"]:
        fx = s["audio"].pop("fx_request", None)
        notes = s.pop("notes")  # re-added last to keep the usual key order
        s["radio_effect"] = {"needed": fx == "radio",
                             "set_at": (s["match"].get("decided_at") or today) if fx == "radio" else None,
                             "revision": 1}
        s["notes"] = notes
    return new, True


REMOVED_EDIT_FIELDS = ("speed", "gain_db")  # audio.edit fields removed 2026-10-09 (owner-authorized reset)


def comparable(obj, field):
    """An approved object as the protection rules compare it across schema versions: without
    audio.fx_request (v2 -> v3) and without the removed edit fields speed / gain_db (2026-10-09; the
    current schema forbids them, so removing them is the only possible change)."""
    if field == "audio":
        out = {k: v for k, v in obj.items() if k != "fx_request"}
        if isinstance(out.get("edit"), dict):
            out["edit"] = {k: v for k, v in out["edit"].items() if k not in REMOVED_EDIT_FIELDS}
        return out
    return obj


def strip_removed_edit_fields(doc):
    """Pure. -> (new_doc, changes). Removes audio.edit.speed / gain_db from every mapping, draft or
    approved; nothing else. changes: [{mapping_id, slot_id, audio_status, audio_revision, previous}]."""
    new = json.loads(json.dumps(doc))
    changes = []
    for s in new.get("slots", []):
        edit = s["audio"].get("edit") or {}
        prev = {k: edit.pop(k) for k in REMOVED_EDIT_FIELDS if k in edit}
        if prev:
            changes.append({"mapping_id": s["mapping_id"], "slot_id": s["slot_id"],
                            "audio_status": s["audio"]["status"], "audio_revision": s["audio"]["revision"],
                            "previous": prev,
                            "non_default": {k: v for k, v in prev.items() if v != {"speed": 1, "gain_db": 0}[k]}})
    return new, changes


def proof_only_removed_fields(old_doc, new_doc):
    """Problems if new_doc differs from old_doc in anything but removed audio.edit fields (empty = proven)."""
    problems = []
    if {k: v for k, v in old_doc.items() if k != "slots"} != {k: v for k, v in new_doc.items() if k != "slots"}:
        problems.append("top-level fields changed")
    if [s["mapping_id"] for s in old_doc["slots"]] != [s["mapping_id"] for s in new_doc["slots"]]:
        problems.append("mapping ids or order changed")
        return problems
    for o, n in zip(old_doc["slots"], new_doc["slots"]):
        if {k: v for k, v in o.items() if k != "audio"} != {k: v for k, v in n.items() if k != "audio"}:
            problems.append(f"{o['mapping_id']}: something besides audio changed")
        if {k: v for k, v in o["audio"].items() if k != "edit"} != {k: v for k, v in n["audio"].items() if k != "edit"}:
            problems.append(f"{o['mapping_id']}: audio status/source/fingerprint/revision changed")
        oe = {k: v for k, v in o["audio"]["edit"].items() if k not in REMOVED_EDIT_FIELDS}
        if oe != n["audio"]["edit"]:
            problems.append(f"{o['mapping_id']}: edit fields besides speed/gain_db changed")
    return problems


def reset_removed_edit_fields(path, loaded_sha256, *, history_dir=None, now=None):
    """One-time, owner-authorized (2026-10-09) migration: remove audio.edit.speed and gain_db from every
    mapping, approved ones included, WITHOUT touching approvals (status, revision, approved_at,
    fingerprint stay as they are; nothing becomes needs_rework). Same stale check, backup to .history/
    and atomic write as every save. Refuses unless the result provably differs only in those fields.
    -> (new sha256 or None when there is nothing to do, changes)."""
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded")
    old = json.loads(current.decode("utf-8"))
    new, changes = strip_removed_edit_fields(old)
    if not changes:
        return None, []
    bad = proof_only_removed_fields(old, new)
    if bad:
        raise ProtectedError("; ".join(bad))
    errs = validate(new, load_schema(SCHEMA_NAME))
    if errs:
        raise StoreError("schema: " + "; ".join(errs[:5]))
    return _write(path, current, new, loaded_sha256, history_dir, now), changes


def migrate(path, loaded_sha256, *, history_dir=None, now=None):
    """Upgrade the file to the current schema with the usual stale check, backup and atomic write.
    Refuses if any approved object would differ (other than the dropped audio.fx_request).
    -> (new sha256 or None if already current, number of slots)."""
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded")
    old = json.loads(current.decode("utf-8"))
    new, changed = migrate_doc(old, (now or dt.datetime.now()).date().isoformat())
    if not changed:
        return None, len(old.get("slots", []))
    olds = {s["mapping_id"]: s for s in old["slots"]}
    for s in new["slots"]:
        o = olds[s["mapping_id"]]
        for f in ("audio", "subtitle"):
            if o[f]["status"] == "approved" and comparable(o[f], f) != comparable(s[f], f):
                raise ProtectedError(f"{s['mapping_id']}/{f}: migration would change an approved object")
    errs = validate(new, load_schema(SCHEMA_NAME))
    if errs:
        raise StoreError("schema: " + "; ".join(errs[:5]))
    return _write(path, current, new, loaded_sha256, history_dir, now), len(new["slots"])


def restore(path, data, loaded_sha256, *, history_dir=None, now=None):
    """Put back exact earlier bytes (a migration rollback): stale check, .history/ backup of the current
    file, atomic write. The caller proves `data` is the backup it means to restore. -> new sha256."""
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded")
    return _write(path, current, None, loaded_sha256, history_dir, now, raw=data)


# --------------------------------------------------------------------------- explicit JSON sync
# SQLite is the source of truth for the decisions. The JSON file is its export. When the file is changed
# outside the Studio, nothing reads it back automatically; the owner picks one of two explicit actions:
#   import_json  the file's decisions replace the database's (after preview_import shows every change)
#   export_json  the database is written over the file (the external file is kept in .history/ first)
# Both take the hashes the owner saw, so a file or database that changed in between is refused.

def sync_status(path):
    """How manual_mappings.json relates to the database. Read-only.
    state: in_sync | line_endings (same content, CRLF) | external_edit | missing | not_imported | pending."""
    path = Path(path)
    db = mapping_db.db_path_for(path)
    on_disk = path.read_bytes() if path.exists() else None
    out = {"file": path.name, "database": db.name,
           "file_sha256": None if on_disk is None else mapping_db.sha256(on_disk)}
    if not mapping_db.is_imported(db):
        return {**out, "state": "not_imported", "db_export_sha256": None, "last_import": None}
    conn = mapping_db.open_existing(db)
    try:
        expected = mapping_db.meta_get(conn, "export_sha256")
        pending = mapping_db.meta_get(conn, "pending_json_write") == "1"
        last_import = mapping_db.meta_get(conn, "last_import")
    finally:
        conn.close()
    out.update(db_export_sha256=expected, last_import=json.loads(last_import) if last_import else None)
    if pending:
        return {**out, "state": "pending"}
    if on_disk is None:
        return {**out, "state": "missing"}
    if mapping_db.sha256(on_disk) == expected:
        return {**out, "state": "in_sync"}
    if mapping_db.sha256(_lf(on_disk)) == expected:
        return {**out, "state": "line_endings"}
    return {**out, "state": "external_edit"}


def _slot_summary(slot):
    return {"match": slot["match"]["status"], "ce_line_refs": slot["match"]["ce_line_refs"],
            "audio": slot["audio"]["status"], "audio_source": slot["audio"]["source"],
            "audio_revision": slot["audio"]["revision"], "subtitle": slot["subtitle"]["status"],
            "subtitle_source": slot["subtitle"]["source"], "subtitle_revision": slot["subtitle"]["revision"],
            "radio": slot["radio_effect"]["needed"], "notes": slot.get("notes", "")}


def _read_import_candidate(path):
    """The file as an import candidate: canonical JSON (CRLF accepted), current schema, valid, no repeats."""
    if not path.exists():
        raise StoreError(f"{path.name} does not exist; there is nothing to import")
    raw = path.read_bytes()
    data = _lf(raw)
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise StoreError(f"{path.name} is not valid JSON: {e}")
    if doc.get("schema") != SCHEMA_ID:
        raise StoreError(f"{path.name} is {doc.get('schema')!r}; only {SCHEMA_ID} can be imported")
    errs = validate(doc, load_schema(SCHEMA_NAME))
    if errs:
        raise StoreError(f"{path.name} fails the schema: " + "; ".join(errs[:5]))
    if mapping_db.serialize(doc) != data:
        raise StoreError(f"{path.name} is not in the canonical format the Studio writes (key order or "
                         "indentation); nothing can be imported from it")
    ids = [x["slot_id"] for x in doc["slots"]]
    mids = [x["mapping_id"] for x in doc["slots"]]
    if len(set(ids)) != len(ids) or len(set(mids)) != len(mids):
        raise StoreError(f"{path.name} repeats a slot_id or mapping_id")
    return raw, data, doc


def preview_import(path):
    """What import_json would change, slot by slot. Read-only. The two hashes in the result are the
    confirmation import_json requires."""
    path = Path(path)
    raw, _data, doc = _read_import_candidate(path)
    conn = mapping_db.open_existing(mapping_db.db_path_for(path))
    try:
        current = mapping_db.export_document(conn)
        db_sha = mapping_db.meta_get(conn, "export_sha256")
    finally:
        conn.close()
    old = {x["mapping_id"]: x for x in current["slots"]}
    new = {x["mapping_id"]: x for x in doc["slots"]}
    changes = []
    for mid in sorted(old.keys() | new.keys()):
        a, b = old.get(mid), new.get(mid)
        if a == b:
            continue
        changes.append({"mapping_id": mid, "slot_id": (b or a)["slot_id"],
                        "kind": "added" if a is None else "removed" if b is None else "changed",
                        "fields": sorted(k for k in (a or {}).keys() | (b or {}).keys()
                                         if (a or {}).get(k) != (b or {}).get(k)),
                        "database": _slot_summary(a) if a else None, "file": _slot_summary(b) if b else None})

    def approvals(d):
        return {(x["mapping_id"], f) for x in d["slots"] for f in ("audio", "subtitle") if x[f]["status"] == "approved"}

    return {"file_sha256": mapping_db.sha256(raw), "db_export_sha256": db_sha,
            "line_endings": "CRLF" if b"\r\n" in raw else "LF",
            "slots_in_file": len(doc["slots"]), "slots_in_database": len(current["slots"]),
            "pins_change": doc["pins"] != current["pins"], "changes": changes,
            "approvals_added": sorted("/".join(k) for k in approvals(doc) - approvals(current)),
            "approvals_removed": sorted("/".join(k) for k in approvals(current) - approvals(doc))}


def _backup_database(db, history, stamp):
    """Consistent copy of the database (SQLite online backup, integrity-checked) into .history/."""
    import sqlite3
    history.mkdir(parents=True, exist_ok=True)
    out = history / f"{db.stem}.{stamp}.before-import.db"
    src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise StoreError(f"the database backup {out.name} failed its integrity check; nothing was imported")
    finally:
        src.close()
        dst.close()
    return out


def import_json(path, file_sha256, db_export_sha256, *, history_dir=None, now=None):
    """Explicit, owner-confirmed import: the file's decisions replace the database's.

    The owner confirms with the two hashes preview_import returned; if the file or the database changed
    since, nothing happens. The database is backed up to .history/ first, every changed slot gets a
    slot_history row with reason "import:<file sha256>", and the file is then rewritten in the canonical
    LF form (same content; CRLF bytes, if any, are kept in .history/). This may replace approved decisions
    only because the owner asked for exactly this file; ordinary saves keep every check_transition rule.
    -> {"imported_sha256", "changed_slots", "database_backup"}"""
    path = Path(path)
    db = mapping_db.db_path_for(path)
    raw, data, doc = _read_import_candidate(path)
    if mapping_db.sha256(raw) != file_sha256:
        raise StaleError(f"{path.name} changed since the preview; preview again")
    stamp_dt = now or dt.datetime.now()
    stamp = stamp_dt.strftime("%Y%m%dT%H%M%S%f")
    history = Path(history_dir) if history_dir else path.parent / ".history"
    conn = mapping_db.open_existing(db)
    try:
        if mapping_db.meta_get(conn, "export_sha256") != db_export_sha256:
            raise StaleError(f"{db.name} changed since the preview; preview again")
        backup = _backup_database(db, history, stamp)
        changed = mapping_db.replace_slots(conn, doc, stamp_dt.isoformat(timespec="microseconds"),
                                           reason=f"import:{file_sha256}")
        if raw != data:
            (history / f"{path.stem}.{stamp}.{file_sha256[:12]}.imported.json").write_bytes(raw)
        _atomic_write(path, data)
        mapping_db.mark_json_synced(conn, mapping_db.sha256(data))
        conn.execute("INSERT INTO meta (key, value) VALUES ('last_import', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (json.dumps({"at": stamp_dt.isoformat(timespec="seconds"), "file_sha256": file_sha256,
                                  "changed_slots": changed, "database_backup": backup.name}),))
        conn.commit()
    finally:
        conn.close()
    return {"imported_sha256": mapping_db.sha256(data), "changed_slots": changed, "database_backup": str(backup)}


def export_json(path, file_sha256, *, history_dir=None, now=None):
    """Explicit, owner-confirmed export: write the database's decisions over the file.
    file_sha256: hash of the file the owner saw (None when it is missing). A file that differs from the
    database is kept in .history/ first. -> new file sha256."""
    path = Path(path)
    db = mapping_db.db_path_for(path)
    on_disk = path.read_bytes() if path.exists() else None
    seen = None if on_disk is None else mapping_db.sha256(on_disk)
    if seen != file_sha256:
        raise StaleError(f"{path.name} changed since you looked at it; check again")
    conn = mapping_db.open_existing(db)
    try:
        data = mapping_db.export_bytes(conn)
        if mapping_db.sha256(data) != mapping_db.meta_get(conn, "export_sha256"):
            raise StoreError(f"{db.name}: its rows do not match the export hash it recorded; not exporting")
        if on_disk is not None and on_disk != data:
            history = Path(history_dir) if history_dir else path.parent / ".history"
            history.mkdir(parents=True, exist_ok=True)
            stamp = (now or dt.datetime.now()).strftime("%Y%m%dT%H%M%S%f")
            (history / f"{path.stem}.{stamp}.{seen[:12]}.replaced-by-export.json").write_bytes(on_disk)
        _atomic_write(path, data)
        mapping_db.mark_json_synced(conn, mapping_db.sha256(data))
    finally:
        conn.close()
    return mapping_db.sha256(data)


# --------------------------------------------------------------------------- loudness-match reset (2026-10-11)
LOUDNESS_OFF = {"mode": "off", "offset_db": 0}


def strip_loudness_match(doc):
    """Pure. -> (new_doc, changes). Every recipe whose loudness is not off (matching Spain's recording gave
    those lines their own gain on top of, and often instead of, the global export gain) gets loudness off.
    Nothing else changes. changes: [{mapping_id, slot_id, audio_status, audio_revision, previous}]."""
    new = json.loads(json.dumps(doc))
    changes = []
    for s in new.get("slots", []):
        edit = s["audio"].get("edit") or {}
        lo = edit.get("loudness")
        if lo and (lo.get("mode", "off") != "off" or lo.get("offset_db", 0)):
            changes.append({"mapping_id": s["mapping_id"], "slot_id": s["slot_id"],
                            "audio_status": s["audio"]["status"], "audio_revision": s["audio"]["revision"],
                            "previous": dict(lo)})
            edit["loudness"] = dict(LOUDNESS_OFF)
    return new, changes


def proof_only_loudness_changed(old_doc, new_doc):
    """Problems if new_doc differs from old_doc in anything but audio.edit.loudness (empty = proven)."""
    problems = []
    if {k: v for k, v in old_doc.items() if k != "slots"} != {k: v for k, v in new_doc.items() if k != "slots"}:
        problems.append("top-level fields changed")
    if [s["mapping_id"] for s in old_doc["slots"]] != [s["mapping_id"] for s in new_doc["slots"]]:
        return problems + ["mapping ids or order changed"]
    for o, n in zip(old_doc["slots"], new_doc["slots"]):
        strip = lambda s: {**s, "audio": {**s["audio"], "edit": {k: v for k, v in s["audio"]["edit"].items() if k != "loudness"}}}
        if strip(o) != strip(n):
            problems.append(f"{o['mapping_id']}: something besides audio.edit.loudness changed")
        if n["audio"]["edit"].get("loudness") not in (None, LOUDNESS_OFF):
            problems.append(f"{o['mapping_id']}: loudness is not off")
    return problems


def reset_loudness_match(path, loaded_sha256, *, history_dir=None, now=None):
    """One-time, owner-authorized (2026-10-11) reset: loudness matching off in every recipe, approved ones
    included, WITHOUT touching approvals (status, revision, approved_at, fingerprint stay; nothing becomes
    needs_rework), so every replacement follows the one global export gain. Same stale check, .history/
    backup and database-first write as every save, so the database and the JSON stay in sync. Refuses
    unless the result provably differs only in audio.edit.loudness. -> (new sha256 or None, changes)."""
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded")
    old = json.loads(current.decode("utf-8"))
    new, changes = strip_loudness_match(old)
    if not changes:
        return None, []
    bad = proof_only_loudness_changed(old, new)
    if bad:
        raise ProtectedError("; ".join(bad))
    errs = schema_errors(new, load_schema(SCHEMA_NAME), changed_mapping_ids(old, new))
    if errs:
        raise StoreError("schema: " + "; ".join(errs[:5]))
    return _write(path, current, new, loaded_sha256, history_dir, now,
                  changed_ids=changed_mapping_ids(old, new)), changes


def strip_limiter(doc):
    """Pure. -> (new_doc, changes). Removes the `limiter` setting from every recipe (loudness matching never
    limits since 2026-10-11, owner). It changes no audio: no recipe uses loudness matching, and the setting
    only applied there. Nothing else changes. changes: [{mapping_id, slot_id, audio_status, audio_revision,
    previous}]."""
    new = json.loads(json.dumps(doc))
    changes = []
    for s in new.get("slots", []):
        edit = s["audio"].get("edit") or {}
        if "limiter" in edit:
            changes.append({"mapping_id": s["mapping_id"], "slot_id": s["slot_id"],
                            "audio_status": s["audio"]["status"], "audio_revision": s["audio"]["revision"],
                            "previous": edit["limiter"]})
            del edit["limiter"]
    return new, changes


def proof_only_limiter_removed(old_doc, new_doc):
    """Problems if new_doc differs from old_doc in anything but the removal of audio.edit.limiter."""
    problems = []
    if {k: v for k, v in old_doc.items() if k != "slots"} != {k: v for k, v in new_doc.items() if k != "slots"}:
        problems.append("top-level fields changed")
    if [s["mapping_id"] for s in old_doc["slots"]] != [s["mapping_id"] for s in new_doc["slots"]]:
        return problems + ["mapping ids or order changed"]
    for o, n in zip(old_doc["slots"], new_doc["slots"]):
        strip = lambda s: {**s, "audio": {**s["audio"], "edit": {k: v for k, v in s["audio"]["edit"].items() if k != "limiter"}}}
        if strip(o) != strip(n):
            problems.append(f"{o['mapping_id']}: something besides audio.edit.limiter changed")
        if "limiter" in n["audio"]["edit"]:
            problems.append(f"{o['mapping_id']}: limiter is still there")
    return problems


def remove_limiter(path, loaded_sha256, *, history_dir=None, now=None):
    """One-time, owner-authorized (2026-10-11) removal of the `limiter` setting from every recipe, approved
    ones included, WITHOUT touching approvals (status, revision, approved_at, fingerprint stay; nothing becomes
    needs_rework). Same stale check, .history/ backup and database-first write as every save. Refuses unless
    the result provably differs only by the removed field. -> (new sha256 or None, changes)."""
    path = Path(path)
    current = _current(path)
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded")
    old = json.loads(current.decode("utf-8"))
    new, changes = strip_limiter(old)
    if not changes:
        return None, []
    bad = proof_only_limiter_removed(old, new)
    if bad:
        raise ProtectedError("; ".join(bad))
    errs = schema_errors(new, load_schema(SCHEMA_NAME), changed_mapping_ids(old, new))
    if errs:
        raise StoreError("schema: " + "; ".join(errs[:5]))
    return _write(path, current, new, loaded_sha256, history_dir, now,
                  changed_ids=changed_mapping_ids(old, new)), changes
