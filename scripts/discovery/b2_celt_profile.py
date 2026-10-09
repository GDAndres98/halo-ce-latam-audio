"""B2 E2 diagnosis: CELT frame-flag profile of MCC dialogue banks vs candidate banks (read-only).

Parses the leading flags (silence, post-filter, transient, intra) of every CELT packet with
common/celt_header.py. Used to show that every original MCC dialogue packet is intra-coded with no
transient and no post-filter, and that the E2 candidate (which crashed MCC) was not.

Inputs: pinned copies in reference-audio/stage1/fsb/ and any candidate banks in work/b2/<exp>/.
Output: work/b2/celt_profile.json (statistics only).

Example:
    python scripts/discovery/b2_celt_profile.py --exp e1 e2 e2b
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.celt011 import split_fmod_frames  # noqa: E402
from common.celt_header import frame_flags  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_writer import decompose  # noqa: E402

KEYS = ("silence", "postfilter", "transient", "intra")


def bank_profile(path, only=None):
    m = decompose(Path(path).read_bytes())
    out = {}
    for ch in (1, 2):
        c = Counter()
        for i, s in enumerate(m["samples"]):
            if s["channels"] != ch or (only is not None and i not in only):
                continue
            for p in split_fmod_frames(s["stream"]):
                f = frame_flags(p)
                c["frames"] += 1
                for k in KEYS:
                    c[k] += f[k]
                c["non_silent_not_intra"] += int(not f["silence"] and not f["intra"])
        if c:
            out[f"{ch}ch"] = dict(c)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp", nargs="*", default=[], help="candidate experiments; only their target sample is profiled")
    args = ap.parse_args()
    ref = REPO_ROOT / "reference-audio" / "stage1" / "fsb"
    report = {"schema": "b2-celt-profile/1",
              "mcc_spanish": bank_profile(ref / "sounds_dialogs_spanish.fsb"),
              "mcc_english": bank_profile(ref / "sounds_dialogs.fsb"), "candidates": {}}
    for exp in args.exp:
        base = REPO_ROOT / "work" / "b2" / exp
        rep = json.loads((base / f"{exp}_report.json").read_text(encoding="utf-8"))
        idx = rep["target"]["index"] if "target" in rep else rep["spanish"]["index"]
        report["candidates"][exp] = {"target_index": idx,
                                     "profile": bank_profile(base / "sounds_dialogs_spanish.fsb", only={idx})}
    out = REPO_ROOT / "work" / "b2" / "celt_profile.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "schema"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
