"""Read-only semantic validation of catalogs and user-owned files (milestone M3).

Pure functions over already-loaded JSON. The CLI
(scripts/validate/validate_project.py) does the I/O. Nothing here writes,
fixes or deletes anything: problems become findings, and fingerprint
mismatches become drift entries. Approved decisions are never touched.

Finding: {"severity": "error"|"warning"|"info", "code", "file", "where", "message"}.
"""
import hashlib
import json
import re

from . import audio_edit
from .jsonschema_lite import validate as schema_validate
from .mapping_store import comparable
from .mcc_catalog import parse_slot_id, slot_id_for

ABS_PATH = re.compile(r"(^|[\s\"'(])([A-Za-z]:[\\/]|/(home|Users|mnt|media)/|\\\\)")
TEST_EVENT_FLAG = "test_event"


def finding(severity, code, file, where, message):
    return {"severity": severity, "code": code, "file": file, "where": where, "message": message}


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- catalog indexes
def build_ce_index(records):
    """ce_line_ref -> facts needed by validators and fingerprints."""
    idx = {}
    for r in records:
        for e in r["entries"]:
            media = {}
            for lang, v in e["media"].items():
                media[lang] = {"evidence": v.get("evidence"),
                               "media": [{"media_id": m["media_id"], "wem_sha256": m.get("wem_sha256")}
                                         for m in v.get("media", [])]}
            subs = {c: {k: v.get(k) for k in ("evidence", "namespace", "key", "source_hash")}
                    for c, v in e["subtitles"].items()}
            idx[e["ce_line_ref"]] = {"record_id": r["record_id"], "mission": r.get("mission"),
                                     "flags": r["flags"], "media": media, "subtitles": subs,
                                     "source_build": r["source_build"].get("exe_file_version")}
    return idx


def build_mcc_index(records):
    """slot_id -> facts; also '#tags' -> {mcc_tag: record summary} for English look-ups."""
    slots, tags = {}, {}
    for r in records:
        tags[r["mcc_tag"]] = {"level": r["level"], "english": [
            {"index": s["index"], "data_sha256": s["data_sha256"]} for s in r["samples"]["english"]]}
        for s in r["samples"]["spanish"]:
            slots[s["slot_id"]] = {"mcc_tag": r["mcc_tag"], "level": r["level"], "index": s["index"],
                                   "name_in_bank": s["name_in_bank"], "data_sha256": s["data_sha256"],
                                   "spanish_fsb_sha256": r["source"]["spanish_fsb_sha256"]}
    return {"slots": slots, "tags": tags}


# --------------------------------------------------------------------------- fingerprints
def mcc_fingerprint(slot_id, mcc):
    s = mcc["slots"].get(slot_id)
    return None if not s else {"slot_id": slot_id, "index": s["index"], "data_sha256": s["data_sha256"]}


def audio_fingerprint(slot, ce, mcc, local=None):
    """Current fingerprint of an audio decision (what an approval pins)."""
    out = {"mcc": mcc_fingerprint(slot["slot_id"], mcc), "sources": []}
    for src in slot["audio"]["sources"]:
        if src["kind"] == "ce":
            m = (ce.get(src["ce_line_ref"]) or {}).get("media", {}).get(src["language"], {})
            out["sources"].append({"kind": "ce", "ce_line_ref": src["ce_line_ref"], "language": src["language"],
                                   "media": m.get("media", [])})
        else:
            rec = ((local or {}).get("user_recordings") or {}).get(src["ref"]) or {}
            out["sources"].append({"kind": "user_recording", "ref": src["ref"], "sha256": rec.get("sha256")})
    return out


def subtitle_fingerprint(slot, ce, mcc, local=None):
    sub = slot["subtitle"]
    out = {"mcc": mcc_fingerprint(slot["slot_id"], mcc), "source": sub["source"]}
    if sub["source"] == "ce_locres" and sub["ce_locres"]:
        s = (ce.get(sub["ce_locres"]["ce_line_ref"]) or {}).get("subtitles", {}).get(sub["ce_locres"]["culture"], {})
        out["ce_locres"] = {**sub["ce_locres"], "namespace": s.get("namespace"), "key": s.get("key"),
                            "source_hash": s.get("source_hash")}
    if sub["source"] == "custom" and sub["custom_ref"]:
        t = (((local or {}).get("custom_subtitles") or {}).get(sub["custom_ref"]) or {}).get("text")
        out["custom"] = {"custom_ref": sub["custom_ref"], "text_sha256": sha256_text(t) if t is not None else None}
    return out


