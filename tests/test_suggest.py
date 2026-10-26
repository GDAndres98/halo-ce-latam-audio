"""Suggestions tab (docs/suggested-matching.md): MCC English vs CE English scores, and the optional Claude re-rank.

All data is synthetic, in a temporary root. They prove, among others:
- suggestions and the re-rank never write mappings/ (the re-rank only caches its answer under work/m4/suggest/ai/);
- scores are deterministic and ties keep catalog order;
- the re-rank sends only the shortlist the server computed, drops ids it did not ask about, and is cached;
- a refusal or a missing SDK is a 503, never a guess.

Run: python -m unittest discover -s tests
"""
import json
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import suggest, suggest_ai  # noqa: E402
from m4_app import ApiError, M4App  # noqa: E402
import m4_server  # noqa: E402
from test_m3_validation import ce_record, mcc_record  # noqa: E402
from test_m4 import ce_rec, make_root, snapshot  # noqa: E402

GRUNT = "sound\\dialog\\grunt\\conditional\\combat2\\"


def suggest_root(tmp):
    """make_root, with English CE text: line_a is z10_010's line reworded, line_b is unrelated."""
    root = make_root(tmp)
    m99 = [ce_rec("line_a", "M99", "Jefe Maestro, despierte", text_en="Wake up, Master Chief!"),
           ce_rec("line_b", "M99", "Corre", text_en="Run, the reactor is going to blow", media_id=200, wem="f"),
           ce_rec("line_c", "M99", "¿Qué pasó?", text_en="What happened here?", media_id=201, wem="e")]
    m98 = [ce_rec("far_away", "M98", "Despierta", text_en="Wake up, Master Chief!", wem="1")]
    for name, rs in (("m98", m98), ("m99", m99)):
        (root / f"work/ce/catalog/{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs), encoding="utf-8")
    # Barks: an MCC generic folder with no subtitle entries, and CE Systemic records (no subtitles) for two characters.
    grunt = [dict(mcc_record(f"grunt_{i}", GRUNT + leaf, index=10 + i, data="f"), level="grunt", kind="conditional",
                  speaker_from_name=None)
             for i, leaf in enumerate(("exclamations\\surprise", "groupcomm\\retreat"))]
    (root / "work/mcc/catalog/grunt.jsonl").write_text("".join(json.dumps(r) + "\n" for r in grunt), encoding="utf-8")
    sys_recs = [dict(ce_record(name, sub_mx="unresolved", media_id=300 + i, wem="1"), mission="SYS", folder=folder,
                     display_key=name, family="systemic")
                for i, (name, folder) in enumerate((("vo_sys_default_01contact_srprs_grunt", "vo_sys_grunt"),
                                                    ("vo_sys_default_02combat_rtrt_grunt", "vo_sys_grunt"),
                                                    ("vo_sys_default_02combat_rtrt_jackal", "vo_sys_jackal")))]
    (root / "work/ce/catalog/sys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sys_recs), encoding="utf-8")
    return root


class FakeClient:
    """Stands in for anthropic.Anthropic: records each request, answers with `answer` (a dict) or a stop reason."""

    def __init__(self, answer=None, stop_reason="end_turn"):
        self.calls, self.answer, self.stop_reason = [], answer, stop_reason
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(self.answer if self.answer is not None else {"ranking": []})
        return types.SimpleNamespace(stop_reason=self.stop_reason, model=kw["model"],
                                     content=[types.SimpleNamespace(type="text", text=text)],
                                     usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))


class IndexTests(unittest.TestCase):
    def test_exact_text_scores_one_and_ties_keep_catalog_order(self):
        idx = suggest.SuggestIndex([("b#0", "Wake up, Master Chief.", "cortana"),
                                    ("a#0", "Wake up, Master Chief.", "keyes"),
                                    ("c#0", "Something else entirely", "")])
        out = idx.score("Wake up, Master Chief.", limit=3)
        self.assertEqual([x["ce_line_ref"] for x in out[:2]], ["b#0", "a#0"])  # catalog order, not name order
        self.assertEqual(out[0]["score"], 1.0)
        self.assertIn("chief", out[0]["shared_words"])
        self.assertEqual(idx.score("Wake up, Master Chief.", limit=3), out)  # deterministic

    def test_speaker_breaks_the_tie_and_empty_text_gives_nothing(self):
        idx = suggest.SuggestIndex([("b#0", "Go now", "cortana"), ("a#0", "Go now", "cryoassistant")])
        out = idx.score("Go now", speaker="cryoassist", limit=2)
        self.assertEqual(out[0]["ce_line_ref"], "a#0")
        self.assertTrue(out[0]["parts"]["same_speaker"])
        self.assertEqual(idx.score("  ...  "), [])
        self.assertEqual(idx.score("Go now", refs=["a#0"], limit=5)[0]["ce_line_ref"], "a#0")
        self.assertEqual(len(idx.score("Go now", refs=["a#0"], limit=5)), 1)

    def test_speaker_names(self):
        self.assertEqual(suggest.ce_speaker("VO_SCR_M01_00460_CryoTech"), "cryotech")
        self.assertEqual(suggest.ce_speaker("VO_SCR_M01_00460"), "")
        self.assertFalse(suggest.same_speaker("cor", "cortana"))  # too short to count as an abbreviation


def write_wav(path, samples, rate=8000):
    import array
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array("h", [max(-32767, min(32767, int(x))) for x in samples]).tobytes())


