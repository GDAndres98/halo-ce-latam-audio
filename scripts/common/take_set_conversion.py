"""Replacement sets for multi-take sounds: the read-only preview and the conversion of a sound's per-take decisions
into one set of replacement takes (docs/replacement-set-conversion.md).

A replacement set is the existing own take set model (own_sets + added_takes, docs/custom-take-set-design.md); this
module only adds the way to build one from decisions the owner already made, instead of clearing them:

  per take (mode A)   3 Spain takes: take 1 -> ce1, take 2 -> ce2, take 3 -> ce1
  replacement set     the sound -> [ce1, ce2]  (two takes: the two ce1 selections have the same audio specification)

Rules (owner, 2026-10-18):
- Group by the exact mcc_tag. Only audio the owner SELECTED becomes a take (audio.source 'ce' with one CE line); a
  match without selected audio never does, and nothing is inferred or ranked.
- Two selections are one take only when their complete audio specification is equal: CE line, language and the
  effective edit recipe (trims, cuts, silences, fades, radio, echo, interference, and the source the recipe was made
  for). The same recording with different trims or effects stays two takes.
- Order: the sound's existing added takes keep their IDs and positions; new takes follow, in the order of the first
  Spain take (bank order) that selected them.
- Never approved by a tool: every created take is a draft (approvals are never copied; see the doc, section B).
- Staged first: the line decisions stay in force (the build is unchanged) until the owner switches the sound to its
  set, which requires every take of the set to be approved and buildable. The switch, a cancel and an undo are each
  ONE store save (mapping_store.save_sequence), checked step by step against the store's rules.
- The own set's `provenance` keeps the exact decisions it replaced (and the custom subtitle text hashes), read-only.
- Sounds WITH a SU/SP subtitle entry (owner, 2026-10-19): one subtitle per set (`own_sets[].subtitle`). Staging
  prefills it as a DRAFT only when every Spain take's current subtitle decision says the same thing; otherwise it is
  left undecided and reported (`set_subtitle_undecided`). Approvals are never copied. The switch needs it approved.

Pure: no file or database access. The Studio (scripts/ui/m4_app.py) and the read-only inventory
(scripts/validate/take_set_inventory.py) pass the documents and catalogs in.
"""
import copy
import hashlib
import json

from . import audio_edit
from .m6_build import edit_problems, plan_audio, plan_inserts
from .own_set_state import is_active
from .project_validation import audio_fingerprint, own_set_subtitle_fingerprint, sha256_text, subtitle_fingerprint

PREVIEW_SCHEMA = "take-set-preview/1"
MX = "Spanish(Mexico)"

# Issue codes. blocked: cannot be staged; review: staged only when the owner acknowledges the code for that sound
# (never in a bulk stage); info: shown, nothing to decide.
CODES = {
    "unsupported_source": ("blocked", "The selected audio is not one Campaign Evolved line (concatenation or a user "
                                      "recording); a replacement take holds exactly one CE line."),
    "unresolved_media": ("blocked", "The selected Campaign Evolved line has no single resolved recording in that "
                                    "language (or is a test event, or unknown)."),
    "invalid_recipe": ("blocked", "The edit recipe is not valid for its line."),
    "gap_on_one_line": ("blocked", "The recipe has a gap, which only applies between concatenated lines."),
    "conflicting_decision": ("blocked", "Campaign Evolved audio is selected while the match is not 'matched'."),
    "duplicate_decision": ("blocked", "Several decisions exist for one Spain take."),
    "nothing_selected": ("blocked", "No Campaign Evolved audio is selected for any take and the sound has no added "
                                    "takes: there is nothing to convert."),
    "undecided_take": ("review", "This Spain take has no decision: the replacement set removes it, with nothing in "
                                 "its place."),
    "keep_original": ("review", "You chose to keep Spain's recording for this take: the replacement set removes it."),
    "mute": ("review", "This take is muted: the replacement set removes it from the rotation instead of playing "
                       "silence, so how often the sound is silent changes."),
    "match_only": ("review", "Matched to a recording, but no audio was selected: the match is not used as a "
                             "replacement."),
    "needs_rework_source": ("review", "The selected audio is marked Needs rework: carrying it into the set may not be "
                                      "what you want."),
    "approved_drift": ("review", "Approved, but the catalogs changed since (drift): the build already skips this "
                                 "take; listen to it again."),
    "subtitle_text": ("review", "A subtitle text is chosen, but the sound has no subtitle entry, so it is never shown; "
                                "a replacement set has no subtitle. The choice is kept in the record."),
    "custom_subtitle_missing": ("review", "The custom subtitle this decision names is missing from "
                                          "manual_mappings.local.json; the record pins it as missing."),
    "needs_recording": ("review", "Marked 'needs a new recording': takes have no such flag. Kept in the record."),
    "radio_flag_conflict": ("review", "Merged decisions disagree on 'needs radio effect'; the take gets it marked."),
    "notes_differ": ("review", "Merged decisions have different notes; the take gets none (all kept in the record)."),
    "approved_source": ("info", "Approved: the new take is a draft and needs your approval (approvals are never "
                                "copied)."),
    "draft_source": ("info", "Draft: the new take is a draft too."),
    "consolidated": ("info", "Same recording, language and recipe as another take: merged into one take."),
    "reuses_existing_take": ("info", "Same audio as a take the sound already has: that take is used."),
    "existing_take": ("info", "An added take the sound already has: it joins the set unchanged (ID, position, "
                              "approval)."),
    "different_but_fits": ("info", "Marked 'different dialogue, fits the scene': kept in the record."),
    "subtitle_keep": ("info", "Subtitle decision on a sound without a subtitle entry: no effect; kept in the record."),
    "set_subtitle_prefilled": ("info", "Every Spain take has the same subtitle decision: the set's one subtitle starts "
                                       "as that choice, as a draft (approve it under Takes of this sound; approvals are "
                                       "never copied)."),
    "set_subtitle_undecided": ("review", "The Spain takes' subtitle decisions differ, or some takes have none: the "
                                         "set's one subtitle is left undecided. Choose and approve it under Takes of "
                                         "this sound before the switch."),
    "notes_carried": ("info", "The decision's notes are copied to the take."),
}
SEVERITY_ORDER = {"blocked": 0, "review": 1, "info": 2}


class ConversionError(Exception):
    """A refused conversion action. status: the HTTP status the Studio answers with."""

    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details or []


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def effective_edit(edit):
    """The part of a recipe that changes the sound (None = unedited). gap_s only applies between concatenated lines."""
    if audio_edit.is_identity(edit):
        return None
    return {k: v for k, v in (edit or {}).items() if k != "gap_s"}


def spec_of(audio):
    """The complete audio specification of a CE take or decision: [ce_line_ref, language, effective recipe]."""
    src = (audio.get("sources") or [{}])[0]
    return [src.get("ce_line_ref"), src.get("language"), effective_edit(audio.get("edit"))]


def spec_key(audio):
    return json.dumps(spec_of(audio), sort_keys=True, ensure_ascii=False)


