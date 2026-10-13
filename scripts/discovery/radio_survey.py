"""Radio-effect survey: how the MCC radio lines are filtered (read-only; docs/radio-filter.md).

For every mapping flagged "Needs radio effect" and a control set of 60 unflagged scripted/cinematic lines with
approved CE audio, decodes (through the Studio's on-demand decoders, cached under work/):
  mcc_es   the MCC Spain recording of the slot (the pinned bank copy)
  mcc_en   the MCC English recording of the same tag
  ce_esmx  the CE es-MX source of the mapping
  ce_en    the CE English recording of the same CE line
and measures, per recording: the long-term average spectrum of the active frames in 1/3-octave bands (relative
to 1 kHz), the 1 % / 99 % cumulative-energy frequencies, crest factor, peak, quiet-frame noise floor.

Groups: radio lines with empty notes ("pilot-style"), radio lines with notes (the cryo assistant "eco"), control.
The filter estimate is (radio MCC - radio CE) - (control MCC - control CE) in the same language, which cancels
the recordings' own colour; the absolute shape is (radio MCC - control MCC). Stdlib only (a radix-2 FFT).
Writes work/reports/radio_survey.json; prints the tables.

    python scripts/discovery/radio_survey.py
"""
import argparse
import cmath
import glob
import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.audio_edit import wav_mono_float  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.ondemand_audio import AudioUnavailable, CeAudio, MccAudio, ce_source_reader, vgmstream_decoder  # noqa: E402

VGMSTREAM = "D:/Tools/vgmstream-r2117/vgmstream-cli.exe"
N = 2048
CENTERS = [63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150,
           4000, 5000, 6300, 8000, 10000, 12500, 16000]
