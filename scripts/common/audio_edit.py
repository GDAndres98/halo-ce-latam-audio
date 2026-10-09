"""Non-destructive dialogue edit recipes: the M4 editor's preview and the M6 build share this code.

A recipe lives in a mapping's `audio.edit` (manual-mappings/3, optional fields added 2026-10-09).
The identity recipe is the original `{"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0}` and is never
rendered: unedited lines keep the original pipeline byte for byte. A non-identity recipe:

    {"trim_start_s": 0.12, "trim_end_s": 0.30, "gap_s": 0,
     "engine": "audio-edit/1",
     "for_source": {"ce_line_ref": "...#0", "language": "Spanish(Mexico)"},
     "cuts": [{"start_s": 1.20, "end_s": 1.45}],      # interior sections removed (source seconds)
     "silences": [{"at_s": 0.80, "dur_s": 0.30}],     # silence inserted at a source time (exact length)
     "fade_in_ms": 10, "fade_out_ms": 10,             # half-cosine fades on the edited edges
     "crossfade_ms": 20,                              # equal-power crossfade at every cut
     "speed": 1.08,                                   # pitch-preserving tempo (rubberband via ffmpeg)
     "gain_db": -1.5,                                 # manual gain
     "loudness": {"mode": "match_mcc", "offset_db": 0}}  # auto gain to the original MCC recording

Times are seconds on the SOURCE recording's timeline (the editor's waveform), so a recipe never
depends on an earlier step. Render order, on the 44.1 kHz mono PCM the pipeline already produces:

    1. keep [trim_start, end - trim_end] minus the cuts; crossfade each junction
    2. fade in / fade out
    3. tempo (if speed != 1): ffmpeg rubberband, fixed speech settings, pitch and formants preserved
    3b. inserted silences, placed where their source time lands after steps 1-3, with short half-cosine
       fades on both sides (crossfade_ms / 2); inserted after the tempo so their length is exact.
       Digital silence (no room tone); BS.1770 gating ignores it, so loudness matching is unaffected.
    4. gain = manual + (match_mcc: MCC loudness + offset - edited loudness), both ITU-R BS.1770-4
       gated integrated loudness
    5. peaks: `limiter` true (default) -> look-ahead peak limiter at -1 dBFS (5 ms look-ahead, 80 ms
       release); with match_mcc the gain is re-measured after limiting (secant steps, up to 6 passes, ±0.05 LU) so the output
       lands on the target. `limiter` false -> the gain is lowered until the peak fits (reported).
       CE lines are ~7 dB quieter than the Spain recordings (a10 survey, 2026-10-09: 58/60 would not
       reach the target with gain alone), hence the limiter.
    6. round to 16-bit

Nothing here reads mappings, approves anything or writes files; ffmpeg is passed in. The radio
flag is separate (`radio_effect`) and no effect is ever applied here.
"""
import math
import subprocess
import sys
import wave
from array import array
from collections import deque

ENGINE = "audio-edit/1"
EDIT_ZERO = {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0}
SAMPLE_RATE = 44100
LOUDNESS_MODES = ("off", "match_mcc")
SILENCE_S = (0.01, 5.0)  # one inserted silence
LIMITS = {"speed": (0.5, 2.0), "gain_db": (-24.0, 24.0), "offset_db": (-12.0, 12.0),
          "fade_in_ms": (0, 500), "fade_out_ms": (0, 500), "crossfade_ms": (0, 200)}
DEFAULTS = {"cuts": [], "silences": [], "fade_in_ms": 0, "fade_out_ms": 0, "crossfade_ms": 20, "speed": 1.0, "gain_db": 0.0,
            "loudness": {"mode": "off", "offset_db": 0.0}, "limiter": True}
