"""Inspect COPIES of MCC Halo 1 string tables (EN vs SP) and report structure.

Read-only on the inputs; writes a stats-only JSON report under work/mcc/.
Stats only: key i <-> string i is verified (docs/subtitle-research.md B.4), but
this report never emits text and never links a subtitle to an audio tag.

Example:
    python scripts/discovery/inspect_mcc_subtitles.py \
        --en work/mcc/loc/EN_Halo1.bin --sp work/mcc/loc/SP_Halo1.bin \
        --lst reference-audio/stage1/lst/sounds_dialogs.lst.bin
"""
import argparse
import collections
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.asset_metadata import fnv1_32  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.mcc_loc import parse_mcc_loc, split_speaker  # noqa: E402


def read_lst_names(path):
    data = Path(path).read_bytes()
    names, o = [], 0
    while o + 12 <= len(data):
        _flag, _count, n = struct.unpack_from("<iiI", data, o)
        o += 12
        names.append(data[o:o + n].decode("ascii", errors="replace").rstrip("\0"))
        o += n
    return names


def fnv1a_32(b):
    h = 2166136261
    for c in b:
        h = ((h ^ c) * 16777619) & 0xFFFFFFFF
    return h


def summarize(t):
    speakers = collections.Counter()
    for s in t["strings"]:
        sp = split_speaker(s)
        if sp:
            speakers[sp[1]] += 1
    return {
        "name": t["name"], "key_count": t["key_count"], "field_0x70": t["field_0x70"],
        "payload_size_field": t["payload_size_field"], "pool_offset": t["pool_offset"],
        "pool_bytes": t["pool_bytes"], "string_segments": len(t["strings"]),
        "empty_segments": sum(1 for s in t["strings"] if not s),
        "segments_with_speaker_label": sum(speakers.values()),
        "speaker_labels": dict(speakers.most_common()),
        "first_key": f"0x{t['keys'][0]:08x}", "last_key": f"0x{t['keys'][-1]:08x}",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--en", required=True, type=Path)
    ap.add_argument("--sp", required=True, type=Path)
    ap.add_argument("--lst", type=Path, help="sounds_dialogs.lst.bin copy, for the tag-name hash test")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "work" / "mcc" / "loc" / "report.json")
    args = ap.parse_args()

    en = parse_mcc_loc(args.en.read_bytes())
    sp = parse_mcc_loc(args.sp.read_bytes())
    ek, sk = set(en["keys"]), set(sp["keys"])
    report = {
        "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.en, args.sp)},
        "en": summarize(en), "sp": summarize(sp),
        "keys": {"shared": len(ek & sk), "en_only": len(ek - sk), "sp_only": len(sk - ek)},
        "key_to_string": "verified: string i belongs to key i (docs/subtitle-research.md B.4)",
    }
    if args.lst:
        names = read_lst_names(args.lst)
        variants = set()
        for n in names:
            base = n.split("\\")[-1]
            for v in (n, base, n.replace("\\", "/"), n + ".sound"):
                for w in (v, v.lower(), v.upper()):
                    variants.add(w)
        funcs = {"crc32": lambda b: zlib.crc32(b) & 0xFFFFFFFF, "fnv1": lambda b: fnv1_32(b.decode()),
                 "fnv1a": fnv1a_32}
        report["tag_name_hash_test"] = {
            "lst_names": len(names), "variants": len(variants),
            "hits": {f: sum(1 for v in variants if fn(v.encode("ascii")) in ek) for f, fn in funcs.items()},
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("en", "sp")}, indent=2))
    for side in ("en", "sp"):
        s = report[side]
        print(side, {k: s[k] for k in ("key_count", "string_segments", "empty_segments",
                                       "segments_with_speaker_label", "first_key", "last_key")})


if __name__ == "__main__":
    main()
