"""Decode the catalog-linked Campaign Evolved recordings of one mission to WAV (milestone M1b).

Input is the M1 catalog (work/ce/catalog/<mission>.jsonl). Each referenced
.wem is read from the language pak (read-only), checked against the
catalog's sha256, copied byte-identical to work/ce/media/, and decoded with
the approved vgmstream-cli. Outputs (all git-ignored):

    work/ce/media/<language>/<media_id>.wem          original media, unmodified copies
    work/ce/audio/<mission>/<language>/<ref>.wav     one WAV per (language, media_id)
    work/ce/audio/<mission>/manifest.json            deterministic export manifest
    work/ce/reports/<mission>_audio_coverage.json    coverage + problems
    work/ce/reports/<mission>_audio_summary.md       readable digest (no game text)
    work/ce/reports/<mission>_review_picks.json|md   five varied lines for a human check

Records flagged `test_event` (the `_lipsync` assets) are excluded from
decoding and reported as excluded. Never reads or writes mappings/
except to read verifications.json if it exists; never matches to MCC.

Example:
    python scripts/extraction/export_ce_audio.py --mission M01 \
        --vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.asset_metadata import CEContext  # noqa: E402
from common.ce_audio_export import (  # noqa: E402
    EXCLUDE_FLAGS, EXPORT_LANGUAGES, EXPORT_SCHEMA, OK, coverage, dumps_json, export_units, manual_review_items,
    plan, recommend, sha256_file)
from common.ce_build import source_build_ids  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402

WORK = REPO_ROOT / "work" / "ce"
DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")
# Verified before verifications.json exists (docs/poc-ce-line-link.md, future entry v-000001).
KNOWN_VERIFIED = {"vo_scr_m01_00460_cryotech#0"}


def vgmstream_info(exe):
    res = subprocess.run([str(exe), "-V"], capture_output=True, text=True)
    try:
        version = json.loads(res.stdout).get("version")
    except ValueError:
        version = None
    return {"name": "vgmstream-cli", "version": version, "exe_sha256": sha256_file(exe)}


def make_decoder(exe):
    def decode(wem, wav):
        res = subprocess.run([str(exe), "-o", str(wav), str(wem)], capture_output=True, text=True)
        return res.returncode == 0, (res.stderr or res.stdout or "").strip()
    return decode


def make_source_reader(ctx):
    paks = {}

    def read(u):
        lang = u["language"]
        if lang not in paks:
            paks[lang] = ctx.pak_for_wwise_language(lang)
        pak = paks[lang]
        if not pak or u["wem_vfs_path"] not in pak.files:
            return None
        return pak.read(u["wem_vfs_path"], ctx.oodle)
    return read


def verified_refs():
    refs = set(KNOWN_VERIFIED)
    p = REPO_ROOT / "mappings" / "verifications.json"
    if p.exists():  # read-only
        for v in json.loads(p.read_text(encoding="utf-8")).get("verifications", []):
            if v.get("subject", "").startswith("ce:"):
                refs.add(v["subject"][3:])
    return refs


def summary_md(mission, manifest, cov):
    L = [f"# Campaign Evolved {mission} audio export — summary", "",
         f"Catalog `{manifest['source_catalog']['path']}` sha256 `{manifest['source_catalog']['sha256'][:16]}…`; "
         f"decoder {manifest['decoder']['name']} {manifest['decoder']['version']}. No game text in this file.", "",
         "| | " + " | ".join(cov["languages"]) + " |", "|---|" + "---|" * len(cov["languages"])]
    rows = [("references", lambda c: c["references"]),
            ("excluded (test event)", lambda c: c["reference_status"].get("excluded:test_event", 0)),
            ("missing in catalog", lambda c: c["reference_status"].get("missing_in_catalog", 0)),
            ("references with OK audio", lambda c: c["references_with_ok_audio"]),
            ("unique media decoded (units)", lambda c: c["units"]),
            ("units shared by >1 reference", lambda c: c["deduplicated_units"]),
            ("unit status", lambda c: ", ".join(f"{k} {v}" for k, v in c["unit_status"].items())),
            ("sample rates", lambda c: ", ".join(f"{k} Hz ×{v}" for k, v in c["sample_rates"].items())),
            ("channels", lambda c: ", ".join(f"{k}ch ×{v}" for k, v in c["channels"].items())),
            ("duration min / median / max s", lambda c: "{min} / {median} / {max}".format(**c["duration_s"])
             if c["duration_s"] else "-"),
            ("total duration s", lambda c: c["duration_s"]["total"] if c["duration_s"] else "-")]
    for title, fn in rows:
        L.append(f"| {title} | " + " | ".join(str(fn(c)) for c in cov["languages"].values()) + " |")
    L += ["", f"All linked references accounted for: {cov['all_references_accounted_for']}. "
              f"Problem units: {len(cov['problem_units'])}. "
              f"Identical audio under different media IDs: {len(cov['identical_audio_different_media_id'])}.", ""]
    if manifest["manual_review"]:
        L += ["## Kept for manual review", ""]
        L += [f"- `{m['ce_line_ref']}` ({', '.join(m['flags'])}): event `{m['event'].rsplit('/', 1)[-1]}`, "
              f"subtitle table `{m['string_table'].rsplit('/', 1)[-1]}`" for m in manifest["manual_review"]]
        L.append("")
    return "\n".join(L)


def picks_md(mission, picks):
    L = [f"# {mission} — five lines for listening + reading review", "",
         "Selected deterministically for variety, not as match suggestions. Paths are relative to "
         f"`work/ce/audio/{mission.lower()}/`. Contains game text: local file only, git-ignored.", ""]
    for n, p in enumerate(picks["picks"], 1):
        L += [f"## {n}. `{p['ce_line_ref']}`: {p['why']}", "",
              f"Family {p['family']}, speaker {p['speaker']}, flags {', '.join(p['flags']) or 'none'}.", ""]
        for lang, a in p["audio"].items():
            shared = [r for r in a["shared_with"] if r != p["ce_line_ref"]]
            L.append(f"- **{lang}** `{a['wav_path']}` ({a['duration_s']} s, media {a['media_id']})"
                     + (f"; same file as `{', '.join(shared)}`" if shared else ""))
        for c, s in p["subtitles"].items():
            L.append(f"- subtitle **{c}**: " + (f"{s['text']}" if "text" in s else f"_{s.get('evidence')}: {s.get('reason')}_"))
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", default="M01")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
    mission, m = args.mission.upper(), args.mission.lower()
    if not args.vgmstream_cli.is_file():
        raise SystemExit(f"vgmstream-cli not found: {args.vgmstream_cli}")
    t0 = time.time()

    cat_path = WORK / "catalog" / f"{m}.jsonl"
    cat_bytes = cat_path.read_bytes()
    records = [json.loads(line) for line in cat_bytes.decode("utf-8").splitlines() if line.strip()]
    schemas = {r["schema"] for r in records}
    if schemas != {"ce-voice-asset/3"}:
        raise SystemExit(f"unexpected catalog schema(s) {schemas}; rebuild with build_ce_catalog.py")
    ctx = CEContext(oodle_dll=args.oodle_dll)
    build_ids = source_build_ids(ctx)
    stale = {r["record_id"] for r in records if r["source_build"] != build_ids}
    if stale:
        raise SystemExit(f"{len(stale)} catalog records were built from a different game build; rebuild the catalog")

    units, refs = plan(records)
    out_root = WORK / "audio" / m
    media_root = WORK / "media"
    export_units(units, out_root, media_root, make_source_reader(ctx), make_decoder(args.vgmstream_cli))

    expected = {(out_root / u["wav_path"]).resolve() for u in units.values()}
    leftovers = sorted(p.relative_to(out_root).as_posix() for p in out_root.rglob("*.wav")
                       if p.resolve() not in expected)
    manifest = {
        "schema": EXPORT_SCHEMA, "mission": mission,
        "source_catalog": {"path": cat_path.relative_to(REPO_ROOT).as_posix(),
                           "sha256": sha256_file(cat_path), "record_schema": "ce-voice-asset/3",
                           "records": len(records)},
        "source_build": build_ids,
        "decoder": vgmstream_info(args.vgmstream_cli),
        "languages": list(EXPORT_LANGUAGES),
        "exclusion_rules": {f"excluded:{k}": v for k, v in EXCLUDE_FLAGS.items()},
        "wav_root": out_root.relative_to(REPO_ROOT).as_posix(),
        "media_root": media_root.relative_to(REPO_ROOT).as_posix(),
        "units": [units[k] for k in sorted(units)],
        "references": refs,
        "manual_review": manual_review_items(records),
        "files_not_in_plan": leftovers,  # reported, never deleted
    }
    (out_root / "manifest.json").write_text(dumps_json(manifest), encoding="utf-8", newline="\n")
    cov = coverage(units, refs)
    cov["mission"] = mission
    cov["files_not_in_plan"] = leftovers
    rep = WORK / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / f"{m}_audio_coverage.json").write_text(dumps_json(cov), encoding="utf-8", newline="\n")
    (rep / f"{m}_audio_summary.md").write_text(summary_md(mission, manifest, cov), encoding="utf-8", newline="\n")
    picks = recommend(records, units, refs, already_verified=verified_refs())
    (rep / f"{m}_review_picks.json").write_text(dumps_json(picks), encoding="utf-8", newline="\n")
    (rep / f"{m}_review_picks.md").write_text(picks_md(mission, picks), encoding="utf-8", newline="\n")

    n_ok = sum(1 for u in units.values() if u.get("status") == OK)
    print(f"{len(units)} unique media, {n_ok} OK, {len(units) - n_ok} problems, "
          f"{len(cov['missing_in_catalog'])} missing in catalog, excluded {cov['excluded']} ({time.time() - t0:.1f}s)")
    for name in ("manifest.json",):
        print(f"  wrote {(out_root / name).relative_to(REPO_ROOT).as_posix()}")
    for name in ("audio_coverage.json", "audio_summary.md", "review_picks.json", "review_picks.md"):
        print(f"  wrote {(rep / f'{m}_{name}').relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
