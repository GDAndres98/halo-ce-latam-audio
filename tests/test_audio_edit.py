"""Audio editor tests: edit recipes (common/audio_edit), M4 saving and protections, M6 planning, and
preview == build parity. Synthetic audio only. The ffmpeg / libcelt steps are skipped when absent.

Run: python -m unittest discover -s tests
"""
import copy
import json
import math
import shutil
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import audio_edit as ae  # noqa: E402
from common import radio_clicks  # noqa: E402
from common.audio_pipeline import CODEC_DELAY, derive, derive_processed, to_mcc_pcm  # noqa: E402
from common.celt011 import DEFAULT_DLL, Celt011  # noqa: E402
from common.edit_preview import EditPreview  # noqa: E402
from common.jsonschema_lite import load_schema  # noqa: E402
from common.m6_build import compare_plans, plan_audio  # noqa: E402
from common.project_validation import validate_mappings  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from test_m4 import AppTestBase  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
HAVE_CELT = DEFAULT_DLL.is_file()
SRC = {"ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"}
FS = 44100


def speech(seconds=1.5, fs=FS, amp=0.3):
    """Harmonic 'voice' with a syllable envelope and a quiet gap in the middle."""
    n = int(seconds * fs)
    out = []
    for k in range(n):
        env = max(0.0, math.sin(2 * math.pi * 2.5 * k / fs)) * (0.05 if 0.45 * n < k < 0.55 * n else 1.0)
        out.append(amp * env * sum(math.sin(2 * math.pi * 140 * h * k / fs) / h for h in range(1, 6)) / 2.3)
    return out


def fake_clicks():
    """Stand-ins for MCC's clicks (the real ones come from the pinned bank, tested in RadioClickTests)."""
    a = ae.pcm16_to_float(ae.float_to_pcm16([0.2 * math.sin(i / 3) for i in range(441)]))
    b = ae.pcm16_to_float(ae.float_to_pcm16([0.1 * math.sin(i / 5) for i in range(882)]))
    return {"in": a, "out": b, "sha256": {"in": "a" * 64, "out": "b" * 64}, "reference": {"slot_id": "es:fake#0"}}


def write_wav(path, x, fs=FS):
    path.parent.mkdir(parents=True, exist_ok=True)
    ae.write_wav(path, ae.float_to_pcm16(x), fs)
    return path


