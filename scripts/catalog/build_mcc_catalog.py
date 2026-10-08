"""Build the MCC Halo CE dialogue catalog for one level and decode its samples (milestone M2).

Works only from the verified copies in reference-audio/stage1/{fsb,lst}/.
Each copy's sha256 must equal the pinned value (docs/feasibility.md §11.2).
The installed originals are hashed read-only to report whether the copies
are still current. Nothing is ever written to the install or to a bank.

Outputs (all git-ignored):
    work/mcc/catalog/<level>.jsonl                    one mcc-dialogue-tag/3 record per tag
    work/mcc/build.json                               copy + install pins, Steam build id
    work/mcc/audio/<level>/<language>/<tag>__<k>.wav  decoded samples (vgmstream-cli -s)
    work/mcc/audio/<level>/manifest.json              deterministic export manifest
    work/mcc/reports/<level>_coverage.json, _issues.json, _summary.md, _review_picks.json|md

Subtitle links stay unresolved (blocker B1). Never matches to Campaign Evolved.

Example:
    python scripts/catalog/build_mcc_catalog.py --level a10 \
        --vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.ce_assets import parse_steam_acf  # noqa: E402
from common.ce_audio_export import dumps_json, inspect_wav, sha256_file  # noqa: E402
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from common.fsb5_lib import FsbBank  # noqa: E402
from common.mcc_catalog import (  # noqa: E402
    LANGUAGES, RECORD_SCHEMA, BankIndex, build_level, coverage, export_plan, export_units, recommend)
from common.mcc_lst import check_ranges, parse_lst  # noqa: E402

COPIES = REPO_ROOT / "reference-audio" / "stage1"
WORK = REPO_ROOT / "work" / "mcc"
DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")
EXPORT_SCHEMA = "mcc-audio-export/1"
BUILD_SCHEMA = "mcc-build/1"
# Full SHA-256 of the copies (= installed originals on 2026-10-07/08; docs/feasibility.md §11.2).
FILES = {
    "english": {"fsb": ("fsb/sounds_dialogs.fsb", "8d072c1b73b9a8f6d7269ff1e3bb8d99b49d76a6e040ea0edf997446cbcba4bb"),
                "lst": ("lst/sounds_dialogs.lst.bin",
                        "566235e5b844f6e859b454fa732f9dec8f316cdeb56eb49602c3b7226174619f")},
    "spanish": {"fsb": ("fsb/sounds_dialogs_spanish.fsb",
                        "ed0ff3ec240546611a62d2a23d6ce66b5cd7af17527bf1b12834a77fa91faef6"),
                "lst": ("lst/sounds_dialogs_spanish.lst.bin",
                        "d5324861186f079c8d436f598b0adcafba259259eaa56be57d987df68cdaffc3")},
}
INSTALL_SUBDIR = {"fsb": "halo1/sound/pc", "lst": "halo1/sound/pc/lst"}


def verify_copies(mcc_root):
    pins = {}
    for lang, kinds in FILES.items():
        for kind, (rel, expected) in kinds.items():
            copy = COPIES / rel
            got = sha256_file(copy)
            if got != expected:
                raise SystemExit(f"copy {rel} sha256 {got} != pinned {expected}; refusing to use it")
            inst = mcc_root / INSTALL_SUBDIR[kind] / Path(rel).name
            inst_hash = sha256_file(inst) if inst.is_file() else None  # read-only
            pins[f"{lang}.{kind}"] = {"copy": copy.relative_to(REPO_ROOT).as_posix(), "sha256": got,
                                      "size": copy.stat().st_size, "install_sha256": inst_hash,
                                      "install_matches_copy": inst_hash == got}
    return pins


def mcc_source_build(mcc_root):
    for acf in sorted(mcc_root.parent.parent.glob("appmanifest_*.acf")):
        kv = parse_steam_acf(acf.read_text(encoding="utf-8", errors="replace"))
        if kv.get("installdir", "").lower() == mcc_root.name.lower():
            return {"steam_appid": kv.get("appid"), "steam_buildid": kv.get("buildid"),
                    "steam_buildid_evidence": "explicit"}
    return {"steam_appid": None, "steam_buildid": None, "steam_buildid_evidence": "unresolved"}


def make_decoder(exe, fsb_paths):
    def decode(u, tmp):
        res = subprocess.run([str(exe), "-s", str(u["subsong"]), "-o", str(tmp), str(fsb_paths[u["language"]])],
                             capture_output=True, text=True)
        return res.returncode == 0, (res.stderr or res.stdout or "").strip()
    return decode


def vgmstream_info(exe):
    res = subprocess.run([str(exe), "-V"], capture_output=True, text=True)
    try:
        version = json.loads(res.stdout).get("version")
    except ValueError:
        version = None
    return {"name": "vgmstream-cli", "version": version, "exe_sha256": sha256_file(exe)}


def summary_md(level, build, cov, issues):
    L = [f"# MCC Halo CE {level} dialogue catalog — summary", "",
         f"Steam build {build['source_build']['steam_buildid']}; copies verified against pinned sha256; "
         f"install matches copies: {all(p['install_matches_copy'] for p in build['files'].values())}. "
         "No game text in this file.", "",
         f"- Tags: **{cov['tags']}** ({', '.join(f'{k} {v}' for k, v in cov['by_kind'].items())})",
         f"- Subtitle links: {cov['subtitle_evidence']} (blocker B1)", "",
         "| | spanish | english |", "|---|---|---|"]
    rows = [("samples", "samples"), ("tags with samples", "tags_with_samples"), ("lst range agrees", "lst_agrees"),
            ("codecs", "codecs"), ("sample rates", "freqs"), ("channels", "channels"),
            ("header duration", "header_duration_s"), ("decode status", "decode_status"),
            ("WAV frames == header", "frames_match_header")]
    for title, k in rows:
        L.append(f"| {title} | {cov['languages']['spanish'].get(k)} | {cov['languages']['english'].get(k)} |")
    L += ["", "## Flags", ""] + [f"- `{k}`: {v}" for k, v in cov["flags"].items()]
    L += ["", "## Issues", ""] + ([f"- `{i['code']}`" + (f" ({i.get('language')})" if i.get("language") else "")
                                   for i in issues] or ["- none"])
    return "\n".join(L) + "\n"


def picks_md(level, picks):
    L = [f"# MCC {level} — five samples for listening review", "",
         f"Selected deterministically for variety. Not matched to any Campaign Evolved line. Paths are relative "
         f"to `work/mcc/audio/{level}/`. Subtitle text is not available (blocker B1).", ""]
    for n, p in enumerate(picks["picks"], 1):
        L += [f"## {n}. `{p['mcc_tag']}`: {p['why']}", "",
              f"Kind {p['kind']}, speaker (from name) {p['speaker_from_name']}, slot {', '.join(p['slot_ids'])}, "
              f"flags {', '.join(p['flags']) or 'none'}.", ""]
        for lang, items in p["audio"].items():
            for a in items:
                L.append(f"- **{lang}** `{a['wav_path']}` ({a['duration_s']} s, bank index {a['index']})")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", default="a10")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    args = ap.parse_args()
    level = args.level.lower()
    if not args.vgmstream_cli.is_file():
        raise SystemExit(f"vgmstream-cli not found: {args.vgmstream_cli}")
    t0 = time.time()
    env, problems = load_env()
    if problems:
        raise SystemExit("; ".join(problems))
    mcc_root = require_path(env, "HALO_MCC_FOLDER", "dir")
    files = verify_copies(mcc_root)
    source = {"steam": mcc_source_build(mcc_root),
              "spanish_fsb_sha256": files["spanish.fsb"]["sha256"], "english_fsb_sha256": files["english.fsb"]["sha256"]}

    banks, lsts, layout = {}, {}, {}
    for lang in LANGUAGES:
        fsb_rel, lst_rel = FILES[lang]["fsb"][0], FILES[lang]["lst"][0]
        bank = FsbBank(COPIES / fsb_rel)
        banks[lang] = BankIndex(bank, lang, Path(fsb_rel).name)
        lsts[lang] = parse_lst((COPIES / lst_rel).read_bytes())["records"]
        layout[lang] = check_ranges(lsts[lang], bank.header["num_samples"])
    records, issues = build_level(level, lsts["english"], lsts["spanish"], banks, source)
    if not records:
        raise SystemExit(f"no tags found for level {level}")
    for lang, chk in layout.items():
        if not (chk["contiguous_from_zero"] and chk["total_matches_bank"]):
            issues.append({"code": "lst_layout_check_failed", "language": lang, **chk})

    cat_dir = WORK / "catalog"
    cat_dir.mkdir(parents=True, exist_ok=True)
    catalog = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n" for r in
                      sorted(records, key=lambda r: (min([s["index"] for s in r["samples"]["spanish"]] or [10**9]),
                                                     r["tag_name"])))
    cat_path = cat_dir / f"{level}.jsonl"
    cat_path.write_text(catalog, encoding="utf-8", newline="\n")

    out_root = WORK / "audio" / level
    units = export_plan(records)
    fsb_paths = {lang: COPIES / FILES[lang]["fsb"][0] for lang in LANGUAGES}
    export_units(units, out_root, make_decoder(args.vgmstream_cli, fsb_paths), inspect_wav, sha256_file)
    expected = {(out_root / u["wav_path"]).resolve() for u in units}
    leftovers = sorted(p.relative_to(out_root).as_posix() for p in out_root.rglob("*.wav") if p.resolve() not in expected)

    build = {"schema": BUILD_SCHEMA, "source_build": source["steam"], "files": files, "lst_layout": layout,
             "catalogs": {level: {"path": cat_path.relative_to(REPO_ROOT).as_posix(), "record_schema": RECORD_SCHEMA,
                                  "records": len(records), "sha256": sha256_file(cat_path),
                                  "tool": "scripts/catalog/build_mcc_catalog.py"}}}
    build_path = WORK / "build.json"
    if build_path.exists():
        old = json.loads(build_path.read_text(encoding="utf-8"))
        if old.get("files") == files:
            build["catalogs"] = {**old.get("catalogs", {}), **build["catalogs"]}
    build_path.write_text(dumps_json(build), encoding="utf-8", newline="\n")

    manifest = {"schema": EXPORT_SCHEMA, "level": level,
                "source_catalog": {"path": cat_path.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_file(cat_path)},
                "source_files": {k: {"copy": v["copy"], "sha256": v["sha256"]} for k, v in files.items()},
                "decoder": vgmstream_info(args.vgmstream_cli), "wav_root": out_root.relative_to(REPO_ROOT).as_posix(),
                "units": units, "files_not_in_plan": leftovers}
    (out_root / "manifest.json").write_text(dumps_json(manifest), encoding="utf-8", newline="\n")

    cov = coverage(level, records, issues, units)
    cov["files_not_in_plan"] = leftovers
    cov["problem_units"] = [{"key": u["key"], "status": u["status"], "reason": u.get("reason"),
                             "mcc_tag": u["mcc_tag"]} for u in units
                            if u["status"] != "ok" or not u["frames_match_header"]]
    rep = WORK / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / f"{level}_coverage.json").write_text(dumps_json(cov), encoding="utf-8", newline="\n")
    (rep / f"{level}_issues.json").write_text(dumps_json({"schema": "mcc-issues-report/1", "level": level,
                                                          "issues": issues,
                                                          "unresolved": [{"mcc_tag": r["mcc_tag"], **u} for r in records
                                                                         for u in r.get("unresolved", [])]}),
                                              encoding="utf-8", newline="\n")
    (rep / f"{level}_summary.md").write_text(summary_md(level, build, cov, issues), encoding="utf-8", newline="\n")
    picks = recommend(records, units)
    (rep / f"{level}_review_picks.json").write_text(dumps_json(picks), encoding="utf-8", newline="\n")
    (rep / f"{level}_review_picks.md").write_text(picks_md(level, picks), encoding="utf-8", newline="\n")

    n_ok = sum(1 for u in units if u["status"] == "ok")
    print(f"{len(records)} tags, {len(units)} samples decoded, {n_ok} OK, {len(cov['problem_units'])} problems, "
          f"{len(issues)} issues ({time.time() - t0:.1f}s)")
    for p in (cat_path, build_path, out_root / "manifest.json"):
        print(f"  wrote {p.relative_to(REPO_ROOT).as_posix()}")
    print(f"  wrote work/mcc/reports/{level}_{{coverage,issues,summary,review_picks}}.*")


if __name__ == "__main__":
    main()