def _issue(code, slot_id=None, detail=None):
    sev, text = CODES[code]
    out = {"code": code, "severity": sev, "message": text}
    if slot_id:
        out["slot_id"] = slot_id
    if detail:
        out["detail"] = detail
    return out


def _decided(m):
    """False for no decision or one still at its defaults (unreviewed, keep Spain, draft)."""
    return bool(m) and not (m["match"]["status"] == "unreviewed" and m["audio"]["source"] == "keep_original"
                            and m["audio"]["status"] == "draft" and m["subtitle"]["source"] == "keep_original"
                            and m["subtitle"]["status"] == "draft")


def _summary(m):
    if not m:
        return None
    a = m["audio"]
    return {"mapping_id": m["mapping_id"], "match": m["match"]["status"], "match_refs": m["match"]["ce_line_refs"],
            "audio": a["status"], "audio_source": a["source"], "audio_revision": a["revision"],
            "audio_refs": [x.get("ce_line_ref") or x.get("ref") for x in a["sources"]],
            "edit_summary": None if audio_edit.is_identity(a["edit"]) else audio_edit.summary(a["edit"]),
            "subtitle": m["subtitle"]["status"], "subtitle_source": m["subtitle"]["source"],
            "radio_effect": bool((m.get("radio_effect") or {}).get("needed")),
            "different_but_fits": bool((m.get("different_but_fits") or {}).get("marked")),
            "needs_recording": bool((m.get("needs_recording") or {}).get("marked")), "notes": m.get("notes", "")}


def custom_refs(slots, local):
    out = []
    for m in slots:
        ref = m["subtitle"].get("custom_ref")
        if ref:
            text = (((local or {}).get("custom_subtitles") or {}).get(ref) or {}).get("text")
            out.append({"custom_ref": ref, "text_sha256": sha256_text(text) if text is not None else None})
    return sorted(out, key=lambda c: c["custom_ref"])


def _classify(m, sample, ce_lines, ce_idx, mcc_idx, local, dup, has_subtitle_entry=False):
    """-> (selected audio object or None, [issues]) for one Spain take. On a sound with a subtitle entry the line
    subtitle decisions are weighed for the whole sound instead (set_subtitle_proposal)."""
    sid = sample["slot_id"]
    if dup:
        return None, [_issue("duplicate_decision", sid)]
    if not _decided(m):
        return None, [_issue("undecided_take", sid)]
    issues = []
    a = m["audio"]
    sub = m["subtitle"]
    if sub["source"] == "custom" and sub.get("custom_ref") and sub["custom_ref"] not in \
            ((local or {}).get("custom_subtitles") or {}):
        issues.append(_issue("custom_subtitle_missing", sid, sub["custom_ref"]))
    if has_subtitle_entry:
        pass  # weighed for the whole sound: set_subtitle_proposal
    elif sub["source"] in ("ce_locres", "custom"):
        issues.insert(0, _issue("subtitle_text", sid, sub["source"]))
    elif sub["status"] != "draft" or sub["source"] != "keep_original":
        issues.append(_issue("subtitle_keep", sid, f"{sub['source']} ({sub['status']})"))
    if (m.get("needs_recording") or {}).get("marked"):
        issues.append(_issue("needs_recording", sid))
    if (m.get("different_but_fits") or {}).get("marked"):
        issues.append(_issue("different_but_fits", sid))
    if a["source"] == "keep_original":
        issues.append(_issue("keep_original", sid, a["status"]))
        if m["match"]["ce_line_refs"]:
            issues.append(_issue("match_only", sid, ", ".join(m["match"]["ce_line_refs"])))
        return None, issues
    if a["source"] == "mute":
        issues.append(_issue("mute", sid, a["status"]))
        return None, issues
    if a["source"] != "ce" or len(a["sources"]) != 1 or a["sources"][0].get("kind") != "ce":
        return None, issues + [_issue("unsupported_source", sid, a["source"])]
    if m["match"]["status"] != "matched":
        return None, issues + [_issue("conflicting_decision", sid, m["match"]["status"])]
    src = a["sources"][0]
    ref, lang = src["ce_line_ref"], src["language"]
    line = ce_lines.get(ref)
    media = (line[2]["media"].get(lang) or {}) if line else {}
    if not line or "test_event" in line[1]["flags"] or media.get("evidence") != "explicit" \
            or len(media.get("media", [])) != 1:
        return None, issues + [_issue("unresolved_media", sid, f"{ref} ({lang})")]
    probs = edit_problems(a["edit"], ref, lang)
    if probs:
        return None, issues + [_issue("invalid_recipe", sid, "; ".join(probs))]
    if (a["edit"] or {}).get("gap_s"):
        return None, issues + [_issue("gap_on_one_line", sid)]
    if a["status"] == "approved":
        if a["fingerprint"] != audio_fingerprint(m, ce_idx, mcc_idx, local):
            issues.append(_issue("approved_drift", sid))
        issues.append(_issue("approved_source", sid))
    elif a["status"] == "needs_rework":
        issues.append(_issue("needs_rework_source", sid))
    else:
        issues.append(_issue("draft_source", sid))
    return a, issues


def _build_view(doc, rec, level, *, ce_lines, ce_idx, mcc_idx, local, subtitle_keys):
    """What the build does with this one sound for `doc` (the M6 planner itself, limited to the sound)."""
    from .m6_build import own_set_drops
    slot_index = {s["slot_id"]: (level, rec, s) for s in rec["samples"]["spanish"]}
    idx = dict(slot_index=slot_index, ce_lines=ce_lines, ce_idx=ce_idx, mcc_idx=mcc_idx, local=local)
    ins = plan_inserts(doc, [level], subtitle_keys=subtitle_keys, **idx)
    audio = plan_audio(doc, [level], dropped_tags=own_set_drops(doc, ins), **idx)
    spain = [{"slot_id": e["slot_id"], "action": e["action"], "reason": e["reason"],
              "ce_line_ref": e.get("ce_line_ref")} for e in audio["entries"]]
    inserts = [{"take_id": e["take_id"], "action": e["action"], "reason": e["reason"],
                "ce_line_ref": e.get("ce_line_ref")} for e in ins]
    plays = [x for x in spain if x["action"] != "dropped"] + [x for x in inserts if x["action"] == "insert"]
    return {"spain": spain, "inserts": inserts, "takes_in_game": len(plays),
            "replaced": sum(x["action"] == "replace" for x in spain),
            "muted": sum(x["action"] == "mute" for x in spain),
            "spain_kept": sum(x["action"] in ("keep_original", "not_eligible") for x in spain),
            "dropped": sum(x["action"] == "dropped" for x in spain),
            "inserted": sum(x["action"] == "insert" for x in inserts)}


def _subtitle_content(m, local):
    """What a line's subtitle decision shows, for comparing takes: (source, ce_locres, custom text). None when a
    custom text is missing from the local file (it cannot be carried)."""
    sub = m["subtitle"]
    text = None
    if sub["source"] == "custom":
        text = (((local or {}).get("custom_subtitles") or {}).get(sub.get("custom_ref")) or {}).get("text")
        if text is None:
            return None
    return (sub["source"], json.dumps(sub.get("ce_locres"), sort_keys=True), text)


