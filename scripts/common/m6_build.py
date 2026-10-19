"""M6 batch build (first limited proof of concept): approved M4 decisions -> candidate MCC files.

Pure logic; the CLI (scripts/build/m6_build.py) does the I/O, encoding and decoding. Nothing here
changes a mapping, approves anything or pairs lines: the only input is what the owner approved in
mappings/manual_mappings.json (read through mapping_store.load).

Audio eligibility (per mapping in the selected levels):
  replace         audio approved, source `ce` (one CE line), mono slot, the CE line has resolved
                  media in that language, the approved fingerprint still equals the current one (no
                  drift), and its edit recipe (if any) is valid and made for that source. The
                  target is the slot's index in the SPANISH bank's own name table (from the MCC
                  catalog), never an English index. An edited line carries its recipe (`edit`);
                  the CLI renders it with common/audio_edit, exactly as the M4 preview does.
  keep_original   audio approved as "keep Spain" -> sample preserved byte for byte.
  replace (two)   the same for a join (`ce_concat`) or an overlay (`ce_mix`) of two CE lines: both resolved, a valid
                  combine recipe made for exactly those two (common/audio_combine.py); the entry carries `sources`
                  and the CLI renders it with audio_pipeline.derive_combined (docs/combine-recordings.md).
  mute            audio approved as "Mute / No replacement", mono slot, no drift, no recipe -> the sample
                  becomes digital silence of exactly its original sample count (common/audio_pipeline.
                  silent_stream: MCC's own CELT silence packet, so the stream keeps its exact byte length).
  dropped         the sound plays its own take set (docs/custom-take-set-design.md) and at least one of its added
                  takes is inserted: the sound's Spain samples are removed from the bank and the Spanish index.
  not_eligible    draft / needs_rework / unsupported (ce_concat, user_recording, composite, stereo,
                  gap on one line) / invalid (drift, unresolved media, test event, bad recipe) -> sample
                  preserved, reason
                  reported. Nothing is approved or changed to make it eligible.
Subtitles are planned independently of audio (`subtitle_plan`): approved decisions only, key by key, for
SU and SP separately; common/mcc_loc_writer writes the tables (variable length, docs/m6-build.md §4).
"""
import json
from collections import Counter, defaultdict

from . import audio_combine, audio_edit
from .fsb5_lib import parse_header
from .fsb5_writer import ALIGN, build, decompose, replace_sample, sample_spans
from .mcc_loc import loc_key, parse_mcc_loc
from .own_set_state import active_own_tags, staged_take_ids
from .project_validation import added_take_fingerprint, audio_fingerprint, subtitle_fingerprint

PLAN_SCHEMA = "m6-build-plan/1"


def _flag(m, name, key):
    return bool((m.get(name) or {}).get(key))


def own_set_drops(doc, insert_entries):
    """Sounds whose Spain samples a build removes: in own-take-set mode with at least one take to insert. A sound
    in that mode without an insertable take keeps Spain's takes (never an empty sound). A staged conversion
    (docs/replacement-set-conversion.md) is not in force: its sound plays as before."""
    own = active_own_tags(doc)
    return sorted(own & {e["mcc_tag"] for e in insert_entries if e["action"] == "insert"})


