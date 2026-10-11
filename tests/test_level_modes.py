"""Build-level loudness modes (audio_edit.render level_mode, export_config level_mode): the global export gain
reaches the output exactly where there is headroom, match_spain brings a line to the Spain recording's
loudness with limiting capped at MATCH_MAX_LIMITING_DB, and the settings are recorded. Synthetic signals only.

Run: python -m unittest tests.test_level_modes
"""
import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))

from common import audio_edit as ae  # noqa: E402
from common.audio_pipeline import needs_processing  # noqa: E402
from common.export_config import ConfigError, load_export_config, save_global_gain  # noqa: E402

FS = ae.SAMPLE_RATE
EDIT = ae.EDIT_ZERO


def speech_like(seconds=2.0, level=0.05, spikes=(), seed=1):
    """A deterministic voiced signal (harmonics with a syllable envelope) plus optional short peaks."""
    n = int(seconds * FS)
    x = []
    for i in range(n):
        t = i / FS
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * t) ** 2
        x.append(level * env * (math.sin(2 * math.pi * 140 * t) + 0.5 * math.sin(2 * math.pi * 280 * t)
                                + 0.25 * math.sin(2 * math.pi * 560 * t)))
    for at, amp in spikes:
        for k in range(30):
            x[int(at * FS) + k] = amp * (1 if k % 2 else -1)
    return ae.float_to_pcm16(x)


def lufs(pcm):
    return ae.loudness(ae.pcm16_to_float(pcm))[0]


def peak(pcm):
    return ae.peak_db(ae.pcm16_to_float(pcm))


class GlobalGainTests(unittest.TestCase):
    def test_four_dB_reaches_the_output_where_there_is_headroom(self):
        pcm = speech_like(level=0.05)
        r0 = ae.render(pcm, EDIT, global_gain_db=0.0)
        r4 = ae.render(pcm, EDIT, global_gain_db=4.0)
        self.assertAlmostEqual(lufs(r4["pcm"]) - lufs(r0["pcm"]), 4.0, delta=0.02)
        self.assertEqual((r4["stats"]["global_gain_applied_db"], r4["stats"]["global_gain_shortfall_db"]), (4.0, 0.0))
        self.assertEqual(r4["stats"]["level_mode_used"], "global_gain")
        self.assertIsNone(r4["stats"]["match"])

    def test_different_gains_give_proportionally_different_levels(self):
        pcm = speech_like(level=0.03)
        levels = [lufs(ae.render(pcm, EDIT, global_gain_db=g)["pcm"]) for g in (-3.0, 0.0, 2.0, 6.0)]
        for (a, ga), (b, gb) in zip(zip(levels, (-3, 0, 2, 6)), zip(levels[1:], (0, 2, 6))):
            self.assertAlmostEqual(b - a, gb - ga, delta=0.02)

    def test_peak_protection_is_reported_and_never_limits(self):
        pcm = speech_like(level=0.65)                    # peak near -2.0 dBFS: about 1 dB of headroom
        r = ae.render(pcm, EDIT, global_gain_db=4.0)
        st = r["stats"]
        self.assertGreater(st["global_gain_shortfall_db"], 0)
        self.assertAlmostEqual(st["global_gain_applied_db"] + st["global_gain_shortfall_db"], 4.0, delta=0.01)
        self.assertLessEqual(peak(r["pcm"]), ae.PEAK_CEILING_DB + 0.01)
        self.assertTrue(st["warnings"])
        # linear: the waveform is the input scaled by one factor (no limiting)
        x, y = ae.pcm16_to_float(pcm), ae.pcm16_to_float(r["pcm"])
        g = 10 ** (st["global_gain_applied_db"] / 20)
        self.assertLess(max(abs(b - a * g) for a, b in zip(x, y)), 3 / 32768)  # 16-bit rounding only

    def test_the_default_mode_is_the_global_gain(self):
        pcm = speech_like()
        self.assertEqual(ae.render(pcm, EDIT, global_gain_db=4.0)["pcm"],
                         ae.render(pcm, EDIT, global_gain_db=4.0, level_mode="global_gain")["pcm"])
        self.assertFalse(needs_processing(EDIT, 0.0))
        self.assertTrue(needs_processing(EDIT, 0.0, "match_spain"))