def set_subtitle_proposal(doc, tag, rec, local):
    """The set's one subtitle for a sound with a subtitle entry (owner, 2026-10-19): a proposal only when EVERY
    Spain take has exactly one decision and all of them show the same thing (same source, same CE subtitle, same
    custom text; status does not matter: the proposal is a draft). -> {"prefill": {source, ce_locres, custom_text}
    or None, "reason": text, "from_mapping_ids": [...]}."""
    by_slot = {}
    for m in doc["slots"]:
        if m["mcc_tag"] == tag:
            by_slot.setdefault(m["slot_id"], []).append(m)
    contents, mids, missing = set(), [], []
    for smp in rec["samples"]["spanish"]:
        ms = by_slot.get(smp["slot_id"], [])
        if len(ms) != 1:
            missing.append(smp["slot_id"])
            continue
        mids.append(ms[0]["mapping_id"])
        contents.add(_subtitle_content(ms[0], local))
    if missing:
        return {"prefill": None, "from_mapping_ids": [],
                "reason": f"{len(missing)} Spain take(s) without one decision: " + ", ".join(missing)}
    if None in contents:
        return {"prefill": None, "from_mapping_ids": [], "reason": "a custom subtitle text is missing locally"}
    if len(contents) != 1:
        return {"prefill": None, "from_mapping_ids": [],
                "reason": f"the takes' subtitle decisions differ ({len(contents)} different choices)"}
    source, ce_locres, text = next(iter(contents))
    return {"prefill": {"source": source, "ce_locres": json.loads(ce_locres), "custom_text": text},
            "from_mapping_ids": sorted(mids), "reason": "every Spain take has the same subtitle decision"}


def new_set_subtitle(prefill, custom_ref=None):
    """A DRAFT set subtitle object from a proposal (never approved; revision 1). A custom text needs its new
    custom_ref (the caller writes the text to the local file); without one, None."""
    if prefill["source"] == "custom" and not custom_ref:
        return None
    return {"status": "draft", "source": prefill["source"],
            "ce_locres": prefill["ce_locres"] if prefill["source"] == "ce_locres" else None,
            "custom_ref": custom_ref if prefill["source"] == "custom" else None,
            "fingerprint": None, "approved_at": None, "revision": 1}


def set_subtitle_problem(doc, tag, *, has_subtitle_entry, ce_idx, mcc_idx, local):
    """None when the set's subtitle is ready for the switch (or the sound has no subtitle entry); else why not."""
    if not has_subtitle_entry:
        return None
    o = next((x for x in doc.get("own_sets", []) if x["mcc_tag"] == tag), None)
    sub = (o or {}).get("subtitle")
    if not sub:
        return "the sound has a subtitle entry: choose and approve the set's subtitle first"
    if sub["status"] != "approved":
        return f"the set's subtitle is {sub['status'].replace('_', ' ')}: approve it first"
    if sub["fingerprint"] != own_set_subtitle_fingerprint(o, ce_idx, mcc_idx, local):
        return "the set's subtitle changed since its approval (drift): rework it"
    return None


def mode_of(doc, tag):
    own = next((o for o in doc.get("own_sets", []) if o["mcc_tag"] == tag), None)
    if own is not None:
        return "replacement_set" if is_active(own) else "replacement_set_staged"
    if any(t["mcc_tag"] == tag for t in doc.get("added_takes", [])):
        return "spain_plus_added"
    return "per_take"


def sound_inputs(doc, tag, rec, *, has_subtitle_entry, ce_idx, local):
    """Everything a conversion of `tag` reads. Its hash is the preview token: a change to any line decision of the
    sound, its added takes, its own-set state, its custom subtitle texts, the catalog facts of its Spain takes or of
    the CE lines it names, or its eligibility makes the preview stale."""
    slots = sorted((m for m in doc["slots"] if m["mcc_tag"] == tag), key=lambda m: m["mapping_id"])
    takes = sorted((t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag), key=lambda t: t["take_id"])
    refs = sorted({x.get("ce_line_ref") for m in slots for x in m["audio"]["sources"] if x.get("ce_line_ref")}
                  | {r for m in slots for r in m["match"]["ce_line_refs"]}
                  | {x.get("ce_line_ref") for t in takes for x in t["audio"]["sources"] if x.get("ce_line_ref")})
    own = next((o for o in doc.get("own_sets", []) if o["mcc_tag"] == tag), None)
    sub = (own or {}).get("subtitle") or {}
    if sub.get("ce_locres"):
        refs = sorted(set(refs) | {sub["ce_locres"]["ce_line_ref"]})
    out = {"preview_schema": PREVIEW_SCHEMA, "mcc_tag": tag, "slots": slots, "added_takes": takes,
           "own_set": own,
           "custom_subtitles": custom_refs(slots, local),
           "catalog": [[s["slot_id"], s["index"], s["data_sha256"], s["channels"], s["ordinal_in_tag"]]
                       for s in rec["samples"]["spanish"]],
           "has_subtitle_entry": bool(has_subtitle_entry),
           "ce": {r: ce_idx.get(r) for r in refs}}
    if sub.get("custom_ref"):  # the set's own custom text (only present for such sets: other tokens are unchanged)
        out["set_custom_subtitle"] = custom_refs([{"subtitle": sub}], local)
    return out


def sound_doc(doc, tag):
    """The part of the decisions one sound reads (its lines, added takes and own set): previews and build views of
    one sound never need the rest, and copying 1,200 lines per sound made the inventory slow."""
    out = {"schema": doc.get("schema"), "pins": doc.get("pins"),
           "slots": [m for m in doc["slots"] if m["mcc_tag"] == tag]}
    takes = [t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag]
    sets = [o for o in doc.get("own_sets", []) if o["mcc_tag"] == tag]
    if takes:
        out["added_takes"] = takes
    if sets:
        out["own_sets"] = sets
    return out


