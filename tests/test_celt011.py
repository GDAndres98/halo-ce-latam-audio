"""Tests for the CELT 0.11 wrapper (B2 E2). The DLL round trip is skipped when vgmstream is absent."""
import math
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common.celt011 import DEFAULT_DLL, FRAME_SAMPLES, SYNC, Celt011, fmod_frames, split_fmod_frames  # noqa: E402
from common.fsb5_writer import celt_frame_sizes  # noqa: E402


class FramingTests(unittest.TestCase):
    def test_fmod_frames_round_trip(self):
        packets = [bytes([k]) * 370 for k in range(3)]
        stream = fmod_frames(packets)
        self.assertEqual(stream[:4], SYNC)
        self.assertEqual(struct.unpack_from("<I", stream, 4)[0], 370)
        self.assertEqual(len(stream), 3 * 378)
        self.assertEqual(split_fmod_frames(stream), packets)
        self.assertEqual(celt_frame_sizes(stream), [370, 370, 370])

    def test_bad_sync_rejected(self):
        with self.assertRaises(ValueError):
            split_fmod_frames(b"XXXX" + struct.pack("<I", 1) + b"a")


@unittest.skipUnless(DEFAULT_DLL.is_file(), "vgmstream libcelt-0110.dll not available")
class Celt011Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Celt011()

    @classmethod
    def tearDownClass(cls):
        cls.c.close()

    def test_cbr_packets_and_frame_count(self):
        n = FRAME_SAMPLES * 3 + 7  # forces a zero-padded last frame
        pcm = b"".join(struct.pack("<h", int(6000 * math.sin(k / 9))) for k in range(n))
        packets, frames = self.c.encode(pcm)
        self.assertEqual(frames, 4)
        self.assertEqual({len(p) for p in packets}, {370})
        out = self.c.decode(packets)
        self.assertEqual(len(out), frames * FRAME_SAMPLES * 2)

    def test_deterministic(self):
        pcm = b"".join(struct.pack("<h", (k * 37) % 4000 - 2000) for k in range(FRAME_SAMPLES * 2))
        self.assertEqual(self.c.encode(pcm), self.c.encode(pcm))

    def test_stereo_packet_size(self):
        pcm = b"\0\0" * FRAME_SAMPLES * 2
        packets, _ = self.c.encode(pcm, channels=2)
        self.assertEqual({len(p) for p in packets}, {464})


if __name__ == "__main__":
    unittest.main()
