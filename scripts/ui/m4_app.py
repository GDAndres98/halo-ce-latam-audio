"""M4: local manual matching UI, application logic (no HTTP here; see m4_server.py).

Design: docs/m4-matching-ui-design.md. What this module guarantees:

- **No suggestions.** CE lines are listed in catalog order (mission, then
  catalog file order, then entry index). A search is a filter the owner
  types; nothing is scored, ranked or pre-filled.
- **Reads** the generated catalogs under work/ (every MCC level and CE
  mission found), the MCC SU/SP subtitle copies, and the user files in
  mappings/. verifications.json and mission_map.json are read-only here.
- **Writes** only three user files, each with a stale-hash refusal, a
  .history/ backup and an atomic write:
  - mappings/manual_mappings.json, only via mapping_store.save with the
    owner's UserActions (tools never approve; approved objects change only
    through needs_rework, revision + 1);
  - mappings/manual_mappings.local.json (custom subtitle text, git-ignored);
  - mappings/mission_progress.json (owner-set level status).
- Audio is decoded on demand into work/ (common/ondemand_audio.py).
- After every save the read-only project validator runs in-process.
"""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import re
import sys
import threading
import unicodedata
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.jsonschema_lite import load_schema  # noqa: E402
from common.mapping_store import (  # noqa: E402
    EMPTY_SHA256, SCHEMA_ID, SCHEMA_NAME, ProtectedError, StaleError, StoreError, UserAction, check_transition,
    save as save_mappings, save_user_file)
from common.mcc_loc import loc_key, parse_mcc_loc, split_speaker  # noqa: E402
from common.ondemand_audio import AudioUnavailable  # noqa: E402
from common.project_validation import (  # noqa: E402
    READY_STATUSES, audio_fingerprint, build_ce_index, build_mcc_index, level_progress, subtitle_fingerprint,
    validate_mappings)

MAPPINGS = "mappings/manual_mappings.json"
LOCAL = "mappings/manual_mappings.local.json"
VERIFICATIONS = "mappings/verifications.json"
MISSION_MAP = "mappings/mission_map.json"
PROGRESS = "mappings/mission_progress.json"
LOC_TABLES = {"SU": "work/mcc/loc/copies/SU_Halo1.bin", "SP": "work/mcc/loc/copies/SP_Halo1.bin",
              "EN": "work/mcc/loc/copies/EN_Halo1.bin"}  # SU = Latin America, SP = Spain, EN = English
MCC_LANGS = ("spanish", "english")
CE_LANGS = ("Spanish(Mexico)", "English(US)", "Spanish(Spain)")
CULTURES = ("es-MX", "en", "es-ES")
MATCH_STATUSES = ("unreviewed", "matched", "no_equivalent", "deferred")
PROGRESS_STATUSES = ("in_progress", "ready_for_build", "in_game_tested", "reviewed")
SUBTITLE_KEY_EVIDENCE = "derived:mcc_loc_key_crc32_tag_path"


class ApiError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details or []


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def fold(text):
    """Search form: case-, accent- and punctuation-insensitive. Letters and digits are kept (accents
    removed, lower-cased); every other run of characters becomes one space. m4.html's highlighter
    mirrors this exactly."""
    out, space = [], True
    for ch in text or "":
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).casefold()
        if base and all(c.isalnum() for c in base):
            out.append(base)
            space = False
        elif not space:
            out.append(" ")
            space = True
    return "".join(out).strip()


def parse_query(q):
    """'jefe "las aguas" desp' -> ['jefe', 'las aguas', 'desp']: words and quoted phrases, all folded.
    Each term must appear somewhere (partial words allowed). A filter only; nothing is scored."""
    terms, rest = [], q or ""
    for phrase in re.findall(r'"([^"]*)"', rest):
        f = fold(phrase)
        if f:
            terms.append(f)
    rest = re.sub(r'"[^"]*"', " ", rest)  # an unclosed quote (still typing) keeps its words as plain terms
    terms += fold(rest).split()
    return terms


def matches(query_terms, haystack):
    hay = f" {haystack} "
    return all(t in hay for t in query_terms)