def plan_sound(doc, tag, rec, level, *, has_subtitle_entry, ce_lines, ce_idx, mcc_idx, local=None,
               subtitle_keys=None):
    """The read-only preview of converting one sound. Never writes. -> item (see the doc, section 4)."""
    doc = sound_doc(doc, tag)
    spain = rec["samples"]["spanish"]
    inputs = sound_inputs(doc, tag, rec, has_subtitle_entry=has_subtitle_entry, ce_idx=ce_idx, local=local)
    token = digest(inputs)
    item = {"mcc_tag": tag, "level": level, "tag_name": rec["tag_name"], "original_takes": len(spain),
            "first_slot_id": spain[0]["slot_id"],
            "mode": mode_of(doc, tag), "token": token, "eligible": True, "reason": "", "status": None,
            "sources": [], "existing_takes": [], "proposed": [], "issues": [], "summary": ""}
    item["has_subtitle_entry"] = bool(has_subtitle_entry)  # owner 2026-10-19: allowed, one subtitle per set
    if any(s["channels"] != 1 for s in spain):
        item.update(eligible=False, reason="stereo sound (stereo replacement is deferred)")
    by_slot = {}
    for m in doc["slots"]:
        if m["mcc_tag"] == tag:
            by_slot.setdefault(m["slot_id"], []).append(m)
    existing = sorted((t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag), key=lambda t: t["position"])
    item["existing_takes"] = [{"take_id": t["take_id"], "position": t["position"], "status": t["audio"]["status"],
                               "ce_line_ref": (t["audio"]["sources"] or [{}])[0].get("ce_line_ref"),
                               "language": (t["audio"]["sources"] or [{}])[0].get("language"),
                               "edit_summary": None if audio_edit.is_identity(t["audio"]["edit"])
                               else audio_edit.summary(t["audio"]["edit"])} for t in existing]
    view = dict(ce_lines=ce_lines, ce_idx=ce_idx, mcc_idx=mcc_idx, local=local, subtitle_keys=subtitle_keys)
    item["build_now"] = _build_view(doc, rec, level, **view)
    if not item["eligible"]:
        item["status"] = "ineligible"
        item["summary"] = f"{len(spain)} original MCC takes: per-take workflow ({item['reason']})"
        return item
    if item["mode"] in ("replacement_set", "replacement_set_staged"):
        item["status"] = "active" if item["mode"] == "replacement_set" else "staged"
        n = len(existing)
        item["takes_total"] = item["replacement_takes"] = n
        item["takes_approved"] = sum(t["audio"]["status"] == "approved" for t in existing)
        item["summary"] = (f"{len(spain)} original MCC takes -> {n} replacement take{'s' * (n != 1)}"
                           + (" (staged, not switched on)" if item["status"] == "staged" else ""))
        return item

    # Classify each Spain take (bank order), then merge equal specifications.
    proposed, by_key = [], {}
    for p in existing:  # the sound's existing added takes keep their ID, position and approval
        k = spec_key(p["audio"])
        entry = {"key": k, "origin": "existing", "take_id": p["take_id"], "position": p["position"],
                 "ce_line_ref": spec_of(p["audio"])[0], "language": spec_of(p["audio"])[1],
                 "edit": p["audio"]["edit"], "edit_summary": None if audio_edit.is_identity(p["audio"]["edit"])
                 else audio_edit.summary(p["audio"]["edit"]), "status": p["audio"]["status"],
                 "radio_effect": bool(p["radio_effect"]["needed"]), "notes": p["notes"], "from_mapping_ids": [],
                 "from_slots": []}
        proposed.append(entry)
        by_key.setdefault(k, entry)
        item["issues"].append(_issue("existing_take", None, p["take_id"]))
    next_pos = max([p["position"] for p in existing] or [0]) + 1
    merged_from = {}
    for s in sorted(spain, key=lambda s: s["index"]):
        ms = by_slot.get(s["slot_id"], [])
        m = ms[0] if len(ms) == 1 else None
        audio, issues = _classify(m, s, ce_lines, ce_idx, mcc_idx, local, dup=len(ms) > 1,
                                  has_subtitle_entry=has_subtitle_entry)
        item["issues"] += issues
        src = {"slot_id": s["slot_id"], "ordinal": s["ordinal_in_tag"], "spanish_index": s["index"],
               "duration_s": s["duration_s"], "decision": _summary(m), "take": None,
               "codes": [i["code"] for i in issues]}
        item["sources"].append(src)
        if audio is None:
            continue
        k = spec_key(audio)
        target = by_key.get(k)
        if target is None:
            ref, lang, _eff = spec_of(audio)
            target = {"key": k, "origin": "new", "take_id": None, "position": next_pos, "ce_line_ref": ref,
                      "language": lang, "edit": copy.deepcopy(audio["edit"]),
                      "edit_summary": None if audio_edit.is_identity(audio["edit"]) else audio_edit.summary(audio["edit"]),
                      "status": "draft", "radio_effect": False, "notes": "", "from_mapping_ids": [], "from_slots": []}
            next_pos += 1
            proposed.append(target)
            by_key[k] = target
        elif target["origin"] == "existing" and not target["from_slots"]:
            item["issues"].append(_issue("reuses_existing_take", s["slot_id"], target["take_id"]))
        else:
            item["issues"].append(_issue("consolidated", s["slot_id"],
                                         "same audio as " + ", ".join(target["from_slots"] or [target["take_id"]])))
        target["from_mapping_ids"].append(m["mapping_id"])
        target["from_slots"].append(s["slot_id"])
        merged_from.setdefault(k, []).append(m)
        src["take"] = target["take_id"] or f"new take {target['position']}"

    for p in proposed:  # flags and notes of the decisions a new take carries
        ms = merged_from.get(p["key"], [])
        if p["origin"] != "new" or not ms:
            continue
        radio = {bool((m.get("radio_effect") or {}).get("needed")) for m in ms}
        p["radio_effect"] = True in radio
        if len(radio) > 1:
            item["issues"].append(_issue("radio_flag_conflict", ms[0]["slot_id"], ", ".join(p["from_slots"])))
        notes = sorted({m.get("notes", "") for m in ms if m.get("notes", "")})
        if len(notes) == 1:
            p["notes"] = notes[0]
            item["issues"].append(_issue("notes_carried", ms[0]["slot_id"]))
        elif len(notes) > 1:
            item["issues"].append(_issue("notes_differ", ms[0]["slot_id"], ", ".join(p["from_slots"])))
    item["proposed"] = proposed
    if has_subtitle_entry:  # the set's ONE subtitle (owner, 2026-10-19): a draft only when every take agrees
        prop = set_subtitle_proposal(doc, tag, rec, local)
        item["set_subtitle"] = prop
        item["issues"].append(_issue("set_subtitle_prefilled" if prop["prefill"] else "set_subtitle_undecided", None,
                                     prop["reason"]))
    if not any(p["from_slots"] for p in proposed) and not existing:
        item["issues"].append(_issue("nothing_selected"))
    if not any(_decided(m) for ms in by_slot.values() for m in ms) and not existing:
        item["status"] = "nothing_to_convert"
    else:
        sev = min([SEVERITY_ORDER[i["severity"]] for i in item["issues"]] or [2])
        item["status"] = {0: "blocked", 1: "review", 2: "ready"}[sev]
    item["issues"].sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i.get("slot_id") or "", i["code"]))
    item["review_codes"] = sorted({i["code"] for i in item["issues"] if i["severity"] == "review"})
    n = item["replacement_takes"] = len(proposed)
    merged = sum(len(p["from_slots"]) for p in proposed if p["origin"] == "new") - sum(
        1 for p in proposed if p["origin"] == "new")
    item["summary"] = (f"{len(spain)} original MCC takes -> {n} replacement take{'s' * (n != 1)}"
                       + (f" ({merged} duplicate selection{'s' * (merged != 1)} merged)" if merged else ""))
    if item["status"] in ("ready", "review"):
        staged, _entry = stage(doc, item, today="2000-01-01", local=local,
                               used_take_ids={t["take_id"] for t in doc.get("added_takes", [])}, acknowledged=None)
        item["build_staged"] = _build_view(staged, rec, level, **view)
        item["build_after"] = {
            "spain": [{"slot_id": s["slot_id"], "action": "dropped",
                       "reason": "replacement set: Spain's take is removed"} for s in spain],
            "takes_in_game": n, "dropped": len(spain), "inserted": n,
            "note": "after you switch the sound to its set, which needs every take approved"}
    return item