# --------------------------------------------------------------------------- catalogs
def validate_catalog(name, records, schema, expected_schema_id, build=None, file_sha256=None):
    """Schema, separation, uniqueness and provenance of one generated catalog."""
    out, seen = [], {}
    for i, r in enumerate(records):
        if r.get("schema") != expected_schema_id:
            out.append(finding("error", "catalog_separation", name, f"line {i + 1}",
                               f"record schema {r.get('schema')!r} does not belong in this catalog "
                               f"(expected {expected_schema_id})"))
            continue
        for e in schema_validate(r, schema)[:5]:
            out.append(finding("error", "schema", name, f"line {i + 1}", e))
        keys = ([e["ce_line_ref"] for e in r.get("entries", [])] if expected_schema_id.startswith("ce-")
                else r.get("slot_ids", []))
        if not expected_schema_id.startswith("ce-"):
            for smp in (r.get("samples") or {}).get("spanish", []):
                sid = smp.get("slot_id", "")
                if slot_id_for(smp.get("name_in_bank", ""), smp.get("name_occurrence_in_bank", -1)) != sid:
                    out.append(finding("error", "slot_id_not_canonical", name, f"line {i + 1}", sid))
                else:
                    try:
                        back = parse_slot_id(sid)
                    except ValueError:
                        back = None
                    if back != (smp["name_in_bank"], smp["name_occurrence_in_bank"]):
                        out.append(finding("error", "slot_id_round_trip", name, f"line {i + 1}", sid))
        for k in keys:
            if k in seen:
                out.append(finding("error", "duplicate_id", name, f"line {i + 1}", f"{k} also on line {seen[k]}"))
            seen[k] = i + 1
    if build is not None:
        cat = next((c for c in (build.get("catalogs") or {}).values() if c.get("path", "").endswith(name)), None)
        if not cat:
            out.append(finding("warning", "provenance_missing", name, "build.json", "catalog not listed in build.json"))
        elif file_sha256 and cat.get("sha256") != file_sha256:
            out.append(finding("error", "catalog_changed_since_build", name, "build.json",
                               "file sha256 differs from build.json; rebuild instead of editing catalogs"))
        if expected_schema_id.startswith("ce-"):
            want = (build.get("source_build") or {}).get("exe_file_version")
            bad = sum(1 for r in records if r.get("source_build", {}).get("exe_file_version") != want)
        else:
            want = ((build.get("files") or {}).get("spanish.fsb") or {}).get("sha256")
            bad = sum(1 for r in records if r.get("source", {}).get("spanish_fsb_sha256") != want)
        if bad:
            out.append(finding("error", "provenance_mismatch", name, "records",
                               f"{bad} records were built from a different source than build.json"))
    return out


def compare_slot_identity(old_records, new_records):
    """ID-change guard for MCC rebuilds: slot ids must never be silently renumbered.

    -> list of {"change": removed|added|moved|renamed, ...}. 'moved' = same slot_id, different sample;
    'renamed' = same sample bytes now under another slot_id.
    """
    def table(records):
        return {s["slot_id"]: (s["index"], s["data_sha256"], r["mcc_tag"])
                for r in records for s in r["samples"]["spanish"]}
    old, new = table(old_records), table(new_records)
    by_data_new = {}
    for sid, (_i, d, _t) in new.items():
        by_data_new.setdefault(d, []).append(sid)
    changes = []
    for sid in sorted(old):
        if sid not in new:
            moved_to = sorted(x for x in by_data_new.get(old[sid][1], []) if x not in old)
            changes.append({"change": "renamed" if moved_to else "removed", "slot_id": sid, "new_slot_ids": moved_to,
                            "mcc_tag": old[sid][2]})
        elif new[sid][:2] != old[sid][:2]:
            changes.append({"change": "moved", "slot_id": sid, "old": list(old[sid][:2]), "new": list(new[sid][:2]),
                            "mcc_tag": old[sid][2]})
    renamed_targets = {x for c in changes for x in c.get("new_slot_ids", [])}
    for sid in sorted(set(new) - set(old) - renamed_targets):
        changes.append({"change": "added", "slot_id": sid, "mcc_tag": new[sid][2]})
    return changes