def level_sort_key(level):
    if re.fullmatch(r"[a-d]\d\d", level):
        return (0, level)
    if re.fullmatch(r"x\d\d", level):
        return (1, level)
    return (2, level)


def _read_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def default_slot(mapping_id, slot_id, mcc_tag):
    """A new, undecided mapping: Spain audio and MCC subtitle stay (v1.0 default for unmatched lines)."""
    return {"mapping_id": mapping_id, "slot_id": slot_id, "mcc_tag": mcc_tag,
            "match": {"status": "unreviewed", "ce_line_refs": [], "decided_at": None, "revision": 1},
            "audio": {"status": "draft", "source": "keep_original", "sources": [],
                      "edit": {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0},
                      "fingerprint": None, "approved_at": None, "revision": 1},
            "subtitle": {"status": "draft", "source": "keep_original", "ce_locres": None, "custom_ref": None,
                         "mcc_key_hash": None, "mcc_key_verification": None, "fingerprint": None,
                         "approved_at": None, "revision": 1},
            "radio_effect": {"needed": False, "set_at": None, "revision": 1},
            "notes": ""}


def _next_id(prefix, used):
    n = max([int(u.split("-")[1]) for u in used if u and u.startswith(prefix + "-")] or [0])
    return f"{prefix}-{n + 1:06d}"


def _audio_sem(a):
    return (a["source"], a["sources"], a["edit"])


def _subtitle_sem(s):
    return (s["source"], s["ce_locres"], s["custom_ref"])


