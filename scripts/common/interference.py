"""Victor 933's damaged transmission: an interference ENVELOPE (2026-10-13, owner prompt 45;
docs/victor933-interference.md). A one-off for INTERFERENCE_LINES only, not a general effects system.

The recipe field `audio.edit.interference` (engine interference/2):

    {"engine": "interference/2",
     "points": [{"t": 0.0, "v": 0.35}, ...],     # the owner's curve: intensity 0..1 at source seconds
     "guides": [{"label", "kind": "partial"|"masked", "start_s", "end_s"}, ...],   # the 11 owner decisions
     "flutter_db": 2.5,                           # organic level wobble of the static (0..6 dB)
     "texture": "synthetic"}                      # the static: "synthetic" (made from scratch) or "mcc"

Times are on the SOURCE recording (before trims and cuts), so editing never moves the interference. The curve
is linear between points, sampled at CONTROL_RATE and smoothed forward AND backward (zero phase, no lag), then
mapped (nonlinear) to two gains, measured against the line's speech level:

    intensity   speech                                     static (re. speech level)
    0           untouched                                  silent
    0.35        untouched           (MCC's hiss bed)       -24 dB
    0.6         -5 dB               (low, understandable)  -20 dB
    0.85        -20 dB                                     -14 dB
    >= 0.95     removed             (spoiler hidden)       -9.3 dB  (MCC Spain: static vs voiced speech)

The static is ONE continuous stream for the whole line, from `texture`: "synthetic" (made from scratch, fitted to
MCC Spain's static: synthetic_texture) or "mcc" (absent = mcc: grains of MCC's own static, common/radio_static.py,
taken from seeded random positions, 160 ms sine-windowed, 50 % overlap, constant power, never a loop), with a
slow seeded flutter on its level. Deterministic; the line's length and pacing are unchanged.

guides only inform: they are drawn in the Studio, initialise the curve (`default_points`) and are reported
(`stats.guides`: whether a masked phrase is fully hidden, how far a partial one is ducked). They never change
the audio by themselves.
"""
import math
import random

LINES = ("vo_scr_m06_00740_victor933#0",)
ENGINE = "interference/2"
KINDS = ("partial", "masked")
TEXTURES = ("synthetic", "mcc")  # absent = "mcc" (the recipes from before the choice existed)
CONTROL_RATE = 1000           # curve samples per second
SMOOTH_MS = 3.0               # zero-phase smoothing of the curve (removes corners: no clicks, no lag)
MIN_SPACING_S = 0.002
LIMITS = {"points": 3000, "guides": 20, "label": 80, "flutter_db": (0, 6)}
SPEECH_FULL = 0.35            # at or below: speech untouched
PARTIAL_LEVEL = 0.6           # the default curve level over a "low but understandable" phrase
MASK_LEVEL = 0.95             # at or above: speech removed
BED_LEVEL = 0.35              # the quiet static between phrases (MCC's hiss bed)
STATIC_AT_MASK_DB = -9.3      # MCC Spain: static median -20.9 dB vs voiced speech -11.6 dB
GRAIN_S, GRAIN_MIN_JUMP_S = 0.16, 0.2
FLUTTER_HZ = 6.0
SEED = 933


class InterferenceError(ValueError):
    pass


# ----------------------------------------------------------------------------- mapping (shared with the Studio)
def speech_gain(i):
    """Linear gain of the speech at intensity i: 1 up to SPEECH_FULL, ducking quadratically (-5 dB at 0.6), then
    a smoothstep to exactly 0 between 0.85 and MASK_LEVEL."""
    if i <= SPEECH_FULL:
        return 1.0
    duck_db = 5.0 * ((i - SPEECH_FULL) / (PARTIAL_LEVEL - SPEECH_FULL)) ** 2
    g = 10 ** (-duck_db / 20)
    if i >= MASK_LEVEL:
        return 0.0
    if i > 0.85:
        u = (i - 0.85) / (MASK_LEVEL - 0.85)
        g *= 1 - u * u * (3 - 2 * u)
    return g


def static_db(i):
    """Static level re. the speech level at intensity i (concave: -24 dB at the bed, -9.3 dB at full); None = off."""
    if i <= 0:
        return None
    return STATIC_AT_MASK_DB - 14.7 * (max(0.0, 1 - min(i, 1.0)) / (1 - BED_LEVEL)) ** 0.6


