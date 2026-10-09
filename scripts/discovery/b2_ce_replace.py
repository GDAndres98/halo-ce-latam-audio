"""B2 E3+: build an MCC Spanish bank with ONE slot replaced by a Campaign Evolved recording (offline).

The pairing (MCC slot <-> CE line) is never chosen by this tool: it comes from the command line, given
by the owner for an experiment (--owner-selected), or later from approved `audio` objects in
mappings/manual_mappings.json (batch generator, M6). Pipeline: common/audio_pipeline.py
(ffmpeg -> 44.1 kHz -> pad codec delay -> CELT 0.11 MCC profile). Validation: common/bank_checks.py
plus vgmstream on all 5,696 subsongs and a content check (decoded target vs the 44.1 kHz source).

Inputs (read-only): reference-audio/stage1 bank copies (pinned), work/mcc/catalog/*.jsonl (slots),
work/ce/audio/<mission>/manifest.json + WAVs (M1b decodes).
Outputs (git-ignored): work/derived/<stream sha>/ (recipe + 44.1 kHz WAV), work/b2/<exp>/
{sounds_dialogs_spanish.fsb, <exp>_report.json, <exp>_manifest.json, <exp>_summary.md,
<exp>_install_rollback.md}. Never installs anything.

Example:
    python scripts/discovery/b2_ce_replace.py --exp e3 --slot "es:A10_xxx#0" \\
        --ce-ref "vo_scr_m01_xxxxx_name#0" --owner-selected
"""
import argparse
import hashlib
import json
import math
import shutil
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.audio_pipeline import derive, snr_db, sha256_file  # noqa: E402
from common.bank_checks import decode_checks, structural_checks  # noqa: E402
from common.celt011 import DEFAULT_DLL, Celt011  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_writer import build, decompose, replace_sample  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_pcm  # noqa: E402

BANK = REPO_ROOT / "reference-audio" / "stage1" / "fsb" / "sounds_dialogs_spanish.fsb"
DERIVED = REPO_ROOT / "work" / "derived"
MIN_CONTENT_SNR_DB = 30.0  # decoded target vs its 44.1 kHz source; re-encoded MCC speech measures ~47.8 dB


def find_slot(slot_id):
    for cat in sorted((REPO_ROOT / "work" / "mcc" / "catalog").glob("*.jsonl")):
        for line in cat.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            for s in rec.get("samples", {}).get("spanish", []):
                if s.get("slot_id") == slot_id:
                    return rec, s
    raise SystemExit(f"slot {slot_id} not found in work/mcc/catalog/*.jsonl")


def find_ce_unit(ce_ref, language):
    for man in sorted((REPO_ROOT / "work" / "ce" / "audio").glob("*/manifest.json")):
        m = json.loads(man.read_text(encoding="utf-8"))
        for u in m["units"]:
            if u["language"] == language and ce_ref in u["references"]:
                if u["status"] != "ok":
                    raise SystemExit(f"{ce_ref} ({language}) has status {u['status']}")
                return m, u, man.parent / u["wav_path"]
    raise SystemExit(f"{ce_ref} ({language}) not found in work/ce/audio/*/manifest.json (decode it with M1b first)")


