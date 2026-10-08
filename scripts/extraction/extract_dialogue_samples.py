"""Decode named Halo CE MCC dialogue samples from English/Spanish FSB5
copies to WAV using vgmstream-cli, and report a CSV of what was found.

Read-only / non-destructive by design:
  - Never touches the live game install -- only ever opens the FSB5
    files given on the command line (intended to be local copies).
  - Never writes into an FSB -- only ever *reads* it and asks
    vgmstream-cli to decode one subsong at a time to a brand new WAV
    file in --out-dir.
  - Does not hardcode any installation path (Steam library, vgmstream
    location, or this repo's layout) -- everything is a required
    command-line argument, so this script is reusable against any
    future copy/location.

Example:
    python extract_dialogue_samples.py ^
        --en-fsb "D:\\copies\\sounds_dialogs.fsb" ^
        --es-fsb "D:\\copies\\sounds_dialogs_spanish.fsb" ^
        --vgmstream-cli "D:\\Tools\\vgmstream-r2117\\vgmstream-cli.exe" ^
        --names a10_010_cryotech,a10_011_cryoassist,a10_350_captkeyes,a10_370_captkeyes,a10_641_cortana ^
        --out-dir "D:\\copies\\wav" ^
        --csv-out "D:\\copies\\stage2a_report.csv"
"""
import argparse
import csv
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.fsb5_lib import FsbBank  # noqa: E402


def wav_duration_seconds(path):
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        return frames / rate if rate else None


def decode_one(vgmstream_cli, fsb_path, zero_based_index, out_wav):
    subsong = zero_based_index + 1  # vgmstream -s is 1-based
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(vgmstream_cli), "-s", str(subsong), "-o", str(out_wav), str(fsb_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--en-fsb", required=True, type=Path,
                     help="Path to a local COPY of the English dialogue bank (sounds_dialogs.fsb)")
    ap.add_argument("--es-fsb", required=True, type=Path,
                     help="Path to a local COPY of the Spanish dialogue bank (sounds_dialogs_spanish.fsb)")
    ap.add_argument("--vgmstream-cli", required=True, type=Path,
                     help="Path to vgmstream-cli.exe")
    ap.add_argument("--names", required=True,
                     help="Comma-separated list of sample names to extract (e.g. a10_350_captkeyes)")
    ap.add_argument("--out-dir", required=True, type=Path,
                     help="Directory to write decoded WAV files into (should be outside Git/Steam)")
    ap.add_argument("--csv-out", required=True, type=Path,
                     help="Path to write the CSV report to")
    args = ap.parse_args()

    names = [n.strip() for n in args.names.split(",") if n.strip()]

    banks = {
        "english": FsbBank(args.en_fsb),
        "spanish": FsbBank(args.es_fsb),
    }

    rows = []
    for name in names:
        for lang, bank in banks.items():
            idx = bank.find(name)
            row = {
                "sample_name": name,
                "language": lang,
                "found": idx is not None,
                "zero_based_index": idx,
                "subsong_1based": (idx + 1) if idx is not None else None,
                "frequency_hz": None,
                "channels": None,
                "codec": bank.header["mode_name"],
                "header_sample_count": None,
                "header_duration_s": None,
                "wav_path": None,
                "wav_duration_s": None,
                "duration_match": None,
                "vgmstream_returncode": None,
                "vgmstream_stderr": None,
            }
            if idx is not None:
                s = bank.samples[idx]
                row["frequency_hz"] = s["frequency"]
                row["channels"] = s["channels"]
                row["header_sample_count"] = s["sample_count"]
                row["header_duration_s"] = round(bank.duration_seconds(idx), 3)

                out_wav = args.out_dir / f"{name}_{lang}.wav"
                res = decode_one(args.vgmstream_cli, bank.path, idx, out_wav)
                row["vgmstream_returncode"] = res.returncode
                if res.returncode == 0 and out_wav.exists():
                    row["wav_path"] = str(out_wav)
                    dur = wav_duration_seconds(out_wav)
                    row["wav_duration_s"] = round(dur, 3) if dur is not None else None
                    if row["wav_duration_s"] is not None:
                        row["duration_match"] = abs(row["wav_duration_s"] - row["header_duration_s"]) < 0.01
                else:
                    row["vgmstream_stderr"] = (res.stderr or "").strip()[:500]
            rows.append(row)

    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {args.csv_out}")
    for row in rows:
        print(row["sample_name"], row["language"], "->",
              "OK" if row["wav_path"] else f"FAILED ({row['vgmstream_stderr']})")


if __name__ == "__main__":
    main()
