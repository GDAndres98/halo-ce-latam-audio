"""Campaign Evolved voice-asset catalog: record building and analysis.

Pure logic. Game data is reached only through a *resolver* object, so
tests can drive everything with synthetic fixtures. The real resolver
(scripts/catalog/build_ce_catalog.py) reads the installed containers
read-only. Schema: docs/dialogue-catalog-design.md §3 (`ce-voice-asset/3`).

Rules enforced here:
- every association carries an evidence value (asset_metadata vocabulary);
- a missing link is `unresolved` with a `reason`, never filled from
  another culture or language;
- ambiguities are reported, never resolved by picking one;
- nothing is matched to MCC.

Resolver interface (duck-typed):
    event(game_path)          -> {"vfs_path", "container", "class", "trailing_bytes_unparsed",
                                  "languages": ce_assets.event_languages(...)} | None
    string_table(game_path)   -> {"vfs_path", "container", "class", "namespace"?, "keys"?} | None
    locres(culture)           -> {"path", "table": {ns: {key: {"text", "source_hash"}}}} | None
    media(language, path)     -> {"container", "vfs_path", "wem_bytes", "wem_sha256"} | None
    has_language(language)    -> bool   (a language pak exists)
    package(vfs_path)         -> {"vfs_path", "class"} | None
"""
import json
import re
from collections import Counter, defaultdict

from .asset_metadata import EXPLICIT, EXPLICIT_INDEX, UNRESOLVED, derived, fnv1_32
from .ce_assets import import_target, soft_path, unwrap

RECORD_SCHEMA = "ce-voice-asset/3"
COVERAGE_SCHEMA = "ce-coverage-report/1"
UNRESOLVED_SCHEMA = "ce-unresolved-report/1"

AUDIO_LANGUAGES = ("Spanish(Mexico)", "English(US)", "Spanish(Spain)")
SUBTITLE_CULTURES = ("es-MX", "en", "es-ES")
LIPSYNC_CULTURES = ("es-MX", "es-ES")
SUPPORTED_CLASSES = ("HaloAudioVoiceVariations", "HaloAudioSound")
FAMILY_ORDER = {"scripted": 0, "cinematic": 1, "systemic": 2}

_FOLDER_RE = re.compile(r"^Meteorite/Content/Audio/(?P<family>[^/]+)/(?P<folder>[^/]+)/(?P<name>[^/]+)$", re.I)
_MISSION_RE = re.compile(r"^vo_(?:scr|cin)_(m\d+)", re.I)


def game_path_to_vfs(game_path):
    p = game_path.split(".")[0]
    if not p.startswith("/Game/"):
        raise ValueError(f"not a /Game path: {game_path}")
    return "Meteorite/Content/" + p[len("/Game/"):] + ".uasset"


def classify(vfs_path):
    """Family / folder / mission / path flags, all from the VFS path (derived, never from content)."""
    m = _FOLDER_RE.match(vfs_path)
    if not m:
        return {"family": None, "folder": None, "mission": None, "asset_name": vfs_path.rsplit("/", 1)[-1],
                "flags": []}
    folder = m["folder"]
    mm = _MISSION_RE.match(folder)
    flags = []
    if folder.lower().endswith("_lipsync"):
        flags.append("lipsync_variant_folder")
    low = vfs_path.lower()
    if "temp_mocap" in low or "/metz_" in low:
        flags.append("temp_asset")
    return {"family": m["family"].lower(), "folder": folder, "mission": mm[1].upper() if mm else None,
            "asset_name": m["name"].rsplit(".", 1)[0], "flags": flags}


def _voice_entries(cls, props):
    """Normalize both known voice-asset shapes to [(path_label, entry_dict)]."""
    if cls == "HaloAudioVoiceVariations":
        return [(f"VoiceEvents[{i}]", ve) for i, ve in enumerate(props.get("VoiceEvents") or [])]
    if cls == "HaloAudioSound":
        return [("PlayEvent", {"VoiceEvent": props.get("PlayEvent"), "Transcription": props.get("TranscriptionLine"),
                               "LipSync": None})]
    raise ValueError(f"unsupported voice asset class {cls}")