def static_gain(i):
    d = static_db(i)
    if d is None:
        return 0.0
    g = 10 ** (d / 20)
    return g * (i / 0.1 if i < 0.1 else 1.0)  # fades to silence below 0.1


# ----------------------------------------------------------------------------- recipe rules
def _num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise InterferenceError(f"{name} must be a number")
    return float(v)


def _r(x, nd):
    x = round(x, nd)
    return int(x) if x == int(x) else x


def normalize(value, ce_line_ref):
    """Owner input -> canonical interference, or None. Only for LINES."""
    if value is None or value is False:
        return None
    if ce_line_ref not in LINES:
        raise InterferenceError("transmission interference exists only for Victor 933's damaged transmission "
                                f"({', '.join(LINES)})")
    if not isinstance(value, dict):
        raise InterferenceError("interference is {points, guides, flutter_db}")
    if value.get("engine") not in (None, ENGINE):
        raise InterferenceError(f"interference {value.get('engine')} is the old region format: run "
                                "scripts/validate/apply_victor933_interference.py --upgrade")
    unknown = set(value) - {"engine", "points", "guides", "flutter_db", "texture"}
    if unknown:
        raise InterferenceError(f"unknown interference field(s) {sorted(unknown)}")
    points = []
    for p in value.get("points") or []:
        if not isinstance(p, dict) or set(p) != {"t", "v"}:
            raise InterferenceError("each interference point is {t, v}")
        points.append({"t": _r(_num(p["t"], "point time"), 3), "v": _r(_num(p["v"], "point value"), 3)})
    points.sort(key=lambda p: p["t"])
    guides = []
    for g in value.get("guides") or []:
        if not isinstance(g, dict) or set(g) - {"label", "kind", "start_s", "end_s"} \
                or not {"kind", "start_s", "end_s"} <= set(g):
            raise InterferenceError("each guide is {label, kind, start_s, end_s}")
        guides.append({"label": str(g.get("label", "")).strip(), "kind": g["kind"],
                       "start_s": _r(_num(g["start_s"], "guide start"), 3), "end_s": _r(_num(g["end_s"], "guide end"), 3)})
    guides.sort(key=lambda g: g["start_s"])
    out = {"engine": ENGINE, "points": points, "guides": guides,
           "flutter_db": _r(_num(value.get("flutter_db", 2.5), "flutter_db"), 1),
           "texture": value.get("texture", "mcc")}
    bad = problems(out)
    if bad:
        raise InterferenceError("; ".join(bad))
    return out


def problems(value, duration_s=None):
    if not value:
        return []
    if value.get("engine") != ENGINE:
        return [f"interference {value.get('engine')!r} is the old region format: run "
                "scripts/validate/apply_victor933_interference.py --upgrade"]
    out = []
    pts = value.get("points") or []
    if len(pts) < 2:
        out.append("the interference curve needs at least 2 points")
    if len(pts) > LIMITS["points"]:
        out.append(f"at most {LIMITS['points']} interference points")
    for k, p in enumerate(pts):
        if not 0 <= p["v"] <= 1:
            out.append(f"point {k + 1}: intensity {p['v']} outside 0..1")
        if p["t"] < 0 or (duration_s is not None and p["t"] > duration_s + 0.001):
            out.append(f"point {k + 1}: {p['t']} s is outside the recording")
        if k and p["t"] - pts[k - 1]["t"] < MIN_SPACING_S - 1e-9:
            out.append(f"point {k + 1}: closer than {MIN_SPACING_S * 1000:g} ms to the point before it")
    guides = value.get("guides") or []
    if len(guides) > LIMITS["guides"]:
        out.append(f"at most {LIMITS['guides']} guides")
    prev = None
    for k, g in enumerate(guides, 1):
        if g.get("kind") not in KINDS:
            out.append(f"guide {k}: kind must be one of {', '.join(KINDS)}")
        if not 0 <= g["start_s"] < g["end_s"]:
            out.append(f"guide {k}: {g['start_s']}-{g['end_s']} s is empty or reversed")
        if len(g.get("label", "")) > LIMITS["label"]:
            out.append(f"guide {k}: label longer than {LIMITS['label']} characters")
        if prev is not None and g["start_s"] < prev:
            out.append(f"guide {k} overlaps the guide before it")
        prev = g["end_s"]
    if value.get("texture", "mcc") not in TEXTURES:
        out.append(f"texture must be one of {', '.join(TEXTURES)}")
    lo, hi = LIMITS["flutter_db"]
    if not lo <= value.get("flutter_db", 0) <= hi:
        out.append(f"flutter {value.get('flutter_db')} dB outside {lo}..{hi}")
    return out


