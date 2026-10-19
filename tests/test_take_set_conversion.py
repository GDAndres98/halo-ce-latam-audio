"""Replacement-set conversion (docs/replacement-set-conversion.md): the read-only preview, staging, the switch,
cancel and undo, the store's checks, and what the build does at each stage. Synthetic data only (temporary roots).

Run: python -m unittest tests.test_take_set_conversion
"""
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import mapping_db, mapping_store  # noqa: E402
from common import take_set_conversion as tsc  # noqa: E402
from common.m6_build import own_set_drops, plan_audio, plan_inserts  # noqa: E402
from common.mapping_store import ProtectedError, UserAction  # noqa: E402
from common.project_validation import (  # noqa: E402
    audio_fingerprint, check_approved_protected, own_set_findings, subtitle_fingerprint, validate_mappings)
from m4_app import ApiError, M4App, default_slot  # noqa: E402
from test_m3_validation import H, ce_record, mcc_record  # noqa: E402
from test_m4 import T, make_root  # noqa: E402

GRUNT = T + "z10_050_grunt"     # three Spain takes, no subtitle entry: eligible
PAIR = T + "z10_060_marine"     # two Spain takes, no subtitle entry
STEREO = T + "z10_070_stereo"   # two stereo takes: ineligible
MX = "Spanish(Mexico)"
G = [f"es:Z10_050_grunt_{k}#0" for k in (1, 2, 3)]
P = [f"es:Z10_060_marine_{k}#0" for k in (1, 2)]
S = [f"es:Z10_070_stereo_{k}#0" for k in (1, 2)]


def multi_record(name, tag, first, n, channels=1, data="0123456789abcdef"):
    """A sound with n Spain takes at bank indexes first .. first + n - 1."""
    rec = mcc_record(f"{name}_1", tag, index=first, data=data[0])
    base = rec["samples"]["spanish"][0]
    rec["samples"]["spanish"] = [dict(base, index=first + k, subsong=first + k + 1, name_in_bank=f"{name}_{k + 1}",
                                      ordinal_in_tag=k, channels=channels, data_sha256=H[data[k]],
                                      slot_id=f"es:{name}_{k + 1}#0") for k in range(n)]
    rec["slot_ids"] = [s["slot_id"] for s in rec["samples"]["spanish"]]
    rec["lst"]["spanish"] = dict(rec["lst"]["spanish"], sample_count=n)
    return rec


