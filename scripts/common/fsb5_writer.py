"""FSB5 bank model + writer (B2 experiment E0). Pure functions on bytes; no file I/O.

`decompose(data)` turns an FSB5 file into an explicit model; `build(model)` serialises it
again. For the MCC Halo CE banks `build(decompose(data)) == data` must hold byte for byte
(docs/b2-audio-research.md, E0). Layout as read by common/fsb5_lib.py (verified in Stage 1)
and vgmstream's fsb5.c:

    0x00 "FSB5", u32 version, u32 num_samples, u32 sample_headers_size,
         u32 name_table_size, u32 data_size, u32 mode, then raw tail to the base header end
         (v1: 0x1C..0x3C = flags/CELT-bitstream id, hash, unknown) -> kept verbatim
    sample headers: u64 per sample (bit 0 chunk flag, bits 1-5 freq index + channel flag,
         bits 6-33 data offset / 16, bits 34-63 sample count), then chunks
         u32 (bit 0 more, bits 1-24 size, bits 25-31 type) + payload, kept verbatim
    name table: u32 offsets (relative to table start) + NUL-terminated names, zero padding
         so the data section starts 32-byte aligned
    data: one stream per sample in header order, each zero-padded to a 32-byte boundary

Recomputed on build: the four size fields, every data offset, chunk `more` bits, name
offsets and padding. Everything else (header tail, sample-header bits 1-5, sample counts,
chunk payloads incl. unknown types, name bytes, stream bytes) is carried verbatim.
Offsets must stay 32-byte aligned so fsb5_lib's (x16, 28-bit) and vgmstream's (x32, 27-bit)
readings agree.
"""
import struct

from .fsb5_lib import bits, parse_header

ALIGN = 32
CELT_MODE = 12
CELT_SYNC = b"\x17\xc3\x0d\xf3"
CELT_FRAME_SAMPLES = 512
KEEP_BITS = 0b111110  # bits 1-5 of the sample header: frequency index and channel flag


def _align(n, a=ALIGN):
    return (n + a - 1) // a * a