def summary(value):
    m = sum(1 for g in value["guides"] if g["kind"] == "masked")
    tex = "synthetic static" if value.get("texture") == "synthetic" else "MCC static"
    return f"interference curve ({len(value['points'])} points; {len(value['guides'])} guides, {m} masked; {tex})"


def needs_mcc_static(value):
    """True when rendering needs MCC's static sample (common/radio_static.py)."""
    return bool(value) and value.get("texture", "mcc") == "mcc"


# ----------------------------------------------------------------------------- the default curve
def default_points(guides, duration_s, seed=SEED):
    """A natural starting curve from the owner's guides: a wobbling hiss bed, swells to PARTIAL_LEVEL over the
    partial phrases, and dropouts over the masked ones that build up before the phrase, hold at full
    intensity over all of it, and fade back after. Deterministic."""
    rng = random.Random(seed)
    pts = []

    def free(t):
        return all(not (g["start_s"] - 0.35 <= t <= g["end_s"] + 0.45) for g in guides)
    t = 0.0
    while t < duration_s:
        if free(t):
            pts.append((t, BED_LEVEL + rng.uniform(-0.08, 0.05)))
        t += 0.3
    for k, g in enumerate(guides):
        a, b = g["start_s"], g["end_s"]
        # a phrase's own edge points stay 5 ms clear of its neighbours (a plateau always covers its whole phrase);
        # the swell and fade points stay 50 ms clear (they never reach into a neighbouring phrase)
        prev_end = guides[k - 1]["end_s"] if k else None
        next_start = guides[k + 1]["start_s"] if k + 1 < len(guides) else None
        edge_lo = prev_end + 0.005 if prev_end is not None else 0.0
        edge_hi = next_start - 0.005 if next_start is not None else duration_s
        before = prev_end + 0.05 if prev_end is not None else 0.0
        after = next_start - 0.05 if next_start is not None else duration_s

        def add(tt, v, lo=before, hi=after):
            if lo <= tt <= hi:
                pts.append((tt, v))
        if g["kind"] == "masked":  # a short swell (speech barely touched), full over the phrase, a quick fade
            add(a - 0.2, 0.5 + rng.uniform(-0.03, 0.03))
            add(a - 0.08, 0.7 + rng.uniform(-0.03, 0.03))
            add(b + 0.1, 0.68 + rng.uniform(-0.03, 0.03))
            add(b + 0.28, BED_LEVEL + rng.uniform(0, 0.06))
        else:
            add(a - 0.16, BED_LEVEL + 0.04)
            pts.append((max(edge_lo, a - 0.03), PARTIAL_LEVEL + rng.uniform(-0.03, 0.03)))
            t = a + 0.18
            while t < b - 0.05:
                pts.append((t, PARTIAL_LEVEL + rng.uniform(-0.05, 0.05)))
                t += 0.18
            pts.append((min(edge_hi, b + 0.03), PARTIAL_LEVEL - 0.02))
            add(b + 0.22, BED_LEVEL + rng.uniform(0, 0.06))
    pts.append((0.0, pts[0][1] if pts else BED_LEVEL))
    pts.append((duration_s, BED_LEVEL))
    # masked phrases win: a full-intensity plateau 30 ms past both edges, and no other point inside it or within
    # 12 ms of it, so the smoothed curve stays at full intensity over the whole phrase whatever the layout
    plateaus = []
    for g in guides:
        if g["kind"] == "masked":
            pa, pb = max(0.0, g["start_s"] - 0.03), min(duration_s, g["end_s"] + 0.03)
            if plateaus and pa <= plateaus[-1][1] + 0.024:
                plateaus[-1] = (plateaus[-1][0], pb)  # close dropouts merge
            else:
                plateaus.append((pa, pb))
    pts = [(t, v) for t, v in pts if not any(pa - 0.012 < t < pb + 0.012 for pa, pb in plateaus)]
    for pa, pb in plateaus:
        pts += [(pa, 1.0), (pb, 1.0)]
    pts.sort()
    out = []
    for t, v in pts:
        t = round(min(max(t, 0.0), duration_s), 3)
        if out and t - out[-1]["t"] < 0.01:
            if v > out[-1]["v"]:  # keep the stronger of two near points (a dropout edge wins)
                out[-1]["v"] = round(v, 3)
            continue
        out.append({"t": t, "v": round(min(max(v, 0.0), 1.0), 3)})
    return out


