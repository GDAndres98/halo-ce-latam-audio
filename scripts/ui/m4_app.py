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
- Audio editor (2026-10-09): the owner's non-destructive edit recipe is part of the audio decision
  (`audio.edit`, common/audio_edit.py), so it follows the same approval / needs_rework rules.
  Previews (common/edit_preview.py) render exactly what M6 encodes, into work/m4/preview/ only.
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
from common import audio_combine, audio_edit, interference, radio_clicks, radio_static  # noqa: E402
from common.export_config import ConfigError, load_export_config  # noqa: E402
from common.jsonschema_lite import load_schema  # noqa: E402
from common import mapping_store  # noqa: E402
from common import take_set_conversion as tsc  # noqa: E402
from common.own_set_state import active_own_tags, is_active  # noqa: E402
from common.mapping_store import (  # noqa: E402
    EMPTY_SHA256, SCHEMA_ID, SCHEMA_NAME, ProtectedError, StaleError, StoreError, UserAction, check_transition,
    load as load_mappings, load_or_default, save as save_mappings, save_user_file)
from common.mcc_loc import loc_key, parse_mcc_loc, split_speaker  # noqa: E402
from common.ondemand_audio import AudioUnavailable  # noqa: E402
from common.project_validation import (  # noqa: E402
    READY_STATUSES, added_take_fingerprint, audio_fingerprint, build_ce_index, build_mcc_index, level_progress,
    own_set_subtitle_fingerprint, subtitle_fingerprint, validate_mappings)

MAPPINGS = "mappings/manual_mappings.json"
LOCAL = "mappings/manual_mappings.local.json"
VERIFICATIONS = "mappings/verifications.json"
MISSION_MAP = "mappings/mission_map.json"
PROGRESS = "mappings/mission_progress.json"
RECOVERY = "mappings/take_set_recovery.local.json"  # git-ignored: local text named by replacement-set records
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


_FOLDED_CHAR = {}  # char -> its folded form, or "" for a separator. Startup folds ~3M characters.


def _fold_char(ch):
    base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).casefold()
    return base if base and all(c.isalnum() for c in base) else ""


def fold(text):
    """Search form: case-, accent- and punctuation-insensitive. Letters and digits are kept (accents
    removed, lower-cased); every other run of characters becomes one space. m4.html's highlighter
    mirrors this exactly."""
    out, space = [], True
    for ch in text or "":
        base = _FOLDED_CHAR.get(ch)
        if base is None:
            base = _FOLDED_CHAR[ch] = _fold_char(ch)
        if base:
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
            "different_but_fits": {"marked": False, "set_at": None, "revision": 1},
            "notes": ""}


def _next_id(prefix, used):
    n = max([int(u.split("-")[1]) for u in used if u and u.startswith(prefix + "-")] or [0])
    return f"{prefix}-{n + 1:06d}"


def _audio_sem(a):
    return (a["source"], a["sources"], a["edit"], a.get("mute_reason"))


def _slot_tags(recs):
    """{slot_id: mcc_tag} for a level's records (level_progress: lines of own-take-set sounds)."""
    return {sid: r["mcc_tag"] for r in recs for sid in r["slot_ids"]}


def _fits(m):
    return bool(m and (m.get("different_but_fits") or {}).get("marked"))


def _needs_recording(m):
    return bool(m and (m.get("needs_recording") or {}).get("marked"))


def _edited(m):
    return bool(m and not audio_edit.is_identity(m["audio"]["edit"]))


def _subtitle_sem(s):
    return (s["source"], s["ce_locres"], s["custom_ref"])


def slot_version(m, local):
    """The stored version of one line: its decision and its custom subtitle text. A save that names the
    version it was loaded from (loaded_slot_sha256) is refused when this changed, and accepted when only
    other lines changed (several computers matching different lines at once)."""
    custom = None
    if m and m["subtitle"]["custom_ref"]:
        custom = (local["custom_subtitles"].get(m["subtitle"]["custom_ref"]) or {}).get("text")
    return _sha(json.dumps({"slot": m, "custom_text": custom}, sort_keys=True, ensure_ascii=False).encode("utf-8"))