# --------------------------------------------------------------------------- mappings
def validate_mappings(doc, schema, *, ce, mcc, local, verifications, current_pins, file="manual_mappings.json",
                      only_mapping_ids=None):
    """-> (findings, drift). ce/mcc are indexes; local may be None; current_pins may hold None values.
    only_mapping_ids: check just these slots in depth (a save checks the slot it changes; the others are
    unchanged and were checked when they were saved). Duplicate ids are still looked for across all slots."""
    from .mapping_store import schema_errors
    out, drift = [], []
    errs = schema_errors(doc, schema, only_mapping_ids)
    out += [finding("error", "schema", file, e.split(":")[0], e) for e in errs]
    if errs:
        return out, drift
    have_ce, have_mcc = bool(ce), bool(mcc["slots"])
    ver_ids = {v["id"]: v for v in (verifications or {}).get("verifications", [])}

    for k, cur in current_pins.items():
        pin = doc["pins"].get(k)
        if pin is None and doc["slots"]:
            out.append(finding("warning", "pin_unset", file, f"/pins/{k}", f"pin not set (current: {cur})"))
        elif pin is not None and cur is not None and pin != cur:
            out.append(finding("warning", "pin_mismatch", file, f"/pins/{k}", f"pinned {pin}, current {cur}"))
            drift.append({"kind": "pin", "pin": k, "pinned": pin, "current": cur})

    ids, slots_seen = {}, {}
    for i, s in enumerate(doc["slots"]):
        w = f"/slots/{i} ({s['mapping_id']})"
        if s["mapping_id"] in ids:
            out.append(finding("error", "duplicate_mapping_id", file, w, f"also at /slots/{ids[s['mapping_id']]}"))
        ids.setdefault(s["mapping_id"], i)
        if s["slot_id"] in slots_seen:
            out.append(finding("error", "conflicting_slot_decisions", file, w,
                               f"{s['slot_id']} is also mapped by {slots_seen[s['slot_id']]}"))
        slots_seen.setdefault(s["slot_id"], s["mapping_id"])
        if only_mapping_ids is not None and s["mapping_id"] not in only_mapping_ids:
            continue
        radio = s.get("radio_effect") or {}
        if radio.get("needed") and s["audio"]["source"] in ("keep_original", "mute"):
            out.append(finding("error", "radio_effect_without_selected_audio", file, w + "/radio_effect",
                               "the 'needs radio effect' flag applies to selected CE audio, not to kept Spain "
                               "audio or a muted line"))
        if s["audio"]["source"] == "mute":  # owner's explicit "Mute / No replacement" (docs/mute-language-permutations.md)
            if s["match"]["status"] != "no_equivalent":
                out.append(finding("error", "mute_requires_no_equivalent", file, w + "/audio",
                                   f"a muted line must be marked 'no equivalent' (match.status={s['match']['status']})"))
            if not (s["audio"].get("mute_reason") or "").strip():
                out.append(finding("error", "mute_without_reason", file, w + "/audio",
                                   "say why the line is muted"))
            if s["subtitle"]["source"] in ("ce_locres", "custom"):
                out.append(finding("info", "muted_line_with_subtitle_text", file, w + "/subtitle",
                                   "the audio is muted but a subtitle text is chosen; it will still be shown"))
        if (s.get("different_but_fits") or {}).get("marked") and not s["match"]["ce_line_refs"]:
            out.append(finding("error", "different_but_fits_without_match", file, w + "/different_but_fits",
                               "'different dialogue, fits the scene' needs at least one matched CE line"))
        if ABS_PATH.search(s["notes"]):
            out.append(finding("error", "local_path_in_committed_file", file, w + "/notes",
                               "absolute paths belong in manual_mappings.local.json"))

        slot = mcc["slots"].get(s["slot_id"])
        if not slot:
            out.append(finding("error" if have_mcc else "warning", "unknown_slot_id", file, w,
                               f"{s['slot_id']} not in any loaded MCC catalog"))
        elif slot["mcc_tag"] != s["mcc_tag"]:
            out.append(finding("error", "mcc_tag_mismatch", file, w, f"catalog says {slot['mcc_tag']}"))

        m, a, sub = s["match"], s["audio"], s["subtitle"]
        for ref in m["ce_line_refs"]:
            if ref not in ce:
                out.append(finding("error" if have_ce else "warning", "unknown_ce_line_ref", file, w + "/match", ref))
        # --- audio decision ---------------------------------------------------------
        ce_srcs = [x for x in a["sources"] if x["kind"] == "ce"]
        if ce_srcs and m["status"] != "matched":
            out.append(finding("error", "audio_conflicts_with_match", file, w + "/audio",
                               f"CE audio sources while match.status={m['status']}"))
        for x in ce_srcs:
            ref = x["ce_line_ref"]
            if ref not in m["ce_line_refs"]:
                out.append(finding("error", "audio_source_not_in_match", file, w + "/audio", ref))
            info = ce.get(ref)
            if not info:
                if ref not in m["ce_line_refs"]:
                    out.append(finding("error" if have_ce else "warning", "unknown_ce_line_ref", file,
                                       w + "/audio", ref))
                continue
            if TEST_EVENT_FLAG in info["flags"]:
                out.append(finding("error", "test_event_audio_source", file, w + "/audio",
                                   f"{ref} plays a test event with no dialogue media"))
            if info["media"].get(x["language"], {}).get("evidence") != "explicit":
                out.append(finding("error" if a["status"] == "approved" else "warning", "audio_source_unresolved",
                                   file, w + "/audio", f"{ref} has no resolved {x['language']} media"))
        for k in audio_edit.removed_fields(a["edit"]):  # speed / gain_db, removed 2026-10-09
            out.append(finding("error", "audio_edit_removed_field", file, w + "/audio/edit",
                               f"{k} is no longer supported; run python scripts/validate/migrate_reset_speed_gain.py"))
        if not audio_edit.is_identity(a["edit"]):  # owner's edit recipe (non-destructive, applied by M6)
            sev = "error" if a["status"] == "approved" else "warning"
            for p in audio_edit.problems({k: v for k, v in a["edit"].items() if k not in audio_edit.REMOVED_FIELDS}):
                out.append(finding("error", "invalid_audio_edit", file, w + "/audio/edit", p))
            if a["source"] != "ce":
                out.append(finding("error", "audio_edit_unsupported_source", file, w + "/audio/edit",
                                   f"edit recipes apply to one CE line (source 'ce'), not {a['source']!r}"))
            elif a["sources"] and {k: a["sources"][0].get(k) for k in ("ce_line_ref", "language")} \
                    != a["edit"].get("for_source"):
                out.append(finding(sev, "audio_edit_source_mismatch", file, w + "/audio/edit",
                                   "the edit was made for another CE line or language; reset or redo it"))
        for x in a["sources"]:
            if x["kind"] == "user_recording":
                if local is None:
                    out.append(finding("error", "local_file_missing", file, w + "/audio",
                                       f"{x['ref']} needs manual_mappings.local.json"))
                elif x["ref"] not in local["user_recordings"]:
                    out.append(finding("error", "unknown_user_recording", file, w + "/audio", x["ref"]))
        # --- subtitle decision (independent of audio) -------------------------------
        if sub["source"] == "ce_locres":
            ref, cul = sub["ce_locres"]["ce_line_ref"], sub["ce_locres"]["culture"]
            if ref not in ce:
                out.append(finding("error" if have_ce else "warning", "unknown_ce_line_ref", file,
                                   w + "/subtitle", ref))
            elif ce[ref]["subtitles"].get(cul, {}).get("evidence") != "explicit":
                out.append(finding("error" if sub["status"] == "approved" else "warning", "subtitle_unresolved",
                                   file, w + "/subtitle", f"{ref} has no resolved {cul} subtitle"))
            if ref not in m["ce_line_refs"]:
                out.append(finding("warning", "subtitle_source_not_in_match", file, w + "/subtitle", ref))
        if sub["source"] == "custom":
            if local is None:
                out.append(finding("error", "local_file_missing", file, w + "/subtitle",
                                   f"{sub['custom_ref']} needs manual_mappings.local.json"))
            elif sub["custom_ref"] not in local["custom_subtitles"]:
                out.append(finding("error", "unknown_custom_ref", file, w + "/subtitle", sub["custom_ref"]))
        if sub["mcc_key_hash"] is not None:
            v = ver_ids.get(sub["mcc_key_verification"])
            if not v or v["subject"] != f"mcc:{s['slot_id']}" or "subtitle_key_link" not in v["checks"] \
                    or v["result"] != "pass":
                out.append(finding("error", "unverified_subtitle_key", file, w + "/subtitle",
                                   "mcc_key_hash needs a passing 'subtitle_key_link' verification for this slot "
                                   "(blocker B1); never guess hashed keys"))
        # --- approvals pin fingerprints; mismatches are drift, never edits ----------
        for field, fn in (("audio", audio_fingerprint), ("subtitle", subtitle_fingerprint)):
            obj = s[field]
            if obj["status"] != "approved":
                continue
            cur = fn(s, ce, mcc, local)
            needs_ce = bool(ce_srcs) if field == "audio" else sub["source"] == "ce_locres"
            if have_mcc and (have_ce or not needs_ce) and obj["fingerprint"] != cur:
                out.append(finding("warning", "approved_fingerprint_drift", file, f"{w}/{field}",
                                   "approved decision no longer matches current catalogs; see drift report"))
                drift.append({"kind": "approved_mapping", "mapping_id": s["mapping_id"], "field": field,
                              "slot_id": s["slot_id"], "approved": obj["fingerprint"], "current": cur})

    if local is not None:
        used_c = {s["subtitle"]["custom_ref"] for s in doc["slots"] if s["subtitle"]["custom_ref"]}
        used_r = {x["ref"] for s in doc["slots"] for x in s["audio"]["sources"] if x["kind"] == "user_recording"}
        for c in sorted(set(local["custom_subtitles"]) - used_c):
            out.append(finding("info", "unused_custom_subtitle", "manual_mappings.local.json", c, "not referenced"))
        for r in sorted(set(local["user_recordings"]) - used_r):
            out.append(finding("info", "unused_user_recording", "manual_mappings.local.json", r, "not referenced"))
    return out, drift


