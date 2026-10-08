"""Synthetic round-trip tests for the FSB5 writer (B2 E0). No game data.

Fixtures are assembled by hand here, independently of fsb5_writer.build, so a round trip
checks the writer against the layout rather than against itself.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common.fsb5_lib import parse_header, parse_name_table, parse_sample_headers  # noqa: E402
from common.fsb5_writer import build, celt_stream_length, decompose, diff_ranges  # noqa: E402

SYNC = b"\x17\xc3\x0d\xf3"
TAIL = struct.pack("<I", 0x80000010) + b"\0" * 4 + bytes(range(16)) + b"\xAA" * 8  # flags, zero, hash, unknown


def celt_stream(frames, payload_len, seed):
    return b"".join(SYNC + struct.pack("<I", payload_len) + bytes((seed + k + i) % 251 for i in range(payload_len))
                    for k in range(frames))


def fsb(samples, names, mode=12, tail=TAIL, nt_override=None):
    """samples: [(freq_idx, stereo, sample_count, [(type, payload)], stream)]."""
    data, offs = b"", []
    for *_, stream in samples:
        offs.append(len(data))
        data += stream + b"\0" * (-len(stream) % 32)
    sh = b""
    for (fi, st, cnt, chunks, _), off in zip(samples, offs):
        sh += struct.pack("<Q", (1 if chunks else 0) | fi << 1 | st << 5 | (off // 16) << 6 | cnt << 34)
        for k, (ct, pl) in enumerate(chunks):
            sh += struct.pack("<I", (1 if k + 1 < len(chunks) else 0) | len(pl) << 1 | ct << 25) + pl
    if nt_override is not None:
        nt = nt_override
    else:
        body, p, o = b"", 4 * len(names), []
        for nm in names:
            o.append(p)
            body += nm + b"\0"
            p += len(nm) + 1
        nt = struct.pack(f"<{len(names)}I", *o) + body
        start = 28 + len(tail) + len(sh)
        nt += b"\0" * (-(start + len(nt)) % 32)
    head = b"FSB5" + struct.pack("<IIIIII", 1, len(samples), len(sh), len(nt), len(data), mode) + tail
    return head + sh + nt + data


def loop(n):
    return (3, struct.pack("<II", 0, n - 2))


MONO = (8, 0, 1024, [loop(1024)], celt_stream(2, 370, 1))
STEREO = (8, 1, 1500, [loop(1500)], celt_stream(3, 464, 7))
ODD = (8, 0, 512, [(5, b"\x01\x02\x03"), loop(512), (11, b"unknown-ish")], celt_stream(1, 370, 3))
BANK = fsb([MONO, STEREO, ODD], [b"a10_010_cryotech", b"stereo_line", b"dup"])


def parsed(data):
    h = parse_header(data)
    s, _ = parse_sample_headers(data, h["base_header_size"], h["sample_headers_size"], h["num_samples"])
    names = parse_name_table(data, h["base_header_size"] + h["sample_headers_size"], h["name_table_size"],
                             h["num_samples"])
    return h, s, names


class Fsb5WriterTests(unittest.TestCase):
    def test_round_trip_is_byte_identical_mono_stereo_and_chunks(self):
        self.assertEqual(build(decompose(BANK)), BANK)
        m = decompose(BANK)
        self.assertEqual([s["channels"] for s in m["samples"]], [1, 2, 1])
        self.assertEqual(m["samples"][2]["chunks"][0], (5, b"\x01\x02\x03"))  # unknown chunk kept verbatim
        self.assertEqual(m["header_tail"], TAIL)

    def test_duplicate_names_and_order_preserved(self):
        bank = fsb([MONO, MONO, ODD], [b"dup", b"dup", b"Zeta"])
        self.assertEqual(build(decompose(bank)), bank)
        self.assertEqual(parsed(build(decompose(bank)))[2], ["dup", "dup", "Zeta"])

    def test_padding_variants_round_trip(self):
        for payload in (370, 371, 372, 380, 394):  # stream lengths hitting different pad sizes
            s = (8, 0, 512, [loop(512)], celt_stream(1, payload, payload))
            bank = fsb([s, MONO], [b"x", b"yy"])
            self.assertEqual(build(decompose(bank)), bank, payload)

    def test_non_celt_mode_keeps_whole_span(self):
        ima = (8, 0, 64, [], b"\x11" * 36)
        bank = fsb([ima, ima], [b"a", b"b"], mode=7, tail=b"\0" * 32)
        self.assertEqual(build(decompose(bank)), bank)

    def test_non_sequential_name_table_kept_raw(self):
        nt = struct.pack("<2I", 12, 8) + b"bb\0\0" + b"aa\0\0" + b"\0" * 4
        bank = fsb([MONO, MONO], [], nt_override=nt)
        m = decompose(bank)
        self.assertIsNone(m["names"])
        self.assertEqual(build(m), bank)

    def test_rebuild_after_stream_change_recomputes_offsets_only(self):
        m = decompose(BANK)
        m["samples"][0]["stream"] = celt_stream(3, 370, 9)  # longer first stream
        m["samples"][0]["sample_count"] = 1536
        new = build(m)
        h0, s0, n0 = parsed(BANK)
        h1, s1, n1 = parsed(new)
        self.assertEqual(n0, n1)
        self.assertEqual([(s["frequency"], s["channels"], s["chunks"]) for s in s0],
                         [(s["frequency"], s["channels"], s["chunks"]) for s in s1])
        self.assertTrue(all(s["data_offset"] % 32 == 0 for s in s1))
        self.assertGreater(s1[1]["data_offset"], s0[1]["data_offset"])
        self.assertEqual(len(new), h1["base_header_size"] + h1["sample_headers_size"] + h1["name_table_size"]
                         + h1["data_size"])
        m2 = decompose(new)
        self.assertEqual(m2["samples"][1]["stream"], decompose(BANK)["samples"][1]["stream"])
        self.assertEqual(build(m2), new)

    def test_rejects_inconsistent_inputs(self):
        with self.assertRaises(ValueError):  # truncated file
            decompose(BANK[:-1])
        bad_count = fsb([(8, 0, 2048, [], celt_stream(2, 370, 1))], [b"a"])  # 2 frames for 4 needed
        with self.assertRaises(ValueError):
            decompose(bad_count)
        dirty = bytearray(BANK)
        dirty[-1] = 1  # non-zero byte in the final padding
        with self.assertRaises(ValueError):
            decompose(bytes(dirty))
        m = decompose(BANK)
        m["samples"][0]["sample_count"] = 1 << 30
        with self.assertRaises(ValueError):
            build(m)

    def test_celt_stream_length(self):
        span = celt_stream(2, 370, 0) + b"\0" * 12
        self.assertEqual(celt_stream_length(span, 1024), 756)
        with self.assertRaises(ValueError):
            celt_stream_length(span, 1025)

    def test_diff_ranges(self):
        a = bytes(200_000)
        b = bytearray(a)
        b[10:13] = b"xyz"
        b[65_534:65_540] = b"ABCDEF"  # crosses a 64 KiB chunk boundary
        self.assertEqual(diff_ranges(a, bytes(b)), [(10, 13), (65_534, 65_540)])
        self.assertEqual(diff_ranges(a, a), [])
        self.assertEqual(diff_ranges(a, a + b"!"), [(200_000, 200_001)])


if __name__ == "__main__":
    unittest.main()
