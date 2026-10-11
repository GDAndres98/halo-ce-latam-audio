"""M6 test builds: owner-approved install / rollback of a build's candidate files (local test only).

Driven by work/m6/<build>/build_manifest.json ("install_files": install path, pinned original
SHA-256, candidate path and SHA-256), so the same steps install an audio build (the Spanish bank), a
subtitle build (SU_Halo1.bin + SP_Halo1.bin) or both (three files, as one operation: all are installed
or none). Based on scripts/discovery/b2_bank_install.py (same process guard, Steam build check and
snapshot).

Subcommands (each refuses to run while MCC / EAC processes exist and stops on any mismatch):
  check      read-only: Steam build, every installed file == its pinned original, every candidate ==
             its manifest hash, the build's validation report is ok, and the build still matches the
             CURRENT approved decisions (refuses if a replaced line or a written subtitle was changed or
             revoked in M4; warns if newer approvals are missing). preflight runs the same checks.
  preflight  check + back up every original OUTSIDE the install (work/mcc/backup/<build>/...), verify
             each backup, snapshot SHA-256 of halo1/sound/pc + SU/SP and size/mtime of every file.
  install    copy each candidate, verify it; then re-hash the snapshot set: only the listed files may
             differ. On any failure (a hash mismatch, an error while copying, an unexpected change) every
             original is restored from its backup and verified.
  rollback   restore every original from its backup, verify, and compare against the preflight
             snapshot (no other file changed). Backups are kept.
  status     installed hash of each file: ORIGINAL / CANDIDATE / UNKNOWN.

Never launches MCC. State: work/m6/<build>/game/*.json (git-ignored). Every install, failed install and
rollback is appended to an install history (default work/m6/deploy_history.jsonl, git-ignored; never
rewritten).

--simulate-failure-after N (tests only) raises an error after N files were copied, to prove the automatic
restore. It is refused unless --mcc-root names a folder other than HALO_MCC_FOLDER.

The Studio's Build & Test page runs this script (preflight + install, rollback, status) after the owner
confirms; the safeguards are the same either way. --mcc-root / --backup-root / --state-dir point it at
another folder (the browser test's throw-away copy of the game); by default it uses HALO_MCC_FOLDER from
.env, the backups in work/mcc/backup/ and the state in work/m6/<build>/game/.

Example:
    python scripts/build/m6_install.py --build a10 check
"""
import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "discovery"))
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from b2_bank_install import running_game_processes, sha256_file, steam_build  # noqa: E402
from common import mapping_store  # noqa: E402
from common.m6_build import (  # noqa: E402
    SUBTITLE_TABLES, compare_plans, compare_subtitle_plans, plan_audio, subtitle_plan)

STEAM_BUILD = "19905945"


def stop(msg):
    raise SystemExit(f"STOP: {msg}")


