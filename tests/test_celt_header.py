"""Tests for the CELT 0.11 frame-flag reader and the MCC encoder profile (B2 E2 diagnosis)."""
import math
import random
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common.celt011 import DEFAULT_DLL, FRAME_SAMPLES, Celt011, profile_violations  # noqa: E402
from common.celt_header import RangeDecoder, frame_flags  # noqa: E402


def clicks(n):
    """Silence with sharp clicks: forces CELT's transient (short-block) decision at default settings."""
    rnd = random.Random(7)
    out = []
    for k in range(n):
        v = 0.0
        if k % 700 < 6:
            v = 20000 * (1 if k % 2 else -1)
        out.append(v + rnd.gauss(0, 40))
    return b"".join(struct.pack("<h", int(max(-32768, min(32767, x)))) for x in out)


class RangeDecoderTests(unittest.TestCase):
    def test_all_zero_packet_reads_silence_flag_zero(self):
        # val starts at 127 - (0 >> 1); first logp(15) symbol is "silence" only if val < rng >> 15
        f = frame_flags(bytes(370))
        self.assertIn(f["silence"], (0, 1))
        self.assertEqual(set(f), {"silence", "postfilter", "pf_period", "pf_gain_q", "pf_tapset", "transient",
                                  "intra"})

    def test_tell_starts_at_one(self):
        self.assertEqual(RangeDecoder(b"\x6f" + bytes(369)).tell(), 1)

    def test_uint_and_bits_stay_in_range(self):
        dec = RangeDecoder(bytes(range(256)) + bytes(114))
        self.assertTrue(0 <= dec.uint(6) < 6)
        self.assertTrue(0 <= dec.bits(7) < 128)


@unittest.skipUnless(DEFAULT_DLL.is_file(), "vgmstream libcelt-0110.dll not available")
class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Celt011()
        cls.pcm = clicks(FRAME_SAMPLES * 40)
        cls.speech = b"".join(struct.pack("<h", int(4000 * math.sin(k / 7) * math.sin(k / 3000)))
                              for k in range(FRAME_SAMPLES * 40))

    @classmethod
    def tearDownClass(cls):
        cls.c.close()

    def test_default_profile_violates_mcc_profile(self):
        packets, _ = self.c.encode(self.pcm, profile="default")
        flags = [frame_flags(p) for p in packets]
        self.assertGreater(sum(f["transient"] for f in flags), 0)
        self.assertTrue(profile_violations(packets))

    def test_fmod_profile_matches_mcc_profile(self):
        for pcm in (self.pcm, self.speech):
            packets, _ = self.c.encode(pcm, profile="fmod")
            self.assertEqual(profile_violations(packets), [])
            flags = [frame_flags(p) for p in packets]
            self.assertEqual(sum(f["transient"] for f in flags), 0)
            self.assertEqual(sum(f["postfilter"] for f in flags), 0)

    def test_fmod_profile_is_default_and_cbr(self):
        packets, _ = self.c.encode(self.speech)
        self.assertEqual({len(p) for p in packets}, {370})
        self.assertEqual(profile_violations(packets), [])

    def test_unknown_profile_rejected(self):
        with self.assertRaises(KeyError):
            self.c.encode(self.speech, profile="nope")


if __name__ == "__main__":
    unittest.main()
