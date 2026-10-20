"""Added takes, own take sets and replacement sets on sounds WITH a SU/SP subtitle entry (owner, 2026-10-19): the
barks-only rule is lifted, with ONE subtitle per set (`own_sets[].subtitle`). Eligibility, the set subtitle's
lifecycle (draft / approve / needs rework, immutability, tools never approve), the conversion prefill, the switch,
undo, the build outcome and the validator. Synthetic data only (temporary roots).

Run: python -m unittest tests.test_set_subtitles
"""
import copy
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import mapping_store  # noqa: E402
from common.m6_build import own_set_drops, plan_audio, plan_inserts, subtitle_plan  # noqa: E402
from common.mapping_store import ProtectedError, UserAction  # noqa: E402
from common.mcc_loc import SPEAKER_SEP, loc_key  # noqa: E402
from common.project_validation import check_approved_protected, own_set_findings, validate_mappings  # noqa: E402
from common.jsonschema_lite import load_schema  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
from test_m4 import T  # noqa: E402
from test_mcc_loc_patch import build as build_loc  # noqa: E402
from test_take_set_conversion import GRUNT, MX, Flow, multi_record  # noqa: E402

MON = T + "z10_080_monitor"     # three Spain takes, WITH a subtitle entry (like d40_monitor_player)
M = [f"es:Z10_080_monitor_{k}#0" for k in (1, 2, 3)]
STEREO_SUB = T + "z10_090_stereo_sub"  # stereo, with a subtitle entry: still refused


class SubtitledBase(Flow):
    def setUp(self):
        super().setUp()
        cat = self.root / "work/mcc/catalog/z10.jsonl"
        recs = [json.loads(x) for x in cat.read_text().splitlines()]
        recs.append(multi_record("Z10_080_monitor", MON, 10, 3, data="89a"))
        recs.append(multi_record("Z10_090_stereo_sub", STEREO_SUB, 13, 2, channels=2, data="bc"))
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs))
        keys = {loc_key(T + "z10_010_keyes"): ("Despierte, Jefe Maestro.", "Despierta, jefe maestro.",
                                               f"cor&idKEYES{SPEAKER_SEP}Wake up, Master Chief."),
                loc_key(T + "z10_020_cortana"): ("¿Qué pasó?", "¿Qué ha pasado?", "What happened?"),
                loc_key(MON): ("Tú, el reclamador.", "Tú, el reclamador.", "You, Reclaimer."),
                loc_key(STEREO_SUB): ("Estéreo.", "Estéreo.", "Stereo.")}
        for n, name in enumerate(("SU", "SP", "EN")):
            ks = sorted(keys)
            (self.root / f"work/mcc/loc/copies/{name}_Halo1.bin").write_bytes(
                build_loc(ks, [keys[k][n] for k in ks], name=f"{name}_Halo1".encode()))
        self.app = M4App(self.root, today=lambda: "2026-10-19", run_validator=False)

    # ------------------------------------------------------------------ helpers
    def sound(self, tag=MON):
        return self.app.sound(tag)

    def local(self):
        return mapping_store.load_or_default(self.local_path, {"schema": "manual-mappings-local/1",
                                                               "custom_subtitles": {}, "user_recordings": {}})

    def put_custom(self, ref, text):
        doc, sha = self.local()
        doc = copy.deepcopy(doc)
        doc["custom_subtitles"][ref] = {"text": text, "updated_at": "2026-10-19"}
        mapping_store.save_user_file(self.local_path, doc, sha, "manual-mappings-local-1")

    def set_sub(self, tag=MON, **body):
        return self.app.set_subtitle({"mcc_tag": tag, "loaded_takes_sha256": self.sound(tag)["version"], **body})

    def own_on(self, tag=MON, refs=("line_a#0",), **extra):
        s = self.sound(tag)
        return self.app.own_set_on({"mcc_tag": tag, "loaded_takes_sha256": s["version"],
                                    "loaded_sound_sha256": s["sound_version"],
                                    "clear_mapping_ids": [t["mapping_id"] for t in s["spain_takes"] if t["mapping_id"]],
                                    "audio_list": [{"ce_line_ref": r, "language": MX} for r in refs], **extra})

    def own(self, tag=MON):
        return next(o for o in self.doc()["own_sets"] if o["mcc_tag"] == tag)

    def plan(self, levels=("z10",)):
        local, _ = self.local()
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        return subtitle_plan(self.doc(), set(levels), local=local,
                             tables={t: self.app.loc[t] for t in ("SU", "SP")}, **idx)

    def key_of(self, plan, tag=MON):
        return next((k for k in plan["keys"] if k["key"] == loc_key(tag)), None)

    def errors(self, doc=None):
        local, _ = self.local()
        findings, _ = validate_mappings(doc or self.doc(), load_schema("manual-mappings-3"), ce=self.app.ce_idx,
                                        mcc=self.app.mcc_idx, local=local, verifications={"verifications": []},
                                        current_pins={}, subtitle_keys=self.app._subtitle_keys())
        return [f for f in findings if f["severity"] == "error"]