class Build:
    def __init__(self, name, mcc_root=None, backup_root=None, state_dir=None, history=None):
        self.name = name
        self.fail_after = None
        self.dir = REPO_ROOT / "work" / "m6" / name
        self.manifest = json.loads((self.dir / "build_manifest.json").read_text(encoding="utf-8"))
        self.kind = self.manifest.get("kind", "audio")
        self.history = Path(history) if history else REPO_ROOT / "work" / "m6" / "deploy_history.jsonl"
        self.report = json.loads((self.dir / "validation_report.json").read_text(encoding="utf-8"))
        self.state = Path(state_dir) if state_dir else self.dir / "game"
        if mcc_root:
            self.root = Path(mcc_root)
            if not self.root.is_dir():
                stop(f"MCC folder {self.root} does not exist")
        else:
            env, _ = load_env()
            self.root = require_path(env, "HALO_MCC_FOLDER", kind="dir")
        backups = Path(backup_root) if backup_root else REPO_ROOT / "work" / "mcc" / "backup"
        self.files = []
        for f in self.manifest["install_files"]:
            self.files.append({**f, "installed": self.root / f["install_rel"],
                               "candidate_path": REPO_ROOT / f["candidate"],
                               "backup": backups / STEAM_BUILD / f["install_rel"]})

    def log_history(self, action, result, message="", **extra):
        """Append one event to the install history (JSON lines; never rewritten)."""
        files = [{"install_rel": f["install_rel"], "original_sha256": f["original_sha256"],
                  "candidate_sha256": f["candidate_sha256"],
                  "installed_sha256": sha256_file(f["installed"]) if f["installed"].is_file() else None}
                 for f in self.files]
        event = {"at": dt.datetime.now().isoformat(timespec="seconds"), "action": action, "result": result,
                 "build": self.name, "kind": self.kind, "mcc_root": str(self.root), "files": files,
                 "message": message, **extra}
        self.history.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def write_state(self, name, data):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def read_state(self, name):
        p = self.state / f"{name}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def hashed_set(self):
        files = [p for p in sorted((self.root / "halo1" / "sound" / "pc").rglob("*")) if p.is_file()]
        files += [self.root / "Data" / "ui" / "localization" / f"{t}_Halo1.bin" for t in ("SU", "SP")]
        return {p.relative_to(self.root).as_posix(): sha256_file(p) for p in files}

    def snapshot(self):
        return {"sha256": self.hashed_set(),
                "stat": {p.relative_to(self.root).as_posix(): [p.stat().st_size, p.stat().st_mtime_ns]
                         for p in self.root.rglob("*") if p.is_file()}}


def require_closed():
    procs = running_game_processes()
    if procs:
        stop(f"MCC/EAC appears to be running: {procs}. Close it completely first.")