SOURCES = ("mcc_es", "mcc_en", "ce_esmx", "ce_en")
WIN = [0.5 - 0.5 * math.cos(2 * math.pi * i / N) for i in range(N)]
TW = [cmath.exp(-2j * math.pi * k / N) for k in range(N // 2)]
BITREV = [int(format(i, f"0{N.bit_length() - 1}b")[::-1], 2) for i in range(N)]


def fft(x):
    a = [complex(x[BITREV[i]]) for i in range(N)]
    size = 2
    while size <= N:
        half, step = size // 2, N // size
        for start in range(0, N, size):
            for k in range(half):
                t = TW[k * step] * a[start + k + half]
                u = a[start + k]
                a[start + k], a[start + k + half] = u + t, u - t
        size *= 2
    return a


def db(p):
    return 10 * math.log10(max(p, 1e-20))


def analyze(path):
    x, sr = wav_mono_float(path)
    frames = [x[i:i + N] for i in range(0, max(1, len(x) - N), N // 2)]
    rms = [math.sqrt(sum(s * s for s in f) / N) + 1e-12 for f in frames]
    top = max(rms)
    active = [i for i, r in enumerate(rms) if 20 * math.log10(r / top) > -25]
    pick = active[:: max(1, len(active) // 30)][:30]
    quiet = sorted(range(len(rms)), key=lambda i: rms[i])

    acc = [0.0] * (N // 2)
    for i in pick:
        f = frames[i] + [0.0] * (N - len(frames[i]))
        X = fft([f[k] * WIN[k] for k in range(N)])
        for k in range(N // 2):
            acc[k] += abs(X[k]) ** 2
    spec = [a / max(1, len(pick)) for a in acc]
    bands = []
    for c in CENTERS:
        lo, hi = c / 2 ** (1 / 6), c * 2 ** (1 / 6)
        ks = [k for k in range(1, N // 2) if lo <= k * sr / N < hi]
        bands.append(db(sum(spec[k] for k in ks) / len(ks)) if ks and hi < sr / 2 else None)
    tot, c, lo_f, hi_f = sum(spec[1:]), 0.0, None, None
    for k in range(1, N // 2):
        c += spec[k]
        if lo_f is None and c >= 0.01 * tot:
            lo_f = k * sr / N
        if hi_f is None and c >= 0.99 * tot:
            hi_f = k * sr / N
    peak = max(abs(s) for s in x)
    act = math.sqrt(sum(rms[i] ** 2 for i in active) / len(active))
    return {"bands": bands, "roll_on_hz": lo_f, "rolloff99_hz": hi_f, "crest_db": 20 * math.log10(peak / act),
            "peak_db": 20 * math.log10(peak + 1e-12), "noise_floor_db": 20 * math.log10(rms[quiet[0]])}


def collect(root):
    decode = vgmstream_decoder(VGMSTREAM)
    mcc, ce = MccAudio(root, decode), CeAudio(root, decode, ce_source_reader())
    slots = json.loads((root / "mappings/manual_mappings.json").read_text(encoding="utf-8"))["slots"]
    mcc_by_slot, ce_by_ref = {}, {}
    for f in glob.glob(str(root / "work/mcc/catalog/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            for sid in r.get("slot_ids", []):
                mcc_by_slot[sid] = (Path(f).stem, r)
    for f in glob.glob(str(root / "work/ce/catalog/m*.jsonl")):
        for line in open(f, encoding="utf-8"):
            for e in json.loads(line).get("entries", []):
                ce_by_ref[e["ce_line_ref"]] = (Path(f).stem, e)

    def safe(fn, *a):
        try:
            return str(fn(*a))
        except AudioUnavailable as e:  # e.g. a silent sample: left out of the medians, reported
            print(f"unavailable {a[1]} {a[-1].get('name_in_bank', a[-1].get('media_id'))}: {e}", file=sys.stderr)
            return None

    def ce_wav(ref, lang):
        if ref not in ce_by_ref:
            return None
        m, e = ce_by_ref[ref]
        media = (e.get("media", {}).get(lang) or {}).get("media", [])
        return safe(ce.wav, m, lang, media[0]) if media else None

    radio = [s for s in slots if s["radio_effect"]["needed"]]
    pool = [s for s in slots if not s["radio_effect"]["needed"] and s["audio"]["status"] == "approved"
            and s["audio"]["source"] == "ce" and s["audio"]["sources"]
            and s["audio"]["sources"][0]["ce_line_ref"].startswith(("vo_scr", "vo_cin"))]
    control = pool[:: max(1, len(pool) // 60)][:60]
    rows = []
    for group, items in (("radio", radio), ("control", control)):
        for s in items:
            level, r = mcc_by_slot[s["slot_id"]]
            es = next(x for x in r["samples"]["spanish"] if x.get("slot_id") == s["slot_id"])
            en = r["samples"]["english"][:1]
            ref = (s["audio"]["sources"] or [{}])[0].get("ce_line_ref") or (s["match"]["ce_line_refs"] or [None])[0]
            g = group if group == "control" else ("radio_eco" if (s.get("notes") or "").strip() else "radio_pilot")
            rows.append({"group": g, "slot_id": s["slot_id"], "ce_line_ref": ref,
                         "mcc_es": safe(mcc.wav, level, "spanish", es),
                         "mcc_en": safe(mcc.wav, level, "english", en[0]) if en else None,
                         "ce_esmx": ce_wav(ref, "Spanish(Mexico)"), "ce_en": ce_wav(ref, "English(US)")})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    args = ap.parse_args()
    rows = collect(args.root)
    for i, r in enumerate(rows):
        for k in SOURCES:
            r[k + "_a"] = analyze(r[k]) if r[k] else None
        print(f"{i + 1}/{len(rows)} {r['slot_id']}", file=sys.stderr)

    def med(v):
        v = [x for x in v if x is not None]
        return st.median(v) if v else None

    prof, summary = {}, {}
    groups = ("radio_pilot", "radio_eco", "control")
    for g in groups:
        for k in SOURCES:
            a = [r[k + "_a"] for r in rows if r["group"] == g and r[k + "_a"]]
            rel = [[None if v is None else v - x["bands"][CENTERS.index(1000)] for v in x["bands"]] for x in a]
            prof[(g, k)] = [med([b[i] for b in rel]) for i in range(len(CENTERS))]
            summary[f"{g}/{k}"] = {"n": len(a), **{m: med([x[m] for x in a]) for m in
                                                   ("roll_on_hz", "rolloff99_hz", "crest_db", "peak_db", "noise_floor_db")}}
            print(f"{g:12s} {k:8s} " + " ".join(f"{m}={v:.1f}" if isinstance(v, float) else f"{m}={v}"
                                                 for m, v in summary[f"{g}/{k}"].items()))
    shape = {}
    for g in ("radio_pilot", "radio_eco"):
        for mk, ck in (("mcc_es", "ce_esmx"), ("mcc_en", "ce_en")):
            est = [None if None in v else (v[0] - v[1]) - (v[2] - v[3]) for v in
                   zip(prof[(g, mk)], prof[(g, ck)], prof[("control", mk)], prof[("control", ck)])]
            absolute = [None if None in v else v[0] - v[1] for v in zip(prof[(g, mk)], prof[("control", mk)])]
            shape[f"{g}/{mk}"] = {"vs_ce": est, "vs_control": absolute}
            print(f"\n{g} {mk} filter estimate vs CE / vs control (dB, 1 kHz = 0):")
            print("  " + " ".join(f"{c}:{e:+.0f}/{a:+.0f}" for c, e, a in zip(CENTERS, est, absolute)
                                  if e is not None and a is not None))
    out = args.root / "work" / "reports" / "radio_survey.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "radio-survey/1", "bands_hz": CENTERS, "summary": summary,
                               "filter_shape": shape, "rows": rows}, indent=1), encoding="utf-8")
    print(f"\nwrote {out.relative_to(args.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
