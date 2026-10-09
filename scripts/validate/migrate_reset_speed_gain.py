"""One-time, owner-authorized migration (2026-10-09): remove the audio editor's `speed` and manual
`gain_db` from every mapping's audio.edit recipe, approved mappings included.

The owner removed both features (speed sounded unnatural; volume is now one global export gain,
config/audio_export.json) and explicitly authorized resetting these two parameters only. Nothing
else changes: approvals (status, revision, approved_at, fingerprint), selected CE recordings,
subtitles, trims, cuts, silences, fades, loudness settings, radio / "fits" flags, notes, mission
progress and verifications. Nothing is marked needs rework.

    python scripts/validate/migrate_reset_speed_gain.py                 # dry run: report only
    python scripts/validate/migrate_reset_speed_gain.py --write         # backup, migrate, verify
    python scripts/validate/migrate_reset_speed_gain.py --rollback work/migrations/<id>

--write:
  1. reads the mappings through mapping_store.load (hash noted);
  2. lists every mapping whose recipe holds speed and/or gain_db (with its previous values);
  3. copies manual_mappings.json and the local file (custom subtitles, user recordings; it holds no
     recipes) to work/migrations/<id>/backup/ and verifies the copies by hash;
  4. writes through mapping_store.reset_removed_edit_fields (stale check, proof that only those fields
     differ, schema, .history/ backup, atomic write);
  5. re-reads and verifies: the proof again, a second pass changes nothing (idempotent), approvals and
     fingerprints unchanged, the project validator;
  6. writes report.json / report.md next to the backup.
Running it again finds nothing and writes nothing. --rollback restores the backed-up file, only if
the current file is still exactly what this migration wrote (the restored file holds speed/gain_db
again, which the current code reports as removed fields: roll back only together with the code).
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import mapping_store  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

NAME = "reset_speed_gain"
MAPPINGS = "mappings/manual_mappings.json"
LOCAL = "mappings/manual_mappings.local.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def approvals(doc):
    """What must survive: every decision's approval state, the radio / fits flags, subtitles."""
    return {s["mapping_id"]: {"slot_id": s["slot_id"], "match": s["match"], "subtitle": s["subtitle"],
                              "radio_effect": s["radio_effect"], "different_but_fits": s.get("different_but_fits"),
                              "notes": s["notes"],
                              "audio": {k: v for k, v in s["audio"].items() if k != "edit"}}
            for s in doc["slots"]}


