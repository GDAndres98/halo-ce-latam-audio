"""Same recording? Compares two decoded WAVs by their sound, ignoring loudness (stdlib only; docs/suggested-matching.md).

Built for barks (owner, 2026-10-23): many Campaign Evolved English variations are MCC's English takes again, sometimes
quieter or slightly different. Neither side has text, so the sound itself is compared.

Features, one frame per 20 ms, after the leading and trailing silence are cut (frames 45 dB under the loudest):
- level:  frame energy in dB, minus the clip's mean (so a gain change cancels out);
- tilt:   energy of the first difference minus the frame energy (how bright the frame is; gain-free);
- zcr:    zero-crossing rate (gain-free).
Each is z-scored over the clip. Two clips compare by the mean of the three correlations at the best small offset
(+-60 ms; the silence cut already lines up the onsets), times overlap / longer length, so a shorter clip that only
covers part of a longer one scores lower. Clips whose lengths differ by more than LENGTH_RATIO are not compared.
"""
import array
import math
import operator
import wave

FRAME_S = 0.02
SILENCE_DB = 45.0
MAX_LAG = 3            # frames (60 ms)
LENGTH_RATIO = 0.6     # shorter / longer below this: not the same recording
WEIGHTS = (0.5, 0.3, 0.2)  # level, tilt, zcr
METHOD = ("audio-match/1: 20 ms frames, silence cut at -45 dB; correlation of level (gain removed), spectral tilt and "
          "zero-crossing rate at the best +-60 ms offset, x overlap; lengths within 0.6x")


def read_mono(path):
    """-> (samples as a list of floats in -1..1, rate). 16-bit PCM (what vgmstream writes); channels averaged."""
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError(f"{path}: {8 * width}-bit WAV (16-bit expected)")
    a = array.array("h")
    a.frombytes(raw)
    if ch == 1:
        return [x / 32768.0 for x in a], rate
    return [sum(a[i:i + ch]) / (32768.0 * ch) for i in range(0, len(a), ch)], rate


def _z(v):
    if not v:
        return []
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
    return [(x - m) / sd for x in v] if sd > 1e-9 else [0.0] * len(v)


def features(path):
    """-> {duration_s, frames, mean_db, level, tilt, zcr} (lists z-scored), or frames 0 for a silent clip."""
    x, rate = read_mono(path)
    hop = max(1, int(rate * FRAME_S))
    e_db, d_db, zc = [], [], []
    for i in range(0, len(x) - hop + 1, hop):
        f = x[i:i + hop]
        e = sum(map(operator.mul, f, f)) / hop
        d = [b - a for a, b in zip(f, f[1:])]
        h = sum(map(operator.mul, d, d)) / max(1, len(d))
        e_db.append(10 * math.log10(e + 1e-12))
        d_db.append(10 * math.log10(h + 1e-12))
        zc.append(sum(1 for a, b in zip(f, f[1:]) if (a < 0) != (b < 0)) / hop)
    out = {"duration_s": round(len(x) / rate, 3), "frames": 0, "mean_db": None, "level": [], "tilt": [], "zcr": []}
    if not e_db:
        return out
    floor = max(e_db) - SILENCE_DB
    voiced = [i for i, e in enumerate(e_db) if e >= floor]
    if not voiced or max(e_db) < -80:
        return out
    a, b = voiced[0], voiced[-1] + 1
    e_db, d_db, zc = e_db[a:b], d_db[a:b], zc[a:b]
    mean = sum(e_db) / len(e_db)
    out.update(frames=len(e_db), mean_db=round(mean, 2), level=_z(e_db),
               tilt=_z([d - e for d, e in zip(d_db, e_db)]), zcr=_z(zc))
    return out


def _corr_at(u, v, lag):
    """Mean product of z-scored u[i] and v[i + lag] over the overlap (~ Pearson correlation)."""
    i0, i1 = max(0, -lag), min(len(u), len(v) - lag)
    n = i1 - i0
    if n <= 0:
        return 0.0, 0
    return sum(map(operator.mul, u[i0:i1], v[i0 + lag:i1 + lag])) / n, n


def compare(fa, fb):
    """-> (score 0..1, lag in frames, gain_db = how much louder b is than a). 0 when not comparable."""
    la, lb = fa["frames"], fb["frames"]
    if not la or not lb or min(la, lb) / max(la, lb) < LENGTH_RATIO:
        return 0.0, 0, None
    best = (0.0, 0)
    for lag in range(-MAX_LAG, MAX_LAG + 1):
        parts = [_corr_at(fa[k], fb[k], lag) for k in ("level", "tilt", "zcr")]
        n = parts[0][1]
        if n < 5:
            continue
        s = sum(w * max(0.0, c) for w, (c, _n) in zip(WEIGHTS, parts)) * n / max(la, lb)
        if s > best[0]:
            best = (s, lag)
    return round(best[0], 4), best[1], round(fb["mean_db"] - fa["mean_db"], 1)