def trimmed(ref, start=0.01):
    return {"trim_start_s": start, "trim_end_s": 0, "gap_s": 0, "engine": "audio-edit/1",
            "for_source": {"ce_line_ref": ref, "language": MX}, "cuts": [], "silences": [], "fade_in_ms": 0,
            "fade_out_ms": 0, "crossfade_ms": 20}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        cat = self.root / "work/mcc/catalog/z10.jsonl"
        recs = [json.loads(x) for x in cat.read_text().splitlines()]
        recs.append(mcc_record("Z10_030_death", T + "z10_030_death", index=2, data="e"))
        recs.append(multi_record("Z10_050_grunt", GRUNT, 3, 3, data="123"))
        recs.append(multi_record("Z10_060_marine", PAIR, 6, 2, data="45"))
        recs.append(multi_record("Z10_070_stereo", STEREO, 8, 2, channels=2, data="67"))
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.app = M4App(self.root, today=lambda: "2026-10-18", run_validator=False)
        self.path = self.root / "mappings/manual_mappings.json"
        self.local_path = self.root / "mappings/manual_mappings.local.json"

    def tearDown(self):
        self.tmp.cleanup()

    # -------------------------------------------------------------- decisions, made as the owner would
    def doc(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def put(self, slot_id, ref=None, *, status="approved", edit=None, source="ce", match=None, subtitle="approved",
            notes="", radio=False, mute_reason=None, **flags):
        """One line decision written through the store with the owner's approve actions (the Studio's save needs
        decoded audio to check a recipe; the store applies the same protection rules)."""
        doc, sha = mapping_store.load(self.path)
        local, _ = mapping_store.load_or_default(self.local_path, {"custom_subtitles": {}, "user_recordings": {}})
        tag = self.app.slot_index[slot_id][1]["mcc_tag"]
        mid = f"m-{len(doc['slots']) + 1:06d}"
        m = default_slot(mid, slot_id, tag)
        if source == "ce":
            m["match"] = {"status": "matched", "ce_line_refs": [ref], "decided_at": "2026-10-18", "revision": 1}
            m["audio"].update(source="ce", sources=[{"kind": "ce", "ce_line_ref": ref, "language": MX}])
            if edit:
                m["audio"]["edit"] = edit
        elif source == "mute":
            m["match"] = {"status": "no_equivalent", "ce_line_refs": [], "decided_at": "2026-10-18", "revision": 1}
            m["audio"].update(source="mute", mute_reason=mute_reason or "silence fits")
        elif source == "keep_original":
            m["match"] = match or {"status": "no_equivalent", "ce_line_refs": [], "decided_at": "2026-10-18",
                                   "revision": 1}
        if isinstance(subtitle, dict):
            m["subtitle"].update(subtitle)
        m["notes"] = notes
        m["radio_effect"]["needed"] = radio
        for k, v in flags.items():
            m[k] = {"marked": v, "set_at": "2026-10-18", "revision": 1}
        if list(m)[-1] != "notes":
            m["notes"] = m.pop("notes")
        actions = []
        if status in ("approved", "needs_rework"):
            m["audio"].update(status="approved", approved_at="2026-10-18",
                              fingerprint=audio_fingerprint(m, self.app.ce_idx, self.app.mcc_idx, local))
            actions.append(UserAction("approve", mid, "audio"))
        if subtitle == "approved" or (isinstance(subtitle, dict) and subtitle.get("status") == "approved"):
            m["subtitle"].update(status="approved", approved_at="2026-10-18",
                                 fingerprint=subtitle_fingerprint(m, self.app.ce_idx, self.app.mcc_idx, local))
            actions.append(UserAction("approve", mid, "subtitle"))
        doc["slots"].append(m)
        sha = mapping_store.save(self.path, doc, sha, user_actions=actions)
        if status == "needs_rework":
            doc = copy.deepcopy(doc)
            doc["slots"][-1]["audio"].update(status="needs_rework", revision=2, approved_at=None, fingerprint=None)
            mapping_store.save(self.path, doc, sha, user_actions=[UserAction("needs_rework", mid, "audio")])
        return mid

    def preview(self, tag=GRUNT):
        return self.app.convert_preview(tag)

    def stage(self, tag=GRUNT, ack=None, item=None, **body):
        item = item or self.preview(tag)
        return self.app.convert_stage({"confirm": True, "items": [
            {"mcc_tag": tag, "token": item["token"], **({"acknowledged": ack} if ack is not None else {})}], **body})

    def approve_take(self, tid, tag=GRUNT):
        return self.app.take_save({"mcc_tag": tag, "take_id": tid, "loaded_takes_sha256": self.app.sound(tag)["version"],
                                   "actions": [{"action": "approve", "field": "audio"}]})

    def activate(self, tag=GRUNT):
        return self.app.convert_activate({"confirm": True, "items": [
            {"mcc_tag": tag, "loaded_sound_sha256": self.app.sound(tag)["sound_version"]}]})

    def plans(self, doc=None):
        doc = doc or self.doc()
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        ins = plan_inserts(doc, ["z10"], subtitle_keys=self.app._subtitle_keys(), **idx)
        drops = own_set_drops(doc, ins)
        audio = plan_audio(doc, ["z10"], dropped_tags=drops, **idx)["entries"]
        return {e["slot_id"]: e["action"] for e in audio}, {e["take_id"]: e["action"] for e in ins}, drops

    def errors(self, doc=None):
        doc = doc or self.doc()
        local, _ = mapping_store.load_or_default(self.local_path, {"custom_subtitles": {}, "user_recordings": {}})
        findings, _ = validate_mappings(doc, mapping_store.load_schema(mapping_store.SCHEMA_NAME), ce=self.app.ce_idx,
                                        mcc=self.app.mcc_idx, local=local, verifications={"verifications": []},
                                        current_pins={}, subtitle_keys=self.app._subtitle_keys())
        return [f for f in findings if f["severity"] == "error"]

    def three_two(self):
        """The owner's example: take 1 -> ce1, take 2 -> ce2, take 3 -> ce1, all approved."""
        return [self.put(G[0], "line_a#0"), self.put(G[1], "line_b#0"), self.put(G[2], "line_a#0")]


class PreviewTests(Base):
    def test_three_original_takes_become_two_unique_replacement_takes(self):
        self.three_two()
        before = self.path.read_bytes()
        item = self.preview()
        self.assertEqual(self.path.read_bytes(), before)  # a preview never writes
        self.assertEqual(item["status"], "ready")
        self.assertEqual(item["summary"], "3 original MCC takes -> 2 replacement takes (1 duplicate selection merged)")
        self.assertEqual([(p["origin"], p["ce_line_ref"], p["position"], p["from_slots"]) for p in item["proposed"]],
                         [("new", "line_a#0", 1, [G[0], G[2]]), ("new", "line_b#0", 2, [G[1]])])
        self.assertIn("consolidated", {i["code"] for i in item["issues"]})
        self.assertEqual(item["build_now"]["replaced"], 3)
        self.assertEqual(item["build_staged"]["spain"], item["build_now"]["spain"])  # staging changes no build
        self.assertEqual(item["build_after"]["takes_in_game"], 2)

    def test_same_recording_with_a_different_recipe_is_another_take(self):
        self.put(G[0], "line_a#0", edit=trimmed("line_a#0"))
        self.put(G[1], "line_a#0")
        self.put(G[2], "line_a#0", edit=trimmed("line_a#0"))
        item = self.preview()
        self.assertEqual([(p["ce_line_ref"], p["edit_summary"], p["from_slots"]) for p in item["proposed"]],
                         [("line_a#0", "trim 0.01/0.00 s", [G[0], G[2]]), ("line_a#0", None, [G[1]])])
        self.put(P[0], "line_a#0", edit=trimmed("line_a#0", 0.01))
        self.put(P[1], "line_a#0", edit=trimmed("line_a#0", 0.02))
        self.assertEqual(len(self.preview(PAIR)["proposed"]), 2)  # same line, different trims: never merged

    def test_match_only_keep_original_and_mute_are_never_replacements(self):
        self.put(G[0], "line_a#0")
        self.put(G[1], source="keep_original", status="draft", subtitle="draft",
                 match={"status": "matched", "ce_line_refs": ["line_b#0"], "decided_at": "2026-10-18", "revision": 1})
        self.put(G[2], source="mute", subtitle="draft")
        item = self.preview()
        self.assertEqual([p["ce_line_ref"] for p in item["proposed"]], ["line_a#0"])  # line_b only matched
        self.assertEqual(item["status"], "review")
        self.assertEqual(item["review_codes"], ["keep_original", "match_only", "mute"])
        by = {s["slot_id"]: s["codes"] for s in item["sources"]}
        self.assertIn("match_only", by[G[1]])
        self.assertIn("mute", by[G[2]])
        self.assertEqual(item["summary"], "3 original MCC takes -> 1 replacement take")

    def test_partial_mapping_leaves_undecided_takes_for_review(self):
        self.put(G[0], "line_a#0")
        item = self.preview()
        self.assertEqual((item["status"], item["review_codes"]), ("review", ["undecided_take"]))
        self.assertEqual(sum(i["code"] == "undecided_take" for i in item["issues"]), 2)

    def test_mixed_statuses_never_carry_an_approval(self):
        self.put(G[0], "line_a#0", status="approved")
        self.put(G[1], "line_b#0", status="draft", subtitle="draft")
        self.put(G[2], "zz_late#0", status="needs_rework")
        item = self.preview()
        self.assertEqual(item["review_codes"], ["needs_rework_source"])
        self.assertTrue(all(p["status"] == "draft" for p in item["proposed"]))
        self.stage(ack=["needs_rework_source"])
        made = [t for t in self.doc()["added_takes"]]
        self.assertEqual([(t["audio"]["status"], t["audio"]["fingerprint"], t["audio"]["approved_at"]) for t in made],
                         [("draft", None, None)] * 3)

    def test_ineligible_and_active_sounds(self):
        self.put(S[0], "line_a#0", status="draft", subtitle="draft")
        item = self.preview(STEREO)
        self.assertEqual((item["status"], item["eligible"]), ("ineligible", False))
        with self.assertRaises(ApiError) as e:
            self.stage(STEREO, item=item)
        self.assertEqual(e.exception.status, 409)
        lv, rec = self.app._tag_record(GRUNT)  # a subtitle entry makes a sound ineligible too
        sub = tsc.plan_sound(self.doc(), GRUNT, rec, lv, has_subtitle_entry=True, ce_lines=self.app.ce_lines,
                             ce_idx=self.app.ce_idx, mcc_idx=self.app.mcc_idx)
        self.assertEqual(sub["status"], "ineligible")
        # an own set already on is never converted again
        self.app.own_set_on({"mcc_tag": PAIR, "loaded_takes_sha256": self.app.sound(PAIR)["version"],
                             "loaded_sound_sha256": self.app.sound(PAIR)["sound_version"], "clear_mapping_ids": [],
                             "audio_list": [{"ce_line_ref": "line_a#0", "language": MX}]})
        item = self.preview(PAIR)
        self.assertEqual(item["status"], "active")
        with self.assertRaises(ApiError):
            self.stage(PAIR, item=item)

    def test_drifted_and_missing_media(self):
        self.put(G[0], "line_b#0")
        self.put(G[1], "line_a#0")
        self.put(G[2], "line_b#0")
        cat = self.root / "work/ce/catalog/m99.jsonl"
        recs = [json.loads(x) for x in cat.read_text(encoding="utf-8").splitlines()]
        for r in recs:  # line_b's recording changed since approval; line_a lost its es-MX media
            if r["record_id"] == "line_b":
                r["entries"][0]["media"][MX]["media"][0]["wem_sha256"] = H["9"]
            if r["record_id"] == "line_a":
                r["entries"][0]["media"][MX] = ce_record("x", mx="unresolved")["entries"][0]["media"][MX]
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        self.app.reload()
        item = self.preview()
        self.assertEqual(item["status"], "blocked")
        codes = {(i["slot_id"], i["code"]) for i in item["issues"]}
        self.assertIn((G[0], "approved_drift"), codes)
        self.assertIn((G[1], "unresolved_media"), codes)
        with self.assertRaises(ApiError):
            self.stage(item=item, ack=item["review_codes"])

    def test_metadata_is_classified_and_recorded(self):
        local = {"schema": "manual-mappings-local/1", "custom_subtitles": {"c-000001": {"text": "¡Ay!",
                                                                                         "updated_at": "2026-10-18"}},
                 "user_recordings": {}}
        mapping_store.save_user_file(self.local_path, local, mapping_store.load_or_default(self.local_path, {})[1],
                                     "manual-mappings-local-1")
        self.put(G[0], "line_a#0", notes="breathy", radio=True, different_but_fits=True,
                 subtitle={"source": "custom", "custom_ref": "c-000001", "status": "approved"})
        self.put(G[1], "line_a#0", notes="loud", needs_recording=True)
        self.put(G[2], "line_b#0", notes="keep this one")
        item = self.preview()
        self.assertEqual(item["review_codes"], ["needs_recording", "notes_differ", "radio_flag_conflict",
                                                "subtitle_text"])
        a, b = item["proposed"]
        self.assertEqual((a["notes"], a["radio_effect"], b["notes"]), ("", True, "keep this one"))
        before = sorted((m for m in self.doc()["slots"] if m["mcc_tag"] == GRUNT), key=lambda m: m["mapping_id"])
        self.stage(ack=item["review_codes"])
        prov = self.doc()["own_sets"][0]["provenance"]
        self.assertEqual(prov["slots"], before)  # every field, approvals and fingerprints included
        self.assertEqual(prov["custom_subtitles"], [{"custom_ref": "c-000001",
                                                     "text_sha256": hashlib.sha256("¡Ay!".encode()).hexdigest()}])
        self.assertEqual(prov["acknowledged"], item["review_codes"])
        self.assertEqual([(t["origin"], t["from_mapping_ids"]) for t in prov["takes"]],
                         [("created", ["m-000001", "m-000002"]), ("created", ["m-000003"])])


class StageActivateTests(Base):
    def test_staging_keeps_the_build_then_the_switch_needs_every_take_approved(self):
        mids = self.three_two()
        before_doc = self.doc()
        before_build = self.plans()
        r = self.stage()
        self.assertEqual([d["created"] for d in r["staged"]], [["t-000001", "t-000002"]])
        doc = self.doc()
        self.assertEqual(doc["slots"], before_doc["slots"])  # the line decisions stay in force
        self.assertEqual(doc["own_sets"][0]["state"], "staged")
        self.assertEqual(self.errors(), [])
        audio, takes, drops = self.plans()
        self.assertEqual((audio, drops), (before_build[0], []))  # during: Spain's takes still replaced as before
        self.assertEqual(takes, {"t-000001": "skip", "t-000002": "skip"})
        self.assertEqual(self.app.sound(GRUNT)["mode"], "replacement_set_staged")
        with self.assertRaises(ApiError) as e:  # drafts: refused, nothing changes
            self.activate()
        self.assertEqual(e.exception.status, 409)
        self.approve_take("t-000001")
        snap = self.path.read_bytes()
        with self.assertRaises(ApiError):  # partially approved: still refused (no partial set in game)
            self.activate()
        self.assertEqual(self.path.read_bytes(), snap)
        self.assertEqual(self.plans()[0], before_build[0])
        self.approve_take("t-000002")
        r = self.activate()
        self.assertEqual(r["switched"][0]["reworked"], [f"{m}/{f}" for m in mids for f in ("audio", "subtitle")])
        doc = self.doc()
        self.assertEqual([m for m in doc["slots"] if m["mcc_tag"] == GRUNT], [])
        own = doc["own_sets"][0]
        self.assertNotIn("state", own)
        self.assertEqual(own["provenance"]["activated_at"], "2026-10-18")
        self.assertEqual(own["provenance"]["slots"], [m for m in before_doc["slots"] if m["mcc_tag"] == GRUNT])
        audio, takes, drops = self.plans()
        self.assertEqual(([audio[s] for s in G], takes, drops), (["dropped"] * 3, {"t-000001": "insert",
                                                                                  "t-000002": "insert"}, [GRUNT]))
        self.assertEqual(self.errors(), [])
        self.assertEqual(own_set_findings(doc, mcc=self.app.mcc_idx, subtitle_keys=self.app._subtitle_keys()), [])
        # against the committed version, the approved decisions are not "deleted": they are in the record
        protected = check_approved_protected(before_doc, doc)
        self.assertEqual({f["code"] for f in protected}, {"approved_mapping_in_replacement_set"})
        conn = sqlite3.connect(self.root / "mappings/manual_mappings.db")
        reasons = {r for (r,) in conn.execute("SELECT reason FROM slot_history WHERE after_body IS NULL")}
        conn.close()
        self.assertEqual(len(reasons), 1)
        self.assertTrue(next(iter(reasons)).startswith("take-set:activate:cv-"))
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")

    def test_existing_added_takes_keep_their_ids_positions_and_approval(self):
        sv = self.app.sound(GRUNT)
        self.app.take_save({"mcc_tag": GRUNT, "loaded_takes_sha256": sv["version"],
                            "audio": {"ce_line_ref": "line_b#0", "language": MX}, "notes": "mine"})
        self.approve_take("t-000001")
        existing = copy.deepcopy(self.doc()["added_takes"][0])
        self.three_two()
        item = self.preview()
        self.assertEqual([(p["origin"], p["take_id"], p["ce_line_ref"], p["position"]) for p in item["proposed"]],
                         [("existing", "t-000001", "line_b#0", 1), ("new", None, "line_a#0", 2)])
        self.assertIn("reuses_existing_take", {i["code"] for i in item["issues"]})
        before = self.plans()
        self.stage()
        doc = self.doc()
        self.assertEqual(doc["added_takes"][0], existing)  # untouched, byte for byte
        self.assertEqual(self.plans()[1]["t-000001"], before[1]["t-000001"])  # still built as before (insert)
        self.assertEqual(self.plans()[1]["t-000002"], "skip")
        self.assertEqual(doc["own_sets"][0]["provenance"]["added_takes"], [existing])

    def test_stale_previews_are_refused(self):
        self.three_two()
        old = self.preview()
        doc, sha = mapping_store.load(self.path)  # a line note changes (another computer)
        new = copy.deepcopy(doc)
        new["slots"][1]["notes"] = "changed"
        mapping_store.save(self.path, new, sha)
        with self.assertRaises(ApiError) as e:
            self.stage(item=old)
        self.assertEqual(e.exception.status, 409)
        self.assertIn("changed since the preview", e.exception.details[0])
        old = self.preview()  # an added take of the sound
        self.app.take_save({"mcc_tag": GRUNT, "loaded_takes_sha256": self.app.sound(GRUNT)["version"],
                            "audio": {"ce_line_ref": "zz_late#0", "language": MX}})
        with self.assertRaises(ApiError):
            self.stage(item=old)
        old = self.preview()  # a catalog fact of a CE line it names
        cat = self.root / "work/ce/catalog/m99.jsonl"
        cat.write_text(cat.read_text(encoding="utf-8").replace(H["a"], H["8"], 1), encoding="utf-8")
        self.app.reload()
        with self.assertRaises(ApiError):
            self.stage(item=old)

    def test_repeated_apply_is_safe_and_ids_are_never_reused(self):
        self.three_two()
        item = self.preview()
        self.stage(item=item)
        snap = self.path.read_bytes()
        again = self.stage(item=item)
        self.assertEqual((again["saved"], again["already"]), (False, [GRUNT]))
        self.assertEqual(self.path.read_bytes(), snap)
        self.app.convert_cancel({"mcc_tag": GRUNT, "loaded_sound_sha256": self.app.sound(GRUNT)["sound_version"]})
        self.stage()
        self.assertEqual([t["take_id"] for t in self.doc()["added_takes"]], ["t-000003", "t-000004"])

    def test_a_failed_save_changes_nothing(self):
        self.three_two()
        self.stage()
        self.approve_take("t-000001")
        self.approve_take("t-000002")
        files = {p: p.read_bytes() for p in (self.path, self.root / "mappings/manual_mappings.db")}
        with mock.patch.object(mapping_db, "_write_meta", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                self.activate()
        self.assertEqual({p: p.read_bytes() for p in files}, files)  # rolled back: file and database as before
        self.assertEqual(mapping_store.sync_status(self.path)["state"], "in_sync")
        self.activate()  # and it works afterwards

    def test_bulk_stage_takes_only_ready_sounds_and_is_all_or_nothing(self):
        self.three_two()
        self.put(P[0], "line_a#0")  # PAIR: one take undecided -> review
        inv = self.app.convert_inventory("z10")
        st = {s["mcc_tag"]: s for s in inv["sounds"]}
        self.assertEqual((st[GRUNT]["status"], st[PAIR]["status"]), ("ready", "review"))
        snap = self.path.read_bytes()
        with self.assertRaises(ApiError) as e:
            self.app.convert_stage({"confirm": True, "bulk": True, "items": [
                {"mcc_tag": t, "token": st[t]["token"]} for t in (GRUNT, PAIR)]})
        self.assertIn("bulk", e.exception.details[0])
        self.assertEqual(self.path.read_bytes(), snap)  # nothing staged
        with self.assertRaises(ApiError):  # without the review acknowledged, one by one too
            self.stage(PAIR)
        r = self.app.convert_stage({"confirm": True, "bulk": True, "items": [{"mcc_tag": GRUNT, "token": st[GRUNT]["token"]}]})
        self.assertEqual([d["mcc_tag"] for d in r["staged"]], [GRUNT])
        self.stage(PAIR, ack=["undecided_take"])
        self.approve_take("t-000001")
        self.approve_take("t-000002")
        snap = self.path.read_bytes()
        with self.assertRaises(ApiError):  # PAIR's take is a draft: neither sound is switched
            self.app.convert_activate({"confirm": True, "items": [
                {"mcc_tag": t, "loaded_sound_sha256": self.app.sound(t)["sound_version"]} for t in (GRUNT, PAIR)]})
        self.assertEqual(self.path.read_bytes(), snap)

    def test_a_line_changed_while_staged_blocks_the_switch(self):
        self.three_two()
        self.stage()
        self.approve_take("t-000001")
        self.approve_take("t-000002")
        s = self.app.sound(GRUNT)  # the line stays editable (its decision is still in force) ...
        self.app.save({"slot_id": G[1], "loaded_slot_sha256": self.app.slot(G[1])["sha256"]["slot"], "notes": "x"})
        with self.assertRaises(ApiError) as e:  # ... and the page's old version is refused
            self.app.convert_activate({"confirm": True, "items": [{"mcc_tag": GRUNT,
                                                                   "loaded_sound_sha256": s["sound_version"]}]})
        self.assertIn("changed since the page loaded it", e.exception.details[0])
        with self.assertRaises(ApiError) as e:  # ... and so is the switch: the record no longer matches
            self.activate()
        self.assertIn("line decision changed since staging", e.exception.details[0])
        s = self.app.sound(GRUNT)
        for op in (self.app.own_set_on, self.app.own_set_off):  # the 4th option leaves a staged sound alone
            with self.assertRaises(ApiError) as e:
                op({"mcc_tag": GRUNT, "loaded_takes_sha256": s["version"], "loaded_sound_sha256": s["sound_version"],
                    "clear_mapping_ids": [], "audio_list": [{"ce_line_ref": "zz_late#0", "language": MX}]})
            self.assertEqual(e.exception.status, 409)

    def test_store_rules_hold_for_every_step(self):
        self.three_two()
        self.stage()
        doc, sha = mapping_store.load(self.path)
        forged = copy.deepcopy(doc)  # a tool approving a created take
        forged["added_takes"][0]["audio"].update(status="approved", approved_at="2026-10-18", fingerprint={})
        with self.assertRaises(ProtectedError):
            mapping_store.save_sequence(self.path, [(forged, [])], sha)
        gone = copy.deepcopy(doc)  # removing approved lines without Needs rework
        gone["slots"] = [m for m in gone["slots"] if m["mcc_tag"] != GRUNT]
        with self.assertRaises(ProtectedError):
            mapping_store.save_sequence(self.path, [(gone, [])], sha)
        edited = copy.deepcopy(doc)  # the record is read-only
        edited["own_sets"][0]["provenance"]["slots"][0]["notes"] = "rewritten"
        with self.assertRaises(ProtectedError):
            mapping_store.save_sequence(self.path, [(edited, [])], sha)


class Flow(Base):
    """Helpers for whole flows: effective build plans, approvals, undo through its preview."""

    def effective(self, doc=None):
        """What a build would produce for the fixture level: per Spain slot its action and audio, the inserted takes,
        and the sounds whose Spain samples are dropped."""
        doc = doc or self.doc()
        local, _ = mapping_store.load_or_default(self.local_path, {"custom_subtitles": {}, "user_recordings": {}})
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx, local=local)
        ins = plan_inserts(doc, ["z10"], subtitle_keys=self.app._subtitle_keys(), **idx)
        drops = own_set_drops(doc, ins)
        audio = plan_audio(doc, ["z10"], dropped_tags=drops, **idx)["entries"]
        return ({e["slot_id"]: (e["action"], e.get("ce_line_ref"), json.dumps(e.get("edit"), sort_keys=True))
                 for e in audio},
                sorted((e["take_id"], e.get("ce_line_ref")) for e in ins if e["action"] == "insert"), drops)

    def existing_take(self, ref="zz_late#0"):
        """An approved added take the sound already has (mode Spain + added takes)."""
        s = self.app.sound(GRUNT)
        r = self.app.take_save({"mcc_tag": GRUNT, "loaded_takes_sha256": s["version"],
                                "audio": {"ce_line_ref": ref, "language": MX}})
        self.approve_take(r["take_id"])
        return r["take_id"]

    def created(self, tag=GRUNT):
        own = next(o for o in self.doc()["own_sets"] if o["mcc_tag"] == tag)
        return [t["take_id"] for t in own["provenance"]["takes"] if t["origin"] == "created"]

    def approve_unchanged(self, tag=GRUNT, take_ids=None):
        listed = self.app.convert_approvable(tag)
        ids = take_ids if take_ids is not None else [t["take_id"] for t in listed["included"]]
        return self.app.convert_approve_unchanged({"mcc_tag": tag, "confirm": True, "take_ids": ids,
                                                   "loaded_sound_sha256": listed["sound_version"]})

    def undo(self, tag=GRUNT, rework_drifted=False):
        p = self.app.convert_revert_preview(tag, rework_drifted)
        return self.app.convert_revert({"mcc_tag": tag, "confirm": True, "token": p["token"],
                                        "rework_drifted": rework_drifted})


class BuildNeutralTests(Flow):
    def test_staged_takes_never_reach_the_build_until_the_switch(self):
        existing = self.existing_take()
        self.three_two()
        original = self.effective()
        self.assertIn((existing, "zz_late#0"), original[1])  # the earlier take is built (Spain + added takes)
        self.stage()
        new = self.created()
        self.assertEqual(len(new), 2)
        self.assertEqual(self.effective(), original)  # right after Stage
        self.approve_take(new[0])
        self.assertEqual(self.effective(), original)  # some approved
        self.approve_take(new[1])
        self.assertEqual(self.effective(), original)  # all approved, before the switch
        _a, takes, _d = self.plans()
        self.assertEqual((takes[existing], takes[new[0]], takes[new[1]]), ("insert", "skip", "skip"))

    def test_cancel_after_every_take_is_approved_returns_to_the_pre_stage_state(self):
        self.existing_take()
        self.three_two()
        original, snap = self.effective(), self.path.read_bytes()
        self.stage()
        for t in self.created():
            self.approve_take(t)
        r = self.app.convert_cancel({"mcc_tag": GRUNT, "loaded_sound_sha256": self.app.sound(GRUNT)["sound_version"]})
        self.assertEqual(len(r["reworked"]), 2)  # each approved take: Needs rework first, then removed, one save
        self.assertEqual(self.path.read_bytes(), snap)
        self.assertEqual(self.effective(), original)


class ApproveUnchangedTests(Flow):
    def test_only_unchanged_takes_of_approved_valid_selections(self):
        self.put(G[0], "line_a#0")                                # approved
        self.put(G[1], "line_b#0", status="draft", subtitle="draft")  # draft contributor
        self.put(G[2], "line_a#0")                                # approved, same audio as G[0]
        self.stage(ack=None)
        a, b = self.created()
        listed = self.app.convert_approvable(GRUNT)
        self.assertEqual([t["take_id"] for t in listed["included"]], [a])
        self.assertEqual([s["slot_id"] for s in listed["included"][0]["sources"]], [G[0], G[2]])
        self.assertEqual(listed["excluded"][0]["take_id"], b)
        self.assertIn("audio is draft, not approved", " ".join(listed["excluded"][0]["reasons"]))
        before_slot = next(m for m in self.doc()["slots"] if m["slot_id"] == G[0])["audio"]["fingerprint"]
        r = self.approve_unchanged()
        self.assertEqual(r["approved"], [a])
        t = next(x for x in self.doc()["added_takes"] if x["take_id"] == a)
        local, _ = mapping_store.load_or_default(self.local_path, {"custom_subtitles": {}, "user_recordings": {}})
        from common.project_validation import added_take_fingerprint
        self.assertEqual((t["audio"]["status"], t["audio"]["approved_at"], t["audio"]["revision"]),
                         ("approved", "2026-10-18", 1))
        self.assertEqual(t["audio"]["fingerprint"],
                         added_take_fingerprint(t, self.app.ce_idx, self.app.mcc_idx, local))  # its own, fresh
        self.assertNotEqual(t["audio"]["fingerprint"], before_slot)
        conn = sqlite3.connect(self.root / "mappings/manual_mappings.db")
        reason = conn.execute("SELECT reason FROM added_take_history WHERE take_id = ? ORDER BY id DESC",
                              (a,)).fetchone()[0]
        conn.close()
        self.assertTrue(reason.startswith("take-set:approve-unchanged:cv-"))

    def test_one_approved_contributor_never_covers_another(self):
        self.put(G[0], "line_a#0")
        self.put(G[1], "line_b#0")
        self.put(G[2], "line_a#0", status="needs_rework")
        self.stage(ack=["needs_rework_source"])
        listed = self.app.convert_approvable(GRUNT)
        self.assertEqual([t["ce_line_ref"] for t in listed["included"]], ["line_b#0"])
        self.assertIn("audio is needs_rework", " ".join(listed["excluded"][0]["reasons"]))

    def test_edits_drift_and_review_points_exclude_a_take(self):
        self.put(G[0], "line_a#0", needs_recording=True)  # a review point on the contributor
        self.put(G[1], "line_b#0")
        self.put(G[2], "zz_late#0")
        self.stage(ack=["needs_recording"])
        a, b, c = self.created()
        s = self.app.sound(GRUNT)  # take b edited after staging (another recording)
        self.app.take_save({"mcc_tag": GRUNT, "take_id": b, "loaded_takes_sha256": s["version"],
                            "audio": {"ce_line_ref": "aa_early#0", "language": MX}})
        cat = self.root / "work/ce/catalog/m98.jsonl"  # zz_late's recording changed since its approval (drift)
        recs = [json.loads(x) for x in cat.read_text(encoding="utf-8").splitlines()]
        for r in recs:
            if r["record_id"] == "zz_late":
                r["entries"][0]["media"][MX]["media"][0]["wem_sha256"] = H["9"]
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        self.app.reload()
        listed = self.app.convert_approvable(GRUNT)
        self.assertEqual(listed["included"], [])
        why = {t["take_id"]: " ".join(t["reasons"]) for t in listed["excluded"]}
        self.assertIn("review points needs_recording", why[a])
        self.assertIn("changed since staging", why[b])
        self.assertIn("drift", why[c])

    def test_a_stale_or_different_confirmation_approves_nothing(self):
        self.three_two()
        self.stage()
        a, b = self.created()
        listed = self.app.convert_approvable(GRUNT)
        self.approve_take(a)  # approved one by one meanwhile (another window)
        snap = self.path.read_bytes()
        with self.assertRaises(ApiError) as e:
            self.app.convert_approve_unchanged({"mcc_tag": GRUNT, "confirm": True, "take_ids": [a, b],
                                                "loaded_sound_sha256": listed["sound_version"]})
        self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ApiError):  # current version, but not the list that is approvable now
            self.app.convert_approve_unchanged({"mcc_tag": GRUNT, "confirm": True, "take_ids": [a, b],
                                                "loaded_sound_sha256": self.app.sound(GRUNT)["sound_version"]})
        self.assertEqual(self.path.read_bytes(), snap)  # no partial approval
        self.approve_unchanged(take_ids=[b])


