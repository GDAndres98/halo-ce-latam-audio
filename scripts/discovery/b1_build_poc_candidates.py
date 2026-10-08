"""B1 PoC step 2: build one-entry SU/SP candidates OFFLINE (docs/subtitle-research.md B.12).

Inputs (read-only): the hash-verified copies work/mcc/loc/copies/{SU,SP}_Halo1.bin. The installed
tables are only hashed, never written.

Outputs (all git-ignored):
    work/mcc/loc/poc/SU_Halo1.bin   entry for 0x26FA1B53 -> "[B1-SU] a10_350" padded with '.'
    work/mcc/loc/poc/SP_Halo1.bin   entry for 0x26FA1B53 -> "[B1-SP] a10_350" padded with '.'
    work/mcc/reports/b1_poc_candidates.json   hashes, spans, per-table checks (no game text)
    work/mcc/reports/b1_poc_install_rollback.md   step 3 procedure with this machine's paths

Same-byte-length replacement only: file size and header fields are unchanged. Each table is
processed independently (key looked up in that table). The build runs twice in memory and must
give identical bytes. Never installs anything, never launches the game.

Example:
    python scripts/discovery/b1_build_poc_candidates.py
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.ce_assets import parse_steam_acf  # noqa: E402
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from common.mcc_loc import loc_key  # noqa: E402
from common.mcc_loc_patch import marker_bytes, patch_entry_same_length, raw_entries, verify_patch  # noqa: E402

TAG = "sound\\dialog\\a10\\a10_350_captkeyes"
KEY = 0x26FA1B53
EXPECTED_BUILD = "19905945"
TABLES = {  # table -> (marker, pinned sha256 of the verified copy)
    "SU_Halo1": ("[B1-SU] a10_350", "247d25298af3d5f990cd20ff5177e05078173347b7bdf395c3995a59c60244d0"),
    "SP_Halo1": ("[B1-SP] a10_350", "794deac326d401a1fb6f5de50f8979f921159a412b095a368ef5424ed4342dda"),
}
COPIES = REPO_ROOT / "work" / "mcc" / "loc" / "copies"
POC = REPO_ROOT / "work" / "mcc" / "loc" / "poc"
BACKUP = REPO_ROOT / "work" / "mcc" / "loc" / "backup" / EXPECTED_BUILD
REPORTS = REPO_ROOT / "work" / "mcc" / "reports"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def steam_buildid(mcc_root):
    for acf in sorted(mcc_root.parent.parent.glob("appmanifest_*.acf")):
        kv = parse_steam_acf(acf.read_text(encoding="utf-8", errors="replace"))
        if kv.get("installdir", "").lower() == mcc_root.name.lower():
            return kv.get("buildid")
    return None


def build_candidate(original, marker):
    t, spans = raw_entries(original)
    i = [n for n, k in enumerate(t["keys"]) if k == KEY]
    if len(i) != 1:
        raise SystemExit(f"key 0x{KEY:08X} found {len(i)} times")
    s, e = spans[i[0]]
    new = marker_bytes(marker, e - s)
    patched, _ = patch_entry_same_length(original, KEY, new)
    return patched, new


def instructions(rows, loc_dir):
    lines = [
        "# B1 PoC step 3: install and rollback (LOCAL ONLY; NOT APPROVED YET)", "",
        "Do **not** run any of this until the owner explicitly approves step 3a or 3b.",
        "Run one sub-step at a time; never have both tables replaced during 3a/3b.", "",
        "Common rules: MCC fully closed during every copy. Launch MCC yourself with",
        "**anti-cheat disabled**. Settings: primary Spanish (Latin America), fallback Spanish (Spain),",
        "subtitles on. Play `a10` to Captain Keyes' line `a10_350` in Classic and Anniversary graphics.",
        "Steam \"Verify integrity of game files\" is the second safety net.", "",
        "PowerShell, from the repo root:", "",
    ]
    for step, name, expect in (("3a", "SU_Halo1", "`[B1-SU] a10_350....` (primary LATAM path reads SU)"),
                               ("3b", "SP_Halo1", "original LATAM text under primary LATAM (no marker); "
                                                  "`[B1-SP] a10_350....` only if you also try primary Spain")):
        r = rows[name]
        inst = loc_dir / f"{name}.bin"
        bak = BACKUP / f"{name}.bin"
        cand = POC / f"{name}.bin"
        lines += [
            f"## Step {step}: `{name}` only", "",
            f"Expected on screen: {expect}.", "",
            "```powershell",
            f"$inst = '{inst}'",
            f"$bak  = '{bak}'",
            f"$cand = '{cand}'",
            f"$orig = '{r['original_sha256'].upper()}'",
            f"$new  = '{r['candidate_sha256'].upper()}'",
            "# 1. pre-check: installed file must still be the original",
            "if ((Get-FileHash $inst -Algorithm SHA256).Hash -ne $orig) { throw 'installed file is not the original; STOP' }",
            "# 2. back up and verify the backup",
            "New-Item -ItemType Directory -Force (Split-Path $bak) | Out-Null",
            "Copy-Item $inst $bak",
            "if ((Get-FileHash $bak -Algorithm SHA256).Hash -ne $orig) { throw 'backup hash mismatch; STOP' }",
            "# 3. place the candidate and verify",
            "if ((Get-FileHash $cand -Algorithm SHA256).Hash -ne $new) { throw 'candidate hash mismatch; STOP' }",
            "Copy-Item $cand $inst -Force",
            "if ((Get-FileHash $inst -Algorithm SHA256).Hash -ne $new) { throw 'placed file hash mismatch; RESTORE NOW' }",
            "```", "",
            "Then launch MCC (anti-cheat disabled), observe, and close MCC completely.", "",
            "**Rollback (always, even if the test failed or MCC hung):**", "",
            "```powershell",
            "Copy-Item $bak $inst -Force",
            "if ((Get-FileHash $inst -Algorithm SHA256).Hash -ne $orig) { throw 'RESTORE FAILED: use Steam Verify integrity' }",
            "'restored OK'",
            "```", "",
        ]
    lines += [
        "## If anything goes wrong", "",
        "- MCC hangs or shows an anti-cheat message: close it, run the rollback, then report.",
        "- Rollback hash mismatch: Steam > MCC > Properties > Installed Files > Verify integrity of game files.",
        "- Report per mode: marker shown or not, audio language, any hang or error.", "",
    ]
    return "\n".join(lines)


def main():
    env, _ = load_env()
    mcc_root = require_path(env, "HALO_MCC_FOLDER", kind="dir")
    loc_dir = mcc_root / "Data" / "ui" / "localization"
    if loc_key(TAG) != KEY:
        raise SystemExit("key rule mismatch for the target tag")
    build = steam_buildid(mcc_root)
    if build != EXPECTED_BUILD:
        raise SystemExit(f"Steam build {build} != {EXPECTED_BUILD}; re-run step 0 first")

    rows, problems = {}, []
    POC.mkdir(parents=True, exist_ok=True)
    for name, (marker, pin) in TABLES.items():
        original = (COPIES / f"{name}.bin").read_bytes()
        if sha256(original) != pin:
            raise SystemExit(f"{name} copy does not match its pin; refusing to use it")
        inst = loc_dir / f"{name}.bin"
        inst_hash = sha256(inst.read_bytes())  # read-only
        if inst_hash != pin:
            problems.append(f"{name}: installed file differs from the pinned original")
        patched, expected = build_candidate(original, marker)
        again, _ = build_candidate(original, marker)
        checks, info = verify_patch(original, patched, KEY, expected)
        checks["deterministic"] = patched == again
        checks["installed_equals_original"] = inst_hash == pin
        failed = [k for k, v in checks.items() if not v]
        if failed:
            problems.append(f"{name}: failed checks {failed}")
        else:
            (POC / f"{name}.bin").write_bytes(patched)
        rows[name] = {
            "source_copy": f"work/mcc/loc/copies/{name}.bin", "original_sha256": pin, "installed_sha256": inst_hash,
            "candidate": f"work/mcc/loc/poc/{name}.bin" if not failed else None,
            "candidate_sha256": sha256(patched), "size": len(patched),
            "marker": marker, "replacement": expected.decode("ascii"), **info,
            "key_count": raw_entries(patched)[0]["key_count"], "checks": checks,
        }

    report = {
        "schema": "b1-poc-candidates/1", "step": "B.12 step 2", "tag": TAG, "key": f"0x{KEY:08X}",
        "steam_buildid": build, "method": "same-byte-length replacement of one entry; ASCII marker padded with '.'",
        "tables": rows, "problems": problems, "ok": not problems,
        "note": "offline only; installed files were hashed, never written; no game text in this report",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "b1_poc_candidates.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "b1_poc_install_rollback.md").write_text(instructions(rows, loc_dir) + "\n", encoding="utf-8")

    for name, r in rows.items():
        print(f"{name}: entry #{r['entry_index']} @0x{r['entry_offset']:X} ({r['entry_bytes']} B), "
              f"{r['differing_bytes']} bytes differ; original {r['original_sha256'][:12]}... "
              f"-> candidate {r['candidate_sha256'][:12]}...; checks {sum(r['checks'].values())}/{len(r['checks'])}")
    print(json.dumps({"problems": problems, "ok": not problems}))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