LIMITER = {"lookahead_ms": 5.0, "release_ms": 80.0}
MAX_MATCH_PASSES = 6
MIN_KEEP_S = 0.05          # the edited line must keep at least this much source audio
PEAK_CEILING_DB = -1.0     # headroom for the codec; also keeps M6's "no new clipping" check meaningful
RUBBERBAND = ("rubberband=tempo={tempo}:transients=mixed:detector=soft:window=standard:"
              "formant=preserved:pitchq=quality:channels=together")


class EditError(ValueError):
    pass


# --------------------------------------------------------------------------- recipe rules
def is_identity(edit):
    """True when the recipe changes nothing (gap_s only matters between concatenated lines)."""
    e = edit or {}
    lo = e.get("loudness") or {}
    return (not e.get("trim_start_s") and not e.get("trim_end_s") and not e.get("cuts") and not e.get("silences")
            and float(e.get("speed", 1.0)) == 1.0 and not e.get("gain_db")
            and lo.get("mode", "off") == "off" and not e.get("fade_in_ms") and not e.get("fade_out_ms"))


def _num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise EditError(f"{name} must be a number")
    return float(v)


def _r(x, nd):
    x = round(x, nd)
    return int(x) if x == int(x) else x


def normalize(edit, for_source=None):
    """Owner input -> canonical recipe (rounded, defaults filled, cuts sorted). Identity -> EDIT_ZERO.
    Raises EditError for anything malformed or out of range (duration checks: `problems`)."""
    e = dict(edit or {})
    unknown = set(e) - set(EDIT_ZERO) - set(DEFAULTS) - {"engine", "for_source"}
    if unknown:
        raise EditError(f"unknown edit field(s) {sorted(unknown)}")
    out = {"trim_start_s": _r(_num(e.get("trim_start_s", 0), "trim_start_s"), 3),
           "trim_end_s": _r(_num(e.get("trim_end_s", 0), "trim_end_s"), 3),
           "gap_s": _r(_num(e.get("gap_s", 0), "gap_s"), 3)}
    cuts = []
    for c in e.get("cuts") or []:
        if not isinstance(c, dict) or set(c) != {"start_s", "end_s"}:
            raise EditError("each cut is {start_s, end_s}")
        cuts.append({"start_s": _r(_num(c["start_s"], "cut start"), 3), "end_s": _r(_num(c["end_s"], "cut end"), 3)})
    cuts.sort(key=lambda c: (c["start_s"], c["end_s"]))
    silences = []
    for c in e.get("silences") or []:
        if not isinstance(c, dict) or set(c) != {"at_s", "dur_s"}:
            raise EditError("each inserted silence is {at_s, dur_s}")
        silences.append({"at_s": _r(_num(c["at_s"], "silence position"), 3),
                         "dur_s": _r(_num(c["dur_s"], "silence length"), 3)})
    silences.sort(key=lambda c: c["at_s"])
    lo = e.get("loudness") or DEFAULTS["loudness"]
    if not isinstance(lo, dict) or set(lo) - {"mode", "offset_db"}:
        raise EditError("loudness is {mode, offset_db}")
    if lo.get("mode", "off") not in LOUDNESS_MODES:
        raise EditError(f"loudness mode must be one of {LOUDNESS_MODES}")
    rec = {**out, "engine": ENGINE, "for_source": None, "cuts": cuts, "silences": silences,
           "fade_in_ms": _r(_num(e.get("fade_in_ms", 0), "fade_in_ms"), 0),
           "fade_out_ms": _r(_num(e.get("fade_out_ms", 0), "fade_out_ms"), 0),
           "crossfade_ms": _r(_num(e.get("crossfade_ms", DEFAULTS["crossfade_ms"]), "crossfade_ms"), 0),
           "speed": _r(_num(e.get("speed", 1.0), "speed"), 3),
           "gain_db": _r(_num(e.get("gain_db", 0), "gain_db"), 1),
           "loudness": {"mode": lo.get("mode", "off"), "offset_db": _r(_num(lo.get("offset_db", 0), "offset_db"), 1)},
           "limiter": e.get("limiter", True)}
    if not isinstance(rec["limiter"], bool):
        raise EditError("limiter must be true or false")
    if is_identity(rec):
        return dict(EDIT_ZERO, gap_s=out["gap_s"])
    fs = for_source or e.get("for_source")
    if not (isinstance(fs, dict) and isinstance(fs.get("ce_line_ref"), str) and isinstance(fs.get("language"), str)):
        raise EditError("an edit needs the source it was made for (for_source)")
    rec["for_source"] = {"ce_line_ref": fs["ce_line_ref"], "language": fs["language"]}
    bad = problems(rec)
    if bad:
        raise EditError("; ".join(bad))
    return rec


