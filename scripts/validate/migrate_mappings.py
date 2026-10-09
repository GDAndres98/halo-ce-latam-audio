"""Upgrade mappings/manual_mappings.json to the current schema (manual-mappings/3).

v2 -> v3 moves the v1.1 radio flag out of the approval-protected audio
object: `audio.fx_request == "radio"` becomes the slot-level
`radio_effect: {needed, set_at, revision}`. No decision changes:
mapping_store.migrate() refuses if any approved audio or subtitle object
would differ (other than the dropped field). The old bytes are backed up to
mappings/.history/ and the file is replaced atomically.

Example:
    python scripts/validate/migrate_mappings.py            # dry run: shows what would change
    python scripts/validate/migrate_mappings.py --write
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import mapping_store  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=REPO_ROOT / "mappings" / "manual_mappings.json")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    doc, sha = mapping_store.load(args.file)
    new, changed = mapping_store.migrate_doc(doc)
    if not changed:
        print(f"{args.file.name} is already {doc.get('schema')}; nothing to do")
        return
    flagged = sum(1 for s in new["slots"] if s["radio_effect"]["needed"])
    print(f"{doc['schema']} -> {new['schema']}: {len(new['slots'])} slot(s), {flagged} radio flag(s) carried over")
    if not args.write:
        print("dry run; re-run with --write to apply")
        return
    new_sha, _ = mapping_store.migrate(args.file, sha)
    print(f"wrote {args.file.name} (sha256 {new_sha[:16]}…); previous bytes in mappings/.history/")


if __name__ == "__main__":
    main()