def _link_event(entry, ve, resolver, languages, flags, line_key):
    event_path = import_target(ve.get("VoiceEvent"))
    ev = {"package": event_path, "evidence": EXPLICIT if event_path else UNRESOLVED}
    entry["event"] = ev
    entry["media"] = {}
    if not event_path:
        ev["reason"] = "VoiceEvent is not an import reference"
        for lang in languages:
            entry["media"][lang] = {"evidence": UNRESOLVED, "reason": "no event"}
        return
    folder_name, event_name = event_path.rsplit("/", 2)[-2:]
    if "/test/" in event_path.lower():
        flags.add("test_event")
    elif event_name.lower() != f"play_{folder_name}".lower():
        flags.add("event_package_folder_mismatch")
    if line_key and event_name.lower() != f"play_{line_key}".lower():
        flags.add("event_name_mismatch")
    try:
        info = resolver.event(event_path)
    except Exception as e:  # parser stop: record, don't guess
        info, err = None, f"{type(e).__name__}: {e}"
    else:
        err = "event package not found in any container"
    if not info:
        ev.update(evidence=UNRESOLVED, reason=err)
        for lang in languages:
            entry["media"][lang] = {"evidence": UNRESOLVED, "reason": "event unreadable"}
        return
    langs = info["languages"]
    ids = sorted({v["event_id"] for v in langs.values() if v["event_id"] is not None})
    ev.update({k: info[k] for k in ("vfs_path", "container", "class", "trailing_bytes_unparsed")})
    ev["event_id"] = ids[0] if len(ids) == 1 else None
    ev["event_ids_per_language_consistent"] = len(ids) <= 1
    if len(ids) > 1:
        flags.add("event_id_inconsistent")
    if ev["event_id"] is not None:
        ev["event_id_matches_fnv1_of_name"] = ev["event_id"] == fnv1_32(event_name)
        ev["event_id_name_check_evidence"] = derived("wwise_shortid_fnv1")
    entry["available_languages"] = sorted(langs)
    for lang in languages:
        v = langs.get(lang)
        if v is None:
            entry["media"][lang] = {"evidence": UNRESOLVED, "reason": "language not in EventLanguageMap"}
            continue
        media = [dict(m) for m in v["media"]]
        out = {"evidence": EXPLICIT, "source": "AkAudioEvent.EventCookedData.EventLanguageMap",
               "media": media, "soundbanks": v["soundbanks"]}
        if not media:
            out.update(evidence=UNRESOLVED, reason="language present but lists no media")
        if len(media) > 1:
            flags.add(f"multi_media:{lang}")
        missing = 0
        for m in media:
            hit = resolver.media(lang, m["media_path"]) if resolver.has_language(lang) else None
            if hit:
                m.update(hit)
                m["exists_evidence"] = EXPLICIT_INDEX
            else:
                missing += 1
                m["exists_evidence"] = UNRESOLVED
                m["reason"] = ("media path not in language pak index" if resolver.has_language(lang)
                               else "no pak found for language")
            m["duration_s"] = None  # filled only by on-demand decoding (M1b), never estimated
        if missing:
            out.update(evidence=UNRESOLVED, reason=f"{missing} of {len(media)} media not in the language pak")
        entry["media"][lang] = out