def install_sheet(exp, slot_id, ce_ref, cand_sha, seconds):
    return "\n".join([
        f"# B2 {exp.upper()}-game: install and rollback (LOCAL ONLY; NOT APPROVED YET)", "",
        f"Candidate: Campaign Evolved `{ce_ref}` (Spanish(Mexico)) in MCC slot `{slot_id}` ({seconds} s).",
        f"Bank `{cand_sha}`.", "",
        "```powershell",
        f"python scripts/discovery/b2_bank_install.py --exp {exp} preflight",
        f"python scripts/discovery/b2_bank_install.py --exp {exp} install",
        "# launch MCC: Steam > Play > \"Play Halo: MCC Anti-Cheat Disabled\"; test; CLOSE MCC (also after a crash)",
        f"python scripts/discovery/b2_bank_install.py --exp {exp} rollback",
        "```", "",
        "Settings: primary Spanish (Latin America), fallback Spanish (Spain), subtitles on. Test Classic and",
        "Anniversary. Expected: the LATAM recording plays in that slot, completely and cleanly; other lines",
        "Spain Spanish; subtitles unchanged (audio only); no crash. If it crashes: close MCC, roll back, report.", "",
    ])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp", required=True)
    ap.add_argument("--slot", required=True, help="MCC Spanish slot id, e.g. es:A10_350_captkeyes#0")
    ap.add_argument("--ce-ref", required=True, help="CE line ref, e.g. vo_scr_m01_00460_cryotech#0")
    ap.add_argument("--language", default="Spanish(Mexico)")
    ap.add_argument("--owner-selected", action="store_true",
                    help="required: confirms the owner chose this pairing (tools never match lines)")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = ap.parse_args()
    if not args.owner_selected:
        raise SystemExit("refusing: the slot/CE pairing must be chosen by the owner (--owner-selected)")
    if not args.ffmpeg:
        raise SystemExit("ffmpeg not found")
    exe, out = args.vgmstream_cli, REPO_ROOT / "work" / "b2" / args.exp

    pins = {k: v["sha256"] for k, v in json.loads((REPO_ROOT / "work" / "mcc" / "build.json")
                                                  .read_text(encoding="utf-8"))["files"].items()}
    original = BANK.read_bytes()
    if hashlib.sha256(original).hexdigest() != pins["spanish.fsb"]:
        raise SystemExit("Spanish bank copy does not match its pin")
    rec, slot = find_slot(args.slot)
    index, channels = slot["index"], slot["channels"]
    if channels != 1:
        raise SystemExit(f"{args.slot} is stereo; stereo slots need an explicit owner choice (not supported yet)")
    man, unit, wav = find_ce_unit(args.ce_ref, args.language)
    if sha256_file(wav) != unit["wav_sha256"]:
        raise SystemExit(f"{wav.name} does not match its manifest hash")

    celt = Celt011()
    res = derive(wav, ffmpeg=args.ffmpeg, celt=celt, out_root=DERIVED, channels=1, profile="fmod",
                 source_meta={"ce_line_ref": args.ce_ref, "language": args.language, "media_id": unit["media_id"],
                              "wem_sha256": unit["wem_sha256"], "ce_build": man["source_build"]})
    again = derive(wav, ffmpeg=args.ffmpeg, celt=celt, out_root=DERIVED, channels=1, profile="fmod",
                   source_meta=res["recipe"]["source"])
    celt.close()

    model = decompose(original)
    candidate = build(replace_sample(model, index, res["stream"], res["sample_count"]))
    candidate2 = build(replace_sample(decompose(original), index, again["stream"], again["sample_count"]))
    out.mkdir(parents=True, exist_ok=True)
    cand_path = out / "sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(candidate)
    cand_sha = hashlib.sha256(candidate).hexdigest()

    checks = {"bank_copy_matches_pin": True, "source_wav_matches_manifest": True,
              "deterministic_stream": res["stream"] == again["stream"], "deterministic_bank": candidate == candidate2}
    checks.update(structural_checks(original, candidate, index, res["stream"], res["sample_count"]))
    dec, target_meta = decode_checks(exe, BANK, cand_path, index, res["sample_count"], len(model["samples"]))
    checks.update(dec)
    vgm_target = decode_pcm(exe, cand_path, index + 1)
    vgm_pcm = vgm_target[vgm_target.index(b"data") + 8:]
    content_snr = snr_db(res["pcm"], vgm_pcm)
    src_samples = len(res["pcm"]) // 2
    src_a, dec_a = array("h", res["pcm"]), array("h", vgm_pcm)
    tail = min(4410, src_samples)  # last 100 ms of the source, aligned for the codec delay
    tail_snr = snr_db(res["pcm"][-tail * 2:], vgm_pcm[(src_samples - tail) * 2:], lag=128)
    tail_silent = max((abs(v) for v in src_a[-tail:]), default=0) < 64
    full_scale = sum(1 for v in dec_a if v in (32767, -32768))
    full_scale_src = sum(1 for v in src_a if v in (32767, -32768))
    after_end = dec_a[128 + src_samples:]
    extra = {"peak_source": max(map(abs, src_a)), "peak_decoded": max(map(abs, dec_a)),
             "full_scale_samples_decoded": full_scale, "full_scale_samples_source": full_scale_src,
             "tail_100ms_snr_db": round(tail_snr, 1) if math.isfinite(tail_snr) else str(tail_snr),
             "samples_after_source_end": len(after_end),
             "max_abs_after_source_end": max(map(abs, after_end), default=0)}
    checks.update({
        "vgm_target_equals_own_decode": vgm_pcm == res["decoded"][:len(vgm_pcm)],
        "content_snr_vs_source_ok": content_snr >= MIN_CONTENT_SNR_DB,
        "duration_covers_source_plus_delay": src_samples + 128 <= res["sample_count"] < src_samples + 128 + 512,
        "no_new_clipping": full_scale <= full_scale_src,
        "tail_not_truncated": tail_silent or tail_snr >= 20.0,
        "silence_after_source_end": extra["max_abs_after_source_end"] < 64,
        "lst_untouched": hashlib.sha256((REPO_ROOT / "reference-audio" / "stage1" / "lst" /
                                         "sounds_dialogs_spanish.lst.bin").read_bytes()).hexdigest()
        == pins["spanish.lst"],
    })

    seconds = round(res["sample_count"] / 44100, 3)
    manifest = {
        "schema": "b2-ce-replace-manifest/1", "experiment": args.exp,
        "pairing": {"slot_id": args.slot, "mcc_tag": rec["mcc_tag"], "spanish_index": index,
                    "ce_line_ref": args.ce_ref, "language": args.language,
                    "selected_by": "owner (command line, --owner-selected)",
                    "note": "experiment pairing; not an approved manual_mappings.json entry"},
        "inputs": {"bank_copy_sha256": pins["spanish.fsb"], "ce_wav_sha256": unit["wav_sha256"],
                   "ce_wem_sha256": unit["wem_sha256"], "libcelt_sha256": sha256_file(DEFAULT_DLL),
                   "ffmpeg": res["recipe"]["steps"][0]["version"]},
        "derived": {"dir": res["dir"].relative_to(REPO_ROOT).as_posix(), "recipe": res["recipe"]},
        "outputs": {"candidate": cand_path.relative_to(REPO_ROOT).as_posix(), "candidate_sha256": cand_sha,
                    "size": len(candidate), "growth_bytes": len(candidate) - len(original)},
    }
    report = {
        "schema": "b2-ce-replace/1", "experiment": args.exp, "ok": all(checks.values()), "checks": checks,
        "target": {"index": index, "slot_id": args.slot, "original_sample_count": slot["sample_count"],
                   "original_seconds": round(slot["sample_count"] / 44100, 3), "new_sample_count": res["sample_count"],
                   "new_seconds": seconds, "source_seconds": res["recipe"]["source"]["seconds"]},
        "content_snr_db": round(content_snr, 1), "signal_checks": extra, "target_meta": target_meta,
        "hashes": {"original_bank": pins["spanish.fsb"], "candidate": cand_sha},
        "note": "offline only; nothing installed",
    }
    (out / f"{args.exp}_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / f"{args.exp}_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / f"{args.exp}_install_rollback.md").write_text(
        install_sheet(args.exp, args.slot, args.ce_ref, cand_sha, seconds) + "\n", encoding="utf-8")
    lines = [f"# B2 {args.exp}: {args.ce_ref} -> {args.slot} — {'PASS' if report['ok'] else 'FAIL'}", "",
             f"Target #{index}: {report['target']['original_seconds']} s -> {seconds} s "
             f"(source {report['target']['source_seconds']} s); content SNR {report['content_snr_db']} dB; "
             f"candidate `{cand_sha}` ({manifest['outputs']['growth_bytes']:+,} B).", ""]
    lines += [f"- `{k}`: {v}" for k, v in checks.items()]
    (out / f"{args.exp}_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:3]))
    for k, v in checks.items():
        if not v:
            print("FAILED:", k)
    print(f"checks {sum(checks.values())}/{len(checks)}; wrote {out.relative_to(REPO_ROOT).as_posix()}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
