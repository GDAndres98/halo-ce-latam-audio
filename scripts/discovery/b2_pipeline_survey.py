"""B2 E3 readiness: run the WAV -> MCC CELT pipeline on every decoded CE recording of one language.

No pairing, no bank: each recording is converted (ffmpeg 44.1 kHz), encoded (CELT 0.11, MCC profile),
decoded again, and checked: MCC profile on every packet, CBR packet size, sample_count = whole frames
covering source + codec delay, and SNR of the decode against the 44.1 kHz source.

Inputs: work/ce/audio/<mission>/manifest.json + WAVs (M1b). Outputs (git-ignored): work/derived/<sha>/
per recording and work/b2/pipeline_survey_<mission>.json.

Example:
    python scripts/discovery/b2_pipeline_survey.py --mission m01
"""
import argparse
import json
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.audio_pipeline import CODEC_DELAY, derive, sha256_file  # noqa: E402
from common.celt011 import Celt011  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

MIN_SNR_DB = 30.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", default="m01")
    ap.add_argument("--language", default="Spanish(Mexico)")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = ap.parse_args()
    base = REPO_ROOT / "work" / "ce" / "audio" / args.mission
    man = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    units = [u for u in man["units"] if u["language"] == args.language and u["status"] == "ok"]
    celt = Celt011()
    rows, failures = [], []
    for u in units:
        wav = base / u["wav_path"]
        if sha256_file(wav) != u["wav_sha256"]:
            failures.append({"ref": u["primary_ref"], "error": "wav hash mismatch"})
            continue
        try:
            r = derive(wav, ffmpeg=args.ffmpeg, celt=celt, out_root=REPO_ROOT / "work" / "derived",
                       source_meta={"ce_line_ref": u["primary_ref"], "language": args.language})
        except Exception as e:  # noqa: BLE001 - reported, never hidden
            failures.append({"ref": u["primary_ref"], "error": str(e)})
            continue
        o = r["recipe"]["output"]
        n = r["recipe"]["pcm_44100"]["samples"]
        rows.append({"ref": u["primary_ref"], "source_s": r["recipe"]["source"]["seconds"],
                     "samples_44100": n, "sample_count": o["sample_count"], "snr_db": o["own_decode_snr_db"],
                     "packet_sizes": r["recipe"]["steps"][2]["packet_bytes"],
                     "covers": n + CODEC_DELAY <= o["sample_count"] < n + CODEC_DELAY + 512,
                     "stream_sha256": o["stream_sha256"]})
    celt.close()
    snrs = [r["snr_db"] for r in rows]
    checks = {
        "all_encoded": len(rows) == len(units) and not failures,
        "all_packets_370": all(r["packet_sizes"] == [370] for r in rows),
        "all_cover_source_plus_delay": all(r["covers"] for r in rows),
        "all_snr_at_least_30db": bool(snrs) and min(snrs) >= MIN_SNR_DB,
        "duration_ratio_44100_over_48000_ok": all(abs(r["samples_44100"] / 44100 - r["source_s"]) < 0.002 for r in rows),
    }
    report = {"schema": "b2-pipeline-survey/1", "mission": args.mission, "language": args.language,
              "count": len(rows), "failures": failures, "checks": checks, "ok": all(checks.values()),
              "snr_db": {"min": min(snrs), "median": statistics.median(snrs), "max": max(snrs)} if snrs else None,
              "rows": rows}
    out = REPO_ROOT / "work" / "b2" / f"pipeline_survey_{args.mission}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("count", "checks", "ok", "snr_db")}, indent=1),
          "failures:", failures[:3])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