def _only_level_settings_reset(head_audio, audio):
    """True when the only differences are the owner-authorized level resets of 2026-10-11, one way only:
    audio.edit.loudness switched off (migrate_reset_loudness_match.py) and/or the audio.edit.limiter setting
    removed (migrate_remove_limiter.py). The global export gain is the only level setting. Switching matching
    on, adding a limiter back, or any other change is still a change to an approved decision."""
    from .mapping_store import LOUDNESS_OFF
    edit = audio.get("edit") or {}
    head_edit = head_audio.get("edit") or {}
    if "limiter" in edit and edit.get("limiter") != head_edit.get("limiter"):
        return False  # a limiter added back or changed
    if edit.get("loudness") != head_edit.get("loudness") and edit.get("loudness") != LOUDNESS_OFF:
        return False
    def without(a):
        a = comparable(a, "audio")
        return {**a, "edit": {k: v for k, v in (a.get("edit") or {}).items() if k not in ("loudness", "limiter")}}
    return without(head_audio) == without(audio)


def check_approved_protected(head_doc, doc, file="manual_mappings.json"):
    """Approved objects committed at HEAD must survive unchanged, unless moved to needs_rework with revision+1."""
    out = []
    if not head_doc:
        return out
    cur = {s["mapping_id"]: s for s in doc.get("slots", [])}
    for hs in head_doc.get("slots", []):
        approved = [f for f in ("audio", "subtitle") if hs[f]["status"] == "approved"]
        if not approved:
            continue
        s = cur.get(hs["mapping_id"])
        if s is None:
            out.append(finding("error", "approved_mapping_removed", file, hs["mapping_id"],
                               "a mapping with an approved decision was deleted"))
            continue
        if s["slot_id"] != hs["slot_id"]:
            out.append(finding("error", "approved_mapping_retargeted", file, hs["mapping_id"],
                               f"slot_id changed {hs['slot_id']} -> {s['slot_id']}"))
        for f in approved:
            if comparable(s[f], f) == comparable(hs[f], f):  # across v2 -> v3 (fx_request moved out)
                continue
            if f == "audio" and _only_level_settings_reset(hs[f], s[f]):
                continue  # owner-authorized resets (2026-10-11: loudness off, limiter removed); one-way only
            # Since HEAD the owner may have reworked it (revision + 1 per rework, enforced at save time by
            # mapping_store) and possibly approved it again: a higher revision is that trace. A change
            # without a higher revision is a silent edit.
            if s[f]["status"] in ("needs_rework", "approved") and s[f]["revision"] > hs[f]["revision"]:
                continue
            out.append(finding("error", "approved_object_modified", file, f"{hs['mapping_id']}/{f}",
                               "approved decisions are immutable; only a user move to needs_rework "
                               "(revision + 1) is allowed"))
    return out


