"""Times the Studio's API operations in-process, on a disposable copy of the mapping data.

    python scripts/ui/profile_api.py                          # makes its own copy (scripts/ui/e2e_fixture.py)
    python scripts/ui/profile_api.py --iterations 30 --label after
    python scripts/ui/profile_api.py --cprofile save           # where the time goes in one operation

It calls M4App directly (no HTTP), so the numbers are Python + SQLite + file I/O; the browser tests measure
the rest. Read operations run on the real catalogs; write operations (save, approve, rework) only ever
touch the copy. Results: work/reports/perf/api_<label>.json (median and p95 per operation, cold = first call).
"""
import argparse
import cProfile
import json
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "ui"))

from m4_app import M4App  # noqa: E402

SLOTS = ["es:A10_010_cryotech#0", "es:A10_020_cryotech#0", "es:A10_350_captkeyes#0", "es:A30_090_cortana#0",
         "es:A10_140_cryotech#0"]
WRITE_SLOT = "es:A10_020_cryotech#0"


def fixture():
    dest = Path(tempfile.mkdtemp(prefix="studio-perf-")) / "root"
    out = subprocess.run([sys.executable, str(REPO / "scripts/ui/e2e_fixture.py"), "--dest", str(dest)],
                         capture_output=True, text=True, check=True).stdout
    return Path(json.loads(out.strip().splitlines()[-1])["root"])


def measure(fn, iterations):
    times = []
    for _ in range(iterations):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    cold, warm = times[0], sorted(times[1:]) or times
    p95 = warm[min(len(warm) - 1, int(round(0.95 * (len(warm) - 1))))]
    return {"cold_ms": round(cold, 1), "median_ms": round(statistics.median(warm), 1), "p95_ms": round(p95, 1),
            "n": len(times)}


def operations(app):
    """name -> zero-argument callable. Writes alternate a note so every save really changes something."""
    state = {"n": 0}

    def save_note():
        d = app.slot(WRITE_SLOT)
        state["n"] += 1
        return app.save({"slot_id": WRITE_SLOT, "loaded_sha256": d["sha256"]["mappings"],
                         "local_sha256": d["sha256"]["local"], "notes": f"perf {state['n']}"})

    def rework_and_approve():
        d = app.slot(WRITE_SLOT)
        if d["mapping"]["audio"]["status"] == "approved":
            return app.save({"slot_id": WRITE_SLOT, "loaded_sha256": d["sha256"]["mappings"],
                             "local_sha256": d["sha256"]["local"], "actions": [{"action": "needs_rework", "field": "audio"}]})
        return app.save({"slot_id": WRITE_SLOT, "loaded_sha256": d["sha256"]["mappings"],
                         "local_sha256": d["sha256"]["local"], "actions": [{"action": "approve", "field": "audio"}]})

    i = {"k": 0}

    def next_slot():
        i["k"] = (i["k"] + 1) % len(SLOTS)
        return app.slot(SLOTS[i["k"]])

    return {
        "state": app.state,
        "slots a10 (open level)": lambda: app.slots("a10"),
        "slots a50 (switch level)": lambda: app.slots("a50"),
        "slots a10 status=undecided": lambda: app.slots("a10", status="undecided"),
        "slots all q='jefe maestro'": lambda: app.slots("all", q="jefe maestro"),
        "slot detail (select line)": next_slot,
        "ce all (no query)": lambda: app.ce("all", limit=100),
        "ce all q='cortana'": lambda: app.ce("all", q="cortana", limit=100),
        "ce all q='despues' (accent-folded)": lambda: app.ce("all", q="despues", limit=100),
        "ce all q='\"jefe maestro\"' (phrase)": lambda: app.ce("all", q='"jefe maestro"', limit=100),
        "ce all q='00460' (partial id)": lambda: app.ce("all", q="00460", limit=100),
        "ce M01 subs=missing hide_used": lambda: app.ce("M01", subs="missing", hide_used=True, keep_slot=WRITE_SLOT),
        "save draft (notes)": save_note,
        "approve / needs rework (audio)": rework_and_approve,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, help="a disposable root (default: make one)")
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--label", default="run")
    ap.add_argument("--cprofile", help="profile one operation (substring of its name) and print the top calls")
    ap.add_argument("--only", help="run only operations whose name contains this")
    args = ap.parse_args()
    root = args.root or fixture()
    if root.resolve() == REPO.resolve():
        raise SystemExit("refusing to profile on the real repository (writes would hit your mappings)")

    t = time.perf_counter()
    app = M4App(root, run_validator=True)
    startup = round((time.perf_counter() - t) * 1000, 1)
    app.validate()  # the server runs this once at start-up (in a thread), before the first request
    ops = operations(app)
    if args.cprofile:
        name = next(n for n in ops if args.cprofile in n)
        ops[name]()  # warm
        prof = cProfile.Profile()
        prof.enable()
        for _ in range(5):
            ops[name]()
        prof.disable()
        print(f"== {name} (5 calls)")
        pstats.Stats(prof).sort_stats("cumulative").print_stats(25)
        return 0

    results = {"root": str(root), "startup_ms": startup, "operations": {}}
    print(f"startup (M4App init: catalogs, indexes, search text) {startup} ms")
    for name, fn in ops.items():
        if args.only and args.only not in name:
            continue
        r = measure(fn, args.iterations)
        results["operations"][name] = r
        print(f"{name:42} cold {r['cold_ms']:8.1f}  median {r['median_ms']:8.1f}  p95 {r['p95_ms']:8.1f} ms")
    out = REPO / "work" / "reports" / "perf" / f"api_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"-> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
