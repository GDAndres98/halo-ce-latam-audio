"""Read-only Campaign Evolved IoStore inspector.

  --headers            container flags (compression/encryption) for every .utoc
  --find SUBSTR        list package paths containing SUBSTR (case-insensitive)
  --dump VFS_PATH      decode a package's exports with the .usmap -> work/ce/inspect/<name>.json

Example:
    python scripts/discovery/inspect_iostore.py --find vo_scr_m01_00460
    python scripts/discovery/inspect_iostore.py --dump Meteorite/Content/Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech.uasset
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.asset_metadata import CEContext  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.zen import UnsupportedProperty  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--headers", action="store_true")
    ap.add_argument("--find")
    ap.add_argument("--dump")
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
    ctx = CEContext(oodle_dll=args.oodle_dll)

    if args.headers:
        for s in ctx.stores:
            h = s.header
            print(f"{s.utoc.name:28s} entries={h['entry_count']:7d} compressed={h['compressed']} "
                  f"encrypted={h['encrypted']} key_guid_zero={h['key_guid_is_zero']} methods={s.methods}")
    if args.find:
        needle = args.find.lower()
        for s in ctx.stores:
            for p in s.files:
                if needle in p.lower():
                    print(f"{s.utoc.name}\t{p}")
    if args.dump:
        info = ctx.load_package(args.dump)
        if not info:
            raise SystemExit("package not found")
        pkg = info["package"]
        out = {"vfs_path": info["vfs_path"], "container": info["container"], "package_name": pkg.name,
               "imported_packages": pkg.imported_package_names, "exports": []}
        for i, e in enumerate(pkg.exports):
            item = {"name": e["name"], "class": e["class"]}
            try:
                props, r = pkg.read_export_properties(i)
                item["properties"] = props
                item["unparsed_trailing_bytes"] = pkg.export_data(i)[1] - r.pos
            except (UnsupportedProperty, KeyError) as ex:
                item["properties"] = None
                item["unresolved"] = f"{type(ex).__name__}: {ex}"
            out["exports"].append(item)
        dest = REPO_ROOT / "work" / "ce" / "inspect" / (pkg.name.rsplit("/", 1)[-1] + ".json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"wrote {dest.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
