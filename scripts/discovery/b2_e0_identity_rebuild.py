"""B2 experiment E0: FSB5 writer identity rebuild (docs/b2-audio-research.md §5).

Inputs (read-only): the pinned copies reference-audio/stage1/fsb/sounds_dialogs{,_spanish}.fsb,
verified against work/mcc/build.json before use. The install is never read or written.

For each bank: decompose with common/fsb5_writer.py, build again, and require:
  - byte-identical output (otherwise up to 20 differing ranges are reported with offsets);
  - re-parse with common/fsb5_lib.py: header, per-sample metadata (frequency, channels, offset,
    sample count, chunks), names and order identical; per-sample payload SHA-256 identical;
  - mono and stereo subsongs decoded by vgmstream (approved r2117) from the original copy and
    the rebuilt file give identical WAVs and identical `-m` metadata.

Outputs (git-ignored): work/b2/e0/<bank>.fsb (rebuilt, ~640 MB total; --no-keep deletes them),
work/b2/e0/vgm/*.wav, work/b2/e0/e0_report.json and e0_summary.md.
No audio is replaced; no new tool is used.

Example:
    python scripts/discovery/b2_e0_identity_rebuild.py
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_lib import FsbBank  # noqa: E402
from common.fsb5_writer import build, decompose, diff_ranges  # noqa: E402

BANKS = {"spanish.fsb": "sounds_dialogs_spanish.fsb", "english.fsb": "sounds_dialogs.fsb"}
COPIES = REPO_ROOT / "reference-audio" / "stage1" / "fsb"
OUT = REPO_ROOT / "work" / "b2" / "e0"
DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def region_of(offset, bank):
    h = bank.header
    sh = h["base_header_size"]
    nt = sh + h["sample_headers_size"]
    if offset < sh:
        return "header"
    if offset < nt:
        return "sample_headers"
    if offset < bank.data_start:
        return "name_table"
    rel = offset - bank.data_start
    idx = max(i for i, s in enumerate(bank.samples) if s["data_offset"] <= rel)
    return f"data:sample[{idx}]"


def payload_hashes(bank):
    ends = [s["data_offset"] for s in bank.samples[1:]] + [bank.header["data_size"]]
    return [sha256(bank.data[bank.data_start + s["data_offset"]:bank.data_start + e])
            for s, e in zip(bank.samples, ends)]


def pick_subsongs(bank):
    """0-based indices: first/second/last mono, a10_350 if present, longest, first/last stereo."""
    mono = [i for i, s in enumerate(bank.samples) if s["channels"] == 1]
    stereo = [i for i, s in enumerate(bank.samples) if s["channels"] == 2]
    longest = max(range(len(bank.samples)), key=lambda i: bank.samples[i]["sample_count"])
    picks = [mono[0], mono[1], mono[-1], longest] + ([stereo[0], stereo[-1]] if stereo else [])
    k = bank.find("a10_350_captkeyes")
    if k is not None:
        picks.append(k)
    return sorted(set(picks))


def vgm_meta(exe, path, subsong):
    res = subprocess.run([str(exe), "-m", "-s", str(subsong), str(path)], capture_output=True, text=True)
    lines = [ln for ln in res.stdout.splitlines() if str(path) not in ln and "metadata for" not in ln.lower()]
    return res.returncode, lines


def vgm_compare(exe, orig_path, new_path, bank, picks, tag):
    out_dir = OUT / "vgm"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in picks:
        row = {"index": i, "subsong": i + 1, "name": bank.names[i], "channels": bank.samples[i]["channels"],
               "sample_count": bank.samples[i]["sample_count"]}
        wavs = {}
        for which, path in (("original", orig_path), ("rebuilt", new_path)):
            wav = out_dir / f"{tag}_{i + 1:05d}_{which}.wav"
            res = subprocess.run([str(exe), "-s", str(i + 1), "-o", str(wav), str(path)],
                                 capture_output=True, text=True)
            wavs[which] = sha256(wav.read_bytes()) if res.returncode == 0 and wav.is_file() else None
        rc_o, meta_o = vgm_meta(exe, orig_path, i + 1)
        rc_n, meta_n = vgm_meta(exe, new_path, i + 1)
        row.update({"wav_sha256_original": wavs["original"], "wav_sha256_rebuilt": wavs["rebuilt"],
                    "wav_identical": wavs["original"] is not None and wavs["original"] == wavs["rebuilt"],
                    "meta_identical": rc_o == rc_n == 0 and meta_o == meta_n,
                    "stream_count_line": next((ln.strip() for ln in meta_n if "stream count" in ln.lower()), None)})
        rows.append(row)
    return rows


def run_bank(key, fname, pins, exe, keep):
    path = COPIES / fname
    t0 = time.time()
    data = path.read_bytes()
    src_sha = sha256(data)
    if src_sha != pins[key]:
        raise SystemExit(f"{fname}: copy sha256 {src_sha} != pinned {pins[key]}; refusing to use it")
    model = decompose(data)
    rebuilt = build(model)
    rebuilt_sha = sha256(rebuilt)
    orig = FsbBank(path)
    diffs = diff_ranges(data, rebuilt)

    OUT.mkdir(parents=True, exist_ok=True)
    new_path = OUT / fname
    new_path.write_bytes(rebuilt)
    new = FsbBank(new_path)
    meta_o = [(s["frequency"], s["channels"], s["data_offset"], s["sample_count"], s["chunks"]) for s in orig.samples]
    meta_n = [(s["frequency"], s["channels"], s["data_offset"], s["sample_count"], s["chunks"]) for s in new.samples]
    ph_o, ph_n = payload_hashes(orig), payload_hashes(new)
    picks = pick_subsongs(orig)
    vgm = vgm_compare(exe, path, new_path, orig, picks, key.split(".")[0])

    checks = {
        "copy_matches_pin": True,
        "byte_identical": rebuilt == data,
        "same_size": len(rebuilt) == len(data),
        "header_identical": orig.header == new.header and data[:orig.header["base_header_size"]] == rebuilt[
            :new.header["base_header_size"]],
        "sample_metadata_identical": meta_o == meta_n,
        "names_and_order_identical": orig.names == new.names,
        "payload_hashes_identical": ph_o == ph_n,
        "has_mono_and_stereo": {s["channels"] for s in orig.samples} >= {1, 2},
        "model_names_sequential": model["names"] is not None,
        "vgmstream_wavs_identical": all(r["wav_identical"] for r in vgm),
        "vgmstream_metadata_identical": all(r["meta_identical"] for r in vgm),
    }
    chunk_types = sorted({c[0] for s in orig.samples for c in s["chunks"]})
    result = {
        "bank": fname, "source_copy": path.relative_to(REPO_ROOT).as_posix(), "source_sha256": src_sha,
        "rebuilt": new_path.relative_to(REPO_ROOT).as_posix() if keep else None, "rebuilt_sha256": rebuilt_sha,
        "size": len(data), "samples": len(orig.samples),
        "mono": sum(s["channels"] == 1 for s in orig.samples), "stereo": sum(s["channels"] == 2 for s in orig.samples),
        "chunk_types": chunk_types, "diff_ranges": [{"start": a, "end": b, "region": region_of(a, orig)}
                                                    for a, b in diffs],
        "vgmstream_subsongs": vgm, "checks": checks, "ok": all(checks.values()),
        "seconds": round(time.time() - t0, 1),
    }
    del orig, new
    if not keep:
        new_path.unlink()
    return result


def summary_md(report):
    lines = ["# B2 E0: FSB5 identity rebuild", "",
             f"vgmstream: `{report['vgmstream']}`. Result: **{'PASS' if report['ok'] else 'FAIL'}**.", ""]
    for b in report["banks"]:
        lines += [f"## {b['bank']}", "",
                  f"- source `{b['source_sha256']}`; rebuilt `{b['rebuilt_sha256']}`; {b['size']:,} bytes",
                  f"- {b['samples']} samples ({b['mono']} mono, {b['stereo']} stereo); chunk types {b['chunk_types']}",
                  f"- differing ranges: {len(b['diff_ranges'])}", ""]
        lines += [f"- `{k}`: {v}" for k, v in b["checks"].items()]
        lines += ["", "| subsong | name | ch | WAV identical | -m identical |", "|---|---|---|---|---|"]
        lines += [f"| {r['subsong']} | {r['name']} | {r['channels']} | {r['wav_identical']} | {r['meta_identical']} |"
                  for r in b["vgmstream_subsongs"]]
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--no-keep", action="store_true", help="delete the rebuilt banks after checking")
    args = ap.parse_args()
    if not args.vgmstream_cli.is_file():
        raise SystemExit(f"vgmstream-cli not found: {args.vgmstream_cli}")
    build_json = json.loads((REPO_ROOT / "work" / "mcc" / "build.json").read_text(encoding="utf-8"))
    pins = {k: build_json["files"][k]["sha256"] for k in BANKS}

    banks = [run_bank(k, f, pins, args.vgmstream_cli, not args.no_keep) for k, f in BANKS.items()]
    report = {"schema": "b2-e0-identity/1", "experiment": "E0", "vgmstream": str(args.vgmstream_cli),
              "banks": banks, "ok": all(b["ok"] for b in banks),
              "note": "offline; verified copies only; no install access; no audio replaced"}
    OUT.mkdir(parents=True, exist_ok=True)
    timing = {b["bank"]: b.pop("seconds") for b in banks}  # keep the JSON deterministic
    (OUT / "e0_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUT / "e0_summary.md").write_text(summary_md(report) + "\n", encoding="utf-8")
    for b in banks:
        print(f"{b['bank']}: ok={b['ok']} diffs={len(b['diff_ranges'])} samples={b['samples']} "
              f"({b['mono']} mono/{b['stereo']} stereo) vgm={len(b['vgmstream_subsongs'])} subsongs "
              f"{timing[b['bank']]}s")
        failed = [k for k, v in b["checks"].items() if not v]
        if failed:
            print("  failed:", failed, b["diff_ranges"][:5])
    print("wrote work/b2/e0/e0_report.json and e0_summary.md")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
