"""Catalog logic tests (milestone M1). All inputs are synthetic fixtures
built here -- no game data is read or stored by these tests.

Run: python -m unittest discover -s tests
"""
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common.asset_metadata import EXPLICIT, EXPLICIT_INDEX, UNRESOLVED, fnv1_32  # noqa: E402
from common.binreader import Reader  # noqa: E402
from common.ce_assets import (  # noqa: E402
    event_languages, parse_steam_acf, parse_string_table_tail, soft_path)
from common.ce_catalog import RECORD_SCHEMA, analyze, build_record, classify, dumps_jsonl  # noqa: E402

SCR = "Meteorite/Content/Audio/scripted/VO_SCR_M99TEST"
TABLE = "/Game/Audio/Transcription/Subtitles/Scripted/VO_SCR_M99TEST"
EV_ROOT = "/Game/WwiseAudio/Events/scripted/vo_scr_m99test"
LANGS = ("Spanish(Mexico)", "English(US)", "Spanish(Spain)")
BUILD = {"exe_file_version": "synthetic-1", "steam_buildid": "0"}


def fstr(s):
    b = s.encode("utf-8") + b"\0"
    return struct.pack("<i", len(b)) + b


def imp(path):
    return {"package_index": -1, "ref": {"import": 0, "target": {"package": path, "public_export_hash": 1}}}


def voice_props(line_key, event, lipsync=None, table=TABLE):
    tr = {"Type": "Subtitle", "StringTable": imp(table), "LineKey": line_key,
          "MetaData": [{"key": "Character", "value": "TESTER"}]} if line_key else {"Type": "Subtitle"}
    return {"VoiceEvents": [{"VoiceEvent": imp(event), "Transcription": tr,
                             "LipSync": {"soft_path": lipsync or "None.None"}}],
            "Category": imp("/Game/Audio/scripted/HAC_Scripted")}


def asset(name, props, folder=SCR, cls="HaloAudioVoiceVariations"):
    return {"vfs_path": f"{folder}/{name}.uasset", "container": "pakchunk0-Windows.utoc",
            "package_name": f"/Game/x/{name}", "class": cls, "props": props, "locations": 1}


def lang_entry(event_name, media_ids):
    return {"event_id": fnv1_32(event_name),
            "media": [{"media_id": m, "media_path": f"Media/L/{m % 100:02d}/{m}.wem", "streaming": True,
                       "source_name": f"{event_name}.wav"} for m in media_ids],
            "soundbanks": [{"bank_id": fnv1_32("VO_SCR_M99"), "bank_path": "x.bnk", "bank_name": "VO_SCR_M99"}]}


class FakeResolver:
    """In-memory stand-in for the read-only game resolver."""

    def __init__(self):
        self.events = {}            # game path -> languages dict, or Exception to raise
        self.tables = {TABLE: {"vfs_path": "t", "container": "c", "class": "StringTable",
                               "namespace": "VO_SCR_M99TEST", "keys": []}}
        self.locres_tables = {"es-MX": {}, "en": {}, "es-ES": {}}
        self.media_index = {lang: set() for lang in LANGS}
        self.packages = {}

    def add_line(self, key, media_ids, cultures=("es-MX", "en", "es-ES"), langs=LANGS, in_pak=True):
        name = f"Play_{key}"
        path = f"{EV_ROOT}/{key.lower()}/{name}"
        self.events[path] = {lang: lang_entry(name, [m + i for m in media_ids]) for i, lang in enumerate(langs)}
        self.tables[TABLE]["keys"].append(key)
        for c in cultures:
            self.locres_tables[c].setdefault("VO_SCR_M99TEST", {})[key] = {"text": f"{c}:{key}", "source_hash": 7}
        if in_pak:
            for i, lang in enumerate(langs):
                for m in media_ids:
                    self.media_index[lang].add(f"Media/L/{(m + i) % 100:02d}/{m + i}.wem")
        return path

    def event(self, game_path):
        v = self.events.get(game_path)
        if isinstance(v, Exception):
            raise v
        return None if v is None else {"vfs_path": game_path, "container": "c", "class": "AkAudioEvent",
                                       "trailing_bytes_unparsed": 16, "languages": v}

    def string_table(self, game_path):
        return self.tables.get(game_path)

    def locres(self, culture):
        t = self.locres_tables.get(culture)
        return None if t is None else {"path": f"Subtitles/{culture}/Subtitles.locres", "table": t}

    def has_language(self, language):
        return language in self.media_index

    def media(self, language, path):
        if path in self.media_index.get(language, ()):
            return {"container": "lang.pak", "vfs_path": path, "wem_bytes": 10, "wem_sha256": "ab" * 32}
        return None

    def package(self, vfs_path):
        return self.packages.get(vfs_path)


