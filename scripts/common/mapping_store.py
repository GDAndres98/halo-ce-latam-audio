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
import json
import os
from collections import namedtuple
from pathlib import Path

from .jsonschema_lite import load_schema, validate

UserAction = namedtuple("UserAction", "action mapping_id field")  # action: approve | needs_rework
SCHEMA_ID = "manual-mappings/3"
SCHEMA_NAME = "manual-mappings-3"
OWNER_FLAGS = ("radio_effect", "different_but_fits")  # slot-level flags outside the approved objects


class StoreError(Exception):
    pass


class StaleError(StoreError):
    pass


class ProtectedError(StoreError):
    pass


def load(path):
    data = Path(path).read_bytes()
    return json.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()


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
    current = path.read_bytes() if path.exists() else b""
    if hashlib.sha256(current).hexdigest() != loaded_sha256:
        raise StaleError(f"{path.name} changed since it was loaded; reload and re-apply your edit")
    old_doc = json.loads(current.decode("utf-8")) if current else {"slots": []}
    if current and old_doc.get("schema") != new_doc.get("schema"):
        raise StoreError(f"schema version change {old_doc.get('schema')} -> {new_doc.get('schema')}: "
                         "use mapping_store.migrate()")
    check_transition(old_doc, new_doc, user_actions)
    errs = validate(new_doc, schema or load_schema(SCHEMA_NAME))
    if errs:
        raise StoreError("schema: " + "; ".join(errs[:5]))
    return _write(path, current, new_doc, loaded_sha256, history_dir, now)


def _write(path, current, new_doc, loaded_sha256, history_dir, now):
    """Back up the previous bytes to .history/, then write atomically. -> new sha256."""
    history = Path(history_dir) if history_dir else path.parent / ".history"
    if current:
        history.mkdir(parents=True, exist_ok=True)
        stamp = (now or dt.datetime.now()).strftime("%Y%m%dT%H%M%S%f")
        (history / f"{path.stem}.{stamp}.{loaded_sha256[:12]}.json").write_bytes(current)
    data = (json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return hashlib.sha256(data).hexdigest()


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()  # loaded hash of a file that doesn't exist yet


def save_user_file(path, new_doc, loaded_sha256, schema_name, *, history_dir=None, now=None):
    """Same stale-check, schema check, backup and atomic write for the other user-owned files
    (manual_mappings.local.json, mission_progress.json). They hold no approvals."""
    path = Path(path)
    current = path.read_bytes() if path.exists() else b""
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


def comparable(obj, field):
    """An approved object as the protection rules compare it across schema versions."""
    if field == "audio":
        return {k: v for k, v in obj.items() if k != "fx_request"}
    return obj


def migrate(path, loaded_sha256, *, history_dir=None, now=None):
    """Upgrade the file to the current schema with the usual stale check, backup and atomic write.
    Refuses if any approved object would differ (other than the dropped audio.fx_request).
    -> (new sha256 or None if already current, number of slots)."""
    path = Path(path)
    current = path.read_bytes()
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