# --------------------------------------------------------------------------- the actions (pure: doc -> new doc)
def _next_take_id(used):
    n = max([int(u.split("-")[1]) for u in used if u and u.startswith("t-")] or [0])
    return f"t-{n + 1:06d}"


def spec_digest(audio):
    """Hash of a take's complete audio specification (spec_of): recorded per take at staging, so an edit made to a
    take afterwards is seen."""
    return digest(spec_of(audio))


def local_refs(slots):
    """Local-only data the decisions name: custom subtitle refs and user recording refs."""
    return (sorted({m["subtitle"]["custom_ref"] for m in slots if m["subtitle"].get("custom_ref")}),
            sorted({x["ref"] for m in slots for x in m["audio"]["sources"] if x.get("kind") == "user_recording"}))


def recovery_record(tag, slots, local, today):
    """The git-ignored recovery snapshot of what the record's decisions name in manual_mappings.local.json (custom
    subtitle text, user recording paths), with integrity hashes. None when they name nothing local."""
    customs, recordings = local_refs(slots)
    if not customs and not recordings:
        return None
    cs = ((local or {}).get("custom_subtitles") or {})
    rs = ((local or {}).get("user_recordings") or {})
    return {"mcc_tag": tag, "created_at": today,
            "custom_subtitles": {c: {**cs[c], "text_sha256": sha256_text(cs[c]["text"])} for c in customs if c in cs},
            "user_recordings": {r: dict(rs[r]) for r in recordings if r in rs},
            "missing": [c for c in customs if c not in cs] + [r for r in recordings if r not in rs]}


def stage(doc, item, *, today, used_take_ids, acknowledged, local=None, set_subtitle_custom_ref=None):
    """-> (new doc, own-set entry). Creates the set's new takes as drafts and a staged own set holding the
    provenance; the line decisions are not touched. acknowledged: the review codes the owner confirmed (None: the
    caller already checked; the preview itself uses that). A sound with a subtitle entry whose takes all agree gets
    the set's one subtitle as a DRAFT (item["set_subtitle"]); a custom text needs set_subtitle_custom_ref (the caller
    writes the text to the local file under that new ref), otherwise it stays undecided."""
    if item["status"] not in ("ready", "review"):
        raise ConversionError(409, f"this sound cannot be converted ({item['status']})",
                              [f"{i['code']}: {i['message']}" for i in item["issues"] if i["severity"] == "blocked"])
    if acknowledged is not None:
        missing = sorted(set(item.get("review_codes", [])) - set(acknowledged))
        if missing:
            raise ConversionError(409, "confirm the points that need your review first", missing)
    tag = item["mcc_tag"]
    new = copy.deepcopy(doc)
    takes = new.setdefault("added_takes", [])
    used = set(used_take_ids) | {t["take_id"] for t in takes}
    by_id = {t["take_id"]: t for t in takes}
    prov_takes = []
    for p in item["proposed"]:
        if p["origin"] == "existing":
            prov_takes.append({"take_id": p["take_id"], "origin": "existing", "from_mapping_ids": p["from_mapping_ids"],
                               "spec_sha256": spec_digest(by_id[p["take_id"]]["audio"])})
            continue
        tid = _next_take_id(used)
        used.add(tid)
        take = {"take_id": tid, "mcc_tag": tag, "position": p["position"],
                "audio": {"status": "draft", "source": "ce",
                          "sources": [{"kind": "ce", "ce_line_ref": p["ce_line_ref"], "language": p["language"]}],
                          "edit": copy.deepcopy(p["edit"]), "fingerprint": None, "approved_at": None,
                          "revision": 1},
                "radio_effect": {"needed": p["radio_effect"], "set_at": today if p["radio_effect"] else None,
                                 "revision": 1},
                "notes": p["notes"]}
        takes.append(take)
        prov_takes.append({"take_id": tid, "origin": "created", "from_mapping_ids": p["from_mapping_ids"],
                           "spec_sha256": spec_digest(take["audio"])})
    if not takes:
        new.pop("added_takes")
    slots = sorted((copy.deepcopy(m) for m in doc["slots"] if m["mcc_tag"] == tag), key=lambda m: m["mapping_id"])
    existing = sorted((copy.deepcopy(t) for t in doc.get("added_takes", []) if t["mcc_tag"] == tag),
                      key=lambda t: t["take_id"])
    entry = {"mcc_tag": tag, "set_at": today, "state": "staged",
             "provenance": {"kind": "conversion", "record_id": "cv-" + item["token"][:12], "created_at": today,
                            "activated_at": None, "source_version": item["token"], "slots": slots,
                            "added_takes": existing, "custom_subtitles": custom_refs(slots, local),
                            "takes": prov_takes, "acknowledged": sorted(acknowledged or [])}}
    prefill = (item.get("set_subtitle") or {}).get("prefill")
    sub = new_set_subtitle(prefill, set_subtitle_custom_ref) if prefill else None
    if sub:
        entry["subtitle"] = sub
    new.setdefault("own_sets", []).append(entry)
    return new, entry


def _own(doc, tag):
    return next((o for o in doc.get("own_sets", []) if o["mcc_tag"] == tag), None)


def _staged(doc, tag):
    o = _own(doc, tag)
    if o is None or is_active(o) or not o.get("provenance"):
        raise ConversionError(409, "this sound has no staged conversion")
    return o, o["provenance"]