class EligibilityTests(SubtitledBase):
    def test_mono_subtitled_sounds_are_allowed_and_stereo_still_refused(self):
        self.assertEqual(self.app.take_rule(MON), (True, ""))
        allowed, reason = self.app.take_rule(STEREO_SUB)
        self.assertFalse(allowed)
        self.assertIn("stereo", reason)
        s = self.sound()
        self.assertTrue(s["has_subtitle_entry"])
        self.assertEqual(s["mcc_text"], {"SU": "Tú, el reclamador.", "SP": "Tú, el reclamador."})
        self.assertFalse(self.sound(GRUNT)["has_subtitle_entry"])
        self.assertIsNone(self.sound(GRUNT)["mcc_text"])

    def test_added_takes_on_a_subtitled_sound_without_a_set_share_the_line_subtitles(self):
        r = self.app.take_save({"mcc_tag": MON, "loaded_takes_sha256": self.sound()["version"],
                                "audio": {"ce_line_ref": "line_a#0", "language": MX}})
        self.approve_take(r["take_id"], MON)
        local, _ = self.local()
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        ins = plan_inserts(self.doc(), ["z10"], local=local, subtitle_keys=self.app._subtitle_keys(), **idx)
        self.assertEqual([(e["take_id"], e["action"]) for e in ins], [(r["take_id"], "insert")])
        self.assertIsNone(self.sound()["set_subtitle"])  # no set: the line decisions still govern the key
        for sid in M:  # every take approves 'none': the key is written empty, as before
            self.put(sid, "line_a#0", subtitle={"source": "none", "status": "approved"})
        k = self.key_of(self.plan())
        self.assertEqual((k["action"], k["text"]), ("write", ""))
        self.assertEqual(self.errors(), [])


