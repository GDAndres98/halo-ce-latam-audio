"""Publish the edited LATAM previews of APPROVED lines for the public read-only Studio (docs/public-access.md §2.1).

    python scripts/build/publish_previews.py            # render what changed, remove what is no longer approved
    python scripts/build/publish_previews.py --dry-run  # only say what would be published
    python scripts/build/publish_previews.py --slot "es:A10_010_cryotech#0"   # only these lines (repeatable)

Renders each eligible line's saved recipe exactly as the build does, into work/public_previews/ (git-ignored).
Writes nothing else: no mappings, no game files. The public view serves a file only while its line is still
approved and unchanged, and only with "public": {"previews": true} in config/studio_server.json.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
from common.celt011 import DEFAULT_DLL  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from m4_server import DEFAULT_VGMSTREAM, make_app  # noqa: E402
from public_previews import STORE_REL, publish  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slot", action="append", help="publish only this line (slot id); repeatable")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--oodle-dll", type=Path)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    ap.add_argument("--celt-dll", type=Path, default=DEFAULT_DLL)
    args = ap.parse_args()
    app = make_app(args.root, args.vgmstream_cli, args.oodle_dll, args.ffmpeg, args.celt_dll)
    if app.editor is None:
        raise SystemExit("the audio editor is not available (ffmpeg and libcelt are needed)")
    try:
        s = publish(app, args.root, dry_run=args.dry_run, only=set(args.slot) if args.slot else None)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"{'would publish' if s['dry_run'] else 'published'} {s['published']} preview(s) in {STORE_REL}/: "
          f"{s['rendered']} rendered, {s['reused']} unchanged, {len(s['removed'])} removed")
    for sid, why in sorted(s["skipped_approved"].items()):
        print(f"  not published: {sid}: {why}")


if __name__ == "__main__":
    main()