class RecipeTests(unittest.TestCase):
    def test_identity_and_canonical_form(self):
        self.assertEqual(ae.normalize({}), ae.EDIT_ZERO)
        self.assertEqual(ae.normalize({"limiter": False, "crossfade_ms": 40}), ae.EDIT_ZERO)
        self.assertTrue(ae.is_identity({"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0}))
        r = ae.normalize({"trim_start_s": 0.12345, "cuts": [{"start_s": 1.2, "end_s": 1.4}, {"start_s": 0.5, "end_s": 0.6}]}, SRC)
        self.assertEqual(r["trim_start_s"], 0.123)
        self.assertEqual([c["start_s"] for c in r["cuts"]], [0.5, 1.2])  # sorted
        self.assertEqual((r["engine"], r["for_source"]), (ae.ENGINE, SRC))
        self.assertNotIn("speed", r)
        self.assertNotIn("gain_db", r)
        self.assertNotIn("limiter", r)  # removed 2026-10-11
        self.assertNotIn("loudness", r)  # removed 2026-10-11
        # Stored by older recipes: a limiter, or loudness that is off, is ignored and dropped.
        self.assertEqual(ae.normalize(dict(r, limiter=True, loudness={"mode": "off", "offset_db": 0})), r)
        for matching in ({"mode": "match_mcc", "offset_db": 0}, {"mode": "off", "offset_db": 2}):
            with self.assertRaises(ae.EditError):  # asking for matching is refused
                ae.normalize(dict(r, loudness=matching))
        self.assertEqual(ae.normalize(r), r)  # idempotent
        self.assertIn("cut", ae.summary(r))
        self.assertNotIn("speed", ae.summary(r))

    def test_rules(self):
        for bad in ({"speed": 1.1}, {"speed": 1}, {"gain_db": 0}, {"gain_db": 3}, {"bogus": 1}, {"cuts": [{"start_s": 1}]},
                    {"cuts": [{"start_s": 1, "end_s": 0.5}]}, {"loudness": {"mode": "loud"}}, {"trim_start_s": "x"},
                    {"cuts": [{"start_s": 0.1, "end_s": 0.5}, {"start_s": 0.4, "end_s": 0.6}]}):
            with self.assertRaises(ae.EditError, msg=bad):
                ae.normalize(dict(bad, trim_end_s=0.1), SRC)
        with self.assertRaises(ae.EditError):
            ae.normalize({"trim_start_s": 0.1})  # no source to bind it to
        r = ae.normalize({"trim_start_s": 0.5, "trim_end_s": 0.5}, SRC)
        self.assertEqual(ae.problems(r, 2.0), [])
        self.assertTrue(ae.problems(r, 1.02))  # keeps less than the minimum
        r = ae.normalize({"cuts": [{"start_s": 1.5, "end_s": 1.9}]}, SRC)
        self.assertTrue(ae.problems(r, 1.6))   # cut past the end

    def test_inserted_silence_rules(self):
        r = ae.normalize({"silences": [{"at_s": 1.2, "dur_s": 0.3}, {"at_s": 0.4, "dur_s": 0.25}]}, SRC)
        self.assertEqual([c["at_s"] for c in r["silences"]], [0.4, 1.2])   # sorted
        self.assertFalse(ae.is_identity(r))
        self.assertIn("+2 silences (0.55 s)", ae.summary(r))
        for bad in ({"silences": [{"at_s": 0.5, "dur_s": 9}]}, {"silences": [{"at_s": 0.5}]},
                    {"silences": [{"at_s": 0.05, "dur_s": 0.2}], "trim_start_s": 0.1},       # inside the start trim
                    {"silences": [{"at_s": 1.0, "dur_s": 0.2}], "cuts": [{"start_s": 0.9, "end_s": 1.1}]},
                    {"silences": [{"at_s": 1.0, "dur_s": 0.2}, {"at_s": 1.0, "dur_s": 0.1}]}):
            with self.assertRaises(ae.EditError, msg=bad):
                ae.normalize(bad, SRC)
        ok = ae.normalize({"silences": [{"at_s": 0.9, "dur_s": 0.2}], "cuts": [{"start_s": 0.9, "end_s": 1.1}]}, SRC)
        self.assertEqual(ae.problems(ok, 2.0), [])   # at a cut's edge is fine (replace a pause)
        self.assertTrue(ae.problems(ae.normalize({"silences": [{"at_s": 1.9, "dur_s": 0.2}]}, SRC), 1.8))

    def test_schema_accepts_recipes_and_old_files_unchanged(self):
        from common.jsonschema_lite import validate
        schema = load_schema("manual-mappings-3")
        edit_schema = schema["$defs"]["slot"]["properties"]["audio"]["properties"]["edit"]
        r = ae.normalize({"trim_start_s": 0.1, "cuts": [{"start_s": 0.5, "end_s": 0.6}],
                          "silences": [{"at_s": 0.8, "dur_s": 0.4}]}, SRC)
        self.assertEqual(validate(r, {**edit_schema, "$defs": schema["$defs"]}), [])
        full = {**edit_schema, "$defs": schema["$defs"]}
        self.assertEqual(validate(dict(r, loudness={"mode": "off", "offset_db": 0}), full), [])  # older recipes
        self.assertTrue(validate(dict(r, loudness={"mode": "match_mcc", "offset_db": 0}), full))  # matching gone
        self.assertTrue(validate(dict(r, limiter=True), full))
        self.assertEqual(validate(dict(ae.EDIT_ZERO), {**edit_schema, "$defs": schema["$defs"]}), [])
        for gone in ({"speed": 1.0}, {"gain_db": 0}):  # removed fields are no longer in the schema
            self.assertTrue(validate(dict(r, **gone), {**edit_schema, "$defs": schema["$defs"]}))
        self.assertEqual(ae.removed_fields(dict(r, speed=1, gain_db=0)), ["speed", "gain_db"])
        self.assertTrue(ae.problems(dict(ae.EDIT_ZERO, speed=1.2)))  # reported even on an identity recipe

    def test_radio_recipe_rules(self):
        r = ae.normalize({"radio": {"preset": "spain"}}, SRC)
        self.assertFalse(ae.is_identity(r))  # a radio filter alone is an edit (bound to its source)
        self.assertEqual(r["radio"], dict(ae.RADIO_PRESETS["spain"], preset="spain"))
        self.assertEqual(ae.normalize(r), r)  # idempotent
        self.assertEqual(ae.summary(r), "radio spain 700–3300 Hz")
        self.assertEqual(ae.normalize({"radio": None}), ae.EDIT_ZERO)  # off: no field, as before
        self.assertNotIn("radio", ae.normalize({"trim_start_s": 0.1}, SRC))
        c = ae.normalize({"radio": {"preset": "custom", "low_hz": 600, "high_hz": 3500, "slope_db_oct": 24,
                                    "presence_db": 3, "drive_db": 0, "noise_dbfs": -55}}, SRC)
        self.assertIn("hiss -55 dBFS", ae.summary(c))
        for bad in ({"preset": "walkie"}, {"preset": "custom", "low_hz": 50}, {"preset": "custom", "slope_db_oct": 18},
                    {"preset": "custom", "low_hz": 2000, "high_hz": 2500}, {"preset": "custom", "noise_dbfs": -10},
                    {"preset": "spain", "wet": 1}, "spain"):
            with self.assertRaises(ae.EditError, msg=bad):
                ae.normalize({"radio": bad}, SRC)
        from common.jsonschema_lite import validate
        schema = load_schema("manual-mappings-3")
        full = {**schema["$defs"]["slot"]["properties"]["audio"]["properties"]["edit"], "$defs": schema["$defs"]}
        self.assertEqual(validate(r, full), [])
        self.assertEqual(validate(c, full), [])
        self.assertTrue(validate(dict(r, radio=dict(r["radio"], slope_db_oct=18)), full))


class DspTests(unittest.TestCase):
    def test_bs1770_reference(self):
        b, a = ae._biquads(48000)[0]
        self.assertAlmostEqual(b[0] / a[0], 1.53512485958697, places=9)
        self.assertAlmostEqual(a[1] / a[0], -1.69065929318241, places=9)
        b, a = ae._biquads(48000)[1]
        self.assertAlmostEqual(a[1] / a[0], -1.99004745483398, places=9)
        for fs in (48000, 44100):
            lufs, method = ae.loudness([math.sin(2 * math.pi * 997 * i / fs) for i in range(fs * 2)], fs)
            self.assertAlmostEqual(lufs, -3.01, delta=0.02)
            self.assertEqual(method, "bs1770_gated")
        self.assertEqual(ae.loudness([0.0] * FS)[1], "silent")
        self.assertEqual(ae.loudness([0.5] * 1000)[1], "ungated_short")

    def test_splice_removes_exactly_the_cuts(self):
        x = [0.25] * FS
        e = ae.normalize({"trim_start_s": 0.1, "trim_end_s": 0.2, "crossfade_ms": 20,
                          "cuts": [{"start_s": 0.3, "end_s": 0.4}, {"start_s": 0.6, "end_s": 0.65}]}, SRC)
        segs = ae.kept_segments(len(x), e)
        self.assertEqual(segs, [(4410, 13230), (17640, 26460), (28665, 35280)])
        y = ae.splice(x, segs, int(0.02 * FS))
        self.assertEqual(len(y), sum(b - a for a, b in segs))
        self.assertTrue(all(0.25 - 1e-9 <= v <= 0.25 * math.sqrt(2) + 1e-9 for v in y))  # equal-power: <= +3 dB
        self.assertEqual(ae.splice([0.0] * FS, segs, 882), [0.0] * len(y))

    def test_inserted_silence_is_exact_and_in_place(self):
        x = [0.25] * FS
        e = ae.normalize({"trim_start_s": 0.1, "cuts": [{"start_s": 0.3, "end_s": 0.4}], "crossfade_ms": 0,
                          "silences": [{"at_s": 0.2, "dur_s": 0.05}, {"at_s": 0.6, "dur_s": 0.1}]}, SRC)
        self.assertEqual(ae.spliced_position(0.2, e), 4410)        # 0.2 - 0.1 trim
        self.assertEqual(ae.spliced_position(0.6, e), 26460 - 4410 - 4410)  # minus the trim and the cut before it
        r = ae.render(ae.float_to_pcm16(x), e)
        y = ae.pcm16_to_float(r["pcm"])
        kept = FS - int(0.1 * FS) - int(0.1 * FS)
        self.assertEqual(len(y), kept + int(0.05 * FS) + int(0.1 * FS))
        self.assertEqual(r["stats"]["inserted_silence_s"], 0.15)
        self.assertEqual(set(y[4410:4410 + 2205]), {0.0})                 # first silence
        p2 = 17640 + 2205
        self.assertEqual(set(y[p2:p2 + 4410]), {0.0})                     # second, after the cut
        self.assertNotEqual(y[4409], 0.0)
        self.assertNotEqual(y[4410 + 2205], 0.0)
        faded = ae.render(ae.float_to_pcm16(x), dict(e, crossfade_ms=20))  # 10 ms fades either side
        z = ae.pcm16_to_float(faded["pcm"])
        self.assertLess(abs(z[4409]), 0.01)
        self.assertLess(abs(z[4410 + 2205]), 0.01)

    def test_fades(self):
        y = ae.fade([1.0] * 1000, 100, 50)
        self.assertLess(y[0], 0.01)
        self.assertLess(y[-1], 0.01)
        self.assertEqual(y[500], 1.0)
        # The limiter exists only for the build-level match_spain mode; global_gain mode never limits
        # (test_level_modes.py).

    def test_render_is_deterministic_and_has_no_per_line_level(self):
        pcm = ae.float_to_pcm16(speech(1.5, amp=0.05))
        e = ae.normalize({"trim_start_s": 0.05, "trim_end_s": 0.05, "fade_in_ms": 10, "fade_out_ms": 10,
                          "cuts": [{"start_s": 0.7, "end_s": 0.8}]}, SRC)
        r1, r2 = ae.render(pcm, e, ref_lufs=-14.0), ae.render(pcm, e)
        self.assertEqual(r1["pcm"], r2["pcm"])  # Spain's loudness is only reported, never applied
        st = r1["stats"]
        self.assertEqual(st["output_samples"], len(pcm) // 2 - int(0.2 * FS))
        self.assertEqual((st["mcc_reference_lufs"], st["total_gain_db"]), (-14.0, 0.0))
        for gone in ("loudness_match", "match_applied_gain_db", "limiter"):
            self.assertNotIn(gone, st)
        self.assertEqual(ae.render(pcm, dict(ae.EDIT_ZERO))["pcm"], pcm)  # identity, no global gain: unchanged
        # An older recipe with loudness off (and a limiter) renders exactly like one without them.
        legacy = ae.render(pcm, dict(e, limiter=True, loudness={"mode": "off", "offset_db": 0}))
        self.assertEqual(legacy["pcm"], r1["pcm"])

    def test_radio_band_pass_response(self):
        def gain_db(radio, f):
            x = [0.5 * math.sin(2 * math.pi * f * i / FS) for i in range(8000)]
            y, _ = ae.radio_filter(x, radio)
            rms = lambda v: math.sqrt(sum(s * s for s in v) / len(v))  # noqa: E731
            return 20 * math.log10(rms(y[4000:]) / rms(x[4000:]))
        spain = ae.normalize_radio({"preset": "spain"})
        self.assertAlmostEqual(gain_db(spain, 1500), 0, delta=0.5)   # pass band
        self.assertLess(gain_db(spain, 300), -30)                    # steep low cut, as the MCC Spain lines
        self.assertLess(gain_db(spain, 6300), -30)                   # and high cut
        gentle = ae.normalize_radio(dict(spain, preset="custom", slope_db_oct=12))
        self.assertGreater(gain_db(gentle, 300), gain_db(spain, 300) + 10)
        lifted = ae.normalize_radio(dict(spain, preset="custom", presence_db=6))
        self.assertAlmostEqual(gain_db(lifted, 1520), 6, delta=1.0)  # peak at the band's geometric centre

    def test_radio_render_is_deterministic_and_bounded(self):
        pcm = ae.float_to_pcm16(speech(1.0, amp=0.9))
        e = ae.normalize({"radio": {"preset": "english"}}, SRC)  # drive and hiss
        r1, r2 = ae.render(pcm, e, global_gain_db=4.0), ae.render(pcm, e, global_gain_db=4.0)
        self.assertEqual(r1["pcm"], r2["pcm"])
        self.assertEqual(len(r1["pcm"]), len(pcm))  # the filter never changes the length
        st = r1["stats"]
        self.assertEqual(st["radio"]["preset"], "english")
        self.assertLessEqual(st["output_peak_dbfs"], ae.PEAK_CEILING_DB + 0.01)
        self.assertIsNone(ae.render(pcm, ae.normalize({"trim_start_s": 0.1}, SRC))["stats"]["radio"])
        quiet = ae.render(ae.float_to_pcm16([0.0] * FS), ae.normalize({"radio": {"preset": "english"}}, SRC))
        self.assertGreater(max(abs(v) for v in ae.pcm16_to_float(quiet["pcm"])), 0)  # hiss in silence

    def test_radio_clicks_go_around_the_line_at_their_own_level(self):
        pcm = ae.float_to_pcm16(speech(1.0, amp=0.3))
        e = ae.normalize({"radio": {"preset": "spain"}}, SRC)
        self.assertTrue(e["radio"]["clicks"])  # the Spain preset has them
        with self.assertRaises(ae.EditError):  # never rendered without the MCC clicks
            ae.render(pcm, e)
        c = fake_clicks()
        r = ae.render(pcm, e, global_gain_db=4.0, clicks=c)
        y = ae.pcm16_to_float(r["pcm"])
        n = len(pcm) // 2
        self.assertEqual(len(y), len(c["in"]) + n + len(c["out"]))
        self.assertEqual(y[:len(c["in"])], c["in"])          # unfiltered, not gained
        self.assertEqual(y[len(y) - len(c["out"]):], c["out"])
        self.assertEqual(r["stats"]["radio"]["clicks"]["in_s"], 0.01)
        off = ae.render(pcm, ae.normalize({"radio": {"preset": "spain", "clicks": False}}, SRC), global_gain_db=4.0, clicks=c)
        self.assertEqual(len(off["pcm"]) // 2, n)
        # a recipe saved before the field existed is valid and has no clicks
        old = dict(e, radio={k: v for k, v in e["radio"].items() if k != "clicks"})
        self.assertEqual(ae.problems(old), [])
        self.assertFalse(ae.normalize(old)["radio"]["clicks"])  # re-saving never turns clicks on
        self.assertEqual(len(ae.render(pcm, old)["pcm"]) // 2, n)
        self.assertIn("no clicks", ae.summary(ae.normalize({"radio": {"preset": "spain", "clicks": False}}, SRC)))
        with self.assertRaises(ae.EditError):
            ae.normalize({"radio": {"preset": "spain", "clicks": "yes"}}, SRC)


class EchoTests(unittest.TestCase):
    def test_echo_rules_and_schema(self):
        r = ae.normalize({"radio": {"preset": "spain_eco"}, "echo": {"preset": "spain"}}, SRC)
        self.assertEqual(r["echo"], dict(ae.ECHO_PRESETS["spain"], preset="spain"))
        self.assertEqual(r["radio"]["presence_hz"], 2500)
        self.assertFalse(r["radio"]["clicks"])
        self.assertEqual(ae.normalize(r), r)  # idempotent
        self.assertEqual(ae.summary(r), "radio spain_eco 350–8000 Hz · echo spain 140 ms")
        self.assertFalse(ae.is_identity(ae.normalize({"echo": {"preset": "english"}}, SRC)))
        self.assertNotIn("presence_hz", ae.normalize({"radio": {"preset": "spain"}}, SRC)["radio"])  # unchanged form
        c = ae.normalize({"echo": {"preset": "custom", "delay_ms": 200, "feedback_db": None, "slap_db": None}}, SRC)
        self.assertIn("echo custom 200 ms", ae.summary(c))
        for bad in ({"preset": "cave"}, {"preset": "custom", "delay_ms": 10}, {"preset": "custom", "diffusion": 2},
                    {"preset": "custom", "echo_db": 0}, {"preset": "spain", "wet": 1}, "spain"):
            with self.assertRaises(ae.EditError, msg=bad):
                ae.normalize({"echo": bad}, SRC)
        with self.assertRaises(ae.EditError):
            ae.normalize({"radio": {"preset": "custom", "presence_db": 3, "presence_hz": 50}}, SRC)
        from common.jsonschema_lite import validate
        schema = load_schema("manual-mappings-3")
        full = {**schema["$defs"]["slot"]["properties"]["audio"]["properties"]["edit"], "$defs": schema["$defs"]}
        self.assertEqual(validate(r, full), [])
        self.assertEqual(validate(c, full), [])
        self.assertTrue(validate(dict(r, echo=dict(r["echo"], delay_ms=5)), full))

    def test_english_echo_is_two_clean_taps(self):
        x = [0.0] * FS
        x[1000] = 0.5  # an impulse shows the taps exactly
        e = ae.normalize_echo({"preset": "english"})
        y, st = ae.echo_effect(x, e)
        self.assertEqual(len(y), FS + ae.echo_tail_samples(e))
        self.assertEqual(st["tail_s"], round(ae.echo_tail_samples(e) / FS, 3))
        g = 10 ** (-12 / 20) * 0.5
        self.assertAlmostEqual(y[1000 + int(round(0.030 * FS))], g, places=6)   # slap at 30 ms
        self.assertAlmostEqual(y[1000 + int(round(0.150 * FS))], g, places=6)   # echo at 150 ms
        self.assertAlmostEqual(y[1000 + int(round(0.300 * FS))], 0.0, places=9)  # no feedback: no second repeat

    def test_spain_echo_repeats_decay_and_render_is_deterministic(self):
        x = [0.0] * FS
        x[1000] = 0.5
        e = ae.normalize_echo({"preset": "spain"})
        y, _ = ae.echo_effect(x, e)
        D = int(round(0.140 * FS))

        def energy(at):
            return sum(v * v for v in y[1000 + at - 300:1000 + at + 1200])
        first, second, third = energy(D), energy(2 * D), energy(3 * D)
        self.assertGreater(first, second)
        self.assertGreater(second, third)
        self.assertGreater(third, 0)
        pcm = ae.float_to_pcm16(speech(1.0, amp=0.3))
        rec = ae.normalize({"radio": {"preset": "spain_eco"}, "echo": {"preset": "spain"}}, SRC)
        r1, r2 = ae.render(pcm, rec, global_gain_db=4.0), ae.render(pcm, rec, global_gain_db=4.0)
        self.assertEqual(r1["pcm"], r2["pcm"])
        self.assertEqual(len(r1["pcm"]) // 2, len(pcm) // 2 + ae.echo_tail_samples(e))
        self.assertEqual(r1["stats"]["echo"]["preset"], "spain")
        self.assertLessEqual(r1["stats"]["output_peak_dbfs"], ae.PEAK_CEILING_DB + 0.01)


V933 = {"ce_line_ref": "vo_scr_m06_00740_victor933#0", "language": "Spanish(Mexico)"}


def fake_static():
    tex = ae.pcm16_to_float(ae.float_to_pcm16([0.05 * math.sin(i * 1.7) * math.sin(i / 37) for i in range(8820)]))
    return {"static": tex, "sha256": "c" * 64, "reference": {"slot_id": "es:fake#0"}}


class InterferenceTests(unittest.TestCase):
    REGIONS = [{"label": "a", "kind": "partial", "start_s": 0.02, "end_s": 0.18, "intensity_db": 0},  # speech() is loud here
               {"label": "b", "kind": "masked", "start_s": 0.6, "end_s": 0.9, "intensity_db": 0}]

    def test_only_victor_933_and_region_rules(self):
        e = ae.normalize({"interference": {"regions": self.REGIONS}}, V933)
        self.assertEqual(e["interference"]["engine"], ae.INTERFERENCE_ENGINE)
        self.assertEqual(ae.normalize(e), e)
        self.assertIn("interference 2 regions (1 masked, 1 partial)", ae.summary(e))
        with self.assertRaises(ae.EditError):  # every other recording is refused
            ae.normalize({"interference": {"regions": self.REGIONS}}, SRC)
        self.assertTrue(ae.problems(dict(e, for_source=SRC)))
        bad_sets = ([dict(self.REGIONS[0], end_s=0.01)], [dict(self.REGIONS[0], kind="loud")],
                    [dict(self.REGIONS[0], intensity_db=20)], [self.REGIONS[0], dict(self.REGIONS[1], start_s=0.1)])
        for regions in bad_sets:
            with self.assertRaises(ae.EditError, msg=regions):
                ae.normalize({"interference": {"regions": regions}}, V933)
        self.assertTrue(ae.problems(e, 0.8))  # a region past the end of the recording
        from common.jsonschema_lite import validate
        schema = load_schema("manual-mappings-3")
        full = {**schema["$defs"]["slot"]["properties"]["audio"]["properties"]["edit"], "$defs": schema["$defs"]}
        self.assertEqual(validate(e, full), [])

    def test_masked_mutes_partial_ducks_and_nothing_else_changes(self):
        x = speech(1.2, amp=0.3)
        pcm = ae.float_to_pcm16(x)
        e = ae.normalize({"interference": {"regions": self.REGIONS}}, V933)
        with self.assertRaises(ae.EditError):  # never rendered without MCC's static
            ae.render(pcm, e)
        y = ae.pcm16_to_float(ae.render(pcm, e, static=fake_static())["pcm"])
        mute = dict(fake_static(), static=[0.0] * 8820)
        sp = ae.pcm16_to_float(ae.render(pcm, e, static=mute)["pcm"])  # the speech that is left
        self.assertEqual(len(y), len(x))
        self.assertEqual(set(sp[int(0.6 * FS):int(0.9 * FS)]), {0.0})               # masked: no speech at all
        self.assertTrue(any(y[int(0.6 * FS):int(0.9 * FS)]))                        # ...static instead
        ratio = max(abs(v) for v in sp[int(0.05 * FS):int(0.15 * FS)]) / max(abs(v) for v in x[int(0.05 * FS):int(0.15 * FS)])
        self.assertAlmostEqual(20 * math.log10(ratio), -ae.PARTIAL_DUCK_DB, delta=0.1)  # partial: ducked
        ramp = int(ae.INTERFERENCE_RAMP_MS * FS / 1000)
        orig = ae.pcm16_to_float(pcm)
        outside = [k for k in range(len(y)) if not (int(0.02 * FS) - ramp <= k < int(0.18 * FS) + ramp
                                                     or int(0.6 * FS) - ramp <= k < int(0.9 * FS) + ramp)]
        self.assertTrue(all(y[k] == orig[k] for k in outside))
        self.assertEqual(y, ae.pcm16_to_float(ae.render(pcm, e, static=fake_static())["pcm"]))  # deterministic

    def test_regions_stay_on_the_source_timeline_under_trims_and_cuts(self):
        pcm = ae.float_to_pcm16(speech(1.2, amp=0.3))
        mute = dict(fake_static(), static=[0.0] * 8820)
        e = ae.normalize({"trim_start_s": 0.1, "cuts": [{"start_s": 0.45, "end_s": 0.55}], "crossfade_ms": 0,
                          "interference": {"regions": self.REGIONS}}, V933)
        sp = ae.pcm16_to_float(ae.render(pcm, e, static=mute)["pcm"])
        a, b = ae.spliced_position(0.6, e), ae.spliced_position(0.9, e)
        self.assertEqual((a, b), (round(0.4 * FS), round(0.7 * FS)))  # 0.1 s trim + 0.1 s cut before it
        self.assertEqual(set(sp[a:b]), {0.0})


class RadioClickTests(unittest.TestCase):
    def test_cut_takes_the_fixed_ranges_with_fades(self):
        x = [0.5] * radio_clicks.REFERENCE_SAMPLES
        c = radio_clicks.cut(x)
        self.assertEqual((len(c["in"]), len(c["out"])), (radio_clicks.IN_END, radio_clicks.OUT_LEN))
        self.assertEqual(c["in"][0], 0.5)
        self.assertLess(c["in"][-1], 0.01)     # faded into the line
        self.assertLess(c["out"][0], 0.01)     # faded in from the line
        self.assertEqual(c["out"][-1], 0.5)
        with self.assertRaises(radio_clicks.ClickError):
            radio_clicks.cut([0.0] * 1000)     # not the reference recording

    def test_a_different_recording_is_refused_by_the_pins(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_wav(Path(d) / "ref.wav", [0.1] * radio_clicks.REFERENCE_SAMPLES)
            with self.assertRaises(radio_clicks.ClickError):
                radio_clicks.from_wav(p)


@unittest.skipUnless(FFMPEG and HAVE_CELT, "ffmpeg and libcelt needed")
class ParityTests(unittest.TestCase):
    """The M4 preview is byte-for-byte what M6 encodes (decoded by the same libcelt)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = write_wav(self.root / "ce.wav", speech(1.7, fs=48000, amp=0.08), 48000)
        self.celt = Celt011()

    def tearDown(self):
        self.celt.close()
        self.tmp.cleanup()

    def pcm_of(self, path):
        with wave.open(str(path), "rb") as w:
            return w.readframes(w.getnframes())

    def test_edited_preview_equals_m6_build(self):
        e = ae.normalize({"trim_start_s": 0.1, "cuts": [{"start_s": 0.8, "end_s": 0.9}],
                          "silences": [{"at_s": 0.5, "dur_s": 0.25}, {"at_s": 0.8, "dur_s": 0.1}], "fade_in_ms": 10}, SRC)
        prev = EditPreview(self.root, FFMPEG, Celt011)
        p = prev.render(self.src, e, -15.0, 3.0)
        built = derive_processed(self.src, e, ffmpeg=FFMPEG, celt=self.celt, out_root=self.root / "derived",
                                 ref_lufs=-15.0, global_gain_db=3.0)
        self.assertEqual(self.pcm_of(prev.path(p["key"], "edited")), built["pcm"])
        n = len(built["pcm"])
        self.assertEqual(self.pcm_of(prev.path(p["key"], "encoded")), built["decoded"][CODEC_DELAY * 2:CODEC_DELAY * 2 + n])
        self.assertEqual(p["stats"]["encoded_sample_count"], built["sample_count"])
        recipe = json.loads((built["dir"] / "recipe.json").read_text(encoding="utf-8"))
        self.assertEqual([s["op"] for s in recipe["steps"]],
                         ["ffmpeg_convert", "audio_edit", "global_gain", "pad_end", "celt_encode"])
        self.assertEqual(recipe["steps"][1]["recipe"], e)
        self.assertEqual(prev.render(self.src, e, -15.0, 3.0)["key"], p["key"])  # cached
        self.assertNotEqual(prev.render(self.src, e, -15.0, 0.0)["key"], p["key"])  # gain is part of the preview
        self.assertEqual(self.pcm_of(self.src)[:100], ae.float_to_pcm16(speech(1.7, fs=48000, amp=0.08))[:100])  # original intact

    def test_radio_preview_equals_m6_build(self):
        e = ae.normalize({"trim_start_s": 0.05, "radio": {"preset": "spain"}}, SRC)
        prev = EditPreview(self.root, FFMPEG, Celt011)
        p = prev.render(self.src, e, None, 4.0, clicks=fake_clicks())
        built = derive_processed(self.src, e, ffmpeg=FFMPEG, celt=self.celt, out_root=self.root / "derived",
                                 global_gain_db=4.0, clicks=fake_clicks())
        self.assertEqual(self.pcm_of(prev.path(p["key"], "edited")), built["pcm"])
        recipe = json.loads((built["dir"] / "recipe.json").read_text(encoding="utf-8"))
        self.assertIn("radio spain", recipe["steps"][1]["summary"])
        self.assertIn("radio_clicks", [s["op"] for s in recipe["steps"]])

    def test_interference_preview_equals_m6_build(self):
        e = ae.normalize({"radio": {"preset": "spain", "clicks": False},
                          "interference": {"regions": InterferenceTests.REGIONS}}, V933)
        prev = EditPreview(self.root, FFMPEG, Celt011)
        p = prev.render(self.src, e, None, 4.0, static=fake_static())
        built = derive_processed(self.src, e, ffmpeg=FFMPEG, celt=self.celt, out_root=self.root / "derived",
                                 global_gain_db=4.0, static=fake_static())
        self.assertEqual(self.pcm_of(prev.path(p["key"], "edited")), built["pcm"])
        n = len(built["pcm"])
        self.assertEqual(self.pcm_of(prev.path(p["key"], "encoded")), built["decoded"][CODEC_DELAY * 2:CODEC_DELAY * 2 + n])
        recipe = json.loads((built["dir"] / "recipe.json").read_text(encoding="utf-8"))
        self.assertIn("interference", [s["op"] for s in recipe["steps"]])

    def test_unedited_line_preview_equals_the_build(self):
        prev = EditPreview(self.root, FFMPEG, Celt011)
        p = prev.render(self.src, dict(ae.EDIT_ZERO), None, 3.0)   # global gain only
        built = derive_processed(self.src, dict(ae.EDIT_ZERO), ffmpeg=FFMPEG, celt=self.celt,
                                 out_root=self.root / "derived", global_gain_db=3.0)
        n = len(built["pcm"])
        self.assertEqual(self.pcm_of(prev.path(p["key"], "encoded")), built["decoded"][CODEC_DELAY * 2:CODEC_DELAY * 2 + n])
        self.assertEqual(p["stats"]["global_gain_applied_db"], 3.0)
        recipe = json.loads((built["dir"] / "recipe.json").read_text(encoding="utf-8"))
        self.assertEqual([s["op"] for s in recipe["steps"]], ["ffmpeg_convert", "global_gain", "pad_end", "celt_encode"])

    def test_zero_gain_unedited_preview_equals_the_original_pipeline(self):
        prev = EditPreview(self.root, FFMPEG, Celt011)
        p = prev.render(self.src, dict(ae.EDIT_ZERO), None, 0.0)
        old = derive(self.src, ffmpeg=FFMPEG, celt=self.celt, out_root=self.root / "derived")
        self.assertEqual(self.pcm_of(prev.path(p["key"], "edited")), to_mcc_pcm(FFMPEG, self.src))
        n = len(old["pcm"])
        self.assertEqual(self.pcm_of(prev.path(p["key"], "encoded")), old["decoded"][CODEC_DELAY * 2:CODEC_DELAY * 2 + n])
        self.assertTrue(p["stats"]["identity"])


class StubCe:
    """CE audio provider for M4 tests: every line plays one synthetic 2-second WAV."""

    def __init__(self, wav):
        self.path = wav

    def cached(self, *_a):
        return self.path

    def wav(self, *_a):
        return self.path


class M4EditTests(AppTestBase):
    def setUp(self):
        super().setUp()
        self.wav = write_wav(self.root / "work/test/ce.wav", speech(2.0))
        self.app = M4App(self.root, ce_audio=StubCe(self.wav), today=lambda: "2026-10-09", run_validator=False)

    def test_an_audio_save_without_an_edit_keeps_the_stored_trim(self):
        # The Studio omits `edit` unless the user changes it. Sending an identity recipe instead would
        # reset a saved trim (the server treats an identity edit as "reset"), so this must hold.
        self.slot = "es:Z10_010_keyes#0"
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0"}],
                         "edit": {"trim_start_s": 0.05, "trim_end_s": 0, "gap_s": 0}})
        self.assertEqual(self.app.slot(self.slot)["mapping"]["audio"]["edit"]["trim_start_s"], 0.05)
        self.save(audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0"}]})
        self.assertEqual(self.app.slot(self.slot)["mapping"]["audio"]["edit"]["trim_start_s"], 0.05)

    def edit(self, **kw):
        return dict({"trim_start_s": 0.1, "cuts": [{"start_s": 1.0, "end_s": 1.2}], "fade_in_ms": 10}, **kw)

    def audio(self, edit=None, lang="Spanish(Mexico)"):
        a = {"source": "ce", "sources": [{"ce_line_ref": "line_a#0", "language": lang}]}
        if edit is not None:
            a["edit"] = edit
        return a

    def test_recipe_is_saved_with_the_audio_decision(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]}, audio=self.audio(self.edit()),
                  radio_effect={"needed": True})
        a = self.doc()["slots"][0]["audio"]
        self.assertEqual(a["edit"]["for_source"], SRC)
        self.assertEqual(a["edit"]["cuts"], [{"start_s": 1, "end_s": 1.2}])
        self.assertEqual(a["status"], "draft")
        d = self.app.slot(self.slot)
        self.assertFalse(d["edit"]["identity"])
        self.assertTrue(self.doc()["slots"][0]["radio_effect"]["needed"])  # flag kept, nothing applied
        self.assertEqual([s["slot_id"] for s in self.app.slots("z10", status="edited")["slots"]], [self.slot])
        self.assertTrue(self.app.slots("z10")["slots"][0]["edited"])
        # sending no edit keeps it while the source is the same
        self.save(audio=self.audio(), notes="n")
        self.assertEqual(self.doc()["slots"][0]["audio"]["edit"]["fade_in_ms"], 10)
        # reset
        self.save(audio=self.audio({}))
        self.assertEqual(self.doc()["slots"][0]["audio"]["edit"], {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0})

    def test_approved_recipe_is_immutable_until_needs_rework(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]}, audio=self.audio(self.edit()),
                  actions=[{"action": "approve", "field": "audio"}])
        approved = copy.deepcopy(self.doc()["slots"][0]["audio"])
        self.assertEqual(approved["status"], "approved")
        with self.assertRaises(ApiError) as cm:
            self.save(audio=self.audio(self.edit(fade_in_ms=20)))
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(ApiError):
            self.save(audio=self.audio({}))                     # reset is a change too
        self.assertEqual(self.doc()["slots"][0]["audio"], approved)
        self.save(actions=[{"action": "needs_rework", "field": "audio"}])
        a = self.doc()["slots"][0]["audio"]
        self.assertEqual((a["status"], a["revision"], a["edit"]), ("needs_rework", 2, approved["edit"]))
        self.save(audio=self.audio(self.edit(fade_in_ms=20)))
        self.assertEqual(self.doc()["slots"][0]["audio"]["edit"]["fade_in_ms"], 20)

    def test_an_edit_never_moves_to_another_recording(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]}, audio=self.audio(self.edit()))
        self.save(audio=self.audio(lang="English(US)"))                  # source changed, edit not sent
        self.assertTrue(self.doc()["slots"][0]["audio"]["edit"] == {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0})
        self.save(audio=self.audio(self.edit(), lang="English(US)"))
        self.assertEqual(self.doc()["slots"][0]["audio"]["edit"]["for_source"]["language"], "English(US)")
        with self.assertRaises(ApiError) as cm:
            self.save(audio={"source": "keep_original", "sources": [], "edit": self.edit()})
        self.assertEqual(cm.exception.status, 400)
        self.save(audio={"source": "keep_original", "sources": []})        # keep Spain: edits dropped
        self.assertEqual(self.doc()["slots"][0]["audio"]["edit"], {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0})

    def test_invalid_edit_is_refused_before_writing(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]}, audio=self.audio())
        before = (self.root / "mappings/manual_mappings.json").read_bytes()
        for bad, status in ((self.edit(trim_end_s=1.9), 422), (self.edit(trim_start_s=1.5), 400),
                            (self.edit(speed=1.1), 400), (self.edit(gain_db=2), 400), ("x", 400)):
            with self.assertRaises(ApiError) as cm:
                self.save(audio=self.audio(bad))
            self.assertEqual(cm.exception.status, status)
        self.assertEqual((self.root / "mappings/manual_mappings.json").read_bytes(), before)

    def test_preview_needs_the_editor_and_never_writes_mappings(self):
        with self.assertRaises(ApiError) as cm:
            self.app.edit_preview({"slot_id": self.slot, **SRC, "edit": {}})
        self.assertEqual(cm.exception.status, 503)
        if not (FFMPEG and HAVE_CELT):
            return
        app = M4App(self.root, ce_audio=StubCe(self.wav), editor=EditPreview(self.root, FFMPEG, Celt011),
                    today=lambda: "2026-10-09", run_validator=False)
        before = {p: p.read_bytes() for p in (self.root / "mappings").glob("*")}
        r = app.edit_preview({"slot_id": self.slot, **SRC, "edit": self.edit(loudness={"mode": "off", "offset_db": 0})})
        self.assertFalse(r["identity"])
        self.assertEqual((r["export_config"]["source"], r["stats"]["global_gain_requested_db"]), ("default", 4.0))
        self.assertTrue(app.preview_wav(r["key"], "encoded").is_file())
        self.assertLess(r["stats"]["output_s"], 2.0)
        with self.assertRaises(ApiError):
            app.edit_preview({"slot_id": self.slot, **SRC, "edit": self.edit(loudness={"mode": "match_mcc", "offset_db": 0})})  # matching was removed
        with self.assertRaises(ApiError):
            app.preview_wav("../../mappings", "encoded")
        self.assertEqual({p: p.read_bytes() for p in (self.root / "mappings").glob("*")}, before)


class ValidatorAndPlanTests(M4EditTests):
    def approved_edited(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]}, audio=self.audio(self.edit()),
                  radio_effect={"needed": True}, actions=[{"action": "approve", "field": "audio"}])
        return self.doc()

    def plan(self, doc):
        return plan_audio(doc, ["z10"], slot_index=self.app.slot_index, ce_lines=self.app.ce_lines,
                          ce_idx=self.app.ce_idx, mcc_idx=self.app.mcc_idx)

    def findings(self, doc):
        f, _ = validate_mappings(doc, load_schema("manual-mappings-3"), ce=self.app.ce_idx, mcc=self.app.mcc_idx,
                                 local=None, verifications={"verifications": []}, current_pins={})
        return {x["code"] for x in f if x["severity"] == "error"}

    def test_m6_plans_edited_lines_and_keeps_flags(self):
        doc = self.approved_edited()
        e = next(x for x in self.plan(doc)["entries"] if x["slot_id"] == self.slot)
        self.assertEqual((e["action"], e["reason"], e["radio_effect"]), ("replace", "approved CE audio (edited)", True))
        self.assertEqual(e["edit"], doc["slots"][0]["audio"]["edit"])
        self.assertIn("cut", e["edit_summary"])
        self.assertEqual(self.findings(doc), set())
        other = copy.deepcopy(doc)
        other["slots"][0]["audio"]["edit"]["for_source"]["language"] = "English(US)"
        e2 = self.plan(other)["entries"][0]
        self.assertEqual(e2["action"], "not_eligible")
        self.assertIn("edit recipe", e2["reason"])
        self.assertIn("audio_edit_source_mismatch", self.findings(other))
        bad = copy.deepcopy(doc)
        del bad["slots"][0]["audio"]["edit"]["engine"]   # schema-valid, but not a recipe this engine knows
        self.assertIn("invalid_audio_edit", self.findings(bad))
        gap = copy.deepcopy(doc)
        gap["slots"][0]["audio"]["edit"]["gap_s"] = 0.2
        self.assertIn("gap", self.plan(gap)["entries"][0]["reason"])

    def test_install_guard_sees_a_changed_recipe(self):
        doc = self.approved_edited()
        built = self.plan(doc)["entries"]
        changed = copy.deepcopy(doc)
        changed["slots"][0]["audio"]["edit"]["fade_in_ms"] = 30
        self.assertEqual(compare_plans(built, self.plan(changed)["entries"])["changed_or_revoked"], [self.slot])
        self.assertEqual(compare_plans(built, self.plan(doc)["entries"])["changed_or_revoked"], [])

    def test_unedited_lines_plan_exactly_as_before(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]}, audio=self.audio(),
                  actions=[{"action": "approve", "field": "audio"}])
        e = self.plan(self.doc())["entries"][0]
        self.assertEqual((e["action"], e["reason"], e["edit"]), ("replace", "approved CE audio", None))
        old_manifest_entry = {k: v for k, v in e.items() if k not in ("edit", "edit_summary")}  # pre-editor builds
        self.assertEqual(compare_plans([old_manifest_entry], [e])["changed_or_revoked"], [])


if __name__ == "__main__":
    unittest.main()