def plan_audio(doc, levels, *, slot_index, ce_lines, ce_idx, mcc_idx, local=None, dropped_tags=()):
    """-> {"entries": [...], "conflicts": [...]} for every Spanish slot in `levels` (mapped or not).
    dropped_tags: own_set_drops(); their slots get the action `dropped`."""
    dropped_tags = set(dropped_tags)
    own = active_own_tags(doc)
    levels = set(levels)
    by_slot = defaultdict(list)
    for m in doc["slots"]:
        by_slot[m["slot_id"]].append(m)
    entries, conflicts = [], []
    for sid, (level, rec, sample) in slot_index.items():
        if level not in levels:
            continue
        ms = by_slot.get(sid, [])
        e = {"slot_id": sid, "level": level, "mcc_tag": rec["mcc_tag"], "spanish_index": sample["index"],
             "channels": sample["channels"], "original_sample_count": sample["sample_count"],
             "original_seconds": sample["duration_s"], "mapping_id": None, "action": "keep_original",
             "reason": "no mapping (Spain audio stays)", "radio_effect": False, "different_but_fits": False,
             "edit": None}
        if rec["mcc_tag"] in dropped_tags:
            e.update(action="dropped", reason="own take set: Spain's take is removed (the sound plays its own takes)",
                     mapping_id=ms[0]["mapping_id"] if ms else None)
            entries.append(e)
            continue
        if rec["mcc_tag"] in own and not ms:
            e["reason"] = "own take set without an approved take yet: Spain audio stays"
        if len(ms) > 1:
            conflicts.append({"code": "duplicate_mapping_for_slot", "slot_id": sid,
                              "mapping_ids": [m["mapping_id"] for m in ms]})
            e.update(action="not_eligible", reason="conflict: several mappings for this slot")
            entries.append(e)
            continue
        if not ms:
            entries.append(e)
            continue
        m = ms[0]
        a = m["audio"]
        e.update(mapping_id=m["mapping_id"], match_status=m["match"]["status"], audio_status=a["status"],
                 audio_source=a["source"], radio_effect=_flag(m, "radio_effect", "needed"),
                 different_but_fits=_flag(m, "different_but_fits", "marked"))
        if m["mcc_tag"] != rec["mcc_tag"]:
            e.update(action="not_eligible", reason=f"invalid: mapping tag {m['mcc_tag']} != catalog tag")
        elif a["status"] != "approved":
            e.update(action="keep_original", reason=f"audio {a['status']} (not approved): Spain audio stays")
        elif a["source"] == "keep_original":
            e.update(action="keep_original", reason="approved: keep Spain audio")
        elif a["source"] == "mute":
            if sample["channels"] != 1:
                e.update(action="not_eligible", reason="unsupported: stereo slot (stereo replacement deferred)")
            elif m["match"]["status"] != "no_equivalent":
                e.update(action="not_eligible", reason="invalid: a muted line must be marked 'no equivalent'")
            elif not audio_edit.is_identity(a["edit"]):
                e.update(action="not_eligible", reason="invalid: a muted line has no edit recipe")
            elif a["fingerprint"] != audio_fingerprint(m, ce_idx, mcc_idx, local):
                e.update(action="not_eligible",
                         reason="invalid: approved fingerprint no longer matches the catalogs (drift); rework it")
            else:
                e.update(action="mute", reason="approved: mute (silence of the original length)",
                         mute_reason=a.get("mute_reason"))
        elif a["source"] in audio_combine.MODE_OF:
            e.update(_plan_combined(m, sample, ce_lines, ce_idx, mcc_idx, local))
        elif a["source"] != "ce":
            e.update(action="not_eligible", reason=f"unsupported in this build: audio source {a['source']}")
        elif sample["channels"] != 1:
            e.update(action="not_eligible", reason="unsupported: stereo slot (stereo replacement deferred)")
        elif a["edit"].get("gap_s"):
            e.update(action="not_eligible", reason="unsupported: a gap applies only between concatenated lines")
        elif len(a["sources"]) != 1 or a["sources"][0]["kind"] != "ce":
            e.update(action="not_eligible", reason="invalid: source 'ce' needs exactly one CE line")
        else:
            src = a["sources"][0]
            ref, lang = src["ce_line_ref"], src["language"]
            line = ce_lines.get(ref)
            media = ((line[2]["media"].get(lang) or {}) if line else {})
            if not line:
                e.update(action="not_eligible", reason=f"invalid: unknown CE line {ref}")
            elif "test_event" in line[1]["flags"]:
                e.update(action="not_eligible", reason=f"invalid: {ref} is a test event")
            elif media.get("evidence") != "explicit" or len(media.get("media", [])) != 1:
                e.update(action="not_eligible", reason=f"invalid: {ref} has no single resolved {lang} media")
            elif a["fingerprint"] != audio_fingerprint(m, ce_idx, mcc_idx, local):
                e.update(action="not_eligible",
                         reason="invalid: approved fingerprint no longer matches the catalogs (drift); rework it")
            elif edit_problems(a["edit"], ref, lang):
                e.update(action="not_eligible",
                         reason="invalid: edit recipe: " + "; ".join(edit_problems(a["edit"], ref, lang)))
            else:
                edited = not audio_edit.is_identity(a["edit"])
                e.update(action="replace", reason="approved CE audio" + (" (edited)" if edited else ""),
                         ce_line_ref=ref, language=lang, ce_mission=line[0], media=media["media"][0],
                         edit=a["edit"] if edited else None,
                         edit_summary=audio_edit.summary(a["edit"]) if edited else None)
        entries.append(e)
    targets = Counter(e["spanish_index"] for e in entries if e["action"] == "replace")
    for idx, n in targets.items():
        if n > 1:
            conflicts.append({"code": "duplicate_target_index", "spanish_index": idx})
            for e in entries:
                if e["spanish_index"] == idx and e["action"] == "replace":
                    e.update(action="not_eligible", reason="conflict: several replacements for one bank sample")
    entries.sort(key=lambda e: e["spanish_index"])
    return {"schema": PLAN_SCHEMA, "levels": sorted(levels), "entries": entries, "conflicts": conflicts}