def run_validator(root):
    spec = importlib.util.spec_from_file_location("validate_project", Path(__file__).resolve().parent / "validate_project.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report, drift = mod.run(root, use_git=(Path(root) / ".git").exists())
    return report, drift


def report_md(rep):
    L = [f"# Migration `{rep['migration']}` ({rep['id']})", "",
         f"Owner-authorized one-time reset of the audio editor's `speed` and manual `gain_db` "
         f"(removed 2026-10-09). Mode: **{rep['mode']}**.", "",
         f"- Mappings: {rep['mappings_total']}; with a recipe holding speed and/or gain_db: **{rep['affected']}** "
         f"(approved {rep['affected_by_status'].get('approved', 0)}, draft {rep['affected_by_status'].get('draft', 0)}, "
         f"needs rework {rep['affected_by_status'].get('needs_rework', 0)}).",
         f"- With a non-default value (speed ≠ 1 or gain ≠ 0): **{rep['non_default']}**.",
         f"- Local file: {rep['local_file']}.",
         f"- File before: `{rep['before_sha256']}`" + (f"; after: `{rep['after_sha256']}`" if rep.get("after_sha256") else ""), ""]
    L += ["| Mapping | Slot | Audio | Previous speed | Previous gain dB |", "|---|---|---|---|---|"]
    for c in rep["changes"]:
        L.append(f"| `{c['mapping_id']}` | `{c['slot_id']}` | {c['audio_status']} rev {c['audio_revision']} | "
                 f"{c['previous'].get('speed', '—')} | {c['previous'].get('gain_db', '—')} |")
    if rep.get("verification"):
        L += ["", "## Verification", ""] + [f"- {k}: {v}" for k, v in rep["verification"].items()]
    if rep.get("backup"):
        L += ["", f"Backup: `{rep['backup']['dir']}` (verified: {rep['backup']['verified']})."]
    return "\n".join(L) + "\n"


def migrate(root, write, now=None):
    root = Path(root)
    now = now or dt.datetime.now()
    path = root / MAPPINGS
    doc, loaded = mapping_store.load(path)
    if doc.get("schema") != mapping_store.SCHEMA_ID:
        raise SystemExit(f"{MAPPINGS} is {doc.get('schema')}; run migrate_mappings.py first")
    new, changes = mapping_store.strip_removed_edit_fields(doc)
    local_p = root / LOCAL
    local_info = "absent"
    if local_p.is_file():
        local = json.loads(local_p.read_text(encoding="utf-8"))
        local_info = (f"{len(local.get('custom_subtitles', {}))} custom subtitle(s), "
                      f"{len(local.get('user_recordings', {}))} user recording(s), no editing recipes "
                      "(recipes live only in manual_mappings.json audio.edit); unchanged")
    by_status = {}
    for c in changes:
        by_status[c["audio_status"]] = by_status.get(c["audio_status"], 0) + 1
    mid = now.strftime("%Y%m%dT%H%M%S") + "_" + NAME
    rep = {"schema": "migration-report/1", "migration": NAME, "id": mid, "mode": "write" if write else "dry run",
           "mappings_total": len(doc["slots"]), "affected": len(changes), "affected_by_status": by_status,
           "non_default": sum(1 for c in changes if c["non_default"]), "local_file": local_info,
           "before_sha256": loaded, "changes": changes}
    if not write or not changes:
        if write:
            rep["mode"] = "write (nothing to do: already migrated)"
        return rep, None
    out = root / "work" / "migrations" / mid
    bdir = out / "backup"
    bdir.mkdir(parents=True, exist_ok=False)
    files = {}
    for rel in (MAPPINGS, LOCAL):
        src = root / rel
        if src.is_file():
            dst = bdir / Path(rel).name
            shutil.copy2(src, dst)
            files[rel] = {"backup": dst.relative_to(root).as_posix(), "sha256": sha(src)}
    verified = all(sha(root / f["backup"]) == f["sha256"] for f in files.values()) and \
        files[MAPPINGS]["sha256"] == loaded
    (bdir / "backup_manifest.json").write_text(json.dumps({"files": files, "verified": verified}, indent=2) + "\n",
                                               encoding="utf-8")
    if not verified:
        raise SystemExit(f"backup verification failed in {bdir}; nothing was migrated")
    rep["backup"] = {"dir": out.relative_to(root).as_posix(), "files": files, "verified": verified}
    before_approvals = approvals(doc)
    after_sha, applied = mapping_store.reset_removed_edit_fields(path, loaded, now=now)
    after, after_loaded = mapping_store.load(path)
    rep["after_sha256"] = after_loaded
    rep["verification"] = {
        "written_sha_matches": after_sha == after_loaded,
        "same_changes_as_planned": applied == changes,
        "only_speed_gain_removed": mapping_store.proof_only_removed_fields(doc, after) == [],
        "approvals_flags_subtitles_unchanged": approvals(after) == before_approvals,
        "no_speed_or_gain_left": all(not any(k in s["audio"]["edit"] for k in mapping_store.REMOVED_EDIT_FIELDS)
                                     for s in after["slots"]),
        "idempotent_second_pass_changes_nothing": mapping_store.strip_removed_edit_fields(after)[1] == [],
        "local_file_unchanged": (not local_p.is_file()) or sha(local_p) == files[LOCAL]["sha256"],
    }
    vrep, drift = run_validator(root)
    errors = [f for f in vrep["findings"] if f["severity"] == "error"]
    rep["verification"]["validator_errors"] = len(errors)
    rep["verification"]["approved_fingerprint_drift"] = len(drift["drift"])
    rep["validator_error_samples"] = errors[:10]
    return rep, out


def rollback(root, mdir):
    root, mdir = Path(root), Path(mdir)
    rep = json.loads((mdir / "report.json").read_text(encoding="utf-8"))
    path = root / MAPPINGS
    cur = path.read_bytes()
    if hashlib.sha256(cur).hexdigest() != rep["after_sha256"]:
        raise SystemExit("refusing: manual_mappings.json changed after this migration (current file is not the "
                         "migrated one). Restore by hand from the backup if you really want to.")
    b = root / rep["backup"]["files"][MAPPINGS]["backup"]
    data = b.read_bytes()
    if hashlib.sha256(data).hexdigest() != rep["before_sha256"]:
        raise SystemExit("refusing: the backup no longer matches its recorded hash")
    mapping_store.restore(path, data, rep["after_sha256"])
    ok = sha(path) == rep["before_sha256"]
    print(f"rolled back {MAPPINGS} to {rep['before_sha256'][:16]}… ({'verified' if ok else 'HASH MISMATCH'}); "
          f"the migrated version is in mappings/.history/")
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
    print(f"{rep['mode']}: {rep['affected']} of {rep['mappings_total']} mapping(s) hold speed/gain_db "
          f"({rep['non_default']} with a non-default value); by audio status {rep['affected_by_status']}")
    for c in rep["changes"]:
        print(f"  {c['mapping_id']} {c['slot_id']} [{c['audio_status']} rev {c['audio_revision']}] previous {c['previous']}")
    if out:
        (out / "report.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        (out / "report.md").write_text(report_md(rep), encoding="utf-8")
        v = rep["verification"]
        ok = all(x is True for k, x in v.items() if isinstance(x, bool)) and v["validator_errors"] == 0
        print("verification:", json.dumps(v))
        print(f"{'OK' if ok else 'CHECK THE REPORT'}: report and verified backup in {out.relative_to(args.root)}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