def approvable(doc, tag, rec, level, *, ce_lines, ce_idx, mcc_idx, local=None, eligible=(True, ""),
               has_subtitle_entry=False):
    """Which created takes of a staged conversion "Approve unchanged converted takes" may approve, and why the others
    may not. Read-only. A take is included only when ALL of these hold:
      - it still exists and was not touched since staging (draft, revision 1, same specification as recorded);
      - every decision it came from is still in force, unchanged since staging, with APPROVED audio;
      - each of those approvals is still valid: its fingerprint equals the current one (no drift) and the build would
        replace that line with it (resolved media, valid recipe made for that recording, mono);
      - each of those decisions selects exactly the take's specification (recording, language, recipe, binding);
      - no review point is attached to any of those decisions, and they agree on 'needs radio effect' and notes;
      - the sound is still eligible (mono).
    One approved contributor never stands in for another: a take merged from an approved and a draft decision is
    excluded. -> {"record_id", "included": [...], "excluded": [...]} (each with its source decisions)."""
    o, prov = _staged(doc, tag)
    recorded = {m["mapping_id"]: m for m in prov["slots"]}
    current = {m["mapping_id"]: m for m in doc["slots"] if m["mcc_tag"] == tag}
    takes = {t["take_id"]: t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag}
    samples = {s["slot_id"]: s for s in rec["samples"]["spanish"]}
    slot_index = {s["slot_id"]: (level, rec, s) for s in rec["samples"]["spanish"]}
    plan = {e["mapping_id"]: e for e in plan_audio(sound_doc(doc, tag), [level], slot_index=slot_index,
                                                   ce_lines=ce_lines, ce_idx=ce_idx, mcc_idx=mcc_idx,
                                                   local=local)["entries"] if e["mapping_id"]}
    included, excluded = [], []
    for pt in prov["takes"]:
        if pt["origin"] != "created":
            continue
        tid, t = pt["take_id"], takes.get(pt["take_id"])
        reasons, sources = [], []
        if not eligible[0]:
            reasons.append(f"the sound is not eligible: {eligible[1]}")
        if t is None:
            reasons.append("removed since staging")
        else:
            a = t["audio"]
            if a["status"] == "approved":
                reasons.append("already approved")
            elif a["status"] != "draft" or a["revision"] != 1:
                reasons.append(f"changed since staging (audio {a['status']}, revision {a['revision']})")
            if pt.get("spec_sha256") != spec_digest(a):
                reasons.append("its recording or recipe changed since staging")
        if not pt["from_mapping_ids"]:
            reasons.append("no source decision")
        flags, notes = set(), set()
        for mid in pt["from_mapping_ids"]:
            m, r = current.get(mid), recorded.get(mid)
            ref = m or r or {}
            src = {"mapping_id": mid, "slot_id": ref.get("slot_id"),
                   "audio": (ref.get("audio") or {}).get("status"), "approved_at": (ref.get("audio") or {}).get("approved_at"),
                   "ce_line_ref": ((ref.get("audio") or {}).get("sources") or [{}])[0].get("ce_line_ref")}
            sources.append(src)
            where = ref.get("slot_id") or mid
            if m is None:
                reasons.append(f"{where}: its decision was removed")
                continue
            if m != r:
                reasons.append(f"{where}: its decision changed since staging")
                continue
            if m["audio"]["status"] != "approved":
                reasons.append(f"{where}: audio is {m['audio']['status']}, not approved")
                continue
            if m["audio"]["fingerprint"] != audio_fingerprint(m, ce_idx, mcc_idx, local):
                reasons.append(f"{where}: its approval no longer matches the catalogs (drift)")
            e = plan.get(mid)
            if not e or e["action"] != "replace":
                reasons.append(f"{where}: the build would not use it ({(e or {}).get('reason', 'not planned')})")
            if t is not None and spec_key(m["audio"]) != spec_key(t["audio"]):
                reasons.append(f"{where}: selects different audio than the take")
            _sel, issues = _classify(m, samples.get(m["slot_id"], {"slot_id": m["slot_id"]}), ce_lines, ce_idx,
                                     mcc_idx, local, dup=False, has_subtitle_entry=has_subtitle_entry)
            open_points = sorted({i["code"] for i in issues if i["severity"] in ("review", "blocked")})
            if open_points:
                reasons.append(f"{where}: review points {', '.join(open_points)}")
            flags.add(bool((m.get("radio_effect") or {}).get("needed")))
            notes.add(m.get("notes", ""))
        if len(flags) > 1:
            reasons.append("its decisions disagree on 'needs radio effect'")
        if len({n for n in notes if n}) > 1:
            reasons.append("its decisions have different notes")
        entry = {"take_id": tid, "ce_line_ref": spec_of(t["audio"])[0] if t else None,
                 "language": spec_of(t["audio"])[1] if t else None,
                 "edit_summary": None if not t or audio_edit.is_identity(t["audio"]["edit"])
                 else audio_edit.summary(t["audio"]["edit"]), "sources": sources}
        (excluded if reasons else included).append({**entry, "reasons": reasons} if reasons else entry)
    return {"record_id": prov["record_id"], "included": included, "excluded": excluded}


def approve_unchanged(doc, tag, take_ids, *, today, fingerprint):
    """The owner's "Approve unchanged converted takes": a NEW approval of each listed take (an explicit user 'approve'
    action per take, a fresh added-take fingerprint and today's date), in one save. fingerprint(take) computes the
    take's own current fingerprint. The caller has checked take_ids against approvable() right before. -> steps."""
    from .mapping_store import UserAction
    new = copy.deepcopy(doc)
    wanted = set(take_ids)
    for t in new.get("added_takes", []):
        if t["take_id"] in wanted:
            if t["mcc_tag"] != tag or t["audio"]["status"] == "approved":
                raise ConversionError(409, f"{t['take_id']} cannot be approved here")
            t["audio"].update(status="approved", approved_at=today, fingerprint=fingerprint(t))
    return [(new, [UserAction("approve", tid, "audio") for tid in sorted(wanted)])]


def switch_problems(doc, tag, *, insert_plan, eligible=(True, ""), subtitle_problem=None):
    """Everything that stops a staged sound from being switched (empty = ready). The record is checked against now:
    the line decisions must equal the recorded ones; the set must hold exactly the recorded takes, each with the
    specification recorded at staging; and every take must be approved AND buildable now (insert_plan: plan_inserts
    of the sound as if switched: resolved media, valid recipe for its recording, no drift, mono). A sound with a
    subtitle entry also needs the set's one subtitle approved and drift-free (subtitle_problem: set_subtitle_problem)."""
    o, prov = _staged(doc, tag)
    out = []
    if not eligible[0]:
        out.append(f"the sound is not eligible: {eligible[1]}")
    if subtitle_problem:
        out.append(subtitle_problem)
    now = {m["mapping_id"]: m for m in doc["slots"] if m["mcc_tag"] == tag}
    rec = {m["mapping_id"]: m for m in prov["slots"]}
    for mid in sorted(now.keys() | rec.keys()):
        if now.get(mid) != rec.get(mid):
            what = "added" if mid not in rec else "removed" if mid not in now else "changed"
            out.append(f"{(now.get(mid) or rec.get(mid))['slot_id']}: line decision {what} since staging")
    takes = {t["take_id"]: t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag}
    recorded = {t["take_id"]: t for t in prov["takes"]}
    for tid in sorted(recorded.keys() - takes.keys()):
        out.append(f"{tid}: removed since staging")
    for tid in sorted(takes.keys() - recorded.keys()):
        out.append(f"{tid}: added since staging (not part of the staged set)")
    plan = {e["take_id"]: e for e in insert_plan}
    for tid in sorted(takes.keys() & recorded.keys()):
        if recorded[tid].get("spec_sha256") != spec_digest(takes[tid]["audio"]):
            out.append(f"{tid}: its recording or recipe changed since staging")
        e = plan.get(tid)
        if not e or e["action"] != "insert":
            out.append(f"{tid}: {(e or {}).get('reason', 'not planned')}")
    if not takes:
        out.append("the set has no take")
    return out