def _link_subtitles(entry, ve, resolver, cultures, flags, ctx_folder):
    tr = ve.get("Transcription") or {}
    table_path = import_target(tr.get("StringTable"))
    line_key = unwrap(tr.get("LineKey"))
    metadata = {kv["key"]: kv["value"] for kv in (unwrap(tr.get("MetaData")) or [])}
    t = {"type": unwrap(tr.get("Type")), "string_table": table_path, "line_key": line_key, "metadata": metadata,
         "evidence": EXPLICIT if table_path and line_key else UNRESOLVED}
    entry["transcription"] = t
    entry["subtitles"] = {}
    if not (table_path and line_key):
        t["reason"] = "no StringTable import" if line_key else "no LineKey"
        flags.add("no_transcription")
        for c in cultures:
            entry["subtitles"][c] = {"evidence": UNRESOLVED, "reason": "no transcription reference"}
        return line_key
    if t["type"] != "Subtitle":
        flags.add(f"transcription_type:{t['type']}")
    if ctx_folder and table_path.rsplit("/", 1)[-1].lower() != ctx_folder.lower().removesuffix("_lipsync"):
        flags.add("foreign_string_table")
    st = resolver.string_table(table_path)
    if not st or st.get("class") != "StringTable":
        reason = "string table not found" if not st else f"import is a {st.get('class')}, not a StringTable"
        entry["string_table"] = {"evidence": UNRESOLVED, "reason": reason}
        for c in cultures:
            entry["subtitles"][c] = {"evidence": UNRESOLVED, "reason": reason}
        return line_key
    ns = st["namespace"]
    present = line_key in st["keys"]
    entry["string_table"] = {"vfs_path": st["vfs_path"], "container": st["container"], "namespace": ns,
                             "entry_count": len(st["keys"]), "key_present": present,
                             "evidence": EXPLICIT if present else UNRESOLVED}
    if not present:
        entry["string_table"]["reason"] = "LineKey not in StringTable keys"
        flags.add("key_not_in_string_table")
    for c in cultures:
        loc = resolver.locres(c)
        if not loc:
            entry["subtitles"][c] = {"evidence": UNRESOLVED, "reason": f"no Subtitles.locres for {c}"}
            continue
        hit = loc["table"].get(ns, {}).get(line_key)
        sub = {"culture": c, "locres": loc["path"], "namespace": ns, "key": line_key,
               "evidence": EXPLICIT if hit else UNRESOLVED}
        if hit:
            sub["text"] = hit["text"]
            sub["source_hash"] = hit.get("source_hash")
        else:
            sub["reason"] = f"(namespace, key) not in {c} locres"  # no fallback to another culture
        entry["subtitles"][c] = sub
    return line_key


def _link_lipsync(entry, ve, resolver, flags):
    lip = soft_path(ve.get("LipSync"))
    if not lip:
        entry["lipsync"] = {"soft_path": None, "evidence": UNRESOLVED, "reason": "LipSync is a null soft path"}
        flags.add("no_lipsync")
        return
    vfs = game_path_to_vfs(lip)
    pkg = resolver.package(vfs)
    entry["lipsync"] = {"soft_path": lip, "evidence": EXPLICIT, "vfs_path": pkg["vfs_path"] if pkg else None,
                        "class": pkg["class"] if pkg else None,
                        "exists_evidence": EXPLICIT_INDEX if pkg else UNRESOLVED, "localized_variants": {}}
    for c in LIPSYNC_CULTURES:
        l10n = vfs.replace("Meteorite/Content/", f"Meteorite/Content/L10N/{c}/", 1)
        hit = resolver.package(l10n)
        entry["lipsync"]["localized_variants"][c] = {
            "vfs_path": hit["vfs_path"] if hit else None,
            "evidence": derived("ue_l10n_folder_convention") if hit else UNRESOLVED}


def build_record(asset, resolver, source_build, languages=AUDIO_LANGUAGES, cultures=SUBTITLE_CULTURES):
    """asset: {"vfs_path", "container", "package_name", "class", "props", "locations"}."""
    c = classify(asset["vfs_path"])
    flags = set(c["flags"])
    rec = {
        "schema": RECORD_SCHEMA,
        "record_id": c["asset_name"].lower(),
        "ce_line_key": None,
        "display_key": None,
        "asset_name": c["asset_name"],
        "family": c["family"], "family_evidence": derived("vfs_folder"),
        "mission": c["mission"], "mission_evidence": derived("vfs_folder_name") if c["mission"] else UNRESOLVED,
        "folder": c["folder"],
        "voice_asset": {"vfs_path": asset["vfs_path"], "container": asset["container"],
                        "package_name": asset["package_name"], "class": asset["class"],
                        "class_evidence": EXPLICIT,
                        "category": import_target(asset["props"].get("Category")),
                        "container_count": asset.get("locations", 1)},
        "entries": [],
        "flags": [],
        "ambiguities": [],
        "source_build": source_build,
    }
    entries = _voice_entries(asset["class"], asset["props"])
    if len(entries) != 1:
        flags.add("multi_variation" if entries else "no_voice_entries")
    line_keys = []
    for n, (label, ve) in enumerate(entries):
        entry = {"index": n, "property": label, "ce_line_ref": f"{rec['record_id']}#{n}"}
        rec["entries"].append(entry)
        line_key = _link_subtitles(entry, ve, resolver, cultures, flags, c["folder"])
        line_keys.append(line_key)
        _link_event(entry, ve, resolver, languages, flags, line_key)
        _link_lipsync(entry, ve, resolver, flags)
    key = next((k for k in line_keys if k), None)
    rec["display_key"] = key or c["asset_name"]
    rec["ce_line_key"] = rec["display_key"].lower()
    rec["ce_line_key_evidence"] = EXPLICIT if key else derived("asset_name")
    if key and key.lower() != c["asset_name"].lower():
        flags.add("line_key_differs_from_asset_name")
    if c["family"] == "scripted" and key:
        parts = key.lower().split("_")
        if len(parts) >= 5:
            tag = f"Meteorite/Content/Tags/sound/scripted/{c['folder'].removesuffix('_lipsync')}/" \
                  f"{'_'.join(parts[2:])}-sound.uasset"
            hit = resolver.package(tag)
            rec["blam_sound_tag"] = {"vfs_path": hit["vfs_path"] if hit else None,
                                     "evidence": derived("name_convention") if hit else UNRESOLVED,
                                     "note": "not referenced by the voice asset; relationship by name only"}
    if asset.get("locations", 1) > 1:
        flags.add("in_multiple_containers")
    rec["flags"] = sorted(flags)
    return rec