def problems(edit, duration_s=None):
    """Rule violations of a stored recipe (empty = fine). With duration_s, also checks the timeline."""
    e = edit or {}
    if is_identity(e):
        return []
    out = []
    if e.get("engine") != ENGINE:
        out.append(f"unknown edit engine {e.get('engine')!r} (expected {ENGINE})")
    if not isinstance(e.get("for_source"), dict):
        out.append("edit has no for_source")
    for k, (lo, hi) in LIMITS.items():
        v = (e.get("loudness") or {}).get(k) if k == "offset_db" else e.get(k, DEFAULTS.get(k))
        if v is not None and not lo <= v <= hi:
            out.append(f"{k} {v} outside {lo}..{hi}")
    ts, te = e.get("trim_start_s", 0), e.get("trim_end_s", 0)
    if ts < 0 or te < 0:
        out.append("trims must be >= 0")
    prev = ts
    for c in e.get("cuts") or []:
        if not c["start_s"] < c["end_s"]:
            out.append(f"cut {c['start_s']}-{c['end_s']} is empty or reversed")
        if c["start_s"] < prev:
            out.append(f"cut {c['start_s']}-{c['end_s']} overlaps the start trim or another cut")
        prev = max(prev, c["end_s"])
    last = None
    for c in e.get("silences") or []:
        if not SILENCE_S[0] <= c["dur_s"] <= SILENCE_S[1]:
            out.append(f"silence at {c['at_s']} s: length {c['dur_s']} outside {SILENCE_S[0]}..{SILENCE_S[1]} s")
        if c["at_s"] < ts:
            out.append(f"silence at {c['at_s']} s is inside the start trim")
        if any(k["start_s"] < c["at_s"] < k["end_s"] for k in e.get("cuts") or []):
            out.append(f"silence at {c['at_s']} s is inside a cut")
        if last is not None and c["at_s"] == last:
            out.append(f"two silences at {c['at_s']} s (merge them)")
        last = c["at_s"]
        if duration_s is not None and c["at_s"] > duration_s - te:
            out.append(f"silence at {c['at_s']} s is past the end trim")
    if duration_s is not None:
        end = duration_s - te
        if prev > end:
            out.append(f"cuts or trims reach past the end trim ({end:.3f} s)")
        kept = end - ts - sum(c["end_s"] - c["start_s"] for c in e.get("cuts") or [])
        if kept < MIN_KEEP_S:
            out.append(f"the edit keeps {max(kept, 0):.3f} s of audio (minimum {MIN_KEEP_S} s)")
    return out


