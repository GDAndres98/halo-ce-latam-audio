"""Build the Campaign Evolved metadata catalog for one mission (milestone M1).

Metadata only: reads the installed containers read-only (paths from .env,
mappings from USMAP_FILEC), hashes the referenced .wem media but decodes
nothing, and writes only under work/ (git-ignored):

    work/ce/catalog/<mission>.jsonl            one ce-voice-asset/3 record per voice asset
    work/ce/build.json                         source build identifiers + container pins
    work/ce/reports/<mission>_coverage.json    counts by evidence / class / family / flag
    work/ce/reports/<mission>_unresolved.json  unresolved fields, ambiguities, orphans, skipped
    work/ce/reports/<mission>_summary.md       human-readable summary (no game text)

Never reads or writes mappings/; never matches anything to MCC.

Example:
    python scripts/catalog/build_ce_catalog.py --mission M01
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.asset_metadata import EXPLICIT, UNRESOLVED, CEContext, derived, sha256_bytes  # noqa: E402
from common.ce_assets import (  # noqa: E402
    event_languages, parse_steam_acf, read_event_cooked_data, read_pe_file_version, read_string_table)
from common.ce_catalog import (  # noqa: E402
    AUDIO_LANGUAGES, SUBTITLE_CULTURES, SUPPORTED_CLASSES, analyze, build_record, dumps_json, dumps_jsonl)
from common.env import REPO_ROOT  # noqa: E402
from common.locres import parse_locres  # noqa: E402

BUILD_SCHEMA = "ce-build/1"
WORK = REPO_ROOT / "work" / "ce"
AUDIO_ROOT = "Meteorite/Content/Audio/"


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


class GameResolver:
    """Read-only resolver over the installed containers, with per-run caches."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._events, self._tables, self._locres, self._lang_pak = {}, {}, {}, {}
        self.containers_used = set()

    def event(self, game_path):
        if game_path not in self._events:
            info, cooked = read_event_cooked_data(self.ctx, game_path)
            self._events[game_path] = None if not info else {
                "vfs_path": info["vfs_path"], "container": info["container"], "class": info["class"],
                "trailing_bytes_unparsed": info["trailing_bytes"], "languages": event_languages(cooked)}
            if info:
                self.containers_used.add(info["container"])
        return self._events[game_path]

    def string_table(self, game_path):
        if game_path not in self._tables:
            self._tables[game_path] = read_string_table(self.ctx, game_path)
            if self._tables[game_path]:
                self.containers_used.add(self._tables[game_path]["container"])
        return self._tables[game_path]

    def locres(self, culture):
        if culture not in self._locres:
            p0 = self.ctx.pak("pakchunk0-Windows.pak")
            path = f"Meteorite/Content/Localization/Subtitles/{culture}/Subtitles.locres"
            if path in p0.files:
                data = p0.read(path, self.ctx.oodle)
                _ver, table = parse_locres(data)
                self._locres[culture] = {"path": path, "table": table, "sha256": sha256_bytes(data),
                                         "container": p0.path.name}
                self.containers_used.add(p0.path.name)
            else:
                self._locres[culture] = None
        return self._locres[culture]

    def _pak(self, language):
        if language not in self._lang_pak:
            self._lang_pak[language] = self.ctx.pak_for_wwise_language(language)
        return self._lang_pak[language]

    def has_language(self, language):
        return self._pak(language) is not None

    def media(self, language, media_path):
        pak = self._pak(language)
        vfs = f"Meteorite/Content/WwiseAudio/{media_path}"
        if not pak or vfs not in pak.files:
            return None
        data = pak.read(vfs, self.ctx.oodle)  # hashed only; never decoded or written
        self.containers_used.add(pak.path.name)
        return {"container": pak.path.name, "vfs_path": vfs, "wem_bytes": len(data), "wem_sha256": sha256_bytes(data)}

    def package(self, vfs_path):
        hit = self.ctx.find_package(vfs_path)
        if not hit:
            return None
        info = self.ctx.load_package(hit[1])
        return {"vfs_path": info["vfs_path"], "class": info["package"].exports[0]["class"]}