# --------------------------------------------------------------------------- analysis
def _add(rec_by_id, rid, code):
    a = rec_by_id[rid]["ambiguities"]
    if code not in a:
        a.append(code)
        a.sort()


def analyze(records, *, string_tables, locres_keys, event_inventory, voice_inventory, skipped):
    """Cross-record checks. Mutates records[*]["ambiguities"]; returns (coverage, unresolved_report).

    string_tables:   {game_path: {"namespace", "keys"}} for every table referenced or expected
    locres_keys:     {culture: {namespace: set(keys)}} restricted to those namespaces
    event_inventory: sorted VFS paths of event packages under the mission's event folders
    voice_inventory: {folder: [vfs paths]} every file found in the voice folders
    skipped:         [{"vfs_path", "reason"}]
    """
    by_id = {r["record_id"]: r for r in records}
    ambiguities = []

    def group(key_fn, code, what):
        g = defaultdict(list)
        for r in records:
            for k in key_fn(r):
                if k is not None:
                    g[k].append(r["record_id"])
        for k, ids in sorted(g.items(), key=lambda kv: str(kv[0])):
            ids = sorted(set(ids))
            if len(ids) > 1:
                ambiguities.append({"code": code, what: k if not isinstance(k, tuple) else list(k), "records": ids})
                for rid in ids:
                    _add(by_id, rid, code)

    group(lambda r: [r["ce_line_key"]], "duplicate_ce_line_key", "ce_line_key")
    group(lambda r: [(e["transcription"].get("string_table"), e["transcription"].get("line_key"))
                     for e in r["entries"] if e["transcription"].get("line_key")],
          "duplicate_subtitle_reference", "string_table_and_key")
    group(lambda r: [e["event"].get("package") for e in r["entries"]], "shared_event", "event")
    group(lambda r: [e["event"].get("event_id") for e in r["entries"]], "shared_event_id", "event_id")
    group(lambda r: [(lang, m["media_id"]) for e in r["entries"] for lang, v in e["media"].items()
                     for m in v.get("media", [])], "shared_media_id", "language_and_media_id")
    for r in records:
        if "event_id_inconsistent" in r["flags"]:
            ambiguities.append({"code": "event_id_inconsistent", "records": [r["record_id"]]})
            _add(by_id, r["record_id"], "event_id_inconsistent")
        if "in_multiple_containers" in r["flags"]:
            ambiguities.append({"code": "in_multiple_containers", "records": [r["record_id"]]})
            _add(by_id, r["record_id"], "in_multiple_containers")

    # String-table key accounting: referenced vs orphaned, and case collisions.
    referenced = defaultdict(set)
    for r in records:
        for e in r["entries"]:
            t = e["transcription"]
            if t.get("string_table") and t.get("line_key"):
                referenced[t["string_table"]].add(t["line_key"])
    tables_report = []
    for path in sorted(string_tables):
        st = string_tables[path]
        keys = st.get("keys") or []
        ns = st.get("namespace")
        lower = Counter(k.lower() for k in keys)
        collisions = sorted(k for k in keys if lower[k.lower()] > 1)
        if collisions:
            ambiguities.append({"code": "string_table_key_case_collision", "string_table": path, "keys": collisions})
        per_culture = {}
        for c, nsmap in sorted(locres_keys.items()):
            lk = nsmap.get(ns, set())
            per_culture[c] = {"keys_in_locres": len(lk),
                              "table_keys_missing_in_locres": sorted(set(keys) - lk),
                              "locres_keys_not_in_table": sorted(lk - set(keys))}
        tables_report.append({
            "string_table": path, "namespace": ns, "key_count": len(keys),
            "referenced_count": len(referenced[path] & set(keys)),
            "orphaned_keys": sorted(set(keys) - referenced[path]),
            "referenced_keys_not_in_table": sorted(referenced[path] - set(keys)),
            "locres": per_culture,
        })

    referenced_events = {game_path_to_vfs(e["event"]["package"]).lower()
                         for r in records for e in r["entries"] if e["event"].get("package")}
    orphan_events = [p for p in event_inventory if p.lower() not in referenced_events]

    # Unresolved items, one row per unresolved field.
    items = []
    for r in records:
        for e in r["entries"]:
            ref = e["ce_line_ref"]
            for field in ("event", "transcription", "string_table", "lipsync"):
                v = e.get(field)
                if v and v.get("evidence") == UNRESOLVED:
                    items.append({"ce_line_ref": ref, "field": field, "reason": v.get("reason")})
            for lang, v in sorted(e["media"].items()):
                if v.get("evidence") == UNRESOLVED:
                    items.append({"ce_line_ref": ref, "field": f"media[{lang}]", "reason": v.get("reason")})
            for c, v in sorted(e["subtitles"].items()):
                if v.get("evidence") == UNRESOLVED:
                    items.append({"ce_line_ref": ref, "field": f"subtitles[{c}]", "reason": v.get("reason")})

    # Coverage.
    def ev_counts(fn):
        cnt = defaultdict(Counter)
        for r in records:
            for e in r["entries"]:
                for k, v in fn(e).items():
                    cnt[k][v.get("evidence")] += 1
        return {k: dict(sorted(v.items())) for k, v in sorted(cnt.items())}

    files_seen = sum(len(v) for v in voice_inventory.values())
    coverage = {
        "schema": COVERAGE_SCHEMA,
        "voice_folders": {f: len(v) for f, v in sorted(voice_inventory.items())},
        "files_seen": files_seen,
        "records": len(records),
        "skipped": len(skipped),
        "accounted_for": len(records) + len(skipped) == files_seen,
        "entries": sum(len(r["entries"]) for r in records),
        "by_family": dict(sorted(Counter(r["family"] for r in records).items())),
        "by_folder": dict(sorted(Counter(r["folder"] for r in records).items())),
        "by_class": dict(sorted(Counter(r["voice_asset"]["class"] for r in records).items())),
        "media_evidence": ev_counts(lambda e: e["media"]),
        "subtitle_evidence": ev_counts(lambda e: e["subtitles"]),
        "event_evidence": ev_counts(lambda e: {"event": e["event"]}),
        "lipsync_evidence": ev_counts(lambda e: {"lipsync": e["lipsync"]}),
        "flags": dict(sorted(Counter(f for r in records for f in r["flags"]).items())),
        "ambiguities": dict(sorted(Counter(a["code"] for a in ambiguities).items())),
        "string_tables": [{k: t[k] for k in ("string_table", "namespace", "key_count", "referenced_count")}
                          | {"orphaned": len(t["orphaned_keys"])} for t in tables_report],
        "events_in_mission_folders": len(event_inventory),
        "orphan_events": len(orphan_events),
        "unresolved_items": len(items),
    }
    report = {
        "schema": UNRESOLVED_SCHEMA,
        "unresolved": items,
        "ambiguities": ambiguities,
        "string_tables": tables_report,
        "orphan_events": orphan_events,
        "skipped": sorted(skipped, key=lambda s: s["vfs_path"].lower()),
    }
    return coverage, report


def sort_records(records):
    return sorted(records, key=lambda r: (FAMILY_ORDER.get(r["family"], 9), r["voice_asset"]["vfs_path"].lower()))


def dumps_jsonl(records):
    """Deterministic JSONL: fixed record order, sorted keys, no timestamps."""
    return "".join(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for r in sort_records(records))


def dumps_json(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
