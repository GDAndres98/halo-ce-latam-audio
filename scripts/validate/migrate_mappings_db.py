"""Dry-run migration of mappings/manual_mappings.json into SQLite (read-only for mappings/).

    python scripts/validate/migrate_mappings_db.py                 # default: work/db/dry-run/
    python scripts/validate/migrate_mappings_db.py --out work/db/x

What it does:
1. Reads the live manual_mappings.json bytes and records their SHA-256.
2. Imports the document into a NEW SQLite file under --out.
3. Reads the database back, rebuilds the document and proves it is byte-identical
   to the source file.
4. Checks indexed columns, approval counts and schema validity.
5. Writes report.json next to the database.

It never writes under mappings/ and never changes approvals. Exit code 1 means a
check failed; the database is then not safe to use as a source of truth.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from common import mapping_db  # noqa: E402
from common.jsonschema_lite import load_schema, validate  # noqa: E402

SOURCE = REPO_ROOT / "mappings" / "manual_mappings.json"
DEFAULT_OUT = REPO_ROOT / "work" / "db" / "dry-run"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def status_counts(doc):
    slots = doc["slots"]
    return {
        "slots": len(slots),
        "match": dict(Counter(s["match"]["status"] for s in slots)),
        "audio": dict(Counter(s["audio"]["status"] for s in slots)),
        "subtitle": dict(Counter(s["subtitle"]["status"] for s in slots)),
        "radio_needed": sum(1 for s in slots if s["radio_effect"]["needed"]),
    }


def migrate(source, out_dir):
    """Import, read back and verify. Returns (report, ok). Raises only for unusable inputs."""
    raw = Path(source).read_bytes()
    source_doc = json.loads(raw.decode("utf-8"))
    out_dir = Path(out_dir)
    db_path = out_dir / "mappings.sqlite"

    conn = mapping_db.create(db_path)
    try:
        mapping_db.import_document(conn, source_doc)
    finally:
        conn.close()

    conn = mapping_db.open_existing(db_path)  # read back from disk, not from memory
    try:
        exported = mapping_db.export_document(conn)
        bad_columns = mapping_db.check_derived_columns(conn)
    finally:
        conn.close()

    checks = {
        "source_is_v3": source_doc.get("schema") == mapping_db.SOURCE_SCHEMA,
        "export_is_byte_identical": mapping_db.serialize(exported) == raw,
        "export_passes_schema": not validate(exported, load_schema("manual-mappings-3")),
        "derived_columns_match_bodies": not bad_columns,
        "slot_count_matches": len(exported["slots"]) == len(source_doc["slots"]),
        "approval_counts_match": status_counts(exported) == status_counts(source_doc),
    }
    report = {
        "tool": "migrate_mappings_db",
        "db_schema_version": mapping_db.DB_SCHEMA_VERSION,
        "source": str(Path(source).as_posix()),
        "source_sha256": sha256(raw),
        "database": str(db_path.as_posix()),
        "database_sha256": sha256(db_path.read_bytes()),
        "counts": status_counts(source_doc),
        "bad_derived_positions": bad_columns[:20],
        "checks": checks,
        "ok": all(checks.values()),
    }
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    out = args.out.resolve()
    if REPO_ROOT / "mappings" in [out, *out.parents]:
        ap.error("--out must not be inside mappings/ (the live decisions folder)")
    if (out / "mappings.sqlite").exists():
        ap.error(f"{out / 'mappings.sqlite'} exists; remove it or pick --out")

    report = migrate(args.source, out)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print(f"slots={report['counts']['slots']}  database={report['database']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
