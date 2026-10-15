"""One-time, owner-authorized migration (2026-10-15): the owner retuned the Soldier radio preset
(audio_edit.RADIO_PRESETS["soldier"]: presence 6 -> 0 dB, drive 6 -> 1 dB, hiss -80 -> -70 dBFS) and asked every
line set to it to follow. Every recipe whose radio filter is labelled `soldier` gets the preset's current values,
approved mappings included.

Nothing else changes: approvals (status, revision, approved_at, fingerprint), selected recordings, subtitles,
trims, cuts, silences, fades, echo, flags, notes, mission progress and history. Nothing is marked needs rework.

    python scripts/validate/migrate_soldier_preset.py                 # dry run: report only
    python scripts/validate/migrate_soldier_preset.py --write         # backup, migrate, verify
    python scripts/validate/migrate_soldier_preset.py --rollback work/migrations/<id>

--write backs up manual_mappings.json, the local file and manual_mappings.db to work/migrations/<id>/backup/,
writes through mapping_store.retune_radio (stale check, proof that only those radio values change, schema,
.history/ copy, database first, then the JSON), re-reads and verifies, and writes report.json / report.md.
Running it again finds nothing and writes nothing.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import mapping_store  # noqa: E402
from common.audio_edit import RADIO_FIELDS, RADIO_PRESETS  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

NAME = "soldier_preset"
PRESET = "soldier"
VALUES = {k: RADIO_PRESETS[PRESET][k] for k in (*RADIO_FIELDS, "clicks")}
MAPPINGS = "mappings/manual_mappings.json"
LOCAL = "mappings/manual_mappings.local.json"
DB = "mappings/manual_mappings.db"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def approvals(doc):
    """What must survive unchanged: everything except the recipe."""
    return {s["mapping_id"]: {k: v for k, v in s.items() if k != "audio"} | {
        "audio": {k: v for k, v in s["audio"].items() if k != "edit"}} for s in doc["slots"]}


def run_validator(root):
    spec = importlib.util.spec_from_file_location("validate_project", Path(__file__).resolve().parent / "validate_project.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run(root, use_git=(Path(root) / ".git").exists())


def backup(root, bdir):
    bdir.mkdir(parents=True, exist_ok=False)
    files = {}
    for rel in (MAPPINGS, LOCAL):
        src = root / rel
        if src.is_file():
            dst = bdir / Path(rel).name
            shutil.copy2(src, dst)
            files[rel] = {"backup": dst.relative_to(root).as_posix(), "sha256": sha(src),
                          "verified": sha(dst) == sha(src)}
    dst = bdir / Path(DB).name
    s = sqlite3.connect(f"file:{(root / DB).as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
        ok = d.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = d.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
    finally:
        s.close()
        d.close()
    files[DB] = {"backup": dst.relative_to(root).as_posix(), "integrity_check": ok, "slots": rows, "verified": ok}
    verified = all(f["verified"] for f in files.values())
    (bdir / "backup_manifest.json").write_text(json.dumps({"files": files, "verified": verified}, indent=2) + "\n",
                                               encoding="utf-8")
    return files, verified


def report_md(rep):
    L = [f"# Migration `{rep['migration']}` ({rep['id']})", "",
         f"Owner-authorized retune of every `{PRESET}` radio filter to the preset's new values {VALUES} "
         f"(approvals kept). Mode: **{rep['mode']}**.", "",
         f"- Mappings: {rep['mappings_total']}; on the preset: **{rep['affected']}** "
         f"(by audio status: {rep['affected_by_status']}).",
         f"- File before: `{rep['before_sha256']}`" + (f"; after: `{rep['after_sha256']}`" if rep.get("after_sha256") else ""), "",
         "| Mapping | Slot | Audio | Previous radio |", "|---|---|---|---|"]
    L += [f"| `{c['mapping_id']}` | `{c['slot_id']}` | {c['audio_status']} rev {c['audio_revision']} | {c['previous']} |"
          for c in rep["changes"]]
    if rep.get("verification"):
        L += ["", "## Verification", ""] + [f"- {k}: {v}" for k, v in rep["verification"].items()]
    if rep.get("backup"):
        L += ["", f"Backup: `{rep['backup']['dir']}` (verified: {rep['backup']['verified']})."]
    return "\n".join(L) + "\n"


def migrate(root, write, now=None):
    root, now = Path(root), now or dt.datetime.now()
    path = root / MAPPINGS
    doc, loaded = mapping_store.load(path)
    _, changes = mapping_store.retune_radio_preset(doc, PRESET, VALUES)
    by_status = {}
    for c in changes:
        by_status[c["audio_status"]] = by_status.get(c["audio_status"], 0) + 1
    mid = now.strftime("%Y%m%dT%H%M%S") + "_" + NAME
    rep = {"schema": "migration-report/1", "migration": NAME, "id": mid, "mode": "write" if write else "dry run",
           "mappings_total": len(doc["slots"]), "affected": len(changes), "affected_by_status": by_status,
           "before_sha256": loaded, "changes": changes}
    if not write or not changes:
        if write:
            rep["mode"] = "write (nothing to do: already migrated)"
        return rep, None
    out = root / "work" / "migrations" / mid
    files, verified = backup(root, out / "backup")
    rep["backup"] = {"dir": out.relative_to(root).as_posix(), "files": files, "verified": verified}
    if not verified or files[MAPPINGS]["sha256"] != loaded:
        raise SystemExit(f"backup verification failed in {out}; nothing was migrated")
    before = approvals(doc)
    after_sha, applied = mapping_store.retune_radio(path, loaded, PRESET, VALUES, now=now)
    after, after_loaded = mapping_store.load(path)
    status = mapping_store.sync_status(path)
    rep["after_sha256"] = after_loaded
    rep["verification"] = {
        "written_sha_matches": after_sha == after_loaded,
        "same_changes_as_planned": applied == changes,
        "only_radio_values_changed": mapping_store.proof_only_radio_retuned(doc, after, PRESET, VALUES) == [],
        "approvals_and_everything_else_unchanged": approvals(after) == before,
        "nothing_left_to_retune": mapping_store.retune_radio_preset(after, PRESET, VALUES)[1] == [],
        "json_and_database_in_sync": status["state"] == "in_sync",
    }
    vrep, drift = run_validator(root)
    rep["verification"]["validator_errors"] = sum(1 for f in vrep["findings"] if f["severity"] == "error")
    rep["verification"]["approved_fingerprint_drift"] = len(drift["drift"])
    return rep, out


def rollback(root, mdir):
    """Put the backed-up decisions back, through the store (database first, then the JSON), only if the
    current file is still exactly what this migration wrote."""
    root, mdir = Path(root), Path(mdir)
    rep = json.loads((mdir / "report.json").read_text(encoding="utf-8"))
    path = root / MAPPINGS
    _, cur = mapping_store.load(path)
    if cur != rep["after_sha256"]:
        raise SystemExit("refusing: manual_mappings.json changed after this migration; restore by hand from the backup")
    data = (root / rep["backup"]["files"][MAPPINGS]["backup"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != rep["before_sha256"]:
        raise SystemExit("refusing: the backup no longer matches its recorded hash")
    mapping_store.restore(path, data, cur)
    ok = mapping_store.load(path)[1] == rep["before_sha256"] and mapping_store.sync_status(path)["state"] == "in_sync"
    print(f"rolled back to {rep['before_sha256'][:16]}… ({'verified, JSON and database in sync' if ok else 'CHECK'})")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--write", action="store_true", help="back up, migrate and verify (default: dry run)")
    ap.add_argument("--rollback", type=Path, help="work/migrations/<id> folder of a previous --write")
    args = ap.parse_args()
    if args.rollback:
        return 0 if rollback(args.root, args.rollback) else 1
    rep, out = migrate(args.root, args.write)
    print(f"{rep['mode']}: {rep['affected']} of {rep['mappings_total']} mapping(s) use the {PRESET} preset with old values; "
          f"by audio status {rep['affected_by_status']}")
    for c in rep["changes"]:
        print(f"  {c['mapping_id']} {c['slot_id']} [{c['audio_status']} rev {c['audio_revision']}] previous {c['previous']}")
    if out:
        (out / "report.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        (out / "report.md").write_text(report_md(rep), encoding="utf-8")
        v = rep["verification"]
        ok = all(x is True for x in v.values() if isinstance(x, bool)) and v["validator_errors"] == 0
        print("verification:", json.dumps(v))
        print(f"{'OK' if ok else 'CHECK THE REPORT'}: report and verified backup in {out.relative_to(args.root)}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