class SwitchTests(Flow):
    def ready(self):
        self.three_two()
        self.stage()
        self.approve_unchanged()

    def test_approved_but_not_buildable_is_not_ready(self):
        self.ready()
        cat = self.root / "work/ce/catalog/m99.jsonl"
        recs = [json.loads(x) for x in cat.read_text(encoding="utf-8").splitlines()]
        for r in recs:
            if r["record_id"] == "line_b":
                r["entries"][0]["media"][MX] = ce_record("x", mx="unresolved")["entries"][0]["media"][MX]
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        self.app.reload()
        snap = self.path.read_bytes()
        with self.assertRaises(ApiError) as e:
            self.activate()
        self.assertIn("no single resolved", e.exception.details[0])
        self.assertEqual(self.path.read_bytes(), snap)

    def test_the_set_must_be_the_staged_one(self):
        self.ready()
        s = self.app.sound(GRUNT)
        self.app.take_save({"mcc_tag": GRUNT, "loaded_takes_sha256": s["version"],
                            "audio": {"ce_line_ref": "aa_early#0", "language": MX}})
        with self.assertRaises(ApiError) as e:
            self.activate()
        self.assertIn("added since staging", e.exception.details[0])
        with mock.patch.object(self.app, "take_rule", return_value=(False, "has a subtitle entry")):
            with self.assertRaises(ApiError) as e:
                self.activate()
        self.assertIn("not eligible", e.exception.details[0])

    def test_switch_changes_the_decisions_only(self):
        from test_m4 import snapshot
        self.ready()
        before = {k: v for k, v in snapshot(self.root).items() if not k.startswith("mappings/")}
        self.activate()
        after = {k: v for k, v in snapshot(self.root).items() if not k.startswith("mappings/")}
        self.assertEqual(after, before)  # no file outside mappings/ (nothing installed, nothing built)

    def test_after_the_switch_a_reworked_or_drifted_take_is_left_out(self):
        self.ready()
        self.activate()
        a, b = self.created()
        self.app.take_save({"mcc_tag": GRUNT, "take_id": a, "loaded_takes_sha256": self.app.sound(GRUNT)["version"],
                            "actions": [{"action": "needs_rework", "field": "audio"}]})
        audio, takes, drops = self.plans()
        self.assertEqual((takes[a], takes[b], drops), ("skip", "insert", [GRUNT]))  # the set plays one take less
        self.assertEqual([audio[s] for s in G], ["dropped"] * 3)
        cat = self.root / "work/ce/catalog/m99.jsonl"  # b drifts: no take left to build
        cat.write_text(cat.read_text(encoding="utf-8").replace(H["f"], H["8"]), encoding="utf-8")
        self.app.reload()
        audio, takes, drops = self.plans()
        self.assertEqual((takes[b], drops), ("not_eligible", []))
        self.assertEqual([audio[s] for s in G], ["keep_original"] * 3)  # falls back to Spain's own recordings
        self.assertTrue(self.app.sound(GRUNT)["added_takes"][1]["drift"])


