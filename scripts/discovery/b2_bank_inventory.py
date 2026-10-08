"""B2 research R7/R8: read-only inventory of MCC Halo CE FMOD runtime and FSB banks.

Reads (never writes) the install:
  - FileVersion of halo1/fmodex64.dll and fmod_event_net64.dll (PE version resource);
  - for every halo1/sound/pc/*.fsb: only the first 64 KiB + sample headers + name table
    region needed for header statistics (FSB5 version, mode/codec, sample count, frequencies,
    channels, extra-chunk types, data-offset alignment, data size);
  - the Spanish dialogue bank pinned copy in reference-audio/stage1/ for per-sample detail.

Writes work/mcc/reports/b2_bank_inventory.json (statistics only, no audio).

Example:
    python scripts/discovery/b2_bank_inventory.py
"""
import collections
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.ce_assets import read_pe_file_version  # noqa: E402
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from common.fsb5_lib import FREQS, MODES, bits, parse_header  # noqa: E402

CHUNK_NAMES = {1: "CHANNELS", 2: "FREQUENCY", 3: "LOOP", 6: "XMASEEK", 7: "DSPCOEFF", 10: "XWMADATA",
               11: "VORBISDATA"}


def read_head(path):
    """Header + sample headers + name table bytes only (data section is not read)."""
    with open(path, "rb") as f:
        first = f.read(64)
        if first[:4] != b"FSB5":
            return None, None
        h = parse_header(first)
        need = h["base_header_size"] + h["sample_headers_size"] + h["name_table_size"]
        f.seek(0)
        return h, f.read(need)


def sample_stats(h, data):
    """Per-sample bitfields (as fsb5_lib, verified in Stage 1): next_chunk:1, freq:4, stereo:1, offset:28 (x16), samples:30."""
    off = h["base_header_size"]
    end = off + h["sample_headers_size"]
    rows = []
    for _ in range(h["num_samples"]):
        (v,) = struct.unpack_from("<Q", data, off)
        off += 8
        row = {"freq": FREQS.get(bits(v, 1, 4)), "channels": 2 if bits(v, 5, 1) else 1,
               "data_offset": bits(v, 6, 28) * 16, "samples": bits(v, 34, 30), "chunks": []}
        more = bits(v, 0, 1)
        while more and off < end:
            (c,) = struct.unpack_from("<I", data, off)
            off += 4
            more, size, ctype = bits(c, 0, 1), bits(c, 1, 24), bits(c, 25, 7)
            payload = data[off:off + size]
            off += size
            row["chunks"].append(ctype)
            if ctype == 1:
                row["channels"] = payload[0]
            elif ctype == 2:
                row["freq"] = struct.unpack_from("<I", payload)[0]
        rows.append(row)
    return rows


def summarize(path, h, data, detail=False):
    rows = sample_stats(h, data)
    offs = [r["data_offset"] for r in rows]
    out = {
        "file": path.name, "size": path.stat().st_size, "fsb_version": h["version"],
        "mode": h["mode"], "codec": MODES.get(h["mode"], h["mode"]), "num_samples": h["num_samples"],
        "has_name_table": h["name_table_size"] > 0, "data_size": h["data_size"],
        "header_bytes": h["base_header_size"] + h["sample_headers_size"] + h["name_table_size"],
        "freqs": dict(collections.Counter(r["freq"] for r in rows)),
        "channels": dict(collections.Counter(r["channels"] for r in rows)),
        "chunk_types": {CHUNK_NAMES.get(k, str(k)): v for k, v in
                        collections.Counter(c for r in rows for c in r["chunks"]).items()},
        "offsets_ascending": all(b > a for a, b in zip(offs, offs[1:])),
        "offset_alignment_32": all(o % 32 == 0 for o in offs),
        "offset_alignment_16": all(o % 16 == 0 for o in offs),
    }
    if detail:
        gaps = [b - a for a, b in zip(offs, offs[1:])]
        out["min_gap"], out["max_gap"] = (min(gaps), max(gaps)) if gaps else (None, None)
        out["first_offset"] = offs[0] if offs else None
        out["loop_chunk_samples"] = sum(1 for r in rows if 3 in r["chunks"])
        out["samples_total"] = sum(r["samples"] for r in rows)
        out["fixed_header_tail_hex"] = data[4 + 24:h["base_header_size"]].hex()
    return out


def main():
    env, _ = load_env()
    mcc = require_path(env, "HALO_MCC_FOLDER", kind="dir")
    report = {"schema": "b2-bank-inventory/1", "runtime": {}, "banks": []}
    for dll in ("fmodex64.dll", "fmod_event_net64.dll"):
        p = mcc / "halo1" / dll
        report["runtime"][dll] = {"present": p.is_file(), "file_version": read_pe_file_version(p) if p.is_file()
                                  else None, "size": p.stat().st_size if p.is_file() else None}
    pc = mcc / "halo1" / "sound" / "pc"
    for p in sorted(pc.glob("*.fsb")):
        h, data = read_head(p)
        if h is None:
            report["banks"].append({"file": p.name, "fsb5": False})
            continue
        report["banks"].append(summarize(p, h, data, detail=p.name.startswith("sounds_dialogs")))
    report["codecs_in_install"] = dict(collections.Counter(b.get("codec") for b in report["banks"]))
    out = REPO_ROOT / "work" / "mcc" / "reports" / "b2_bank_inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["runtime"], indent=2))
    print(json.dumps(report["codecs_in_install"]))
    for b in report["banks"]:
        print(b.get("file"), b.get("codec"), b.get("num_samples"), b.get("freqs"), b.get("channels"),
              b.get("chunk_types"), b.get("size"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
