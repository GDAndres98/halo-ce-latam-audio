"""Check and repair the link between mappings/manual_mappings.db (the source of truth) and its JSON export.

    python scripts/validate/mapping_sync.py status
    python scripts/validate/mapping_sync.py preview-import [--report work/reports/mapping_import_preview.json]
    python scripts/validate/mapping_sync.py import --file-sha256 <sha> --db-sha256 <sha>
    python scripts/validate/mapping_sync.py export --file-sha256 <sha | none>

status          read-only: in_sync, line_endings (same content with CRLF; read as in sync), external_edit,
                missing, pending (a save's JSON write is unfinished; the next read finishes it).
preview-import  read-only: every slot the file would change in the database, and the approvals it would
                add or remove. Prints the two hashes `import` needs.
import          the file's decisions replace the database's. Requires the hashes from preview-import, so a
                file or database that changed in between is refused. Backs the database up to
                mappings/.history/ first and records each changed slot in slot_history (reason import:<sha>).
export          the database is written over the file. Requires the file hash you saw (none if missing);
                a differing file is kept in mappings/.history/ first.

Import and export are owner actions. Close the Studio first (or use its Data page, which does the same).
Never run import on someone's behalf: it can replace approved decisions.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import mapping_store  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "preview-import", "import", "export"])
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--file-sha256")
    ap.add_argument("--db-sha256")
    ap.add_argument("--report", type=Path, help="preview-import: also write the preview as JSON here")
    args = ap.parse_args()
    path = args.root / "mappings" / "manual_mappings.json"
    try:
        if args.command == "status":
            print(json.dumps(mapping_store.sync_status(path), indent=2))
        elif args.command == "preview-import":
            preview = mapping_store.preview_import(path)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(preview, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{len(preview['changes'])} slot(s) would change; line endings {preview['line_endings']}; "
                  f"pins change: {preview['pins_change']}")
            for c in preview["changes"]:
                print(f"  {c['kind']:8} {c['mapping_id']} {c['slot_id']}  fields {', '.join(c['fields'])}")
                for side in ("database", "file"):
                    if c[side]:
                        v = c[side]
                        print(f"    {side:8} match {v['match']} {v['ce_line_refs']} · audio {v['audio']} "
                              f"({v['audio_source']}, rev {v['audio_revision']}) · subtitle {v['subtitle']} "
                              f"({v['subtitle_source']}, rev {v['subtitle_revision']})")
            print(f"approvals added: {preview['approvals_added'] or 'none'}; removed: {preview['approvals_removed'] or 'none'}")
            print(f"to import: --file-sha256 {preview['file_sha256']} --db-sha256 {preview['db_export_sha256']}")
        elif args.command == "import":
            if not (args.file_sha256 and args.db_sha256):
                ap.error("import needs --file-sha256 and --db-sha256 from preview-import")
            print(json.dumps(mapping_store.import_json(path, args.file_sha256, args.db_sha256), indent=2))
        else:
            if not args.file_sha256:
                ap.error("export needs --file-sha256 (the value from status, or none)")
            seen = None if args.file_sha256.lower() == "none" else args.file_sha256
            print(json.dumps({"exported_sha256": mapping_store.export_json(path, seen)}, indent=2))
    except mapping_store.StoreError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
