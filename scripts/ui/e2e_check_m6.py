"""Checks that the decisions the Studio wrote are read by the M6 audio planner as the owner intends.

    python scripts/ui/e2e_check_m6.py --root <disposable root from e2e_fixture.py> --slot es:A10_010_cryotech#0

It runs the same planner the batch builder uses (common/m6_build.plan_audio) on the given decisions, with
no build and no file written. The end-to-end test calls it after the browser steps, so a decision made in
the Studio is shown to be exactly what a build would replace.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ui"))

from common import mapping_store  # noqa: E402
from common.m6_build import plan_audio  # noqa: E402
from m4_app import M4App  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--slot", required=True)
    ap.add_argument("--level", default="a10")
    args = ap.parse_args()

    root = args.root.resolve()
    app = M4App(root, run_validator=False)
    doc, _ = mapping_store.load(root / "mappings" / "manual_mappings.json")
    local, _ = mapping_store.load_or_default(root / "mappings" / "manual_mappings.local.json", {})
    plan = plan_audio(doc, [args.level], slot_index=app.slot_index, ce_lines=app.ce_lines,
                      ce_idx=app.ce_idx, mcc_idx=app.mcc_idx, local=local)
    entry = next(e for e in plan["entries"] if e["slot_id"] == args.slot)
    checks = {
        "planned_as_replacement": entry["action"] == "replace",
        "uses_the_chosen_recording": entry["edit"] is not None or entry.get("ce_line_ref") is not None,
        "no_conflicts": not [c for c in plan["conflicts"] if c.get("slot_id") == args.slot],
    }
    print(json.dumps({"action": entry["action"], "reason": entry["reason"], "edit": entry["edit"],
                      "checks": checks, "ok": all(checks.values())}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
