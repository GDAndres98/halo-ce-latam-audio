"""B2 E1-game: owner-approved install / rollback of the E1 candidate bank (one file only).

Subcommands (each refuses to run while MCC / EAC processes exist, and stops on any mismatch):
  preflight  verify Steam build, installed bank == pinned original, candidate == E1 report hash,
             candidate differs from the original only inside sample #30; snapshot SHA-256 of every
             file under halo1/sound/pc plus the SU/SP subtitle tables, and size/mtime of every
             install file; back up the installed bank to work/mcc/fsb/backup/<build>/ and verify it.
  install    copy the candidate over halo1/sound/pc/sounds_dialogs_spanish.fsb and verify its hash
             (restores the backup immediately if the placed file does not verify).
  rollback   restore the bank from the verified backup, verify the pinned hash, and re-check the
             snapshot (every other snapshotted file unchanged). The backup is kept.
  status     print the installed bank's hash and which state it matches.

Never launches MCC; touches no file other than sounds_dialogs_spanish.fsb in the install.
State/report: work/b2/e1/game/{preflight,install,rollback}.json (git-ignored).

Example:
    python scripts/discovery/b2_e1_game.py preflight
"""
import argparse
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.ce_assets import parse_steam_acf  # noqa: E402
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from common.fsb5_writer import sample_spans  # noqa: E402

BUILD = "19905945"
ORIGINAL = "ed0ff3ec240546611a62d2a23d6ce66b5cd7af17527bf1b12834a77fa91faef6"
CANDIDATE = "86f787ac184897619d471897e41650c04a4f1cb490df1b174c0f6f8793c6f55c"
TARGET_INDEX = 30
CAND = REPO_ROOT / "work" / "b2" / "e1" / "sounds_dialogs_spanish.fsb"
BACKUP = REPO_ROOT / "work" / "mcc" / "fsb" / "backup" / BUILD / "sounds_dialogs_spanish.fsb"
STATE = REPO_ROOT / "work" / "b2" / "e1" / "game"
PROC_MARKERS = ("mcc", "halo", "easyanticheat")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def stop(msg):
    raise SystemExit(f"STOP: {msg}")


def running_game_processes():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    names = {row[0] for row in csv.reader(io.StringIO(out)) if row}
    return sorted(n for n in names if any(m in n.lower() for m in PROC_MARKERS))


def paths():
    env, _ = load_env()
    root = require_path(env, "HALO_MCC_FOLDER", kind="dir")
    return root, root / "halo1" / "sound" / "pc" / "sounds_dialogs_spanish.fsb"


def require_closed():
    procs = running_game_processes()
    if procs:
        stop(f"MCC/EAC appears to be running: {procs}. Close it completely first.")


def steam_build(root):
    for acf in sorted(root.parent.parent.glob("appmanifest_*.acf")):
        kv = parse_steam_acf(acf.read_text(encoding="utf-8", errors="replace"))
        if kv.get("installdir", "").lower() == root.name.lower():
            return kv.get("buildid"), kv.get("StateFlags")
    return None, None


def snapshot(root):
    hashed = sorted((root / "halo1" / "sound" / "pc").rglob("*"))
    hashed = [p for p in hashed if p.is_file()]
    hashed += [root / "Data" / "ui" / "localization" / f"{t}_Halo1.bin" for t in ("SU", "SP")]
    snap = {"sha256": {p.relative_to(root).as_posix(): sha256_file(p) for p in hashed},
            "stat": {p.relative_to(root).as_posix(): [p.stat().st_size, p.stat().st_mtime_ns]
                     for p in root.rglob("*") if p.is_file()}}
    return snap


