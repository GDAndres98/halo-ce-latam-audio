"""Mute / No replacement (owner request 2026-10-15, docs/mute-language-permutations.md §1): the decision in the
Studio, the validator's rules, M6 planning, the shared-subtitle rule, progress counts and the silent stream.
Synthetic data only; the CELT round trip is skipped when vgmstream's libcelt is absent.

Run: python -m unittest tests.test_mute
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.celt011 import DEFAULT_DLL, FRAME_SAMPLES, Celt011, split_fmod_frames  # noqa: E402
from common.m6_build import compare_plans, entry_group, plan_audio, subtitle_plan  # noqa: E402
from common.project_validation import level_progress  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from test_m4 import make_root  # noqa: E402

KEYES0, KEYES1, CORTANA = "es:Z10_010_keyes#0", "es:Z10_010_keyes#1", "es:Z10_020_cortana#0"
MUTE = {"source": "mute", "mute_reason": "no Campaign Evolved equivalent; the scene works without it"}
NO_EQ = {"status": "no_equivalent", "ce_line_refs": []}


class MuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        cat = self.root / "work/mcc/catalog/z10.jsonl"
        recs = [json.loads(x) for x in cat.read_text().splitlines()]
        take = dict(recs[0]["samples"]["spanish"][0], index=3, subsong=4, name_occurrence_in_bank=1, ordinal_in_tag=1,
                    slot_id=KEYES1)  # a second take of z10_010_keyes: one tag, one subtitle key, two slots
        recs[0]["samples"]["spanish"].append(take)
        recs[0]["slot_ids"].append(KEYES1)
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.app = M4App(self.root, today=lambda: "2026-10-15", run_validator=False)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, slot, **body):
        detail = self.app.slot(slot)
        body.update(slot_id=slot, loaded_sha256=detail["sha256"]["mappings"], local_sha256=detail["sha256"]["local"])
        return self.app.save(body)

    def doc(self):
        return json.loads((self.root / "mappings/manual_mappings.json").read_text(encoding="utf-8"))

    def slot(self, slot_id):
        return next(s for s in self.doc()["slots"] if s["slot_id"] == slot_id)

    def idx(self):
        return dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                    mcc_idx=self.app.mcc_idx)

    def plan(self, doc=None):
        return {e["slot_id"]: e for e in plan_audio(doc or self.doc(), ["z10"], **self.idx())["entries"]}

    def sub_plan(self):
        return subtitle_plan(self.doc(), {"z10"}, local=None, tables={t: self.app.loc[t] for t in ("SU", "SP")},
                             **self.idx())

    # ------------------------------------------------------------------ the decision
    def test_mute_is_its_own_decision_with_a_reason(self):
        self.save(KEYES0, match=NO_EQ, audio=MUTE)
        s = self.slot(KEYES0)
        self.assertEqual((s["match"]["status"], s["audio"]["source"], s["audio"]["status"]),
                         ("no_equivalent", "mute", "draft"))
        self.assertEqual(s["audio"]["mute_reason"], MUTE["mute_reason"])
        self.assertEqual(s["audio"]["sources"], [])
        self.assertEqual(s["subtitle"]["source"], "keep_original")  # the subtitle is a separate decision
        self.assertEqual(self.plan()[KEYES0]["action"], "keep_original")  # a draft never mutes anything

    def test_mute_needs_a_reason_and_no_equivalent(self):
        with self.assertRaises(ApiError) as e:
            self.save(KEYES0, match=NO_EQ, audio={"source": "mute", "mute_reason": "  "})
        self.assertEqual(e.exception.status, 400)
        with self.assertRaises(ApiError) as e:
            self.save(KEYES0, match={"status": "unreviewed", "ce_line_refs": []}, audio=MUTE)
        self.assertEqual(e.exception.status, 422)
        self.assertTrue(any("mute_requires_no_equivalent" in d for d in e.exception.details))
        with self.assertRaises(ApiError):
            self.save(KEYES0, match=NO_EQ, audio=MUTE, radio_effect={"needed": True})

    def test_approved_mute_is_locked_and_can_be_reverted(self):
        self.save(KEYES0, match=NO_EQ, audio=MUTE, actions=[{"action": "approve", "field": "audio"}])
        a = self.slot(KEYES0)["audio"]
        self.assertEqual((a["status"], a["revision"]), ("approved", 1))
        with self.assertRaises(ApiError) as e:  # approved: read-only, even the reason
            self.save(KEYES0, audio=dict(MUTE, mute_reason="another reason"))
        self.assertEqual(e.exception.status, 409)
        self.save(KEYES0, actions=[{"action": "needs_rework", "field": "audio"}])
        self.save(KEYES0, match={"status": "unreviewed", "ce_line_refs": []}, audio={"source": "keep_original"})
        a = self.slot(KEYES0)["audio"]
        self.assertEqual((a["source"], a["status"], a["revision"]), ("keep_original", "needs_rework", 2))
        self.assertNotIn("mute_reason", a)  # only a muted decision carries a reason (schema)
        self.assertEqual(self.plan()[KEYES0]["action"], "keep_original")

    def test_slot_filter_and_progress(self):
        self.save(KEYES0, match=NO_EQ, audio=MUTE, actions=[{"action": "approve", "field": "audio"}])
        self.save(CORTANA, match=NO_EQ)  # no equivalent, but Spain's audio stays
        rows = self.app.slots("z10", status="muted")["slots"]
        self.assertEqual([r["slot_id"] for r in rows], [KEYES0])
        p = level_progress([KEYES0, KEYES1, CORTANA], self.doc())
        self.assertEqual((p["no_equivalent"], p["muted"], p["muted_approved"], p["matched"]), (2, 1, 1, 0))

    # ------------------------------------------------------------------ M6 planning
    def test_plan_mutes_only_approved_mono_lines_without_drift(self):
        self.save(KEYES0, match=NO_EQ, audio=MUTE, actions=[{"action": "approve", "field": "audio"}])
        e = self.plan()[KEYES0]
        self.assertEqual((e["action"], e["mute_reason"], entry_group(e)), ("mute", MUTE["mute_reason"], "muted"))
        drift = self.doc()
        drift["slots"][0]["audio"]["fingerprint"]["mcc"]["data_sha256"] = "0" * 64
        self.assertIn("drift", self.plan(drift)[KEYES0]["reason"])
        stereo = copy.deepcopy(self.doc())
        idx = self.app.slot_index[KEYES0][2]
        idx["channels"] = 2
        try:
            self.assertEqual(self.plan(stereo)[KEYES0]["action"], "not_eligible")
        finally:
            idx["channels"] = 1

    def test_a_built_mute_that_was_revoked_makes_the_build_stale(self):
        self.save(KEYES0, match=NO_EQ, audio=MUTE, actions=[{"action": "approve", "field": "audio"}])
        built = list(self.plan().values())
        self.save(KEYES0, actions=[{"action": "needs_rework", "field": "audio"}])
        self.assertEqual(compare_plans(built, list(self.plan().values()))["changed_or_revoked"], [KEYES0])
        self.assertEqual(compare_plans(list(self.plan().values()), built)["newly_eligible"], [KEYES0])

    # ------------------------------------------------------------------ shared subtitles
    def test_no_subtitle_on_one_take_only_is_a_conflict(self):
        self.save(KEYES0, match=NO_EQ, audio=MUTE, subtitle={"source": "none"},
                  actions=[{"action": "approve", "field": "subtitle"}])
        p = self.sub_plan()
        self.assertEqual(p["conflicts"][0]["code"], "empty_subtitle_not_agreed_by_every_take")
        self.assertEqual(p["conflicts"][0]["takes_without_approved_none"], [KEYES1])
        self.assertEqual(p["summary"]["keys_to_write"], 0)  # the other take still plays: its subtitle stays

    def test_no_subtitle_on_every_take_writes_an_empty_entry(self):
        for s in (KEYES0, KEYES1):
            self.save(s, match=NO_EQ, audio=MUTE, subtitle={"source": "none"},
                      actions=[{"action": "approve", "field": "subtitle"}])
        p = self.sub_plan()
        self.assertEqual(p["conflicts"], [])
        k = next(k for k in p["keys"] if k["action"] == "write")
        self.assertEqual((k["text"], k["slots"]), ("", [KEYES0, KEYES1]))
        self.assertEqual(p["summary"]["empty_entries"], 1)


@unittest.skipUnless(DEFAULT_DLL.is_file(), "vgmstream libcelt-0110.dll not available")
class SilentStreamTests(unittest.TestCase):
    def test_exact_length_digital_silence_in_mcc_profile(self):
        from common.audio_pipeline import silent_stream
        from common.celt_header import frame_flags
        celt = Celt011()
        try:
            res = silent_stream(celt, 7 * FRAME_SAMPLES)
            again = silent_stream(celt, 7 * FRAME_SAMPLES)
            with self.assertRaises(ValueError):
                silent_stream(celt, 7 * FRAME_SAMPLES + 1)  # MCC samples are whole frames
        finally:
            celt.close()
        packets = split_fmod_frames(res["stream"])
        self.assertEqual((res["sample_count"], res["frames"], len(packets)), (7 * FRAME_SAMPLES, 7, 7))
        self.assertTrue(all(frame_flags(p)["silence"] for p in packets))
        self.assertEqual({len(p) for p in packets}, {370})  # CBR, like every MCC mono packet
        self.assertEqual(len(set(packets)), 1)  # one silence packet, repeated
        self.assertEqual(res["decoded"], b"\0" * (2 * 7 * FRAME_SAMPLES))
        self.assertEqual(res["stream"], again["stream"])  # deterministic

    def test_muting_a_sample_keeps_the_bank_layout(self):
        from common.audio_pipeline import silent_stream
        from common.fsb5_writer import sample_spans
        from common.m6_build import assemble, multi_structural_checks
        from test_m6_build import five_sample_bank
        original = five_sample_bank()
        celt = Celt011()
        try:
            res = silent_stream(celt, 1536)  # sample 1: 3 frames of 370-byte packets
        finally:
            celt.close()
        repl = {1: (res["stream"], res["sample_count"])}
        cand = assemble(original, repl)
        self.assertTrue(all(multi_structural_checks(original, cand, repl).values()))
        self.assertEqual(len(cand), len(original))
        self.assertEqual(sample_spans(cand), sample_spans(original))  # nothing moves

    @unittest.skipUnless(Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe").is_file(), "vgmstream not available")
    def test_m6_cli_mutes_and_checks_a_sample(self):
        sys.path.insert(0, str(ROOT / "scripts" / "build"))
        import m6_build as cli
        from common.fsb5_writer import decompose
        from test_m6_build import five_sample_bank
        original = five_sample_bank()
        entry = {"slot_id": "es:b#0", "spanish_index": 1, "original_sample_count": 1536}
        cfg = {"global_gain_db": 0.0, "level_mode": "global_gain"}
        celt = Celt011()
        try:
            cand, results = cli.build_once(original, [], None, None, celt, cfg, mutes=[entry], model=decompose(original))
        finally:
            celt.close()
        self.assertEqual(len(cand), len(original))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cand.fsb"
            path.write_bytes(cand)
            checks = cli.mute_checks(cli.DEFAULT_VGMSTREAM, path, entry, results[1])
        self.assertTrue(all(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
