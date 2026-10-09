"""Campaign-wide extraction/catalog inventory (read-only over work/ and mappings/).

Summarizes every built MCC level catalog and CE mission catalog, what audio
is already decoded (eagerly or on demand), the owner's mission map and
progress, and the extraction gaps still open. With --scan-ce it also lists
the CE voice folders in the installed containers (read-only) so folders the
catalogs don't cover (Systemic barks, temp mocap) are reported, not dropped.

Writes only:
    work/reports/campaign_inventory.json   (campaign-inventory/1)
    work/reports/campaign_inventory.md     (no game text)

Never matches anything across games; the level <-> mission scope shown is
the owner's mission_map.json.

Example:
    python scripts/catalog/campaign_inventory.py --scan-ce
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT  # noqa: E402
from common.mcc_loc import loc_key, parse_mcc_loc  # noqa: E402
from common.project_validation import dumps, level_progress  # noqa: E402

SCHEMA = "campaign-inventory/1"
AUDIO_ROOT = "Meteorite/Content/Audio/"


def read_json(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def read_jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def level_group(level):
    return "campaign" if re.fullmatch(r"[a-d]\d\d", level) else "cutscene" if re.fullmatch(r"x\d\d", level) \
        else "generic"


def mcc_levels(root, mappings, mission_map, progress, loc):
    out = []
    ondemand = {lang: {p.name.split("_")[0] for p in (root / "work/mcc/audio/ondemand" / lang).glob("*.wav")}
                for lang in ("spanish", "english")}
    scope = {e["mcc_level"]: e["ce_missions"] for e in mission_map.get("entries", [])}
    status = {e["mcc_level"]: e["status"] for e in progress.get("levels", [])}
    for p in sorted((root / "work/mcc/catalog").glob("*.jsonl"),
                    key=lambda p: (["campaign", "cutscene", "generic"].index(level_group(p.stem)), p.stem)):
        level, recs = p.stem, read_jsonl(p)
        issues = read_json(root / f"work/mcc/reports/{level}_issues.json", {}).get("issues", [])
        manifest = read_json(root / f"work/mcc/audio/{level}/manifest.json")
        es = [s for r in recs for s in r["samples"]["spanish"]]
        en = [s for r in recs for s in r["samples"]["english"]]
        flags = Counter(f for r in recs for f in {x.split(":")[0] for x in r["flags"]})  # once per record
        eager = {(u["language"], u["index"]) for u in (manifest or {}).get("units", []) if u.get("status") == "ok"}
        decoded = {lang: sum(1 for s in ss if (lang, s["index"]) in eager or str(s["index"]) in ondemand[lang])
                   for lang, ss in (("spanish", es), ("english", en))}
        sids = [sid for r in recs for sid in r["slot_ids"]]
        out.append({
            "level": level, "group": level_group(level), "tags": len(recs), "spanish_slots": len(es),
            "english_samples": len(en), "kinds": dict(sorted(Counter(r["kind"] for r in recs).items())),
            "stereo_slots": sum(1 for s in es if s["channels"] > 1),
            "tags_missing_spanish": sum(1 for r in recs if not r["samples"]["spanish"]),
            "tags_missing_english": sum(1 for r in recs if not r["samples"]["english"]),
            "tags_resolved_from_lst_range": flags.get("samples_from_lst_range", 0),
            "spanish_duration_s": round(sum(s["duration_s"] or 0 for s in es), 1),
            "subtitle_keys_present": {t: (sum(1 for r in recs if loc_key(r["mcc_tag"]) in tbl) if tbl is not None
                                          else None) for t, tbl in loc.items()},
            "issues": dict(sorted(Counter(i["code"] for i in issues).items())),
            "stray_bank_samples": sum(len(i.get("samples", [])) for i in issues
                                      if i["code"] == "bank_samples_without_tag" and i.get("language") == "spanish"),
            "audio": {"eager_manifest": manifest is not None, "decoded": decoded},
            "ce_missions": scope.get(level, []), "status": status.get(level),
            "progress": level_progress(sids, mappings),
        })
    return out


def ce_missions(root, mission_map):
    out = []
    mapped = {}
    for e in mission_map.get("entries", []):
        for m in e["ce_missions"]:
            mapped.setdefault(m, []).append(e["mcc_level"])
    ondemand = {lang: {p.stem for p in (root / "work/ce/audio/ondemand" / lang).glob("*.wav")}
                for lang in ("Spanish(Mexico)", "English(US)")}
    for p in sorted((root / "work/ce/catalog").glob("*.jsonl")):
        mission, recs = p.stem.upper(), read_jsonl(p)
        cov = read_json(root / f"work/ce/reports/{p.stem}_coverage.json", {})
        manifest = read_json(root / f"work/ce/audio/{p.stem}/manifest.json")
        entries = [e for r in recs for e in r["entries"]]
        eager = {(u["language"], u["media_id"]) for u in (manifest or {}).get("units", []) if u.get("status") == "ok"}

        def ev(e, kind, k):
            return (e[kind].get(k) or {}).get("evidence", "unresolved")

        decoded = {}
        for lang in ("Spanish(Mexico)", "English(US)"):
            ids = [m["media_id"] for e in entries if ev(e, "media", lang) == "explicit"
                   for m in e["media"][lang]["media"]]
            decoded[lang] = {"media": len(set(ids)),
                             "decoded": sum(1 for i in set(ids) if (lang, i) in eager or str(i) in ondemand[lang])}
        out.append({
            "mission": mission, "records": len(recs), "lines": len(entries),
            "families": dict(sorted(Counter(r["family"] for r in recs).items())),
            "folders": sorted({r.get("folder") for r in recs}),
            "test_events": sum(1 for r in recs if "test_event" in r["flags"]),
            "es_mx_media": dict(Counter(ev(e, "media", "Spanish(Mexico)") for e in entries)),
            "en_media": dict(Counter(ev(e, "media", "English(US)") for e in entries)),
            "es_mx_subtitles": dict(Counter(ev(e, "subtitles", "es-MX") for e in entries)),
            "skipped_assets": cov.get("skipped"), "accounted_for": cov.get("accounted_for"),
            "audio": {"eager_manifest": manifest is not None, "by_language": decoded},
            "mcc_levels_in_mission_map": mapped.get(mission, []),
        })
    return out


def scan_ce_folders(oodle_dll=None):
    """{family: {folder: package count}} for Audio/scripted and Audio/cinematic, plus other Audio roots."""
    from common.asset_metadata import CEContext
    ctx = CEContext(oodle_dll=oodle_dll)
    out = {}
    for p in ctx.list_packages(AUDIO_ROOT):
        rest = p[len(AUDIO_ROOT):].split("/")
        fam = rest[0]
        sub = rest[1] if len(rest) > 2 else "<files>"
        out.setdefault(fam, Counter())[sub] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def gaps(levels, missions, scan):
    g = []
    unmapped = [lv["level"] for lv in levels if lv["group"] in ("campaign", "cutscene") and not lv["ce_missions"]]
    if unmapped:
        g.append({"code": "levels_without_mission_scope", "owner_action": True, "items": unmapped,
                  "note": "mission_map.json scopes CE search per level; M4 still allows searching all missions."})
    gen = [lv["level"] for lv in levels if lv["group"] == "generic"]
    if gen:
        g.append({"code": "generic_barks_have_no_ce_catalog", "items": gen,
                  "note": "MCC combat/AI barks live in generic folders; their CE counterparts are under "
                          "Audio/Systemic. Deferred by the owner (2026-10-08) to a separate milestone (M-SYS)."})
    lst = [lv["level"] for lv in levels if lv["tags_resolved_from_lst_range"]]
    if lst:
        g.append({"code": "slots_identified_by_lst_range", "items": lst,
                  "note": "Name-table lookup failed or was ambiguous; samples come from the tag's .lst.bin range "
                          "(derived:lst_record_layout). Rule approved by the owner 2026-10-08; verified by "
                          "scripts/validate/verify_slot_ids.py."})
    miss = [f"{lv['level']}:{lv['tags_missing_spanish']}" for lv in levels if lv["tags_missing_spanish"]]
    if miss:
        g.append({"code": "mcc_tags_without_spanish_sample", "items": miss})
    stray = [f"{lv['level']}:{lv['stray_bank_samples']}" for lv in levels if lv["stray_bank_samples"]]
    if stray:
        g.append({"code": "spanish_bank_samples_without_tag", "items": stray,
                  "note": "Reported per level in work/mcc/reports/<level>_issues.json; not catalogued as slots."})
    st = [f"{lv['level']}:{lv['stereo_slots']}" for lv in levels if lv["stereo_slots"]]
    if st:
        g.append({"code": "stereo_slots_replacement_deferred", "items": st,
                  "note": "Visible and playable in M4; stereo replacement is deferred (owner, 2026-10-08)."})
    subs = [f"{lv['level']}:{lv['tags'] - (lv['subtitle_keys_present'].get('SU') or 0)}" for lv in levels
            if lv["subtitle_keys_present"].get("SU") is not None and lv["subtitle_keys_present"]["SU"] < lv["tags"]]
    if subs:
        g.append({"code": "mcc_tags_without_su_subtitle_key", "items": subs,
                  "note": "No SU_Halo1.bin entry under CRC(tag path); such lines may have no subtitle at all."})
    unres = [f"{m['mission']}:{m['es_mx_media'].get('unresolved', 0)}/{m['es_mx_subtitles'].get('unresolved', 0)}"
             for m in missions if m["es_mx_media"].get("unresolved") or m["es_mx_subtitles"].get("unresolved")]
    if unres:
        g.append({"code": "ce_unresolved_es_mx_media_or_subtitle", "items": unres,
                  "note": "mission:media/subtitle counts; unresolved items are never filled from another culture."})
    nomap = [m["mission"] for m in missions if not m["mcc_levels_in_mission_map"]]
    if nomap:
        g.append({"code": "ce_missions_not_in_mission_map", "items": nomap,
                  "note": "Not inferred by tools. M12-M14 are named m12dlc1..m14dlc3 in CE and may have no MCC "
                          "counterpart level (owner to confirm)."})
    if scan:
        covered = {f.lower() for m in missions for f in m["folders"]}
        extra = []
        for fam in ("scripted", "cinematic"):
            for folder, n in scan.get(fam, {}).items():
                if folder != "<files>" and folder.lower() not in covered:
                    extra.append(f"{fam}/{folder} ({n})")
        if extra:
            g.append({"code": "ce_voice_folders_not_catalogued", "items": extra,
                      "note": "Kept in the extraction backlog by the owner (2026-10-08); lipsync folders are "
                              "covered through their parent records."})
        others = {k: sum(v.values()) for k, v in scan.items() if k not in ("scripted", "cinematic")}
        if others.get("Systemic"):
            g.append({"code": "ce_systemic_audio_not_catalogued", "items": [f"Systemic ({others['Systemic']} packages)"],
                      "note": "Candidate source for MCC generic barks; deferred to milestone M-SYS (owner)."})
    return g


def summary_md(inv):
    L = ["# Campaign-wide catalog inventory", "",
         "Generated by `scripts/catalog/campaign_inventory.py`. Read-only; no game text in this file. "
         "Cross-game scope comes only from the owner's `mission_map.json`; nothing is matched.", "",
         f"- MCC: **{inv['totals']['mcc_levels']} folders**, {inv['totals']['mcc_tags']} tags, "
         f"**{inv['totals']['mcc_spanish_slots']} / {inv['totals']['spanish_bank_samples']}** Spanish bank samples "
         "catalogued as slots",
         f"- CE: **{inv['totals']['ce_missions']} missions**, {inv['totals']['ce_records']} records, "
         f"{inv['totals']['ce_lines']} lines, {inv['totals']['ce_lines_with_es_mx_media']} with es-MX audio", "",
         "## MCC levels", "",
         "| Level | Group | Tags | ES slots | Stereo | From lst | Missing ES | SU keys | Decoded es/en | CE scope "
         "| Decided | Audio ✔ | Sub ✔ | Status |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for lv in inv["mcc_levels"]:
        p = lv["progress"]
        L.append(f"| {lv['level']} | {lv['group']} | {lv['tags']} | {lv['spanish_slots']} | {lv['stereo_slots']} | "
                 f"{lv['tags_resolved_from_lst_range']} | {lv['tags_missing_spanish']} | "
                 f"{lv['subtitle_keys_present'].get('SU')} | {lv['audio']['decoded']['spanish']}/"
                 f"{lv['audio']['decoded']['english']} | {', '.join(lv['ce_missions']) or '—'} | "
                 f"{p['decided']}/{p['slots']} | {p['audio_approved']} | {p['subtitle_approved']} | "
                 f"{lv['status'] or '—'} |")
    L += ["", "## CE missions", "",
          "| Mission | Records | Lines | Families | Test events | es-MX media | es-MX subtitles | Decoded es-MX | "
          "Decoded en | MCC levels (owner map) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m in inv["ce_missions"]:
        a = m["audio"]["by_language"]
        L.append(f"| {m['mission']} | {m['records']} | {m['lines']} | "
                 f"{', '.join(f'{k} {v}' for k, v in m['families'].items())} | {m['test_events']} | "
                 f"{m['es_mx_media'].get('explicit', 0)} ok / {m['es_mx_media'].get('unresolved', 0)} unres. | "
                 f"{m['es_mx_subtitles'].get('explicit', 0)} ok / {m['es_mx_subtitles'].get('unresolved', 0)} unres. | "
                 f"{a['Spanish(Mexico)']['decoded']}/{a['Spanish(Mexico)']['media']} | "
                 f"{a['English(US)']['decoded']}/{a['English(US)']['media']} | "
                 f"{', '.join(m['mcc_levels_in_mission_map']) or '—'} |")
    L += ["", "## Gaps", ""]
    for g in inv["gaps"]:
        L.append(f"- **`{g['code']}`**{' (owner action)' if g.get('owner_action') else ''}: "
                 f"{', '.join(g['items'][:30])}{' …' if len(g['items']) > 30 else ''}")
        if g.get("note"):
            L.append(f"  - {g['note']}")
    L += ["", "Audio is decoded on demand by the M4 UI; 'Decoded' counts eager (M1b/M2) plus on-demand cache.", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--scan-ce", action="store_true", help="also list CE voice folders in the installed containers")
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
    root = args.root
    mappings = read_json(root / "mappings/manual_mappings.json", {"slots": []})
    mission_map = read_json(root / "mappings/mission_map.json", {"entries": []})
    progress = read_json(root / "mappings/mission_progress.json", {"levels": []})
    loc = {}
    for t in ("SU", "SP"):
        p = root / f"work/mcc/loc/copies/{t}_Halo1.bin"
        loc[t] = parse_mcc_loc(p.read_bytes())["entries"] if p.is_file() else None
    levels = mcc_levels(root, mappings, mission_map, progress, loc)
    missions = ce_missions(root, mission_map)
    scan = scan_ce_folders(args.oodle_dll) if args.scan_ce else None
    mcc_build = read_json(root / "work/mcc/build.json", {})
    bank_total = (mcc_build.get("lst_layout") or {}).get("spanish", {}).get("bank_samples")
    inv = {"schema": SCHEMA,
           "sources": {"mcc_build": (mcc_build.get("source_build") or {}),
                       "ce_build": (read_json(root / "work/ce/build.json", {}).get("source_build") or {})},
           "totals": {"mcc_levels": len(levels), "mcc_tags": sum(x["tags"] for x in levels),
                      "mcc_spanish_slots": sum(x["spanish_slots"] for x in levels),
                      "spanish_bank_samples": bank_total,
                      "ce_missions": len(missions), "ce_records": sum(m["records"] for m in missions),
                      "ce_lines": sum(m["lines"] for m in missions),
                      "ce_lines_with_es_mx_media": sum(m["es_mx_media"].get("explicit", 0) for m in missions)},
           "mcc_levels": levels, "ce_missions": missions, "ce_voice_folders": scan,
           "gaps": gaps(levels, missions, scan)}
    rep = root / "work/reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "campaign_inventory.json").write_text(dumps(inv), encoding="utf-8", newline="\n")
    (rep / "campaign_inventory.md").write_text(summary_md(inv), encoding="utf-8", newline="\n")
    t = inv["totals"]
    print(f"MCC {t['mcc_levels']} folders, {t['mcc_tags']} tags, {t['mcc_spanish_slots']}/{t['spanish_bank_samples']} "
          f"Spanish slots; CE {t['ce_missions']} missions, {t['ce_lines']} lines; {len(inv['gaps'])} gap group(s)")
    print("  wrote work/reports/campaign_inventory.json, work/reports/campaign_inventory.md")


if __name__ == "__main__":
    main()
