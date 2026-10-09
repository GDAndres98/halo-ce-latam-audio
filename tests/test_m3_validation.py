"""M3 tests: schemas, the stdlib schema engine, semantic validation, the
protected mapping store and the slot-ID change guard. All data is synthetic
(made-up IDs and hashes); the only repo files read are the committed
schemas and empty templates.

Run: python -m unittest discover -s tests
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import mapping_store  # noqa: E402
from common.jsonschema_lite import UnsupportedKeyword, load_schema, validate  # noqa: E402
from common.mapping_store import ProtectedError, StaleError, StoreError, UserAction  # noqa: E402
from common.project_validation import (  # noqa: E402
    audio_fingerprint, build_ce_index, build_mcc_index, check_approved_protected, compare_slot_identity,
    subtitle_fingerprint, validate_catalog, validate_mappings, validate_mission_map, validate_verifications)

H = {c: c * 64 for c in "abcdef0123456789"}  # fake sha256 values
MAP_SCHEMA = load_schema("manual-mappings-3")
VER_SCHEMA = load_schema("verifications-1")
CE_SCHEMA = load_schema("ce-voice-asset-3")
MCC_SCHEMA = load_schema("mcc-dialogue-tag-3")
TAG = "sound\\dialog\\z10\\z10_010_keyes"


# --------------------------------------------------------------------------- synthetic catalogs
def ce_record(rid, flags=(), mx="explicit", sub_mx="explicit", media_id=100, wem="a"):
    media = {"evidence": mx, "media": [{"media_id": media_id, "media_path": "Media/x.wem", "exists_evidence": "explicit:index",
                                        "wem_sha256": H[wem], "duration_s": None}]} if mx == "explicit" else \
        {"evidence": "unresolved", "reason": "language not in EventLanguageMap"}
    sub = ({"evidence": "explicit", "namespace": "NS", "key": rid.upper(), "source_hash": 7, "text": "t"}
           if sub_mx == "explicit" else {"evidence": "unresolved", "reason": "no transcription reference"})
    return {"schema": "ce-voice-asset/3", "record_id": rid, "ce_line_key": rid, "ce_line_key_evidence": "explicit",
            "display_key": rid.upper(), "asset_name": rid, "family": "scripted", "family_evidence": "derived:vfs_folder",
            "mission": "M99", "mission_evidence": "derived:vfs_folder_name", "folder": "F",
            "voice_asset": {"vfs_path": f"Meteorite/Content/Audio/scripted/F/{rid}.uasset", "container": "c",
                            "class": "HaloAudioVoiceVariations", "class_evidence": "explicit"},
            "entries": [{"index": 0, "ce_line_ref": f"{rid}#0", "event": {"evidence": "explicit"},
                         "transcription": {"evidence": "explicit"}, "lipsync": {"evidence": "unresolved", "reason": "x"},
                         "media": {"Spanish(Mexico)": media, "English(US)": media},
                         "subtitles": {"es-MX": sub, "en": sub}}],
            "flags": sorted(flags), "ambiguities": [],
            "source_build": {"exe_file_version": "ce-1", "steam_buildid": "1"}}


def mcc_record(name="Z10_010_keyes", tag=TAG, index=0, data="b", fsb="c"):
    sample = {"index": index, "subsong": index + 1, "name_in_bank": name, "name_occurrence_in_bank": 0,
              "ordinal_in_tag": 0, "codec": "CELT", "freq": 44100, "channels": 1, "sample_count": 10,
              "duration_s": 0.1, "data_sha256": H[data], "evidence": "explicit"}
    lst = {"first_sample_index": index, "sample_count": 1, "evidence": "derived:lst_record_layout",
           "agrees_with_name_table": True}
    return {"schema": "mcc-dialogue-tag/3", "mcc_tag": tag, "tag_name": tag.rsplit("\\", 1)[-1], "level": "z10",
            "kind": "scripted", "sequence": "010", "speaker_from_name": "keyes", "name_evidence": "derived:tag_name",
            "lst": {"spanish": lst, "english": lst},
            "samples": {"spanish": [{**sample, "slot_id": f"es:{name}#0"}], "english": [dict(sample, data_sha256=H["d"])]},
            "slot_ids": [f"es:{name}#0"], "flags": [],
            "subtitle": {"key_hash": None, "evidence": "unresolved", "reason": "B1"},
            "source": {"spanish_fsb_sha256": H[fsb], "english_fsb_sha256": H["e"], "steam": {"steam_buildid": "9"}}}


CE = build_ce_index([ce_record("line_a"), ce_record("line_b", media_id=200, wem="f"),
                     ce_record("lipsync_x", flags=("test_event",), mx="unresolved"),
                     ce_record("replay_y", sub_mx="unresolved")])
MCC = build_mcc_index([mcc_record()])
SLOT = "es:Z10_010_keyes#0"
PINS = {"ce_build": "ce-1", "mcc_steam_buildid": "9", "mcc_spanish_fsb_sha256": H["c"]}
LOCAL = {"schema": "manual-mappings-local/1", "custom_subtitles": {"c-000001": {"text": "hola", "updated_at": "2026-10-08"}},
         "user_recordings": {"r-000001": {"path": "D:/x.wav", "sha256": H["1"]}}}


def slot(**over):
    s = {"mapping_id": "m-000001", "slot_id": SLOT, "mcc_tag": TAG,
         "match": {"status": "matched", "ce_line_refs": ["line_a#0"], "decided_at": "2026-10-08", "revision": 1},
         "audio": {"status": "draft", "source": "ce",
                   "sources": [{"kind": "ce", "ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"}],
                   "edit": {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0}, "fingerprint": None,
                   "approved_at": None, "revision": 1},
         "subtitle": {"status": "draft", "source": "custom", "ce_locres": None, "custom_ref": "c-000001",
                      "mcc_key_hash": None, "mcc_key_verification": None, "fingerprint": None, "approved_at": None,
                      "revision": 1},
         "radio_effect": {"needed": False, "set_at": None, "revision": 1},
         "notes": ""}
    for path, v in over.items():
        cur = s
        keys = path.split("__")
        for k in keys[:-1]:
            cur = cur[k]
        cur[keys[-1]] = v
    return s


def doc(*slots, pins=PINS):
    return {"schema": "manual-mappings/3", "pins": dict(pins), "slots": list(slots)}


def check(d, local=LOCAL, verifications=None, ce=CE, mcc=MCC):
    return validate_mappings(d, MAP_SCHEMA, ce=ce, mcc=mcc, local=local, verifications=verifications,
                             current_pins=PINS)


def codes(findings, severity="error"):
    return sorted({f["code"] for f in findings if f["severity"] == severity})


def approve(s, field, ce=CE, mcc=MCC, local=LOCAL):
    fn = audio_fingerprint if field == "audio" else subtitle_fingerprint
    s[field].update(status="approved", approved_at="2026-10-08", fingerprint=fn(s, ce, mcc, local))
    return s


# --------------------------------------------------------------------------- tests
class SchemaEngineTests(unittest.TestCase):
    def test_unsupported_keyword_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.schema.json"
            p.write_text(json.dumps({"type": "object", "format": "email"}), encoding="utf-8")
            with self.assertRaises(UnsupportedKeyword):
                load_schema(p)

    def test_core_keywords(self):
        s = {"$defs": {"n": {"type": "integer", "minimum": 1}}, "type": "object", "required": ["a"],
             "additionalProperties": False,
             "properties": {"a": {"$ref": "#/$defs/n"}, "b": {"oneOf": [{"type": "string"}, {"type": "null"}]},
                            "c": {"type": "array", "uniqueItems": True, "items": {"enum": [1, 2]}}},
             "if": {"properties": {"a": {"const": 2}}}, "then": {"required": ["b"]}}
        self.assertEqual(validate({"a": 1, "c": [1, 2]}, s), [])
        errs = " ".join(validate({"a": 2, "c": [1, 1, 3], "z": 0}, s))
        for needle in ("not unique", "not in", "unexpected property", "missing required property 'b'"):
            self.assertIn(needle, errs)
        self.assertTrue(validate({"a": 0}, s))

    def test_all_project_schemas_load_and_templates_validate(self):
        for name in ("ce-voice-asset-3", "mcc-dialogue-tag-3", "manual-mappings-2", "manual-mappings-3", "manual-mappings-local-1",
                     "verifications-1", "mission-map-1"):
            load_schema(name)
        for rel, schema in (("mappings/manual_mappings.json", "manual-mappings-3"),
                            ("mappings/manual_mappings.local.example.json", "manual-mappings-local-1"),
                            ("mappings/mission_map.json", "mission-map-1")):
            d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            self.assertEqual(validate(d, load_schema(schema)), [], rel)
        self.assertEqual(json.loads((ROOT / "mappings/manual_mappings.json").read_text(encoding="utf-8"))["slots"], [])

    def test_catalog_schemas_are_separate(self):
        self.assertEqual(validate(ce_record("line_a"), CE_SCHEMA), [])
        self.assertEqual(validate(mcc_record(), MCC_SCHEMA), [])
        self.assertTrue(validate(ce_record("line_a"), MCC_SCHEMA))
        self.assertTrue(validate(mcc_record(), CE_SCHEMA))
        bad = mcc_record()
        bad["subtitle"]["key_hash"] = 123  # unresolved subtitle may not carry a guessed key
        self.assertTrue(validate(bad, MCC_SCHEMA))


class MappingRuleTests(unittest.TestCase):
    def test_independent_audio_and_subtitle_combinations_are_valid(self):
        keep_audio_ce_sub = slot(audio__source="keep_original", audio__sources=[], subtitle__source="ce_locres",
                                 subtitle__custom_ref=None,
                                 subtitle__ce_locres={"ce_line_ref": "line_a#0", "culture": "es-MX"})
        concat = slot(mapping_id="m-000002", slot_id=SLOT, audio__source="ce_concat",
                      match__ce_line_refs=["line_a#0", "line_b#0"],
                      audio__sources=[{"kind": "ce", "ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"},
                                      {"kind": "ce", "ce_line_ref": "line_b#0", "language": "Spanish(Mexico)"}])
        composite = slot(audio__source="composite",
                         audio__sources=[{"kind": "ce", "ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"},
                                         {"kind": "user_recording", "ref": "r-000001"}])
        unmatched = slot(match__status="no_equivalent", match__ce_line_refs=[], audio__source="keep_original",
                         audio__sources=[])
        for s in (slot(), keep_audio_ce_sub, concat, composite, unmatched):
            f, drift = check(doc(s))
            self.assertEqual(codes(f), [], s["audio"]["source"])
            self.assertEqual(drift, [])

    def test_schema_level_rules(self):
        bad = [
            slot(audio__source="ce_concat"),                                         # needs >= 2 sources
            slot(audio__source="keep_original"),                                     # must have no sources
            slot(match__status="no_equivalent"),                                     # unmatched with refs
            slot(match__status="matched", match__ce_line_refs=[]),                   # matched without refs
            slot(audio__status="approved"),                                          # approval w/o fingerprint
            slot(subtitle__source="ce_locres"),                                      # custom_ref with ce_locres
            slot(subtitle__mcc_key_hash=123),                                        # key without verification id
            slot(audio__fx_request="radio"),                                        # moved out in v3
            slot(radio_effect__needed="yes"),
            slot(mapping_id="m-1"),
        ]
        for s in bad:
            self.assertIn("schema", codes(check(doc(s))[0]))

    def test_ids_references_duplicates_and_conflicts(self):
        cases = {
            "duplicate_mapping_id": doc(slot(), slot(slot_id="es:Other#0")),
            "conflicting_slot_decisions": doc(slot(), slot(mapping_id="m-000002")),
            "unknown_slot_id": doc(slot(slot_id="es:Nope#0")),
            "mcc_tag_mismatch": doc(slot(mcc_tag="sound\\dialog\\z10\\other")),
            "unknown_ce_line_ref": doc(slot(match__ce_line_refs=["ghost#0"],
                                            audio__sources=[{"kind": "ce", "ce_line_ref": "ghost#0",
                                                             "language": "Spanish(Mexico)"}])),
            "audio_source_not_in_match": doc(slot(audio__sources=[{"kind": "ce", "ce_line_ref": "line_b#0",
                                                                   "language": "Spanish(Mexico)"}])),
            "audio_conflicts_with_match": doc(slot(match__status="deferred")),
            "test_event_audio_source": doc(slot(match__ce_line_refs=["lipsync_x#0"],
                                                audio__sources=[{"kind": "ce", "ce_line_ref": "lipsync_x#0",
                                                                 "language": "Spanish(Mexico)"}])),
            "unknown_custom_ref": doc(slot(subtitle__custom_ref="c-000009")),
            "unknown_user_recording": doc(slot(audio__source="user_recording",
                                               audio__sources=[{"kind": "user_recording", "ref": "r-000009"}],
                                               match__status="no_equivalent", match__ce_line_refs=[])),
            "local_path_in_committed_file": doc(slot(notes="see C:\\Users\\me\\take.wav")),
            "unverified_subtitle_key": doc(slot(subtitle__mcc_key_hash=123, subtitle__mcc_key_verification="v-000001")),
        }
        for code, d in cases.items():
            self.assertIn(code, codes(check(d)[0]), code)
        self.assertIn("local_file_missing", codes(check(doc(slot()), local=None)[0]))

    def test_unresolved_sources_are_warnings_in_draft_and_errors_when_approved(self):
        s = slot(subtitle__source="ce_locres", subtitle__custom_ref=None,
                 subtitle__ce_locres={"ce_line_ref": "replay_y#0", "culture": "es-MX"},
                 match__ce_line_refs=["line_a#0", "replay_y#0"])
        self.assertIn("subtitle_unresolved", codes(check(doc(s))[0], "warning"))
        approve(s, "subtitle")
        self.assertIn("subtitle_unresolved", codes(check(doc(s))[0]))

    def test_verified_subtitle_key_is_accepted(self):
        ver = {"verifications": [{"id": "v-000001", "subject": f"mcc:{SLOT}", "checks": ["subtitle_key_link"],
                                  "result": "pass"}]}
        s = slot(subtitle__mcc_key_hash=123, subtitle__mcc_key_verification="v-000001")
        self.assertNotIn("unverified_subtitle_key", codes(check(doc(s), verifications=ver)[0]))

    def test_approved_fingerprint_drift_is_reported_never_fixed(self):
        s = approve(approve(slot(), "audio"), "subtitle")
        d = doc(s)
        before = copy.deepcopy(d)
        f, drift = check(d)
        self.assertEqual((codes(f), drift), ([], []))
        ce2 = build_ce_index([ce_record("line_a", media_id=999, wem="9"), ce_record("line_b")])
        f, drift = check(d, ce=ce2)
        self.assertIn("approved_fingerprint_drift", codes(f, "warning"))
        self.assertEqual([x["field"] for x in drift], ["audio"])
        local2 = copy.deepcopy(LOCAL)
        local2["custom_subtitles"]["c-000001"]["text"] = "changed"
        self.assertEqual([x["field"] for x in check(d, local=local2)[1]], ["subtitle"])
        self.assertEqual(d, before)

    def test_pins(self):
        f, drift = check(doc(slot(), pins={**PINS, "ce_build": "ce-0"}))
        self.assertIn("pin_mismatch", codes(f, "warning"))
        self.assertEqual(drift[0]["kind"], "pin")
        self.assertIn("pin_unset", codes(check(doc(slot(), pins={k: None for k in PINS}))[0], "warning"))


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.head = doc(approve(slot(), "audio"))

    def test_head_comparison(self):
        same = copy.deepcopy(self.head)
        self.assertEqual(check_approved_protected(self.head, same), [])
        edited = copy.deepcopy(self.head)
        edited["slots"][0]["audio"]["edit"]["trim_end_s"] = 0.5
        self.assertEqual(codes(check_approved_protected(self.head, edited)), ["approved_object_modified"])
        rework = copy.deepcopy(self.head)
        rework["slots"][0]["audio"].update(status="needs_rework", revision=2)
        self.assertEqual(check_approved_protected(self.head, rework), [])
        self.assertEqual(codes(check_approved_protected(self.head, doc())), ["approved_mapping_removed"])
        moved = copy.deepcopy(self.head)
        moved["slots"][0]["slot_id"] = "es:Other#0"
        self.assertIn("approved_mapping_retargeted", codes(check_approved_protected(self.head, moved)))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "manual_mappings.json"
        self.path.write_text(json.dumps(doc(slot())), encoding="utf-8")
        self.hist = Path(self.tmp.name) / ".history"

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, d, sha, actions=()):
        return mapping_store.save(self.path, d, sha, user_actions=actions, history_dir=self.hist)

    def test_tool_cannot_approve_but_user_can(self):
        d, sha = mapping_store.load(self.path)
        new = copy.deepcopy(d)
        approve(new["slots"][0], "audio")
        with self.assertRaises(ProtectedError):
            self.save(new, sha)
        sha2 = self.save(new, sha, [UserAction("approve", "m-000001", "audio")])
        self.assertEqual(mapping_store.load(self.path)[1], sha2)
        self.assertEqual(len(list(self.hist.iterdir())), 1)  # backup made before the save

    def test_approved_is_immutable_except_user_needs_rework(self):
        d, sha = mapping_store.load(self.path)
        approve(d["slots"][0], "subtitle")
        sha = self.save(d, sha, [UserAction("approve", "m-000001", "subtitle")])
        d, sha = mapping_store.load(self.path)
        tamper = copy.deepcopy(d)
        tamper["slots"][0]["subtitle"]["custom_ref"] = "c-000002"
        with self.assertRaises(ProtectedError):
            self.save(tamper, sha)
        with self.assertRaises(ProtectedError):
            self.save(doc(), sha)  # deleting the approved mapping
        rework = copy.deepcopy(d)
        rework["slots"][0]["subtitle"].update(status="needs_rework", revision=1)  # revision not bumped
        with self.assertRaises(ProtectedError):
            self.save(rework, sha, [UserAction("needs_rework", "m-000001", "subtitle")])
        rework["slots"][0]["subtitle"]["revision"] = 2
        self.save(rework, sha, [UserAction("needs_rework", "m-000001", "subtitle")])
        self.assertEqual(mapping_store.load(self.path)[0]["slots"][0]["subtitle"]["status"], "needs_rework")

    def test_stale_and_invalid_saves_leave_file_untouched(self):
        d, sha = mapping_store.load(self.path)
        original = self.path.read_bytes()
        with self.assertRaises(StaleError):
            self.save(d, "0" * 64)
        bad = copy.deepcopy(d)
        bad["slots"][0]["audio"]["source"] = "ce_concat"
        with self.assertRaises(StoreError):
            self.save(bad, sha)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(any(p.suffix == ".tmp" for p in self.path.parent.iterdir()))


class VerificationTests(unittest.TestCase):
    def ver(self, n, subject, fp):
        return {"id": f"v-{n:06d}", "subject": subject, "checks": ["correct_audio"], "languages": ["x"],
                "fingerprint": fp, "result": "pass", "by": "user", "at": "2026-10-08", "note": ""}

    def setUp(self):
        self.doc = {"schema_version": 1, "verifications": [
            self.ver(1, "ce:line_a#0", {"media": {"Spanish(Mexico)": {"media_id": 100, "wem_sha256": H["a"]}}}),
            self.ver(2, f"mcc:{SLOT}", {"samples": {"spanish": {"index": 0, "data_sha256": H["b"]}}})]}

    def run_v(self, d, head=None, ce=CE, mcc=MCC):
        return validate_verifications(d, VER_SCHEMA, ce=ce, mcc=mcc, head_doc=head)

    def test_clean_append_only_and_sequence(self):
        self.assertEqual(self.run_v(self.doc, head={"verifications": self.doc["verifications"][:1]}), ([], []))
        changed = copy.deepcopy(self.doc)
        changed["verifications"][0]["result"] = "fail"
        self.assertIn("verifications_not_append_only", codes(self.run_v(changed, head=self.doc)[0]))
        gap = copy.deepcopy(self.doc)
        gap["verifications"][1]["id"] = "v-000005"
        self.assertIn("verification_id_sequence", codes(self.run_v(gap)[0]))

    def test_drift_and_unknown_subjects(self):
        mcc2 = build_mcc_index([mcc_record(index=4, data="9")])  # same slot_id, different sample
        f, drift = self.run_v(self.doc, mcc=mcc2)
        self.assertEqual([d["id"] for d in drift], ["v-000002"])
        self.assertIn("ID change", drift[0]["note"])
        unknown = copy.deepcopy(self.doc)
        unknown["verifications"][0]["subject"] = "ce:ghost#0"
        self.assertIn("unknown_subject", codes(self.run_v(unknown)[0]))


class GuardAndCatalogTests(unittest.TestCase):
    def test_slot_id_change_detection(self):
        old = [mcc_record("A", "sound\\dialog\\z10\\a", 0, "1"), mcc_record("B", "sound\\dialog\\z10\\b", 1, "2"),
               mcc_record("C", "sound\\dialog\\z10\\c", 2, "3")]
        new = [mcc_record("A", "sound\\dialog\\z10\\a", 5, "4"),     # moved: same id, other sample
               mcc_record("B2", "sound\\dialog\\z10\\b", 1, "2"),    # renamed: same bytes, new id
               mcc_record("D", "sound\\dialog\\z10\\d", 3, "5")]     # added; C removed
        got = {(c["change"], c["slot_id"]) for c in compare_slot_identity(old, new)}
        self.assertEqual(got, {("moved", "es:A#0"), ("renamed", "es:B#0"), ("removed", "es:C#0"), ("added", "es:D#0")})
        self.assertEqual(compare_slot_identity(old, old), [])

    def test_catalog_duplicates_separation_and_provenance(self):
        build = {"files": {"spanish.fsb": {"sha256": H["c"]}},
                 "catalogs": {"z10": {"path": "work/mcc/catalog/z10.jsonl", "sha256": H["0"]}}}
        recs = [mcc_record(), mcc_record(fsb="7"), ce_record("line_a")]
        f = validate_catalog("z10.jsonl", recs, MCC_SCHEMA, "mcc-dialogue-tag/3", build, H["1"])
        self.assertEqual(codes(f), ["catalog_changed_since_build", "catalog_separation", "duplicate_id",
                                    "provenance_mismatch"])
        self.assertEqual(validate_catalog("z10.jsonl", [mcc_record()], MCC_SCHEMA, "mcc-dialogue-tag/3",
                                          build, H["0"]), [])

    def test_mission_map(self):
        s = load_schema("mission-map-1")
        e = {"mcc_level": "a10", "ce_missions": ["M01"], "decided_at": "2026-10-08", "note": ""}
        self.assertEqual(validate_mission_map({"schema": "mission-map/1", "entries": [e]}, s,
                                              ce_missions={"M01"}, mcc_levels={"a10"}), [])
        self.assertIn("duplicate_level", codes(validate_mission_map({"schema": "mission-map/1", "entries": [e, e]}, s,
                                                                    ce_missions=set(), mcc_levels=set())))


if __name__ == "__main__":
    unittest.main()
