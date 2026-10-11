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


if __name__ == "__main__":
    unittest.main()
