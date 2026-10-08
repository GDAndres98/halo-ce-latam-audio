"""Read-only FSB5 (FMOD Sample Bank) header/name-table parser.

No dependency on FMOD or any third-party FSB library. The structural
layout implemented here (fixed header, packed 64-bit per-sample
bitfields, frequency lookup table, optional name table) is a from-
scratch reimplementation based on the publicly documented format used
by the open-source HearthSim/python-fsb5 project.

This module only reads bytes already in memory; it never writes to,
modifies, or repacks any bank. See docs/feasibility.md for how it's
used (Stage 1 / Stage 2A of the Halo CE LATAM audio mod feasibility
work).
"""
import struct

FREQS = {1: 8000, 2: 11000, 3: 11025, 4: 16000, 5: 22050,
         6: 24000, 7: 32000, 8: 44100, 9: 48000}

MODES = {
    0: "NONE", 1: "PCM8", 2: "PCM16", 3: "PCM24", 4: "PCM32",
    5: "PCMFLOAT", 6: "GCADPCM", 7: "IMAADPCM", 8: "VAG", 9: "HEVAG",
    10: "XMA", 11: "MPEG", 12: "CELT", 13: "AT9", 14: "XWMA", 15: "VORBIS",
}


def bits(val, start, length):
    return (val >> start) & ((1 << length) - 1)


def parse_header(data):
    magic = data[0:4]
    if magic != b"FSB5":
        raise ValueError(f"not an FSB5 file (magic={magic!r})")
    version, num_samples, sample_headers_size, name_table_size, data_size, mode = \
        struct.unpack_from("<IIIIII", data, 4)
    off = 4 + 4 * 6
    if version == 0:
        off += 4  # extra 'unknown' field on version-0 files
    off += 8 + 16 + 8  # zero(8) + hash(16) + dummy(8)
    return {
        "version": version,
        "num_samples": num_samples,
        "sample_headers_size": sample_headers_size,
        "name_table_size": name_table_size,
        "data_size": data_size,
        "mode": mode,
        "mode_name": MODES.get(mode, f"UNKNOWN({mode})"),
        "base_header_size": off,
    }


def parse_sample_headers(data, header_off, sample_headers_size, num_samples):
    samples = []
    off = header_off
    end = header_off + sample_headers_size
    for i in range(num_samples):
        if off + 8 > end:
            break
        (val,) = struct.unpack_from("<Q", data, off)
        off += 8
        next_chunk = bits(val, 0, 1)
        freq_idx = bits(val, 1, 4)
        chan_flag = bits(val, 5, 1)
        data_offset = bits(val, 6, 28) * 16
        sample_count = bits(val, 34, 30)
        chunks = []
        while next_chunk:
            (cval,) = struct.unpack_from("<I", data, off)
            off += 4
            next_chunk = bits(cval, 0, 1)
            csize = bits(cval, 1, 24)
            ctype = bits(cval, 25, 7)
            chunks.append((ctype, csize))
            off += csize
        samples.append({
            "index": i,
            "frequency": FREQS.get(freq_idx, f"unknown_idx_{freq_idx}"),
            "channels": chan_flag + 1,
            "data_offset": data_offset,
            "sample_count": sample_count,
            "chunks": chunks,
        })
    return samples, off


def parse_name_table(data, nt_off, nt_size, num_samples):
    if nt_size == 0:
        return [None] * num_samples
    offsets = struct.unpack_from(f"<{num_samples}I", data, nt_off)
    names = []
    for o in offsets:
        start = nt_off + o
        end_pos = data.index(b"\x00", start)
        names.append(data[start:end_pos].decode("utf-8", errors="replace"))
    return names


class FsbBank:
    """Parsed, read-only view of one FSB5 file (loaded fully into memory)."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        self.header = parse_header(self.data)
        sh_off = self.header["base_header_size"]
        self.samples, _ = parse_sample_headers(
            self.data, sh_off, self.header["sample_headers_size"],
            self.header["num_samples"])
        nt_off = sh_off + self.header["sample_headers_size"]
        self.names = parse_name_table(
            self.data, nt_off, self.header["name_table_size"],
            self.header["num_samples"])
        self.data_start = nt_off + self.header["name_table_size"]
        self._by_name = {n.lower(): i for i, n in enumerate(self.names) if n}

    def find(self, name):
        """Return the 0-based sample index for an exact (case-insensitive) name match, or None."""
        return self._by_name.get(name.lower())

    def duration_seconds(self, index):
        s = self.samples[index]
        return s["sample_count"] / s["frequency"]