def celt_stream_length(span, sample_count):
    """Bytes of real CELT frames at the start of `span` (sync + u32 size + packet per frame)."""
    p, frames = 0, 0
    while p + 8 <= len(span) and span[p:p + 4] == CELT_SYNC:
        p += 8 + struct.unpack_from("<I", span, p + 4)[0]
        frames += 1
    if p > len(span):
        raise ValueError("CELT frame runs past the sample's data span")
    expected = -(-sample_count // CELT_FRAME_SAMPLES)
    if frames != expected:
        raise ValueError(f"{frames} CELT frames, expected {expected} for {sample_count} samples")
    return p


def decompose(data):
    """FSB5 bytes -> model dict. Raises ValueError on anything the writer could not reproduce."""
    h = parse_header(data)
    base = h["base_header_size"]
    n = h["num_samples"]
    if len(data) != base + h["sample_headers_size"] + h["name_table_size"] + h["data_size"]:
        raise ValueError("file size != header + sample headers + name table + data")

    off, samples = base, []
    for _ in range(n):
        (v,) = struct.unpack_from("<Q", data, off)
        off += 8
        more, chunks = bits(v, 0, 1), []
        while more:
            (c,) = struct.unpack_from("<I", data, off)
            off += 4
            more, size, ctype = bits(c, 0, 1), bits(c, 1, 24), bits(c, 25, 7)
            chunks.append((ctype, bytes(data[off:off + size])))
            off += size
        samples.append({"head_bits": v & KEEP_BITS, "data_offset": bits(v, 6, 28) * 16,
                        "sample_count": bits(v, 34, 30), "channels": bits(v, 5, 1) + 1, "chunks": chunks})
    if off != base + h["sample_headers_size"]:
        raise ValueError("sample headers do not fill sample_headers_size exactly")

    nt_off = off
    nt = data[nt_off:nt_off + h["name_table_size"]]
    names = None
    if h["name_table_size"]:
        offs = struct.unpack_from(f"<{n}I", nt, 0)
        names, pos = [], 4 * n
        for o in offs:
            end = nt.index(b"\0", o)
            names.append(bytes(nt[o:end]))
            if o != pos:
                names = None  # non-sequential layout: keep the table verbatim
                break
            pos = end + 1
        if names is not None and (nt[pos:].strip(b"\0")
                                  or _align(nt_off + pos) - nt_off != h["name_table_size"]):
            names = None
    data_start = nt_off + h["name_table_size"]

    ends = [s["data_offset"] for s in samples[1:]] + [h["data_size"]]
    for s, end in zip(samples, ends):
        if s["data_offset"] % ALIGN or end < s["data_offset"]:
            raise ValueError("sample data offsets are not ascending and 32-byte aligned")
        span = data[data_start + s["data_offset"]:data_start + end]
        n_real = (celt_stream_length(span, s["sample_count"]) if h["mode"] == CELT_MODE
                  else len(span))
        if span[n_real:].strip(b"\0") or _align(s["data_offset"] + n_real) != end:
            raise ValueError("stream padding is not zero-filled 32-byte alignment")
        s["stream"] = bytes(span[:n_real])
        del s["data_offset"]
    return {"header_prefix": bytes(data[:4]), "version": h["version"], "mode": h["mode"],
            "header_tail": bytes(data[28:base]), "samples": samples, "names": names,
            "name_table_raw": None if names is not None else bytes(nt)}


def build(model):
    """Model -> FSB5 bytes (recomputes sizes, offsets, chunk flags, name offsets, padding)."""
    samples = model["samples"]
    n = len(samples)
    base = 28 + len(model["header_tail"])

    data_parts, offsets, pos = [], [], 0
    for s in samples:
        offsets.append(pos)
        stream = s["stream"]
        padded = _align(len(stream))
        data_parts.append(stream + b"\0" * (padded - len(stream)))
        pos += padded
    data_size = pos

    sh = bytearray()
    for s, offset in zip(samples, offsets):
        if offset % ALIGN or offset // 16 >= 1 << 28 or s["sample_count"] >= 1 << 30:
            raise ValueError("offset or sample count does not fit the FSB5 sample header")
        v = (s["head_bits"] & KEEP_BITS) | (1 if s["chunks"] else 0) | (offset // 16) << 6 \
            | s["sample_count"] << 34
        sh += struct.pack("<Q", v)
        for k, (ctype, payload) in enumerate(s["chunks"]):
            more = 1 if k + 1 < len(s["chunks"]) else 0
            sh += struct.pack("<I", more | len(payload) << 1 | ctype << 25) + payload

    if model["names"] is not None:
        body = b"".join(nm + b"\0" for nm in model["names"])
        offs, p = [], 4 * n
        for nm in model["names"]:
            offs.append(p)
            p += len(nm) + 1
        nt = struct.pack(f"<{n}I", *offs) + body
        nt_off = base + len(sh)
        nt += b"\0" * (_align(nt_off + len(nt)) - nt_off - len(nt))
    else:
        nt = model["name_table_raw"] or b""

    head = model["header_prefix"] + struct.pack("<IIIIII", model["version"], n, len(sh), len(nt), data_size,
                                                model["mode"]) + model["header_tail"]
    return head + bytes(sh) + nt + b"".join(data_parts)


def diff_ranges(a, b, limit=20, chunk=1 << 16):
    """[(start, end)] byte ranges where a and b differ (a length difference is one more range)."""
    if a == b:
        return []
    out, n = [], min(len(a), len(b))
    for c in range(0, n, chunk):
        if len(out) >= limit:
            break
        ca, cb = a[c:c + chunk], b[c:c + chunk]
        if ca == cb:
            continue
        i = 0
        while i < len(ca) and len(out) < limit:
            if ca[i] != cb[i]:
                j = i
                while j < len(ca) and ca[j] != cb[j]:
                    j += 1
                if out and out[-1][1] == c + i:  # range continues from the previous chunk
                    out[-1] = (out[-1][0], c + j)
                else:
                    out.append((c + i, c + j))
                i = j
            else:
                i += 1
    if len(a) != len(b) and len(out) < limit:
        out.append((n, max(len(a), len(b))))
    return out
