"""M4 tests: the matching UI's application logic, HTTP layer, on-demand audio,
mission progress, and the campaign-wide MCC catalog rules it depends on.

All data is synthetic (made-up IDs, hashes and text) in a temporary root.
They prove, among others (design §5):
- an approved object can't be changed without needs_rework;
- a stale save gets a 409;
- nothing is written outside mappings/ (and work/ audio caches);
- CE lines come back in catalog order, filtered only; nothing is pre-filled.

Run: python -m unittest discover -s tests
"""
import array
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import mapping_db, mapping_store  # noqa: E402
from common.jsonschema_lite import load_schema, validate  # noqa: E402
from common.mcc_catalog import parse_slot_id, slot_id_for  # noqa: E402
from common.mcc_loc import SPEAKER_SEP, loc_key  # noqa: E402
from common.ondemand_audio import AudioUnavailable, CeAudio, MccAudio  # noqa: E402
from common.project_validation import level_progress, validate_mission_progress  # noqa: E402
from m4_app import ApiError, M4App, fold, parse_query  # noqa: E402
import m4_server  # noqa: E402
from test_m3_validation import H, ce_record, mcc_record  # noqa: E402
from test_mcc_loc_patch import build as build_loc  # noqa: E402

T = "sound\\dialog\\z10\\"
PINS = {"ce_build": "ce-1", "mcc_steam_buildid": "9", "mcc_spanish_fsb_sha256": H["c"]}