class M4App:
    def __init__(self, root, *, mcc_audio=None, ce_audio=None, editor=None, today=None, run_validator=True):
        self.root = Path(root)
        self.mcc_audio, self.ce_audio, self.editor = mcc_audio, ce_audio, editor
        self._clicks = None  # MCC's radio clicks, decoded on the first preview that needs them
        self._static = None  # MCC's radio static (Victor 933's interference), likewise
        self.today = today or (lambda: dt.date.today().isoformat())
        self.run_validator = run_validator
        self._save_lock = threading.Lock()
        self.last_validation = None
        # The project validator after a save runs in the background (validate_soon): it re-checks every
        # catalog and took ~5.4 s of each 5.7 s save. Catalog results are cached by file size and mtime.
        self._catalog_cache = {}
        self._validation_lock = threading.Lock()
        self._validation_queued = False
        self._queue_lock = threading.Lock()
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
        if not (self.root / MAPPINGS).is_file():
            raise ApiError(500, f"{MAPPINGS} is missing; create it from the template (design §5.1)")
        try:
            doc, sha = load_mappings(self.root / MAPPINGS)
        except StoreError as e:  # the file and the database disagree: refuse, never guess
            raise ApiError(409, str(e))
        if doc.get("schema") != SCHEMA_ID:
            raise ApiError(409, f"{MAPPINGS} is {doc.get('schema')}; run python scripts/validate/migrate_mappings.py "
                                "--write first")
        return doc, sha

    def _read_document(self, rel, default):
        """User documents (custom subtitles, mission progress) are read through the store, which checks
        them against the database."""
        try:
            return load_or_default(self.root / rel, default)
        except StoreError as e:
            raise ApiError(409, str(e))

    def _local(self):
        return self._read_document(LOCAL, {"schema": "manual-mappings-local/1", "custom_subtitles": {},
                                           "user_recordings": {}})

    def _progress(self):
        return self._read_document(PROGRESS, {"schema": "mission-progress/1", "levels": []})

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
                           "tags": len(recs), "slots": len(sids),
                           "progress": level_progress(sids, mappings, [r["mcc_tag"] for r in recs], _slot_tags(recs)),
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

    @staticmethod
    def _recorded_ids(doc):
        return [m["mapping_id"] for o in doc.get("own_sets", []) for m in (o.get("provenance") or {}).get("slots", [])]

    @staticmethod
    def _recorded_slots(doc):
        """{slot_id: recorded decision} of the sounds whose replacement set is in force: their lines have no decision
        of their own, but the reminders of the archived one (needs a new recording, needs radio effect, notes) stay
        operational (docs/replacement-set-conversion.md §6)."""
        return {m["slot_id"]: m for o in doc.get("own_sets", []) if is_active(o)
                for m in (o.get("provenance") or {}).get("slots", [])}

    def _slot_filter(self, status, m, s, take_counts=None, own=None, recorded=None):
        if status == "takes":  # the sound has added takes (counted once per request, not per line)
            return (take_counts or {}).get(self.slot_index[s["slot_id"]][1]["mcc_tag"], 0) > 0
        if own:  # every take of the sound is replaced: the line is filtered by its sound's takes (MccColumn shows the same)
            a = "approved" if own["takes"] and own["approved"] == own["takes"] else                 "needs_rework" if own["needs_rework"] else "draft"
            return {None: True, "": True, "matched": True, "needs_rework": a == "needs_rework",
                    "audio_pending": a != "approved", "draft": a == "draft", "approved": a == "approved",
                    "own_set": True, "stereo": s["channels"] > 1,
                    "radio": bool(recorded and recorded["radio_effect"]["needed"]),
                    "recording": _needs_recording(recorded)}.get(status, False)
        st = m["match"]["status"] if m else "unreviewed"
        a = m["audio"]["status"] if m else "draft"
        sub = m["subtitle"]["status"] if m else "draft"
        return {None: True, "": True, "undecided": st == "unreviewed",
                "matched": st == "matched", "no_equivalent": st == "no_equivalent", "deferred": st == "deferred",
                "needs_rework": "needs_rework" in (a, sub), "audio_pending": a != "approved",
                "subtitle_pending": sub != "approved", "draft": "draft" in (a, sub),
                "approved": a == "approved" and sub == "approved",
                "keep_original": bool(m and m["audio"]["source"] == "keep_original"),
                "muted": bool(m and m["audio"]["source"] == "mute"),
                "radio": bool(m and m["radio_effect"]["needed"]), "fits": _fits(m), "edited": _edited(m),
                "recording": _needs_recording(m),
                "stereo": s["channels"] > 1}.get(status, False)

    def _subtitle_preview(self, mcc_tag, table=None):
        """The first words of the LATAM Spanish subtitle (Spain's if there is none), or of one table's text
        (`table`, e.g. "EN"): enough to recognise a line in the list without loading the full text."""
        texts = self._mcc_text(mcc_tag)
        entry = texts.get(table) if table else (texts.get("SU") or texts.get("SP"))
        text = (entry or {}).get("text") or ""
        return text if len(text) <= 90 else text[:87].rstrip() + "…"

    def slots(self, level, status=None, q=None, limit=1500):
        """level may be 'all' (search every level). Catalog order; the query and status only filter."""
        if level != "all" and level not in self.levels:
            raise ApiError(404, f"unknown level {level}")
        mappings, msha = self._mappings()
        by_slot = {s["slot_id"]: s for s in mappings["slots"]}
        take_counts = self._take_counts(mappings)
        own_tags = self._own_status(mappings)
        recorded = self._recorded_slots(mappings)
        terms = parse_query(q)
        out, total = [], 0
        for lv in (self.levels if level == "all" else [level]):
            for r in self.levels[lv]:
                for s in r["samples"]["spanish"]:
                    m = by_slot.get(s["slot_id"])
                    if not self._slot_filter(status, m, s, take_counts, own_tags.get(r["mcc_tag"]),
                                             recorded.get(s["slot_id"])):
                        continue
                    if terms and not matches(terms, self._mcc_hay[s["slot_id"]]):
                        continue
                    total += 1
                    if len(out) >= limit:
                        continue
                    out.append(self._slot_row(lv, r, s, m, take_counts, own_tags, recorded))
                    if terms:  # lets the page show and highlight what matched
                        out[-1]["texts"] = {t: v["text"] for t, v in self._mcc_text(r["mcc_tag"]).items()}
        prog = None
        if level != "all":
            prog = level_progress([sid for r in self.levels[level] for sid in r["slot_ids"]], mappings,
                                  [r["mcc_tag"] for r in self.levels[level]], _slot_tags(self.levels[level]))
        return {"level": level, "slots": out, "total": total, "truncated": total > len(out),
                "progress": prog, "sha256": msha, "terms": terms}

    def _slot_row(self, lv, r, s, m, take_counts=None, own_tags=None, recorded=None):
        """One line of the MCC list (also returned by a save, so the page updates that row in place). A line of a sound
        whose replacement set is in force has no decision; its archived decision's reminders are shown instead
        (archived: true)."""
        en = r["samples"]["english"]
        k = s["ordinal_in_tag"]
        if recorded is None:
            recorded = self._recorded_slots(self._mappings()[0])
        arch = recorded.get(s["slot_id"]) if m is None else None
        return {"slot_id": s["slot_id"], "level": lv, "mcc_tag": r["mcc_tag"],
                "tag_name": r["tag_name"], "kind": r["kind"],
                "speaker_from_name": r["speaker_from_name"], "ordinal": k,
                "permutations": len(r["samples"]["spanish"]), "duration_s": s["duration_s"],
                "en_duration_s": en[k]["duration_s"] if k < len(en) else None,
                "english_index": en[k]["index"] if k < len(en) else None,
                "channels": s["channels"], "flags": r["flags"],
                "decision": self._decision_summary(m),
                "radio_effect": bool(m and m["radio_effect"]["needed"]) or bool(arch and arch["radio_effect"]["needed"]),
                "different_but_fits": _fits(m), "needs_recording": _needs_recording(m) or _needs_recording(arch),
                "edited": _edited(m),
                "archived_reminders": bool(arch and (arch["radio_effect"]["needed"] or _needs_recording(arch)
                                                     or arch.get("notes"))),
                "added_takes": (take_counts if take_counts is not None
                                else self._take_counts(self._mappings()[0])).get(r["mcc_tag"], 0),
                "own_set": (own_tags if own_tags is not None else self._own_status(self._mappings()[0])).get(r["mcc_tag"]),
                "preview": self._subtitle_preview(r["mcc_tag"]),
                "english_preview": self._subtitle_preview(r["mcc_tag"], "EN"),
                "spanish_index": s["index"]}

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
        listed in some slot's match or used by an added take, except those of keep_slot (the slot being edited)."""
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
        doc = self._mappings()[0]
        for m in doc["slots"]:
            for ref in m["match"]["ce_line_refs"]:
                used.setdefault(ref, []).append(m["slot_id"])
        for t in doc.get("added_takes", []):     # a sound's added takes use their CE lines too (listed by take id)
            for src in t["audio"]["sources"]:
                if src.get("ce_line_ref") and t["take_id"] not in used.get(src["ce_line_ref"], []):
                    used.setdefault(src["ce_line_ref"], []).append(t["take_id"])
        hidden ={ref for ref, sids in used.items() if any(x != keep_slot for x in sids)} if hide_used else set()
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

    def slot(self, slot_id, with_interference=True):
        """with_interference=False (the public view) skips the Victor 933 lane defaults, which decode audio."""
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
        edit = m["audio"]["edit"] if m else dict(audio_edit.EDIT_ZERO)
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
                "edit": {"identity": audio_edit.is_identity(edit), "summary": audio_edit.summary(edit),
                         "available": self.editor is not None, "engine": audio_edit.ENGINE},
                "interference": {ref: d for ref in refs if with_interference
                                 and (d := self.interference_defaults(ref, slot_id))},
                "ce_missions": self._mission_scope(level),
                "sound": self.sound(r["mcc_tag"], mappings, local),
                "sha256": {"mappings": msha, "local": lsha, "slot": slot_version(m, local)}}

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

    # ------------------------------------------------------------------ audio editor
    def _ce_wav_for(self, src):
        ref, lang = src.get("ce_line_ref"), src.get("language", "Spanish(Mexico)")
        if ref not in self.ce_lines or lang not in CE_LANGS:
            raise ApiError(404, "unknown CE line or language")
        return ref, lang, self.ce_wav(ref, lang)

    def edit_preview(self, body):
        """body: {slot_id, ce_line_ref, language, edit}. Renders the recipe and the global export gain
        (config/audio_export.json) exactly as M6 would (never
        saves anything) -> {key, stats, edit (canonical), summary, identity, mcc_reference_lufs, urls}."""
        if not self.editor:
            raise ApiError(503, "the audio editor needs ffmpeg and libcelt (see docs/m4-user-guide.md)")
        sid = body.get("slot_id")
        if sid not in self.slot_index:
            raise ApiError(404, f"unknown slot {sid}")
        level, _r, s = self.slot_index[sid]
        if s["channels"] != 1:
            raise ApiError(400, "the editor supports mono slots only (stereo replacement is deferred)")
        ref, lang, wav = self._ce_wav_for(body)
        try:
            edit = audio_edit.normalize(body.get("edit") or {}, for_source={"ce_line_ref": ref, "language": lang})
        except audio_edit.EditError as e:
            raise ApiError(400, f"edit: {e}")
        problems = audio_edit.problems(edit, self._wav_duration(wav))
        if problems:
            raise ApiError(422, "the edit is not valid", problems)
        mcc_ref = None
        if self.mcc_audio:
            try:
                mcc_ref = self.editor.reference_lufs(self.mcc_audio.wav(level, "spanish", s))
            except AudioUnavailable:
                pass  # without it, match_spain falls back to the global gain (reported in the stats)
        try:
            cfg = load_export_config(self.root)  # read on every preview: a config change applies at once
        except ConfigError as e:
            raise ApiError(500, str(e))
        try:
            clicks = self.radio_clicks() if (edit.get("radio") or {}).get("clicks") else None
            static = self.radio_static() if interference.needs_mcc_static(edit.get("interference")) else None
            r = self.editor.render(wav, edit, mcc_ref, cfg["global_gain_db"], cfg["level_mode"], clicks, static)
        except audio_edit.EditError as e:
            raise ApiError(422, f"edit: {e}")
        return {"key": r["key"], "stats": r["stats"], "edit": edit, "summary": audio_edit.summary(edit),
                "identity": audio_edit.is_identity(edit), "mcc_reference_lufs": mcc_ref, "export_config": cfg,
                "urls": {k: f"/audio/preview?key={r['key']}&kind={k}" for k in ("edited", "encoded")}}

    def edit_preview_combined(self, body):
        """body: {slot_id, source: ce_concat | ce_mix, sources: [{ce_line_ref, language}] x2, edit}. Renders the join
        or overlay and the build-level gain exactly as M6 would (never saves) -> {key, stats, edit, summary, urls}."""
        if not self.editor:
            raise ApiError(503, "previews need ffmpeg and libcelt (see docs/m4-user-guide.md)")
        sid = body.get("slot_id")
        if sid not in self.slot_index:
            raise ApiError(404, f"unknown slot {sid}")
        level, _r, s = self.slot_index[sid]
        if s["channels"] != 1:
            raise ApiError(400, "mono slots only (stereo replacement is deferred)")
        source = body.get("source")
        if source not in audio_combine.MODE_OF:
            raise ApiError(400, "source must be ce_concat (join) or ce_mix (play together)")
        _src, sources = self._normalize_audio({"source": source, "sources": body.get("sources") or []}, [])
        edit = self._normalize_combined({"edit": body.get("edit") or {}}, source, sources, {})
        wavs = [self._ce_wav_for(x)[2] for x in sources]
        mcc_ref = None
        if self.mcc_audio:
            try:
                mcc_ref = self.editor.reference_lufs(self.mcc_audio.wav(level, "spanish", s))
            except AudioUnavailable:
                pass
        try:
            cfg = load_export_config(self.root)
        except ConfigError as e:
            raise ApiError(500, str(e))
        try:
            clicks = self.radio_clicks() if (edit.get("radio") or {}).get("clicks") else None
            r = self.editor.render_combined(wavs, edit, mcc_ref, cfg["global_gain_db"], cfg["level_mode"], clicks)
        except audio_edit.EditError as e:
            raise ApiError(422, f"edit: {e}")
        return {"key": r["key"], "stats": r["stats"], "edit": edit, "summary": audio_combine.summary(edit),
                "identity": False, "mcc_reference_lufs": mcc_ref, "export_config": cfg,
                "urls": {k: f"/audio/preview?key={r['key']}&kind={k}" for k in ("edited", "encoded")}}

    def radio_clicks(self):
        """MCC's Spain radio clicks (common/radio_clicks.py), decoded once from the pinned bank."""
        if self._clicks is None:
            if not self.mcc_audio:
                raise ApiError(503, "the radio clicks need MCC audio decoding (vgmstream)")
            try:
                self._clicks = radio_clicks.load(self.mcc_audio, self.slot_index)
            except (AudioUnavailable, radio_clicks.ClickError) as e:
                raise ApiError(503, f"radio clicks: {e}")
        return self._clicks

    def radio_static(self):
        """MCC's radio static (common/radio_static.py), decoded once from the pinned bank."""
        if self._static is None:
            if not self.mcc_audio:
                raise ApiError(503, "the transmission interference needs MCC audio decoding (vgmstream)")
            try:
                self._static = radio_static.load(self.mcc_audio, self.slot_index)
            except (AudioUnavailable, radio_static.StaticError) as e:
                raise ApiError(503, f"radio static: {e}")
        return self._static

    def interference_defaults(self, ce_line_ref, slot_id=None):
        """For a line with the one-off interference treatment (Victor 933): the owner's 11 guides
        (config/interference/<line>.json), the default curve generated from them, the intensity scale and the MCC
        samples of the slot (reference overlay and A/B). None for every other line."""
        if ce_line_ref not in audio_edit.INTERFERENCE_LINES:
            return None
        p = self.root / "config" / "interference" / (ce_line_ref.split("#")[0] + ".json")
        if not p.is_file():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        guides = [{k: g[k] for k in ("label", "kind", "start_s", "end_s")} for g in d["guides"]]
        try:
            duration = self._wav_duration(self.ce_wav(ce_line_ref, "Spanish(Mexico)"))
        except ApiError:
            duration = None
        out = {"guides": guides, "kinds": d.get("kinds"), "alignment": d.get("alignment"), "duration_s": duration,
               "points": interference.default_points(guides, duration) if duration else None,
               "scale": {"speech_full": interference.SPEECH_FULL, "partial": interference.PARTIAL_LEVEL,
                         "mask": interference.MASK_LEVEL, "bed": interference.BED_LEVEL}}
        if slot_id in self.slot_index:
            level, rec, s = self.slot_index[slot_id]
            en = rec["samples"]["english"]
            out["mcc"] = {"level": level, "spanish": s["index"], "english": en[0]["index"] if en else None}
        return out

    def interference_reference(self, slot_id, lang):
        """The MCC original's interference estimate (common/interference.reference_curve), for the Studio overlay.
        Cached in work/m4/interference/ by the sample's data hash. Read-only otherwise."""
        if slot_id not in self.slot_index or lang not in MCC_LANGS:
            raise ApiError(404, "unknown slot or language")
        level, rec, s = self.slot_index[slot_id]
        sample = s if lang == "spanish" else (rec["samples"]["english"] or [None])[0]
        if not sample:
            raise ApiError(404, f"no {lang} recording")
        cache = self.root / "work" / "m4" / "interference" / f"ref_{lang}_{sample['data_sha256'][:16]}.json"
        if cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))
        if not self.mcc_audio:
            raise ApiError(503, "MCC audio decoding is not configured")
        try:
            x, fs = audio_edit.wav_mono_float(self.mcc_audio.wav(level, lang, sample))
        except AudioUnavailable as e:
            raise ApiError(503, str(e))
        out = dict(interference.reference_curve(x, fs), language=lang, slot_id=slot_id)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out), encoding="utf-8")
        return out

    def preview_wav(self, key, kind):
        if not self.editor:
            raise ApiError(503, "the audio editor is not configured")
        try:
            p = self.editor.path(key, kind)
        except ValueError as e:
            raise ApiError(400, str(e))
        if not p.is_file():
            raise ApiError(404, "preview not rendered (render it first)")
        return p

    def _normalize_combined(self, a, source, sources, current):
        """The combine recipe of a join (ce_concat) or an overlay (ce_mix). Not sent: kept while it still belongs
        to the same two recordings in the same order and the same mode, otherwise the default (unedited parts, no
        gap, no offset): a recipe never silently moves to other recordings."""
        mode = audio_combine.MODE_OF[source]
        binds = [{"ce_line_ref": s["ce_line_ref"], "language": s["language"]} for s in sources]
        raw = a.get("edit")
        if raw is None:
            if audio_combine.is_combine(current) and current.get("mode") == mode and current.get("for_sources") == binds:
                return current
            return audio_combine.default(mode, binds)
        if not isinstance(raw, dict):
            raise ApiError(400, "edit must be an object")
        try:
            edit = audio_combine.normalize(raw, mode, binds)
        except audio_edit.EditError as e:
            raise ApiError(400, f"edit: {e}")
        durations = [self._wav_duration(self._ce_wav_for(b)[2]) for b in binds] if mode == "concat" else None
        problems = audio_combine.problems(edit, durations, sources)
        if problems:
            raise ApiError(422, "the edit is not valid", problems)
        return edit

    def _normalize_edit(self, a, source, sources, current):
        """The recipe to store with this audio choice. Not sent: kept while it still belongs to the same
        CE source, otherwise reset (an edit never silently moves to another recording)."""
        if source in audio_combine.MODE_OF:
            return self._normalize_combined(a, source, sources, current)
        if audio_combine.is_combine(current):  # leaving a join / overlay: its recipe does not apply to one line
            current = dict(audio_edit.EDIT_ZERO)
        gap = current.get("gap_s", 0)
        src = ({"ce_line_ref": sources[0]["ce_line_ref"], "language": sources[0]["language"]}
               if source == "ce" and sources else None)
        raw = a.get("edit")
        if raw is None:
            if audio_edit.is_identity(current) or (src and current.get("for_source") == src):
                return current
            return dict(audio_edit.EDIT_ZERO, gap_s=gap)
        if not isinstance(raw, dict):
            raise ApiError(400, "edit must be an object")
        try:
            edit = audio_edit.normalize(dict(raw, gap_s=raw.get("gap_s", gap)), for_source=src)
        except audio_edit.EditError as e:
            raise ApiError(400, f"edit: {e}")
        if audio_edit.is_identity(edit):
            same = audio_edit.is_identity(current) and current.get("gap_s", 0) == edit["gap_s"]
            return current if same else edit
        if source != "ce":
            raise ApiError(400, "edits apply to one CE line (audio source 'ce'); reset the edit first")
        _ref, _lang, wav = self._ce_wav_for(src)
        problems = audio_edit.problems(edit, self._wav_duration(wav))
        if problems:
            raise ApiError(422, "the edit is not valid", problems)
        return edit

    # ------------------------------------------------------------------ save
    def _normalize_audio(self, a, refs):
        source = a.get("source")
        if source not in ("keep_original", "ce", "ce_concat", "ce_mix", "mute"):
            raise ApiError(400, f"audio source {source!r} is not supported by the UI")
        if source == "mute":  # Mute / No replacement: no sources; the reason is part of the decision
            if a.get("sources"):
                raise ApiError(400, "a muted line has no audio sources")
            reason = a.get("mute_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ApiError(400, "say why the line is muted (mute_reason)")
            if len(reason.strip()) > 500:
                raise ApiError(400, "the mute reason is limited to 500 characters")
            return source, []
        sources = []
        for x in a.get("sources") or []:
            ref, lang = x.get("ce_line_ref"), x.get("language", "Spanish(Mexico)")
            if ref not in self.ce_lines:
                raise ApiError(400, f"unknown CE line {ref}")
            if lang not in CE_LANGS:
                raise ApiError(400, f"unknown language {lang}")
            sources.append({"kind": "ce", "ce_line_ref": ref, "language": lang})
        if source in audio_combine.MODE_OF and len(sources) != 2:  # join / play together (docs/combine-recordings.md)
            raise ApiError(400, "joining or playing recordings together uses exactly two Campaign Evolved recordings")
        if source == "ce" and len(sources) != 1:
            raise ApiError(400, "a Campaign Evolved replacement uses exactly one recording")
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
        local, lsha = self._local()
        if rec["mcc_tag"] in self._own_tags(doc):
            raise ApiError(409, "every take of this sound is replaced (own take set), so this line has no decision of "
                                "its own; approve the takes under 'Takes of this sound', or choose 'Back to Spain's "
                                "takes' under Replacement audio to decide this line again")
        idx = next((i for i, x in enumerate(doc["slots"]) if x["slot_id"] == slot_id), None)
        if "loaded_slot_sha256" in body:
            # Per line: the save is checked against the version of this line the page loaded, so saves of
            # other lines (another computer, another window) do not make it stale. The write itself is still
            # checked against the whole file below (the store refuses if anything changed in between).
            if body["loaded_slot_sha256"] != slot_version(None if idx is None else doc["slots"][idx], local):
                raise ApiError(409, "This line was changed elsewhere (another computer or window) since this page "
                                    "loaded it; reload it and re-apply your edits")
        else:  # the whole-file check (classic page, older clients)
            if body.get("loaded_sha256") != sha:
                raise ApiError(409, "manual_mappings.json changed since this page loaded it; reload and re-apply")
            if body.get("local_sha256", lsha) != lsha:
                raise ApiError(409, "manual_mappings.local.json changed since this page loaded it; reload")
        new_doc = copy.deepcopy(doc)
        if idx is None:
            slot = default_slot(_next_id("m", [x["mapping_id"] for x in doc["slots"]] + self._recorded_ids(doc)),
                                slot_id, rec["mcc_tag"])
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
            edit = self._normalize_edit(body["audio"], source, sources, slot["audio"]["edit"])
            want = dict(slot["audio"], source=source, sources=sources, edit=edit)
            want.pop("mute_reason", None)
            if source == "mute":
                want["mute_reason"] = body["audio"]["mute_reason"].strip()
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
                    custom_ref = _next_id("c", self._used_custom_refs(doc, local))
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

        if "different_but_fits" in body:  # owner flag on the match; independent of approvals like radio_effect
            marked = (body["different_but_fits"] or {}).get("marked")
            if not isinstance(marked, bool):
                raise ApiError(400, "different_but_fits.marked must be true or false")
            cur = slot.get("different_but_fits") or {"marked": False, "set_at": None, "revision": 1}
            if marked != cur["marked"]:
                existed = idx is not None and "different_but_fits" in slot
                slot["different_but_fits"] = {"marked": marked, "set_at": today,
                                              "revision": cur["revision"] + (1 if existed else 0)}
            elif "different_but_fits" not in slot:
                slot["different_but_fits"] = cur

        if "needs_recording" in body:  # owner flag: the line needs a new recording; independent of approvals
            marked = (body["needs_recording"] or {}).get("marked")
            if not isinstance(marked, bool):
                raise ApiError(400, "needs_recording.marked must be true or false")
            cur = slot.get("needs_recording")
            # Optional field: written only once it is first marked, so saving other changes leaves existing
            # slots byte-identical.
            if marked != (cur or {}).get("marked", False):
                slot["needs_recording"] = {"marked": marked, "set_at": today,
                                           "revision": cur["revision"] + 1 if cur else 1}

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

        if list(slot)[-1] != "notes":  # optional flags are inserted before the notes
            slot["notes"] = slot.pop("notes")
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
                                        file=MAPPINGS, only_mapping_ids={mid})
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
        self.validate_soon()
        detail = self.slot(slot_id)
        level_slots = [sid for x in self.levels[level] for sid in x["slot_ids"]]
        return {"saved": True, "sha256": new_sha, "slot": detail,
                # The list row and the level's progress as the server now holds them: the page replaces that
                # row and the counters instead of reloading the list.
                "row": self._slot_row(level, rec, _s, detail["mapping"]),
                "progress": level_progress(level_slots, new_doc, [x["mcc_tag"] for x in self.levels[level]],
                                           _slot_tags(self.levels[level])),
                # The project-wide report is refreshed in the background (validate_soon); this is the last
                # complete one. The decision itself was checked above, before anything was written.
                "validation": self.last_validation, "validation_pending": self.run_validator}

    # ------------------------------------------------------------------ added takes (docs/added-takes-design.md)
    @staticmethod
    def _take_counts(doc):
        out = {}
        for t in doc.get("added_takes", []):
            out[t["mcc_tag"]] = out.get(t["mcc_tag"], 0) + 1
        return out

    def _tag_record(self, mcc_tag):
        for lv, recs in self.levels.items():
            for r in recs:
                if r["mcc_tag"] == mcc_tag:
                    return lv, r
        raise ApiError(404, f"unknown sound {mcc_tag}")

    def take_rule(self, mcc_tag):
        """-> (allowed, reason). Mono sounds only (stereo replacement is deferred). Owner, 2026-10-19: with or without
        a SU/SP subtitle entry (before: barks only). On a sound with one, every take shows the same text: the line
        subtitle decisions decide it, or, while the sound plays its own take set, the set's ONE subtitle."""
        _lv, r = self._tag_record(mcc_tag)
        if any(s["channels"] != 1 for s in r["samples"]["spanish"]):
            return False, "stereo sound (stereo replacement is deferred)"
        return True, ""

    @staticmethod
    def _own_tags(doc):
        """Sounds whose replacement set is in force (a staged conversion is not: its lines keep their decisions)."""
        return active_own_tags(doc)

    def has_subtitle_entry(self, mcc_tag):
        return loc_key(mcc_tag) in self._subtitle_keys()

    @staticmethod
    def _used_custom_refs(doc, local):
        """Every custom subtitle ref in use or on record: local texts, line decisions, sets' subtitles and the
        decisions replacement-set records keep (a new ref never collides with one an Undo would bring back)."""
        return (list((local or {}).get("custom_subtitles") or {})
                + [x["subtitle"]["custom_ref"] for x in doc["slots"]]
                + [(o.get("subtitle") or {}).get("custom_ref") for o in doc.get("own_sets", [])]
                + [m["subtitle"]["custom_ref"] for o in doc.get("own_sets", [])
                   for m in (o.get("provenance") or {}).get("slots", [])])

    def _own_status(self, doc):
        """{mcc_tag: {takes, approved, needs_rework, subtitle}} for the sounds in own-take-set mode (the MCC list shows
        the sound's state on its lines, which have no decision of their own). subtitle: the set's one subtitle status
        ("undecided" when there is none) for a sound with a subtitle entry, else None."""
        out = {t: {"takes": 0, "approved": 0, "needs_rework": 0,
                   "subtitle": None if not self.has_subtitle_entry(t) else "undecided"} for t in active_own_tags(doc)}
        for o in doc.get("own_sets", []):
            if o["mcc_tag"] in out and out[o["mcc_tag"]]["subtitle"] and o.get("subtitle"):
                out[o["mcc_tag"]]["subtitle"] = o["subtitle"]["status"]
        for t in doc.get("added_takes", []):
            st = out.get(t["mcc_tag"])
            if st is not None:
                st["takes"] += 1
                st["approved"] += t["audio"]["status"] == "approved"
                st["needs_rework"] += t["audio"]["status"] == "needs_rework"
        return out

    @staticmethod
    def takes_version(doc, mcc_tag, local=None):
        """The stored version of one sound's added takes and own-set switch (with the set's subtitle and, when it is
        custom, its text): a take save names the version it was made from."""
        takes = [t for t in doc.get("added_takes", []) if t["mcc_tag"] == mcc_tag]
        own = [o for o in doc.get("own_sets", []) if o["mcc_tag"] == mcc_tag]
        data = {"takes": takes, "own_set": own}
        ref = ((own[0] if own else {}).get("subtitle") or {}).get("custom_ref")
        if ref:  # only for a set with a custom subtitle: every other version is unchanged
            data["set_custom_text"] = (((local or {}).get("custom_subtitles") or {}).get(ref) or {}).get("text")
        return _sha(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8"))

    def sound(self, mcc_tag, mappings=None, local=None):
        """One sound: its Spain takes (with their decisions) and its added takes, for the Studio's section."""
        if mappings is None:
            mappings, _ = self._mappings()
        if local is None:
            local, _ = self._local()
        lv, r = self._tag_record(mcc_tag)
        by_slot = {x["slot_id"]: x for x in mappings["slots"]}
        allowed, reason = self.take_rule(mcc_tag)
        takes = []
        for t in sorted((t for t in mappings.get("added_takes", []) if t["mcc_tag"] == mcc_tag),
                        key=lambda t: t["position"]):
            drift = (t["audio"]["status"] == "approved"
                     and t["audio"]["fingerprint"] != added_take_fingerprint(t, self.ce_idx, self.mcc_idx, local))
            src = (t["audio"]["sources"] or [{}])[0]
            takes.append({**t, "drift": drift, "edit_summary": audio_edit.summary(t["audio"]["edit"]),
                          "edited": not audio_edit.is_identity(t["audio"]["edit"]),
                          "line": self.ce_line(src["ce_line_ref"]) if src.get("ce_line_ref") in self.ce_lines else None})
        spain = []
        for s in r["samples"]["spanish"]:
            m = by_slot.get(s["slot_id"])
            spain.append({"slot_id": s["slot_id"], "ordinal": s["ordinal_in_tag"], "duration_s": s["duration_s"],
                          "spanish_index": s["index"], "decision": self._decision_summary(m),
                          "mapping_id": (m or {}).get("mapping_id"),
                          "audio_ref": ((m or {}).get("audio", {}).get("sources") or [{}])[0].get("ce_line_ref")})
        own = next((o for o in mappings.get("own_sets", []) if o["mcc_tag"] == mcc_tag), None)
        prov = (own or {}).get("provenance")
        staged = {t["take_id"] for t in (prov or {}).get("takes", []) if t["origin"] == "created"} \
            if own and not is_active(own) else set()
        for t in takes:
            t["staged"] = t["take_id"] in staged
        entry = self.has_subtitle_entry(mcc_tag)
        return {"mcc_tag": mcc_tag, "level": lv, "tag_name": r["tag_name"], "allowed": allowed, "reason": reason,
                "spain_takes": spain, "added_takes": takes, "total_takes": len(spain) + len(takes),
                "warn_above": 12, "version": self.takes_version(mappings, mcc_tag, local),
                # Owner, 2026-10-19: a sound with a SU/SP entry shows ONE text for every take (MCC's texts here, for
                # the set subtitle panel); while it plays its own take set, the set's subtitle decides it.
                "has_subtitle_entry": entry,
                "mcc_text": ({t: v["text"] for t, v in self._mcc_text(mcc_tag).items() if t in ("SU", "SP")}
                             if entry else None),
                "set_subtitle": self._set_subtitle_view(own, local) if own and entry else None,
                # Every line decision, take and set of the sound (docs/replacement-set-conversion.md): conversions
                # and the 4th audio option name this version, because they consume the line decisions too.
                "sound_version": self._sound_version(mappings, local, mcc_tag),
                "mode": tsc.mode_of(mappings, mcc_tag),
                "own_set": {"mcc_tag": own["mcc_tag"], "set_at": own["set_at"]} if own and is_active(own) else None,
                "reminders": [{"slot_id": m["slot_id"], "mapping_id": m["mapping_id"],
                               "needs_recording": _needs_recording(m), "radio_effect": m["radio_effect"]["needed"],
                               "notes": m.get("notes", "")}
                              for m in (prov or {}).get("slots", []) if own and is_active(own)
                              and (_needs_recording(m) or m["radio_effect"]["needed"] or m.get("notes"))],
                "conversion": None if not prov else {
                    "state": "active" if is_active(own) else "staged", "kind": prov["kind"],
                    "record_id": prov["record_id"], "created_at": prov["created_at"],
                    "activated_at": prov["activated_at"], "replaced_decisions": len(prov["slots"]),
                    "takes": prov["takes"], "acknowledged": prov["acknowledged"],
                    "decisions": [{"mapping_id": m["mapping_id"], "slot_id": m["slot_id"],
                                   "audio": m["audio"]["status"], "audio_source": m["audio"]["source"],
                                   "audio_ref": (m["audio"]["sources"] or [{}])[0].get("ce_line_ref"),
                                   "subtitle": m["subtitle"]["status"], "notes": m.get("notes", "")}
                                  for m in prov["slots"]]}}

    def _set_subtitle_view(self, own, local):
        """The set's one subtitle for the page: the decision, its custom text, the text it shows and drift."""
        sub = own.get("subtitle")
        if not sub:
            return {"decision": None, "custom_text": None, "text": None, "drift": False}
        custom = (((local or {}).get("custom_subtitles") or {}).get(sub["custom_ref"]) or {}).get("text") \
            if sub["custom_ref"] else None
        text = None
        if sub["source"] == "ce_locres" and sub["ce_locres"]["ce_line_ref"] in self.ce_lines:
            e = self.ce_lines[sub["ce_locres"]["ce_line_ref"]][2]
            text = (e["subtitles"].get(sub["ce_locres"]["culture"]) or {}).get("text")
        elif sub["source"] == "custom":
            text = custom
        elif sub["source"] == "keep_original":
            text = self._mcc_text(own["mcc_tag"])["SU"]["text"]
        elif sub["source"] == "none":
            text = ""
        drift = sub["status"] == "approved" and sub["fingerprint"] != own_set_subtitle_fingerprint(
            own, self.ce_idx, self.mcc_idx, local)
        return {"decision": sub, "custom_text": custom, "text": text, "drift": drift}

    def _set_subtitle_object(self, body_sub, current, doc, local, new_local, today):
        """A set subtitle choice from the page -> (subtitle object, local changed). body_sub: {source, ce_locres?:
        {ce_line_ref, culture}, custom_text?}. Same sources and rules as a line's subtitle; never approved here."""
        if not isinstance(body_sub, dict):
            raise ApiError(400, "subtitle must be {source, ce_locres?, custom_text?}")
        source = body_sub.get("source")
        if source not in ("keep_original", "ce_locres", "custom", "none"):
            raise ApiError(400, f"unknown subtitle source {source!r}")
        cur = current or {"status": "draft", "source": "keep_original", "ce_locres": None, "custom_ref": None,
                          "fingerprint": None, "approved_at": None, "revision": 1}
        ce_locres, custom_ref, local_changed = None, None, False
        if source == "ce_locres":
            c = body_sub.get("ce_locres") or {}
            if c.get("ce_line_ref") not in self.ce_lines or c.get("culture") not in CULTURES:
                raise ApiError(400, "subtitle ce_locres needs a known CE line and culture")
            ce_locres = {"ce_line_ref": c["ce_line_ref"], "culture": c["culture"]}
        if source == "custom":
            text = (body_sub.get("custom_text") or "").strip()
            if not text:
                raise ApiError(400, "custom subtitle text is empty")
            if len(text) > 2000:
                raise ApiError(400, "the subtitle text is limited to 2000 characters")
            custom_ref = cur["custom_ref"] or _next_id("c", self._used_custom_refs(doc, new_local))
            if (new_local["custom_subtitles"].get(custom_ref) or {}).get("text") != text:
                if cur["status"] == "approved":
                    raise ApiError(409, "the set's subtitle is approved and read-only; choose 'needs rework' first")
                new_local["custom_subtitles"][custom_ref] = {"text": text, "updated_at": today}
                local_changed = True
        want = dict(cur, source=source, ce_locres=ce_locres, custom_ref=custom_ref)
        if _subtitle_sem(want) != _subtitle_sem(cur) and cur["status"] == "approved":
            raise ApiError(409, "the set's subtitle is approved and read-only; choose 'needs rework' first")
        return want, local_changed

    def set_subtitle(self, body):
        """body: {mcc_tag, loaded_takes_sha256, subtitle?: {source, ce_locres?, custom_text?} | null,
        actions?: [{action: approve | needs_rework}]}. The ONE subtitle of a sound that has a SU/SP entry and an own
        take set, staged or in force (owner, 2026-10-19). Same rules as a line's subtitle: saved as a draft; approved
        only by an explicit 'approve' action (fingerprint pinned); approved = read-only until 'needs_rework'
        (revision + 1). null removes an unapproved one (undecided again). The custom text stays in the git-ignored
        local file."""
        with self._save_lock:
            tag = body.get("mcc_tag")
            self._tag_record(tag)
            doc, sha = self._mappings()
            local, lsha = self._local()
            if body.get("loaded_takes_sha256") != self.takes_version(doc, tag, local):
                raise ApiError(409, "This sound's takes changed elsewhere since this page loaded them; reload")
            if not self.has_subtitle_entry(tag):
                raise ApiError(409, "this sound has no subtitle entry in SU or SP (keys are never added)")
            new_doc = copy.deepcopy(doc)
            own = next((o for o in new_doc.get("own_sets", []) if o["mcc_tag"] == tag), None)
            if own is None:
                raise ApiError(409, "the sound has no own take set; its line subtitle decisions decide its text")
            actions = body.get("actions") or []
            user_actions = []
            for a in actions:
                if not isinstance(a, dict) or a.get("action") not in ("approve", "needs_rework") \
                        or a.get("field", "subtitle") != "subtitle":
                    raise ApiError(400, f"unknown action {a}")
                user_actions.append(UserAction(a["action"], tag, "subtitle"))
            kinds = {a.action for a in user_actions}
            if len(kinds) != len(user_actions) or kinds == {"approve", "needs_rework"}:
                raise ApiError(400, "one action at a time")
            today = self.today()
            sub = own.get("subtitle")
            if "needs_rework" in kinds:
                if not sub or sub["status"] != "approved":
                    raise ApiError(400, "the set's subtitle is not approved; nothing to rework")
                sub = dict(sub, status="needs_rework", revision=sub["revision"] + 1, approved_at=None, fingerprint=None)
            new_local, local_changed = copy.deepcopy(local), False
            if "subtitle" in body:
                if body["subtitle"] is None:
                    if sub and sub["status"] == "approved":
                        raise ApiError(409, "the set's subtitle is approved; mark it Needs rework before clearing it")
                    sub = None
                else:
                    sub, local_changed = self._set_subtitle_object(body["subtitle"], sub, doc, local, new_local, today)
            if "approve" in kinds:
                if not sub:
                    raise ApiError(400, "choose the set's subtitle before approving it")
                if sub["status"] == "approved":
                    raise ApiError(400, "the set's subtitle is already approved")
                sub = dict(sub, status="approved", approved_at=today)
                sub["fingerprint"] = own_set_subtitle_fingerprint({"mcc_tag": tag, "subtitle": sub}, self.ce_idx,
                                                                  self.mcc_idx, new_local)
            if sub is None:
                own.pop("subtitle", None)
            else:
                own["subtitle"] = sub
            if new_doc == doc and not local_changed:
                return {"saved": False, "message": "nothing changed", "sound": self.sound(tag, doc, local)}
            try:
                check_transition(doc, new_doc, user_actions)
            except ProtectedError as e:
                raise ApiError(409, str(e))
            errors = self._conversion_errors(new_doc, new_local, {tag})
            if errors:
                raise ApiError(422, "the set's subtitle is not valid yet", errors)
            try:
                if local_changed:
                    save_user_file(self.root / LOCAL, new_local, lsha, "manual-mappings-local-1")
                new_sha = save_mappings(self.root / MAPPINGS, new_doc, sha, user_actions=user_actions)
            except (StaleError, ProtectedError) as e:
                raise ApiError(409, str(e))
            except StoreError as e:
                raise ApiError(422, str(e))
            self.validate_soon()
            return {"saved": True, "sha256": new_sha, "sound": self.sound(tag)}

    def _sound_version(self, doc, local, mcc_tag):
        _lv, r = self._tag_record(mcc_tag)
        return tsc.digest(tsc.sound_inputs(doc, mcc_tag, r, has_subtitle_entry=loc_key(mcc_tag) in self._subtitle_keys(),
                                         ce_idx=self.ce_idx, local=local))

    # ------------------------------------------------------------------ own take sets (docs/custom-take-set-design.md)
    def own_set_on(self, body):
        """body: {mcc_tag, loaded_takes_sha256, clear_mapping_ids: [...], audio_list?: [{ce_line_ref, language}],
        subtitle?: {source, ce_locres?, custom_text?}}. subtitle: the set's ONE subtitle, saved as a DRAFT (sounds with
        a SU/SP entry only, owner 2026-10-19; approve it under Takes of this sound).
        Replaces every take of the sound (the line's 4th audio option): the sound then plays only its added takes,
        plus the recordings in audio_list, added as drafts in the same save (already a take: skipped). At least one
        take must result. An explicit user action that clears the sound's line decisions:
        approved ones are first marked Needs rework (a user action, revision + 1), then every decision of the sound
        is removed. clear_mapping_ids must list exactly the decisions the page showed, or nothing is done."""
        with self._save_lock:
            tag = body.get("mcc_tag")
            self._tag_record(tag)
            doc, sha = self._mappings()
            local, lsha = self._local()
            if body.get("loaded_takes_sha256") != self.takes_version(doc, tag, local):
                raise ApiError(409, "This sound's takes changed elsewhere since this page loaded them; reload")
            if tag in self._own_tags(doc):
                return {"saved": False, "message": "the own take set is already on", "sound": self.sound(tag, doc, local)}
            if tag in {o["mcc_tag"] for o in doc.get("own_sets", [])}:
                raise ApiError(409, "a conversion of this sound is staged; switch it on or cancel it first")
            if body.get("loaded_sound_sha256") != self._sound_version(doc, local, tag):
                raise ApiError(409, "This sound's line decisions changed elsewhere since this page listed them; reload")
            allowed, reason = self.take_rule(tag)
            if not allowed:
                raise ApiError(409, f"an own take set is not allowed here: {reason}")
            items = body.get("audio_list") or []
            if not isinstance(items, list) or len(items) > 50 or not all(isinstance(x, dict) for x in items):
                raise ApiError(400, "audio_list must be at most 50 {ce_line_ref, language} items")
            for ab in items:
                if ab.get("ce_line_ref") not in self.ce_lines:
                    raise ApiError(400, f"unknown CE line {ab.get('ce_line_ref')}")
                if ab.get("language", "Spanish(Mexico)") not in CE_LANGS:
                    raise ApiError(400, f"unknown language {ab.get('language')}")
            existing = [t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag]
            if not existing and not items:
                raise ApiError(400, "choose at least one Campaign Evolved recording to replace the sound's takes with")
            mine = [s for s in doc["slots"] if s["mcc_tag"] == tag]
            if sorted(body.get("clear_mapping_ids") or []) != sorted(s["mapping_id"] for s in mine):
                raise ApiError(409, "the decisions of this sound changed since the page listed them; reload")
            new_local, local_changed, set_sub = copy.deepcopy(local), False, None
            if body.get("subtitle") is not None:
                if not self.has_subtitle_entry(tag):
                    raise ApiError(400, "this sound has no subtitle entry: its set has no subtitle")
                set_sub, local_changed = self._set_subtitle_object(body["subtitle"], None, doc, local, new_local,
                                                                   self.today())
            # One save of two checked steps (mapping_store.save_sequence): 1. Needs rework on every approved
            # decision (the only allowed change to an approved object); 2. remove the sound's decisions and turn the
            # set on. The set's provenance keeps the removed decisions exactly (docs/replacement-set-conversion.md).
            source = self._sound_version(doc, local, tag)
            actions = [UserAction("needs_rework", s["mapping_id"], f) for s in mine for f in ("audio", "subtitle")
                       if s[f]["status"] == "approved"]
            steps = []
            if actions:
                step = copy.deepcopy(doc)
                for s in step["slots"]:
                    for f in ("audio", "subtitle"):
                        if s["mcc_tag"] == tag and s[f]["status"] == "approved":
                            s[f].update(status="needs_rework", revision=s[f]["revision"] + 1, approved_at=None,
                                        fingerprint=None)
                steps.append((step, actions))
            new_doc = copy.deepcopy(steps[-1][0] if steps else doc)
            new_doc["slots"] = [s for s in new_doc["slots"] if s["mcc_tag"] != tag]
            entry = {"mcc_tag": tag, "set_at": self.today(), "provenance": {
                "kind": "replace", "record_id": "rs-" + source[:12], "created_at": self.today(),
                "activated_at": self.today(), "source_version": source,
                "slots": sorted(copy.deepcopy(mine), key=lambda m: m["mapping_id"]),
                "added_takes": sorted(copy.deepcopy(existing), key=lambda t: t["take_id"]),
                "custom_subtitles": tsc.custom_refs(mine, local),
                "takes": [{"take_id": t["take_id"], "origin": "existing", "from_mapping_ids": [],
                           "spec_sha256": tsc.spec_digest(t["audio"])} for t in existing],
                "acknowledged": []}}
            if set_sub:
                entry["subtitle"] = set_sub
            new_doc.setdefault("own_sets", []).append(entry)
            takes = new_doc.setdefault("added_takes", [])
            have = {(x.get("ce_line_ref"), x.get("language")) for t in existing for x in t["audio"]["sources"][:1]}
            added, skipped = [], []
            for ab in items:
                key = (ab["ce_line_ref"], ab.get("language", "Spanish(Mexico)"))
                if key in have:
                    skipped.append(key[0])
                    continue
                have.add(key)
                added.append(self._new_take(tag, takes, len(existing) + len(added) + 1, ab)["take_id"])
            by_id = {t["take_id"]: t for t in takes}
            entry["provenance"]["takes"] += [{"take_id": t, "origin": "created", "from_mapping_ids": [],
                                              "spec_sha256": tsc.spec_digest(by_id[t]["audio"])} for t in added]
            if not takes:
                new_doc.pop("added_takes")
            steps.append((new_doc, []))
            errors = self._conversion_errors(new_doc, new_local, {tag})
            if errors:
                raise ApiError(422, "the result would not be valid; nothing was saved", errors)
            self._save_recovery({entry["provenance"]["record_id"]: tsc.recovery_record(tag, mine, local, self.today())})
            if local_changed:  # the set's custom subtitle text: git-ignored local file, written first (as line saves)
                try:
                    save_user_file(self.root / LOCAL, new_local, lsha, "manual-mappings-local-1")
                except StaleError as e:
                    raise ApiError(409, str(e))
            try:
                new_sha = mapping_store.save_sequence(self.root / MAPPINGS, steps, sha,
                                                      reason=f"take-set:replace:{entry['provenance']['record_id']}")
            except (StaleError, ProtectedError) as e:
                raise ApiError(409, str(e))
            except StoreError as e:
                raise ApiError(422, str(e))
            self.validate_soon()
            return {"saved": True, "sha256": new_sha, "sound": self.sound(tag),
                    "cleared": [s["mapping_id"] for s in mine], "added": added, "skipped": skipped,
                    "reworked": [f"{a.mapping_id}/{a.field}" for a in actions]}

    def own_set_off(self, body):
        """body: {mcc_tag, loaded_takes_sha256}. Back to Spain's takes + added takes. Cleared decisions do not come
        back (the owner chose 'clear', 2026-10-18); the lines start undecided."""
        with self._save_lock:
            tag = body.get("mcc_tag")
            self._tag_record(tag)
            doc, sha = self._mappings()
            local, _ = self._local()
            if body.get("loaded_takes_sha256") != self.takes_version(doc, tag, local):
                raise ApiError(409, "This sound's takes changed elsewhere since this page loaded them; reload")
            if tag not in self._own_tags(doc):
                if tag in {o["mcc_tag"] for o in doc.get("own_sets", [])}:
                    raise ApiError(409, "the conversion of this sound is staged, not on: cancel it instead")
                return {"saved": False, "message": "the own take set is already off", "sound": self.sound(tag, doc, local)}
            # The set's approved subtitle goes with the set: Needs rework first (a user action), same save.
            steps, cur = tsc.rework_set_subtitle_steps(doc, tag)
            new_doc = copy.deepcopy(cur)
            new_doc["own_sets"] = [o for o in new_doc["own_sets"] if o["mcc_tag"] != tag]
            if not new_doc["own_sets"]:
                new_doc.pop("own_sets")  # never stored empty (schema: minItems 1)
            steps.append((new_doc, []))
            try:
                new_sha = mapping_store.save_sequence(self.root / MAPPINGS, steps, sha, reason=f"take-set:off:{tag}")
            except (StaleError, ProtectedError) as e:
                raise ApiError(409, str(e))
            except StoreError as e:
                raise ApiError(422, str(e))
            self.validate_soon()
            return {"saved": True, "sha256": new_sha, "sound": self.sound(tag)}

    # ------------------------------------------------------------------ replacement sets (docs/replacement-set-conversion.md)
    def _records(self):
        out = {}
        for lv, recs in self.levels.items():
            for r in recs:
                out.setdefault(r["mcc_tag"], (lv, r))
        return out

    def _plan(self, doc, local, tag):
        lv, r = self._tag_record(tag)
        keys = self._subtitle_keys()
        return tsc.plan_sound(doc, tag, r, lv, has_subtitle_entry=loc_key(tag) in keys, ce_lines=self.ce_lines,
                              ce_idx=self.ce_idx, mcc_idx=self.mcc_idx, local=local, subtitle_keys=keys)

    def convert_preview(self, mcc_tag):
        """Read-only: what converting this sound's per-take decisions into a replacement set would do."""
        doc, _ = self._mappings()
        local, _ = self._local()
        item = self._plan(doc, local, mcc_tag)
        item["sound_version"] = self._sound_version(doc, local, mcc_tag)
        return item

    def convert_inventory(self, level=None):
        """Read-only: every multi-take sound with a decision, an added take or a set, previewed (level: one level)."""
        doc, sha = self._mappings()
        local, _ = self._local()
        recs = self._records()
        if level and level != "all":
            if level not in self.levels:
                raise ApiError(404, f"unknown level {level}")
            recs = {t: v for t, v in recs.items() if v[0] == level}
        inv = tsc.inventory(doc, recs, subtitle_keys=self._subtitle_keys(), ce_lines=self.ce_lines,
                            ce_idx=self.ce_idx, mcc_idx=self.mcc_idx, local=local)
        for it in inv["sounds"]:  # the list stays light; one sound's preview has the details
            for k in ("build_now", "build_staged", "build_after", "sources", "proposed", "existing_takes"):
                it.pop(k, None)
            it["issues"] = [i for i in it["issues"] if i["severity"] != "info"]
        return {**inv, "sha256": sha}

    def _conversion_errors(self, new_doc, local, tags, mapping_ids=()):
        findings, _ = validate_mappings(new_doc, load_schema(SCHEMA_NAME), ce=self.ce_idx, mcc=self.mcc_idx,
                                        local=local, verifications=self._verifications(),
                                        current_pins=self._current_pins(), file=MAPPINGS,
                                        only_mapping_ids=set(mapping_ids), subtitle_keys=self._subtitle_keys())
        names = {t.rsplit(chr(92), 1)[-1] for t in tags}
        ids = {t["take_id"] for t in new_doc.get("added_takes", []) if t["mcc_tag"] in tags} | set(mapping_ids)
        return [f"{f['code']}: {f['message']}" for f in findings if f["severity"] == "error" and (
            f["code"] == "schema" or any(f"({i})" in f["where"] for i in ids)
            or any(f"({n})" in f["where"] for n in names))]

    def _commit(self, steps, sha, reason, local, tags, mapping_ids=()):
        errors = self._conversion_errors(steps[-1][0], local, tags, mapping_ids)
        if errors:
            raise ApiError(422, "the result would not be valid; nothing was saved", errors)
        try:
            new_sha = mapping_store.save_sequence(self.root / MAPPINGS, steps, sha, reason=reason)
        except (StaleError, ProtectedError) as e:
            raise ApiError(409, str(e))
        except StoreError as e:
            raise ApiError(422, str(e))
        self.validate_soon()
        return new_sha

    def _recovery(self):
        return self._read_document(RECOVERY, {"schema": "take-set-recovery/1", "records": {}})

    def _save_recovery(self, records):
        """Adds recovery records (record id -> snapshot) to the git-ignored recovery document before the decisions
        are saved. Records are only added: an existing one is never changed. None values (nothing local) are
        skipped."""
        records = {k: v for k, v in records.items() if v}
        if not records:
            return
        doc, sha = self._recovery()
        new = copy.deepcopy(doc)
        for k, v in records.items():
            new["records"].setdefault(k, v)
        if new == doc:
            return
        try:
            save_user_file(self.root / RECOVERY, new, sha, "take-set-recovery-1")
        except StaleError as e:
            raise ApiError(409, str(e))
        except StoreError as e:
            raise ApiError(422, str(e))

    def convert_stage(self, body):
        """body: {items: [{mcc_tag, token, acknowledged?: [review codes]}], bulk?: bool, confirm: true}. Stages the
        conversion of each sound in ONE save: new draft takes and a staged set with the record of the decisions; the
        decisions themselves stay in force. Each token must be the current preview's (a change to any line, take,
        set, custom text, catalog fact or eligibility of the sound makes it stale). A bulk stage takes only sounds
        whose preview needs no review. Repeating a stage that was already saved changes nothing."""
        if body.get("confirm") is not True:
            raise ApiError(400, "staging a replacement set needs confirm: true")
        items = body.get("items")
        if not isinstance(items, list) or not items or len(items) > 500:
            raise ApiError(400, "items must list 1 to 500 sounds")
        with self._save_lock:
            doc, sha = self._mappings()
            local, lsha = self._local()
            used = set(mapping_store.used_take_ids(self.root / MAPPINGS))
            new_doc, done, already, problems, tags = doc, [], [], [], set()
            new_local, local_changed = copy.deepcopy(local), False
            for it in items:
                tag = it.get("mcc_tag") if isinstance(it, dict) else None
                if tag in tags:
                    raise ApiError(400, f"{tag} is listed twice")
                self._tag_record(tag)
                tags.add(tag)
                own = next((o for o in doc.get("own_sets", []) if o["mcc_tag"] == tag), None)
                rec_id = "cv-" + str(it.get("token", ""))[:12]
                if own and (own.get("provenance") or {}).get("record_id") == rec_id:
                    already.append(tag)
                    continue
                item = self._plan(doc, local, tag)
                if it.get("token") != item["token"]:
                    problems.append(f"{tag}: changed since the preview; preview it again")
                    continue
                if body.get("bulk") and item["status"] != "ready":
                    problems.append(f"{tag}: {item['status']} (bulk staging takes only sounds that need no review)")
                    continue
                prefill = (item.get("set_subtitle") or {}).get("prefill")
                ref = None
                if prefill and prefill["source"] == "custom":  # the set gets its own copy of the agreed text
                    ref = _next_id("c", self._used_custom_refs(new_doc, new_local))
                try:
                    new_doc, entry = tsc.stage(new_doc, item, today=self.today(), used_take_ids=used,
                                               acknowledged=list(it.get("acknowledged") or []), local=local,
                                               set_subtitle_custom_ref=ref)
                    if ref:
                        new_local["custom_subtitles"][ref] = {"text": prefill["custom_text"], "updated_at": self.today()}
                        local_changed = True
                except tsc.ConversionError as e:
                    problems.append(f"{tag}: {e.message}" + (f" ({', '.join(e.details)})" if e.details else ""))
                    continue
                used |= {t["take_id"] for t in entry["provenance"]["takes"]}
                done.append({"mcc_tag": tag, "record_id": entry["provenance"]["record_id"],
                             "created": [t["take_id"] for t in entry["provenance"]["takes"] if t["origin"] == "created"]})
            if problems:
                raise ApiError(409, "nothing was staged", problems)
            if not done:
                return {"saved": False, "message": "already staged", "already": already, "staged": []}
            errors = self._conversion_errors(new_doc, new_local, tags)
            if errors:
                raise ApiError(422, "the result would not be valid; nothing was saved", errors)
            self._save_recovery({d["record_id"]: tsc.recovery_record(
                d["mcc_tag"], [m for m in doc["slots"] if m["mcc_tag"] == d["mcc_tag"]], local, self.today())
                for d in done})
            if local_changed:
                try:
                    save_user_file(self.root / LOCAL, new_local, lsha, "manual-mappings-local-1")
                except StaleError as e:
                    raise ApiError(409, str(e))
            new_sha = self._commit([(new_doc, [])], sha, "take-set:stage:" + ",".join(d["record_id"] for d in done),
                                   new_local, tags)
        out = {"saved": True, "sha256": new_sha, "staged": done, "already": already}
        if len(items) == 1:
            out["sound"] = self.sound(items[0]["mcc_tag"])
        return out

    def _hypothetical_inserts(self, doc, tag):
        """The build's view of the sound's takes as if its set were switched on (staged takes are never built)."""
        from common.m6_build import plan_inserts
        hyp = copy.deepcopy(tsc.sound_doc(doc, tag))
        for o in hyp.get("own_sets", []):
            o.pop("state", None)
        lv, _r = self._tag_record(tag)
        return [e for e in plan_inserts(hyp, [lv], slot_index=self.slot_index, ce_lines=self.ce_lines,
                                        ce_idx=self.ce_idx, mcc_idx=self.mcc_idx, subtitle_keys=self._subtitle_keys())
                if e["mcc_tag"] == tag]

    def convert_activate(self, body):
        """body: {items: [{mcc_tag, loaded_sound_sha256}], confirm: true}. Switches each staged sound to its
        replacement set, in ONE save: refused unless every take of each set is approved and buildable and the line
        decisions are those recorded at staging; the approved ones are marked Needs rework, then removed (they stay
        in the set's record)."""
        if body.get("confirm") is not True:
            raise ApiError(400, "switching a sound to its replacement set needs confirm: true")
        items = body.get("items")
        if not isinstance(items, list) or not items or len(items) > 500:
            raise ApiError(400, "items must list 1 to 500 sounds")
        with self._save_lock:
            doc, sha = self._mappings()
            local, _ = self._local()
            steps, cur, problems, tags, done = [], doc, [], set(), []
            for it in items:
                tag = it.get("mcc_tag") if isinstance(it, dict) else None
                self._tag_record(tag)
                if tag in tags:
                    raise ApiError(400, f"{tag} is listed twice")
                tags.add(tag)
                if it.get("loaded_sound_sha256") != self._sound_version(doc, local, tag):
                    problems.append(f"{tag}: changed since the page loaded it; reload")
                    continue
                try:
                    more = tsc.activate(cur, tag, today=self.today(), insert_plan=self._hypothetical_inserts(cur, tag),
                                        eligible=self.take_rule(tag), subtitle_problem=tsc.set_subtitle_problem(
                                            cur, tag, has_subtitle_entry=self.has_subtitle_entry(tag),
                                            ce_idx=self.ce_idx, mcc_idx=self.mcc_idx, local=local))
                except tsc.ConversionError as e:
                    problems.append(f"{tag}: {e.message}" + (f" ({'; '.join(e.details)})" if e.details else ""))
                    continue
                steps += more
                cur = more[-1][0]
                done.append({"mcc_tag": tag, "record_id": next(o for o in cur["own_sets"] if o["mcc_tag"] == tag)
                             ["provenance"]["record_id"],
                             "reworked": [f"{a.mapping_id}/{a.field}" for st in more for a in st[1]]})
            if problems:
                raise ApiError(409, "nothing was switched", problems)
            new_sha = self._commit(steps, sha, "take-set:activate:" + ",".join(d["record_id"] for d in done),
                                   local, tags)
        out = {"saved": True, "sha256": new_sha, "switched": done}
        if len(items) == 1:
            out["sound"] = self.sound(items[0]["mcc_tag"])
        return out

    def convert_approvable(self, mcc_tag):
        """Read-only: which takes of the staged conversion "Approve unchanged converted takes" would approve, with their
        source decisions, and which it leaves out and why (take_set_conversion.approvable)."""
        doc, _ = self._mappings()
        local, _ = self._local()
        lv, r = self._tag_record(mcc_tag)
        try:
            out = tsc.approvable(doc, mcc_tag, r, lv, ce_lines=self.ce_lines, ce_idx=self.ce_idx, mcc_idx=self.mcc_idx,
                                 local=local, eligible=self.take_rule(mcc_tag),
                                 has_subtitle_entry=self.has_subtitle_entry(mcc_tag))
        except tsc.ConversionError as e:
            raise ApiError(e.status, e.message, e.details)
        return {**out, "mcc_tag": mcc_tag, "sound_version": self._sound_version(doc, local, mcc_tag)}

    def convert_approve_unchanged(self, body):
        """body: {mcc_tag, loaded_sound_sha256, take_ids, confirm: true}: the owner's explicit approval of exactly the
        takes the page listed as unchanged. Everything is checked again now; if the sound changed or the list of
        approvable takes is not exactly take_ids, nothing is approved. Each take gets a NEW approval: a 'approve'
        user action, today's date and its own fresh added-take fingerprint (never a slot's), in one save whose
        history rows carry the reason take-set:approve-unchanged:<record>."""
        if body.get("confirm") is not True:
            raise ApiError(400, "approving takes needs confirm: true")
        tag = body.get("mcc_tag")
        lv, r = self._tag_record(tag)
        want = body.get("take_ids")
        if not isinstance(want, list) or not want or len(set(want)) != len(want):
            raise ApiError(400, "take_ids must list the takes shown, once each")
        with self._save_lock:
            doc, sha = self._mappings()
            local, _ = self._local()
            if body.get("loaded_sound_sha256") != self._sound_version(doc, local, tag):
                raise ApiError(409, "This sound changed since the list was shown; nothing was approved. Look again.")
            try:
                check = tsc.approvable(doc, tag, r, lv, ce_lines=self.ce_lines, ce_idx=self.ce_idx,
                                       mcc_idx=self.mcc_idx, local=local, eligible=self.take_rule(tag),
                                       has_subtitle_entry=self.has_subtitle_entry(tag))
            except tsc.ConversionError as e:
                raise ApiError(e.status, e.message, e.details)
            now = sorted(t["take_id"] for t in check["included"])
            if sorted(want) != now:
                raise ApiError(409, "the takes that can be approved are not the ones shown; nothing was approved",
                               [f"now approvable: {', '.join(now) or 'none'}"])
            steps = tsc.approve_unchanged(doc, tag, want, today=self.today(),
                                          fingerprint=lambda t: added_take_fingerprint(t, self.ce_idx, self.mcc_idx, local))
            new_sha = self._commit(steps, sha, f"take-set:approve-unchanged:{check['record_id']}", local, {tag})
        return {"saved": True, "sha256": new_sha, "approved": sorted(want), "record_id": check["record_id"],
                "sound": self.sound(tag)}

    def convert_cancel(self, body):
        """body: {mcc_tag, loaded_sound_sha256}. Cancels a staged conversion: the takes it created go (approved ones
        through Needs rework, in the same save) and the line decisions, never touched, stay as they are."""
        tag = body.get("mcc_tag")
        self._tag_record(tag)
        with self._save_lock:
            doc, sha = self._mappings()
            local, _ = self._local()
            if body.get("loaded_sound_sha256") != self._sound_version(doc, local, tag):
                raise ApiError(409, "This sound changed elsewhere since this page loaded it; reload")
            try:
                steps = tsc.cancel(doc, tag)
            except tsc.ConversionError as e:
                raise ApiError(e.status, e.message, e.details)
            rec = next(o for o in doc["own_sets"] if o["mcc_tag"] == tag)["provenance"]["record_id"]
            new_sha = self._commit(steps, sha, f"take-set:cancel:{rec}", local, {tag})
        return {"saved": True, "sha256": new_sha, "sound": self.sound(tag), "record_id": rec,
                "reworked": [f"{a.mapping_id}/{a.field}" for st in steps for a in st[1]]}

    def _revert_plan(self, doc, local, tag, rework_drifted):
        _lv, r = self._tag_record(tag)
        try:
            plan = tsc.revert_plan(doc, tag, local=local, recovery=self._recovery()[0], slot_ids=set(r["slot_ids"]),
                                   ce_idx=self.ce_idx, mcc_idx=self.mcc_idx, rework_drifted=rework_drifted)
        except tsc.ConversionError as e:
            raise ApiError(e.status, e.message, e.details)
        version = self._sound_version(doc, local, tag)
        return plan, version, tsc.plan_token(plan, version)

    def convert_revert_preview(self, mcc_tag, rework_drifted=False):
        """Read-only: what Undo would do for this sound, and every conflict that stops it, before anything changes."""
        doc, _ = self._mappings()
        local, _ = self._local()
        plan, version, token = self._revert_plan(doc, local, mcc_tag, rework_drifted)
        return {**{k: v for k, v in plan.items() if k != "steps"}, "mcc_tag": mcc_tag, "sound_version": version,
                "token": token}

    def convert_revert(self, body):
        """body: {mcc_tag, token, rework_drifted?, confirm: true}, token from convert_revert_preview. Undoes an active
        replacement set that has a record, exactly as previewed (take_set_conversion.revert_plan): the recorded line
        decisions come back with their approvals (store action 'restore'), the takes the record created leave the
        sound (approved ones through Needs rework), earlier takes stay, missing local text is put back from the
        recovery snapshot (newer local text is never overwritten). Refused while any conflict remains, or if
        anything changed since the preview. One save of the decisions, reason take-set:revert:<record>."""
        if body.get("confirm") is not True:
            raise ApiError(400, "undoing a replacement set needs confirm: true")
        tag = body.get("mcc_tag")
        self._tag_record(tag)
        with self._save_lock:
            doc, sha = self._mappings()
            local, lsha = self._local()
            plan, _version, token = self._revert_plan(doc, local, tag, bool(body.get("rework_drifted")))
            if body.get("token") != token:
                raise ApiError(409, "the sound, its record or the local data changed since the preview; nothing was "
                                    "undone. Preview the undo again.")
            if plan["conflicts"]:
                raise ApiError(409, "the undo has conflicts; nothing was changed",
                               [f"{c['code']}: {c['detail']}" for c in plan["conflicts"]])
            restore_local = plan["local_restore"]
            new_local = local
            if restore_local["custom_subtitles"] or restore_local["user_recordings"]:
                new_local = copy.deepcopy(local)
                for k in ("custom_subtitles", "user_recordings"):
                    for ref, v in restore_local[k].items():
                        if ref in new_local[k]:  # checked by the plan; never overwrite
                            raise ApiError(409, f"{ref} reappeared in the local file; nothing was changed")
                        new_local[k][ref] = v
            restored = [m["mapping_id"] for m in plan["steps"][-1][0]["slots"] if m["mcc_tag"] == tag]
            errors = self._conversion_errors(plan["steps"][-1][0], new_local, {tag}, restored)
            if errors:
                raise ApiError(422, "the result would not be valid; nothing was saved", errors)
            if new_local is not local:
                try:
                    save_user_file(self.root / LOCAL, new_local, lsha, "manual-mappings-local-1")
                except StaleError as e:
                    raise ApiError(409, str(e))
            new_sha = self._commit(plan["steps"], sha, f"take-set:revert:{plan['record_id']}", new_local, {tag},
                                   restored)
        return {"saved": True, "sha256": new_sha, "sound": self.sound(tag), "record_id": plan["record_id"],
                "restored": restored, "restore": plan["restore"], "removed_takes": plan["remove_takes"],
                "kept_takes": plan["keep_takes"], "notes": plan["notes"], "local_restored":
                sorted(restore_local["custom_subtitles"]) + sorted(restore_local["user_recordings"]),
                "takes_reworked": [f"{a.mapping_id}/{a.field}" for st in plan["steps"] for a in st[1]
                                   if a.action == "needs_rework"]}

    def _take_edit(self, raw_edit, src, current):
        """The recipe to store for an added take (the same rules as a line's: _normalize_edit)."""
        a = {} if raw_edit is None else {"edit": raw_edit}
        return self._normalize_edit(a, "ce", [src], current)

    def take_save(self, body):
        """body: {mcc_tag, loaded_takes_sha256, take_id? (absent = a new take), audio?: {ce_line_ref, language, edit?},
        radio_effect?: {needed}, notes?, actions?: [{action: approve|needs_rework, field: "audio"}]}."""
        with self._save_lock:
            return self._take_write(body, "save")

    def take_remove(self, body):
        """body: {mcc_tag, take_id, loaded_takes_sha256}. Not while approved (Needs rework first)."""
        with self._save_lock:
            return self._take_write(body, "remove")

    def take_move(self, body):
        """body: {mcc_tag, take_id, direction: -1 | 1, loaded_takes_sha256}: swaps it with its neighbour."""
        with self._save_lock:
            return self._take_write(body, "move")

    def take_add_many(self, body):
        """body: {mcc_tag, loaded_takes_sha256, audio_list: [{ce_line_ref, language}, ...]}: adds each recording as
        a new draft take, in one save (all or nothing). Recordings that are already a take of the sound, or listed
        twice, are skipped and reported. Never approves."""
        with self._save_lock:
            return self._take_write(body, "add_many")

    def take_approve_many(self, body):
        """body: {mcc_tag, loaded_takes_sha256, take_ids: [...], confirm: true}: approves exactly the listed takes
        of the sound (each a draft or needs rework, with a recording), in one save (all or nothing). The owner's
        confirmed action; the page lists the take IDs in its confirmation."""
        with self._save_lock:
            return self._take_write(body, "approve_many")

    def _new_take(self, tag, takes, position, ab):
        """A new draft take of `tag` for the recording ab = {ce_line_ref, language, edit?}; appended to `takes`."""
        ref, lang = ab.get("ce_line_ref"), ab.get("language", "Spanish(Mexico)")
        if ref not in self.ce_lines:
            raise ApiError(400, f"unknown CE line {ref}")
        if lang not in CE_LANGS:
            raise ApiError(400, f"unknown language {lang}")
        used = [t["take_id"] for t in takes] + sorted(mapping_store.used_take_ids(self.root / MAPPINGS))
        src = {"kind": "ce", "ce_line_ref": ref, "language": lang}
        edit = self._take_edit(ab.get("edit"), src, {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0})
        take = {"take_id": _next_id("t", used), "mcc_tag": tag, "position": position,
                "audio": {"status": "draft", "source": "ce", "sources": [src], "edit": edit,
                          "fingerprint": None, "approved_at": None, "revision": 1},
                "radio_effect": {"needed": False, "set_at": None, "revision": 1}, "notes": ""}
        takes.append(take)
        return take

    def _take_write(self, body, op):
        tag = body.get("mcc_tag")
        self._tag_record(tag)  # 404 for an unknown sound
        doc, sha = self._mappings()
        local, _lsha = self._local()
        if body.get("loaded_takes_sha256") != self.takes_version(doc, tag, local):
            raise ApiError(409, "This sound's added takes changed elsewhere since this page loaded them; reload")
        new_doc = copy.deepcopy(doc)
        takes = new_doc.setdefault("added_takes", [])
        mine = sorted((t for t in takes if t["mcc_tag"] == tag), key=lambda t: t["position"])
        tid = body.get("take_id")
        take = next((t for t in mine if t["take_id"] == tid), None) if tid else None
        if tid and take is None:
            raise ApiError(404, f"unknown added take {tid} for this sound")
        user_actions, today = [], self.today()
        added, skipped = [], []
        if op == "add_many":
            items = body.get("audio_list")
            if not isinstance(items, list) or not items:
                raise ApiError(400, "audio_list must name at least one Campaign Evolved recording")
            if len(items) > 50:
                raise ApiError(400, "at most 50 recordings at a time")
            allowed, reason = self.take_rule(tag)
            if not allowed:
                raise ApiError(409, f"added takes are not allowed here: {reason}")
            have = {(s.get("ce_line_ref"), s.get("language")) for t in mine for s in t["audio"]["sources"][:1]}
            for ab in items:
                if not isinstance(ab, dict):
                    raise ApiError(400, "each audio_list item must be {ce_line_ref, language}")
                key = (ab.get("ce_line_ref"), ab.get("language", "Spanish(Mexico)"))
                if key in have:
                    skipped.append(key[0])
                    continue
                have.add(key)
                added.append(self._new_take(tag, takes, len(mine) + len(added) + 1, ab)["take_id"])
        elif op == "approve_many":
            ids = body.get("take_ids")
            if body.get("confirm") is not True:
                raise ApiError(400, "approving several takes needs confirm: true")
            if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
                raise ApiError(400, "take_ids must list at least one take, each once")
            by_id = {t["take_id"]: t for t in mine}
            for i in ids:
                t = by_id.get(i)
                if t is None:
                    raise ApiError(404, f"unknown added take {i} for this sound")
                if t["audio"]["status"] == "approved":
                    raise ApiError(409, f"{i} is already approved")
                if not t["audio"]["sources"]:
                    raise ApiError(400, f"{i} has no recording yet")
            for i in ids:  # in list order, after every check passed
                t = by_id[i]
                user_actions.append(UserAction("approve", i, "audio"))
                t["audio"].update(status="approved", approved_at=today,
                                  fingerprint=added_take_fingerprint(t, self.ce_idx, self.mcc_idx, local))
            added = list(ids)
        elif op == "remove":
            if take["audio"]["status"] == "approved":
                raise ApiError(409, "the take is approved; mark it Needs rework before removing it")
            takes.remove(take)
            for k, t in enumerate(x for x in mine if x is not take):
                t["position"] = k + 1
        elif op == "move":
            d = body.get("direction")
            if d not in (-1, 1):
                raise ApiError(400, "direction must be -1 or 1")
            i = mine.index(take)
            j = i + d
            if not 0 <= j < len(mine):
                raise ApiError(400, "the take is already at that end")
            mine[i]["position"], mine[j]["position"] = mine[j]["position"], mine[i]["position"]
        else:
            if take is None:  # a new take: allowed sounds only
                allowed, reason = self.take_rule(tag)
                if not allowed:
                    raise ApiError(409, f"added takes are not allowed here: {reason}")
                used = [t["take_id"] for t in takes] + sorted(mapping_store.used_take_ids(self.root / MAPPINGS))
                take = {"take_id": _next_id("t", used), "mcc_tag": tag, "position": len(mine) + 1,
                        "audio": {"status": "draft", "source": "ce", "sources": [],
                                  "edit": {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0},
                                  "fingerprint": None, "approved_at": None, "revision": 1},
                        "radio_effect": {"needed": False, "set_at": None, "revision": 1}, "notes": ""}
                takes.append(take)
                if not body.get("audio"):
                    raise ApiError(400, "a new take needs its Campaign Evolved recording (audio.ce_line_ref)")
            actions = body.get("actions") or []
            for a in actions:
                if a.get("action") not in ("approve", "needs_rework") or a.get("field") != "audio":
                    raise ApiError(400, f"unknown action {a}")
                user_actions.append(UserAction(a["action"], take["take_id"], "audio"))
            if any(a.action == "needs_rework" for a in user_actions):
                if take["audio"]["status"] != "approved":
                    raise ApiError(400, "the take is not approved; nothing to rework")
                take["audio"].update(status="needs_rework", revision=take["audio"]["revision"] + 1,
                                     approved_at=None, fingerprint=None)
            if body.get("audio"):
                ab = body["audio"]
                ref, lang = ab.get("ce_line_ref"), ab.get("language", "Spanish(Mexico)")
                if ref not in self.ce_lines:
                    raise ApiError(400, f"unknown CE line {ref}")
                if lang not in CE_LANGS:
                    raise ApiError(400, f"unknown language {lang}")
                src = {"kind": "ce", "ce_line_ref": ref, "language": lang}
                edit = self._take_edit(ab.get("edit"), src, take["audio"]["edit"])
                want = dict(take["audio"], sources=[src], edit=edit)
                if _audio_sem(want) != _audio_sem(take["audio"]):
                    if take["audio"]["status"] == "approved":
                        raise ApiError(409, "the take is approved and read-only; choose 'needs rework' first")
                    take["audio"] = want
            if "radio_effect" in body:
                needed = (body["radio_effect"] or {}).get("needed")
                if not isinstance(needed, bool):
                    raise ApiError(400, "radio_effect.needed must be true or false")
                cur = take["radio_effect"]
                if needed != cur["needed"]:
                    take["radio_effect"] = {"needed": needed, "set_at": today,
                                            "revision": cur["revision"] + (1 if tid else 0)}
            if "notes" in body:
                notes = body["notes"] or ""
                if len(notes) > 2000:
                    raise ApiError(400, "notes are limited to 2000 characters")
                take["notes"] = notes
            if any(a.action == "approve" for a in user_actions):
                if take["audio"]["status"] == "approved":
                    raise ApiError(400, "the take is already approved")
                take["audio"].update(status="approved", approved_at=today,
                                     fingerprint=added_take_fingerprint(take, self.ce_idx, self.mcc_idx, local))
        if not takes:
            new_doc.pop("added_takes")  # never stored empty (schema: minItems 1)
        if new_doc == doc:
            message = "every recording is already a take of this sound" if skipped else "nothing changed"
            return {"saved": False, "message": message, "sound": self.sound(tag, doc, local),
                    **({"added": [], "skipped": skipped} if op == "add_many" else {})}
        try:
            check_transition(doc, new_doc, user_actions)
        except ProtectedError as e:
            raise ApiError(409, str(e))
        findings, _ = validate_mappings(new_doc, load_schema(SCHEMA_NAME), ce=self.ce_idx, mcc=self.mcc_idx,
                                        local=local, verifications=self._verifications(),
                                        current_pins=self._current_pins(), file=MAPPINGS, only_mapping_ids=set(),
                                        subtitle_keys=self._subtitle_keys())
        mine_ids = {t["take_id"] for t in new_doc.get("added_takes", []) if t["mcc_tag"] == tag}
        errors = [f for f in findings if f["severity"] == "error"
                  and (f["code"] == "schema" or any(f"({t})" in f["where"] for t in mine_ids))]
        if errors:
            raise ApiError(422, "the take is not valid yet", [f"{f['code']}: {f['message']}" for f in errors])
        try:
            new_sha = save_mappings(self.root / MAPPINGS, new_doc, sha, user_actions=user_actions)
        except (StaleError, ProtectedError) as e:
            raise ApiError(409, str(e))
        except StoreError as e:
            raise ApiError(422, str(e))
        self.validate_soon()
        if op == "add_many":
            return {"saved": True, "sha256": new_sha, "sound": self.sound(tag), "added": added, "skipped": skipped}
        if op == "approve_many":
            return {"saved": True, "sha256": new_sha, "sound": self.sound(tag), "approved": added}
        return {"saved": True, "sha256": new_sha, "sound": self.sound(tag),
                "take_id": None if op == "remove" else take["take_id"]}

    def _subtitle_keys(self):
        """The SU/SP subtitle keys (computed once per reload; every sound's version reads them)."""
        if getattr(self, "_sub_keys", None) is None or self._sub_keys[0] is not self.loc:
            keys = set()
            for t in ("SU", "SP"):
                if self.loc.get(t) is not None:
                    keys |= set(self.loc[t])
            self._sub_keys = (self.loc, keys)
        return self._sub_keys[1]

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
                prog = level_progress([sid for r in self.levels[level] for sid in r["slot_ids"]], mappings,
                                      slot_tags=_slot_tags(self.levels[level]))
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
        self.validate_soon()
        return {"saved": True, "sha256": new_sha, "entry": entry, "validation": self.last_validation,
                "validation_pending": self.run_validator}

    # ------------------------------------------------------------------ data (JSON <-> SQLite)
    # The database is the source of truth; the JSON file is its export. These are the owner's explicit
    # recovery actions when the file was changed outside the Studio. Nothing here runs on its own.
    def data_status(self):
        return mapping_store.sync_status(self.root / MAPPINGS)

    def data_preview_import(self):
        try:
            return mapping_store.preview_import(self.root / MAPPINGS)
        except StoreError as e:
            raise ApiError(422, str(e))

    def data_import(self, body):
        """body: {file_sha256, db_export_sha256, confirm: true} - the hashes shown in the preview."""
        if body.get("confirm") is not True:
            raise ApiError(400, "an import replaces decisions in the database; it needs confirm: true")
        with self._save_lock:
            try:
                result = mapping_store.import_json(self.root / MAPPINGS, body.get("file_sha256"),
                                                   body.get("db_export_sha256"))
            except StaleError as e:
                raise ApiError(409, str(e))
            except StoreError as e:
                raise ApiError(422, str(e))
        return {**result, "status": self.data_status()}

    def data_export(self, body):
        """body: {file_sha256 (as shown by the status; null when the file is missing), confirm: true}."""
        if body.get("confirm") is not True:
            raise ApiError(400, "an export writes over manual_mappings.json; it needs confirm: true")
        with self._save_lock:
            try:
                sha = mapping_store.export_json(self.root / MAPPINGS, body.get("file_sha256"))
            except StaleError as e:
                raise ApiError(409, str(e))
            except StoreError as e:
                raise ApiError(422, str(e))
        return {"exported_sha256": sha, "status": self.data_status()}

    # ------------------------------------------------------------------ validator
    def validate(self):
        """Run the project validator now (start-up, POST /api/validate). One run at a time."""
        if not self.run_validator:
            return None
        with self._validation_lock:
            if getattr(self, "_validator", None) is None:
                spec = importlib.util.spec_from_file_location(
                    "validate_project", Path(__file__).resolve().parents[1] / "validate" / "validate_project.py")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._validator = mod
            report, drift = self._validator.run(self.root, use_git=(self.root / ".git").exists(),
                                                catalog_cache=self._catalog_cache)
            self.last_validation = {"summary": report["summary"],
                                    "findings": [f for f in report["findings"] if f["severity"] != "info"][:50],
                                    "drift_entries": len(drift["drift"]),
                                    "at": dt.datetime.now().isoformat(timespec="seconds")}
            return self.last_validation

    def validate_soon(self):
        """Refresh the report in the background after a save. Saves in quick succession share one run: a run
        that is queued but not started yet covers every save before it."""
        if not self.run_validator:
            return
        with self._queue_lock:
            if self._validation_queued:
                return
            self._validation_queued = True

        def work():
            with self._queue_lock:
                self._validation_queued = False
            try:
                self.validate()
            except Exception as e:  # noqa: BLE001 - a background report must never take the server down
                self.last_validation = {"error": f"{type(e).__name__}: {e}"}

        threading.Thread(target=work, daemon=True, name="validate-soon").start()