def _plan_combined(m, sample, ce_lines, ce_idx, mcc_idx, local):
    """The plan fields of an approved join / overlay (two CE lines in one replacement)."""
    a = m["audio"]
    word = "join" if a["source"] == "ce_concat" else "overlay"
    if sample["channels"] != 1:
        return {"action": "not_eligible", "reason": "unsupported: stereo slot (stereo replacement deferred)"}
    if len(a["sources"]) != 2 or any(s.get("kind") != "ce" for s in a["sources"]):
        return {"action": "not_eligible", "reason": f"unsupported: a {word} needs exactly two CE lines"}
    srcs = []
    for s in a["sources"]:
        ref, lang = s["ce_line_ref"], s["language"]
        line = ce_lines.get(ref)
        media = ((line[2]["media"].get(lang) or {}) if line else {})
        if not line:
            return {"action": "not_eligible", "reason": f"invalid: unknown CE line {ref}"}
        if "test_event" in line[1]["flags"]:
            return {"action": "not_eligible", "reason": f"invalid: {ref} is a test event"}
        if media.get("evidence") != "explicit" or len(media.get("media", [])) != 1:
            return {"action": "not_eligible", "reason": f"invalid: {ref} has no single resolved {lang} media"}
        srcs.append({"ce_line_ref": ref, "language": lang, "ce_mission": line[0], "media": media["media"][0]})
    if a["fingerprint"] != audio_fingerprint(m, ce_idx, mcc_idx, local):
        return {"action": "not_eligible",
                "reason": "invalid: approved fingerprint no longer matches the catalogs (drift); rework it"}
    edit = a["edit"]
    probs = (["the recipe is not a join/overlay recipe"] if not audio_combine.is_combine(edit)
             else [f"the recipe is a {edit.get('mode')}, the source a {word}"]
             if edit.get("mode") != audio_combine.MODE_OF[a["source"]]
             else audio_combine.problems(edit, sources=a["sources"]))
    if probs:
        return {"action": "not_eligible", "reason": "invalid: recipe: " + "; ".join(probs)}
    first = srcs[0]
    return {"action": "replace", "reason": f"approved CE {word} of two lines", "ce_line_ref": first["ce_line_ref"],
            "language": first["language"], "ce_mission": first["ce_mission"], "media": first["media"],
            "sources": srcs, "combine": edit["mode"], "edit": edit, "edit_summary": audio_combine.summary(edit)}


def plan_inserts(doc, levels, *, slot_index, ce_lines, ce_idx, mcc_idx, local=None, subtitle_keys=None):
    """Approved added takes of the sounds in `levels` -> one entry each (docs/added-takes-design.md):
      insert        approved, its sound mono and without a subtitle entry, one resolved CE line, no drift, a valid
                    recipe made for that line -> inserted after the sound's Spain takes, in position order
      skip          draft / needs_rework, or created by a staged conversion that is not switched on yet
                    (docs/replacement-set-conversion.md): left out (reported)
      not_eligible  invalid (reason reported). Nothing is approved or changed here."""
    levels = set(levels)
    own, staged = active_own_tags(doc), staged_take_ids(doc)
    tags = {}
    for _sid, (lv, rec, _smp) in slot_index.items():
        tags.setdefault(rec["mcc_tag"], (lv, rec))
    out = []
    for t in sorted(doc.get("added_takes", []), key=lambda t: (t["mcc_tag"], t["position"])):
        hit = tags.get(t["mcc_tag"])
        if not hit or hit[0] not in levels:
            continue
        lv, rec = hit
        sp = rec["samples"]["spanish"]
        a = t["audio"]
        e = {"take_id": t["take_id"], "mcc_tag": t["mcc_tag"], "level": lv, "position": t["position"],
             "own_set": t["mcc_tag"] in own,
             "spain_takes": len(sp), "ref_slot_id": sp[0]["slot_id"], "audio_status": a["status"],
             "radio_effect": bool(t["radio_effect"]["needed"]), "action": "not_eligible", "reason": "", "edit": None}
        src = (a["sources"] or [{}])[0]
        ref, lang = src.get("ce_line_ref"), src.get("language")
        line = ce_lines.get(ref)
        media = ((line[2]["media"].get(lang) or {}) if line else {})
        if t["take_id"] in staged:
            e.update(action="skip", reason="staged replacement set: inserted only after the sound is switched to its "
                                           f"set (audio {a['status']})")
        elif a["status"] != "approved":
            e.update(action="skip", reason=f"audio {a['status']} (not approved): not inserted")
        elif any(x["channels"] != 1 for x in sp):
            e.update(reason="unsupported: stereo sound (stereo replacement deferred)")
        elif subtitle_keys is not None and loc_key(t["mcc_tag"]) in subtitle_keys:
            e.update(reason="invalid: the sound has a subtitle entry (added takes are for sounds without one)")
        elif len(a["sources"]) != 1 or src.get("kind") != "ce":
            e.update(reason="invalid: an added take needs exactly one CE line")
        elif not line:
            e.update(reason=f"invalid: unknown CE line {ref}")
        elif "test_event" in line[1]["flags"]:
            e.update(reason=f"invalid: {ref} is a test event")
        elif media.get("evidence") != "explicit" or len(media.get("media", [])) != 1:
            e.update(reason=f"invalid: {ref} has no single resolved {lang} media")
        elif a["fingerprint"] != added_take_fingerprint(t, ce_idx, mcc_idx, local):
            e.update(reason="invalid: approved fingerprint no longer matches the catalogs (drift); rework it")
        elif edit_problems(a["edit"], ref, lang):
            e.update(reason="invalid: edit recipe: " + "; ".join(edit_problems(a["edit"], ref, lang)))
        else:
            edited = not audio_edit.is_identity(a["edit"])
            e.update(action="insert", reason="approved added take" + (" (edited)" if edited else ""),
                     ce_line_ref=ref, language=lang, ce_mission=line[0], media=media["media"][0],
                     edit=a["edit"] if edited else None,
                     edit_summary=audio_edit.summary(a["edit"]) if edited else None)
        out.append(e)
    return out


