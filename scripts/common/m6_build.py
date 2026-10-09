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
  not_eligible    draft / needs_rework / unsupported (ce_concat, user_recording, composite, stereo,
                  gap on one line) / invalid (drift, unresolved media, test event, bad recipe) -> sample
                  preserved, reason
                  reported. Nothing is approved or changed to make it eligible.
Subtitles are planned independently of audio (`subtitle_plan`) as a DRY RUN: this build writes no
subtitle table, because mcc_loc_patch only supports same-length replacement and variable-length
tables are unvalidated (docs/m6-build.md §4).
"""
import json
from collections import Counter, defaultdict

from . import audio_edit
from .fsb5_lib import parse_header
from .fsb5_writer import ALIGN, build, decompose, replace_sample, sample_spans
from .mcc_loc import loc_key
from .project_validation import audio_fingerprint, subtitle_fingerprint

PLAN_SCHEMA = "m6-build-plan/1"


def _flag(m, name, key):
    return bool((m.get(name) or {}).get(key))


def plan_audio(doc, levels, *, slot_index, ce_lines, ce_idx, mcc_idx, local=None):
    """-> {"entries": [...], "conflicts": [...]} for every Spanish slot in `levels` (mapped or not)."""
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


def edit_problems(edit, ref, lang):
    """Static recipe problems for one CE source (the timeline is checked when rendering). Includes
    removed fields (speed, gain_db) still stored before the one-time migration."""
    out = audio_edit.problems(edit)
    if audio_edit.is_identity(edit):
        return out
    if edit.get("for_source") != {"ce_line_ref": ref, "language": lang}:
        out.append("made for another CE line or language")
    return out


FOLDER_GROUPS = ("replace", "approved_keep_spain", "not_approved", "unmapped", "unsupported", "invalid")


def entry_group(e):
    """Report group of one planned slot (per folder, owner request 2026-10-08)."""
    if e["action"] == "replace":
        return "replace"
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
        f["stereo_replaced"] += e["channels"] > 1 and e["action"] == "replace"
    return out


def _built_key(e):
    """What a built slot depends on: same action, mapping, source media and edit recipe -> same sample."""
    return (e["action"], e.get("mapping_id"), e.get("ce_line_ref"), e.get("language"),
            (e.get("media") or {}).get("wem_sha256"), json.dumps(e.get("edit"), sort_keys=True))


def compare_plans(built_entries, current_entries):
    """Built plan vs a plan from the current mappings.
    -> {"changed_or_revoked": [...], "newly_eligible": [...]}: the first means the build no longer matches
    an approved decision (do not install; rebuild); the second only means newer approvals are missing."""
    cur = {e["slot_id"]: e for e in current_entries}
    changed, new = [], []
    for e in built_entries:
        c = cur.get(e["slot_id"])
        if e["action"] == "replace" and (c is None or _built_key(c) != _built_key(e)):
            changed.append(e["slot_id"])
        elif e["action"] != "replace" and c is not None and c["action"] == "replace":
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


def subtitle_plan(doc, levels, *, slot_index, ce_lines, ce_idx, mcc_idx, local, tables):
    """Dry run of approved subtitle decisions against each table independently.

    tables: {"SU": entries dict, "SP": entries dict} (mcc_loc.parse_mcc_loc(...)["entries"]).
    -> {"rows": [...], "conflicts": [...], "summary": {...}}. Writes nothing."""
    rows, conflicts = [], []
    by_key = defaultdict(list)
    for m in doc["slots"]:
        hit = slot_index.get(m["slot_id"])
        if not hit or hit[0] not in levels:
            continue
        s = m["subtitle"]
        row = {"slot_id": m["slot_id"], "mapping_id": m["mapping_id"], "mcc_tag": hit[1]["mcc_tag"],
               "status": s["status"], "source": s["source"], "change": False}
        if s["status"] != "approved":
            row["result"] = f"not applied: subtitle {s['status']}"
        elif s["source"] == "keep_original":
            row["result"] = "approved: keep MCC text (no change)"
        elif s["fingerprint"] != subtitle_fingerprint(m, ce_idx, mcc_idx, local):
            row["result"] = "invalid: approved fingerprint drift"
        else:
            if s["source"] == "ce_locres":
                ref, cul = s["ce_locres"]["ce_line_ref"], s["ce_locres"]["culture"]
                text = ((ce_lines.get(ref) or (None, None, {"subtitles": {}}))[2]["subtitles"].get(cul) or {}).get("text")
            elif s["source"] == "custom":
                text = ((local or {}).get("custom_subtitles", {}).get(s["custom_ref"]) or {}).get("text")
            else:  # "none": an empty subtitle
                text = ""
            key = loc_key(hit[1]["mcc_tag"])
            row.update(key=key, key_evidence="derived:mcc_loc_key_crc32_tag_path", change=text is not None)
            if text is None:
                row["result"] = "invalid: approved text not found"
                row["change"] = False
            else:
                new = text.encode("utf-8")
                row["new_utf8_bytes"] = len(new)
                row["text_ok"] = b"\0" not in new
                for t, tbl in tables.items():
                    old = None if tbl is None else tbl.get(key)
                    row[t] = {"key_found": old is not None,
                              "old_utf8_bytes": None if old is None else len(old.encode("utf-8")),
                              "same_length": old is not None and len(old.encode("utf-8")) == len(new),
                              "unchanged_text": old == text}
                row["result"] = "planned (not generated in this build)"
                by_key[key].append((m["slot_id"], text))
        rows.append(row)
    for key, items in by_key.items():
        if len({t for _, t in items}) > 1:
            conflicts.append({"code": "different_texts_for_one_subtitle_key", "key": key,
                              "slots": [sid for sid, _ in items]})
    changes = [r for r in rows if r["change"]]
    summary = {"approved_text_changes": len(changes),
               "keys_found": {t: sum(1 for r in changes if r[t]["key_found"]) for t in tables},
               "same_length": {t: sum(1 for r in changes if r[t]["same_length"]) for t in tables},
               "variable_length": {t: sum(1 for r in changes if r[t]["key_found"] and not r[t]["same_length"])
                                   for t in tables},
               "text_ok": all(r.get("text_ok", True) for r in changes),
               "generation": "disabled",
               "reason": "mcc_loc_patch supports same-byte-length replacement only; variable-length tables "
                         "are not validated offline or in game (B1 residual, docs/m6-build.md §4)"}
    return {"rows": rows, "conflicts": conflicts, "summary": summary}


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
