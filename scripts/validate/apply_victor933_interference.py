"""One-off, owner-requested (2026-10-13): put the transmission interference into Victor 933's recipe.

The owner chose the 11 phrases and their kinds (docs/victor933-interference.md); the times come from
config/interference/vo_scr_m06_00740_victor933.json. Only mapping m-000482's audio.edit gains `interference`
(trims, cuts, fades and the radio filter are kept): an interference/2 curve generated from the 11 guides
(common/interference.default_points). Its audio must not be approved (needs rework since the radio migration):
an approved line is refused, never re-opened here. Nothing else changes.

--upgrade (owner prompt 45): a recipe that still holds the old interference/1 regions gets the curve instead;
the regions' labels, kinds and times become the guides (unchanged decisions). --reset-curve regenerates the
curve from the recipe's guides (the Studio's "Reset curve" does the same for the draft). --texture synthetic|mcc
sets the static's source (synthetic = made from scratch; owner request 2026-10-13), keeping the curve.

    python scripts/validate/apply_victor933_interference.py [--upgrade]              # dry run
    python scripts/validate/apply_victor933_interference.py [--upgrade] --write      # backup, apply, verify
    python scripts/validate/apply_victor933_interference.py --rollback work/migrations/<id>
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
from common import audio_edit, interference, mapping_store  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

NAME = "victor933_interference"
MAPPINGS = "mappings/manual_mappings.json"
REF = "vo_scr_m06_00740_victor933#0"
DEFAULTS = "config/interference/vo_scr_m06_00740_victor933.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def plan(doc, guides, duration_s, upgrade=False, reset_curve=False, texture=None):
    new = copy.deepcopy(doc)
    targets = [s for s in new["slots"] if s["audio"]["source"] == "ce"
               and [x["ce_line_ref"] for x in s["audio"]["sources"]] == [REF]]
    if len(targets) != 1:
        raise SystemExit(f"expected exactly one mapping with {REF} as its audio, found {len(targets)}")
    s = targets[0]
    if s["audio"]["status"] == "approved":
        raise SystemExit(f"{s['mapping_id']} audio is approved: mark it Needs rework in the Studio first")
    current = s["audio"]["edit"].get("interference")
    if texture and current and current.get("engine") == interference.ENGINE and not reset_curve:
        before = s["audio"]["edit"]
        s["audio"]["edit"] = audio_edit.normalize(dict(before, interference=dict(current, texture=texture)))
        if s["audio"]["edit"] == before:
            return new, None
        return new, {"mapping_id": s["mapping_id"], "slot_id": s["slot_id"], "audio": s["audio"]["status"],
                     "summary": audio_edit.summary(s["audio"]["edit"])}
    if current and not (upgrade and current.get("engine") != interference.ENGINE) and not reset_curve:
        return new, None
    if current and current.get("engine") != interference.ENGINE:  # the old regions: their decisions become the guides
        guides = [{k: r[k] for k in ("label", "kind", "start_s", "end_s")} for r in current["regions"]]
    elif current:  # --reset-curve: the recipe's own guides, a freshly generated curve
        guides = current["guides"]
    value = {"guides": guides, "points": interference.default_points(guides, duration_s), "flutter_db": 2.5,
             "texture": texture or (current or {}).get("texture", "synthetic")}
    before = s["audio"]["edit"]
    s["audio"]["edit"] = audio_edit.normalize(dict(before, interference=value))
    if s["audio"]["edit"] == before:
        return new, None  # already exactly this curve
    return new, {"mapping_id": s["mapping_id"], "slot_id": s["slot_id"], "audio": s["audio"]["status"],
                 "summary": audio_edit.summary(s["audio"]["edit"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--rollback", type=Path)
    ap.add_argument("--upgrade", action="store_true", help="replace old interference/1 regions by the curve")
    ap.add_argument("--reset-curve", action="store_true",
                    help="replace the stored curve by the generated default (the guides are kept); audio not approved only")
    ap.add_argument("--texture", choices=interference.TEXTURES,
                    help="set the static's source (synthetic = made from scratch, mcc = MCC Spain's sample)")
    a = ap.parse_args()
    root, path = a.root, a.root / MAPPINGS
    if a.rollback:
        rep = json.loads((a.rollback / "report.json").read_text(encoding="utf-8"))
        if sha(path) != rep["after_sha256"]:
            raise SystemExit("refusing: manual_mappings.json changed after this change")
        data = (root / rep["backup"]).read_bytes()
        mapping_store.restore(path, data, rep["after_sha256"])
        print("rolled back" if sha(path) == rep["before_sha256"] else "HASH MISMATCH after rollback")
        return 0
    guides = json.loads((root / DEFAULTS).read_text(encoding="utf-8"))["guides"]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
    from m4_server import DEFAULT_VGMSTREAM, make_app
    app = make_app(root, DEFAULT_VGMSTREAM)
    duration = app._wav_duration(app.ce_wav(REF, "Spanish(Mexico)"))
    doc, loaded = mapping_store.load(path)
    new, change = plan(doc, guides, duration, upgrade=a.upgrade, reset_curve=a.reset_curve, texture=a.texture)
    if not change:
        print("nothing to do: the recipe already holds this interference curve")
        return 0
    print(f"{'write' if a.write else 'dry run'}: {change['mapping_id']} {change['slot_id']} [{change['audio']}] -> {change['summary']}")
    if not a.write:
        return 0
    now = dt.datetime.now()
    out = root / "work" / "migrations" / (now.strftime("%Y%m%dT%H%M%S") + "_" + NAME)
    (out / "backup").mkdir(parents=True)
    bak = out / "backup" / "manual_mappings.json"
    shutil.copy2(path, bak)
    if sha(bak) != loaded:
        raise SystemExit("backup verification failed; nothing changed")
    after_sha = mapping_store.save(path, new, loaded, now=now)
    after, after_loaded = mapping_store.load(path)
    changed = [s["mapping_id"] for s, t in zip(doc["slots"], after["slots"]) if s != t]
    rep = {"migration": NAME, "before_sha256": loaded, "after_sha256": after_loaded, "backup": bak.relative_to(root).as_posix(),
           "change": change, "verification": {"written_sha_matches": after_sha == after_loaded, "result_equals_plan": after == new,
                                              "only_this_mapping_changed": changed == [change["mapping_id"]]}}
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("verification:", json.dumps(rep["verification"]), "->", out.relative_to(root))
    return 0 if all(rep["verification"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