def insert_takes(bank, lst_bytes, inserts, drop_tags=()):
    """bank (FSB5 bytes, any replacements already applied), the Spanish index (.lst.bin bytes) and
    inserts [{"take_id", "mcc_tag", "stream", "sample_count"}] in position order -> (bank bytes, lst bytes,
    index_map [original index -> new index, None for a removed sample], {take_id: new index}).

    drop_tags: sounds in own-take-set mode; their own samples are left out, so the sound holds only its inserted
    takes (each must have at least one).

    Each sound's added takes go right after its own samples; the index gets the new counts and shifted
    starts. A new sample copies the head bits of its sound's first sample (frequency, mono) and gets a LOOP
    chunk 0, n-2 like every MCC dialogue sample, and a unique name (`LATAM t000001`)."""
    from .fsb5_writer import loop_chunk
    from .mcc_lst import build_lst, check_ranges, parse_lst
    model = decompose(bank)
    lst = parse_lst(lst_bytes)
    if not check_ranges(lst["records"], len(model["samples"]))["contiguous_from_zero"]:
        raise ValueError("the sound index is not contiguous; refusing to insert")
    by_tag = defaultdict(list)
    for x in inserts:
        by_tag[x["mcc_tag"]].append(x)
    unknown = (set(by_tag) | set(drop_tags)) - {t for t, _, _ in lst["records"]}
    if unknown:
        raise ValueError(f"sounds not in the index: {sorted(unknown)}")
    empty = sorted(t for t in drop_tags if not by_tag.get(t))
    if empty:
        raise ValueError(f"refusing to remove every take of {empty}: no take to insert")
    samples, names, records, index_map, new_index = [], [], [], [], {}
    for tag, first, count in lst["records"]:
        start = len(samples)
        for i in range(first, first + count):
            if tag in drop_tags:
                index_map.append(None)
                continue
            index_map.append(len(samples))
            samples.append(model["samples"][i])
            names.append(model["names"][i])
        template = model["samples"][first]
        for x in by_tag.get(tag, []):
            name = f"LATAM {x['take_id'].replace('-', '')}".encode()
            if name in model["names"] or name in names:
                raise ValueError(f"{name!r} is already in the bank")
            new_index[x["take_id"]] = len(samples)
            samples.append({"head_bits": template["head_bits"], "sample_count": x["sample_count"],
                            "channels": template["channels"], "stream": x["stream"],
                            "chunks": [loop_chunk(x["sample_count"]) if ct == 3 else (ct, pl)
                                       for ct, pl in template["chunks"]]})
            names.append(name)
        records.append((tag, start, len(samples) - start))
    new = dict(model, samples=samples, names=names)
    return build(new), build_lst(lst["version"], records), index_map, new_index


def insert_checks(base, cand, lst_old, lst_new, index_map, new_index, inserts, drop_tags=()):
    """Independent checks of insert_takes: `cand` == `base` with the inserts added (and the samples of drop_tags
    removed), and the index consistent."""
    from .mcc_lst import build_lst, check_ranges, parse_lst
    mb, mc = decompose(base), decompose(cand)
    lo, ln = parse_lst(lst_old), parse_lst(lst_new)
    by_tag = defaultdict(int)
    for x in inserts:
        by_tag[x["mcc_tag"]] += 1
    rng = check_ranges(ln["records"], len(mc["samples"]))
    drop = set(drop_tags)
    dropped = {i for t, f, n in lo["records"] if t in drop for i in range(f, f + n)}
    kept = lambda o: 0 if o[0] in drop else o[2]  # noqa: E731
    return {
        "insert:round_trip": build(mc) == cand,
        "insert:sample_count": len(mc["samples"]) == len(mb["samples"]) + len(inserts) - len(dropped),
        "insert:removed_exactly_the_own_set_sounds": {i for i, j in enumerate(index_map) if j is None} == dropped,
        "insert:header_tail_unchanged": mc["header_tail"] == mb["header_tail"] and mc["mode"] == mb["mode"],
        "insert:every_existing_sample_byte_identical_at_its_new_place": all(
            mc["samples"][index_map[i]] == s and mc["names"][index_map[i]] == mb["names"][i]
            for i, s in enumerate(mb["samples"]) if index_map[i] is not None),
        "insert:inserted_streams_and_counts": all(
            mc["samples"][new_index[x["take_id"]]]["stream"] == x["stream"]
            and mc["samples"][new_index[x["take_id"]]]["sample_count"] == x["sample_count"] for x in inserts),
        "insert:inserted_loop_0_n_minus_2": all(
            all(pl == (0).to_bytes(4, "little") + (x["sample_count"] - 2).to_bytes(4, "little")
                for ct, pl in mc["samples"][new_index[x["take_id"]]]["chunks"] if ct == 3) for x in inserts),
        "insert:lst_writer_reproduces_the_original_index": build_lst(lo["version"], lo["records"]) == lst_old,
        "insert:lst_same_tags_same_order": [r[0] for r in ln["records"]] == [r[0] for r in lo["records"]],
        "insert:lst_contiguous_and_covers_the_bank": rng["contiguous_from_zero"] and rng["total_matches_bank"],
        "insert:lst_counts": all(n[2] == kept(o) + by_tag.get(o[0], 0) for o, n in zip(lo["records"], ln["records"])),
        "insert:own_set_sounds_hold_only_their_takes": all(
            n[2] == by_tag.get(o[0], 0) > 0 and all(new_index[x["take_id"]] in range(n[1], n[1] + n[2])
                                                    for x in inserts if x["mcc_tag"] == o[0])
            for o, n in zip(lo["records"], ln["records"]) if o[0] in drop),
        "insert:every_sound_resolves_to_its_old_samples_first": all(
            [mc["samples"][j] for j in range(n[1], n[1] + kept(o))]
            == [mb["samples"][i] for i in range(o[1], o[1] + kept(o))]
            for o, n in zip(lo["records"], ln["records"])),
    }


