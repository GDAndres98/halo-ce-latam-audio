"""One-time, owner-authorized migration (2026-10-13): give the pilot-style radio lines the Spain radio filter
and send their audio back to review.

Owner decisions (2026-10-13): the radio filter lives in the audio edit recipe (`audio.edit.radio`,
common/audio_edit.py); approved lines may be set to needs rework for it; scope is pilot-style radio only.
Targets: mappings flagged "Needs radio effect" (`radio_effect.needed`) whose notes are empty, with CE audio.
The 18 lines noted "eco" (cryo assistant echo) are left alone: an echo is not this filter.

For each target the recipe gains `radio = Spain preset` (docs/radio-filter.md; trims, cuts, silences and
fades are kept). Approved audio becomes needs_rework (revision + 1, approved_at and fingerprint cleared:
exactly the Studio's "Needs rework" action); draft or needs-rework audio just gets the filter. Nothing else
changes: matches, subtitles, flags, notes, other mappings. Approving again is the owner's, in the Studio.

    python scripts/validate/migrate_radio_preset.py              # dry run: report only
    python scripts/validate/migrate_radio_preset.py --write      # backup, migrate, verify
    python scripts/validate/migrate_radio_preset.py --rollback work/migrations/<id>

Running it again finds nothing to do (lines that already have a radio filter are skipped). --rollback
restores the backed-up file only if the current file is still exactly what this migration wrote.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import audio_edit, mapping_store  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.mapping_store import UserAction  # noqa: E402

NAME = "radio_preset"
PRESET = "spain"
MAPPINGS = "mappings/manual_mappings.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def targets(doc):
    out = []
    for s in doc["slots"]:
        if not s["radio_effect"]["needed"] or (s.get("notes") or "").strip():
            continue
        a = s["audio"]
        if a["source"] != "ce" or not a["sources"]:
            out.append((s, "skip: audio is not one CE recording"))
        elif a["edit"].get("radio"):
            out.append((s, "skip: already has a radio filter"))
        else:
            out.append((s, None))
    return out


def plan(doc):
    """-> (new_doc, user_actions, changes, skipped). Pure."""
    new = copy.deepcopy(doc)
    by_id = {s["mapping_id"]: s for s in new["slots"]}
    actions, changes, skipped = [], [], []
    for s, why in targets(doc):
        if why:
            skipped.append({"mapping_id": s["mapping_id"], "slot_id": s["slot_id"], "reason": why})
            continue
        n = by_id[s["mapping_id"]]
        a = n["audio"]
        src = {"ce_line_ref": a["sources"][0]["ce_line_ref"], "language": a["sources"][0]["language"]}
        edit = audio_edit.normalize(dict(a["edit"], radio={"preset": PRESET}), for_source=src)
        was = a["status"]
        if was == "approved":
            a.update(status="needs_rework", revision=a["revision"] + 1, approved_at=None, fingerprint=None)
            actions.append(UserAction("needs_rework", n["mapping_id"], "audio"))
        a["edit"] = edit
        changes.append({"mapping_id": n["mapping_id"], "slot_id": n["slot_id"], "audio_before": was,
                        "audio_after": a["status"], "revision": a["revision"], "edit_summary": audio_edit.summary(edit)})
    return new, actions, changes, skipped


def untouched(doc):
    """Everything this migration must not change."""
    return {s["mapping_id"]: {k: v for k, v in s.items() if k != "audio"} for s in doc["slots"]}


def migrate(root, write, now=None):
    root, now = Path(root), now or dt.datetime.now()
    path = root / MAPPINGS
    doc, loaded = mapping_store.load(path)
    new, actions, changes, skipped = plan(doc)
    mid = now.strftime("%Y%m%dT%H%M%S") + "_" + NAME
    rep = {"schema": "migration-report/1", "migration": NAME, "id": mid, "mode": "write" if write else "dry run",
           "preset": dict(audio_edit.RADIO_PRESETS[PRESET], preset=PRESET), "before_sha256": loaded,
           "changes": changes, "skipped": skipped}
    if not write or not changes:
        if write:
            rep["mode"] = "write (nothing to do)"
        return rep, None
    out = root / "work" / "migrations" / mid
    (out / "backup").mkdir(parents=True, exist_ok=False)
    bak = out / "backup" / Path(MAPPINGS).name
    shutil.copy2(path, bak)
    if sha(bak) != loaded:
        raise SystemExit(f"backup verification failed in {bak}; nothing was migrated")
    rep["backup"] = {"dir": out.relative_to(root).as_posix(), "file": bak.relative_to(root).as_posix(), "verified": True}
    after_sha = mapping_store.save(path, new, loaded, user_actions=actions, now=now)
    after, after_loaded = mapping_store.load(path)
    rep["after_sha256"] = after_loaded
    changed_ids = {c["mapping_id"] for c in changes}
    rep["verification"] = {
        "written_sha_matches": after_sha == after_loaded,
        "result_equals_plan": after == new,
        "only_audio_of_targets_changed": untouched(after) == untouched(doc) and all(
            a["audio"] == b["audio"] for a, b in zip(doc["slots"], after["slots"]) if a["mapping_id"] not in changed_ids),
        "every_target_has_the_filter": all(s["audio"]["edit"].get("radio", {}).get("preset") == PRESET
                                           for s in after["slots"] if s["mapping_id"] in changed_ids),
        "none_left_approved": all(s["audio"]["status"] != "approved"
                                  for s in after["slots"] if s["mapping_id"] in changed_ids),
        "idempotent_second_pass_changes_nothing": plan(after)[2] == [],
    }
    return rep, out


def rollback(root, mdir):
    root, mdir = Path(root), Path(mdir)
    rep = json.loads((mdir / "report.json").read_text(encoding="utf-8"))
    path = root / MAPPINGS
    if hashlib.sha256(path.read_bytes()).hexdigest() != rep["after_sha256"]:
        raise SystemExit("refusing: manual_mappings.json changed after this migration. Restore by hand from the "
                         "backup if you really want to.")
    data = (root / rep["backup"]["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != rep["before_sha256"]:
        raise SystemExit("refusing: the backup no longer matches its recorded hash")
    mapping_store.restore(path, data, rep["after_sha256"])
    ok = sha(path) == rep["before_sha256"]
    print(f"rolled back {MAPPINGS} to {rep['before_sha256'][:16]}… ({'verified' if ok else 'HASH MISMATCH'})")
    return ok


def report_md(rep):
    L = [f"# Migration `{rep['migration']}` ({rep['id']})", "",
         "Owner-authorized (2026-10-13): Spain radio filter on the pilot-style radio lines; approved audio set to "
         f"needs rework. Mode: **{rep['mode']}**.", "",
         f"- Preset: `{json.dumps(rep['preset'])}`",
         f"- Changed: **{len(rep['changes'])}**; skipped: {len(rep['skipped'])}.",
         f"- File before: `{rep['before_sha256']}`" + (f"; after: `{rep['after_sha256']}`" if rep.get("after_sha256") else ""),
         "", "| Mapping | Slot | Audio before → after | Recipe |", "|---|---|---|---|"]
    L += [f"| `{c['mapping_id']}` | `{c['slot_id']}` | {c['audio_before']} → {c['audio_after']} (rev {c['revision']}) | "
          f"{c['edit_summary']} |" for c in rep["changes"]]
    if rep["skipped"]:
        L += ["", "Skipped:"] + [f"- `{s['slot_id']}`: {s['reason']}" for s in rep["skipped"]]
    if rep.get("verification"):
        L += ["", "## Verification", ""] + [f"- {k}: {v}" for k, v in rep["verification"].items()]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--write", action="store_true", help="back up, migrate and verify (default: dry run)")
    ap.add_argument("--rollback", type=Path, help="work/migrations/<id> folder of a previous --write")
    args = ap.parse_args()
    if args.rollback:
        return 0 if rollback(args.root, args.rollback) else 1
    rep, out = migrate(args.root, args.write)
    print(f"{rep['mode']}: {len(rep['changes'])} line(s) get the {PRESET} radio filter; {len(rep['skipped'])} skipped")
    for c in rep["changes"]:
        print(f"  {c['mapping_id']} {c['slot_id']}: audio {c['audio_before']} -> {c['audio_after']} · {c['edit_summary']}")
    for s in rep["skipped"]:
        print(f"  skipped {s['slot_id']}: {s['reason']}")
    if out:
        (out / "report.json").write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        (out / "report.md").write_text(report_md(rep), encoding="utf-8")
        ok = all(rep["verification"].values())
        print("verification:", json.dumps(rep["verification"]))
        print(f"{'OK' if ok else 'CHECK THE REPORT'}: report and verified backup in {out.relative_to(args.root)}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