def write_state(name, data):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def preflight():
    require_closed()
    root, inst = paths()
    build, flags = steam_build(root)
    if build != BUILD:
        stop(f"Steam build {build} != {BUILD}")
    if flags != "4":
        stop(f"Steam StateFlags {flags} != 4 (an update may be pending)")
    inst_sha = sha256_file(inst)
    if inst_sha != ORIGINAL:
        stop(f"installed bank {inst_sha} is not the pinned original")
    if sha256_file(CAND) != CANDIDATE:
        stop("E1 candidate hash mismatch; re-run b2_e1_transplant.py")
    orig, cand = inst.read_bytes(), CAND.read_bytes()
    t0, t1 = sample_spans(orig)[TARGET_INDEX]
    if len(orig) != len(cand) or orig[:t0] != cand[:t0] or orig[t1:] != cand[t1:]:
        stop("candidate differs from the installed original outside sample #30")
    print("checks OK; snapshotting install (hashing halo1/sound/pc and SU/SP)...")
    snap = snapshot(root)
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if BACKUP.is_file():
        if sha256_file(BACKUP) != ORIGINAL:
            stop(f"existing backup {BACKUP} is not the original; not overwriting it")
        note = "existing backup verified"
    else:
        shutil.copyfile(inst, BACKUP)
        note = "backup created"
    if sha256_file(BACKUP) != ORIGINAL:
        stop("backup hash mismatch")
    write_state("preflight", {"steam_build": build, "steam_state_flags": flags, "installed_sha256": inst_sha,
                              "candidate_sha256": CANDIDATE, "target_span": [t0, t1],
                              "backup": BACKUP.relative_to(REPO_ROOT).as_posix(), "backup_sha256": ORIGINAL,
                              "backup_note": note, "snapshot": snap})
    print(f"PREFLIGHT OK: build {build}; installed = original; candidate verified, differs only in "
          f"[{t0},{t1}); {note} and verified; {len(snap['sha256'])} files hashed, {len(snap['stat'])} stat'ed")


def install():
    require_closed()
    if not (STATE / "preflight.json").is_file():
        stop("run preflight first")
    root, inst = paths()
    if sha256_file(BACKUP) != ORIGINAL:
        stop("backup is missing or not the original")
    if sha256_file(inst) != ORIGINAL:
        stop("installed bank is not the original")
    if sha256_file(CAND) != CANDIDATE:
        stop("candidate hash mismatch")
    shutil.copyfile(CAND, inst)
    placed = sha256_file(inst)
    if placed != CANDIDATE:
        shutil.copyfile(BACKUP, inst)
        stop(f"placed file {placed} did not verify; original restored "
             f"({'OK' if sha256_file(inst) == ORIGINAL else 'FAILED - use Steam Verify integrity'})")
    write_state("install", {"installed_sha256": placed, "file": inst.relative_to(root).as_posix()})
    print(f"INSTALL OK: {inst.relative_to(root).as_posix()} = candidate {placed}")


def rollback():
    require_closed()
    root, inst = paths()
    if sha256_file(BACKUP) != ORIGINAL:
        stop("backup is not the original; use Steam 'Verify integrity of game files'")
    shutil.copyfile(BACKUP, inst)
    restored = sha256_file(inst)
    if restored != ORIGINAL:
        stop(f"restored bank {restored} != original; use Steam 'Verify integrity of game files'")
    pre = json.loads((STATE / "preflight.json").read_text(encoding="utf-8"))["snapshot"]
    now = snapshot(root)
    bank = inst.relative_to(root).as_posix()
    hash_changes = sorted(k for k in pre["sha256"] if now["sha256"].get(k) != pre["sha256"][k])
    stat_added = sorted(set(now["stat"]) - set(pre["stat"]))
    stat_removed = sorted(set(pre["stat"]) - set(now["stat"]))
    stat_changed = sorted(k for k in set(pre["stat"]) & set(now["stat"]) if pre["stat"][k] != now["stat"][k]
                          and k != bank)
    result = {"restored_sha256": restored, "restored_equals_original": True,
              "hashed_files_changed": hash_changes, "files_added": stat_added, "files_removed": stat_removed,
              "other_files_size_or_mtime_changed": stat_changed, "backup_kept": BACKUP.is_file()}
    write_state("rollback", result)
    print(f"ROLLBACK OK: bank = original {restored}")
    print(f"hashed files changed vs preflight: {hash_changes or 'none'}")
    print(f"install files added/removed/changed (size or mtime, excluding the bank): "
          f"{len(stat_added)}/{len(stat_removed)}/{len(stat_changed)}")
    for k in (stat_added + stat_removed + stat_changed)[:20]:
        print("  ", k)


def status():
    root, inst = paths()
    h = sha256_file(inst)
    print(h, "= ORIGINAL" if h == ORIGINAL else "= E1 CANDIDATE" if h == CANDIDATE else "= UNKNOWN")
    print("running:", running_game_processes() or "none")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["preflight", "install", "rollback", "status"])
    a = ap.parse_args()
    {"preflight": preflight, "install": install, "rollback": rollback, "status": status}[a.action]()


if __name__ == "__main__":
    main()
