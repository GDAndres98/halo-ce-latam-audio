"""B2 experiment E1 (OFFLINE): same-length English -> Spanish transplant of one sample.

docs/b2-audio-research.md §5.2. Replaces only the CELT stream of Spanish sample #30
(`A10_350_captkeyes`, slot es:A10_350_captkeyes#0) with the MCC English recording of the same
line (`A10_350_CaptKeyes`, English #30). Same sample count, channels, LOOP and stream length,
so no offset, size field, sample header or name changes. MCC retail content only.

Inputs (read-only): pinned copies in reference-audio/stage1/ (verified against
work/mcc/build.json). The installed Spanish bank is only hashed (for the install sheet).

Outputs (git-ignored, work/b2/e1/):
    sounds_dialogs_spanish.fsb      candidate bank (309 MB)
    vgm/*.wav                       vgmstream decodes used for the checks
    e1_report.json, e1_summary.md   hashes and every check
    e1_install_rollback.md          OWNER-RUN procedure for E1-game (NOT approved yet)

Never installs, never launches the game, never touches subtitles or mappings.

Example:
    python scripts/discovery/b2_e1_transplant.py
"""
import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from common.fsb5_lib import FsbBank  # noqa: E402
from common.fsb5_writer import (build, decompose, diff_ranges, replace_stream,  # noqa: E402
                                same_length_compatibility, sample_spans)

TARGET_INDEX = 30
TARGET_SLOT = "es:A10_350_captkeyes#0"
TARGET_TAG = "sound\\dialog\\a10\\a10_350_captkeyes"
STEAM_BUILD = "19905945"
REF = REPO_ROOT / "reference-audio" / "stage1"
OUT = REPO_ROOT / "work" / "b2" / "e1"
BACKUP = REPO_ROOT / "work" / "mcc" / "fsb" / "backup" / STEAM_BUILD
DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")
# 0-based: target, its neighbours, and the E0 representative picks (mono first/last, longest, stereo)
NEIGHBOURS = [28, 29, 31, 32]
REPRESENTATIVE = [0, 1, 572, 4159, 5599, 5695]


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def decode(exe, path, subsong, wav):
    res = subprocess.run([str(exe), "-s", str(subsong), "-o", str(wav), str(path)], capture_output=True, text=True)
    return sha256(wav.read_bytes()) if res.returncode == 0 and wav.is_file() else None


def decode_hash(exe, path, subsong):
    """SHA-256 of vgmstream's decoded WAV on stdout (-p); nothing is written to disk."""
    res = subprocess.run([str(exe), "-p", "-s", str(subsong), str(path)], capture_output=True)
    return sha256(res.stdout) if res.returncode == 0 and len(res.stdout) > 44 else None


def decode_all(exe, path, count, workers=8):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda k: decode_hash(exe, path, k), range(1, count + 1)))


def meta(exe, path, subsong):
    res = subprocess.run([str(exe), "-m", "-s", str(subsong), str(path)], capture_output=True, text=True)
    return [ln for ln in res.stdout.splitlines() if str(path) not in ln and "metadata for" not in ln.lower()]