def compare_inserts(built, current):
    """Added takes a build inserted vs the current plan: changed_or_revoked (do not install; rebuild) and
    newly_eligible (only missing)."""
    def key(e):
        return (e.get("ce_line_ref"), e.get("language"), (e.get("media") or {}).get("wem_sha256"),
                json.dumps(e.get("edit"), sort_keys=True))
    cur = {e["take_id"]: e for e in current if e["action"] == "insert"}
    was = {e["take_id"]: e for e in built if e["action"] == "insert"}
    return {"changed_or_revoked": sorted(t for t, e in was.items() if t not in cur or key(cur[t]) != key(e)),
            "newly_eligible": sorted(t for t in cur if t not in was)}


def edit_problems(edit, ref, lang):
    """Static recipe problems for one CE source (the timeline is checked when rendering). Includes
    removed fields (speed, gain_db) still stored before the one-time migration."""
    out = audio_edit.problems(edit)
    if audio_edit.is_identity(edit):
        return out
    if edit.get("for_source") != {"ce_line_ref": ref, "language": lang}:
        out.append("made for another CE line or language")
    return out


FOLDER_GROUPS = ("replace", "muted", "dropped", "approved_keep_spain", "not_approved", "unmapped", "unsupported",
                 "invalid")
BUILT_ACTIONS = ("replace", "mute", "dropped")  # actions that change a bank sample


def entry_group(e):
    """Report group of one planned slot (per folder, owner request 2026-10-08)."""
    if e["action"] == "replace":
        return "replace"
    if e["action"] == "mute":
        return "muted"
    if e["action"] == "dropped":
        return "dropped"
    if e["mapping_id"] is None:
        return "unmapped"
    if e["action"] == "not_eligible":
        return "unsupported" if e["reason"].startswith("unsupported") else "invalid"
    if e["reason"].startswith("approved"):
        return "approved_keep_spain"
    return "not_approved"


def folder_summary(entries):
    """{folder: {group: count, slots, stereo, stereo_replaced}} in catalog-folder order."""
    out = {}
    for e in entries:
        f = out.setdefault(e["level"], {**{g: 0 for g in FOLDER_GROUPS}, "slots": 0, "stereo": 0,
                                        "stereo_replaced": 0})
        f[entry_group(e)] += 1
        f["slots"] += 1
        f["stereo"] += e["channels"] > 1
        f["stereo_replaced"] += e["channels"] > 1 and e["action"] in BUILT_ACTIONS
    return out


def _built_key(e):
    """What a built slot depends on: same action, mapping, source media and edit recipe -> same sample."""
    return (e["action"], e.get("mapping_id"), e.get("ce_line_ref"), e.get("language"),
            (e.get("media") or {}).get("wem_sha256"), json.dumps(e.get("edit"), sort_keys=True),
            json.dumps([(s["ce_line_ref"], s["language"], s["media"].get("wem_sha256")) for s in e["sources"]])
            if e.get("sources") else None)


def compare_plans(built_entries, current_entries):
    """Built plan vs a plan from the current mappings.
    -> {"changed_or_revoked": [...], "newly_eligible": [...]}: the first means the build no longer matches
    an approved decision (do not install; rebuild); the second only means newer approvals are missing."""
    cur = {e["slot_id"]: e for e in current_entries}
    changed, new = [], []
    for e in built_entries:
        c = cur.get(e["slot_id"])
        if e["action"] in BUILT_ACTIONS and (c is None or _built_key(c) != _built_key(e)):
            changed.append(e["slot_id"])
        elif e["action"] not in BUILT_ACTIONS and c is not None and c["action"] in BUILT_ACTIONS:
            new.append(e["slot_id"])
    return {"changed_or_revoked": changed, "newly_eligible": new}