class RecoveryTests(Flow):
    def switched(self):
        mids = self.three_two()
        self.stage()
        self.approve_unchanged()
        before = sorted((m for m in self.doc()["slots"] if m["mcc_tag"] == GRUNT), key=lambda m: m["mapping_id"])
        self.activate()
        return mids, before

    def test_round_trip_restores_the_original_effective_state(self):
        existing = self.existing_take()
        mids = self.three_two()
        original_doc, original = self.doc(), self.effective()
        self.stage()
        created = self.created()
        self.approve_unchanged()
        self.activate()
        self.assertNotEqual(self.effective(), original)
        preview = self.app.convert_revert_preview(GRUNT)
        self.assertEqual(preview["conflicts"], [])
        self.assertEqual({r["audio"] for r in preview["restore"]}, {"approval restored"})
        r = self.undo()
        self.assertEqual((r["removed_takes"], r["kept_takes"]), (created, [existing]))
        doc = self.doc()
        self.assertEqual(sorted((m for m in doc["slots"] if m["mcc_tag"] == GRUNT), key=lambda m: m["mapping_id"]),
                         sorted((m for m in original_doc["slots"] if m["mcc_tag"] == GRUNT),
                                key=lambda m: m["mapping_id"]))  # approvals, fingerprints, revisions: exact
        self.assertEqual(doc["added_takes"], original_doc["added_takes"])
        self.assertNotIn("own_sets", doc)
        self.assertEqual(self.app.sound(GRUNT)["mode"], "spain_plus_added")
        self.assertEqual(self.effective(), original)  # the build is what it was before the conversion
        self.assertEqual(self.errors(), [])
        conn = sqlite3.connect(self.root / "mappings/manual_mappings.db")
        gone = {t for (t,) in conn.execute("SELECT take_id FROM added_take_history WHERE after_body IS NULL")}
        reason = conn.execute("SELECT reason FROM slot_history WHERE mapping_id = ? ORDER BY id DESC",
                              (mids[0],)).fetchone()[0]
        conn.close()
        self.assertTrue(set(created) <= gone)  # their history stays; their IDs are never reused
        self.assertTrue(reason.startswith("take-set:revert:"))
        s = self.app.sound(GRUNT)
        new = self.app.take_save({"mcc_tag": GRUNT, "loaded_takes_sha256": s["version"],
                                  "audio": {"ce_line_ref": "aa_early#0", "language": MX}})["take_id"]
        self.assertNotIn(new, created + [existing])

    def test_restore_is_only_for_the_record_being_undone(self):
        _mids, before = self.switched()
        doc, sha = mapping_store.load(self.path)
        forged = copy.deepcopy(doc)  # the recorded approved body put back while the set stays on
        forged["slots"].append(copy.deepcopy(before[0]))
        acts = [UserAction("restore", before[0]["mapping_id"], f) for f in ("audio", "subtitle")]
        with self.assertRaises(ProtectedError):
            mapping_store.save_sequence(self.path, [(forged, acts)], sha)
        edited = copy.deepcopy(doc)  # or a changed body while undoing
        edited["own_sets"] = [o for o in edited["own_sets"] if o["mcc_tag"] != GRUNT] or None
        if edited["own_sets"] is None:
            edited.pop("own_sets")
        body = copy.deepcopy(before[0])
        body["audio"]["sources"][0]["ce_line_ref"] = "line_b#0"
        edited["slots"].append(body)
        with self.assertRaises(ProtectedError):
            mapping_store.save_sequence(self.path, [(edited, acts)], sha)

    def test_conflicts_are_shown_first_and_nothing_changes(self):
        self.switched()
        s = self.app.sound(GRUNT)
        self.app.take_save({"mcc_tag": GRUNT, "loaded_takes_sha256": s["version"],
                            "audio": {"ce_line_ref": "zz_late#0", "language": MX}})  # added after the switch
        cat = self.root / "work/ce/catalog/m99.jsonl"  # line_b changed: its approval drifted
        cat.write_text(cat.read_text(encoding="utf-8").replace(H["f"], H["8"]), encoding="utf-8")
        self.app.reload()
        snap = self.path.read_bytes()
        p = self.app.convert_revert_preview(GRUNT)
        self.assertEqual({c["code"] for c in p["conflicts"]}, {"take_added_after", "approval_drift"})
        with self.assertRaises(ApiError) as e:
            self.app.convert_revert({"mcc_tag": GRUNT, "confirm": True, "token": p["token"]})
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(self.path.read_bytes(), snap)

    def test_drifted_approvals_come_back_as_needs_rework_only_when_chosen(self):
        mids, before = self.switched()
        cat = self.root / "work/ce/catalog/m99.jsonl"
        cat.write_text(cat.read_text(encoding="utf-8").replace(H["f"], H["8"]), encoding="utf-8")
        self.app.reload()
        old = self.app.convert_revert_preview(GRUNT)
        with self.assertRaises(ApiError):  # the token of the plain preview does not cover the choice
            self.app.convert_revert({"mcc_tag": GRUNT, "confirm": True, "token": old["token"], "rework_drifted": True})
        self.undo(rework_drifted=True)
        now = {m["slot_id"]: m for m in self.doc()["slots"]}
        self.assertEqual(now[G[1]]["audio"]["status"], "needs_rework")  # line_b: drifted
        self.assertEqual(now[G[0]]["audio"], before[0]["audio"])       # line_a: restored exactly

    def test_new_decisions_never_take_a_recorded_id(self):
        mids, _before = self.switched()
        self.put(P[0], "line_a#0")  # through the store helper: next id after every slot
        r = self.app.save({"slot_id": P[1], "loaded_slot_sha256": self.app.slot(P[1])["sha256"]["slot"],
                           "notes": "x"})
        self.assertNotIn(r["slot"]["mapping"]["mapping_id"], mids)

    def test_undo_of_the_fourth_option(self):
        self.put(G[0], "line_a#0")
        before = self.doc()["slots"]
        s = self.app.sound(GRUNT)
        self.app.own_set_on({"mcc_tag": GRUNT, "loaded_takes_sha256": s["version"], "loaded_sound_sha256": s["sound_version"],
                             "clear_mapping_ids": ["m-000001"], "audio_list": [{"ce_line_ref": "line_b#0", "language": MX}]})
        r = self.undo()
        self.assertEqual(r["restored"], ["m-000001"])
        self.assertEqual(self.doc()["slots"], before)  # approval included