def summary(edit):
    """Short human description, e.g. 'trim 0.12/0.30 s · 1 cut (0.25 s) · speed ×1.08 · match MCC'."""
    if is_identity(edit):
        return "no edits"
    e, bits = edit, []
    if e["trim_start_s"] or e["trim_end_s"]:
        bits.append(f"trim {e['trim_start_s']:.2f}/{e['trim_end_s']:.2f} s")
    if e["cuts"]:
        bits.append(f"{len(e['cuts'])} cut{'s' if len(e['cuts']) > 1 else ''} "
                    f"({sum(c['end_s'] - c['start_s'] for c in e['cuts']):.2f} s)")
    if e.get("silences"):
        bits.append(f"+{len(e['silences'])} silence{'s' if len(e['silences']) > 1 else ''} "
                    f"({sum(c['dur_s'] for c in e['silences']):.2f} s)")
    if e["speed"] != 1:
        bits.append(f"speed ×{e['speed']:g}")
    if e["loudness"]["mode"] == "match_mcc":
        bits.append("match MCC loudness" + (f" {e['loudness']['offset_db']:+g} dB" if e["loudness"]["offset_db"] else ""))
    if e["gain_db"]:
        bits.append(f"gain {e['gain_db']:+g} dB")
    if e["fade_in_ms"] or e["fade_out_ms"]:
        bits.append(f"fades {e['fade_in_ms']:g}/{e['fade_out_ms']:g} ms")
    if not e.get("limiter", True):
        bits.append("no limiter")
    return " · ".join(bits)


# --------------------------------------------------------------------------- PCM helpers
def pcm16_to_float(pcm):
    a = array("h", pcm)
    if sys.byteorder != "little":
        a.byteswap()
    return [v / 32768.0 for v in a]


def float_to_pcm16(x):
    a = array("h", [32767 if v >= 32767 else -32768 if v <= -32768 else v
                    for v in (int(round(s * 32768.0)) for s in x)])
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def wav_mono_float(path):
    """(samples in [-1, 1), sample_rate) of a 16-bit WAV; several channels are averaged."""
    with wave.open(str(path), "rb") as w:
        ch, sr, width = w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise EditError(f"{path}: {8 * width}-bit WAV not supported")
    x = pcm16_to_float(raw)
    if ch > 1:
        x = [sum(x[i:i + ch]) / ch for i in range(0, len(x) - ch + 1, ch)]
    return x, sr