def discover_voice_folders(ctx, mission):
    """{folder_vfs_prefix: [file paths]} for Audio/scripted|cinematic folders named vo_scr_<m>* / vo_cin_<m>*."""
    m = mission.lower()
    folders = {}
    for family, prefix in (("scripted", f"vo_scr_{m}"), ("cinematic", f"vo_cin_{m}")):
        root = f"{AUDIO_ROOT}{family}/"
        for p in ctx.list_packages(root):
            rest = p[len(root):]
            if "/" not in rest:
                continue
            folder = rest.split("/", 1)[0]
            if folder.lower().startswith(prefix):
                folders.setdefault(f"{root}{folder}", []).append(p)
    return folders


def load_voice_asset(ctx, vfs_path):
    """-> (asset dict, None) or (None, skip reason)."""
    if not vfs_path.lower().endswith(".uasset"):
        return None, f"not a package header ({vfs_path.rsplit('.', 1)[-1]} companion file)"
    try:
        info = ctx.load_package(vfs_path)
        pkg = info["package"]
        cls = pkg.exports[0]["class"]
        if cls not in SUPPORTED_CLASSES:
            return None, f"unsupported class {cls}: reported, not guessed"
        props, _ = pkg.read_export_properties(0)
    except Exception as e:  # parser stop is a reported skip, never a silent drop
        return None, f"parse error: {type(e).__name__}: {e}"
    return {"vfs_path": info["vfs_path"], "container": info["container"], "package_name": pkg.name,
            "class": cls, "props": props, "locations": len(ctx.package_locations(vfs_path))}, None


def source_build_ids(ctx):
    exe = ctx.remake / "Meteorite" / "Binaries" / "Win64" / "HaloCampaignEvolved.exe"
    fv = read_pe_file_version(exe) if exe.is_file() else None
    out = {"exe_file_version": fv, "exe_file_version_evidence": EXPLICIT if fv else UNRESOLVED}
    steamapps = ctx.remake.parent.parent
    for acf in sorted(steamapps.glob("appmanifest_*.acf")):
        kv = parse_steam_acf(acf.read_text(encoding="utf-8", errors="replace"))
        if kv.get("installdir", "").lower() == ctx.remake.name.lower():
            out.update({"steam_appid": kv.get("appid"), "steam_buildid": kv.get("buildid"),
                        "steam_buildid_evidence": EXPLICIT})
            break
    else:
        out.update({"steam_buildid": None, "steam_buildid_evidence": UNRESOLVED})
    out["usmap_name"] = ctx.usmap_path.name
    out["usmap_build_string_evidence"] = derived("ue4ss_usmap_filename")
    return out


def container_pins(ctx, names):
    pins = []
    for name in sorted(names):
        p = ctx.paks / name
        pin = {"name": name, "size": p.stat().st_size}
        if name.endswith(".utoc"):
            pin["utoc_sha256"] = sha256_file(p)
        elif name.endswith(".pak"):
            pak = ctx.pak(name)
            with open(p, "rb") as f:
                f.seek(pak.footer["index_offset"])
                pin["index_sha256"] = sha256_bytes(f.read(pak.footer["index_size"]))
        pins.append(pin)
    return pins