def bark(seed, n=8000, gain=1.0, pad=0):
    """A synthetic 'voice': noise bursts shaped by a seed-specific envelope, with silence padding."""
    import math
    import random
    rnd = random.Random(seed)
    env = [abs(math.sin(i / (300 + 40 * seed))) for i in range(n)]
    freq = 200 + 90 * seed
    return [0.0] * pad + [gain * 12000 * env[i] * (0.6 * math.sin(2 * math.pi * freq * i / 8000) + 0.4 * rnd.uniform(-1, 1))
                          for i in range(n)] + [0.0] * pad


class AudioMatchTests(unittest.TestCase):
    def test_same_recording_matches_whatever_the_volume_and_padding(self):
        from common import audio_match
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            write_wav(t / "a.wav", bark(1))
            write_wav(t / "a_quiet.wav", bark(1, gain=0.3, pad=800))   # -10 dB, with silence around it
            write_wav(t / "b.wav", bark(4))
            fa, fq, fb = (audio_match.features(t / f"{n}.wav") for n in ("a", "a_quiet", "b"))
        same, _lag, gain = audio_match.compare(fa, fq)
        other = audio_match.compare(fa, fb)[0]
        self.assertGreater(same, 0.9)
        self.assertAlmostEqual(gain, -10.5, delta=1.0)
        self.assertLess(other, 0.6)
        self.assertEqual(audio_match.compare(fa, {"frames": 0}), (0.0, 0, None))


