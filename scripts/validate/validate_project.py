"""Read-only validation of catalogs and user-owned mapping files (milestone M3).

Checks, without modifying anything:
  - generated catalogs: schema, CE/MCC separation, duplicate IDs, provenance vs build.json;
  - mappings/manual_mappings.json: schema, IDs and references, duplicates and conflicts,
    independent audio/subtitle rules, approved-object protection vs git HEAD, pins,
    fingerprint drift;
  - mappings/manual_mappings.local.json: schema, and that git ignores it;
  - mappings/verifications.json: schema, sequence, append-only vs HEAD, subjects, drift;
  - mappings/mission_map.json: schema, duplicates;
  - repository hygiene: no game assets, work/ or reference-audio/ files tracked by git.

Writes only work/reports/validation.json and work/reports/drift.json (use --no-write to skip).
Never edits a mapping, verification, catalog or game file. Exit code 1 if any error.

Example:
    python scripts/validate/validate_project.py
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT  # noqa: E402
from common.jsonschema_lite import load_schema  # noqa: E402
from common.project_validation import (  # noqa: E402
    build_ce_index, build_mcc_index, check_approved_protected, dumps, finding, validate_catalog, validate_mappings,
    validate_mission_map, validate_verifications)
from common.jsonschema_lite import validate as schema_validate  # noqa: E402

ASSET_RE = re.compile(r"\.(map|pak|ucas|utoc|fsb|wav|ogg|bnk|wem|7z|locres|uasset|usmap|raw|bin)$|(^|/)\.env$|"
                      r"^(work|reference-audio|extracted|scratch)/|\.local\.json$", re.I)
USER_FILES = {"mappings": "mappings/manual_mappings.json", "local": "mappings/manual_mappings.local.json",
              "verifications": "mappings/verifications.json", "mission_map": "mappings/mission_map.json"}


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    return r


def head_json(root, rel):
    r = git(root, "show", f"HEAD:{rel}")
    if r is None or r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def read_json(path, out, rel):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError as e:
        out.append(finding("error", "invalid_json", rel, "/", str(e)))
        return None


def load_catalogs(root, out):
    ce_records, mcc_records = [], []
    for kind, sub, schema_name, schema_id, sink in (
            ("ce", "work/ce", "ce-voice-asset-3", "ce-voice-asset/3", ce_records),
            ("mcc", "work/mcc", "mcc-dialogue-tag-3", "mcc-dialogue-tag/3", mcc_records)):
        build = read_json(root / sub / "build.json", out, f"{sub}/build.json")
        schema = load_schema(schema_name)
        for p in sorted((root / sub / "catalog").glob("*.jsonl")):
            data = p.read_bytes()
            records = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
            rel = p.relative_to(root).as_posix()
            out += validate_catalog(rel, records, schema, schema_id, build, hashlib.sha256(data).hexdigest())
            sink += records
    return ce_records, mcc_records


def current_pins(root):
    ce = read_json(root / "work/ce/build.json", [], "") or {}
    mcc = read_json(root / "work/mcc/build.json", [], "") or {}
    return {"ce_build": (ce.get("source_build") or {}).get("exe_file_version"),
            "mcc_steam_buildid": (mcc.get("source_build") or {}).get("steam_buildid"),
            "mcc_spanish_fsb_sha256": ((mcc.get("files") or {}).get("spanish.fsb") or {}).get("sha256")}


def run(root, use_git=True):
    out, drift = [], []
    ce_records, mcc_records = load_catalogs(root, out)
    ce, mcc = build_ce_index(ce_records), build_mcc_index(mcc_records)
    # cross-catalog uniqueness (several missions / levels)
    for label, keys in (("ce_line_ref", [e["ce_line_ref"] for r in ce_records for e in r["entries"]]),
                        ("slot_id", [s for r in mcc_records for s in r["slot_ids"]])):
        for k, n in Counter(keys).items():
            if n > 1:
                out.append(finding("error", "duplicate_id_across_catalogs", "catalogs", k, f"{label} appears {n}x"))

    docs = {k: read_json(root / rel, out, rel) for k, rel in USER_FILES.items()}
    heads = {k: head_json(root, rel) for k, rel in USER_FILES.items()} if use_git else {}

    local = docs["local"]
    if local is not None:
        errs = schema_validate(local, load_schema("manual-mappings-local-1"))
        out += [finding("error", "schema", USER_FILES["local"], e.split(":")[0], e) for e in errs]
        if errs:
            local = None
    if use_git:
        r = git(root, "check-ignore", "-q", USER_FILES["local"])
        if r is not None and r.returncode != 0:
            out.append(finding("error", "local_file_not_ignored", USER_FILES["local"], "/",
                               "custom text and local paths must stay git-ignored"))
        tracked = git(root, "ls-files")
        for f in (tracked.stdout.splitlines() if tracked and tracked.returncode == 0 else []):
            if ASSET_RE.search(f):
                out.append(finding("error", "proprietary_or_local_file_tracked", f, "/",
                                   "game assets, work/, reference-audio/, .env and *.local.json must not be in git"))

    if docs["verifications"] is None:
        out.append(finding("warning", "file_missing", USER_FILES["verifications"], "/", "no verifications yet"))
    else:
        f, d = validate_verifications(docs["verifications"], load_schema("verifications-1"), ce=ce, mcc=mcc,
                                      head_doc=heads.get("verifications"), file=USER_FILES["verifications"])
        out += f
        drift += d

    if docs["mappings"] is None:
        out.append(finding("error", "file_missing", USER_FILES["mappings"], "/",
                           "create it from the empty template (docs/dialogue-catalog-design.md §5.1)"))
    else:
        f, d = validate_mappings(docs["mappings"], load_schema("manual-mappings-2"), ce=ce, mcc=mcc, local=local,
                                 verifications=docs["verifications"], current_pins=current_pins(root),
                                 file=USER_FILES["mappings"])
        out += f
        drift += d
        out += check_approved_protected(heads.get("mappings"), docs["mappings"], USER_FILES["mappings"])

    if docs["mission_map"] is not None:
        out += validate_mission_map(docs["mission_map"], load_schema("mission-map-1"),
                                    ce_missions={r["mission"] for r in ce_records},
                                    mcc_levels={r["level"] for r in mcc_records}, file=USER_FILES["mission_map"])
    summary = {"catalog_records": {"ce": len(ce_records), "mcc": len(mcc_records)},
               "ce_line_refs": len(ce), "mcc_slots": len(mcc["slots"]),
               "mappings": len((docs["mappings"] or {}).get("slots", [])),
               "verifications": len((docs["verifications"] or {}).get("verifications", [])),
               "by_severity": dict(sorted(Counter(x["severity"] for x in out).items())),
               "drift_entries": len(drift)}
    out.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}[x["severity"]], x["file"], x["code"], x["where"]))
    return {"schema": "validation-report/1", "summary": summary, "findings": out}, \
        {"schema": "drift-report/1", "drift": drift}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--no-git", action="store_true", help="skip HEAD comparisons and git hygiene checks")
    ap.add_argument("--no-write", action="store_true", help="print only; do not write work/reports/")
    args = ap.parse_args()
    report, drift = run(args.root, use_git=not args.no_git)
    if not args.no_write:
        rep = args.root / "work" / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "validation.json").write_text(dumps(report), encoding="utf-8", newline="\n")
        (rep / "drift.json").write_text(dumps(drift), encoding="utf-8", newline="\n")
    s = report["summary"]
    print(f"catalog records ce={s['catalog_records']['ce']} mcc={s['catalog_records']['mcc']}; "
          f"mappings={s['mappings']} verifications={s['verifications']}; findings {s['by_severity'] or 'none'}; "
          f"drift {s['drift_entries']}")
    for x in report["findings"]:
        if x["severity"] != "info":
            print(f"  [{x['severity']}] {x['code']} {x['file']} {x['where']}: {x['message']}")
    sys.exit(1 if s["by_severity"].get("error") else 0)


if __name__ == "__main__":
    main()