def write_wav(path, n=800, amp=1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    a = array.array("h", [amp if i % 2 else -amp for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(a.tobytes())


def fake_decode(calls):
    def decode(src, out, subsong=None):
        calls.append((Path(src).name, subsong))
        write_wav(Path(out))
        return True, ""
    return decode


def ce_rec(rid, mission, text_mx, text_en="english", **kw):
    r = ce_record(rid, **kw)
    r["mission"] = mission
    for e in r["entries"]:
        for c, t in (("es-MX", text_mx), ("en", text_en)):
            if e["subtitles"][c].get("evidence") == "explicit":
                e["subtitles"][c] = dict(e["subtitles"][c], text=t)
    return r


def make_root(tmp):
    root = Path(tmp)
    (root / "work/mcc/catalog").mkdir(parents=True)
    (root / "work/ce/catalog").mkdir(parents=True)
    (root / "mappings").mkdir()
    recs = [mcc_record(), mcc_record("Z10_020_cortana", T + "z10_020_cortana", index=1, data="f")]
    (root / "work/mcc/catalog/z10.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    # M98 sorts before M99; inside a mission the file order is kept (never re-sorted or ranked).
    m98 = [ce_rec("zz_late", "M98", "Último en el archivo", wem="1"), ce_rec("aa_early", "M98", "Primero", wem="2"),
           ce_rec("no_text", "M98", "", wem="3", sub_mx="unresolved")]  # spoken, but no subtitle in any culture
    m99 = [ce_rec("line_a", "M99", "Jefe Maestro, despierte"), ce_rec("line_b", "M99", "Corre", media_id=200, wem="f"),
           ce_rec("lipsync_x", "M99", "x", flags=("test_event",), mx="unresolved")]
    for name, rs in (("m98", m98), ("m99", m99)):
        (root / f"work/ce/catalog/{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs), encoding="utf-8")
    (root / "work/ce/build.json").write_text(json.dumps({"source_build": {"exe_file_version": "ce-1"}}))
    (root / "work/mcc/build.json").write_text(json.dumps({"source_build": {"steam_buildid": "9"},
                                                          "files": {"spanish.fsb": {"sha256": H["c"]}}}))
    (root / "mappings/manual_mappings.json").write_bytes(mapping_db.serialize(
        {"schema": "manual-mappings/3", "pins": PINS, "slots": []}))
    keys = {loc_key(T + "z10_010_keyes"): ("Despierte, Jefe Maestro.", "Despierta, jefe maestro.",
                                           f"cor&idKEYES{SPEAKER_SEP}Wake up, Master Chief."),
            loc_key(T + "z10_020_cortana"): ("¿Qué pasó?", "¿Qué ha pasado?", "What happened?")}
    (root / "work/mcc/loc/copies").mkdir(parents=True)
    for n, name in enumerate(("SU", "SP", "EN")):
        ks = sorted(keys)
        (root / f"work/mcc/loc/copies/{name}_Halo1.bin").write_bytes(
            build_loc(ks, [keys[k][n] for k in ks], name=f"{name}_Halo1".encode()))
    (root / "mappings/verifications.json").write_text(json.dumps({"schema_version": 1, "verifications": []}))
    (root / "mappings/mission_map.json").write_text(json.dumps(
        {"schema": "mission-map/1", "entries": [{"mcc_level": "z10", "ce_missions": ["M99"],
                                                  "decided_at": "2026-10-08", "note": "test"}]}))
    mapping_store.load(root / "mappings/manual_mappings.json")  # the cutover: creates manual_mappings.db
    return root


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class AppTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        self.app = M4App(self.root, today=lambda: "2026-10-09", run_validator=False)
        self.slot = "es:Z10_010_keyes#0"

    def tearDown(self):
        self.tmp.cleanup()

    def sha(self):
        return self.app.slot(self.slot)["sha256"]["mappings"]

    def doc(self):
        return json.loads((self.root / "mappings/manual_mappings.json").read_text(encoding="utf-8"))

    def save(self, **body):
        body.setdefault("slot_id", self.slot)
        body.setdefault("loaded_sha256", self.sha())
        return self.app.save(body)

    def match_a(self):
        return self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                         audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"}]})


class ViewTests(AppTestBase):
    def test_catalog_order_and_filter_only(self):
        r = self.app.ce("all")
        self.assertEqual([x["ce_line_ref"] for x in r["lines"]],
                         ["zz_late#0", "aa_early#0", "no_text#0", "line_a#0", "line_b#0", "lipsync_x#0"])
        self.assertIn("never ranked", r["order"])
        self.assertEqual([x["ce_line_ref"] for x in self.app.ce("all", q="jefe")["lines"]], ["line_a#0"])
        # accent- and case-insensitive filter; a non-matching query returns nothing rather than "closest" lines
        self.assertEqual([x["ce_line_ref"] for x in self.app.ce("all", q="ULTIMO")["lines"]], ["zz_late#0"])
        self.assertEqual(self.app.ce("all", q="no such words")["total"], 0)
        self.assertEqual(self.app.ce("mapped", level="z10")["scope"], ["M99"])
        self.assertEqual(self.app.ce("M98")["total"], 3)
        self.assertEqual(fold("Último"), "ultimo")

    def test_new_slot_is_not_prefilled(self):
        d = self.app.slot(self.slot)
        self.assertIsNone(d["mapping"])
        self.assertTrue(d["is_new"])
        self.assertEqual(d["matched_lines"], [])
        self.assertTrue(all(s["decision"] is None for s in self.app.slots("z10")["slots"]))
        self.assertEqual(self.doc()["slots"], [])  # reading never writes

    def test_test_event_line_is_marked(self):
        line = self.app.ce_line("lipsync_x#0")
        self.assertTrue(line["test_event"])
        self.assertEqual(line["media"]["Spanish(Mexico)"]["count"], 0)

    def test_unknown_ids_are_404(self):
        for call in (lambda: self.app.slot("es:nope#0"), lambda: self.app.ce_line("nope#0"),
                     lambda: self.app.slots("q99"), lambda: self.app.ce("M42")):
            with self.assertRaises(ApiError) as cm:
                call()
            self.assertEqual(cm.exception.status, 404)


class SaveTests(AppTestBase):
    def test_draft_save_creates_mapping_and_backup(self):
        r = self.match_a()
        self.assertTrue(r["saved"])
        s = self.doc()["slots"][0]
        self.assertEqual((s["mapping_id"], s["match"]["status"], s["match"]["decided_at"]), ("m-000001", "matched", "2026-10-09"))
        self.assertEqual(s["audio"]["status"], "draft")
        self.assertEqual(s["subtitle"]["source"], "keep_original")  # never inferred from the match
        self.assertEqual(validate(self.doc(), load_schema("manual-mappings-3")), [])
        self.save(notes="second save")
        self.assertEqual(len(list((self.root / "mappings/.history").glob("manual_mappings.*.json"))), 2)

    def test_stale_save_is_409(self):
        old = self.sha()
        self.match_a()
        with self.assertRaises(ApiError) as cm:
            self.save(loaded_sha256=old, notes="late")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.doc()["slots"][0]["notes"], "")

    def test_approved_audio_is_immutable_until_needs_rework(self):
        self.match_a()
        self.save(actions=[{"action": "approve", "field": "audio"}])
        a = self.doc()["slots"][0]["audio"]
        self.assertEqual((a["status"], a["approved_at"]), ("approved", "2026-10-09"))
        self.assertEqual(a["fingerprint"]["sources"][0]["media"][0]["media_id"], 100)
        before = (self.root / "mappings/manual_mappings.json").read_bytes()
        for body in ({"audio": {"source": "keep_original", "sources": []}},
                     {"match": {"status": "no_equivalent", "ce_line_refs": []}},
                     {"actions": [{"action": "approve", "field": "audio"}]}):
            with self.assertRaises(ApiError) as cm:
                self.save(**body)
            self.assertIn(cm.exception.status, (400, 409, 422))
        self.assertEqual((self.root / "mappings/manual_mappings.json").read_bytes(), before)
        # an identical resubmission of the approved object is not a change
        self.assertFalse(self.save(audio={"source": "ce", "sources": [
            {"ce_line_ref": "line_a#0", "language": "Spanish(Mexico)"}]})["saved"])
        self.save(actions=[{"action": "needs_rework", "field": "audio"}])
        a = self.doc()["slots"][0]["audio"]
        self.assertEqual((a["status"], a["revision"], a["fingerprint"]), ("needs_rework", 2, None))
        self.save(audio={"source": "keep_original", "sources": []}, match={"status": "deferred", "ce_line_refs": []})
        self.assertEqual(self.doc()["slots"][0]["audio"]["source"], "keep_original")

    def test_approve_audio_and_subtitle_in_one_save(self):
        self.match_a()
        backups = lambda: len(list((self.root / "mappings/.history").glob("*.json")))  # noqa: E731
        before = backups()
        self.save(subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "line_a#0", "culture": "es-MX"}},
                  actions=[{"action": "approve", "field": "audio"}, {"action": "approve", "field": "subtitle"}])
        s = self.doc()["slots"][0]
        self.assertEqual((s["audio"]["status"], s["subtitle"]["status"]), ("approved", "approved"))
        self.assertTrue(s["audio"]["fingerprint"] and s["subtitle"]["fingerprint"])
        self.assertEqual(backups(), before + 1)  # one write for both approvals

    def test_audio_and_subtitle_are_independent(self):
        self.match_a()
        self.save(subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "line_a#0", "culture": "es-MX"}},
                  actions=[{"action": "approve", "field": "subtitle"}])
        s = self.doc()["slots"][0]
        self.assertEqual((s["subtitle"]["status"], s["audio"]["status"]), ("approved", "draft"))
        self.save(audio={"source": "keep_original", "sources": []})  # audio stays editable
        with self.assertRaises(ApiError):
            self.save(subtitle={"source": "keep_original"})

    def test_custom_text_lives_only_in_the_local_file(self):
        self.save(subtitle={"source": "custom", "custom_text": "Texto propio"})
        s = self.doc()["slots"][0]["subtitle"]
        self.assertEqual(s["custom_ref"], "c-000001")
        self.assertNotIn("Texto propio", (self.root / "mappings/manual_mappings.json").read_text(encoding="utf-8"))
        local = json.loads((self.root / "mappings/manual_mappings.local.json").read_text(encoding="utf-8"))
        self.assertEqual(local["custom_subtitles"]["c-000001"]["text"], "Texto propio")
        self.assertEqual(self.app.slot(self.slot)["custom_text"], "Texto propio")
        self.save(actions=[{"action": "approve", "field": "subtitle"}],
                  local_sha256=self.app.slot(self.slot)["sha256"]["local"])
        with self.assertRaises(ApiError) as cm:  # editing the text of an approved subtitle is a change too
            self.save(subtitle={"source": "custom", "custom_text": "otro"},
                      local_sha256=self.app.slot(self.slot)["sha256"]["local"])
        self.assertEqual(cm.exception.status, 409)

    def test_invalid_decisions_are_refused_before_writing(self):
        before = snapshot(self.root)
        bad = [{"match": {"status": "matched", "ce_line_refs": []}},
               {"match": {"status": "matched", "ce_line_refs": ["nope#0"]}},
               {"match": {"status": "matched", "ce_line_refs": ["lipsync_x#0"]},
                "audio": {"source": "ce", "sources": [{"ce_line_ref": "lipsync_x#0"}]}},
               {"audio": {"source": "ce", "sources": [{"ce_line_ref": "line_b#0"}]}},  # not in the match
               {"subtitle": {"source": "custom", "custom_text": "  "}},
               {"actions": [{"action": "approve", "field": "match"}]},
               {"actions": [{"action": "needs_rework", "field": "audio"}]}]
        for body in bad:
            with self.assertRaises(ApiError, msg=body):
                self.save(**body)
        self.assertEqual(snapshot(self.root), before)

    def test_writes_stay_inside_mappings(self):
        before = snapshot(self.root)
        self.match_a()
        self.save(subtitle={"source": "custom", "custom_text": "x"}, actions=[{"action": "approve", "field": "audio"}])
        changed = {k for k, v in snapshot(self.root).items() if before.get(k) != v}
        self.assertTrue(changed)
        self.assertTrue(all(k.startswith("mappings/") for k in changed), changed)

    def test_concat_order_is_kept(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_b#0", "line_a#0"]},
                  audio={"source": "ce_concat", "sources": [{"ce_line_ref": "line_b#0"}, {"ce_line_ref": "line_a#0"}]})
        self.assertEqual([x["ce_line_ref"] for x in self.doc()["slots"][0]["audio"]["sources"]],
                         ["line_b#0", "line_a#0"])