class NameTests(unittest.TestCase):
    def test_abbreviations_and_synonyms_fold_to_one_word(self):
        self.assertEqual(suggest.name_tokens("01contact_srprs"), ["contact", "surprise"])
        self.assertEqual(suggest.name_tokens("08idle_doze"), suggest.name_tokens("idle_sleeping"))
        self.assertEqual(suggest.name_tokens("friend_killed_by_enemy"), ["ally", "kill", "by", "foe"])
        self.assertEqual(suggest.mcc_name_parts(GRUNT + "shouting\\taunt", "grunt"),
                         ("taunt", "conditional combat2 shouting"))
        self.assertEqual(suggest.ce_record_name("vo_sys_default_02combat_rtrt_grunt", "grunt"), "02combat_rtrt")

    def test_run_together_mcc_names_are_split_into_words(self):
        self.assertEqual(suggest.segment("hurtfriendplayer"), ["hurt", "friend", "player"])
        self.assertEqual(suggest.name_tokens("fleere"), ["flee", "response"])
        self.assertEqual(suggest.name_tokens("lostcontact"), suggest.name_tokens("05search_lst_cntct")[1:])
        self.assertEqual(suggest.segment("qwzxv"), ["qwzxv"])  # nothing to split: kept as it is

    def test_name_index_scores_within_groups(self):
        idx = suggest.NameIndex([("a#0", "01contact_srprs", "g"), ("b#0", "02combat_rtrt", "g"),
                                 ("c#0", "02combat_rtrt", "j")])
        self.assertEqual(idx.score("surprise", "exclamations")[0]["ce_line_ref"], "a#0")
        self.assertEqual([x["ce_line_ref"] for x in idx.score("retreat", groups={"j"})], ["c#0"])
        self.assertEqual(idx.score("zzz"), [])


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = suggest_root(self.tmp.name)
        self.app = M4App(self.root, today=lambda: "2026-10-23", run_validator=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_suggestions_score_english_in_the_level_scope_and_write_nothing(self):
        before = snapshot(self.root)
        r = self.app.suggestions("z10")
        self.assertEqual(r["scope"], ["M99"])  # mission_map: z10 -> M99; M98's identical line is out of scope
        by_tag = {s["tag_name"]: s for s in r["sounds"]}
        self.assertEqual(by_tag["z10_010_keyes"]["candidates"][0]["ce_line_ref"], "line_a#0")
        self.assertEqual(by_tag["z10_020_cortana"]["candidates"][0]["ce_line_ref"], "line_c#0")
        top = by_tag["z10_010_keyes"]["candidates"][0]
        self.assertEqual((top["english"], top["es_mx"], top["mission"]),
                         ("Wake up, Master Chief!", "Jefe Maestro, despierte", "M99"))
        self.assertTrue(r["read_only"])
        self.assertEqual(snapshot(self.root), before)
        everywhere = self.app.suggestions("z10", scope="all")
        self.assertIn("far_away#0", [c["ce_line_ref"] for s in everywhere["sounds"] for c in s["candidates"]])

    def test_decided_sounds_are_hidden_unless_asked_and_used_lines_are_marked(self):
        sha = self.app.slot("es:Z10_010_keyes#0")["sha256"]["mappings"]
        self.app.save({"slot_id": "es:Z10_010_keyes#0", "loaded_sha256": sha,
                       "match": {"status": "matched", "ce_line_refs": ["line_a#0"]}})
        r = self.app.suggestions("z10")
        self.assertEqual([s["tag_name"] for s in r["sounds"]], ["z10_020_cortana"])
        self.assertEqual(r["counts"]["decided"], 1)
        full = {s["tag_name"]: s for s in self.app.suggestions("z10", show="all")["sounds"]}
        self.assertTrue(full["z10_010_keyes"]["decided"])
        self.assertEqual(full["z10_010_keyes"]["candidates"][0]["used_by"], ["es:Z10_010_keyes#0"])

    def test_bad_arguments(self):
        for call, status in ((lambda: self.app.suggestions("q99"), 404), (lambda: self.app.suggestions("z10", "M42"), 404),
                             (lambda: self.app.suggestions("z10", show="best"), 400)):
            with self.assertRaises(ApiError) as cm:
                call()
            self.assertEqual(cm.exception.status, status)

    def rerank(self, client):
        self.app.ai_client = client
        return self.app.suggest_rerank({"mcc_tag": "sound\\dialog\\z10\\z10_010_keyes"})

    def test_rerank_sends_the_server_shortlist_keeps_only_asked_ids_and_caches(self):
        before = snapshot(self.root)
        client = FakeClient({"ranking": [
            {"id": "invented#0", "verdict": "same_line", "confidence": 1, "reason": "not asked"},
            {"id": "line_a#0", "verdict": "reworded", "confidence": 1.7, "reason": "same words, new punctuation"},
            {"id": "line_a#0", "verdict": "different", "confidence": 0.1, "reason": "duplicate"}]})
        out = self.rerank(client)
        self.assertEqual([(x["ce_line_ref"], x["verdict"], x["confidence"]) for x in out["ranking"]],
                         [("line_a#0", "reworded", 1.0)])
        self.assertEqual(out["ranking"][0]["es_mx"], "Jefe Maestro, despierte")
        self.assertFalse(out["cached"])
        sent = client.calls[0]
        self.assertEqual(sent["model"], suggest_ai.MODEL)
        self.assertEqual(sent["extra_body"], {"fallbacks": "default"})
        user = sent["messages"][0]["content"]
        self.assertIn("Wake up, Master Chief.", user)
        self.assertNotIn("Despierte", user)        # no Spanish text is sent
        self.assertNotIn("far_away", user)         # only the level's scope
        self.assertEqual(json.loads(user.split("\n", 1)[1])["mcc_line"]["context"][0]["english"], "What happened?")
        # Asked again: the cached answer, no second call. The only new files are the cache.
        self.assertTrue(self.rerank(client)["cached"])
        self.assertEqual(len(client.calls), 1)
        new = set(snapshot(self.root)) - set(before)
        self.assertTrue(new and all(p.startswith("work/m4/suggest/ai/") for p in new), new)
        self.assertEqual({p: b for p, b in snapshot(self.root).items() if p in before}, before)

    def test_refusal_and_bad_answers_are_503(self):
        for client in (FakeClient(stop_reason="refusal"), FakeClient(stop_reason="max_tokens")):
            with self.assertRaises(ApiError) as cm:
                self.rerank(client)
            self.assertEqual(cm.exception.status, 503)
        bad = FakeClient()
        bad.create = lambda **kw: types.SimpleNamespace(stop_reason="end_turn", model="m", usage=None,
                                                        content=[types.SimpleNamespace(type="text", text="not json")])
        bad.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=bad.create))
        with self.assertRaises(ApiError) as cm:
            self.rerank(bad)
        self.assertEqual(cm.exception.status, 503)
        self.assertFalse((self.root / suggest_ai.CACHE_DIR).exists())  # nothing cached from a failure

    def test_missing_sdk_is_503(self):
        try:
            import anthropic  # noqa: F401
            self.skipTest("the anthropic package is installed here")
        except ImportError:
            pass
        with self.assertRaises(ApiError) as cm:
            self.rerank(None)
        self.assertEqual(cm.exception.status, 503)
        self.assertIn("pip install anthropic", cm.exception.message)

    def test_barks_are_scored_by_name_in_the_characters_folder(self):
        before = snapshot(self.root)
        r = self.app.suggestions("grunt", show="all")
        self.assertEqual((r["counts"]["by_name"], r["counts"]["by_text"]), (2, 0))
        self.assertEqual(r["character"], "vo_sys_grunt")  # the folder named like the level
        by = {s["name"]: s for s in r["sounds"]}
        self.assertEqual(by["surprise"]["mode"], "name")
        self.assertEqual(by["surprise"]["candidates"][0]["name"], "01contact_srprs")
        self.assertEqual([c["folder"] for c in by["retreat"]["candidates"]], ["vo_sys_grunt"])  # not the jackal's
        every = {s["name"]: s for s in self.app.suggestions("grunt", show="all", character="all")["sounds"]}
        self.assertEqual(len(every["retreat"]["candidates"]), 2)
        self.assertEqual(snapshot(self.root), before)
        with self.assertRaises(ApiError):
            self.app.suggestions("grunt", character="vo_sys_nobody")

    def test_barks_with_an_audio_comparison_are_listed_by_sound(self):
        doc = {"schema": "audio-match/1", "level": "grunt", "ce_folder": "vo_sys_grunt", "method": "m",
               "built_at": "2026-10-23", "mcc_takes": [], "ce_variations": [], "failed": [],
               "pairs": {"10": [{"ce_line_ref": "vo_sys_default_01contact_srprs_grunt#0",
                                 "record_id": "vo_sys_default_01contact_srprs_grunt", "score": 0.97, "gain_db": -3.0,
                                 "lag_ms": 0}],
                         "11": [{"ce_line_ref": "vo_sys_default_02combat_rtrt_grunt#0",
                                 "record_id": "vo_sys_default_02combat_rtrt_grunt", "score": 0.3, "gain_db": 0.0,
                                 "lag_ms": 0}]}}
        p = self.root / "work/suggest/audio/grunt__vo_sys_grunt.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
        r = self.app.suggestions("grunt", show="all")
        self.assertEqual((r["counts"]["by_audio"], r["counts"]["by_name"]), (1, 1))  # retreat's best is too weak
        by = {s["name"]: s for s in r["sounds"]}
        surprise = by["surprise"]
        self.assertEqual(surprise["mode"], "audio")
        c = surprise["candidates"][0]
        self.assertEqual((c["name"], c["audio"]["takes_matched"], c["audio"]["takes"]), ("01contact_srprs", 1, 1))
        self.assertEqual(c["audio"]["pairs"][0]["english_index"], 10)
        self.assertEqual(c["variation_refs"], [{"ce_line_ref": "vo_sys_default_01contact_srprs_grunt#0",
                                                "en": True, "mx": True}])
        self.assertEqual(by["retreat"]["mode"], "name")
        self.assertEqual(surprise["english_takes"], [10])
        self.assertEqual(r["audio_match"]["built_at"], "2026-10-23")

    def test_a_written_review_is_attached_to_its_sounds(self):
        surprise = GRUNT + "exclamations\\surprise"
        doc = {"schema": "suggest-review/1", "level": "grunt", "ce_folder": "vo_sys_grunt", "reviewer": "Claude",
               "reviewed_at": "2026-10-23", "audio_match_built_at": None, "basis": "b", "notes": ["n"],
               "sounds": {surprise: {"assessment": "same_recordings", "summary": "s", "picks": [
                   {"ce_line_ref": "vo_sys_default_01contact_srprs_grunt#0", "record_id": "x", "verdict": "same_line",
                    "confidence": 0.9, "english_takes": [1, 7], "reason": "r"},
                   {"ce_line_ref": "gone_from_the_catalog#0", "record_id": "y", "verdict": "related",
                    "confidence": 0.1, "english_takes": None, "reason": "r"}]}}}
        p = self.root / "work/suggest/review/grunt__vo_sys_grunt.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
        before = snapshot(self.root)
        r = self.app.suggestions("grunt", show="all")
        self.assertEqual((r["review"]["reviewer"], r["review"]["stale"]), ("Claude", False))
        by = {s["name"]: s for s in r["sounds"]}
        rev = by["surprise"]["review"]
        self.assertEqual(rev["assessment"], "same_recordings")
        self.assertEqual([(x["name"], x["english_takes"]) for x in rev["picks"]], [("01contact_srprs", [10])])  # take 7: none
        self.assertIsNone(by["retreat"]["review"])
        self.assertEqual(snapshot(self.root), before)

    def test_the_owners_character_map_limits_a_level_to_its_folders(self):
        (self.root / "config").mkdir()
        (self.root / "config/suggest_characters.json").write_text(json.dumps(
            {"schema": "suggest-characters/1", "levels": {"grunt": ["vo_sys_jackal"]}}), encoding="utf-8")
        audio = self.root / "work/suggest/audio"
        audio.mkdir(parents=True)
        other = {"schema": "audio-match/1", "built_at": "2026-10-23", "method": "m", "ce_folder": "ALL", "pairs": {
            "10": [{"ce_line_ref": "vo_sys_default_01contact_srprs_grunt#0",
                    "record_id": "vo_sys_default_01contact_srprs_grunt", "score": 0.99, "gain_db": 0, "lag_ms": 0}]}}
        (audio / "grunt__ALL.json").write_text(json.dumps(other), encoding="utf-8")
        r = self.app.suggestions("grunt", show="all")
        self.assertEqual(r["character_map"], ["vo_sys_jackal"])
        self.assertEqual(r["counts"]["by_audio"], 0)  # the ALL comparison (another character) is not used
        folders = {c["folder"] for s in r["sounds"] for c in s["candidates"]}
        self.assertEqual(folders, {"vo_sys_jackal"})
        self.assertIn("--mapped", r["audio_match"]["command"])

    def test_bark_rerank_and_folder_request_send_names_only(self):
        client = FakeClient({"ranking": [{"id": "vo_sys_default_01contact_srprs_grunt#0", "verdict": "same_line",
                                          "confidence": 0.9, "reason": "surprise on contact"}]})
        self.app.ai_client = client
        out = self.app.suggest_rerank({"mcc_tag": GRUNT + "exclamations\\surprise"})
        self.assertEqual((out["mode"], out["ranking"][0]["name"]), ("name", "01contact_srprs"))
        self.assertIn("barks", client.calls[0]["system"])
        folder_client = FakeClient({"sounds": [
            {"mcc_id": "conditional/combat2/groupcomm/retreat", "picks": [
                {"id": "vo_sys_default_02combat_rtrt_grunt#0", "verdict": "same_line", "confidence": 0.8, "reason": "r"},
                {"id": "vo_sys_default_02combat_rtrt_jackal#0", "verdict": "same_line", "confidence": 0.8,
                 "reason": "not asked about"}]},
            {"mcc_id": "invented", "picks": []}]})
        self.app.ai_client = folder_client
        res = self.app.suggest_folder({"level": "grunt"})
        retreat = GRUNT + "groupcomm\\retreat"
        self.assertEqual(list(res["sounds"]), [retreat])
        self.assertEqual([p["ce_line_ref"] for p in res["sounds"][retreat]], ["vo_sys_default_02combat_rtrt_grunt#0"])
        sent = json.loads(folder_client.calls[0]["messages"][0]["content"].split("\n", 1)[1])
        self.assertEqual({r["folder"] for r in sent["ce_records"]}, {"vo_sys_grunt"})
        self.assertEqual([x["takes"] for x in sent["mcc_sounds"]], [1, 1])
        self.assertTrue(self.app.suggest_folder({"level": "grunt"})["cached"])
        self.assertEqual(len(folder_client.calls), 1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = M4App(suggest_root(self.tmp.name), today=lambda: "2026-10-23", run_validator=False)
        self.app.ai_client = FakeClient({"ranking": [{"id": "line_a#0", "verdict": "same_line", "confidence": 0.9,
                                                      "reason": "same words"}]})
        self.httpd = ThreadingHTTPServer((m4_server.HOST, 0), m4_server.make_handler(self.app, quiet=True))
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data,
                                   headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_routes(self):
        st, body = self.req("/api/suggest?level=z10&show=all")
        self.assertEqual(st, 200)
        self.assertEqual(len(body["sounds"]), 2)
        st, body = self.req("/api/suggest/rerank", {"mcc_tag": "sound\\dialog\\z10\\z10_010_keyes"})
        self.assertEqual((st, body["ranking"][0]["ce_line_ref"]), (200, "line_a#0"))
        self.assertEqual(self.req("/api/suggest/rerank", {"mcc_tag": "sound\\dialog\\z10\\nope"})[0], 404)

    def test_rerank_needs_admin_remotely_and_suggest_is_not_public(self):
        self.assertIn("/api/suggest/rerank", m4_server.ADMIN_POSTS)
        from public_view import PUBLIC_GETS
        self.assertFalse({"/api/suggest", "/api/suggest/rerank"} & set(PUBLIC_GETS))


if __name__ == "__main__":
    unittest.main()