# --------------------------------------------------------------------------- verifications
def validate_verifications(doc, schema, *, ce, mcc, head_doc=None, file="verifications.json"):
    out, drift = [], []
    errs = schema_validate(doc, schema)
    out += [finding("error", "schema", file, e.split(":")[0], e) for e in errs]
    if errs:
        return out, drift
    vs = doc["verifications"]
    for n, v in enumerate(vs, 1):
        if v["id"] != f"v-{n:06d}":
            out.append(finding("error", "verification_id_sequence", file, v["id"], f"expected v-{n:06d}"))
    if head_doc:
        hv = head_doc.get("verifications", [])
        if vs[:len(hv)] != hv:
            out.append(finding("error", "verifications_not_append_only", file, "/verifications",
                               "entries committed at HEAD were changed, reordered or removed"))
    for v in vs:
        kind, ident = v["subject"].split(":", 1)
        fp = v["fingerprint"]
        if kind == "ce":
            info = ce.get(ident)
            if not info:
                out.append(finding("error" if ce else "info", "unknown_subject", file, v["id"], v["subject"]))
                continue
            for lang, want in (fp.get("media") or {}).items():
                cur = info["media"].get(lang, {}).get("media", [])
                cur0 = cur[0] if cur else {}
                if (cur0.get("media_id"), cur0.get("wem_sha256")) != (want.get("media_id"), want.get("wem_sha256")):
                    drift.append({"kind": "verification", "id": v["id"], "subject": v["subject"], "language": lang,
                                  "verified": want, "current": cur0})
        else:
            slot = mcc["slots"].get(ident)
            if not slot:
                out.append(finding("error" if mcc["slots"] else "info", "unknown_subject", file, v["id"],
                                   v["subject"]))
                continue
            es = (fp.get("samples") or {}).get("spanish") or {}
            if (es.get("index"), es.get("data_sha256")) != (slot["index"], slot["data_sha256"]):
                drift.append({"kind": "verification", "id": v["id"], "subject": v["subject"],
                              "language": "spanish", "verified": es,
                              "current": {"index": slot["index"], "data_sha256": slot["data_sha256"]},
                              "note": "slot_id now points to a different sample (ID change)"})
            if v.get("mcc_tag") and v["mcc_tag"] != slot["mcc_tag"]:
                out.append(finding("error", "mcc_tag_mismatch", file, v["id"], f"catalog says {slot['mcc_tag']}"))
    for d in drift:
        out.append(finding("warning", "verification_fingerprint_drift", file, d["id"],
                           f"{d['subject']} {d['language']}: verified media differs from current catalog"))
    return out, drift