def activate(doc, tag, *, today, insert_plan, eligible=(True, ""), subtitle_problem=None):
    """Switch a staged sound to its replacement set. -> steps [(doc, user_actions)] for mapping_store.save_sequence.
    Refused (ConversionError, nothing changes) on any switch_problems(). Approved line decisions are first marked
    Needs rework (the only allowed change to an approved object), then removed: they live on in the provenance. It
    changes the decisions only; installed game files are never touched (a build and an install are separate)."""
    from .mapping_store import UserAction
    problems = switch_problems(doc, tag, insert_plan=insert_plan, eligible=eligible,
                               subtitle_problem=subtitle_problem)
    if problems:
        raise ConversionError(409, "the sound cannot be switched yet; nothing changed", problems)
    now = sorted((m for m in doc["slots"] if m["mcc_tag"] == tag), key=lambda m: m["mapping_id"])
    actions = [UserAction("needs_rework", m["mapping_id"], f) for m in now for f in ("audio", "subtitle")
               if m[f]["status"] == "approved"]
    steps = []
    if actions:
        step = copy.deepcopy(doc)
        for m in step["slots"]:
            if m["mcc_tag"] == tag:
                for f in ("audio", "subtitle"):
                    if m[f]["status"] == "approved":
                        m[f].update(status="needs_rework", revision=m[f]["revision"] + 1, approved_at=None,
                                    fingerprint=None)
        steps.append((step, actions))
    final = copy.deepcopy(steps[-1][0] if steps else doc)
    final["slots"] = [m for m in final["slots"] if m["mcc_tag"] != tag]
    fo = _own(final, tag)
    fo.pop("state")
    fo["provenance"]["activated_at"] = today
    steps.append((final, []))
    return steps


def _remove_takes_steps(doc, take_ids):
    """Steps that remove `take_ids` (approved ones marked Needs rework first) -> (steps, last doc)."""
    from .mapping_store import UserAction
    take_ids = set(take_ids)
    actions = [UserAction("needs_rework", t["take_id"], "audio") for t in doc.get("added_takes", [])
               if t["take_id"] in take_ids and t["audio"]["status"] == "approved"]
    steps, cur = [], doc
    if actions:
        cur = copy.deepcopy(doc)
        for t in cur["added_takes"]:
            if t["take_id"] in take_ids and t["audio"]["status"] == "approved":
                t["audio"].update(status="needs_rework", revision=t["audio"]["revision"] + 1, approved_at=None,
                                  fingerprint=None)
        steps.append((cur, actions))
    final = copy.deepcopy(cur)
    kept = [t for t in final.get("added_takes", []) if t["take_id"] not in take_ids]
    for tag in {t["mcc_tag"] for t in final.get("added_takes", []) if t["take_id"] in take_ids}:
        for k, t in enumerate(sorted((t for t in kept if t["mcc_tag"] == tag), key=lambda t: t["position"])):
            t["position"] = k + 1
    final["added_takes"] = kept
    if not kept:
        final.pop("added_takes", None)
    return steps, final


def rework_set_subtitle_steps(doc, tag):
    """Before a set is removed (cancel, undo, back to Spain's takes): its approved subtitle is first marked Needs
    rework, a user action (revision + 1), as the store requires. -> (steps, last doc)."""
    from .mapping_store import UserAction
    o = _own(doc, tag)
    sub = (o or {}).get("subtitle")
    if not sub or sub["status"] != "approved":
        return [], doc
    new = copy.deepcopy(doc)
    _own(new, tag)["subtitle"].update(status="needs_rework", revision=sub["revision"] + 1, approved_at=None,
                                      fingerprint=None)
    return [(new, [UserAction("needs_rework", tag, "subtitle")])], new


def _drop_own(doc, tag):
    doc["own_sets"] = [o for o in doc.get("own_sets", []) if o["mcc_tag"] != tag]
    if not doc["own_sets"]:
        doc.pop("own_sets")


def cancel(doc, tag):
    """Cancel a staged conversion: its created takes are removed (approved ones through an explicit Needs rework step
    in the same save) and the staged set goes; the line decisions were never touched. -> steps."""
    o, prov = _staged(doc, tag)
    created = [t["take_id"] for t in prov["takes"] if t["origin"] == "created"]
    first, cur = rework_set_subtitle_steps(doc, tag)
    steps, final = _remove_takes_steps(cur, created)
    _drop_own(final, tag)
    steps = first + steps
    steps.append((final, []))
    return steps


