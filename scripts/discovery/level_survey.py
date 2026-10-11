"""Loudness survey of a built bank: what the game will actually play, against what it played before (read-only).

For a sample of the replaced lines of work/m6/<build>/, decodes with vgmstream:
  MCC    the original Spain recording (pinned bank copy, the same subsong)
  CE     the Campaign Evolved source WAV
  rend   the processed 44.1 kHz PCM the build encoded (work/derived/<sha>/mcc_44100.wav)
  dec    the line as the game will decode it from the candidate bank
and measures BS.1770 integrated loudness (common.audio_edit.loudness), active-speech RMS and sample peak.

It answers: is the build's gain in the decoded output (rend - CE = applied gain; dec - rend = codec), and
how loud are the replacements against the recordings they replace (dec - MCC). Writes nothing in the repo;
--json saves the rows.

    python scripts/discovery/level_survey.py --build all_mapped_4 --step 10
"""
import argparse
import io
import json
import math
import statistics as st
import sys
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.audio_edit import loudness, peak_db, wav_mono_float  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_pcm  # noqa: E402

ORIGINAL = REPO_ROOT / "reference-audio" / "stage1" / "fsb" / "sounds_dialogs_spanish.fsb"


def wav_bytes(b):
    w = wave.open(io.BytesIO(b))
    ch, n = w.getnchannels(), w.getnframes()
    a = array("h", w.readframes(n))
    return [v / 32768 for v in (a[::ch] if ch > 1 else a)], w.getframerate()


def active_rms_db(x, fs):
    n = int(0.02 * fs)
    frames = [sum(v * v for v in x[i:i + n]) / n for i in range(0, len(x) - n, n)]
    act = [p for p in frames if p > 1e-5]  # frames above -50 dBFS
    return 10 * math.log10(sum(act) / len(act)) if act else None


def measure(x, fs):
    return {"lufs": loudness(x, fs)[0], "rms": active_rms_db(x, fs), "peak": peak_db(x)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", required=True)
    ap.add_argument("--step", type=int, default=10, help="every Nth replaced line (default 10)")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--json", type=Path, help="save the rows here")
    a = ap.parse_args()
    folder = REPO_ROOT / "work" / "m6" / a.build
    m = json.loads((folder / "build_manifest.json").read_text(encoding="utf-8"))
    bank = folder / "sounds_dialogs_spanish.fsb"
    lv = m.get("level") or {"mode": "global_gain", "global_gain_db": (m.get("global_gain") or {}).get("configured_db")}
    print(f"build {a.build} ({m.get('built_at')}): level {lv['mode']}, global gain {lv.get('global_gain_db')}")
    rows = []
    for e in [e for e in m["slots"] if e["action"] == "replace"][::a.step]:
        sub = e["spanish_index"] + 1
        r = {"slot": e["slot_id"], "level": e["level"], "gain": e.get("total_gain_db", e.get("global_gain_applied_db")),
             "MCC": measure(*wav_bytes(decode_pcm(a.vgmstream_cli, ORIGINAL, sub))),
             "CE": measure(*wav_mono_float(REPO_ROOT / e["source_wav"])),
             "rend": measure(*wav_mono_float(REPO_ROOT / e["derived_dir"] / "mcc_44100.wav")),
             "dec": measure(*wav_bytes(decode_pcm(a.vgmstream_cli, bank, sub)))}
        rows.append(r)
        print(f"{r['slot'][:32]:32} {r['level']:8} gain {r['gain']:+5.1f} | MCC {r['MCC']['lufs']:6.1f} | CE "
              f"{r['CE']['lufs']:6.1f} | decoded {r['dec']['lufs']:6.1f} pk {r['dec']['peak']:5.1f} | vs MCC "
              f"{r['dec']['lufs'] - r['MCC']['lufs']:+5.1f}", flush=True)
    if not rows:
        raise SystemExit("no replaced lines")

    def med(k, f):
        return st.median(r[k][f] for r in rows if r[k][f] is not None)
    print(f"\n{len(rows)} line(s)")
    for k in ("MCC", "CE", "rend", "dec"):
        print(f"  {k:5} LUFS median {med(k, 'lufs'):6.1f} | active RMS {med(k, 'rms'):6.1f} | peak {med(k, 'peak'):5.1f}")
    d = sorted(r["dec"]["lufs"] - r["MCC"]["lufs"] for r in rows)
    print(f"  decoded - MCC LUFS: median {st.median(d):+.1f} (p10 {d[len(d) // 10]:+.1f}, p90 {d[9 * len(d) // 10]:+.1f})")
    c = sorted(r["dec"]["lufs"] - r["rend"]["lufs"] for r in rows)
    print(f"  decoded - rendered (codec): median {st.median(c):+.2f} (min {c[0]:+.2f}, max {c[-1]:+.2f})")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