def stale_check(b):
    """Re-plan the build's folders from the CURRENT mappings: refuse if a replaced line (or a written subtitle)
    is no longer the approved decision; warn if newer approvals are simply not in this build."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "ui"))
    from m4_app import M4App
    app = M4App(REPO_ROOT, run_validator=False)
    doc, _ = mapping_store.load(REPO_ROOT / "mappings" / "manual_mappings.json")
    lp = REPO_ROOT / "mappings" / "manual_mappings.local.json"
    local = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else None
    idx = dict(slot_index=app.slot_index, ce_lines=app.ce_lines, ce_idx=app.ce_idx, mcc_idx=app.mcc_idx)
    diff = {"changed_or_revoked": [], "newly_eligible": []}
    if b.kind in ("audio", "both"):
        cur = plan_audio(doc, b.manifest["levels"], local=local, **idx)
        diff = compare_plans(b.manifest["slots"], cur["entries"])
    if b.kind in ("subtitles", "both"):
        cur_s = subtitle_plan(doc, set(b.manifest["levels"]), local=local,
                              tables={t: app.loc.get(t) for t in SUBTITLE_TABLES}, **idx)
        sd = compare_subtitle_plans(b.manifest["subtitles"], cur_s)
        diff = {k: diff[k] + sd[k] for k in diff}
    if diff["changed_or_revoked"]:
        stop(f"{len(diff['changed_or_revoked'])} line(s) in this build are no longer the approved decision "
             f"(e.g. {diff['changed_or_revoked'][:5]}); rebuild before installing")
    if diff["newly_eligible"]:
        print(f"note: {len(diff['newly_eligible'])} newer approval(s) are not in this build "
              f"(e.g. {diff['newly_eligible'][:5]}); rebuild to include them, or test this build as is")
    return diff


def check(b, quiet=False):
    require_closed()
    if not b.report.get("ok"):
        stop("the build's validation report is not ok; rebuild")
    stale_check(b)
    build, flags = steam_build(b.root)
    if build != STEAM_BUILD:
        stop(f"Steam build {build} != {STEAM_BUILD}: the pins and the build are for another game version")
    if flags != "4":
        stop(f"Steam StateFlags {flags} != 4 (an update may be pending)")
    for f in b.files:
        if sha256_file(f["installed"]) != f["original_sha256"]:
            stop(f"installed {f['install_rel']} is not the pinned original (already modified? run status)")
        if sha256_file(f["candidate_path"]) != f["candidate_sha256"]:
            stop(f"candidate {f['candidate']} does not match the manifest; rebuild")
    if not quiet:
        print(f"CHECK OK (read-only): Steam build {build}; {len(b.files)} installed file(s) = pinned originals; "
              "candidates verified; MCC closed")
    return build, flags


def preflight(b):
    build, flags = check(b, quiet=True)
    notes = []
    for f in b.files:
        f["backup"].parent.mkdir(parents=True, exist_ok=True)
        if f["backup"].is_file():
            if sha256_file(f["backup"]) != f["original_sha256"]:
                stop(f"existing backup {f['backup']} is not the original; not overwriting it")
            notes.append(f"{f['install_rel']}: existing backup verified")
        else:
            shutil.copyfile(f["installed"], f["backup"])
            if sha256_file(f["backup"]) != f["original_sha256"]:
                f["backup"].unlink()
                stop(f"backup of {f['install_rel']} did not verify")
            notes.append(f"{f['install_rel']}: backup created and verified")
    print("backups OK; snapshotting the install (hashing halo1/sound/pc and SU/SP)...")
    snap = b.snapshot()
    b.write_state("preflight", {"steam_build": build, "files": [
        {"install_rel": f["install_rel"], "original_sha256": f["original_sha256"],
         "candidate_sha256": f["candidate_sha256"], "backup": f["backup"].as_posix()}
        for f in b.files], "notes": notes, "snapshot": snap})
    print("PREFLIGHT OK:", "; ".join(notes), f"; {len(snap['sha256'])} files hashed, {len(snap['stat'])} stat'ed")


def restore_all(b):
    bad = []
    for f in b.files:
        shutil.copyfile(f["backup"], f["installed"])
        if sha256_file(f["installed"]) != f["original_sha256"]:
            bad.append(f["install_rel"])
    return bad


def install(b):
    require_closed()
    stale_check(b)
    pre = b.read_state("preflight")
    if not pre:
        stop("run preflight first")
    for f in b.files:
        if sha256_file(f["backup"]) != f["original_sha256"]:
            stop(f"backup of {f['install_rel']} is missing or not the original")
        if sha256_file(f["installed"]) != f["original_sha256"]:
            stop(f"installed {f['install_rel']} is not the original")
        if sha256_file(f["candidate_path"]) != f["candidate_sha256"]:
            stop(f"candidate {f['candidate']} hash mismatch")
    placed = {}

    def fail(msg):
        """Restore every original (all of the build's files, copied or not), verify, record, stop."""
        bad = restore_all(b)
        state = ("originals restored and verified" if not bad
                 else f"RESTORE FAILED for {bad}: use Steam 'Verify integrity of game files'")
        b.log_history("install", "failed", f"{msg}; {state}", rolled_back=not bad)
        stop(f"{msg}; {state}")

    try:
        for n, f in enumerate(b.files):
            if b.fail_after is not None and n >= b.fail_after:
                raise OSError(f"simulated failure before copying {f['install_rel']} "
                              f"(--simulate-failure-after {b.fail_after}, test only)")
            shutil.copyfile(f["candidate_path"], f["installed"])
            placed[f["install_rel"]] = sha256_file(f["installed"])
            if placed[f["install_rel"]] != f["candidate_sha256"]:
                fail(f"{f['install_rel']} did not verify after copying")
    except OSError as e:
        fail(f"install interrupted: {e}")
    now = b.hashed_set()
    expected = {f["install_rel"] for f in b.files}
    changed = sorted(k for k, v in pre["snapshot"]["sha256"].items() if now.get(k) != v)
    if set(changed) != expected:
        fail(f"unexpected changes after install: {changed}")
    b.write_state("install", {"placed": placed, "changed_vs_preflight": changed})
    b.log_history("install", "ok", f"{len(placed)} file(s) installed")
    print(f"INSTALL OK: {', '.join(f'{k} = candidate {v[:16]}…' for k, v in placed.items())}; "
          "no other hashed file changed")


def rollback(b):
    require_closed()
    pre = b.read_state("preflight")
    for f in b.files:
        if sha256_file(f["backup"]) != f["original_sha256"]:
            b.log_history("rollback", "failed", f"backup of {f['install_rel']} is not the original")
            stop(f"backup of {f['install_rel']} is not the original; use Steam 'Verify integrity of game files'")
    bad = restore_all(b)
    if bad:
        b.log_history("rollback", "failed", f"restore did not verify for {bad}")
        stop(f"restore did not verify for {bad}; use Steam 'Verify integrity of game files'")
    result = {"restored": [f["install_rel"] for f in b.files], "backups_kept": True}
    if pre:
        now = b.snapshot()
        mine = {f["install_rel"] for f in b.files}
        result.update(
            hashed_files_changed=sorted(k for k, v in pre["snapshot"]["sha256"].items() if now["sha256"].get(k) != v),
            files_added=sorted(set(now["stat"]) - set(pre["snapshot"]["stat"])),
            files_removed=sorted(set(pre["snapshot"]["stat"]) - set(now["stat"])),
            other_files_size_or_mtime_changed=sorted(
                k for k in set(now["stat"]) & set(pre["snapshot"]["stat"])
                if now["stat"][k] != pre["snapshot"]["stat"][k] and k not in mine))
    b.write_state("rollback", result)
    b.log_history("rollback", "ok", f"{len(b.files)} file(s) restored",
                  hashed_files_changed=result.get("hashed_files_changed"))
    print(f"ROLLBACK OK: {len(b.files)} file(s) = pinned originals")
    if pre:
        print(f"hashed files changed vs preflight: {result['hashed_files_changed'] or 'none'}")
        print(f"files added/removed/changed (size or mtime, excluding restored files): "
              f"{len(result['files_added'])}/{len(result['files_removed'])}/"
              f"{len(result['other_files_size_or_mtime_changed'])}")
        for k in (result["files_added"] + result["files_removed"] + result["other_files_size_or_mtime_changed"])[:20]:
            print("  ", k)


def status(b):
    for f in b.files:
        h = sha256_file(f["installed"])
        state = "ORIGINAL" if h == f["original_sha256"] else "CANDIDATE" if h == f["candidate_sha256"] else "UNKNOWN"
        print(f"{f['install_rel']}: {h[:16]}… = {state}")
    print("running:", running_game_processes() or "none")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", required=True, help="build folder under work/m6/ (e.g. a10)")
    ap.add_argument("action", choices=["check", "preflight", "install", "rollback", "status"])
    ap.add_argument("--mcc-root", type=Path, help="MCC install folder (default: HALO_MCC_FOLDER in .env)")
    ap.add_argument("--backup-root", type=Path, help="where originals are backed up (default work/mcc/backup)")
    ap.add_argument("--state-dir", type=Path, help="preflight/install state (default work/m6/<build>/game)")
    ap.add_argument("--history", type=Path, help="install history, JSON lines (default work/m6/deploy_history.jsonl)")
    ap.add_argument("--simulate-failure-after", type=int, metavar="N",
                    help="TESTS ONLY: fail after copying N file(s); needs --mcc-root other than HALO_MCC_FOLDER")
    a = ap.parse_args()
    if a.simulate_failure_after is not None:
        env, _ = load_env()
        real = env.get("HALO_MCC_FOLDER")
        if not a.mcc_root or (real and Path(real).resolve() == Path(a.mcc_root).resolve()):
            stop("--simulate-failure-after is only for a throw-away game folder given with --mcc-root")
    b = Build(a.build, a.mcc_root, a.backup_root, a.state_dir, a.history)
    b.fail_after = a.simulate_failure_after
    {"check": check, "preflight": preflight, "install": install, "rollback": rollback, "status": status}[a.action](b)


if __name__ == "__main__":
    main()