class SetSubtitleLifecycleTests(SubtitledBase):
    def test_draft_approve_immutable_rework_and_custom_text_stays_local(self):
        self.own_on(subtitle={"source": "custom", "custom_text": "Tú, Reclamador."})
        sub = self.own()["subtitle"]
        self.assertEqual((sub["status"], sub["source"], sub["revision"], sub["fingerprint"]),
                         ("draft", "custom", 1, None))
        ref = sub["custom_ref"]
        self.assertNotIn("Tú, Reclamador.", self.path.read_text(encoding="utf-8"))  # text only in the local file
        self.assertEqual(self.local()[0]["custom_subtitles"][ref]["text"], "Tú, Reclamador.")
        view = self.sound()["set_subtitle"]
        self.assertEqual((view["text"], view["custom_text"], view["drift"]), ("Tú, Reclamador.", "Tú, Reclamador.", False))

        self.set_sub(actions=[{"action": "approve"}])
        sub = self.own()["subtitle"]
        self.assertEqual((sub["status"], sub["approved_at"]), ("approved", "2026-10-19"))
        self.assertEqual(sub["fingerprint"]["mcc"], {"mcc_tag": MON})
        for change in ({"source": "none"}, {"source": "custom", "custom_text": "Otro texto."}):
            with self.assertRaises(ApiError) as e:  # approved: read-only
                self.set_sub(subtitle=change)
            self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ApiError):  # cannot clear an approved one
            self.set_sub(subtitle=None)

        self.set_sub(actions=[{"action": "needs_rework"}])
        sub = self.own()["subtitle"]
        self.assertEqual((sub["status"], sub["revision"], sub["fingerprint"]), ("needs_rework", 2, None))
        self.set_sub(subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "line_a#0", "culture": "es-MX"}})
        sub = self.own()["subtitle"]
        self.assertEqual((sub["source"], sub["custom_ref"], sub["status"]), ("ce_locres", None, "needs_rework"))
        self.assertEqual(self.sound()["set_subtitle"]["text"], "Jefe Maestro, despierte")
        self.set_sub(subtitle=None)  # back to undecided (not approved)
        self.assertNotIn("subtitle", self.own())

    def test_tools_never_approve_and_the_store_protects_an_approved_set_subtitle(self):
        self.own_on(subtitle={"source": "none"})
        doc, sha = mapping_store.load(self.path)
        forged = copy.deepcopy(doc)
        o = next(x for x in forged["own_sets"] if x["mcc_tag"] == MON)
        o["subtitle"].update(status="approved", approved_at="2026-10-19", fingerprint={})
        with self.assertRaises(ProtectedError):  # no user action: refused
            mapping_store.save(self.path, forged, sha)
        self.set_sub(actions=[{"action": "approve"}])
        doc, sha = mapping_store.load(self.path)
        edited = copy.deepcopy(doc)
        next(x for x in edited["own_sets"] if x["mcc_tag"] == MON)["subtitle"]["source"] = "keep_original"
        with self.assertRaises(ProtectedError):  # approved: immutable, even with an 'approve' action
            mapping_store.save(self.path, edited, sha, user_actions=[UserAction("approve", MON, "subtitle")])
        gone = copy.deepcopy(doc)
        gone["own_sets"] = [x for x in gone["own_sets"] if x["mcc_tag"] != MON]
        if not gone["own_sets"]:
            gone.pop("own_sets")
        with self.assertRaises(ProtectedError):  # the set cannot go while its subtitle is approved
            mapping_store.save(self.path, gone, sha)
        # validator against a committed HEAD: a silent change is an error, a rework is not
        head = copy.deepcopy(doc)
        self.assertEqual([f["code"] for f in check_approved_protected(head, edited)], ["approved_object_modified"])
        reworked = copy.deepcopy(doc)
        next(x for x in reworked["own_sets"] if x["mcc_tag"] == MON)["subtitle"].update(
            status="needs_rework", revision=2, approved_at=None, fingerprint=None)
        self.assertEqual(check_approved_protected(head, reworked), [])

    def test_back_to_spain_reworks_the_approved_set_subtitle_in_the_same_save(self):
        self.own_on(subtitle={"source": "none"})
        self.set_sub(actions=[{"action": "approve"}])
        self.app.own_set_off({"mcc_tag": MON, "loaded_takes_sha256": self.sound()["version"]})
        self.assertNotIn("own_sets", self.doc())
        conn = sqlite3.connect(self.root / "mappings/manual_mappings.db")
        rows = conn.execute("SELECT before_body, after_body FROM own_set_history WHERE mcc_tag = ? ORDER BY id",
                            (MON,)).fetchall()
        conn.close()
        self.assertEqual(json.loads(rows[-1][0])["subtitle"]["status"], "approved")
        self.assertIsNone(rows[-1][1])

    def test_set_subtitle_is_refused_without_an_entry_or_a_set(self):
        with self.assertRaises(ApiError) as e:  # no own set yet
            self.set_sub(subtitle={"source": "none"})
        self.assertEqual(e.exception.status, 409)
        self.own_on(GRUNT)
        with self.assertRaises(ApiError) as e:  # no subtitle entry
            self.set_sub(GRUNT, subtitle={"source": "none"})
        self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ApiError) as e:  # an unknown CE line
            self.own_on(subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "nope#0", "culture": "es-MX"}})
        self.assertEqual(e.exception.status, 400)

    def test_turning_the_set_on_clears_line_subtitles_into_the_record(self):
        mid = self.put(M[0], "line_a#0", subtitle={"source": "none", "status": "approved"})
        r = self.own_on(subtitle={"source": "keep_original"})
        self.assertIn(f"{mid}/subtitle", r["reworked"])
        rec = self.own()["provenance"]["slots"]
        self.assertEqual([(m["mapping_id"], m["subtitle"]["source"], m["subtitle"]["status"]) for m in rec],
                         [(mid, "none", "approved")])  # recorded exactly
        self.assertEqual([m for m in self.doc()["slots"] if m["mcc_tag"] == MON], [])