class M4App:
    def __init__(self, root, *, mcc_audio=None, ce_audio=None, today=None, run_validator=True):
        self.root = Path(root)
        self.mcc_audio, self.ce_audio = mcc_audio, ce_audio
        self.today = today or (lambda: dt.date.today().isoformat())
        self.run_validator = run_validator
        self._save_lock = threading.Lock()
        self.last_validation = None
        self.reload()

    # ------------------------------------------------------------------ loading
    def reload(self):
        self.levels, self.slot_index = {}, {}
        cat = self.root / "work" / "mcc" / "catalog"
        for p in sorted(cat.glob("*.jsonl"), key=lambda p: level_sort_key(p.stem)) if cat.is_dir() else []:
            recs = _read_jsonl(p)
            self.levels[p.stem] = recs
            for r in recs:
                for s in r["samples"]["spanish"]:
                    self.slot_index[s["slot_id"]] = (p.stem, r, s)
        self.missions, self.ce_lines, self.ce_order = {}, {}, []
        cat = self.root / "work" / "ce" / "catalog"
        for p in sorted(cat.glob("*.jsonl")) if cat.is_dir() else []:
            recs = _read_jsonl(p)
            mission = p.stem.upper()
            self.missions[mission] = recs
            for r in recs:
                for e in r["entries"]:
                    self.ce_lines[e["ce_line_ref"]] = (mission, r, e)
                    self.ce_order.append(e["ce_line_ref"])
        all_mcc = [r for recs in self.levels.values() for r in recs]
        self.ce_idx = build_ce_index([r for recs in self.missions.values() for r in recs])
        self.mcc_idx = build_mcc_index(all_mcc)
        self.loc = {}
        for name, rel in LOC_TABLES.items():
            p = self.root / rel
            self.loc[name] = parse_mcc_loc(p.read_bytes())["entries"] if p.is_file() else None
        self._mcc_hay = {}
        for lv, recs in self.levels.items():
            for r in recs:
                texts = self._mcc_text(r["mcc_tag"])
                base = " ".join([lv, r["mcc_tag"], r["speaker_from_name"] or "", r["kind"]] +
                                [v["text"] or "" for v in texts.values()] +
                                [v["speaker_label"] or "" for v in texts.values()])
                for smp in r["samples"]["spanish"]:
                    self._mcc_hay[smp["slot_id"]] = fold(smp["slot_id"] + " " + smp["name_in_bank"] + " " + base)
        self._ce_hay = {ref: fold(" ".join([ref, r["display_key"], r.get("folder", "")] +
                                           [(e["subtitles"].get(c) or {}).get("text") or "" for c in CULTURES]))
                        for ref, (_m, r, e) in self.ce_lines.items()}

    def _read_user(self, rel, default=None):
        p = self.root / rel
        if not p.is_file():
            return copy.deepcopy(default), EMPTY_SHA256
        data = p.read_bytes()
        return json.loads(data.decode("utf-8")), _sha(data)

    def _mappings(self):
        doc, sha = self._read_user(MAPPINGS)
        if doc is None:
            raise ApiError(500, f"{MAPPINGS} is missing; create it from the template (design §5.1)")
        if doc.get("schema") != SCHEMA_ID:
            raise ApiError(409, f"{MAPPINGS} is {doc.get('schema')}; run python scripts/validate/migrate_mappings.py "
                                "--write first")
        return doc, sha

    def _local(self):
        return self._read_user(LOCAL, {"schema": "manual-mappings-local/1", "custom_subtitles": {},
                                       "user_recordings": {}})

    def _progress(self):
        return self._read_user(PROGRESS, {"schema": "mission-progress/1", "levels": []})

    def _verifications(self):
        return self._read_user(VERIFICATIONS, {"verifications": []})[0]

    def _mission_scope(self, level):
        doc = self._read_user(MISSION_MAP, {"entries": []})[0]
        for e in doc.get("entries", []):
            if e["mcc_level"] == level:
                return e["ce_missions"]
        return []

    def _current_pins(self):
        ce = self._read_user("work/ce/build.json", {})[0] or {}
        mcc = self._read_user("work/mcc/build.json", {})[0] or {}
        return {"ce_build": (ce.get("source_build") or {}).get("exe_file_version"),
                "mcc_steam_buildid": (mcc.get("source_build") or {}).get("steam_buildid"),
                "mcc_spanish_fsb_sha256": ((mcc.get("files") or {}).get("spanish.fsb") or {}).get("sha256")}

    # ------------------------------------------------------------------ views
    def state(self):
        mappings, msha = self._mappings()
        progress, psha = self._progress()
        status = {e["mcc_level"]: e for e in progress["levels"]}
        levels = []
        for lv, recs in self.levels.items():
            sids = [sid for r in recs for sid in r["slot_ids"]]
            levels.append({"level": lv, "group": ["campaign", "cutscene", "generic"][level_sort_key(lv)[0]],
                           "tags": len(recs), "slots": len(sids), "progress": level_progress(sids, mappings),
                           "status": status.get(lv), "ce_missions": self._mission_scope(lv)})
        missions = []
        for m, recs in self.missions.items():
            entries = [e for r in recs for e in r["entries"]]
            missions.append({"mission": m, "records": len(recs), "lines": len(entries),
                             "lines_with_es_mx_audio": sum(
                                 1 for e in entries
                                 if (e["media"].get("Spanish(Mexico)") or {}).get("evidence") == "explicit")})
        return {"levels": levels, "missions": missions, "pins": mappings["pins"], "current_pins": self._current_pins(),
                "sha256": {"mappings": msha, "local": self._local()[1], "progress": psha},
                "validation": self.last_validation}

    def _decision_summary(self, m):
        if not m:
            return None
        return {"match": m["match"]["status"], "audio": m["audio"]["status"], "subtitle": m["subtitle"]["status"],
                "audio_source": m["audio"]["source"], "subtitle_source": m["subtitle"]["source"]}

    def _mcc_text(self, mcc_tag):
        key = loc_key(mcc_tag)
        out = {}
        for t, tbl in self.loc.items():
            raw = None if tbl is None else tbl.get(key)
            sp = split_speaker(raw) if raw else None  # EN carries a speaker label; shown apart, never edited
            out[t] = {"key": key, "text": sp[2] if sp else raw, "speaker_label": sp[1] if sp else None,
                      "table_loaded": tbl is not None, "evidence": SUBTITLE_KEY_EVIDENCE}
        return out

    def _slot_filter(self, status, m, s):
        st = m["match"]["status"] if m else "unreviewed"
        a = m["audio"]["status"] if m else "draft"
        sub = m["subtitle"]["status"] if m else "draft"
        return {None: True, "": True, "undecided": st == "unreviewed",
                "matched": st == "matched", "no_equivalent": st == "no_equivalent", "deferred": st == "deferred",
                "needs_rework": "needs_rework" in (a, sub), "audio_pending": a != "approved",
                "subtitle_pending": sub != "approved",
                "radio": bool(m and m["radio_effect"]["needed"]), "stereo": s["channels"] > 1}.get(status, False)

    def slots(self, level, status=None, q=None, limit=1500):
        """level may be 'all' (search every level). Catalog order; the query and status only filter."""
        if level != "all" and level not in self.levels:
            raise ApiError(404, f"unknown level {level}")
        mappings, msha = self._mappings()
        by_slot = {s["slot_id"]: s for s in mappings["slots"]}
        terms = parse_query(q)
        out, total = [], 0
        for lv in (self.levels if level == "all" else [level]):
            for r in self.levels[lv]:
                en = r["samples"]["english"]
                for s in r["samples"]["spanish"]:
                    m = by_slot.get(s["slot_id"])
                    if not self._slot_filter(status, m, s):
                        continue
                    if terms and not matches(terms, self._mcc_hay[s["slot_id"]]):
                        continue
                    total += 1
                    if len(out) >= limit:
                        continue
                    k = s["ordinal_in_tag"]
                    out.append({"slot_id": s["slot_id"], "level": lv, "mcc_tag": r["mcc_tag"],
                                "tag_name": r["tag_name"], "kind": r["kind"],
                                "speaker_from_name": r["speaker_from_name"], "ordinal": k,
                                "permutations": len(r["samples"]["spanish"]), "duration_s": s["duration_s"],
                                "en_duration_s": en[k]["duration_s"] if k < len(en) else None,
                                "channels": s["channels"], "flags": r["flags"],
                                "decision": self._decision_summary(m),
                                "radio_effect": bool(m and m["radio_effect"]["needed"])})
                    if terms:  # lets the page show and highlight what matched
                        out[-1]["texts"] = {t: v["text"] for t, v in self._mcc_text(r["mcc_tag"]).items()}
        prog = None
        if level != "all":
            prog = level_progress([sid for r in self.levels[level] for sid in r["slot_ids"]], mappings)
        return {"level": level, "slots": out, "total": total, "truncated": total > len(out),
                "progress": prog, "sha256": msha, "terms": terms}

    def _verifs_for(self, subject):
        return [v for v in self._verifications().get("verifications", []) if v.get("subject") == subject]

    def _wav_duration(self, path):
        try:
            with wave.open(str(path), "rb") as w:
                return round(w.getnframes() / w.getframerate(), 3)
        except (OSError, wave.Error, EOFError, ZeroDivisionError):
            return None

    def ce_line(self, ref, with_verifications=True):
        if ref not in self.ce_lines:
            raise ApiError(404, f"unknown CE line {ref}")
        mission, r, e = self.ce_lines[ref]
        media = {}
        for lang in CE_LANGS:
            m = e["media"].get(lang) or {}
            items = m.get("media", []) if m.get("evidence") == "explicit" else []
            dur = None
            if items and self.ce_audio:
                hit = self.ce_audio.cached(mission, lang, items[0])
                dur = self._wav_duration(hit) if hit else None
            media[lang] = {"evidence": m.get("evidence"), "reason": m.get("reason"), "count": len(items),
                           "duration_s": dur}
        subs = {c: {"text": (e["subtitles"].get(c) or {}).get("text"),
                    "evidence": (e["subtitles"].get(c) or {}).get("evidence"),
                    "reason": (e["subtitles"].get(c) or {}).get("reason")} for c in CULTURES}
        out = {"ce_line_ref": ref, "mission": mission, "record_id": r["record_id"], "display_key": r["display_key"],
               "family": r["family"], "folder": r.get("folder"), "entry_index": e["index"],
               "entries_in_record": len(r["entries"]), "flags": r["flags"], "test_event": "test_event" in r["flags"],
               "media": media, "subtitles": subs,
               "has_source_subtitle": {c: bool(subs[c]["text"]) for c in CULTURES}}
        if with_verifications:
            out["verifications"] = [v["id"] for v in self._verifs_for(f"ce:{ref}")]
        return out

    def ce(self, mission="all", q=None, offset=0, limit=100, level=None, subs=None, hide_used=False,
           keep_slot=None):
        """CE lines in catalog order, filtered only by the owner's scope, query and subtitle filter
        (subs: 'missing' = no es-MX subtitle text, 'present' = has one). hide_used drops lines already
        listed in some slot's match, except those of keep_slot (the slot being edited)."""
        if mission == "mapped":
            scope = set(self._mission_scope(level)) if level else set()
        elif mission in (None, "", "all"):
            scope = set(self.missions)
        elif mission.upper() in self.missions:
            scope = {mission.upper()}
        else:
            raise ApiError(404, f"unknown mission {mission}")
        terms = parse_query(q)
        if subs not in (None, "", "missing", "present"):
            raise ApiError(400, f"unknown subtitle filter {subs!r}")

        def has_mx(ref):
            return bool((self.ce_lines[ref][2]["subtitles"].get("es-MX") or {}).get("text"))
        used = {}
        for m in self._mappings()[0]["slots"]:
            for ref in m["match"]["ce_line_refs"]:
                used.setdefault(ref, []).append(m["slot_id"])
        hidden = {ref for ref, sids in used.items() if any(x != keep_slot for x in sids)} if hide_used else set()
        hidden -= {ref for ref, sids in used.items() if keep_slot in sids}
        refs = [ref for ref in self.ce_order if self.ce_lines[ref][0] in scope
                and (not terms or matches(terms, self._ce_hay[ref]))
                and (not subs or has_mx(ref) == (subs == "present"))]
        n_hidden = sum(1 for ref in refs if ref in hidden)
        refs = [ref for ref in refs if ref not in hidden]
        offset, limit = max(0, int(offset)), max(1, min(500, int(limit)))
        verifs = {}
        for v in self._verifications().get("verifications", []):
            if v.get("subject", "").startswith("ce:"):
                verifs.setdefault(v["subject"][3:], []).append(v["id"])
        lines = []
        for ref in refs[offset:offset + limit]:
            line = self.ce_line(ref, with_verifications=False)
            line["verifications"] = verifs.get(ref, [])
            line["used_by"] = used.get(ref, [])
            lines.append(line)
        return {"scope": sorted(scope), "total": len(refs), "offset": offset, "limit": limit, "lines": lines,
                "terms": terms, "hidden_used": n_hidden,
                "order": "catalog order (mission, catalog file, entry index); filter only, never ranked"}

    def slot(self, slot_id):
        if slot_id not in self.slot_index:
            raise ApiError(404, f"unknown slot {slot_id}")
        level, r, s = self.slot_index[slot_id]
        mappings, msha = self._mappings()
        local, lsha = self._local()
        m = next((x for x in mappings["slots"] if x["slot_id"] == slot_id), None)
        drift = {}
        if m:
            for f, fn in (("audio", audio_fingerprint), ("subtitle", subtitle_fingerprint)):
                if m[f]["status"] == "approved":
                    drift[f] = m[f]["fingerprint"] != fn(m, self.ce_idx, self.mcc_idx, local)
        custom = None
        if m and m["subtitle"]["custom_ref"]:
            custom = (local["custom_subtitles"].get(m["subtitle"]["custom_ref"]) or {}).get("text")
        refs = m["match"]["ce_line_refs"] if m else []
        sample = {k: s.get(k) for k in ("index", "subsong", "name_in_bank", "name_occurrence_in_bank",
                                         "ordinal_in_tag", "duration_s", "channels", "freq", "codec", "evidence")}
        return {"slot_id": slot_id, "level": level, "mcc_tag": r["mcc_tag"], "tag_name": r["tag_name"],
                "kind": r["kind"], "sequence": r["sequence"], "speaker_from_name": r["speaker_from_name"],
                "flags": r["flags"], "spanish": sample,
                "english": [{k: e.get(k) for k in ("index", "subsong", "name_in_bank", "ordinal_in_tag",
                                                    "duration_s", "channels", "evidence")}
                            for e in r["samples"]["english"]],
                "mcc_subtitles": self._mcc_text(r["mcc_tag"]),
                "mapping": m, "is_new": m is None, "custom_text": custom,
                "matched_lines": [self.ce_line(x) for x in refs if x in self.ce_lines],
                "unknown_refs": [x for x in refs if x not in self.ce_lines],
                "verifications": self._verifs_for(f"mcc:{slot_id}"), "fingerprint_drift": drift,
                "ce_missions": self._mission_scope(level), "sha256": {"mappings": msha, "local": lsha}}

    # ------------------------------------------------------------------ audio
    def mcc_wav(self, level, lang, index):
        if lang not in MCC_LANGS or level not in self.levels:
            raise ApiError(404, "unknown level or language")
        index = int(index)
        for r in self.levels[level]:
            for s in r["samples"][lang]:
                if s["index"] == index:
                    if not self.mcc_audio:
                        raise ApiError(503, "MCC audio decoding is not configured")
                    try:
                        return self.mcc_audio.wav(level, lang, s)
                    except AudioUnavailable as e:
                        raise ApiError(503, str(e))
        raise ApiError(404, f"{lang} sample {index} is not in level {level}")

    def ce_wav(self, ref, lang, k=0):
        if ref not in self.ce_lines or lang not in CE_LANGS:
            raise ApiError(404, "unknown CE line or language")
        mission, _r, e = self.ce_lines[ref]
        m = e["media"].get(lang) or {}
        items = m.get("media", []) if m.get("evidence") == "explicit" else []
        k = int(k)
        if not 0 <= k < len(items):
            raise ApiError(404, f"{ref} has no resolved {lang} media #{k}")
        if not self.ce_audio:
            raise ApiError(503, "CE audio decoding is not configured")
        try:
            return self.ce_audio.wav(mission, lang, items[k])
        except AudioUnavailable as e:
            raise ApiError(503, str(e))

    # ------------------------------------------------------------------ save
    def _normalize_audio(self, a, refs):
        source = a.get("source")
        if source not in ("keep_original", "ce", "ce_concat"):
            raise ApiError(400, f"audio source {source!r} is not supported by the UI")
        sources = []
        for x in a.get("sources") or []:
            ref, lang = x.get("ce_line_ref"), x.get("language", "Spanish(Mexico)")
            if ref not in self.ce_lines:
                raise ApiError(400, f"unknown CE line {ref}")
            if lang not in CE_LANGS:
                raise ApiError(400, f"unknown language {lang}")
            sources.append({"kind": "ce", "ce_line_ref": ref, "language": lang})
        return source, sources

    def save(self, body):
        """body: {loaded_sha256, slot_id, match?, audio?, subtitle?, notes?, actions?: [{action, field}],
        local_sha256?}. Returns the new state of the slot plus validator findings."""
        with self._save_lock:
            return self._save(body)

    def _save(self, body):
        slot_id = body.get("slot_id")
        if slot_id not in self.slot_index:
            raise ApiError(404, f"unknown slot {slot_id}")
        level, rec, _s = self.slot_index[slot_id]
        doc, sha = self._mappings()
        if body.get("loaded_sha256") != sha:
            raise ApiError(409, "manual_mappings.json changed since this page loaded it; reload and re-apply")
        local, lsha = self._local()
        if body.get("local_sha256", lsha) != lsha:
            raise ApiError(409, "manual_mappings.local.json changed since this page loaded it; reload")
        new_doc = copy.deepcopy(doc)
        idx = next((i for i, x in enumerate(new_doc["slots"]) if x["slot_id"] == slot_id), None)
        if idx is None:
            slot = default_slot(_next_id("m", [x["mapping_id"] for x in doc["slots"]]), slot_id, rec["mcc_tag"])
        else:
            slot = new_doc["slots"][idx]
        mid, today = slot["mapping_id"], self.today()
        actions = body.get("actions") or []
        user_actions = []
        for a in actions:
            if a.get("action") not in ("approve", "needs_rework") or a.get("field") not in ("audio", "subtitle"):
                raise ApiError(400, f"unknown action {a}")
            user_actions.append(UserAction(a["action"], mid, a["field"]))
        rework = {a.field for a in user_actions if a.action == "needs_rework"}
        approve = {a.field for a in user_actions if a.action == "approve"}
        if rework & approve:
            raise ApiError(400, "approve and needs_rework on the same field in one save")

        for f in sorted(rework):
            obj = slot[f]
            if obj["status"] != "approved":
                raise ApiError(400, f"{f} is not approved; nothing to rework")
            obj.update(status="needs_rework", revision=obj["revision"] + 1, approved_at=None, fingerprint=None)

        if "match" in body:
            m = body["match"]
            status, refs = m.get("status"), list(m.get("ce_line_refs") or [])
            if status not in MATCH_STATUSES:
                raise ApiError(400, f"unknown match status {status!r}")
            unknown = [x for x in refs if x not in self.ce_lines]
            if unknown:
                raise ApiError(400, f"unknown CE line(s) {unknown}")
            if len(set(refs)) != len(refs):
                raise ApiError(400, "a CE line is listed twice")
            cur = slot["match"]
            if (status, refs) != (cur["status"], cur["ce_line_refs"]):
                if cur["decided_at"] is not None:
                    cur["revision"] += 1
                cur.update(status=status, ce_line_refs=refs, decided_at=None if status == "unreviewed" else today)

        def guard(field, changed):
            if changed and slot[field]["status"] == "approved":
                raise ApiError(409, f"{field} is approved and read-only; choose 'needs rework' first")

        if "audio" in body:
            source, sources = self._normalize_audio(body["audio"], slot["match"]["ce_line_refs"])
            want = dict(slot["audio"], source=source, sources=sources)
            changed = _audio_sem(want) != _audio_sem(slot["audio"])
            guard("audio", changed)
            if changed:
                slot["audio"] = want

        new_local, local_changed = copy.deepcopy(local), False
        if "subtitle" in body:
            sb = body["subtitle"]
            source = sb.get("source")
            if source not in ("keep_original", "ce_locres", "custom", "none"):
                raise ApiError(400, f"unknown subtitle source {source!r}")
            ce_locres, custom_ref = None, None
            if source == "ce_locres":
                c = sb.get("ce_locres") or {}
                if c.get("ce_line_ref") not in self.ce_lines or c.get("culture") not in CULTURES:
                    raise ApiError(400, "subtitle ce_locres needs a known CE line and culture")
                ce_locres = {"ce_line_ref": c["ce_line_ref"], "culture": c["culture"]}
            if source == "custom":
                text = (sb.get("custom_text") or "").strip()
                if not text:
                    raise ApiError(400, "custom subtitle text is empty")
                custom_ref = slot["subtitle"]["custom_ref"]
                if not custom_ref:
                    used = list(local["custom_subtitles"]) + [x["subtitle"]["custom_ref"] for x in doc["slots"]]
                    custom_ref = _next_id("c", used)
                old_text = (local["custom_subtitles"].get(custom_ref) or {}).get("text")
                if old_text != text:
                    guard("subtitle", True)
                    new_local["custom_subtitles"][custom_ref] = {"text": text, "updated_at": today}
                    local_changed = True
            want = dict(slot["subtitle"], source=source, ce_locres=ce_locres, custom_ref=custom_ref)
            changed = _subtitle_sem(want) != _subtitle_sem(slot["subtitle"])
            guard("subtitle", changed)
            if changed:
                slot["subtitle"] = want

        if "radio_effect" in body:  # independent of approvals: never touches the audio/subtitle objects
            needed = (body["radio_effect"] or {}).get("needed")
            if not isinstance(needed, bool):
                raise ApiError(400, "radio_effect.needed must be true or false")
            cur = slot["radio_effect"]
            if needed != cur["needed"]:
                slot["radio_effect"] = {"needed": needed, "set_at": today,
                                        "revision": cur["revision"] + (0 if idx is None else 1)}

        if "notes" in body:
            notes = body["notes"] or ""
            if len(notes) > 2000:
                raise ApiError(400, "notes are limited to 2000 characters")
            slot["notes"] = notes

        for f in sorted(approve):
            if slot[f]["status"] == "approved":
                raise ApiError(400, f"{f} is already approved")
            fn = audio_fingerprint if f == "audio" else subtitle_fingerprint
            slot[f].update(status="approved", approved_at=today,
                           fingerprint=fn(slot, self.ce_idx, self.mcc_idx, new_local))

        if idx is None:
            new_doc["slots"].append(slot)
        if new_doc == doc and not local_changed:
            return {"saved": False, "message": "nothing changed", "slot": self.slot(slot_id)}

        # Refuse before writing anything: the store's protections, then the validator's errors for this slot.
        try:
            check_transition(doc, new_doc, user_actions)
        except ProtectedError as e:
            raise ApiError(409, str(e))
        verifs = self._verifications()
        findings, _ = validate_mappings(new_doc, load_schema(SCHEMA_NAME), ce=self.ce_idx, mcc=self.mcc_idx,
                                        local=new_local, verifications=verifs, current_pins=self._current_pins(),
                                        file=MAPPINGS)
        errors = [f for f in findings if f["severity"] == "error" and (f"({mid})" in f["where"] or f["code"] == "schema")]
        if errors:
            raise ApiError(422, "the decision is not valid yet", [f"{f['code']}: {f['message']}" for f in errors])
        try:
            if local_changed:
                save_user_file(self.root / LOCAL, new_local, lsha, "manual-mappings-local-1")
            new_sha = save_mappings(self.root / MAPPINGS, new_doc, sha, user_actions=user_actions)
        except StaleError as e:
            raise ApiError(409, str(e))
        except ProtectedError as e:
            raise ApiError(409, str(e))
        except StoreError as e:
            raise ApiError(422, str(e))
        return {"saved": True, "sha256": new_sha, "slot": self.slot(slot_id), "validation": self.validate()}

    # ------------------------------------------------------------------ level status
    def set_progress(self, body):
        level, status = body.get("level"), body.get("status")
        if level not in self.levels:
            raise ApiError(404, f"unknown level {level}")
        if status not in PROGRESS_STATUSES:
            raise ApiError(400, f"unknown status {status!r}")
        with self._save_lock:
            doc, sha = self._progress()
            if body.get("loaded_sha256") != sha:
                raise ApiError(409, "mission_progress.json changed since this page loaded it; reload")
            if status in ("in_game_tested", "reviewed") and body.get("confirm") is not True:
                raise ApiError(400, f"'{status}' needs an explicit owner confirmation")
            if status in READY_STATUSES:
                mappings, _ = self._mappings()
                prog = level_progress([sid for r in self.levels[level] for sid in r["slot_ids"]], mappings)
                if not prog["ready_for_build"]:
                    raise ApiError(409, f"{level} is not ready: {prog['slots'] - prog['decided']} slot(s) undecided, "
                                        f"{prog['slots'] - prog['audio_approved']} without approved audio")
            ver = body.get("verification") or None
            if ver and ver not in {v["id"] for v in self._verifications().get("verifications", [])}:
                raise ApiError(400, f"unknown verification {ver}")
            entry = {"mcc_level": level, "status": status, "updated_at": self.today(), "verification": ver,
                     "note": (body.get("note") or "")[:2000]}
            new = copy.deepcopy(doc)
            new["levels"] = [e for e in new["levels"] if e["mcc_level"] != level] + [entry]
            new["levels"].sort(key=lambda e: level_sort_key(e["mcc_level"]))
            try:
                new_sha = save_user_file(self.root / PROGRESS, new, sha, "mission-progress-1")
            except StaleError as e:
                raise ApiError(409, str(e))
            except StoreError as e:
                raise ApiError(422, str(e))
        return {"saved": True, "sha256": new_sha, "entry": entry, "validation": self.validate()}

    # ------------------------------------------------------------------ validator
    def validate(self):
        if not self.run_validator:
            return None
        spec = importlib.util.spec_from_file_location(
            "validate_project", Path(__file__).resolve().parents[1] / "validate" / "validate_project.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report, drift = mod.run(self.root, use_git=(self.root / ".git").exists())
        self.last_validation = {"summary": report["summary"],
                                "findings": [f for f in report["findings"] if f["severity"] != "info"][:50],
                                "drift_entries": len(drift["drift"])}
        return self.last_validation
