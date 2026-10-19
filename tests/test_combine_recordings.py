"""Two Campaign Evolved recordings in one replacement (docs/combine-recordings.md): join (ce_concat) and play together
(ce_mix). The render rules, the Studio save path, the validator, the M6 plan and preview == build parity.
Synthetic audio only; the ffmpeg / libcelt steps are skipped when absent.

Run: python -m unittest tests.test_combine_recordings
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import audio_combine as ac  # noqa: E402
from common import audio_edit as ae  # noqa: E402
from common.jsonschema_lite import load_schema  # noqa: E402
from common.m6_build import compare_plans, plan_audio  # noqa: E402
from common.project_validation import validate_mappings  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from test_audio_edit import FFMPEG, HAVE_CELT, speech, write_wav  # noqa: E402
from test_m4 import AppTestBase  # noqa: E402

FS = 44100
MX = "Spanish(Mexico)"
A = {"ce_line_ref": "line_a#0", "language": MX}
B = {"ce_line_ref": "line_b#0", "language": MX}


def pcm(x):
    return ae.float_to_pcm16(x)


def tone(seconds, amp=0.3):
    return speech(seconds, amp=amp)


class RenderTests(unittest.TestCase):
    def join(self, gap, parts=None):
        return ac.normalize({"parts": parts or [{}, {}], "gap_s": gap}, "concat", [A, B])

    def test_join_with_a_gap_of_silence(self):
        a, b = tone(1.0), tone(0.5)
        r = ac.render([pcm(a), pcm(b)], self.join(0.25))
        st = r["stats"]
        self.assertEqual((st["combined_s"], st["part_2_starts_s"], st["overlap_s"]), (1.75, 1.25, 0.0))
        y = ae.pcm16_to_float(r["pcm"])
        self.assertEqual(max(abs(v) for v in y[int(1.0 * FS) + 10:int(1.25 * FS) - 10]), 0.0)  # the gap is silence
        self.assertEqual(r, ac.render([pcm(a), pcm(b)], self.join(0.25)))  # deterministic

    def test_join_with_a_negative_gap_overlaps_and_both_play(self):
        a, b = tone(1.0), tone(0.5)
        st = ac.render([pcm(a), pcm(b)], self.join(-0.2))["stats"]
        self.assertEqual((st["combined_s"], st["part_2_starts_s"], st["overlap_s"]), (1.3, 0.8, 0.2))

    def test_each_part_keeps_its_own_edit(self):
        e = self.join(0, [{"trim_start_s": 0.4}, {"trim_end_s": 0.1, "fade_out_ms": 20}])
        self.assertEqual(e["parts"][0]["for_source"], A)
        self.assertEqual(e["parts"][1]["for_source"], B)
        st = ac.render([pcm(tone(1.0)), pcm(tone(0.5))], e)["stats"]
        self.assertEqual([p["edited_s"] for p in st["parts"]], [0.6, 0.4])
        self.assertEqual(st["combined_s"], 1.0)
        self.assertEqual(ac.summary(e), "join · no gap · part 1: trim 0.40/0.00 s · part 2: trim 0.00/0.10 s · fades 0/20 ms")

    def test_play_together_with_an_offset(self):
        e = ac.normalize({"offset_s": 0.5}, "mix", [A, B])
        st = ac.render([pcm(tone(1.0)), pcm(tone(1.0))], e)["stats"]
        self.assertEqual((st["first_starts_s"], st["second_starts_s"], st["combined_s"], st["overlap_s"]),
                         (0.0, 0.5, 1.5, 0.5))
        e = ac.normalize({"offset_s": -0.25}, "mix", [A, B])
        st = ac.render([pcm(tone(1.0)), pcm(tone(0.5))], e)["stats"]
        self.assertEqual((st["first_starts_s"], st["second_starts_s"], st["combined_s"]), (0.25, 0.0, 1.25))

    def test_a_sum_past_the_ceiling_is_lowered_and_reported(self):
        e = ac.normalize({"offset_s": 0}, "mix", [A, B])
        r = ac.render([pcm(tone(1.0, amp=0.8)), pcm(tone(1.0, amp=0.8))], e)
        st = r["stats"]
        self.assertLess(st["sum_trim_db"], 0)
        self.assertIn("lowered", st["warnings"][0])
        self.assertLessEqual(st["output_peak_dbfs"], ae.PEAK_CEILING_DB + 0.01)
        quiet = ac.render([pcm(tone(1.0, amp=0.1)), pcm(tone(1.0, amp=0.1))], e)["stats"]
        self.assertEqual(quiet["sum_trim_db"], 0.0)  # nothing changes when they fit

    def test_radio_and_echo_apply_to_the_result(self):
        e = ac.normalize({"offset_s": 0.2, "radio": dict(ae.RADIO_PRESETS["english"], preset="english")}, "mix", [A, B])
        st = ac.render([pcm(tone(0.6)), pcm(tone(0.6))], e)["stats"]
        self.assertIsNotNone(st["radio"])  # the filter ran on the combined audio

    def test_rules(self):
        with self.assertRaises(ae.EditError):  # effects belong to the result, not to a part
            ac.normalize({"parts": [{"radio": dict(ae.RADIO_PRESETS["spain"], preset="spain")}, {}], "gap_s": 0},
                         "concat", [A, B])
        with self.assertRaises(ae.EditError):
            ac.normalize({"offset_s": 1}, "concat", [A, B])
        with self.assertRaises(ae.EditError):
            ac.normalize({"parts": [{}, {}]}, "mix", [A, B])
        with self.assertRaises(ae.EditError):
            ac.normalize({"gap_s": 6}, "concat", [A, B])
        with self.assertRaises(ae.EditError):
            ac.normalize({}, "concat", [A])
        self.assertFalse(ae.is_identity(ac.default("concat", [A, B])))
        self.assertEqual(ac.problems(ac.default("mix", [A, B]), sources=[B, A]),
                         ["the recipe was made for other recordings or another order; reset it"])


class StubByMedia:
    """CE audio by media id: line_a (media 100) and line_b (media 200) are different recordings."""

    def __init__(self, wavs):
        self.wavs = wavs

    def wav(self, _mission, _lang, media):
        return self.wavs[media["media_id"]]

    def cached(self, *_a):
        return None


class StudioTests(AppTestBase):
    def setUp(self):
        super().setUp()
        self.wa = write_wav(self.root / "work/test/a.wav", tone(1.0))
        self.wb = write_wav(self.root / "work/test/b.wav", tone(0.6))
        self.app = M4App(self.root, ce_audio=StubByMedia({100: self.wa, 200: self.wb}), today=lambda: "2026-10-19",
                         run_validator=False)

    def combined(self, source, edit=None, sources=(A, B), **extra):
        audio = {"source": source, "sources": [dict(s) for s in sources]}
        if edit is not None:
            audio["edit"] = edit
        return self.save(match={"status": "matched", "ce_line_refs": ["line_a#0", "line_b#0"]}, audio=audio, **extra)

    def stored(self):
        return self.app.slot(self.slot)["mapping"]["audio"]

    def test_join_is_saved_approved_validated_and_planned(self):
        self.combined("ce_concat", {"parts": [{"trim_start_s": 0.2}, {}], "gap_s": -0.1})
        a = self.stored()
        self.assertEqual((a["source"], a["edit"]["mode"], a["edit"]["gap_s"], a["edit"]["parts"][0]["trim_start_s"]),
                         ("ce_concat", "concat", -0.1, 0.2))
        self.combined("ce_concat", actions=[{"action": "approve", "field": "audio"}])  # recipe kept when not sent
        a = self.stored()
        self.assertEqual((a["status"], a["edit"]["gap_s"]), ("approved", -0.1))
        self.assertEqual([s["ce_line_ref"] for s in a["fingerprint"]["sources"]], ["line_a#0", "line_b#0"])
        doc = self.doc()
        findings, _ = validate_mappings(doc, load_schema("manual-mappings-3"), ce=self.app.ce_idx, mcc=self.app.mcc_idx,
                                        local=None, verifications={"verifications": []}, current_pins={})
        self.assertEqual([f for f in findings if f["severity"] == "error"], [])
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        e = next(x for x in plan_audio(doc, ["z10"], **idx)["entries"] if x["slot_id"] == self.slot)
        self.assertEqual((e["action"], e["combine"], [s["ce_line_ref"] for s in e["sources"]]),
                         ("replace", "concat", ["line_a#0", "line_b#0"]))
        changed = copy.deepcopy(e)  # the second recording changed since the build: it must be rebuilt
        changed["sources"][1]["media"] = dict(changed["sources"][1]["media"], wem_sha256="0" * 64)
        self.assertEqual(compare_plans([changed], [e])["changed_or_revoked"], [self.slot])

    def test_play_together_and_the_recipe_follows_its_recordings(self):
        self.combined("ce_mix", {"offset_s": 0.3})
        self.assertEqual(self.stored()["edit"]["offset_s"], 0.3)
        self.combined("ce_mix", sources=(B, A))  # other order, no recipe sent: back to the default, never moved
        self.assertEqual((self.stored()["edit"]["offset_s"], self.stored()["edit"]["for_sources"]), (0, [B, A]))
        self.combined("ce_concat")  # another mode: its own default
        self.assertEqual(self.stored()["edit"], ac.default("concat", [A, B]))
        self.save(audio={"source": "ce", "sources": [A]})  # back to one recording: no combine recipe left
        self.assertTrue(ae.is_identity(self.stored()["edit"]))

    def test_refusals(self):
        for audio, status in (({"source": "ce_mix", "sources": [A]}, 400),
                              ({"source": "ce_mix", "sources": [A, B], "edit": {"parts": [{}, {}]}}, 400),
                              ({"source": "ce_concat", "sources": [A, B], "edit": {"parts": [{"trim_start_s": 0.98}, {}],
                                                                                    "gap_s": 0}}, 422)):
            with self.assertRaises(ApiError) as e:
                self.save(match={"status": "matched", "ce_line_refs": ["line_a#0", "line_b#0"]}, audio=audio)
            self.assertEqual(e.exception.status, status, audio)

    @unittest.skipUnless(FFMPEG and HAVE_CELT, "needs ffmpeg and libcelt")
    def test_preview_equals_the_build_and_never_writes_mappings(self):
        from common.audio_pipeline import CODEC_DELAY, derive_combined
        from common.celt011 import Celt011
        from common.edit_preview import EditPreview
        import wave
        app = M4App(self.root, ce_audio=StubByMedia({100: self.wa, 200: self.wb}),
                    editor=EditPreview(self.root, FFMPEG, Celt011), today=lambda: "2026-10-19", run_validator=False)
        before = {p: p.read_bytes() for p in (self.root / "mappings").glob("*")}
        edit = {"parts": [{"trim_start_s": 0.1}, {}], "gap_s": -0.15}
        r = app.edit_preview_combined({"slot_id": self.slot, "source": "ce_concat", "sources": [A, B], "edit": edit})
        self.assertEqual({p: p.read_bytes() for p in (self.root / "mappings").glob("*")}, before)
        celt = Celt011()
        try:
            built = derive_combined([self.wa, self.wb], r["edit"], ffmpeg=FFMPEG, celt=celt,
                                    out_root=self.root / "derived", global_gain_db=4.0)
        finally:
            celt.close()
        with wave.open(str(app.preview_wav(r["key"], "edited")), "rb") as w:
            self.assertEqual(w.readframes(w.getnframes()), built["pcm"])
        with wave.open(str(app.preview_wav(r["key"], "encoded")), "rb") as w:
            n = len(built["pcm"])
            self.assertEqual(w.readframes(w.getnframes()), built["decoded"][CODEC_DELAY * 2:CODEC_DELAY * 2 + n])
        recipe = json.loads((built["dir"] / "recipe.json").read_text(encoding="utf-8"))
        self.assertEqual([s["file"] for s in recipe["sources"]], ["a.wav", "b.wav"])


if __name__ == "__main__":
    unittest.main()