def mission_folders(level_folders, mission):
    """Dialogue folders of one playable map: its own folder plus cutscene folders (xNN) used by no other
    campaign map, from work/mcc/level_folders.json (derived:map_tag_path_scan). Shared generic bark folders
    are listed separately and not selected (milestone M-SYS)."""
    lv = level_folders["levels"].get(mission)
    if not lv:
        raise ValueError(f"{mission} is not in level_folders.json (run build_level_folders.py)")
    own, cine, shared = [], [], []
    for f in lv["folders"]:
        used = level_folders["folders"][f]["used_by"]
        if f == mission:
            own.append(f)
        elif f.startswith("x") and f[1:].isdigit() and used == [mission]:
            cine.append(f)
        else:
            shared.append(f)
    return {"selected": own + sorted(cine), "cinematics": sorted(cine), "shared_not_selected": sorted(shared),
            "evidence": lv["evidence"], "map_sha256": lv["map_sha256"]}


SUBTITLE_TABLES = ("SU", "SP")  # SU = Latin America, SP = Spain: both get the same canonical text (B1 plan)
SUBTITLE_PLAN_SCHEMA = "m6-subtitle-plan/2"
# The build baseline: hash-verified copies of the shipped tables (MCC Steam build 19905945; the same pins as
# scripts/discovery/b1_build_poc_candidates.py). Builds never read the installed files.
SUBTITLE_COPY = "work/mcc/loc/copies/{table}_Halo1.bin"
SUBTITLE_INSTALL = "Data/ui/localization/{table}_Halo1.bin"
SUBTITLE_PINS = {"SU": "247d25298af3d5f990cd20ff5177e05078173347b7bdf395c3995a59c60244d0",
                 "SP": "794deac326d401a1fb6f5de50f8979f921159a412b095a368ef5424ed4342dda"}
BUILD_KINDS = ("audio", "subtitles", "both")


def build_tables(originals, plan):
    """originals: {"SU": bytes, "SP": bytes} -> {table: (candidate bytes, writer info, checks)}.

    Each table is written from the plan (common/mcc_loc_writer), written a second time with the changes in
    reverse order (determinism, order independence), and verified independently of the writer."""
    from .mcc_loc_writer import verify_table, write_table
    out = {}
    for t, original in originals.items():
        changes = table_changes(plan, t)
        cand, info = write_table(original, changes)
        again, _ = write_table(original, dict(reversed(list(changes.items()))))
        checks = verify_table(original, cand, changes)
        checks["deterministic"] = cand == again
        baseline = parse_mcc_loc(original)["entries"]  # the plan must have been made from these very bytes
        checks["planned_old_text_matches_baseline"] = all(
            k["tables"][t]["old_text"] == baseline.get(k["key"]) for k in plan["keys"]
            if k["action"] == "write" and k["tables"][t]["write"])
        out[t] = (cand, info, checks)
    return out


def _approved_text(m, ce_lines, local):
    """The text an approved, changing subtitle decision asks for; None if it cannot be found."""
    s = m["subtitle"]
    if s["source"] == "ce_locres":
        ref, cul = s["ce_locres"]["ce_line_ref"], s["ce_locres"]["culture"]
        line = ce_lines.get(ref)
        return ((line[2]["subtitles"].get(cul) or {}).get("text")) if line else None
    if s["source"] == "custom":
        return ((local or {}).get("custom_subtitles", {}).get(s["custom_ref"]) or {}).get("text")
    return ""  # "none": the owner approved showing no subtitle -> an empty entry