def install_sheet(inst, cand, orig_sha, cand_sha):
    bak = BACKUP / inst.name
    return "\n".join([
        "# B2 E1-game: install and rollback (LOCAL ONLY; NOT APPROVED YET)", "",
        "Do **not** run any of this until the owner explicitly approves **E1-game**.", "",
        "- Candidate: English `A10_350_CaptKeyes` audio in Spanish slot #30 (`a10_350_captkeyes`).",
        "- MCC fully closed during every copy. Launch MCC yourself with **anti-cheat disabled**.",
        "- Settings: primary Spanish (Latin America), fallback Spanish (Spain), subtitles on.",
        "- The file is ~309 MB; the backup needs the same free space.",
        "- Steam \"Verify integrity of game files\" is the second safety net.", "",
        "## Install (PowerShell, from the repo root)", "",
        "```powershell",
        f"$inst = '{inst}'",
        f"$bak  = '{bak}'",
        f"$cand = '{cand}'",
        f"$orig = '{orig_sha.upper()}'",
        f"$new  = '{cand_sha.upper()}'",
        "# 1. pre-check: the installed bank must still be the original",
        "if ((Get-FileHash $inst -Algorithm SHA256).Hash -ne $orig) { throw 'installed bank is not the original; STOP' }",
        "# 2. back up and verify the backup",
        "New-Item -ItemType Directory -Force (Split-Path $bak) | Out-Null",
        "Copy-Item $inst $bak",
        "if ((Get-FileHash $bak -Algorithm SHA256).Hash -ne $orig) { throw 'backup hash mismatch; STOP' }",
        "# 3. verify the candidate, place it, verify the placed file",
        "if ((Get-FileHash $cand -Algorithm SHA256).Hash -ne $new) { throw 'candidate hash mismatch; STOP' }",
        "Copy-Item $cand $inst -Force",
        "if ((Get-FileHash $inst -Algorithm SHA256).Hash -ne $new) { throw 'placed file hash mismatch; RESTORE NOW' }",
        "'placed OK'",
        "```", "",
        "## Test", "",
        "Play `a10` from the start through the cryo sequence to Captain Keyes' line `a10_350`,",
        "once in **Classic** and once in **Anniversary** graphics. Note for each mode:",
        "- Keyes' voice at `a10_350`: English / Spain Spanish / silent / other;",
        "- the cryo lines and the lines right before and after: Spain Spanish?",
        "- whether the line plays to the end; any hang, crash or anti-cheat message.", "",
        "Expected: **English** Keyes at `a10_350` only; everything else Spain Spanish; subtitles unchanged.", "",
        "## Rollback (always, even after a hang or failure; MCC closed)", "",
        "```powershell",
        "Copy-Item $bak $inst -Force",
        "if ((Get-FileHash $inst -Algorithm SHA256).Hash -ne $orig) { throw 'RESTORE FAILED: use Steam Verify integrity' }",
        "'restored OK'",
        "```", "",
        "If MCC hangs or shows an anti-cheat message: close it, roll back, then report.", "",
    ])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    args = ap.parse_args()
    exe = args.vgmstream_cli
    if not exe.is_file():
        raise SystemExit(f"vgmstream-cli not found: {exe}")
    env, _ = load_env()
    inst = require_path(env, "HALO_MCC_FOLDER", kind="dir") / "halo1" / "sound" / "pc" / "sounds_dialogs_spanish.fsb"
    pins = {k: v["sha256"] for k, v in json.loads((REPO_ROOT / "work" / "mcc" / "build.json")
                                                  .read_text(encoding="utf-8"))["files"].items()}

    es_path, en_path = REF / "fsb" / "sounds_dialogs_spanish.fsb", REF / "fsb" / "sounds_dialogs.fsb"
    lst_path = REF / "lst" / "sounds_dialogs_spanish.lst.bin"
    es, en = es_path.read_bytes(), en_path.read_bytes()
    hashes = {"spanish.fsb": sha256(es), "english.fsb": sha256(en), "spanish.lst": sha256(lst_path.read_bytes())}
    for k, v in hashes.items():
        if v != pins[k]:
            raise SystemExit(f"{k}: copy sha256 {v} != pinned {pins[k]}; refusing to use it")
    install_sha = sha256(inst.read_bytes()) if inst.is_file() else None  # read-only

    m_es, m_en = decompose(es), decompose(en)
    names_es = [n.decode("utf-8") for n in m_es["names"]]
    names_en = [n.decode("utf-8") for n in m_en["names"]]
    target_es, target_en = names_es[TARGET_INDEX], names_en[TARGET_INDEX]
    identity = {
        "es_name_is_target": target_es == "A10_350_captkeyes",
        "es_name_occurrence_0": names_es.index(target_es) == TARGET_INDEX,
        "en_name_matches_case_insensitive": target_en.lower() == target_es.lower(),
        "en_name_unique": sum(n.lower() == target_en.lower() for n in names_en) == 1,
    }
    compat = same_length_compatibility(m_es["samples"][TARGET_INDEX], m_en["samples"][TARGET_INDEX])
    if not all(identity.values()) or not all(compat.values()):
        raise SystemExit(f"target not compatible: {identity} {compat}")

    src_stream = m_en["samples"][TARGET_INDEX]["stream"]
    candidate = build(replace_stream(m_es, TARGET_INDEX, src_stream))
    again = build(replace_stream(decompose(es), TARGET_INDEX, src_stream))
    OUT.mkdir(parents=True, exist_ok=True)
    cand_path = OUT / "sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(candidate)
    cand_sha = sha256(candidate)

    spans = sample_spans(es)
    t0, t1 = spans[TARGET_INDEX]
    diffs = diff_ranges(es, candidate, limit=1000)
    data_start = spans[0][0]
    orig_bank, cand_bank = FsbBank(es_path), FsbBank(cand_path)
    meta_o = [(s["frequency"], s["channels"], s["data_offset"], s["sample_count"], s["chunks"])
              for s in orig_bank.samples]
    meta_c = [(s["frequency"], s["channels"], s["data_offset"], s["sample_count"], s["chunks"])
              for s in cand_bank.samples]
    pay_o = [sha256(es[a:b]) for a, b in spans]
    pay_c = [sha256(candidate[a:b]) for a, b in sample_spans(candidate)]
    en_span = sample_spans(en)[TARGET_INDEX]
    changed = [i for i, (a, b) in enumerate(zip(pay_o, pay_c)) if a != b]

    vdir = OUT / "vgm"
    vdir.mkdir(parents=True, exist_ok=True)
    sub = TARGET_INDEX + 1
    target_wavs = {"candidate": decode(exe, cand_path, sub, vdir / f"target_{sub}_candidate.wav"),
                   "english": decode(exe, en_path, sub, vdir / f"target_{sub}_english.wav"),
                   "spanish_original": decode(exe, es_path, sub, vdir / f"target_{sub}_spanish.wav")}
    others = []
    for i in NEIGHBOURS + REPRESENTATIVE:
        a = decode(exe, es_path, i + 1, vdir / f"es_{i + 1:05d}_original.wav")
        b = decode(exe, cand_path, i + 1, vdir / f"es_{i + 1:05d}_candidate.wav")
        others.append({"index": i, "subsong": i + 1, "name": names_es[i], "channels": orig_bank.samples[i]["channels"],
                       "wav_sha256": b, "identical_to_original": a is not None and a == b,
                       "meta_identical": meta(exe, es_path, i + 1) == meta(exe, cand_path, i + 1)})

    full_o = decode_all(exe, es_path, len(pay_o))
    full_c = decode_all(exe, cand_path, len(pay_c))
    en_target_pcm = decode_hash(exe, en_path, sub)
    full = {
        "subsongs": len(full_c),
        "decoded_original": sum(h is not None for h in full_o),
        "decoded_candidate": sum(h is not None for h in full_c),
        "differing_subsongs": [k + 1 for k, (a, b) in enumerate(zip(full_o, full_c)) if a != b],
        "target_equals_english": full_c[TARGET_INDEX] == en_target_pcm,
    }

    checks = {
        "copies_match_pins": True,
        "target_identity": all(identity.values()),
        "metadata_compatible": all(compat.values()),
        "same_size": len(candidate) == len(es),
        "bytes_outside_target_span_identical": candidate[:t0] == es[:t0] and candidate[t1:] == es[t1:],
        "listed_diff_ranges_inside_target_span": bool(diffs) and all(t0 <= a and b <= t1 for a, b in diffs),
        "header_identical": candidate[:data_start] == es[:data_start],  # header, sample headers, name table
        "only_target_payload_changed": changed == [TARGET_INDEX],
        "other_5695_payloads_identical": sum(a == b for a, b in zip(pay_o, pay_c)) == len(pay_o) - 1 == 5695,
        "target_payload_equals_english": candidate[t0:t1] == en[en_span[0]:en_span[1]],
        "reparse_metadata_identical": meta_o == meta_c,
        "names_and_order_identical": orig_bank.names == cand_bank.names,
        "round_trip": build(decompose(candidate)) == candidate,
        "deterministic": again == candidate,
        "lst_untouched": sha256(lst_path.read_bytes()) == pins["spanish.lst"],
        "vgm_target_equals_english": target_wavs["candidate"] is not None
        and target_wavs["candidate"] == target_wavs["english"],
        "vgm_target_differs_from_spanish": target_wavs["candidate"] != target_wavs["spanish_original"],
        "vgm_target_meta_identical": meta(exe, es_path, sub) == meta(exe, cand_path, sub),
        "vgm_neighbours_and_representatives_identical": all(o["identical_to_original"] and o["meta_identical"]
                                                            for o in others),
        "vgm_stereo_covered": any(o["channels"] == 2 for o in others),
        "vgm_all_5696_subsongs_decode": full["decoded_original"] == full["decoded_candidate"] == len(pay_o) == 5696,
        "vgm_only_subsong_31_differs": full["differing_subsongs"] == [sub],
        "vgm_full_target_equals_english": full["target_equals_english"],
    }
    report = {
        "schema": "b2-e1-transplant/1", "experiment": "E1 offline", "steam_build": STEAM_BUILD,
        "target": {"index": TARGET_INDEX, "subsong": sub, "slot_id": TARGET_SLOT, "tag": TARGET_TAG,
                   "spanish_name": target_es, "english_name": target_en,
                   "sample_count": m_es["samples"][TARGET_INDEX]["sample_count"],
                   "stream_bytes": len(src_stream), "span": [t0, t1],
                   "spanish_stream_sha256": sha256(m_es["samples"][TARGET_INDEX]["stream"]),
                   "english_stream_sha256": sha256(src_stream)},
        "identity_checks": identity, "compatibility": compat,
        "hashes": {"original_bank_copy": hashes["spanish.fsb"], "original_bank_installed": install_sha,
                   "installed_equals_original": install_sha == hashes["spanish.fsb"],
                   "english_bank_copy": hashes["english.fsb"], "spanish_lst_copy": hashes["spanish.lst"],
                   "candidate": cand_sha},
        "candidate": cand_path.relative_to(REPO_ROOT).as_posix(), "size": len(candidate),
        "diff_ranges": [{"start": a, "end": b} for a, b in diffs], "diff_ranges_truncated": len(diffs) >= 1000,
        "differing_bytes_in_target": sum(x != y for x, y in zip(es[t0:t1], candidate[t0:t1])),
        "changed_payload_indices": changed,
        "vgmstream": {"target_wav_sha256": target_wavs, "others": others, "full_bank": full},
        "checks": checks, "ok": all(checks.values()),
        "note": "offline only; MCC retail content only; nothing installed; no subtitle or mapping change",
    }
    (OUT / "e1_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUT / "e1_install_rollback.md").write_text(install_sheet(inst, cand_path, hashes["spanish.fsb"], cand_sha) + "\n",
                                                encoding="utf-8")
    lines = ["# B2 E1 offline: English a10_350 in Spanish slot #30", "",
             f"Result: **{'PASS' if report['ok'] else 'FAIL'}**. Candidate `{cand_sha}` ({len(candidate):,} B).", "",
             f"Original `{hashes['spanish.fsb']}`; installed equals original: {report['hashes']['installed_equals_original']}.",
             f"Diff: {report['differing_bytes_in_target']:,} differing bytes, all inside bytes {t0:,}–{t1:,} "
             f"(sample #{TARGET_INDEX}); every byte outside that span is identical.", ""]
    lines += [f"- `{k}`: {v}" for k, v in checks.items()]
    lines += ["", "| subsong | name | ch | identical | -m identical |", "|---|---|---|---|---|"]
    lines += [f"| {o['subsong']} | {o['name']} | {o['channels']} | {o['identical_to_original']} | {o['meta_identical']} |"
              for o in others]
    (OUT / "e1_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"candidate {cand_sha} size={len(candidate)} differing_bytes={report['differing_bytes_in_target']} "
          f"in [{t0},{t1}) changed={changed}")
    print(f"installed bank equals original: {report['hashes']['installed_equals_original']}")
    for k, v in checks.items():
        if not v:
            print("FAILED:", k)
    print(f"checks {sum(checks.values())}/{len(checks)}; wrote work/b2/e1/")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
