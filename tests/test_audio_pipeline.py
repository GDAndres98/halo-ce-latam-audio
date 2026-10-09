"""End-to-end tests: synthetic 48 kHz WAV -> ffmpeg -> CELT (MCC profile) -> FSB5 bank -> checks.

No game data. ffmpeg / libcelt / vgmstream steps are skipped when the tools are absent.
"""
import math
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.audio_pipeline import CODEC_DELAY, derive, encode_for_mcc, snr_db  # noqa: E402
from common.bank_checks import decode_checks, structural_checks  # noqa: E402
from common.celt011 import DEFAULT_DLL, Celt011, profile_violations, split_fmod_frames  # noqa: E402
from common.fsb5_writer import build, decompose, replace_sample  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM  # noqa: E402
from test_fsb5_writer import celt_stream, fsb, loop  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
HAVE_CELT = DEFAULT_DLL.is_file()


def speechlike_48k(seconds=1.3):
    n = int(48000 * seconds)
    return b"".join(struct.pack("<h", int(sum(4000 / h * math.sin(2 * math.pi * 150 * h * k / 48000)
                                              for h in range(1, 8)) * max(0.0, math.sin(2 * math.pi * 3 * k / 48000))))
                    for k in range(n))


def bank():
    return fsb([(8, 0, 1024, [loop(1024)], celt_stream(2, 370, 1)),
                (8, 0, 1536, [loop(1536)], celt_stream(3, 370, 2)),
                (8, 1, 512, [loop(512)], celt_stream(1, 464, 3))],
               [b"a", b"target", b"stereo"])


class StructuralChecksTests(unittest.TestCase):
    def test_pass_for_clean_replacement_and_fail_for_collateral_change(self):
        original = bank()
        stream = celt_stream(5, 370, 9)
        cand = build(replace_sample(decompose(original), 1, stream, 2560))
        checks = structural_checks(original, cand, 1, stream, 2560)
        self.assertTrue(all(checks.values()), checks)
        m = decompose(cand)
        m["samples"][2] = dict(m["samples"][2], stream=celt_stream(1, 464, 99))
        bad = build(m)
        self.assertFalse(structural_checks(original, bad, 1, stream, 2560)["other_samples_identical"])
        self.assertFalse(structural_checks(original, cand, 1, stream, 2048)["target_sample_count"])


@unittest.skipUnless(HAVE_CELT, "libcelt-0110.dll not available")
class EncodeTests(unittest.TestCase):
    def test_encode_pads_codec_delay_and_whole_frames(self):
        c = Celt011()
        try:
            n = 44100
            pcm = b"".join(struct.pack("<h", int(3000 * math.sin(k / 11))) for k in range(n))
            enc = encode_for_mcc(c, pcm)
            self.assertEqual(enc["sample_count"], -(-(n + CODEC_DELAY) // 512) * 512)
            self.assertEqual(profile_violations(split_fmod_frames(enc["stream"])), [])
            with self.assertRaises(ValueError):
                encode_for_mcc(c, pcm, profile="nope")
        finally:
            c.close()


@unittest.skipUnless(HAVE_CELT and FFMPEG, "ffmpeg or libcelt-0110.dll not available")
class PipelineTests(unittest.TestCase):
    def test_wav_48k_to_bank_end_to_end(self):
        c = Celt011()
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "line_48k.wav"
            with wave.open(str(src), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(48000), w.writeframes(speechlike_48k())
            r = derive(src, ffmpeg=FFMPEG, celt=c, out_root=Path(td) / "derived", source_meta={"note": "synthetic"})
            r2 = derive(src, ffmpeg=FFMPEG, celt=c, out_root=Path(td) / "derived", source_meta={"note": "synthetic"})
            c.close()
            recipe = r["recipe"]
            self.assertEqual(r["stream"], r2["stream"])  # deterministic
            self.assertEqual(recipe["source"]["sample_rate"], 48000)
            n = recipe["pcm_44100"]["samples"]
            self.assertLess(abs(n - int(1.3 * 44100)), 3)
            self.assertTrue(n + CODEC_DELAY <= r["sample_count"] < n + CODEC_DELAY + 512)
            self.assertGreater(snr_db(r["pcm"], r["decoded"]), 30)
            self.assertEqual(recipe["steps"][2]["packet_bytes"], [370])
            self.assertTrue((r["dir"] / "recipe.json").is_file() and (r["dir"] / "mcc_44100.wav").is_file())
            self.assertEqual(r["dir"].name, recipe["output"]["stream_sha256"])

            original = bank()
            cand = build(replace_sample(decompose(original), 1, r["stream"], r["sample_count"]))
            checks = structural_checks(original, cand, 1, r["stream"], r["sample_count"])
            self.assertTrue(all(checks.values()), checks)
            if DEFAULT_VGMSTREAM.is_file():
                op, cp = Path(td) / "orig.fsb", Path(td) / "cand.fsb"
                op.write_bytes(original)
                cp.write_bytes(cand)
                dec, _ = decode_checks(DEFAULT_VGMSTREAM, op, cp, 1, r["sample_count"], 3)
                self.assertTrue(dec["vgm_target_sample_count"] and dec["vgm_target_encoding_custom_celt"], dec)


if __name__ == "__main__":
    unittest.main()
