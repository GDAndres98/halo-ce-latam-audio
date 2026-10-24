"""The 2026-10-11 loudness-match reset: only audio.edit.loudness changes, approvals stay, and the validator
accepts exactly that one-way change on approved decisions."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import mapping_store  # noqa: E402
from common.project_validation import check_approved_protected  # noqa: E402


def slot(mid, mode, status="approved"):
    edit = {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0, "engine": "audio-edit/1",
            "for_source": {"ce_line_ref": "x#0", "language": "Spanish(Mexico)"}, "cuts": [], "silences": [],
            "fade_in_ms": 0, "fade_out_ms": 0, "crossfade_ms": 20, "loudness": {"mode": mode, "offset_db": 0},
            "limiter": True}
    return {"mapping_id": mid, "slot_id": f"es:{mid}#0", "notes": "",
            "audio": {"status": status, "revision": 2, "source": "ce", "edit": edit, "approved_at": "2026-10-09"},
            "subtitle": {"status": status, "revision": 1}}


class LimiterRemovalTests(unittest.TestCase):
    """2026-10-11: the `limiter` setting is removed from every recipe; nothing else changes."""

    def setUp(self):
        self.doc = {"schema": "manual-mappings/3", "pins": {}, "slots": [slot("m-1", "off"), slot("m-2", "off", "draft")]}
        del self.doc["slots"][1]["audio"]["edit"]["limiter"]  # already without it

    def test_only_the_field_goes_and_approvals_stay(self):
        new, changes = mapping_store.strip_limiter(self.doc)
        self.assertEqual([(c["mapping_id"], c["previous"]) for c in changes], [("m-1", True)])
        self.assertNotIn("limiter", new["slots"][0]["audio"]["edit"])
        self.assertEqual((new["slots"][0]["audio"]["status"], new["slots"][0]["audio"]["revision"]), ("approved", 2))
        self.assertEqual(mapping_store.proof_only_limiter_removed(self.doc, new), [])
        self.assertEqual(mapping_store.strip_limiter(new)[1], [])  # idempotent

    def test_the_proof_catches_any_other_change(self):
        new, _ = mapping_store.strip_limiter(self.doc)
        new["slots"][0]["audio"]["edit"]["fade_out_ms"] = 10
        self.assertTrue(mapping_store.proof_only_limiter_removed(self.doc, new))

    def test_validator_accepts_the_removal_one_way_only(self):
        removed, _ = mapping_store.strip_limiter(self.doc)
        self.assertEqual(check_approved_protected(self.doc, removed), [])
        self.assertTrue(check_approved_protected(removed, self.doc))  # adding it back to an approved recipe
        changed = copy.deepcopy(self.doc)
        changed["slots"][0]["audio"]["edit"]["limiter"] = False
        self.assertTrue(check_approved_protected(self.doc, changed))  # changing it is not allowed either


class LoudnessResetTests(unittest.TestCase):
    def setUp(self):
        self.doc = {"schema": "manual-mappings/3", "pins": {}, "slots": [slot("m-1", "match_mcc"), slot("m-2", "off")]}

    def test_only_loudness_changes_and_only_where_matching_was_on(self):
        new, changes = mapping_store.strip_loudness_match(self.doc)
        self.assertEqual([c["mapping_id"] for c in changes], ["m-1"])
        self.assertEqual(new["slots"][0]["audio"]["edit"]["loudness"], mapping_store.LOUDNESS_OFF)
        self.assertEqual(new["slots"][0]["audio"]["status"], "approved")
        self.assertEqual(new["slots"][0]["audio"]["revision"], 2)
        self.assertEqual(mapping_store.proof_only_loudness_changed(self.doc, new), [])
        self.assertEqual(mapping_store.strip_loudness_match(new)[1], [])  # idempotent

    def test_the_proof_catches_any_other_change(self):
        new, _ = mapping_store.strip_loudness_match(self.doc)
        new["slots"][0]["audio"]["edit"]["fade_in_ms"] = 10
        self.assertTrue(mapping_store.proof_only_loudness_changed(self.doc, new))
        new, _ = mapping_store.strip_loudness_match(self.doc)
        new["slots"][1]["audio"]["revision"] = 3
        self.assertTrue(mapping_store.proof_only_loudness_changed(self.doc, new))

    def test_validator_accepts_turning_matching_off_but_not_on(self):
        reset, _ = mapping_store.strip_loudness_match(self.doc)
        self.assertEqual(check_approved_protected(self.doc, reset), [])
        turned_on = copy.deepcopy(self.doc)
        turned_on["slots"][1]["audio"]["edit"]["loudness"] = {"mode": "match_mcc", "offset_db": 0}
        codes = [f["code"] for f in check_approved_protected(self.doc, turned_on)]
        self.assertEqual(codes, ["approved_object_modified"])
        other = copy.deepcopy(reset)
        other["slots"][0]["audio"]["edit"]["fade_out_ms"] = 50  # off AND another change
        self.assertEqual([f["code"] for f in check_approved_protected(self.doc, other)], ["approved_object_modified"])


class LoudnessFieldRemovalTests(unittest.TestCase):
    """2026-10-23: the legacy, always-off `loudness` setting is removed from every recipe; nothing else changes."""

    def setUp(self):
        self.doc = {"schema": "manual-mappings/3", "pins": {}, "slots": [slot("m-1", "off"), slot("m-2", "off", "draft"),
                                                                          slot("m-3", "off")]}
        del self.doc["slots"][2]["audio"]["edit"]["loudness"]  # already without it

    def test_only_the_field_goes_and_approvals_stay(self):
        new, changes = mapping_store.strip_loudness_field(self.doc)
        self.assertEqual([c["mapping_id"] for c in changes], ["m-1", "m-2"])
        self.assertTrue(all("loudness" not in s["audio"]["edit"] for s in new["slots"]))
        self.assertEqual((new["slots"][0]["audio"]["status"], new["slots"][0]["audio"]["revision"]), ("approved", 2))
        self.assertEqual(mapping_store.proof_only_loudness_removed(self.doc, new), [])
        self.assertEqual(mapping_store.strip_loudness_field(new)[1], [])  # idempotent

    def test_a_loudness_that_is_not_off_is_never_removed(self):
        self.doc["slots"][0]["audio"]["edit"]["loudness"] = {"mode": "match_mcc", "offset_db": 0}
        new, changes = mapping_store.strip_loudness_field(self.doc)
        self.assertEqual([c["mapping_id"] for c in changes], ["m-2"])
        forced = copy.deepcopy(new)
        del forced["slots"][0]["audio"]["edit"]["loudness"]
        self.assertTrue(mapping_store.proof_only_loudness_removed(self.doc, forced))

    def test_the_proof_catches_any_other_change(self):
        new, _ = mapping_store.strip_loudness_field(self.doc)
        new["slots"][0]["audio"]["edit"]["fade_out_ms"] = 10
        self.assertTrue(mapping_store.proof_only_loudness_removed(self.doc, new))

    def test_validator_accepts_the_removal_one_way_only(self):
        removed, _ = mapping_store.strip_loudness_field(self.doc)
        self.assertEqual(check_approved_protected(self.doc, removed), [])
        other = copy.deepcopy(removed)
        other["slots"][0]["audio"]["edit"]["fade_out_ms"] = 50  # removed AND another change
        self.assertEqual([f["code"] for f in check_approved_protected(self.doc, other)], ["approved_object_modified"])
        matching = copy.deepcopy(removed)
        matching["slots"][0]["audio"]["edit"]["loudness"] = {"mode": "match_mcc", "offset_db": 0}
        self.assertTrue(check_approved_protected(removed, matching))  # matching back on an approved recipe


if __name__ == "__main__":
    unittest.main()