def subtitle_plan(doc, levels, *, slot_index, ce_lines, ce_idx, mcc_idx, local, tables):
    """Approved subtitle decisions -> what each table gets, key by key. Writes nothing.

    tables: {"SU": parsed entries dict or None, "SP": ...} (mcc_loc.parse_mcc_loc(...)["entries"]).
    Only mappings in `levels` count. Per mapping (`rows`, `category`):
      excluded     subtitle draft / needs_rework (never applied), approved fingerprint drift, approved text
                   not found, a text a table cannot hold (NUL, control characters, too long)
      keep         approved "keep MCC text": the entry stays byte for byte
      write        approved CE es-MX / EN / custom text, or "none" (an empty entry)
      conflict     the takes of one line disagree (see below)
      missing_key  the line has no entry in SU or SP
    Several slots (takes) share one key, the tag path. All approved decisions for a key must agree: different
    texts, or a text next to an approved "keep", is a conflict and the key is left unchanged (reported, never
    guessed). An empty entry ("none", e.g. for a muted line) hides the subtitle of every take of the tag, so it
    is written only when EVERY Spanish take of the tag has an approved "none"; otherwise the key is left
    unchanged and reported (a take that still plays keeps its subtitle). Keys are looked up in each table
    independently; a key a table lacks is never added.
    Nothing is approved, changed or chosen here."""
    from .mcc_loc_writer import normalize_text, text_problems
    rows, conflicts = [], []
    by_key = defaultdict(list)
    takes_of = {}  # key -> every Spanish slot (take) of the tag, mapped or not
    for m in sorted(doc["slots"], key=lambda m: m["slot_id"]):
        hit = slot_index.get(m["slot_id"])
        if not hit or hit[0] not in levels:
            continue
        s = m["subtitle"]
        tag = hit[1]["mcc_tag"]
        key = loc_key(tag)
        takes_of.setdefault(key, set()).update(hit[1].get("slot_ids") or [m["slot_id"]])
        row = {"slot_id": m["slot_id"], "mapping_id": m["mapping_id"], "level": hit[0], "mcc_tag": tag,
               "key": key, "key_evidence": "derived:mcc_loc_key_crc32_tag_path", "status": s["status"],
               "source": s["source"], "change": False, "category": "excluded"}
        if s["status"] != "approved":
            row["result"] = f"not applied: subtitle {s['status']}"
        elif s["source"] == "keep_original":
            row.update(category="keep", result="approved: keep MCC text (no change)")
        elif s["fingerprint"] != subtitle_fingerprint(m, ce_idx, mcc_idx, local):
            row["result"] = "invalid: approved fingerprint drift; rework it"
        else:
            raw = _approved_text(m, ce_lines, local)
            if raw is None:
                row["result"] = "invalid: approved text not found"
            else:
                text, notes = normalize_text(raw)
                problems = text_problems(text)
                if problems:
                    row["result"] = "invalid text: " + "; ".join(problems)
                else:
                    row.update(category="write", change=True, text=text, normalised=notes,
                               new_utf8_bytes=len(text.encode("utf-8")),
                               result="no subtitle (approved empty entry)" if text == "" else "approved text")
        if row["category"] in ("keep", "write"):
            by_key[key].append(row)
        rows.append(row)

    keys = {}
    for key, items in sorted(by_key.items()):
        outcomes = {("keep", None) if r["category"] == "keep" else ("write", r["text"]) for r in items}
        entry = {"key": key, "key_hex": f"0x{key:08X}", "mcc_tag": items[0]["mcc_tag"], "level": items[0]["level"],
                 "slots": [r["slot_id"] for r in items], "mapping_ids": [r["mapping_id"] for r in items]}
        if not any(tbl is not None and key in tbl for tbl in tables.values()):
            for r in items:
                r.update(category="missing_key", change=False,
                         result="excluded: this line has no subtitle entry in SU or SP (keys are never added)")
            keys[key] = dict(entry, action="missing_key", tables={t: {"key_found": False, "write": False}
                                                                  for t in tables})
            continue
        if len(outcomes) > 1:
            code =("keep_and_change_for_one_subtitle_key" if ("keep", None) in outcomes
                    else "different_texts_for_one_subtitle_key")
            conflicts.append({"code": code, "key": key, "key_hex": entry["key_hex"], "mcc_tag": entry["mcc_tag"],
                              "slots": entry["slots"]})
            for r in items:
                r.update(category="conflict", change=False,
                         result="conflict: the takes of this line have different approved subtitles; unchanged")
            keys[key] = dict(entry, action="conflict")
            continue
        kind, text = next(iter(outcomes))
        missing = sorted(takes_of[key] - set(entry["slots"]))
        if kind == "write" and text == "" and missing:
            conflicts.append({"code": "empty_subtitle_not_agreed_by_every_take", "key": key,
                              "key_hex": entry["key_hex"], "mcc_tag": entry["mcc_tag"], "slots": entry["slots"],
                              "takes_without_approved_none": missing})
            for r in items:
                r.update(category="conflict", change=False,
                         result="conflict: 'no subtitle' hides the line for every take; these takes have no "
                                "approved 'none': " + ", ".join(missing) + "; unchanged")
            keys[key] = dict(entry, action="conflict")
            continue
        if kind == "keep":
            keys[key] = dict(entry, action="keep")
            continue
        per = {}
        for t, tbl in tables.items():
            old = None if tbl is None else tbl.get(key)
            per[t] = {"key_found": old is not None, "write": old is not None, "old_text": old,
                      "old_utf8_bytes": None if old is None else len(old.encode("utf-8")),
                      "same_length": old is not None and len(old.encode("utf-8")) == len(text.encode("utf-8")),
                      "unchanged_text": old == text}
        keys[key] = dict(entry, action="write", text=text, new_utf8_bytes=len(text.encode("utf-8")), tables=per)
        for r in items:
            for t in tables:
                r[t] = {k: per[t][k] for k in ("key_found", "old_utf8_bytes", "same_length", "unchanged_text")}

    written = [k for k in keys.values() if k["action"] == "write"]
    by_cat = Counter(r["category"] for r in rows)
    summary = {
        "approved_subtitles": sum(1 for r in rows if r["status"] == "approved"),
        "approved_text_changes": sum(1 for r in rows if r["change"]),  # slots whose subtitle text is written
        "rows": dict(sorted(by_cat.items())),
        "keys_to_write": len(written),
        "keys_written": {t: sum(1 for k in written if k["tables"][t]["write"]) for t in tables},
        "keys_found": {t: sum(1 for k in written if k["tables"][t]["key_found"]) for t in tables},
        "missing_keys": {t: sum(1 for k in keys.values() if k.get("tables") and not k["tables"][t]["key_found"])
                         for t in tables},
        "same_length": {t: sum(1 for k in written if k["tables"][t]["same_length"]) for t in tables},
        "variable_length": {t: sum(1 for k in written if k["tables"][t]["write"] and not k["tables"][t]["same_length"])
                            for t in tables},
        "empty_entries": sum(1 for k in written if k["text"] == ""),
        "conflicts": len(conflicts),
        "excluded": sum(1 for r in rows if r["category"] in ("excluded", "conflict", "missing_key")),
        "text_ok": True,  # texts a table cannot hold are excluded per row above
        "generation": "enabled",
        "writer": "mcc-loc-writer/1 (variable length, docs/m6-build.md §4)",
    }
    return {"schema": SUBTITLE_PLAN_SCHEMA, "rows": rows, "keys": [keys[k] for k in sorted(keys)],
            "conflicts": conflicts, "summary": summary}