class ConversionPrefillTests(SubtitledBase):
    def test_every_take_agrees_on_none_prefills_a_draft(self):
        for sid, ref in zip(M, ("line_a#0", "line_b#0", "line_a#0")):
            self.put(sid, ref, subtitle={"source": "none", "status": "approved"})
        item = self.preview(MON)
        self.assertTrue(item["eligible"])
        self.assertEqual(item["set_subtitle"]["prefill"], {"source": "none", "ce_locres": None, "custom_text": None})
        self.assertIn("set_subtitle_prefilled", [i["code"] for i in item["issues"]])
        self.stage(MON, ack=item["review_codes"])
        sub = self.own()["subtitle"]
        self.assertEqual((sub["status"], sub["source"], sub["revision"], sub["approved_at"], sub["fingerprint"]),
                         ("draft", "none", 1, None, None))  # approvals are never copied

    def test_takes_that_disagree_leave_it_undecided_and_need_review(self):
        self.put(M[0], "line_a#0", subtitle={"source": "none", "status": "approved"})
        self.put(M[1], "line_b#0", subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "line_b#0",
                                                                                    "culture": "es-MX"}})
        self.put(M[2], "line_a#0", subtitle={"source": "none", "status": "approved"})
        item = self.preview(MON)
        self.assertIsNone(item["set_subtitle"]["prefill"])
        self.assertIn("set_subtitle_undecided", item["review_codes"])
        with self.assertRaises(ApiError):  # a review point: not without the owner's acknowledgement
            self.stage(MON, ack=[c for c in item["review_codes"] if c != "set_subtitle_undecided"])
        self.stage(MON, ack=item["review_codes"])
        self.assertNotIn("subtitle", self.own())

    def test_a_take_without_a_decision_means_undecided(self):
        self.put(M[0], "line_a#0", subtitle={"source": "none", "status": "approved"})
        self.put(M[1], "line_a#0", subtitle={"source": "none", "status": "approved"})
        item = self.preview(MON)
        self.assertIsNone(item["set_subtitle"]["prefill"])
        self.assertIn(M[2], item["set_subtitle"]["reason"])

    def test_agreed_custom_text_gets_its_own_new_local_ref(self):
        self.put_custom("c-000001", "Tú, Reclamador.")
        self.put_custom("c-000002", "Tú, Reclamador.")
        self.put_custom("c-000003", "Tú, Reclamador.")
        for k, (sid, ref) in enumerate(zip(M, ("line_a#0", "line_b#0", "line_a#0"))):
            self.put(sid, ref, subtitle={"source": "custom", "custom_ref": f"c-00000{k + 1}", "status": "approved"})
        item = self.preview(MON)
        self.assertEqual(item["set_subtitle"]["prefill"]["custom_text"], "Tú, Reclamador.")
        self.assertNotIn("subtitle_text", item["review_codes"])  # weighed for the sound, not per take
        self.stage(MON, ack=item["review_codes"])
        sub = self.own()["subtitle"]
        self.assertEqual((sub["source"], sub["status"], sub["custom_ref"]), ("custom", "draft", "c-000004"))
        self.assertEqual(self.local()[0]["custom_subtitles"]["c-000004"]["text"], "Tú, Reclamador.")
        self.assertEqual(self.errors(), [])