class MatchSpainTests(unittest.TestCase):
    def test_a_quiet_line_reaches_the_spain_loudness(self):
        pcm = speech_like(level=0.02)                    # low crest: little limiting needed
        src = lufs(pcm)
        r = ae.render(pcm, EDIT, ref_lufs=src + 8.0, global_gain_db=4.0, level_mode="match_spain")
        st = r["stats"]
        self.assertEqual(st["level_mode_used"], "match_spain")
        self.assertEqual(st["global_gain_applied_db"], 0.0)   # the global gain is not used in this mode
        self.assertAlmostEqual(lufs(r["pcm"]), src + 8.0, delta=0.3)
        self.assertLessEqual(peak(r["pcm"]), ae.PEAK_CEILING_DB + 0.01)
        self.assertEqual(st["match"]["shortfall_db"], 0.0)

    def test_a_louder_line_is_brought_down_without_limiting(self):
        pcm = speech_like(level=0.2)
        src = lufs(pcm)
        r = ae.render(pcm, EDIT, ref_lufs=src - 5.0, level_mode="match_spain")
        self.assertAlmostEqual(lufs(r["pcm"]), src - 5.0, delta=0.05)
        self.assertEqual(r["stats"]["match"]["limiter_max_reduction_db"], 0.0)

    def test_limiting_is_capped_and_the_shortfall_reported(self):
        pcm = speech_like(level=0.02, spikes=[(0.5, 0.9), (1.2, 0.9)])   # high crest: sharp peaks
        src = lufs(pcm)
        r = ae.render(pcm, EDIT, ref_lufs=src + 20.0, level_mode="match_spain")
        m = r["stats"]["match"]
        self.assertGreater(m["shortfall_db"], 0)
        self.assertLessEqual(m["limiter_max_reduction_db"], ae.MATCH_MAX_LIMITING_DB + 0.05)
        self.assertLessEqual(peak(r["pcm"]), ae.PEAK_CEILING_DB + 0.01)
        self.assertTrue(any("match Spain" in w for w in r["stats"]["warnings"]))

    def test_without_a_reference_the_global_gain_applies(self):
        pcm = speech_like(level=0.05)
        r = ae.render(pcm, EDIT, ref_lufs=None, global_gain_db=4.0, level_mode="match_spain")
        self.assertEqual(r["stats"]["level_mode_used"], "global_gain")
        self.assertEqual(r["stats"]["global_gain_applied_db"], 4.0)
        self.assertTrue(any("global gain used" in w for w in r["stats"]["warnings"]))

    def test_deterministic_and_preview_cache_keys_follow_the_mode(self):
        pcm = speech_like(level=0.03, spikes=[(0.7, 0.6)])
        a = ae.render(pcm, EDIT, ref_lufs=-12.0, level_mode="match_spain")
        b = ae.render(pcm, EDIT, ref_lufs=-12.0, level_mode="match_spain")
        self.assertEqual(a["pcm"], b["pcm"])
        with self.assertRaises(ae.EditError):
            ae.render(pcm, EDIT, level_mode="louder")
        # the M4 preview caches by the mode too: the same line in another mode is a different render
        import inspect
        from common.edit_preview import EditPreview
        self.assertIn('"level_mode": level_mode', inspect.getsource(EditPreview.render))


class ExportSettingsTests(unittest.TestCase):
    def test_level_mode_is_saved_with_the_gain_and_defaults_to_global_gain(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_export_config(tmp)["level_mode"], "global_gain")
            self.assertEqual(load_export_config(tmp)["global_gain_db"], 4.0)
            saved = save_global_gain(tmp, None, None, level_mode="match_spain")
            self.assertEqual((saved["level_mode"], saved["global_gain_db"]), ("match_spain", 4.0))
            saved = save_global_gain(tmp, 3.0, saved["sha256"])           # changing the gain keeps the mode
            self.assertEqual((saved["level_mode"], saved["global_gain_db"]), ("match_spain", 3.0))
            with self.assertRaises(ConfigError):
                save_global_gain(tmp, None, saved["sha256"], level_mode="loudest")
            with self.assertRaises(ConfigError):
                save_global_gain(tmp, None, saved["sha256"])


class BuildStalenessTests(unittest.TestCase):
    def test_a_build_made_in_another_level_mode_is_stale(self):
        from build_api import BuildBoard
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mappings").mkdir()
            (root / "mappings/manual_mappings.json").write_bytes(b"d")
            sha = hashlib.sha256(b"d").hexdigest()
            for name, mode, gain in (("g4", "global_gain", 4.0), ("m", "match_spain", 1.0)):
                f = root / "work/m6" / name
                f.mkdir(parents=True)
                (f / "build_manifest.json").write_text(json.dumps({
                    "kind": "audio", "levels": ["a10"], "inputs": {"mappings_sha256": sha},
                    "global_gain": {"configured_db": gain, "level_mode": mode}, "install_files": [], "slots": []}))
                (f / "validation_report.json").write_text(json.dumps({"ok": True}))
            board = BuildBoard(root, lambda: {"a10"})
            b = {x["name"]: x for x in board.list_builds()["builds"]}
            self.assertFalse(b["g4"]["stale"])
            self.assertIn("level mode changed since the build (match_spain → global_gain)", b["m"]["stale_reasons"])
            save_global_gain(root, None, None, level_mode="match_spain")
            b = {x["name"]: x for x in board.list_builds()["builds"]}
            self.assertTrue(b["g4"]["stale"])
            self.assertFalse(b["m"]["stale"], b["m"]["stale_reasons"])  # the gain is not used in match mode


if __name__ == "__main__":
    unittest.main()