def table_changes(plan, table):
    """{key: text} that `table` gets from a subtitle plan (keys it holds, decisions that agree)."""
    return {k["key"]: k["text"] for k in plan["keys"] if k["action"] == "write" and k["tables"][table]["write"]}


def compare_subtitle_plans(built, current):
    """Keys a subtitle build wrote vs the current plan. -> {"changed_or_revoked": [...], "newly_eligible": [...]}.
    A key the build wrote whose current approved text differs (or is no longer approved) means the build no
    longer matches the decisions (do not install; rebuild); keys approved since are only missing from it."""
    def written(plan):
        return {(t, k["key"]): k["text"] for k in plan.get("keys", []) if k.get("action") == "write"
                for t, p in k["tables"].items() if p["write"]}
    b, c = written(built), written(current)
    changed = sorted({f"{t}:0x{k:08X}" for (t, k), text in b.items() if c.get((t, k)) != text})
    new = sorted({f"{t}:0x{k:08X}" for (t, k) in c if (t, k) not in b})
    return {"changed_or_revoked": changed, "newly_eligible": new}


def assemble(original, replacements):
    """replacements: {index: (stream, sample_count)} -> candidate bank bytes (one build)."""
    model = decompose(original)
    for idx in sorted(replacements):
        stream, count = replacements[idx]
        model = replace_sample(model, idx, stream, count)
    return build(model)


def multi_structural_checks(original, candidate, replacements):
    """Checks that `candidate` == `original` with exactly the samples in `replacements` replaced."""
    mo, mc = decompose(original), decompose(candidate)
    so, sc = sample_spans(original), sample_spans(candidate)
    ho, hc = parse_header(original), parse_header(candidate)
    targets = set(replacements)
    growth = {k: (sc[k][1] - sc[k][0]) - (so[k][1] - so[k][0]) for k in targets}
    data_start = so[0][0]
    shift_ok = True
    acc = 0
    for k in range(len(so)):
        if sc[k][0] - so[k][0] != acc:
            shift_ok = False
            break
        acc += growth.get(k, 0)

    def loop_ok(k):
        n = replacements[k][1]
        return all(p == (0).to_bytes(4, "little") + (n - 2).to_bytes(4, "little")
                   for ty, p in mc["samples"][k]["chunks"] if ty == 3)
    return {
        "same_sample_count_and_names": len(mc["samples"]) == len(mo["samples"]) and mc["names"] == mo["names"],
        "header_tail_identical": mc["header_tail"] == mo["header_tail"],
        "sample_headers_size_unchanged": hc["sample_headers_size"] == ho["sample_headers_size"],
        "targets_are_expected_streams": all(mc["samples"][k]["stream"] == s for k, (s, _) in replacements.items()),
        "targets_sample_counts": all(mc["samples"][k]["sample_count"] == n for k, (_, n) in replacements.items()),
        "targets_loop_0_n_minus_2": all(loop_ok(k) for k in targets),
        "targets_head_bits_and_chunk_types_unchanged": all(
            mc["samples"][k]["head_bits"] == mo["samples"][k]["head_bits"]
            and [t for t, _ in mc["samples"][k]["chunks"]] == [t for t, _ in mo["samples"][k]["chunks"]]
            for k in targets),
        "untouched_sample_headers_identical": all(a == b for k, (a, b) in enumerate(zip(mo["samples"], mc["samples"]))
                                                  if k not in targets),
        "untouched_payloads_byte_identical": all(original[a:b] == candidate[c:d]
                                                 for k, ((a, b), (c, d)) in enumerate(zip(so, sc)) if k not in targets),
        "offsets_shift_by_cumulative_growth": shift_ok,
        "all_offsets_32_aligned": all((a - data_start) % ALIGN == 0 for a, _ in sc),
        "size_equation": len(candidate) == hc["base_header_size"] + hc["sample_headers_size"]
        + hc["name_table_size"] + hc["data_size"],
        "data_size_delta_equals_total_growth": hc["data_size"] - ho["data_size"] == sum(growth.values())
        and len(candidate) - len(original) == sum(growth.values()),
        "round_trip": build(mc) == candidate,
    }