def validate_mission_map(doc, schema, *, ce_missions, mcc_levels, file="mission_map.json"):
    out = [finding("error", "schema", file, e.split(":")[0], e) for e in schema_validate(doc, schema)]
    if out:
        return out
    seen = set()
    for e in doc["entries"]:
        if e["mcc_level"] in seen:
            out.append(finding("error", "duplicate_level", file, e["mcc_level"], "level listed twice"))
        seen.add(e["mcc_level"])
        if mcc_levels and e["mcc_level"] not in mcc_levels:
            out.append(finding("info", "level_catalog_missing", file, e["mcc_level"], "no MCC catalog built yet"))
        for m in e["ce_missions"]:
            if ce_missions and m not in ce_missions:
                out.append(finding("info", "mission_catalog_missing", file, m, "no CE catalog built yet"))
    return out


READY_STATUSES = ("ready_for_build", "in_game_tested", "reviewed")


def level_progress(level_slot_ids, mappings_doc):
    """Slot-level progress of one MCC level, derived from manual_mappings.json. Pure."""
    by_slot = {s["slot_id"]: s for s in (mappings_doc or {}).get("slots", [])}
    out = {"slots": len(level_slot_ids), "decided": 0, "matched": 0, "no_equivalent": 0, "deferred": 0,
           "audio_approved": 0, "subtitle_approved": 0, "needs_rework": 0, "radio_effect": 0,
           "different_but_fits": 0, "needs_recording": 0, "muted": 0, "muted_approved": 0}
    for sid in level_slot_ids:
        s = by_slot.get(sid)
        if not s:
            continue
        st = s["match"]["status"]
        if st != "unreviewed":
            out["decided"] += 1
        if st in ("matched", "no_equivalent", "deferred"):
            out[st] += 1
        out["audio_approved"] += s["audio"]["status"] == "approved"
        out["subtitle_approved"] += s["subtitle"]["status"] == "approved"
        out["radio_effect"] += bool((s.get("radio_effect") or {}).get("needed"))
        out["different_but_fits"] += bool((s.get("different_but_fits") or {}).get("marked"))
        out["needs_recording"] += bool((s.get("needs_recording") or {}).get("marked"))
        out["needs_rework"] += "needs_rework" in (s["audio"]["status"], s["subtitle"]["status"])
        # Muted lines (a subset of no_equivalent): decided, never counted as matched recordings.
        out["muted"] += s["audio"]["source"] == "mute"
        out["muted_approved"] += s["audio"]["source"] == "mute" and s["audio"]["status"] == "approved"
    out["ready_for_build"] = bool(level_slot_ids) and out["decided"] == out["audio_approved"] == len(level_slot_ids)
    return out