class ClassifyTests(unittest.TestCase):
    def test_family_mission_and_path_flags(self):
        c = classify(f"{SCR}/VO_SCR_M99_00010_Tester.uasset")
        self.assertEqual((c["family"], c["mission"], c["folder"], c["flags"]),
                         ("scripted", "M99", "VO_SCR_M99TEST", []))
        c = classify("Meteorite/Content/Audio/scripted/vo_scr_m99test_lipsync/x_lipsync.uasset")
        self.assertIn("lipsync_variant_folder", c["flags"])
        c = classify("Meteorite/Content/Audio/cinematic/vo_cin_m99test/temp_mocap_VO_x.uasset")
        self.assertEqual((c["family"], c["mission"]), ("cinematic", "M99"))
        self.assertIn("temp_asset", c["flags"])


class BuildRecordTests(unittest.TestCase):
    def setUp(self):
        self.res = FakeResolver()

    def test_fully_explicit_line(self):
        ev = self.res.add_line("VO_SCR_M99_00010_Tester", [100])
        lip = "/Game/Audio/LipSync/Scripted/VO_SCR_M99TEST/VO_SCR_M99_00010_Tester.VO_SCR_M99_00010_Tester"
        self.res.packages["Meteorite/Content/Audio/LipSync/Scripted/VO_SCR_M99TEST/VO_SCR_M99_00010_Tester.uasset"] = \
            {"vfs_path": "lip", "class": "AnimSequence"}
        r = build_record(asset("VO_SCR_M99_00010_Tester", voice_props("VO_SCR_M99_00010_Tester", ev, lip)),
                         self.res, BUILD)
        self.assertEqual(r["schema"], RECORD_SCHEMA)
        self.assertEqual(r["source_build"], BUILD)
        self.assertEqual((r["record_id"], r["ce_line_key"], r["display_key"]),
                         ("vo_scr_m99_00010_tester", "vo_scr_m99_00010_tester", "VO_SCR_M99_00010_Tester"))
        e = r["entries"][0]
        self.assertEqual(e["ce_line_ref"], "vo_scr_m99_00010_tester#0")
        self.assertEqual(e["event"]["event_id"], fnv1_32("Play_VO_SCR_M99_00010_Tester"))
        self.assertTrue(e["event"]["event_id_matches_fnv1_of_name"])
        for lang in LANGS:
            m = e["media"][lang]
            self.assertEqual(m["evidence"], EXPLICIT)
            self.assertEqual(m["media"][0]["exists_evidence"], EXPLICIT_INDEX)
            self.assertIsNone(m["media"][0]["duration_s"])  # never estimated without decoding
        self.assertEqual(e["media"]["Spanish(Mexico)"]["media"][0]["media_id"], 100)
        for c in ("es-MX", "en", "es-ES"):
            self.assertEqual(e["subtitles"][c]["evidence"], EXPLICIT)
            self.assertEqual(e["subtitles"][c]["text"], f"{c}:VO_SCR_M99_00010_Tester")
        self.assertEqual(e["lipsync"]["class"], "AnimSequence")
        self.assertEqual(r["flags"], [])

    def test_missing_culture_is_unresolved_never_filled_from_another(self):
        ev = self.res.add_line("VO_SCR_M99_00020_Tester", [200], cultures=("en", "es-ES"))
        r = build_record(asset("VO_SCR_M99_00020_Tester", voice_props("VO_SCR_M99_00020_Tester", ev)), self.res, BUILD)
        sub = r["entries"][0]["subtitles"]["es-MX"]
        self.assertEqual(sub["evidence"], UNRESOLVED)
        self.assertNotIn("text", sub)
        self.assertIn("es-MX", sub["reason"])
        self.assertEqual(r["entries"][0]["subtitles"]["en"]["evidence"], EXPLICIT)

    def test_missing_language_and_missing_media_file(self):
        ev = self.res.add_line("VO_SCR_M99_00030_Tester", [300], langs=("English(US)",))
        r = build_record(asset("VO_SCR_M99_00030_Tester", voice_props("VO_SCR_M99_00030_Tester", ev)), self.res, BUILD)
        mx = r["entries"][0]["media"]["Spanish(Mexico)"]
        self.assertEqual((mx["evidence"], mx["reason"]), (UNRESOLVED, "language not in EventLanguageMap"))
        ev = self.res.add_line("VO_SCR_M99_00040_Tester", [400], in_pak=False)
        r = build_record(asset("VO_SCR_M99_00040_Tester", voice_props("VO_SCR_M99_00040_Tester", ev)), self.res, BUILD)
        mx = r["entries"][0]["media"]["Spanish(Mexico)"]
        self.assertEqual(mx["evidence"], UNRESOLVED)
        self.assertEqual(mx["media"][0]["media_id"], 400)  # the explicit ID is still recorded
        self.assertEqual(mx["media"][0]["exists_evidence"], UNRESOLVED)

    def test_no_transcription_null_lipsync_and_event_parse_error(self):
        ev = f"{EV_ROOT}/vo_scr_m99_00051_tester/Play_VO_SCR_M99_00050_Tester"
        self.res.events[ev] = ValueError("synthetic parser stop")
        r = build_record(asset("VO_SCR_M99_00051_Tester", voice_props(None, ev)), self.res, BUILD)
        e = r["entries"][0]
        self.assertEqual(r["ce_line_key_evidence"], "derived:asset_name")
        self.assertEqual(e["transcription"]["evidence"], UNRESOLVED)
        self.assertTrue(all(v["evidence"] == UNRESOLVED for v in e["subtitles"].values()))
        self.assertEqual(e["lipsync"]["evidence"], UNRESOLVED)
        self.assertEqual(e["event"]["evidence"], UNRESOLVED)
        self.assertIn("synthetic parser stop", e["event"]["reason"])
        self.assertTrue({"no_transcription", "no_lipsync", "event_package_folder_mismatch"} <= set(r["flags"]))

    def test_halo_audio_sound_shape_and_unknown_class(self):
        ev = self.res.add_line("VO_SCR_M99_00060_Tester", [600])
        props = {"PlayEvent": imp(ev), "TranscriptionLine": voice_props("VO_SCR_M99_00060_Tester", ev)
                 ["VoiceEvents"][0]["Transcription"]}
        r = build_record(asset("VO_SCR_M99_00060_Tester", props, cls="HaloAudioSound"), self.res, BUILD)
        self.assertEqual(r["entries"][0]["property"], "PlayEvent")
        self.assertEqual(r["entries"][0]["subtitles"]["es-MX"]["evidence"], EXPLICIT)
        with self.assertRaises(ValueError):
            build_record(asset("x", {}, cls="SomethingElse"), self.res, BUILD)