def summary_md(mission, cov, rep, build):
    L = [f"# Campaign Evolved {mission} catalog — summary", "",
         f"Source build: `{build['source_build'].get('exe_file_version')}` "
         f"(Steam build {build['source_build'].get('steam_buildid')}). Catalog sha256 "
         f"`{build['catalogs'][mission]['sha256'][:16]}…`. No game text in this file.", "",
         f"- Files seen in voice folders: **{cov['files_seen']}** → records **{cov['records']}**, "
         f"skipped **{cov['skipped']}** (accounted for: {cov['accounted_for']})",
         f"- Entries (VoiceEvents): {cov['entries']}; unresolved items: {cov['unresolved_items']}", "",
         "| Folder | Files |", "|---|---|"]
    L += [f"| `{f.rsplit('/', 1)[-1]}` | {n} |" for f, n in cov["voice_folders"].items()]
    L += ["", "## Evidence", "", "| Link | explicit | unresolved |", "|---|---|---|"]
    for title, key in (("media", "media_evidence"), ("subtitle", "subtitle_evidence"),
                       ("event", "event_evidence"), ("lipsync", "lipsync_evidence")):
        for k, v in cov[key].items():
            L.append(f"| {title} `{k}` | {v.get('explicit', 0)} | {v.get('unresolved', 0)} |")
    L += ["", "## Flags", ""] + [f"- `{k}`: {v}" for k, v in cov["flags"].items()]
    L += ["", "## Ambiguities", ""] + [f"- `{k}`: {v}" for k, v in cov["ambiguities"].items()]
    L += ["", "## String tables", "", "| Table | Keys | Referenced | Orphaned |", "|---|---|---|---|"]
    L += [f"| `{t['string_table'].rsplit('/', 1)[-1]}` | {t['key_count']} | {t['referenced_count']} | "
          f"{t['orphaned']} |" for t in cov["string_tables"]]
    L += ["", f"Event packages in mission event folders: {cov['events_in_mission_folders']}, "
              f"not referenced by any voice asset: {cov['orphan_events']}.", ""]
    reasons = {}
    for it in rep["unresolved"]:
        reasons[(it["field"], it["reason"])] = reasons.get((it["field"], it["reason"]), 0) + 1
    L += ["## Unresolved, by reason", "", "| Field | Reason | Count |", "|---|---|---|"]
    L += [f"| {f} | {r} | {n} |" for (f, r), n in sorted(reasons.items())]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", default="M01")
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
    mission = args.mission.upper()
    t0 = time.time()
    ctx = CEContext(oodle_dll=args.oodle_dll)
    res = GameResolver(ctx)
    build_ids = source_build_ids(ctx)

    folders = discover_voice_folders(ctx, mission)
    if not folders:
        raise SystemExit(f"no voice folders found for {mission}")
    records, skipped = [], []
    for folder in sorted(folders):
        for p in folders[folder]:
            asset, why = load_voice_asset(ctx, p)
            if not asset:
                skipped.append({"vfs_path": p, "reason": why})
                continue
            res.containers_used.add(asset["container"])
            records.append(build_record(asset, res, build_ids))
    ids = {}
    for r in records:
        ids.setdefault(r["record_id"], []).append(r)
    for rid, group in ids.items():  # keep ce_line_ref unique: qualify colliding names by folder
        if len(group) > 1:
            for r in group:
                r["record_id"] = f"{r['folder'].lower()}/{rid}"
                for e in r["entries"]:
                    e["ce_line_ref"] = f"{r['record_id']}#{e['index']}"
                r["flags"] = sorted(set(r["flags"]) | {"record_id_qualified"})

    # Every string table referenced, plus the ones expected for each (non-lipsync) folder.
    # Keyed case-insensitively: imports spell folders 'Scripted' while the VFS index has 'scripted'.
    table_paths = {}
    for r in records:
        for e in r["entries"]:
            tp = e["transcription"].get("string_table")
            if tp:
                table_paths.setdefault(tp.lower(), tp)
    for folder in folders:
        fam, name = folder[len(AUDIO_ROOT):].split("/")
        if not name.lower().endswith("_lipsync"):
            for p in ctx.list_packages(f"{AUDIO_ROOT}Transcription/Subtitles/{fam}/"):
                if p.rsplit("/", 1)[-1].lower() == f"{name.lower()}.uasset":
                    tp = "/Game/" + p[len("Meteorite/Content/"):-len(".uasset")]
                    table_paths.setdefault(tp.lower(), tp)
    string_tables = {}
    for tp in sorted(table_paths.values()):
        st = res.string_table(tp)
        string_tables[tp] = st if st and st.get("class") == "StringTable" else {"namespace": None, "keys": []}
    namespaces = {st["namespace"] for st in string_tables.values() if st.get("namespace")}
    locres_keys = {}
    for c in SUBTITLE_CULTURES:
        loc = res.locres(c)
        locres_keys[c] = {ns: set((loc["table"] if loc else {}).get(ns, {})) for ns in namespaces}

    event_inventory = []
    for folder in folders:
        fam, name = folder[len(AUDIO_ROOT):].split("/")
        if not name.lower().endswith("_lipsync"):
            event_inventory += [p for p in ctx.list_packages(f"Meteorite/Content/WwiseAudio/Events/{fam}/{name}/")
                                if p.lower().endswith(".uasset")]
    event_inventory = sorted(set(event_inventory), key=str.lower)

    coverage, report = analyze(records, string_tables=string_tables, locres_keys=locres_keys,
                               event_inventory=event_inventory,
                               voice_inventory=folders, skipped=skipped)
    coverage["mission"] = report["mission"] = mission
    coverage["source_build"] = report["source_build"] = build_ids

    catalog = dumps_jsonl(records)
    out_cat = WORK / "catalog" / f"{mission.lower()}.jsonl"
    out_cat.parent.mkdir(parents=True, exist_ok=True)
    out_cat.write_text(catalog, encoding="utf-8", newline="\n")

    build_path = WORK / "build.json"
    build = json.loads(build_path.read_text(encoding="utf-8")) if build_path.exists() else {}
    if build.get("schema") != BUILD_SCHEMA or build.get("source_build") != build_ids:
        build = {"schema": BUILD_SCHEMA, "source_build": build_ids, "catalogs": {}, "containers": [],
                 "locres": {}}  # different game build: previous catalogs are stale
    pins = {p["name"]: p for p in build["containers"]}
    for p in container_pins(ctx, res.containers_used | {"global.utoc"}):
        pins[p["name"]] = p
    build["containers"] = [pins[k] for k in sorted(pins)]
    build["usmap_sha256"] = sha256_file(ctx.usmap_path)
    for c in SUBTITLE_CULTURES:
        loc = res.locres(c)
        build["locres"][c] = {"path": loc["path"], "sha256": loc["sha256"]} if loc else None
    build["catalogs"][mission] = {
        "path": out_cat.relative_to(REPO_ROOT).as_posix(), "record_schema": records[0]["schema"] if records else None,
        "records": len(records), "skipped": len(skipped), "sha256": sha256_bytes(catalog.encode("utf-8")),
        "audio_languages": list(AUDIO_LANGUAGES), "subtitle_cultures": list(SUBTITLE_CULTURES),
        "tool": "scripts/catalog/build_ce_catalog.py"}
    build_path.write_text(dumps_json(build), encoding="utf-8", newline="\n")

    rep_dir = WORK / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    m = mission.lower()
    (rep_dir / f"{m}_coverage.json").write_text(dumps_json(coverage), encoding="utf-8", newline="\n")
    (rep_dir / f"{m}_unresolved.json").write_text(dumps_json(report), encoding="utf-8", newline="\n")
    (rep_dir / f"{m}_summary.md").write_text(summary_md(mission, coverage, report, build), encoding="utf-8",
                                              newline="\n")
    print(f"{len(records)} records, {len(skipped)} skipped, "
          f"{coverage['unresolved_items']} unresolved items, {len(report['ambiguities'])} ambiguities "
          f"({time.time() - t0:.1f}s)")
    for p in (out_cat, build_path, rep_dir / f"{m}_coverage.json", rep_dir / f"{m}_unresolved.json",
              rep_dir / f"{m}_summary.md"):
        print(f"  wrote {p.relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
