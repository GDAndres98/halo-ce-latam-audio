"""Which MCC dialogue folders/tags does each playable Halo CE map use? (read-only evidence)

For every campaign map in the install (halo1/maps/<level>.map, read-only) this lists the
`sound\\dialog\\...` tag paths stored in the map. A Halo CE cache file carries the full path of
every tag it contains, so a dialogue tag path inside a10.map means that sound tag is built into
The Pillar of Autumn (gameplay or its in-engine cinematics). Evidence label:
`derived:map_tag_path_scan` (byte scan for tag-path strings, not a parse of the tag index).

Writes only work/mcc/level_folders.json (`mcc-level-folders/1`):
  {levels: {a10: {map_sha256, folders: {a10: {tags, tags_in_catalog, catalog_tags}, x10: {...}}}},
   folders: {x10: {used_by: [a10]}}, ...}
Used by scripts/build/m6_build.py --mission <level> to select a mission's dialogue folders.

Example:
    python scripts/catalog/build_level_folders.py
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402

CAMPAIGN = ("a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40")
TAG_RE = re.compile(rb"sound\\dialog\\[A-Za-z0-9_ \\]+")
SCHEMA = "mcc-level-folders/1"


def tag_paths(data):
    """Dialogue tag paths in a map's bytes, lower-cased (folders below dialog\\ are kept)."""
    out = set()
    for m in TAG_RE.finditer(data):
        p = m.group(0).decode("ascii").rstrip("\\ ").lower()
        if p.count("\\") >= 3:
            out.add(p)
    return out


def catalog_tags():
    tags = {}
    for p in sorted((REPO_ROOT / "work" / "mcc" / "catalog").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            tags[r["mcc_tag"].lower()] = p.stem
    return tags


def main():
    env, problems = load_env()
    if problems:
        raise SystemExit("; ".join(problems))
    root = require_path(env, "HALO_MCC_FOLDER", "dir")
    cat = catalog_tags()
    levels, used_by = {}, defaultdict(list)
    for lv in CAMPAIGN:
        path = root / "halo1" / "maps" / f"{lv}.map"
        if not path.is_file():
            continue
        data = path.read_bytes()  # read-only
        found = tag_paths(data)
        known = sorted(t for t in found if t in cat)
        folders = defaultdict(list)
        for t in known:
            folders[cat[t]].append(t)
        levels[lv] = {"map": f"halo1/maps/{lv}.map", "map_sha256": hashlib.sha256(data).hexdigest(),
                      "evidence": "derived:map_tag_path_scan",
                      "dialogue_tag_paths_found": len(found), "unmatched_paths": sorted(set(found) - set(known)),
                      "folders": {f: {"tags": len(ts), "catalog_tags": None, "tag_paths": ts}
                                  for f, ts in sorted(folders.items())}}
        for f in folders:
            used_by[f].append(lv)
    per_folder = defaultdict(int)
    for t, f in cat.items():
        per_folder[f] += 1
    for lv in levels.values():
        for f, v in lv["folders"].items():
            v["catalog_tags"] = per_folder[f]
    out = {"schema": SCHEMA, "levels": levels,
           "folders": {f: {"used_by": sorted(v), "catalog_tags": per_folder[f]} for f, v in sorted(used_by.items())},
           "folders_in_no_campaign_map": sorted(set(per_folder) - set(used_by))}
    dst = REPO_ROOT / "work" / "mcc" / "level_folders.json"
    dst.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for lv, v in levels.items():
        print(lv, ", ".join(f"{f} {x['tags']}/{x['catalog_tags']}" for f, x in v["folders"].items()),
              f"(unmatched paths {len(v['unmatched_paths'])})")
    print("in no campaign map:", out["folders_in_no_campaign_map"])
    print("wrote", dst.relative_to(REPO_ROOT).as_posix())


if __name__ == "__main__":
    main()
