"""One-time, owner-requested migration (2026-10-13): turn on MCC's radio clicks for the radio lines whose Spain
original has them.

Owner feedback (2026-10-13): the radio effect was missing the key-up click and the closing click. The recipe's
`radio.clicks` (common/radio_clicks.py) adds them. This turns it on for every mapping whose recipe has a radio
filter without clicks AND whose Spain original opens with the click (radio_clicks.intro_similarity >= SIMILAR);
the others are listed and left off (their Spain originals have no click: the owner decides).

Only audio that is not approved is changed (the 2026-10-13 radio migration left these lines needs rework / draft).
An approved line is skipped and reported: changing it needs its own needs-rework decision.

    python scripts/validate/migrate_radio_clicks.py              # dry run: report only
    python scripts/validate/migrate_radio_clicks.py --write      # backup, migrate, verify
    python scripts/validate/migrate_radio_clicks.py --rollback work/migrations/<id>
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
from common import audio_edit, mapping_store, radio_clicks  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

NAME = "radio_clicks"
MAPPINGS = "mappings/manual_mappings.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def plan(doc, similarity):
    """similarity(slot_id) -> intro_similarity of the Spain original. -> (new_doc, changes, skipped). Pure."""
    new = copy.deepcopy(doc)
    changes, skipped = [], []
    for s in new["slots"]:
        radio = (s["audio"]["edit"] or {}).get("radio")
        if not radio or radio.get("clicks"):
            continue
        sim = similarity(s["slot_id"])
        row = {"mapping_id": s["mapping_id"], "slot_id": s["slot_id"], "audio": s["audio"]["status"],
               "spain_intro_similarity": sim}
        if sim < radio_clicks.SIMILAR:
            skipped.append(dict(row, reason="the Spain original has no opening click"))
        elif s["audio"]["status"] == "approved":
            skipped.append(dict(row, reason="approved: needs its own needs-rework decision"))
        else:
            s["audio"]["edit"] = audio_edit.normalize(dict(s["audio"]["edit"], radio=dict(radio, clicks=True)))
            changes.append(dict(row, edit_summary=audio_edit.summary(s["audio"]["edit"])))
    return new, changes, skipped


def similarity_from_bank(root):
    from m4_server import DEFAULT_VGMSTREAM, make_app
    app = make_app(Path(root), DEFAULT_VGMSTREAM)
    clicks = radio_clicks.load(app.mcc_audio, app.slot_index)

    def sim(slot_id):
        level, _r, sample = app.slot_index[slot_id]
        x, _sr = audio_edit.wav_mono_float(app.mcc_audio.wav(level, "spanish", sample))
        return radio_clicks.intro_similarity(x, clicks["in"])
    return sim


def migrate(root, write, now=None):
    root, now = Path(root), now or dt.datetime.now()
    path = root / MAPPINGS
    doc, loaded = mapping_store.load(path)
    new, changes, skipped = plan(doc, similarity_from_bank(root))
    mid = now.strftime("%Y%m%dT%H%M%S") + "_" + NAME
    rep = {"schema": "migration-report/1", "migration": NAME, "id": mid, "mode": "write" if write else "dry run",
           "threshold": radio_clicks.SIMILAR, "clicks_pins": radio_clicks.PINNED, "before_sha256": loaded,
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
    after_sha = mapping_store.save(path, new, loaded, now=now)  # no user actions: nothing approved is touched
    after, after_loaded = mapping_store.load(path)
    rep["after_sha256"] = after_loaded
    ids = {c["mapping_id"] for c in changes}
    rep["verification"] = {
        "written_sha_matches": after_sha == after_loaded,
        "result_equals_plan": after == new,
        "only_the_radio_clicks_changed": all(
            (a == b) if a["mapping_id"] not in ids else
            (dict(a, audio=dict(a["audio"], edit=None)) == dict(b, audio=dict(b["audio"], edit=None))
             and dict(a["audio"]["edit"], radio=dict(a["audio"]["edit"]["radio"], clicks=True)) == b["audio"]["edit"])
            for a, b in zip(doc["slots"], after["slots"])),
        "no_approved_audio_changed": all(a["audio"]["status"] != "approved" for a in doc["slots"] if a["mapping_id"] in ids),
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
         "Owner feedback (2026-10-13): the radio effect lacked MCC's opening and closing clicks. `radio.clicks` turned "
         f"on where the Spain original opens with the click (similarity >= {rep['threshold']}). Mode: **{rep['mode']}**.",
         "", f"- Changed: **{len(rep['changes'])}**; left off: {len(rep['skipped'])}.",
         f"- File before: `{rep['before_sha256']}`" + (f"; after: `{rep['after_sha256']}`" if rep.get("after_sha256") else ""),
         "", "| Mapping | Slot | Audio | Spain intro similarity |", "|---|---|---|---|"]
    L += [f"| `{c['mapping_id']}` | `{c['slot_id']}` | {c['audio']} | {c['spain_intro_similarity']} |" for c in rep["changes"]]
    if rep["skipped"]:
        L += ["", "Left without clicks:", ""] + [
            f"- `{s['slot_id']}` ({s['audio']}, similarity {s['spain_intro_similarity']}): {s['reason']}" for s in rep["skipped"]]
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
    print(f"{rep['mode']}: clicks on for {len(rep['changes'])} line(s); {len(rep['skipped'])} left off")
    for c in rep["changes"]:
        print(f"  {c['mapping_id']} {c['slot_id']} [{c['audio']}] similarity {c['spain_intro_similarity']}")
    for s in rep["skipped"]:
        print(f"  left off {s['slot_id']} [{s['audio']}] similarity {s['spain_intro_similarity']}: {s['reason']}")
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