def write_wav(path, pcm, rate=SAMPLE_RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


# --------------------------------------------------------------------------- loudness (ITU-R BS.1770-4)
def _biquads(fs):
    """K-weighting (high shelf + RLB high pass) for any rate: B. De Man's analog-prototype derivation,
    which reproduces the BS.1770-4 48 kHz coefficients (tests/test_audio_edit.py)."""
    def shelf(G, Q, fc):
        K, Vh = math.tan(math.pi * fc / fs), 10 ** (G / 20)
        Vb = Vh ** 0.4996667741545416
        return (Vh + Vb * K / Q + K * K, 2 * (K * K - Vh), Vh - Vb * K / Q + K * K), \
               (1 + K / Q + K * K, 2 * (K * K - 1), 1 - K / Q + K * K)

    def highpass(Q, fc):
        K = math.tan(math.pi * fc / fs)
        d = 1 + K / Q + K * K
        return (d, -2 * d, d), (d, 2 * (K * K - 1), 1 - K / Q + K * K)
    return [shelf(3.999843853973347, 0.7071752369554196, 1681.974450955533),
            highpass(0.5003270373238773, 38.13547087602444)]


def _kweighted_squares(x, fs):
    for b, a in _biquads(fs):
        b0, b1, b2 = (v / a[0] for v in b)
        a1, a2 = a[1] / a[0], a[2] / a[0]
        y, x1, x2, y1, y2 = [0.0] * len(x), 0.0, 0.0, 0.0, 0.0
        for i, v in enumerate(x):
            o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, v, y1, o
            y[i] = o
        x = y
    return [v * v for v in x]


def loudness(x, fs=SAMPLE_RATE):
    """-> (LUFS or None for silence, method). Gated integrated loudness (400 ms blocks, 75 % overlap,
    -70 LUFS absolute and -10 LU relative gates); clips shorter than one block use the ungated mean."""
    if not x:
        return None, "empty"
    z = _kweighted_squares(x, fs)
    to_lufs = lambda p: -0.691 + 10 * math.log10(p) if p > 0 else None  # noqa: E731
    n, step = int(round(0.4 * fs)), int(round(0.1 * fs))
    if len(z) < n:
        return to_lufs(sum(z) / len(z)), "ungated_short"
    pre = [0.0]
    for v in z:
        pre.append(pre[-1] + v)
    blocks = [(pre[s + n] - pre[s]) / n for s in range(0, len(z) - n + 1, step)]
    gated = [p for p in blocks if p > 0 and to_lufs(p) > -70]
    if not gated:
        return None, "silent"
    rel = to_lufs(sum(gated) / len(gated)) - 10
    final = [p for p in gated if to_lufs(p) > rel]
    return to_lufs(sum(final) / len(final)), "bs1770_gated"


def peak_db(x):
    p = max((abs(v) for v in x), default=0.0)
    return 20 * math.log10(p) if p > 0 else None


# --------------------------------------------------------------------------- render steps
def _half_cos(i, n):
    return 0.5 - 0.5 * math.cos(math.pi * (i + 0.5) / n)


def kept_segments(n, edit, fs=SAMPLE_RATE):
    """Sample ranges of the source that the recipe keeps, in order."""
    a, end = int(round(edit["trim_start_s"] * fs)), n - int(round(edit["trim_end_s"] * fs))
    segs = []
    for c in edit["cuts"]:
        s, e = int(round(c["start_s"] * fs)), int(round(c["end_s"] * fs))
        if s > a:
            segs.append((a, min(s, end)))
        a = max(a, e)
    if end > a:
        segs.append((a, end))
    return [(s, e) for s, e in segs if e > s]


def splice(x, segs, crossfade_samples):
    """Join the kept segments; each junction is an equal-power crossfade of the material around the cut
    (half before, half after), so exactly the cut length is removed."""
    out = list(x[segs[0][0]:segs[0][1]])
    for k in range(1, len(segs)):
        (s0, e0), (s1, e1) = segs[k - 1], segs[k]
        h = min(crossfade_samples // 2, (e0 - s0) // 2, (e1 - s1) // 2, len(x) - e0, s1)
        if h <= 0:
            out.extend(x[s1:e1])
            continue
        del out[len(out) - h:]
        L = 2 * h
        for i in range(L):
            t = (i + 0.5) / L
            out.append(x[e0 - h + i] * math.cos(t * math.pi / 2) + x[s1 - h + i] * math.sin(t * math.pi / 2))
        out.extend(x[s1 + h:e1])
    return out


def spliced_position(t, edit, fs=SAMPLE_RATE):
    """Sample index in the spliced signal (trims and cuts applied) of source time t (not inside a cut)."""
    pos = int(round(t * fs)) - int(round(edit["trim_start_s"] * fs))
    for c in edit["cuts"]:
        s, e = int(round(c["start_s"] * fs)), int(round(c["end_s"] * fs))
        if e <= int(round(t * fs)):
            pos -= e - s
    return max(0, pos)


def insert_silences(y, points, fade_samples):
    """points: [(sample index, length)] ascending. Fades out before / in after each, then zeros."""
    out, at = [], 0
    for p, n in points:
        p = min(max(p, at), len(y))
        piece = list(y[at:p])
        h = min(fade_samples, len(piece))
        for i in range(h):
            piece[len(piece) - 1 - i] *= _half_cos(i, h)
        out.extend(piece)
        out.extend([0.0] * n)
        at = p
        h = min(fade_samples, len(y) - p)
        for i in range(h):
            y[p + i] *= _half_cos(i, h)
    out.extend(y[at:])
    return out


def fade(x, fade_in, fade_out):
    n = len(x)
    fi, fo = min(fade_in, n // 2), min(fade_out, n // 2)
    for i in range(fi):
        x[i] *= _half_cos(i, fi)
    for i in range(fo):
        x[n - 1 - i] *= _half_cos(i, fo)
    return x


def tempo(x, speed, ffmpeg, fs=SAMPLE_RATE):
    """Pitch-preserving time stretch with ffmpeg's rubberband filter (deterministic; length n / speed)."""
    a = array("f", x)
    if sys.byteorder != "little":
        a.byteswap()
    args = [str(ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-f", "f32le", "-ar", str(fs), "-ac", "1",
            "-i", "-", "-af", RUBBERBAND.format(tempo=f"{speed:.6g}"), "-f", "f32le", "-"]
    res = subprocess.run(args, input=a.tobytes(), capture_output=True)
    if res.returncode != 0 or not res.stdout:
        raise EditError(f"ffmpeg rubberband failed: {res.stderr.decode(errors='replace')[:300]}")
    b = array("f")
    b.frombytes(res.stdout)
    if sys.byteorder != "little":
        b.byteswap()
    return list(b)


def tempo_filter(speed):
    return RUBBERBAND.format(tempo=f"{speed:.6g}")


def limit(x, ceiling, fs=SAMPLE_RATE, lookahead_ms=LIMITER["lookahead_ms"], release_ms=LIMITER["release_ms"]):
    """Look-ahead peak limiter -> (samples, max gain reduction dB). |output| <= ceiling for every sample:
    the gain at i is a mean of held minima that each cover sample i (sliding minimum over the next
    `lookahead` samples, exponential release, then a box filter over the previous `lookahead` samples)."""
    n, L = len(x), max(1, int(round(lookahead_ms * fs / 1000)))
    req = [ceiling / abs(v) if abs(v) > ceiling else 1.0 for v in x]
    if n == 0 or min(req) >= 1.0:
        return list(x), 0.0
    hold, dq = [1.0] * n, deque()
    for i in range(n - 1, -1, -1):  # hold[i] = min(req[i .. i+L])
        while dq and req[dq[-1]] >= req[i]:
            dq.pop()
        dq.append(i)
        while dq[0] > i + L:
            dq.popleft()
        hold[i] = req[dq[0]]
    a, g = math.exp(-1000.0 / (release_ms * fs)), 1.0
    for i in range(n):
        g = min(hold[i], 1.0 - (1.0 - g) * a)
        hold[i] = g
    out, acc, gmin = [0.0] * n, 0.0, 1.0
    for i in range(n):  # mean of hold[i-L .. i]; every term <= req[i]
        acc += hold[i]
        if i > L:
            acc -= hold[i - L - 1]
        gi = min(acc / min(i + 1, L + 1), req[i])  # min() only guards float rounding
        gmin = min(gmin, gi)
        out[i] = x[i] * gi
    return out, round(-20 * math.log10(gmin), 2)


def _gain(y, db, use_limiter, ceiling):
    g = 10 ** (db / 20)
    z = [v * g for v in y]
    return limit(z, ceiling) if use_limiter else (z, 0.0)


def render(pcm, edit, *, ffmpeg=None, ref_lufs=None, fs=SAMPLE_RATE):
    """44.1 kHz mono 16-bit PCM + recipe -> {"pcm": bytes, "stats": {...}}. Deterministic.
    ref_lufs: loudness of the original MCC recording (required when loudness.mode == match_mcc)."""
    if is_identity(edit):
        raise EditError("identity recipes are not rendered (the original pipeline is used)")
    x = pcm16_to_float(pcm)
    n = len(x)
    bad = problems(edit, n / fs)
    if bad:
        raise EditError("; ".join(bad))
    segs = kept_segments(n, edit, fs)
    y = splice(x, segs, int(round(edit["crossfade_ms"] * fs / 1000)))
    y = fade(y, int(round(edit["fade_in_ms"] * fs / 1000)), int(round(edit["fade_out_ms"] * fs / 1000)))
    spliced = len(y)
    if edit["speed"] != 1:
        if not ffmpeg:
            raise EditError("ffmpeg is needed for a speed change")
        y = tempo(y, edit["speed"], ffmpeg, fs)
    inserted = 0
    if edit.get("silences"):
        ratio = len(y) / spliced if spliced else 1.0
        pts = [(int(round(spliced_position(c["at_s"], edit, fs) * ratio)), int(round(c["dur_s"] * fs)))
               for c in edit["silences"]]
        inserted = sum(n for _, n in pts)
        y = insert_silences(list(y), pts, int(round(edit["crossfade_ms"] / 2 * fs / 1000)))
    measured, method = loudness(y, fs)
    auto = 0.0
    lo = edit["loudness"]
    if lo["mode"] == "match_mcc":
        if ref_lufs is None:
            raise EditError("loudness matching needs the original MCC recording's loudness")
        auto = (ref_lufs + lo["offset_db"] - measured) if measured is not None else 0.0
    want = auto + edit["gain_db"]
    ceiling = 10 ** (PEAK_CEILING_DB / 20)
    use_limiter = edit.get("limiter", True)
    pk = peak_db(y)
    passes = 0
    if use_limiter:
        applied = want
        z, reduction = _gain(y, applied, True, ceiling)
        passes = 1
        if lo["mode"] == "match_mcc" and measured is not None:
            target = ref_lufs + lo["offset_db"] + edit["gain_db"]
            prev = None
            for _ in range(MAX_MATCH_PASSES - 1):  # secant steps on gain -> output loudness
                cur = loudness(z, fs)[0]
                err = target - cur
                if abs(err) < 0.05:
                    break
                slope = (cur - prev[1]) / (applied - prev[0]) if prev and applied != prev[0] else 1.0
                prev = (applied, cur)
                step = err / slope if slope > 0.05 else err
                applied = min(applied + step, want + 12.0)  # never more than 12 dB past the plain-gain request
                if applied == prev[0]:
                    break
                z, reduction = _gain(y, applied, True, ceiling)
                passes += 1
    else:
        applied = want if pk is None else min(want, PEAK_CEILING_DB - pk)
        z, reduction = _gain(y, applied, False, ceiling)
    out = float_to_pcm16(z)
    final = pcm16_to_float(out)
    out_lufs = loudness(final, fs)[0]
    stats = {"engine": ENGINE, "source_samples": n, "source_s": round(n / fs, 3),
             "kept_segments_s": [[round(s / fs, 3), round(e / fs, 3)] for s, e in segs],
             "spliced_samples": spliced, "spliced_s": round(spliced / fs, 3),
             "inserted_silence_s": round(inserted / fs, 3),
             "output_samples": len(final), "output_s": round(len(final) / fs, 3),
             "speed": edit["speed"], "tempo_filter": tempo_filter(edit["speed"]) if edit["speed"] != 1 else None,
             "loudness_method": method, "loudness_before_gain_lufs": _rnd(measured),
             "mcc_reference_lufs": _rnd(ref_lufs), "auto_gain_db": round(auto, 2), "manual_gain_db": edit["gain_db"],
             "requested_gain_db": round(want, 2), "applied_gain_db": round(applied, 2),
             "limiter": use_limiter, "limiter_max_reduction_db": reduction, "loudness_passes": passes,
             "gain_lowered_for_peak_db": round(want - applied, 2) if not use_limiter and applied < want - 1e-9 else 0.0,
             "output_lufs": _rnd(out_lufs), "output_peak_dbfs": _rnd(peak_db(final)),
             "loudness_target_lufs": _rnd(ref_lufs + lo["offset_db"] + edit["gain_db"])
             if lo["mode"] == "match_mcc" and ref_lufs is not None else None}
    return {"pcm": out, "stats": stats}


def _rnd(v):
    return None if v is None else round(v, 2)


def wav_loudness(path):
    """Loudness (LUFS) of a decoded recording, e.g. the original MCC Spain sample (the match reference)."""
    return loudness(*wav_mono_float(path))[0]