# ----------------------------------------------------------------------------- rendering
def control_curve(points, n):
    """The curve at CONTROL_RATE for n control frames: linear between points, then smoothed with a one-pole
    filter run forward and backward (zero phase)."""
    c = [0.0] * n
    j = 0
    for k in range(n):
        t = k / CONTROL_RATE
        while j + 1 < len(points) and points[j + 1]["t"] <= t:
            j += 1
        p = points[j]
        if t <= points[0]["t"]:
            c[k] = points[0]["v"]
        elif j + 1 >= len(points):
            c[k] = p["v"]
        else:
            q = points[j + 1]
            c[k] = p["v"] + (q["v"] - p["v"]) * (t - p["t"]) / (q["t"] - p["t"])
    a = math.exp(-1000.0 / (SMOOTH_MS * CONTROL_RATE))
    for rng_ in (range(n), range(n - 1, -1, -1)):
        s = None
        for k in rng_:
            s = c[k] if s is None else a * s + (1 - a) * c[k]
            c[k] = s
    return c


def texture(static, n, fs, seed=SEED):
    """n samples of continuous static: sine-windowed grains (GRAIN_S, 50 % overlap) from seeded random
    positions of MCC's static, normalised to unit RMS. Never loops: consecutive grains jump >= GRAIN_MIN_JUMP_S."""
    rng = random.Random(seed)
    L = len(static)
    G = min(int(GRAIN_S * fs), L)
    H = G // 2
    win = [math.sin(math.pi * (i + 0.5) / G) for i in range(G)]
    out = [0.0] * (n + G)
    prev = None
    for start in range(0, n + H, H):
        while True:
            pos = rng.randrange(0, max(1, L - G))
            if prev is None or abs(pos - prev) >= GRAIN_MIN_JUMP_S * fs or L - G < GRAIN_MIN_JUMP_S * fs * 2:
                break
        prev = pos
        for i in range(G):
            if start + i < len(out):
                out[start + i] += static[pos + i] * win[i]
    out = out[:n]
    rms = math.sqrt(sum(v * v for v in out) / max(1, n)) or 1.0
    return [v / rms for v in out]


def flutter(n_ctrl, seed=SEED):
    """Slow organic level variation (unit std) at CONTROL_RATE: seeded white noise, two one-pole low-passes."""
    rng = random.Random(seed + 1)
    a = math.exp(-2 * math.pi * FLUTTER_HZ / CONTROL_RATE)
    y1 = y2 = 0.0
    out = []
    for _ in range(n_ctrl):
        y1 = a * y1 + (1 - a) * rng.gauss(0, 1)
        y2 = a * y2 + (1 - a) * y1
        out.append(y2)
    sd = math.sqrt(sum(v * v for v in out) / max(1, len(out))) or 1.0
    return [v / sd for v in out]


