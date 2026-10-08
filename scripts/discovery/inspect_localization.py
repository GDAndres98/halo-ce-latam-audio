"""Read-only Campaign Evolved .locres inspector.

Lists localization targets/cultures, or looks up (namespace, key) across
cultures. Output goes to stdout only (subtitle text never enters Git).

Example:
    python scripts/discovery/inspect_localization.py --list
    python scripts/discovery/inspect_localization.py --target Subtitles \
        --namespace VO_SCR_M01PILLAROFAUTUMN --key VO_SCR_M01_00460_CryoTech --cultures en,es-MX,es-ES
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.asset_metadata import CEContext  # noqa: E402
from common.locres import parse_locres  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--target", default="Subtitles")
    ap.add_argument("--namespace")
    ap.add_argument("--key")
    ap.add_argument("--cultures", default="en,es-MX,es-ES")
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
    ctx = CEContext(oodle_dll=args.oodle_dll)
    p0 = ctx.pak("pakchunk0-Windows.pak")
    prefix = "Meteorite/Content/Localization/"
    if args.list:
        for f in sorted(p0.files):
            if f.startswith(prefix) and f.endswith((".locres", ".locmeta")):
                e = p0.entry(f)
                print(f"{f[len(prefix):]}\t{e['usize']} B\t{'compressed' if e['method'] else 'stored'}")
        return
    for culture in args.cultures.split(","):
        path = f"{prefix}{args.target}/{culture}/{args.target}.locres"
        if path not in p0.files:
            print(f"{culture}: no {args.target}.locres")
            continue
        version, table = parse_locres(p0.read(path, ctx.oodle))
        total = sum(len(v) for v in table.values())
        if not args.namespace:
            print(f"{culture}: v{version}, {len(table)} namespaces, {total} entries")
            continue
        hit = table.get(args.namespace, {}).get(args.key) if args.key else None
        if args.key:
            print(f"{culture}: {'FOUND' if hit else 'missing'}\t{hit['text'] if hit else ''}")
        else:
            print(f"{culture}: namespace has {len(table.get(args.namespace, {}))} keys")


if __name__ == "__main__":
    main()