class LocalRecoveryTests(Flow):
    TEXT = "¡Ay, me dieron!"

    def with_custom_text(self):
        local = {"schema": "manual-mappings-local/1", "custom_subtitles": {"c-000001": {"text": self.TEXT,
                                                                                         "updated_at": "2026-10-18"}},
                 "user_recordings": {}}
        mapping_store.save_user_file(self.local_path, local, mapping_store.load_or_default(self.local_path, {})[1],
                                     "manual-mappings-local-1")
        self.put(G[0], "line_a#0", subtitle={"source": "custom", "custom_ref": "c-000001", "status": "approved"})
        self.put(G[1], "line_b#0")
        self.put(G[2], "line_a#0")
        self.stage(ack=["subtitle_text"])
        for t in self.created():
            self.approve_take(t)
        self.activate()

    def set_local_text(self, text):
        local, sha = mapping_store.load_or_default(self.local_path, {})
        local = copy.deepcopy(local)
        if text is None:
            local["custom_subtitles"].pop("c-000001")
        else:
            local["custom_subtitles"]["c-000001"] = {"text": text, "updated_at": "2026-10-19"}
        mapping_store.save_user_file(self.local_path, local, sha, "manual-mappings-local-1")

    def test_the_text_is_kept_locally_and_restored_when_missing(self):
        self.with_custom_text()
        rec = json.loads((self.root / "mappings/take_set_recovery.local.json").read_text(encoding="utf-8"))
        (rid, snap), = rec["records"].items()
        self.assertEqual(snap["custom_subtitles"]["c-000001"]["text"], self.TEXT)
        self.assertNotIn(self.TEXT, self.path.read_text(encoding="utf-8"))  # never in the committed file
        self.assertIn("/mappings/*.local.json", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        self.set_local_text(None)  # the local text is lost afterwards
        p = self.app.convert_revert_preview(GRUNT)
        self.assertEqual((p["conflicts"], list(p["local_restore"]["custom_subtitles"])), ([], ["c-000001"]))
        self.undo()
        local, _ = mapping_store.load_or_default(self.local_path, {})
        self.assertEqual(local["custom_subtitles"]["c-000001"]["text"], self.TEXT)
        m = next(x for x in self.doc()["slots"] if x["slot_id"] == G[0])
        self.assertEqual(m["subtitle"]["status"], "approved")  # its approval pins that text: restored with it
        self.assertEqual(self.errors(), [])

    def test_newer_local_text_is_never_overwritten(self):
        self.with_custom_text()
        self.set_local_text("otro texto")
        snap = (self.path.read_bytes(), self.local_path.read_bytes())
        p = self.app.convert_revert_preview(GRUNT)
        # the text differs from the snapshot, and the recorded subtitle approval pinned the old text
        self.assertEqual([c["code"] for c in p["conflicts"]], ["local_text_changed", "approval_drift"])
        with self.assertRaises(ApiError):
            self.app.convert_revert({"mcc_tag": GRUNT, "confirm": True, "token": p["token"]})
        self.assertEqual((self.path.read_bytes(), self.local_path.read_bytes()), snap)


class VisibilityTests(Flow):
    def test_reminders_of_archived_decisions_stay_operational(self):
        self.put(G[0], "line_a#0", needs_recording=True, notes="retake later")
        self.put(G[1], "line_b#0", radio=True)
        self.put(G[2], "line_b#0", radio=True)
        self.stage(ack=["needs_recording"])
        for t in self.created():
            self.approve_take(t)
        self.activate()
        rows = {r["slot_id"]: r for r in self.app.slots("z10")["slots"]}
        self.assertTrue(rows[G[0]]["needs_recording"] and rows[G[0]]["archived_reminders"])
        self.assertTrue(rows[G[1]]["radio_effect"])
        ids = lambda st: {r["slot_id"] for r in self.app.slots("z10", status=st)["slots"]}  # noqa: E731
        self.assertIn(G[0], ids("recording"))
        self.assertEqual(ids("radio") & set(G), {G[1], G[2]})
        p = self.app.slots("z10")["progress"]
        self.assertEqual((p["needs_recording"], p["radio_effect"]), (1, 2))
        self.assertEqual([(x["slot_id"], x["needs_recording"], x["notes"]) for x in self.app.sound(GRUNT)["reminders"]
                          if x["needs_recording"]], [(G[0], True, "retake later")])

    def test_existing_sets_on_single_take_sounds_are_listed(self):
        death = T + "z10_030_death"
        s = self.app.sound(death)
        self.app.own_set_on({"mcc_tag": death, "loaded_takes_sha256": s["version"],
                             "loaded_sound_sha256": s["sound_version"], "clear_mapping_ids": [],
                             "audio_list": [{"ce_line_ref": "line_a#0", "language": MX}]})
        self.three_two()
        inv = self.app.convert_inventory("all")
        by = {x["mcc_tag"]: x for x in inv["sounds"]}
        self.assertEqual((by[death]["status"], by[death]["single_take"]), ("active", True))
        self.assertEqual(inv["counts"]["own_sets_single_take"], 1)
        self.assertEqual(inv["counts"]["multi_take_sounds"], 3)  # GRUNT, PAIR, STEREO: labelled apart


class BuildTests(Base):
    def test_bank_and_index_of_a_converted_sound(self):
        """After the switch the build removes the sound's three Spain samples and inserts its two takes; the bank
        and the Spanish index stay consistent (insert_checks). Before the switch nothing is inserted."""
        from common.m6_build import insert_checks, insert_takes
        from common.mcc_lst import build_lst, parse_lst
        from test_fsb5_writer import celt_stream, fsb, loop
        recs = [r for recs in self.app.levels.values() for r in recs]
        n = max(s["index"] for r in recs for s in r["samples"]["spanish"]) + 1
        bank = fsb([(8, 0, 512, [loop(512)], celt_stream(1, 370, k)) for k in range(n)],
                   [f"s{k}".encode() for k in range(n)])
        lst = build_lst(1, sorted(((r["mcc_tag"], r["samples"]["spanish"][0]["index"], len(r["samples"]["spanish"]))
                                   for r in recs), key=lambda x: x[1]))
        self.three_two()
        self.stage()
        _a, takes, drops = self.plans()
        self.assertEqual((drops, [t for t, a in takes.items() if a == "insert"]), ([], []))  # staged: bank as before
        self.approve_take("t-000001")
        self.approve_take("t-000002")
        self.activate()
        _a, takes, drops = self.plans()
        items = [{"take_id": t, "mcc_tag": GRUNT, "stream": celt_stream(2, 370, 90 + k), "sample_count": 1024}
                 for k, t in enumerate(sorted(t for t, a in takes.items() if a == "insert"))]
        cand, new_lst, index_map, new_index = insert_takes(bank, lst, items, drops)
        checks = insert_checks(bank, cand, lst, new_lst, index_map, new_index, items, drops)
        self.assertTrue(all(checks.values()), {k: v for k, v in checks.items() if not v})
        rec = {t: (f, c) for t, f, c in parse_lst(new_lst)["records"]}
        self.assertEqual(rec[GRUNT][1], 2)  # 3 original MCC takes -> 2 replacement takes


class ReadOnlyInventoryTests(Base):
    def test_the_inventory_cli_never_writes_or_creates_the_database(self):
        self.three_two()
        db = self.root / "mappings/manual_mappings.db"
        files = {p: p.read_bytes() for p in (self.path, db)}
        out = subprocess.run([sys.executable, str(ROOT / "scripts/validate/take_set_inventory.py"), "--root",
                              str(self.root)], capture_output=True, text=True, check=True).stdout
        self.assertIn('"ready": 1', out)
        self.assertIn("in sync", out)
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        db.unlink()  # no database: none is created
        subprocess.run([sys.executable, str(ROOT / "scripts/validate/take_set_inventory.py"), "--root",
                        str(self.root)], capture_output=True, text=True, check=True)
        self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