def speech_rms(x, fs):
    """Median RMS of the line's active 20 ms frames (within 20 dB of its 95th-percentile frame)."""
    n = max(1, int(0.02 * fs))
    rms = [math.sqrt(sum(v * v for v in x[i:i + n]) / n) for i in range(0, len(x) - n + 1, n)]
    rms = [r for r in rms if r > 0]
    if not rms:
        return 0.0
    top = sorted(rms)[int(0.95 * (len(rms) - 1))]
    active = sorted(r for r in rms if r >= top * 0.1)
    return active[len(active) // 2]


def apply(x, value, static, fs):
    """Interference on the SOURCE samples -> (samples, stats). Same length, deterministic."""
    synthetic = value.get("texture", "mcc") == "synthetic"
    if not synthetic and not static:
        raise InterferenceError("the transmission interference needs MCC's static (common/radio_static.py); "
                                "it could not be decoded")
    n = len(x)
    n_ctrl = int(n / fs * CONTROL_RATE) + 2
    curve = control_curve(value["points"], n_ctrl)
    fl = flutter(n_ctrl)
    s_ref = speech_rms(x, fs)
    gs = [speech_gain(c) for c in curve]
    gn = [s_ref * static_gain(c) * 10 ** (value["flutter_db"] * f / 20) for c, f in zip(curve, fl)]
    tex = synthetic_texture(n, fs) if synthetic else texture(static["static"], n, fs)
    y = [0.0] * n
    step = CONTROL_RATE / fs
    for i in range(n):
        p = i * step
        k = int(p)
        u = p - k
        g1 = gs[k] + (gs[k + 1] - gs[k]) * u
        g2 = gn[k] + (gn[k + 1] - gn[k]) * u
        y[i] = x[i] * g1 + tex[i] * g2
    guides = []
    for g in value["guides"]:
        a, b = int(g["start_s"] * CONTROL_RATE), max(int(g["start_s"] * CONTROL_RATE) + 1, int(g["end_s"] * CONTROL_RATE))
        seg = curve[a:b] or [0.0]
        gmax = max(gs[a:b] or [1.0])
        guides.append({"label": g["label"], "kind": g["kind"], "min_intensity": round(min(seg), 3),
                       "mean_intensity": round(sum(seg) / len(seg), 3),
                       "max_speech_gain_db": None if gmax == 0 else round(20 * math.log10(gmax), 1),
                       "hidden": gmax == 0})
    return y, {"engine": ENGINE, "points": len(value["points"]), "guides": guides,
               "masked_hidden": all(g["hidden"] for g in guides if g["kind"] == "masked"),
               "speech_reference_dbfs": round(20 * math.log10(s_ref), 2) if s_ref > 0 else None,
               "texture": "synthetic" if synthetic else "mcc",
               "static_sha256": None if synthetic else static["sha256"],
               "static_reference": None if synthetic else static["reference"]["slot_id"]}


# ----------------------------------------------------------------------------- MCC reference (Studio overlay only)
def intensity_for_static_db(rel_db):
    """Inverse of static_db: the intensity whose static sits rel_db under the speech level."""
    if rel_db >= STATIC_AT_MASK_DB:
        return 1.0
    u = (STATIC_AT_MASK_DB - rel_db) / 14.7
    return max(0.0, 1 - (1 - BED_LEVEL) * u ** (1 / 0.6))


def reference_curve(x, fs, frame_s=0.02):
    """An estimate of the interference in an MCC original, on the curve's 0..1 scale, every frame_s seconds.
    Per frame (11 kHz): level and voicing (best normalised autocorrelation, 2.5-12.5 ms lag). Noise-like frames
    (voicing <= 0.3) map back from their level re. the voiced speech through static_db; voiced frames (speech on
    top) count as light interference at most (0.45); in between, a blend. Smoothed over 3 frames. A visual
    reference only: it never changes the owner's curve."""
    f = max(1, round(fs / 11025))
    y = [sum(x[i:i + f]) / f for i in range(0, len(x) - f + 1, f)]
    sr = fs / f
    n = int(frame_s * sr)
    lo, hi = int(0.0025 * sr), int(0.0125 * sr)
    lv, vo = [], []
    for i in range(0, len(y) - n - hi, n):
        a = y[i:i + n]
        e0 = sum(v * v for v in a)
        lv.append(10 * math.log10(e0 / n + 1e-20))
        best = 0.0
        if e0 > 0:
            for k in range(lo, hi, 2):
                b = y[i + k:i + k + n]
                best = max(best, sum(p * q for p, q in zip(a, b)) / math.sqrt(e0 * (sum(q * q for q in b) or 1e-20)))
        vo.append(best)
    voiced = sorted(level for level, v in zip(lv, vo) if v > 0.6 and level > -30)
    ref = voiced[len(voiced) // 2] if voiced else max(lv)
    raw = []
    for level, v in zip(lv, vo):
        noise = min(1.0, max(0.0, (0.6 - v) / 0.3))
        i_noise = intensity_for_static_db(level - ref)
        raw.append(noise * i_noise + (1 - noise) * min(i_noise, 0.45))
    sm = [sum(raw[max(0, k - 1):k + 2]) / len(raw[max(0, k - 1):k + 2]) for k in range(len(raw))]
    return {"frame_s": frame_s, "values": [round(v, 3) for v in sm], "duration_s": round(len(x) / fs, 3),
            "speech_level_dbfs": round(ref, 1)}


# ----------------------------------------------------------------------------- synthetic static (texture "synthetic")
# Static made from scratch (owner request, 2026-10-13), shaped to MCC Spain's static (measured on the pinned
# 4.40-5.80 s burst): band-limited about 300-4000 Hz with humps at ~500 Hz (+7 dB) and ~2 kHz (+8.5 dB), near-
# Gaussian (kurtosis 3.3, crest 13.8 dB), ~2 dB level variation over 5 ms frames, ~1 dB over 50 ms.
SYNTH = {"hp_hz": 320, "hp_order": 4, "lp_hz": 3600, "lp_order": 4, "peaks": ((500, 9.0, 2.0), (2000, 11.0, 1.8)),
         "crackle_per_s": 40, "crackle_db": -10.0, "flicker_db": 1.5, "flicker_hz": 30.0,
         "flicker_slow_db": 0.6, "flicker_slow_hz": 5.0}
# Fit (docs/victor933-interference.md §3.3): 1/3-octave spectrum within 2.9 dB rms of MCC's static (125 Hz-8 kHz); level
# std over 5 ms frames 1.91 dB (MCC 2.07), over 50 ms 0.99 dB (0.95); kurtosis 3.44 (3.28); crest 13.1 dB (13.8).


def _butter_qs(order):
    return [1 / (2 * math.cos((2 * k - 1) * math.pi / (2 * order))) for k in range(1, order // 2 + 1)]


def _biquad(x, b, a):
    b0, b1, b2 = (v / a[0] for v in b)
    a1, a2 = a[1] / a[0], a[2] / a[0]
    y, x1, x2, y1, y2 = [0.0] * len(x), 0.0, 0.0, 0.0, 0.0
    for i, v in enumerate(x):
        o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y[i] = o
    return y


def _rbj(kind, f0, fs, q=0.7071, gain_db=0.0):
    w = 2 * math.pi * f0 / fs
    cw, al = math.cos(w), math.sin(w) / (2 * q)
    if kind == "hp":
        return ((1 + cw) / 2, -(1 + cw), (1 + cw) / 2), (1 + al, -2 * cw, 1 - al)
    if kind == "lp":
        return ((1 - cw) / 2, 1 - cw, (1 - cw) / 2), (1 + al, -2 * cw, 1 - al)
    A = 10 ** (gain_db / 40)
    return (1 + al * A, -2 * cw, 1 - al * A), (1 + al / A, -2 * cw, 1 - al / A)


def synthetic_texture(n, fs, seed=SEED):
    """n samples of static made from scratch, unit RMS, deterministic: seeded white noise plus sparse crackle
    (decaying 1-4 ms pops), a random flicker, then Butterworth high- and low-pass filters and the two humps of
    SYNTH (fitted to MCC Spain's static: tests/test_audio_edit.py and docs/victor933-interference.md §3.3)."""
    rng = random.Random(seed + 7)
    x = [rng.gauss(0.0, 1.0) for _ in range(n)]
    pops = int(SYNTH["crackle_per_s"] * n / fs)
    amp = 10 ** (SYNTH["crackle_db"] / 20)
    for _ in range(pops):
        at, length = rng.randrange(0, max(1, n)), int(rng.uniform(0.001, 0.004) * fs)
        g = amp * math.exp(rng.gauss(0.0, 0.6)) * 3.0
        for i in range(length):
            if at + i < n:
                x[at + i] += g * rng.gauss(0.0, 1.0) * math.exp(-4.0 * i / max(1, length))
    mods = []  # level flicker in dB: a fast (crackle-scale) and a slow component, each unit std
    for hz in (SYNTH["flicker_hz"], SYNTH["flicker_slow_hz"]):
        a = math.exp(-2 * math.pi * hz / fs)
        y1 = y2 = 0.0
        m = []
        for _ in range(n):
            y1 = a * y1 + (1 - a) * rng.gauss(0.0, 1.0)
            y2 = a * y2 + (1 - a) * y1
            m.append(y2)
        sd = math.sqrt(sum(v * v for v in m) / max(1, n)) or 1.0
        mods.append([v / sd for v in m])
    for i in range(n):
        x[i] *= 10 ** ((SYNTH["flicker_db"] * mods[0][i] + SYNTH["flicker_slow_db"] * mods[1][i]) / 20)
    for q in _butter_qs(SYNTH["hp_order"]):
        x = _biquad(x, *_rbj("hp", SYNTH["hp_hz"], fs, q))
    for q in _butter_qs(SYNTH["lp_order"]):
        x = _biquad(x, *_rbj("lp", SYNTH["lp_hz"], fs, q))
    for f0, gain, q in SYNTH["peaks"]:
        x = _biquad(x, *_rbj("peak", f0, fs, q, gain))
    rms = math.sqrt(sum(v * v for v in x) / max(1, n)) or 1.0
    return [v / rms for v in x]
