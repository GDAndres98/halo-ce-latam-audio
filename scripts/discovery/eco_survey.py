"""Echo survey of the "eco" radio lines (read-only; docs/radio-filter.md §5).

Reads the recordings listed by `scripts/discovery/radio_survey.py` (work/reports/radio_survey.json; run it first)
and measures, for the radio lines whose note says "eco" (the cryo assistant's intercom) and 20 control lines:
  sample autocorrelation   normalised, at fixed lags (discrete, exact echoes: the MCC English taps)
  envelope autocorrelation of 5 ms RMS frames (smeared echoes, which sample correlation misses: MCC Spain)
for MCC Spain, MCC English and the CE es-MX source. Then it applies the recipe presets (radio spain_eco + echo
spain; radio english_eco + echo english) to the dry CE es-MX recordings with common/audio_edit.py and measures the
same, so the presets can be compared with what they imitate. Stdlib only; writes work/reports/eco_survey.json.

    python scripts/discovery/eco_survey.py
"""
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import audio_edit as ae  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

SAMPLE_LAGS = (30, 60, 120, 150, 200, 300)
ENV_LAGS = (80, 140, 150, 200, 280)


def sample_ac(x, fs, lag_ms):
    """Normalised autocorrelation near a lag (x decimated by 4; best of +-2 decimated samples)."""
    y, f = x[::4], fs / 4
    r0 = sum(v * v for v in y) or 1.0
    k0 = round(lag_ms / 1000 * f)
    return max(sum(y[i] * y[i + k] for i in range(len(y) - k)) / r0 for k in range(k0 - 2, k0 + 3))


def envelope_ac(x, fs, ms=5):
    fr = int(ms / 1000 * fs)
    e = [math.sqrt(sum(v * v for v in x[i:i + fr]) / fr) for i in range(0, len(x) - fr, fr)]
    m = sum(e) / len(e)
    e = [v - m for v in e]
    r0 = sum(v * v for v in e) or 1.0
    return {L: sum(e[i] * e[i + L // ms] for i in range(len(e) - L // ms)) / r0 for L in ENV_LAGS}


def measure(x, fs):
    return {"sample": {L: sample_ac(x, fs, L) for L in SAMPLE_LAGS}, "envelope": envelope_ac(x, fs)}


def medians(ms):
    return {kind: {L: round(st.median(m[kind][L] for m in ms), 3) for L in ms[0][kind]} for kind in ("sample", "envelope")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    args = ap.parse_args()
    src = args.root / "work" / "reports" / "radio_survey.json"
    if not src.is_file():
        raise SystemExit("run scripts/discovery/radio_survey.py first")
    rows = json.loads(src.read_text(encoding="utf-8"))["rows"]
    groups = {"eco": [r for r in rows if r["group"] == "radio_eco"],
              "control": [r for r in rows if r["group"] == "control"][:20]}
    out = {"schema": "eco-survey/1", "sample_lags_ms": SAMPLE_LAGS, "envelope_lags_ms": ENV_LAGS, "measured": {}}
    for g, rs in groups.items():
        for k in ("mcc_es", "mcc_en", "ce_esmx"):
            ms = [measure(*ae.wav_mono_float(r[k])) for r in rs if r[k]]
            out["measured"][f"{g}/{k}"] = medians(ms)
            print(f"{g:8s} {k:8s}", json.dumps(out["measured"][f"{g}/{k}"]), flush=True)
    for name, radio, echo in (("spain preset", "spain_eco", "spain"), ("english preset", "english_eco", "english")):
        ms = []
        for r in groups["eco"]:
            x, fs = ae.wav_mono_float(r["ce_esmx"])
            y, _ = ae.radio_filter(x, ae.normalize_radio({"preset": radio}), fs)
            y, _ = ae.echo_effect(y, ae.normalize_echo({"preset": echo}), fs)
            ms.append(measure(y, fs))
        out["measured"][name] = medians(ms)
        print(f"{name:17s}", json.dumps(out["measured"][name]), flush=True)
    dst = args.root / "work" / "reports" / "eco_survey.json"
    dst.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dst.relative_to(args.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