def revert_plan(doc, tag, *, local, recovery, slot_ids, ce_idx, mcc_idx, rework_drifted=False):
    """Undo of an active replacement set that has a record, planned and checked before anything changes.

    Faithful restore: every recorded line decision comes back exactly as it was, approvals included (each restored
    approval is a 'restore' user action the store accepts only for the exact recorded object of the record being
    undone). The takes the record created leave the sound (approved ones through Needs rework, same save); their IDs
    stay in the history and are never reused. Takes the sound had before stay as they are now.

    Conflicts (nothing changes while there is one):
      take_added_after       a take joined the set after it was made (undoing would add it to Spain's takes)
      slot_not_in_catalog    a recorded Spain take is no longer in the catalog
      slot_decided           a recorded Spain take has a decision now
      mapping_id_in_use      the recorded decision's ID now belongs to another line
      approval_drift         a recorded approval no longer matches the current catalogs (rework_drifted=True brings
                             only those back as Needs rework instead: the owner's explicit choice)
      local_text_changed     a custom subtitle (or user recording) in manual_mappings.local.json differs from the
                             recovery snapshot: it is never overwritten
      local_text_unrecoverable  the text is missing locally and the snapshot cannot restore it (absent or corrupt)
      custom_ref_in_use      a recorded custom subtitle ref is now used by another line
    recovery: the take_set_recovery.local.json document. -> plan (with "steps" only when there is no conflict)."""
    o = _own(doc, tag)
    if o is None or not is_active(o):
        raise ConversionError(409, "this sound has no active replacement set")
    prov = o.get("provenance")
    if not prov:
        raise ConversionError(409, "this set has no record of the decisions it replaced (made before 2026-10-18); "
                                   "use 'Back to Spain's takes' instead")
    conflicts, notes = [], []
    created = {t["take_id"] for t in prov["takes"] if t["origin"] == "created"}
    known = {t["take_id"] for t in prov["takes"]}
    tag_takes = {t["take_id"]: t for t in doc.get("added_takes", []) if t["mcc_tag"] == tag}
    for tid in sorted(tag_takes.keys() - known):
        conflicts.append({"code": "take_added_after", "detail": f"{tid} joined the set after it was made; remove it first"})
    before = {t["take_id"]: t for t in prov["added_takes"]}
    for tid in sorted(before):
        now = tag_takes.get(tid)
        if now is None:
            notes.append(f"{tid} (a take the sound had before) was removed since; it stays removed")
        elif now != before[tid]:
            notes.append(f"{tid} (a take the sound had before) changed since ({now['audio']['status']}, revision "
                         f"{now['audio']['revision']}); it is kept as it is now")
    current_ids = {m["mapping_id"]: m for m in doc["slots"]}
    decided = {m["slot_id"] for m in doc["slots"]}
    used_custom = {m["subtitle"].get("custom_ref") for m in doc["slots"]} - {None}
    rec = ((recovery or {}).get("records") or {}).get(prov["record_id"]) or {}
    texts = dict((local or {}).get("custom_subtitles") or {})
    recs = dict((local or {}).get("user_recordings") or {})
    local_restore = {"custom_subtitles": {}, "user_recordings": {}}
    for c in prov["custom_subtitles"]:
        ref, want = c["custom_ref"], c["text_sha256"]
        if ref in used_custom:
            conflicts.append({"code": "custom_ref_in_use", "detail": f"{ref} is now used by another line"})
        cur = (texts.get(ref) or {}).get("text")
        snap = (rec.get("custom_subtitles") or {}).get(ref)
        snap_ok = bool(snap) and sha256_text(snap["text"]) == want == snap.get("text_sha256")
        if cur is not None:
            if sha256_text(cur) != want:
                conflicts.append({"code": "local_text_changed",
                                  "detail": f"custom subtitle {ref} changed after the record; it is not overwritten"})
        elif want is None:
            pass  # it was already missing when recorded
        elif snap_ok:
            local_restore["custom_subtitles"][ref] = {"text": snap["text"], "updated_at": snap["updated_at"]}
            texts[ref] = local_restore["custom_subtitles"][ref]
        else:
            conflicts.append({"code": "local_text_unrecoverable",
                              "detail": f"custom subtitle {ref} is missing and the recovery snapshot cannot restore it"})
    _customs, recordings = local_refs(prov["slots"])
    for r in recordings:
        cur, snap = recs.get(r), (rec.get("user_recordings") or {}).get(r)
        if cur is not None and snap is not None and cur != snap:
            conflicts.append({"code": "local_text_changed", "detail": f"user recording {r} changed after the record"})
        elif cur is None and snap is not None:
            local_restore["user_recordings"][r] = dict(snap)
            recs[r] = snap
        elif cur is None:
            conflicts.append({"code": "local_text_unrecoverable", "detail": f"user recording {r} is missing"})
    view_local = {"custom_subtitles": texts, "user_recordings": recs}
    restore, drifted = [], []
    for m in prov["slots"]:
        if m["slot_id"] not in slot_ids:
            conflicts.append({"code": "slot_not_in_catalog", "detail": f"{m['slot_id']} is no longer a Spain take of this sound"})
        if m["slot_id"] in decided:
            conflicts.append({"code": "slot_decided", "detail": f"{m['slot_id']} has a decision now"})
        if m["mapping_id"] in current_ids:
            conflicts.append({"code": "mapping_id_in_use",
                              "detail": f"{m['mapping_id']} now belongs to {current_ids[m['mapping_id']]['slot_id']}"})
        row = {"mapping_id": m["mapping_id"], "slot_id": m["slot_id"]}
        for f, fn in (("audio", audio_fingerprint), ("subtitle", subtitle_fingerprint)):
            st = m[f]["status"]
            if st == "approved" and m[f]["fingerprint"] != fn(m, ce_idx, mcc_idx, view_local):
                drifted.append(f"{m['mapping_id']}/{f}")
                row[f] = "needs rework (approval drifted)" if rework_drifted else "approval drifted"
            else:
                row[f] = "approval restored" if st == "approved" else st
        restore.append(row)
    if drifted and not rework_drifted:
        conflicts.append({"code": "approval_drift", "detail": "approvals that no longer match the catalogs: "
                          + ", ".join(drifted)})
    plan = {"record_id": prov["record_id"], "kind": prov["kind"], "restore": restore, "drifted": drifted,
            "remove_takes": sorted(created & tag_takes.keys()),
            "keep_takes": sorted(tag_takes.keys() - created), "notes": notes, "local_restore": local_restore,
            "conflicts": conflicts, "rework_drifted": bool(rework_drifted)}
    if conflicts:
        return plan
    from .mapping_store import UserAction
    first, cur = rework_set_subtitle_steps(doc, tag)  # the set's own subtitle goes with the set
    steps, final = _remove_takes_steps(cur, created)
    steps = first + steps
    actions = []
    for m in prov["slots"]:
        body = copy.deepcopy(m)
        for f in ("audio", "subtitle"):
            if body[f]["status"] != "approved":
                continue
            if f"{m['mapping_id']}/{f}" in drifted:
                body[f].update(status="needs_rework", revision=body[f]["revision"] + 1, approved_at=None,
                               fingerprint=None)
            else:
                actions.append(UserAction("restore", m["mapping_id"], f))
        final["slots"].append(body)
    _drop_own(final, tag)
    steps.append((final, actions))
    plan["steps"] = steps
    return plan


def plan_token(plan, sound_version):
    """What the owner confirms: the planned undo and the sound version it was planned from."""
    return digest({"sound_version": sound_version, "plan": {k: v for k, v in plan.items() if k != "steps"}})


# --------------------------------------------------------------------------- inventory (read-only)
def inventory(doc, records, *, subtitle_keys, ce_lines, ce_idx, mcc_idx, local=None, tags=None):
    """Every multi-take sound with something to look at (a decision, an added take or an own set), previewed, plus
    every sound that has an own set whatever its number of Spain takes (an own set on a single-take sound is listed
    with single_take: true and counted apart, never hidden). records: {mcc_tag: (level, record)}.
    -> {"sounds": [...], "counts": {...}}: multi_take_sounds / untouched / <status> count multi-take sounds only;
    own_sets_single_take counts the others. Never writes."""
    from .mcc_loc import loc_key
    touched = {m["mcc_tag"] for m in doc["slots"]} | {t["mcc_tag"] for t in doc.get("added_takes", [])} \
        | {o["mcc_tag"] for o in doc.get("own_sets", [])}
    own = {o["mcc_tag"] for o in doc.get("own_sets", [])}
    counts = {"multi_take_sounds": 0, "untouched": 0, "own_sets_single_take": 0}
    sounds = []
    for tag in sorted(records):
        level, rec = records[tag]
        if tags is not None and tag not in tags:
            continue
        single = len(rec["samples"]["spanish"]) < 2
        if single and tag not in own:
            continue
        if not single:
            counts["multi_take_sounds"] += 1
            if tag not in touched:
                counts["untouched"] += 1
                continue
        item = plan_sound(doc, tag, rec, level, has_subtitle_entry=loc_key(tag) in subtitle_keys, ce_lines=ce_lines,
                          ce_idx=ce_idx, mcc_idx=mcc_idx, local=local, subtitle_keys=subtitle_keys)
        item["single_take"] = single
        if single:
            counts["own_sets_single_take"] += 1
        else:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        sounds.append(item)
    return {"schema": PREVIEW_SCHEMA, "sounds": sounds, "counts": counts}