def validate_mission_progress(doc, schema, *, level_slots, mappings_doc, verifications, file="mission_progress.json"):
    """level_slots: {level: [slot_id]} from the loaded MCC catalogs. Never edits the file."""
    out = [finding("error", "schema", file, e.split(":")[0], e) for e in schema_validate(doc, schema)]
    if out:
        return out
    ver_ids = {v["id"] for v in (verifications or {}).get("verifications", [])}
    seen = set()
    for e in doc["levels"]:
        lv = e["mcc_level"]
        if lv in seen:
            out.append(finding("error", "duplicate_level", file, lv, "level listed twice"))
        seen.add(lv)
        if e["verification"] and e["verification"] not in ver_ids:
            out.append(finding("error", "unknown_verification", file, lv, e["verification"]))
        if lv not in level_slots:
            if level_slots:
                out.append(finding("info", "level_catalog_missing", file, lv, "no MCC catalog built yet"))
            continue
        if e["status"] in READY_STATUSES:
            prog = level_progress(level_slots[lv], mappings_doc)
            if not prog["ready_for_build"]:
                out.append(finding("warning", "level_status_ahead_of_decisions", file, lv,
                                   f"status {e['status']} but {prog['slots'] - prog['decided']} slot(s) undecided and "
                                   f"{prog['slots'] - prog['audio_approved']} without approved audio"))
    return out


def dumps(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