class ProgressTests(AppTestBase):
    def progress(self, **body):
        body.setdefault("loaded_sha256", self.app.state()["sha256"]["progress"])
        body.setdefault("level", "z10")
        return self.app.set_progress(body)

    def test_ready_needs_every_slot_decided_and_audio_approved(self):
        with self.assertRaises(ApiError) as cm:
            self.progress(status="ready_for_build")
        self.assertEqual(cm.exception.status, 409)
        self.progress(status="in_progress")
        for sid in ("es:Z10_010_keyes#0", "es:Z10_020_cortana#0"):
            self.slot = sid
            self.save(match={"status": "no_equivalent", "ce_line_refs": []},
                      actions=[{"action": "approve", "field": "audio"}])
        self.progress(status="ready_for_build")
        with self.assertRaises(ApiError):  # tested/reviewed need an explicit owner confirmation
            self.progress(status="reviewed")
        r = self.progress(status="reviewed", confirm=True, note="ok")
        self.assertEqual(r["entry"]["status"], "reviewed")
        doc = json.loads((self.root / "mappings/mission_progress.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(doc, load_schema("mission-progress-1")), [])
        self.assertEqual(len(doc["levels"]), 1)
        with self.assertRaises(ApiError) as cm:
            self.progress(status="in_progress", loaded_sha256="0" * 64)
        self.assertEqual(cm.exception.status, 409)

    def test_validator_flags_status_ahead_of_decisions(self):
        doc = {"schema": "mission-progress/1", "levels": [
            {"mcc_level": "z10", "status": "reviewed", "updated_at": "2026-10-09", "verification": "v-000999", "note": ""}]}
        f = validate_mission_progress(doc, load_schema("mission-progress-1"),
                                      level_slots={"z10": ["es:a#0"]}, mappings_doc={"slots": []},
                                      verifications={"verifications": []})
        self.assertEqual({x["code"] for x in f}, {"unknown_verification", "level_status_ahead_of_decisions"})
        self.assertFalse(level_progress(["es:a#0"], {"slots": []})["ready_for_build"])


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mcc_on_demand_verifies_the_pinned_copy(self):
        bank = self.root / "copies/es.fsb"
        bank.parent.mkdir()
        bank.write_bytes(b"bank")
        (self.root / "work/mcc").mkdir(parents=True)
        pin = {"copy": "copies/es.fsb", "sha256": hashlib.sha256(b"bank").hexdigest()}
        (self.root / "work/mcc/build.json").write_text(json.dumps({"files": {"spanish.fsb": pin}}))
        calls = []
        audio = MccAudio(self.root, fake_decode(calls))
        sample = {"index": 7, "subsong": 8, "data_sha256": H["a"]}
        p = audio.wav("z10", "spanish", sample)
        self.assertEqual(p, self.root / f"work/mcc/audio/ondemand/spanish/7_{H['a'][:12]}.wav")
        audio.wav("z10", "spanish", sample)
        self.assertEqual(calls, [("es.fsb", 8)])  # cached after the first decode
        bank.write_bytes(b"changed")
        with self.assertRaises(AudioUnavailable):
            MccAudio(self.root, fake_decode([])).wav("z10", "spanish", dict(sample, index=9))

    def test_mcc_reuses_eager_decode(self):
        write_wav(self.root / "work/mcc/audio/z10/spanish/z10_x__0.wav")
        (self.root / "work/mcc/audio/z10/manifest.json").write_text(json.dumps({"units": [
            {"language": "spanish", "index": 3, "status": "ok", "wav_path": "spanish/z10_x__0.wav"}]}))
        p = MccAudio(self.root, fake_decode([])).wav("z10", "spanish", {"index": 3, "data_sha256": H["a"]})
        self.assertEqual(p.name, "z10_x__0.wav")

    def test_ce_on_demand_checks_the_wem_hash(self):
        data = b"RIFF-wem"
        media = {"media_id": 55, "vfs_path": "x/55.wem", "wem_sha256": hashlib.sha256(data).hexdigest()}
        calls = []
        audio = CeAudio(self.root, fake_decode(calls), lambda lang, vfs: data)
        p = audio.wav("M02", "Spanish(Mexico)", media)
        self.assertEqual(p, self.root / "work/ce/audio/ondemand/Spanish(Mexico)/55.wav")
        self.assertEqual((self.root / "work/ce/media/Spanish(Mexico)/55.wem").read_bytes(), data)
        bad = CeAudio(self.root, fake_decode([]), lambda lang, vfs: b"other bytes")
        with self.assertRaises(AudioUnavailable):
            bad.wav("M02", "English(US)", dict(media, media_id=56))
        missing = CeAudio(self.root, fake_decode([]), lambda lang, vfs: None)
        with self.assertRaises(AudioUnavailable):
            missing.wav("M02", "English(US)", dict(media, media_id=57))


class HttpTests(unittest.TestCase):
    """The real handler on an ephemeral 127.0.0.1 port."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = make_root(self.tmp.name)
        self.app = M4App(root, today=lambda: "2026-10-09", run_validator=False)
        self.httpd = ThreadingHTTPServer((m4_server.HOST, 0), m4_server.make_handler(self.app, quiet=True))
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if body is not None else {}
        r = urllib.request.Request(self.base + path, data=data, headers={**h, **(headers or {})})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_binds_loopback_only(self):
        self.assertEqual(m4_server.HOST, "127.0.0.1")
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_page_state_and_stale_save(self):
        st, page = self.req("/")
        self.assertEqual(st, 200)
        self.assertIn(b"M4", page)
        st, body = self.req("/api/state")
        sha = json.loads(body)["sha256"]["mappings"]
        st, _ = self.req("/api/save", {"slot_id": "es:Z10_010_keyes#0", "loaded_sha256": sha, "notes": "x"})
        self.assertEqual(st, 200)
        st, body = self.req("/api/save", {"slot_id": "es:Z10_010_keyes#0", "loaded_sha256": sha, "notes": "y"})
        self.assertEqual(st, 409)
        self.assertIn("changed since", json.loads(body)["error"])

    def test_cross_origin_and_bad_requests_are_refused(self):
        self.assertEqual(self.req("/api/state", headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/save", {"slot_id": "x"}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/slot?id=es%3Anope%230")[0], 404)
        self.assertEqual(self.req("/audio/mcc?level=z10&lang=spanish&index=0")[0], 503)  # no decoder configured
        self.assertEqual(self.req("/audio/mcc?level=z10&lang=spanish&index=99")[0], 404)
        self.assertEqual(self.req("/nope")[0], 404)

    def test_server_modules_use_the_stdlib_only(self):
        import ast
        allowed = set(sys.stdlib_module_names) | {"common", "m4_app", "build_api"}
        for name in ("m4_server.py", "m4_app.py", "build_api.py"):
            tree = ast.parse((ROOT / "scripts/ui" / name).read_text(encoding="utf-8"))
            mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertLessEqual(mods, allowed, name)


class SearchTests(AppTestBase):
    def ids(self, **kw):
        return [x["slot_id"] for x in self.app.slots(kw.pop("level", "z10"), **kw)["slots"]]

    def test_query_parsing(self):
        self.assertEqual(parse_query('Jefe "las  Aguas," desp'), ["las aguas", "jefe", "desp"])
        self.assertEqual(fold("¿Qué pasó, JEFE?"), "que paso jefe")
        self.assertEqual(parse_query('"unclosed phrase'), ["unclosed", "phrase"])

    def test_mcc_search_su_sp_en_and_metadata(self):
        k, c = "es:Z10_010_keyes#0", "es:Z10_020_cortana#0"
        self.assertEqual(self.ids(q="despierte"), [k])           # SU (Latin America)
        self.assertEqual(self.ids(q="DESPIERTA"), [k])           # SP (Spain), case-insensitive
        self.assertEqual(self.ids(q="wake up master"), [k])      # EN, speaker label stripped from the text
        self.assertEqual(self.ids(q='"what happened"'), [c])     # phrase, punctuation ignored
        self.assertEqual(self.ids(q="que paso"), [c])            # accents ignored
        self.assertEqual(self.ids(q="cortan"), [c])              # partial word on the tag / speaker
        self.assertEqual(self.ids(q="nothing like this"), [])
        self.assertEqual(self.ids(level="all", q="happened"), [c])  # across levels
        self.assertEqual(self.app.slot(k)["mcc_subtitles"]["EN"]["speaker_label"], "KEYES")
        self.assertEqual(self.app.slot(k)["mcc_subtitles"]["EN"]["text"], "Wake up, Master Chief.")

    def test_ce_search_and_missing_subtitle_filter(self):
        def refs(**kw):
            return [x["ce_line_ref"] for x in self.app.ce("all", **kw)["lines"]]
        self.assertEqual(refs(q="english"), ["zz_late#0", "aa_early#0", "line_a#0", "line_b#0", "lipsync_x#0"])
        self.assertEqual(refs(q='"maestro despierte"'), ["line_a#0"])
        self.assertEqual(refs(subs="missing"), ["no_text#0"])
        self.assertEqual(refs(q="no_text"), ["no_text#0"])      # found by its identifier
        line = self.app.ce_line("no_text#0")
        self.assertEqual(line["has_source_subtitle"], {"es-MX": False, "en": False, "es-ES": False})
        self.assertEqual(line["media"]["Spanish(Mexico)"]["count"], 1)   # still playable
        self.assertNotIn("score", json.dumps(self.app.ce("all", q="primero")))

    def test_hide_lines_already_used(self):
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]})            # slot 1 uses line_a
        self.slot = "es:Z10_020_cortana#0"
        self.save(match={"status": "deferred", "ce_line_refs": ["line_b#0"]})           # slot 2 uses line_b

        def refs(**kw):
            return [x["ce_line_ref"] for x in self.app.ce("M99", **kw)["lines"]]
        self.assertEqual(refs(), ["line_a#0", "line_b#0", "lipsync_x#0"])               # off: everything
        r = self.app.ce("M99", hide_used=True)
        self.assertEqual(([x["ce_line_ref"] for x in r["lines"]], r["hidden_used"]), (["lipsync_x#0"], 2))
        # the slot being edited keeps its own lines visible
        self.assertEqual(refs(hide_used=True, keep_slot="es:Z10_020_cortana#0"), ["line_b#0", "lipsync_x#0"])
        self.assertEqual(self.app.ce("M99")["lines"][0]["used_by"], ["es:Z10_010_keyes#0"])

    def test_search_never_writes_or_selects(self):
        before = snapshot(self.root)
        self.app.slots("all", q="jefe")
        self.app.ce("all", q="jefe")
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.app.slot("es:Z10_010_keyes#0")["mapping"], None)


class MissingSubtitleTests(AppTestBase):
    def test_custom_text_for_a_line_without_source_subtitle(self):
        self.save(match={"status": "matched", "ce_line_refs": ["no_text#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "no_text#0"}]})
        catalog_before = (self.root / "work/ce/catalog/m98.jsonl").read_bytes()
        with self.assertRaises(ApiError) as cm:  # the CE text can't be approved: there is none
            self.save(subtitle={"source": "ce_locres", "ce_locres": {"ce_line_ref": "no_text#0", "culture": "es-MX"}},
                      actions=[{"action": "approve", "field": "subtitle"}])
        self.assertEqual(cm.exception.status, 422)
        # draft custom text: saved, survives a restart, still undecided
        self.save(subtitle={"source": "custom", "custom_text": "Texto propio"})
        app2 = M4App(self.root, today=lambda: "2026-10-10", run_validator=False)
        d = app2.slot(self.slot)
        self.assertEqual((d["custom_text"], d["mapping"]["subtitle"]["status"]), ("Texto propio", "draft"))
        # audio approved on its own; the subtitle stays undecided
        self.save(actions=[{"action": "approve", "field": "audio"}])
        self.assertEqual(self.doc()["slots"][0]["subtitle"]["status"], "draft")
        self.save(subtitle={"source": "custom", "custom_text": "Texto final"},
                  local_sha256=self.app.slot(self.slot)["sha256"]["local"],
                  actions=[{"action": "approve", "field": "subtitle"}])
        s = self.doc()["slots"][0]["subtitle"]
        self.assertEqual(s["status"], "approved")
        self.assertEqual(s["fingerprint"]["custom"]["text_sha256"],
                         hashlib.sha256("Texto final".encode()).hexdigest())
        self.assertEqual((self.root / "work/ce/catalog/m98.jsonl").read_bytes(), catalog_before)


class RadioEffectTests(AppTestBase):
    def test_flag_is_independent_persistent_and_filterable(self):
        self.match_a()
        self.save(actions=[{"action": "approve", "field": "audio"}])
        audio = copy.deepcopy(self.doc()["slots"][0]["audio"])
        self.save(radio_effect={"needed": True})  # allowed while the audio is approved
        s = self.doc()["slots"][0]
        self.assertEqual(s["radio_effect"], {"needed": True, "set_at": "2026-10-09", "revision": 2})
        self.assertEqual(s["audio"], audio)       # the approved object is untouched
        app2 = M4App(self.root, run_validator=False)
        self.assertEqual([x["slot_id"] for x in app2.slots("z10", status="radio")["slots"]], [self.slot])
        self.assertEqual(app2.slots("all", status="radio")["total"], 1)
        self.assertEqual(app2.state()["levels"][0]["progress"]["radio_effect"], 1)
        # needs rework keeps the flag
        self.save(actions=[{"action": "needs_rework", "field": "audio"}])
        self.assertTrue(self.doc()["slots"][0]["radio_effect"]["needed"])
        # the flag only applies to selected CE audio
        with self.assertRaises(ApiError) as cm:
            self.save(audio={"source": "keep_original", "sources": []}, match={"status": "deferred", "ce_line_refs": []})
        self.assertEqual(cm.exception.status, 422)
        self.save(audio={"source": "keep_original", "sources": []}, match={"status": "deferred", "ce_line_refs": []},
                  radio_effect={"needed": False})
        self.assertEqual(self.doc()["slots"][0]["radio_effect"]["revision"], 3)
        with self.assertRaises(ApiError):
            self.save(radio_effect={"needed": "yes"})

    def test_store_refuses_a_flag_change_without_revision(self):
        from common.mapping_store import ProtectedError, check_transition
        self.match_a()
        old = self.doc()
        new = copy.deepcopy(old)
        new["slots"][0]["radio_effect"]["needed"] = True
        with self.assertRaises(ProtectedError):
            check_transition(old, new)


class DifferentButFitsTests(AppTestBase):
    def test_flag_is_independent_persistent_and_filterable(self):
        self.match_a()
        self.save(actions=[{"action": "approve", "field": "audio"}, {"action": "approve", "field": "subtitle"}])
        approved = copy.deepcopy(self.doc()["slots"][0])
        self.save(different_but_fits={"marked": True})          # allowed while both parts are approved
        s = self.doc()["slots"][0]
        self.assertEqual(s["different_but_fits"], {"marked": True, "set_at": "2026-10-09", "revision": 2})
        self.assertEqual((s["audio"], s["subtitle"]), (approved["audio"], approved["subtitle"]))
        self.assertEqual(list(s)[-1], "notes")
        self.assertEqual(validate(self.doc(), load_schema("manual-mappings-3")), [])
        app2 = M4App(self.root, run_validator=False)
        self.assertEqual([x["slot_id"] for x in app2.slots("z10", status="fits")["slots"]], [self.slot])
        self.assertTrue(app2.slots("z10")["slots"][0]["different_but_fits"])
        self.assertEqual(app2.state()["levels"][0]["progress"]["different_but_fits"], 1)
        self.save(actions=[{"action": "needs_rework", "field": "audio"}])   # rework keeps the flag
        self.assertTrue(self.doc()["slots"][0]["different_but_fits"]["marked"])
        self.save(different_but_fits={"marked": False})
        self.assertEqual(self.doc()["slots"][0]["different_but_fits"]["revision"], 3)
        with self.assertRaises(ApiError):
            self.save(different_but_fits={"marked": 1})

    def test_needs_a_matched_line(self):
        with self.assertRaises(ApiError) as cm:
            self.save(match={"status": "no_equivalent", "ce_line_refs": []}, different_but_fits={"marked": True})
        self.assertEqual(cm.exception.status, 422)

    def test_optional_for_slots_saved_before_the_flag_existed(self):
        self.match_a()
        doc = self.doc()
        del doc["slots"][0]["different_but_fits"]                 # as written by the previous app version
        # Simulates a file written by an older app version: no database existed then, so drop it
        # (the Studio refuses a JSON edited behind the database's back).
        (self.root / "mappings/manual_mappings.db").unlink()
        (self.root / "mappings/manual_mappings.json").write_bytes(mapping_db.serialize(doc))
        self.assertEqual(validate(doc, load_schema("manual-mappings-3")), [])
        self.assertFalse(self.app.slots("z10")["slots"][0]["different_but_fits"])
        self.save(notes="unrelated edit")                         # an edit without the flag doesn't add it
        self.assertNotIn("different_but_fits", self.doc()["slots"][0])
        self.save(different_but_fits={"marked": True})
        self.assertEqual(self.doc()["slots"][0]["different_but_fits"]["revision"], 1)


class MigrationTests(unittest.TestCase):
    def test_v2_to_v3_moves_the_flag_and_keeps_approvals(self):
        from common import mapping_store
        from test_m3_validation import slot as m3_slot
        s2 = copy.deepcopy(m3_slot(audio__status="approved", audio__approved_at="2026-10-08",
                                   audio__fingerprint={"x": 1}))
        del s2["radio_effect"]
        s2["audio"]["fx_request"] = "radio"
        v2 = {"schema": "manual-mappings/2", "pins": PINS, "slots": [s2]}
        self.assertEqual(validate(v2, load_schema("manual-mappings-2")), [])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manual_mappings.json"
            p.write_text(json.dumps(v2), encoding="utf-8")
            _doc, sha = mapping_store.load(p)
            mapping_store.migrate(p, sha, history_dir=Path(d) / "h")
            v3 = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(v3["schema"], "manual-mappings/3")
            self.assertTrue(v3["slots"][0]["radio_effect"]["needed"])
            self.assertNotIn("fx_request", v3["slots"][0]["audio"])
            self.assertEqual(v3["slots"][0]["audio"]["status"], "approved")
            self.assertEqual(validate(v3, load_schema("manual-mappings-3")), [])
            self.assertEqual(len(list((Path(d) / "h").iterdir())), 1)
            with self.assertRaises(mapping_store.StoreError):  # a normal save may not change the version
                mapping_store.save(p, v2, mapping_store.load(p)[1], schema=load_schema("manual-mappings-2"))
        self.assertEqual(mapping_store.migrate_doc(v3), (v3, False))


class CampaignCatalogRuleTests(unittest.TestCase):
    def test_slot_id_encoding_keeps_plain_names(self):
        self.assertEqual(slot_id_for("A10_010_cryotech", 0), "es:A10_010_cryotech#0")
        self.assertEqual(slot_id_for("deathquiet 01", 2), "es:deathquiet%2001#2")
        self.assertEqual(slot_id_for("a#b%c", 0), "es:a%23b%25c#0")
        pattern = load_schema("manual-mappings-3")["$defs"]["slot_id"]["pattern"]
        import re
        self.assertTrue(re.match(pattern, slot_id_for("x\ty z", 1)))

    def test_slot_id_round_trip(self):
        import random
        rnd = random.Random(7)
        alphabet = "aZ_09 .-%#\t()'ñé"
        for _ in range(2000):
            name = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 12)))
            occ = rnd.randint(0, 40)
            sid = slot_id_for(name, occ)
            self.assertEqual(parse_slot_id(sid), (name, occ), sid)
            self.assertNotRegex(sid[3:].rsplit("#", 1)[0], r"[#\s]")
        for bad in ("A10_x#0", "es:a%2#0", "es:a%zz#0", "es:a#x"):
            with self.assertRaises(ValueError):
                parse_slot_id(bad)


if __name__ == "__main__":
    unittest.main()
