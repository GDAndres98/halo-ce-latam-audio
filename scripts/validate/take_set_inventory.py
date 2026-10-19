"""Read-only inventory: which multi-take sounds could be converted to a replacement set, and which need review
(docs/replacement-set-conversion.md).

    python scripts/validate/take_set_inventory.py [--root .] [--level a10] [--report work/reports/take_set_inventory.json]
                                                  [--sound "sound\\dialog\\...\\death_violent"]

Strictly read-only, and safe while the Studio runs:
- reads mappings/manual_mappings.json and manual_mappings.local.json as plain files. It never goes through
  mapping_store.load, which could import the file into the database or upgrade the database's schema;
- opens mappings/manual_mappings.db (if it exists) read-only (SQLite mode=ro) only to compare its recorded export
  hash with the file, so the counts are known to describe the database's decisions. A database is never created;
- reads the MCC and CE catalogs and the SU/SP copies under work/.
Writes nothing but the optional --report file. It changes no decision, approves nothing and pairs nothing.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.mcc_loc import parse_mcc_loc  # noqa: E402
from common.project_validation import build_ce_index, build_mcc_index  # noqa: E402
from common.take_set_conversion import inventory, plan_sound  # noqa: E402


def _jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def read_only_state(root):
    """-> (doc, local, sync) without touching the database except a read-only look at its export hash."""
    path = root / "mappings" / "manual_mappings.json"
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    lp = root / "mappings" / "manual_mappings.local.json"
    local = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else {"custom_subtitles": {}, "user_recordings": {}}
    db = root / "mappings" / "manual_mappings.db"
    sync = {"file_sha256": hashlib.sha256(raw).hexdigest(), "database": None, "in_sync": None}
    if db.is_file():
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)  # read-only: no upgrade, no write
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'export_sha256'").fetchone()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        lf = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        sync.update(database={"schema_version": version, "export_sha256": row and row[0]},
                    in_sync=bool(row) and row[0] in (sync["file_sha256"], lf))
    return doc, local, sync


def catalogs(root):
    records, mcc_recs = {}, []
    for p in sorted((root / "work" / "mcc" / "catalog").glob("*.jsonl")):
        for r in _jsonl(p):
            mcc_recs.append(r)
            records.setdefault(r["mcc_tag"], (p.stem, r))
    ce_recs, ce_lines = [], {}
    for p in sorted((root / "work" / "ce" / "catalog").glob("*.jsonl")):
        for r in _jsonl(p):
            ce_recs.append(r)
            for e in r["entries"]:
                ce_lines[e["ce_line_ref"]] = (p.stem.upper(), r, e)
    keys = set()
    for t in ("SU", "SP"):
        f = root / "work" / "mcc" / "loc" / "copies" / f"{t}_Halo1.bin"
        if f.is_file():
            keys |= set(parse_mcc_loc(f.read_bytes())["entries"])
    return records, ce_lines, build_ce_index(ce_recs), build_mcc_index(mcc_recs), keys


def run(root, level=None, sound=None):
    doc, local, sync = read_only_state(root)
    records, ce_lines, ce_idx, mcc_idx, keys = catalogs(root)
    if level:
        records = {t: v for t, v in records.items() if v[0] == level}
    if sound:
        lv, rec = records[sound]
        from common.mcc_loc import loc_key
        return {"sync": sync, "sound": plan_sound(doc, sound, rec, lv, has_subtitle_entry=loc_key(sound) in keys,
                                                  ce_lines=ce_lines, ce_idx=ce_idx, mcc_idx=mcc_idx, local=local,
                                                  subtitle_keys=keys)}
    inv = inventory(doc, records, subtitle_keys=keys, ce_lines=ce_lines, ce_idx=ce_idx, mcc_idx=mcc_idx, local=local)
    review = {}
    for it in inv["sounds"]:
        for c in it.get("review_codes", []):
            review[c] = review.get(c, 0) + 1
    blocked = {}
    for it in inv["sounds"]:
        for c in {i["code"] for i in it["issues"] if i["severity"] == "blocked"}:
            blocked[c] = blocked.get(c, 0) + 1
    return {"sync": sync, "counts": inv["counts"], "review_codes": review, "blocked_codes": blocked,
            "sounds": [{k: it.get(k) for k in ("mcc_tag", "level", "status", "mode", "summary", "review_codes", "reason")}
                       for it in inv["sounds"]], "detail": inv["sounds"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--level")
    ap.add_argument("--sound", help="one mcc_tag: print its full preview")
    ap.add_argument("--report", type=Path, help="also write the full result as JSON here")
    args = ap.parse_args()
    out = run(args.root, args.level, args.sound)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.sound:
        print(json.dumps(out["sound"], indent=2, ensure_ascii=False))
        return
    s = out["sync"]
    print(f"decisions file {s['file_sha256'][:12]}…; database: "
          + ("none" if s["database"] is None else f"schema v{s['database']['schema_version']}, "
             + ("in sync" if s["in_sync"] else "NOT in sync with the file (counts describe the file)")))
    print("counts:", json.dumps(out["counts"]))
    print("review codes (sounds):", json.dumps(out["review_codes"]))
    print("blocked codes (sounds):", json.dumps(out["blocked_codes"]))
    for it in out["sounds"]:
        if it["status"] in ("ready", "review", "blocked"):
            print(f"  {it['status']:<8} {it['mcc_tag']}: {it['summary']}"
                  + (f"  [{', '.join(it['review_codes'])}]" if it["review_codes"] else ""))


if __name__ == "__main__":
    main()
