"""Waveform peaks of a PCM WAV, for drawing it without downloading and decoding the whole file first.

peaks(path, per_second) -> {"duration", "sample_rate", "channels", "peaks": [0..1, ...]}: the largest
absolute sample of each bucket, all channels together, rounded to 3 decimals. The browser draws these
straight away and streams the audio itself with range requests.
"""
import array
import sys
import threading
import wave
from collections import OrderedDict
from pathlib import Path

MAX_PEAKS = 16000


def compute(path, per_second=400):
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV is supported")
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
        samples = array.array("h")
        samples.frombytes(w.readframes(frames))
    if sys.byteorder == "big":
        samples.byteswap()
    duration = frames / rate if rate else 0.0
    n = max(1, min(MAX_PEAKS, int(duration * per_second) or 1))
    total = len(samples)
    step = total / n if total else 1
    out = []
    for i in range(n):
        a, b = int(i * step), int((i + 1) * step)
        if b <= a:
            b = a + 1
        chunk = samples[a:b]
        out.append(round(max(max(chunk), -min(chunk)) / 32768, 3) if chunk else 0.0)
    return {"duration": round(duration, 6), "sample_rate": rate, "channels": channels, "peaks": out}


class PeakCache:
    """Peaks per (file, size, mtime): a file rewritten in place gets new peaks."""

    def __init__(self, size=256):
        self.size = size
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path, per_second=400):
        st = Path(path).stat()
        key = (str(path), st.st_size, st.st_mtime_ns, per_second)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        value = compute(path, per_second)
        with self._lock:
            self._items[key] = value
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return value
