"""The radio key-up / key-down clicks of MCC's Spain radio lines (2026-10-13, docs/radio-filter.md §1.6).

Spain's pilot-style radio lines open with the same short click (about 16-40 ms into the sample) and end with the
same release + squelch (the last ~212 ms): a fixed sound spliced around the lines (35 of the 40 pilot-style Spain
originals open with it, correlation 0.80-1.00: `intro_similarity`). The recipe's `radio.clicks` puts them around a
CE replacement. They are taken from one retail MCC sample, the Spain recording of REFERENCE_SLOT in the pinned
bank copy (MccAudio verifies the bank against its pin), at fixed sample positions, and checked against PINNED:
nothing is synthesised and no audio is stored in the repo.

    click_in   samples [0, IN_END) of the reference: 16 ms lead-in, the click, 10 ms of the bed; 5 ms fade-out
    click_out  samples [n - OUT_LEN, n): from the quietest point before the release burst to the end; 2 ms fade-in

Both are 44.1 kHz mono floats, at the level they have in the game.
"""
import hashlib
import math

from . import audio_edit

REFERENCE_SLOT = "es:A30_220_bisenti#0"
SAMPLE_RATE = 44100
IN_END = 2205                    # 50.0 ms
OUT_LEN = 157696 - 148114        # 9582 samples = 217.3 ms (the reference sample has 157,696)
REFERENCE_SAMPLES = 157696
FADE_IN_END_MS = 5
FADE_OUT_START_MS = 2
# sha256 of each click's 16-bit PCM, from the pinned Spain bank (build 19905945), 2026-10-13
PINNED = {"in": "59c48068b5c1aa85aeef26e4d75a3db49ab933a1ad56c7f8c2f807c51793bdb8",
          "out": "8b60c92e55b755c51ba18193ebc622ba284f9ebd429751d85b0a2ed94267f79a"}


class ClickError(ValueError):
    pass


def _half_cos(i, n):
    return 0.5 - 0.5 * math.cos(math.pi * (i + 0.5) / n)


def cut(x):
    """Reference samples (floats) -> {"in": [...], "out": [...]} with the edge fades. Pure."""
    if len(x) != REFERENCE_SAMPLES:
        raise ClickError(f"the reference recording has {len(x)} samples, expected {REFERENCE_SAMPLES}")
    a = list(x[:IN_END])
    n = int(FADE_IN_END_MS * SAMPLE_RATE / 1000)
    for i in range(n):
        a[len(a) - 1 - i] *= _half_cos(i, n)
    b = list(x[len(x) - OUT_LEN:])
    n = int(FADE_OUT_START_MS * SAMPLE_RATE / 1000)
    for i in range(n):
        b[i] *= _half_cos(i, n)
    return {"in": a, "out": b}


def pcm_sha256(samples):
    return hashlib.sha256(audio_edit.float_to_pcm16(samples)).hexdigest()


def from_wav(path):
    """The clicks from the decoded reference recording, verified against PINNED.
    -> {"in", "out" (floats, quantised to 16 bits), "sha256": {in, out}, "reference"}."""
    x, sr = audio_edit.wav_mono_float(path)
    if sr != SAMPLE_RATE:
        raise ClickError(f"the reference recording is {sr} Hz, expected {SAMPLE_RATE}")
    c = cut(x)
    out = {"reference": {"slot_id": REFERENCE_SLOT, "in_samples": [0, IN_END],
                         "out_samples": [REFERENCE_SAMPLES - OUT_LEN, REFERENCE_SAMPLES]}, "sha256": {}}
    for k in ("in", "out"):
        pcm = audio_edit.float_to_pcm16(c[k])
        sha = hashlib.sha256(pcm).hexdigest()
        if sha != PINNED[k]:
            raise ClickError(f"the {k} click no longer matches its pin ({sha[:12]}… != {PINNED[k][:12]}…)")
        out["sha256"][k] = sha
        out[k] = audio_edit.pcm16_to_float(pcm)
    return out


def load(mcc_audio, slot_index):
    """The clicks via the on-demand MCC decoder. slot_index: {slot_id: (level, record, spanish sample)}."""
    if REFERENCE_SLOT not in slot_index:
        raise ClickError(f"{REFERENCE_SLOT} is not in the MCC catalog")
    level, _r, sample = slot_index[REFERENCE_SLOT]
    return from_wav(mcc_audio.wav(level, "spanish", sample))


ONSET_SEARCH_S = 0.1
SIMILAR = 0.75   # intro_similarity at or above this: the recording opens with the click


def intro_similarity(x, reference_in):
    """How closely a recording's opening matches the reference click (0..1): the best normalised correlation
    of the 35 ms after the recording's first sample above -40 dBFS (within its first 100 ms) with the
    reference click, over lags of +-40 samples. 0 when nothing starts in the first 100 ms."""
    def first(a, limit):
        return next((i for i, v in enumerate(a[:limit]) if abs(v) > 0.01), None)
    L = int(0.035 * SAMPLE_RATE)
    r0, o = first(reference_in, len(reference_in)), first(x, int(ONSET_SEARCH_S * SAMPLE_RATE))
    if r0 is None or o is None:
        return 0.0
    ref = reference_in[max(0, r0 - 50):max(0, r0 - 50) + L]
    er = math.sqrt(sum(v * v for v in ref)) or 1.0
    best = 0.0
    for lag in range(-40, 41):
        a = max(0, o - 50 + lag)
        w = x[a:a + len(ref)]
        if len(w) < len(ref):
            continue
        ew = math.sqrt(sum(v * v for v in w)) or 1.0
        best = max(best, sum(p * q for p, q in zip(ref, w)) / (er * ew))
    return round(best, 3)