class AnalyzeTests(unittest.TestCase):
    def build(self):
        res = FakeResolver()
        a = res.add_line("VO_SCR_M99_00010_Tester", [100])
        res.add_line("VO_SCR_M99_00020_Tester", [200])  # key with no voice asset -> orphan
        recs = [
            build_record(asset("VO_SCR_M99_00010_Tester", voice_props("VO_SCR_M99_00010_Tester", a)), res, BUILD),
            # second asset re-using the same key and event (like the *_lipsync variants)
            build_record(asset("vo_scr_m99_00010_tester_lipsync", voice_props("VO_SCR_M99_00010_Tester", a),
                               folder="Meteorite/Content/Audio/scripted/vo_scr_m99test_lipsync"), res, BUILD),
        ]
        locres_keys = {c: {"VO_SCR_M99TEST": set(t.get("VO_SCR_M99TEST", {})) | ({"EXTRA"} if c == "en" else set())}
                       for c, t in res.locres_tables.items()}
        events = [f"Meteorite/Content{EV_ROOT[5:]}/vo_scr_m99_00010_tester/Play_VO_SCR_M99_00010_Tester.uasset",
                  f"Meteorite/Content{EV_ROOT[5:]}/vo_scr_m99_00020_tester/Play_VO_SCR_M99_00020_Tester.uasset"]
        inv = {SCR: [recs[0]["voice_asset"]["vfs_path"], f"{SCR}/broken.uasset"],
               "Meteorite/Content/Audio/scripted/vo_scr_m99test_lipsync": [recs[1]["voice_asset"]["vfs_path"]]}
        skipped = [{"vfs_path": f"{SCR}/broken.uasset", "reason": "parse error"}]
        cov, rep = analyze(recs, string_tables={TABLE: res.tables[TABLE]}, locres_keys=locres_keys,
                           event_inventory=events, voice_inventory=inv, skipped=skipped)
        return recs, cov, rep

    def test_ambiguities_orphans_and_accounting(self):
        recs, cov, rep = self.build()
        codes = {a["code"] for a in rep["ambiguities"]}
        self.assertTrue({"duplicate_ce_line_key", "duplicate_subtitle_reference", "shared_event", "shared_event_id",
                         "shared_media_id"} <= codes)
        self.assertIn("shared_event", recs[0]["ambiguities"])
        t = rep["string_tables"][0]
        self.assertEqual(t["orphaned_keys"], ["VO_SCR_M99_00020_Tester"])
        self.assertEqual(t["locres"]["en"]["locres_keys_not_in_table"], ["EXTRA"])
        self.assertEqual(len(rep["orphan_events"]), 1)
        self.assertTrue(cov["accounted_for"])
        self.assertEqual((cov["files_seen"], cov["records"], cov["skipped"]), (3, 2, 1))
        self.assertEqual(cov["media_evidence"]["Spanish(Mexico)"], {"explicit": 2})
        self.assertEqual(cov["unresolved_items"], 2)  # the two null lip-syncs

    def test_jsonl_is_deterministic_and_order_independent(self):
        recs, _, _ = self.build()
        a, b = dumps_jsonl(recs), dumps_jsonl(list(reversed(recs)))
        self.assertEqual(a, b)
        lines = a.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["record_id"], "vo_scr_m99_00010_tester")
        self.assertNotIn("built_at", a)


