"""MCC's radio static, for Victor 933's damaged transmission (2026-10-13, docs/victor933-interference.md).

The MCC original of that line (Spain recording of REFERENCE_SLOT, the same slot the CE line replaces) has static
bursts that replace words; its longest, 4.40-5.80 s, is pure static (voicing 0.26-0.28, no speech under it).
That stretch is the texture the recipe's `interference` uses. It is cut from the pinned bank copy at fixed
sample positions and checked against PINNED, like the radio clicks (common/radio_clicks.py): nothing is
synthesised and no audio is stored in the repo.

    static   samples [START, END) of the reference, 44.1 kHz mono floats at the level they have in the game
"""
import hashlib

from . import audio_edit

REFERENCE_SLOT = "es:c10_010_captpilot#0"
SAMPLE_RATE = 44100
REFERENCE_SAMPLES = 1253888
START, END = 194040, 255780      # 4.40-5.80 s
# sha256 of the static's 16-bit PCM, from the pinned Spain bank (build 19905945), 2026-10-13
PINNED = "7677792fb2fd9fd9077f3001c18a8295566466c2c42795fb4b9e2d8af623f35b"


class StaticError(ValueError):
    pass


def from_wav(path):
    """The static from the decoded reference recording, verified against PINNED.
    -> {"static": floats (quantised to 16 bits), "sha256", "reference"}."""
    x, sr = audio_edit.wav_mono_float(path)
    if sr != SAMPLE_RATE or len(x) != REFERENCE_SAMPLES:
        raise StaticError(f"the reference recording is {len(x)} samples at {sr} Hz, expected "
                          f"{REFERENCE_SAMPLES} at {SAMPLE_RATE}")
    pcm = audio_edit.float_to_pcm16(x[START:END])
    sha = hashlib.sha256(pcm).hexdigest()
    if sha != PINNED:
        raise StaticError(f"the static no longer matches its pin ({sha[:12]}… != {PINNED[:12]}…)")
    return {"static": audio_edit.pcm16_to_float(pcm), "sha256": sha,
            "reference": {"slot_id": REFERENCE_SLOT, "samples": [START, END]}}


def load(mcc_audio, slot_index):
    """The static via the on-demand MCC decoder. slot_index: {slot_id: (level, record, spanish sample)}."""
    if REFERENCE_SLOT not in slot_index:
        raise StaticError(f"{REFERENCE_SLOT} is not in the MCC catalog")
    level, _r, sample = slot_index[REFERENCE_SLOT]
    return from_wav(mcc_audio.wav(level, "spanish", sample))
