"""Builds a disposable copy of the mapping data for the browser end-to-end test (frontend/e2e/run.mjs).

    python scripts/ui/e2e_fixture.py --dest <empty folder>

The copy holds the real decisions, custom text and progress, so the test sees the same data you do.
Two things differ, both only in the copy:
- the line the acceptance test works on (es:A10_010_cryotech#0) is reset to undecided. The real decision
  is approved, and an approved decision can only be changed through a Needs-rework step, which is part of
  what the test checks; starting from undecided lets the test walk the whole workflow once.
- work/ and reference-audio/ are linked, not copied (gigabytes of audio). The copy only ever writes its
  own mappings folder and the audio caches under work/; reference-audio/ (the pinned banks) is only read.

The real mappings folder is never written by this script. It prints a JSON line with the paths the test
needs, and a hash of the real decisions so the test can prove they did not change.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ui"))

from common import mapping_db, mapping_store  # noqa: E402
from m4_app import default_slot  # noqa: E402

TEST_SLOT = "es:A10_010_cryotech#0"
SHELL_TEST_FILES = ("manual_mappings.db", "manual_mappings.json", "manual_mappings.local.json",
                    "mission_progress.json", "mission_map.json", "verifications.json")


def reset_test_line(json_path):
    """Make TEST_SLOT undecided in the copy. Written through the database like the store does, then the
    JSON export is rewritten to match, so the copy stays consistent."""
    doc, _ = mapping_store.load(json_path)
    idx = next(i for i, s in enumerate(doc["slots"]) if s["slot_id"] == TEST_SLOT)
    mapping_id, mcc_tag = doc["slots"][idx]["mapping_id"], doc["slots"][idx]["mcc_tag"]
    doc["slots"][idx] = default_slot(mapping_id, TEST_SLOT, mcc_tag)
    conn = mapping_db.open_existing(mapping_db.db_path_for(json_path))
    try:
        mapping_db.replace_slots(conn, doc, "2026-10-10T00:00:00")
        data = mapping_db.serialize(doc)
        json_path.write_bytes(data)
        mapping_db.mark_json_synced(conn, mapping_db.sha256(data))
    finally:
        conn.close()


def link_work(dest, name="work"):
    """A directory junction (no admin rights needed on Windows) to the repository's folder `name`."""
    target, link = REPO_ROOT / name, dest / name
    if sys.platform == "win32":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return "junction"
    raise SystemExit(f"could not link {target} into the test folder; run the test on Windows with junctions")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", type=Path, required=True)
    args = ap.parse_args()
    dest = args.dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty")
    real = REPO_ROOT / "mappings"
    real_hash = hashlib.sha256((real / "manual_mappings.json").read_bytes()).hexdigest()
    (dest / "mappings").mkdir(parents=True, exist_ok=True)
    for name in SHELL_TEST_FILES:
        src = real / name
        if src.exists():
            shutil.copy2(src, dest / "mappings" / name)
    if (REPO_ROOT / "config" / "audio_export.json").exists():
        (dest / "config").mkdir(exist_ok=True)
        shutil.copy2(REPO_ROOT / "config" / "audio_export.json", dest / "config" / "audio_export.json")
    if (REPO_ROOT / "config" / "interference").is_dir():  # the one-off interference defaults (text only)
        shutil.copytree(REPO_ROOT / "config" / "interference", dest / "config" / "interference", dirs_exist_ok=True)
    link = link_work(dest)
    # The pinned bank copies the MCC audio is decoded from on demand (read only; nothing writes there).
    if (REPO_ROOT / "reference-audio").is_dir():
        link_work(dest, "reference-audio")
    reset_test_line(dest / "mappings" / "manual_mappings.json")
    print(json.dumps({
        "root": dest.as_posix(),
        "work_link": link,
        "test_slot": TEST_SLOT,
        "real_mappings_sha256": real_hash,
        "real_mappings": real.as_posix(),
    }))


if __name__ == "__main__":
    main()
