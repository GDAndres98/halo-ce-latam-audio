"""Synthetic tests for the E1 same-length stream replacement (no game data)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.fsb5_writer import (build, celt_frame_sizes, decompose, replace_stream,  # noqa: E402
                                same_length_compatibility, sample_spans)
from test_fsb5_writer import celt_stream, fsb, loop  # noqa: E402

# "Spanish" and "English" banks: same layout at index 1, different audio bytes
ES = fsb([(8, 0, 1024, [loop(1024)], celt_stream(2, 370, 1)),
          (8, 0, 1536, [loop(1536)], celt_stream(3, 370, 2)),
          (8, 1, 512, [loop(512)], celt_stream(1, 464, 3))],
         [b"A10_340_cryoassist", b"A10_350_captkeyes", b"stereo"])
EN = fsb([(8, 0, 2048, [loop(2048)], celt_stream(4, 370, 9)),
          (8, 0, 1536, [loop(1536)], celt_stream(3, 370, 77)),
          (8, 1, 512, [loop(512)], celt_stream(1, 464, 5))],
         [b"A10_340_CryoAssist", b"A10_350_CaptKeyes", b"stereo"])


class E1TransplantTests(unittest.TestCase):
    def setUp(self):
        self.es, self.en = decompose(ES), decompose(EN)
        self.new = build(replace_stream(self.es, 1, self.en["samples"][1]["stream"]))

    def test_compatible_target_passes_every_check(self):
        c = same_length_compatibility(self.es["samples"][1], self.en["samples"][1])
        self.assertTrue(all(c.values()), c)

    def test_only_target_span_changes(self):
        spans = sample_spans(ES)
        t0, t1 = spans[1]
        self.assertEqual(len(self.new), len(ES))
        self.assertEqual(self.new[:t0], ES[:t0])
        self.assertEqual(self.new[t1:], ES[t1:])
        self.assertNotEqual(self.new[t0:t1], ES[t0:t1])
        self.assertEqual(sample_spans(self.new), spans)
        e0, e1 = sample_spans(EN)[1]
        self.assertEqual(self.new[t0:t1], EN[e0:e1])

    def test_header_names_and_other_samples_preserved(self):
        m = decompose(self.new)
        self.assertEqual(m["names"], self.es["names"])  # Spanish names kept, not English
        self.assertEqual(m["header_tail"], self.es["header_tail"])
        for i in (0, 2):
            self.assertEqual(m["samples"][i], self.es["samples"][i])
        self.assertEqual(m["samples"][1]["chunks"], self.es["samples"][1]["chunks"])
        self.assertEqual(build(m), self.new)

    def test_replace_does_not_mutate_input_model(self):
        before = self.es["samples"][1]["stream"]
        replace_stream(self.es, 1, b"x")
        self.assertEqual(self.es["samples"][1]["stream"], before)

    def test_incompatible_samples_are_flagged(self):
        es1, en = self.es["samples"][1], self.en["samples"]
        self.assertFalse(same_length_compatibility(es1, en[0])["sample_count_equal"])
        self.assertFalse(same_length_compatibility(es1, en[0])["stream_length_equal"])
        self.assertFalse(same_length_compatibility(es1, en[2])["channels_equal"])
        self.assertFalse(same_length_compatibility(es1, en[2])["celt_frame_sizes_equal"])
        other_loop = dict(en[1], chunks=[loop(1000)])
        self.assertFalse(same_length_compatibility(es1, other_loop)["chunks_equal"])

    def test_celt_frame_sizes(self):
        self.assertEqual(celt_frame_sizes(celt_stream(3, 370, 0)), [370, 370, 370])
        with self.assertRaises(ValueError):
            celt_frame_sizes(celt_stream(1, 370, 0) + b"\0")


if __name__ == "__main__":
    unittest.main()
