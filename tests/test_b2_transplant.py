"""Synthetic tests for different-length sample replacement (B2 E1b). No game data."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.fsb5_lib import parse_header, parse_sample_headers  # noqa: E402
from common.fsb5_writer import (build, decompose, loop_chunk, replace_sample,  # noqa: E402
                                replacement_compatibility, sample_spans)
from common.vgm import meta_value  # noqa: E402
from test_fsb5_writer import celt_stream, fsb, loop  # noqa: E402

ES = fsb([(8, 0, 1024, [loop(1024)], celt_stream(2, 370, 1)),
          (8, 0, 1536, [loop(1536)], celt_stream(3, 370, 2)),
          (8, 0, 512, [loop(512)], celt_stream(1, 370, 3)),
          (8, 1, 512, [loop(512)], celt_stream(1, 464, 4))],
         [b"a", b"A10_140_cryotech", b"c", b"stereo"])
LONGER = {"head_bits": 16, "channels": 1, "sample_count": 2560, "chunks": [loop(2560)],
          "stream": celt_stream(5, 370, 9)}
SHORTER = dict(LONGER, sample_count=512, chunks=[loop(512)], stream=celt_stream(1, 370, 8))


class TransplantTests(unittest.TestCase):
    def setUp(self):
        self.m = decompose(ES)

    def test_loop_chunk_rule(self):
        self.assertEqual(loop_chunk(201728), (3, struct.pack("<II", 0, 201726)))

    def test_longer_replacement_shifts_later_samples_only(self):
        new = build(replace_sample(self.m, 1, LONGER["stream"], LONGER["sample_count"]))
        so, sn = sample_spans(ES), sample_spans(new)
        growth = (sn[1][1] - sn[1][0]) - (so[1][1] - so[1][0])
        self.assertGreater(growth, 0)
        self.assertEqual(growth % 32, 0)
        self.assertEqual(sn[:2][0], so[0])
        self.assertEqual(sn[1][0], so[1][0])
        self.assertEqual({c[0] - o[0] for o, c in zip(so[2:], sn[2:])}, {growth})
        self.assertEqual(len(new) - len(ES), growth)
        for k in (0, 2, 3):
            self.assertEqual(ES[so[k][0]:so[k][1]], new[sn[k][0]:sn[k][1]])
        h = parse_header(new)
        s, _ = parse_sample_headers(new, h["base_header_size"], h["sample_headers_size"], h["num_samples"])
        self.assertEqual(s[1]["sample_count"], 2560)
        m2 = decompose(new)
        self.assertEqual(m2["samples"][1]["chunks"], [loop_chunk(2560)])
        self.assertEqual([m2["samples"][k] for k in (0, 2, 3)], [self.m["samples"][k] for k in (0, 2, 3)])
        self.assertEqual(m2["names"], self.m["names"])
        self.assertEqual(build(m2), new)

    def test_shorter_replacement_shrinks_bank(self):
        new = build(replace_sample(self.m, 1, SHORTER["stream"], SHORTER["sample_count"]))
        self.assertLess(len(new), len(ES))
        self.assertEqual(decompose(new)["samples"][1]["chunks"], [loop_chunk(512)])
        self.assertEqual(build(decompose(new)), new)

    def test_sample_without_loop_gets_none(self):
        bank = fsb([(8, 0, 512, [], celt_stream(1, 370, 1)), (8, 0, 512, [], celt_stream(1, 370, 2))],
                   [b"x", b"y"])
        m = decompose(bank)
        new = decompose(build(replace_sample(m, 0, LONGER["stream"], LONGER["sample_count"])))
        self.assertEqual(new["samples"][0]["chunks"], [])

    def test_compatibility(self):
        dst = self.m["samples"][1]
        self.assertTrue(all(replacement_compatibility(dst, LONGER).values()))
        stereo = self.m["samples"][3]
        c = replacement_compatibility(dst, stereo)
        self.assertFalse(c["channels_equal"])
        self.assertFalse(c["frame_size_equal"])
        bad_count = dict(LONGER, sample_count=2000)
        c = replacement_compatibility(dst, bad_count)
        self.assertFalse(c["frame_count_matches_samples"] and c["sample_count_frame_aligned"])

    def test_meta_value(self):
        lines = ["sample rate: 44100 Hz", "stream total samples: 201728 (0:04.574 seconds)"]
        self.assertEqual(meta_value(lines, "stream total samples").split(" ")[0], "201728")
        self.assertIsNone(meta_value(lines, "channels"))


if __name__ == "__main__":
    unittest.main()