class CeAssetParserTests(unittest.TestCase):
    def test_string_table_tail(self):
        data = struct.pack("<i", 0) + fstr("NS") + struct.pack("<i", 2) + fstr("K1") + fstr("src one") \
            + fstr("K2") + fstr("src two")
        self.assertEqual(parse_string_table_tail(Reader(data)), ("NS", [("K1", "src one"), ("K2", "src two")]))

    def test_event_languages_masks_ids_and_copies_fields(self):
        cooked = {"EventLanguageMap": [{"key": {"LanguageName": {"name": "Spanish(Mexico)"}}, "value": {
            "EventId": -1, "Media": [{"MediaId": -2, "MediaPathName": {"name": "Media/x/1.wem"}, "bStreaming": True,
                                      "DebugName": {"name": "a.wav"}}],
            "SoundBanks": [{"SoundBankId": 5, "SoundBankPathName": {"name": "b.bnk"}, "DebugName": {"name": "B"}}]}}]}
        out = event_languages(cooked)["Spanish(Mexico)"]
        self.assertEqual(out["event_id"], 0xFFFFFFFF)
        self.assertEqual(out["media"][0], {"media_id": 0xFFFFFFFE, "media_path": "Media/x/1.wem", "streaming": True,
                                           "source_name": "a.wav"})
        self.assertEqual(out["soundbanks"][0]["bank_name"], "B")

    def test_soft_path_null(self):
        self.assertIsNone(soft_path({"soft_path": "None.None"}))
        self.assertEqual(soft_path({"soft_path": "/Game/a.a"}), "/Game/a.a")

    def test_steam_acf_top_level_only(self):
        text = '"AppState"\n{\n\t"appid"\t\t"42"\n\t"buildid"\t\t"999"\n\t"UserConfig"\n\t{\n' \
               '\t\t"buildid"\t\t"nested"\n\t}\n}\n'
        self.assertEqual(parse_steam_acf(text), {"appid": "42", "buildid": "999"})


if __name__ == "__main__":
    unittest.main()