class SwitchUndoBuildTests(SubtitledBase):
    def staged_with_approved_takes(self):
        mids = [self.put(sid, ref, subtitle={"source": "none", "status": "approved"})
                for sid, ref in zip(M, ("line_a#0", "line_b#0", "line_a#0"))]
        item = self.preview(MON)
        self.stage(MON, ack=item["review_codes"])
        self.approve_unchanged(MON)
        return mids

    def test_switch_needs_the_set_subtitle_approved_then_undo_restores_line_subtitles_exactly(self):
        mids = self.staged_with_approved_takes()
        before = sorted((m for m in self.doc()["slots"] if m["mcc_tag"] == MON), key=lambda m: m["mapping_id"])
        staged_plan = self.plan()  # a staged set changes nothing: the lines' approved 'none' is written
        self.assertEqual((self.key_of(staged_plan)["action"], self.key_of(staged_plan)["text"]), ("write", ""))
        with self.assertRaises(ApiError) as e:  # the set's subtitle is a draft
            self.activate(MON)
        self.assertEqual(e.exception.status, 409)
        self.assertIn("subtitle", " ".join(e.exception.details))
        self.set_sub(actions=[{"action": "approve"}])
        self.activate(MON)
        doc = self.doc()
        self.assertEqual([m for m in doc["slots"] if m["mcc_tag"] == MON], [])
        k = self.key_of(self.plan())
        self.assertEqual((k["action"], k["text"], k["slots"]), ("write", "", ["own set z10_080_monitor"]))
        self.assertEqual(self.errors(), [])

        preview = self.app.convert_revert_preview(MON)
        self.assertEqual(preview["conflicts"], [])
        self.assertEqual({r["subtitle"] for r in preview["restore"]}, {"approval restored"})
        self.undo(MON)
        after = sorted((m for m in self.doc()["slots"] if m["mcc_tag"] == MON), key=lambda m: m["mapping_id"])
        self.assertEqual(after, before)  # subtitle approvals, fingerprints, revisions: exact
        self.assertEqual(sorted(m["mapping_id"] for m in after), sorted(mids))
        self.assertNotIn("own_sets", self.doc())
        self.assertEqual(self.errors(), [])

    def test_build_outcome_comes_from_the_set_subtitle(self):
        self.own_on(subtitle={"source": "custom", "custom_text": "Tú, Reclamador."})
        t = self.own_take()
        self.approve_take(t, MON)
        plan = self.plan()
        self.assertIsNone(self.key_of(plan))  # draft: excluded, MCC text stays, never guessed
        row = next(r for r in plan["rows"] if r.get("own_set"))
        self.assertEqual((row["category"], row["slot_id"]), ("excluded", "own set z10_080_monitor"))
        self.assertIn("MCC text stays", row["result"])
        self.set_sub(actions=[{"action": "approve"}])
        k = self.key_of(self.plan())
        self.assertEqual((k["action"], k["text"]), ("write", "Tú, Reclamador."))
        self.assertTrue(all(k["tables"][x]["write"] for x in ("SU", "SP")))
        self.set_sub(actions=[{"action": "needs_rework"}])
        self.set_sub(subtitle={"source": "keep_original"}, actions=[])
        self.set_sub(actions=[{"action": "approve"}])
        self.assertEqual(self.key_of(self.plan())["action"], "keep")
        # the audio side: the set's take is inserted and Spain's takes dropped, as for any own set
        local, _ = self.local()
        idx = dict(slot_index=self.app.slot_index, ce_lines=self.app.ce_lines, ce_idx=self.app.ce_idx,
                   mcc_idx=self.app.mcc_idx)
        ins = plan_inserts(self.doc(), ["z10"], local=local, **idx)
        self.assertEqual(own_set_drops(self.doc(), ins), [MON])
        acts = {e["slot_id"]: e["action"] for e in plan_audio(self.doc(), ["z10"], dropped_tags=[MON], **idx)["entries"]}
        self.assertEqual({acts[s] for s in M}, {"dropped"})

    def own_take(self):
        return next(t["take_id"] for t in self.doc()["added_takes"] if t["mcc_tag"] == MON)

    def test_unapproved_set_subtitle_drift_and_validator(self):
        self.own_on(subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "line_a#0", "culture": "es-MX"}})
        mcc, keys = self.app.mcc_idx, self.app._subtitle_keys()
        codes = [f["code"] for f in own_set_findings(self.doc(), mcc=mcc, subtitle_keys=keys, ce=self.app.ce_idx,
                                                     local=self.local()[0])]
        self.assertIn("own_set_subtitle_not_approved", codes)
        self.set_sub(actions=[{"action": "approve"}])
        # the CE subtitle changes afterwards: drift; the build excludes the key
        cat = self.root / "work/ce/catalog/m99.jsonl"
        recs = [json.loads(x) for x in cat.read_text(encoding="utf-8").splitlines()]
        for r in recs:
            if r["record_id"] == "line_a":
                r["entries"][0]["subtitles"]["es-MX"]["source_hash"] = "changed"
        cat.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        self.app.reload()
        self.assertTrue(self.sound()["set_subtitle"]["drift"])
        self.assertIsNone(self.key_of(self.plan()))
        local, _ = self.local()
        _f, drift = validate_mappings(self.doc(), load_schema("manual-mappings-3"), ce=self.app.ce_idx,
                                      mcc=self.app.mcc_idx, local=local, verifications={"verifications": []},
                                      current_pins={}, subtitle_keys=self.app._subtitle_keys())
        self.assertIn("approved_own_set_subtitle", [d["kind"] for d in drift])
        # a set subtitle on a sound without an entry, or naming a missing custom text, is an error
        bad = copy.deepcopy(self.doc())
        bad["own_sets"].append({"mcc_tag": GRUNT, "set_at": "2026-10-19", "subtitle": {
            "status": "draft", "source": "custom", "ce_locres": None, "custom_ref": "c-000099", "fingerprint": None,
            "approved_at": None, "revision": 1}})
        codes = {f["code"] for f in self.errors(bad)}
        self.assertTrue({"own_set_subtitle_without_entry", "unknown_custom_ref"} <= codes)


if __name__ == "__main__":
    unittest.main()
