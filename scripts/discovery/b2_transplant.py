"""B2 offline transplant: put the MCC English CELT recording of a line into its Spanish slot.

General form of E1 (same length) that also handles different lengths (E1b): the target sample's
stream, sample count and LOOP chunk change; every later sample's data offset shifts; every other
byte of every other sample is unchanged. MCC retail content only.

Inputs (read-only): pinned copies in reference-audio/stage1/ (verified against work/mcc/build.json).
Outputs (git-ignored) in work/b2/<exp>/: sounds_dialogs_spanish.fsb (candidate), <exp>_report.json,
<exp>_summary.md. Never installs anything; installs go through b2_bank_install.py with owner approval.

Example:
    python scripts/discovery/b2_transplant.py --exp e1b --name A10_140_cryotech
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_lib import FsbBank  # noqa: E402
from common.fsb5_writer import (ALIGN, build, decompose, replace_sample,  # noqa: E402
                                replacement_compatibility, sample_spans)
from common.vgm import DEFAULT_VGMSTREAM, decode_all, decode_hash, meta, meta_value  # noqa: E402

REF = REPO_ROOT / "reference-audio" / "stage1"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def unique_index(names, name):
    hits = [i for i, n in enumerate(names) if n.lower() == name.lower()]
    if len(hits) != 1:
        raise SystemExit(f"{name!r} matches {len(hits)} samples (need exactly 1)")
    return hits[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp", required=True, help="experiment id, e.g. e1b (output folder work/b2/<exp>/)")
    ap.add_argument("--name", required=True, help="sample name (case-insensitive, unique in both banks)")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    args = ap.parse_args()
    exe = args.vgmstream_cli
    out = REPO_ROOT / "work" / "b2" / args.exp

    pins = {k: v["sha256"] for k, v in json.loads((REPO_ROOT / "work" / "mcc" / "build.json")
                                                  .read_text(encoding="utf-8"))["files"].items()}
    es_path, en_path = REF / "fsb" / "sounds_dialogs_spanish.fsb", REF / "fsb" / "sounds_dialogs.fsb"
    lst_path = REF / "lst" / "sounds_dialogs_spanish.lst.bin"
    es, en = es_path.read_bytes(), en_path.read_bytes()
    for key, blob in (("spanish.fsb", es), ("english.fsb", en), ("spanish.lst", lst_path.read_bytes())):
        if sha256(blob) != pins[key]:
            raise SystemExit(f"{key}: copy does not match its pin; refusing to use it")

    m_es, m_en = decompose(es), decompose(en)
    names_es = [n.decode("utf-8") for n in m_es["names"]]
    names_en = [n.decode("utf-8") for n in m_en["names"]]
    i = unique_index(names_es, args.name)
    j = unique_index(names_en, args.name)
    dst, src = m_es["samples"][i], m_en["samples"][j]
    compat = replacement_compatibility(dst, src)
    if not all(compat.values()):
        raise SystemExit(f"not compatible: {compat}")

    candidate = build(replace_sample(m_es, i, src["stream"], src["sample_count"]))
    again = build(replace_sample(decompose(es), i, src["stream"], src["sample_count"]))
    out.mkdir(parents=True, exist_ok=True)
    cand_path = out / "sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(candidate)

    so, sc = sample_spans(es), sample_spans(candidate)
    old_span, new_span = so[i][1] - so[i][0], sc[i][1] - sc[i][0]
    growth = new_span - old_span
    shifts = {c[0] - o[0] for o, c in zip(so[i + 1:], sc[i + 1:])}
    m_c = decompose(candidate)
    ob, cb = FsbBank(es_path), FsbBank(cand_path)
    data_start = so[0][0]
    hdr_o, hdr_c = ob.header, cb.header
    loop = struct.unpack("<II", next(p for t, p in m_c["samples"][i]["chunks"] if t == 3))

    full_o = decode_all(exe, es_path, len(so))
    full_c = decode_all(exe, cand_path, len(sc))
    en_target = decode_hash(exe, en_path, j + 1)
    meta_c = meta(exe, cand_path, i + 1)

    others_identical = all(
        a == b for k, (a, b) in enumerate(zip(m_es["samples"], m_c["samples"])) if k != i)
    checks = {
        "copies_match_pins": True,
        "compatible": all(compat.values()),
        "target_stream_equals_english": m_c["samples"][i]["stream"] == src["stream"],
        "target_sample_count": m_c["samples"][i]["sample_count"] == src["sample_count"],
        "target_loop_0_n_minus_2": loop == (0, src["sample_count"] - 2),
        "target_head_bits_unchanged": m_c["samples"][i]["head_bits"] == dst["head_bits"],
        "other_5695_samples_identical": others_identical and len(m_c["samples"]) == len(m_es["samples"]),
        "names_and_order_identical": m_c["names"] == m_es["names"],
        "header_tail_identical": m_c["header_tail"] == m_es["header_tail"],
        "sample_headers_size_unchanged": hdr_c["sample_headers_size"] == hdr_o["sample_headers_size"],
        "name_table_bytes_identical": candidate[data_start - hdr_o["name_table_size"]:data_start]
        == es[data_start - hdr_o["name_table_size"]:data_start],
        "earlier_offsets_unchanged": sc[:i] == so[:i] and sc[i][0] == so[i][0],
        "later_offsets_shift_uniformly": len(shifts) <= 1 and (not shifts or shifts == {growth}),
        "all_offsets_32_aligned": all((a - data_start) % ALIGN == 0 for a, _ in sc),
        "data_size_and_file_size_grow_by_growth": hdr_c["data_size"] - hdr_o["data_size"] == growth
        and len(candidate) - len(es) == growth,
        "size_equation": len(candidate) == hdr_c["base_header_size"] + hdr_c["sample_headers_size"]
        + hdr_c["name_table_size"] + hdr_c["data_size"],
        "payloads_by_index_identical_except_target": all(
            es[a:b] == candidate[c:d] for k, ((a, b), (c, d)) in enumerate(zip(so, sc)) if k != i),
        "reparse_metadata_except_target": [(s["frequency"], s["channels"], s["sample_count"], s["chunks"])
                                           for k, s in enumerate(ob.samples) if k != i]
        == [(s["frequency"], s["channels"], s["sample_count"], s["chunks"]) for k, s in enumerate(cb.samples)
            if k != i],
        "round_trip": build(m_c) == candidate,
        "deterministic": again == candidate,
        "lst_untouched": sha256(lst_path.read_bytes()) == pins["spanish.lst"],
        "vgm_all_subsongs_decode": None not in full_o and None not in full_c and len(full_c) == len(full_o),
        "vgm_only_target_differs": [k + 1 for k, (a, b) in enumerate(zip(full_o, full_c)) if a != b] == [i + 1],
        "vgm_target_equals_english": full_c[i] == en_target,
        "vgm_target_duration": (meta_value(meta_c, "stream total samples") or "").split(" ")[0]
        == str(src["sample_count"]),
    }
    report = {
        "schema": "b2-transplant/1", "experiment": args.exp, "name": args.name,
        "spanish": {"index": i, "subsong": i + 1, "name": names_es[i], "sample_count": dst["sample_count"],
                    "seconds": round(dst["sample_count"] / 44100, 3), "stream_bytes": len(dst["stream"]),
                    "span_bytes": old_span},
        "english": {"index": j, "subsong": j + 1, "name": names_en[j], "sample_count": src["sample_count"],
                    "seconds": round(src["sample_count"] / 44100, 3), "stream_bytes": len(src["stream"]),
                    "stream_sha256": sha256(src["stream"])},
        "loop": list(loop), "growth_bytes": growth, "later_samples_shifted": len(so) - i - 1,
        "compatibility": compat,
        "hashes": {"original_bank": pins["spanish.fsb"], "candidate": sha256(candidate),
                   "spanish_lst": pins["spanish.lst"]},
        "candidate": cand_path.relative_to(REPO_ROOT).as_posix(), "size": len(candidate),
        "vgm_target_meta": meta_c, "checks": checks, "ok": all(checks.values()),
        "note": "offline only; MCC retail content only; nothing installed",
    }
    (out / f"{args.exp}_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [f"# B2 {args.exp}: English {names_en[j]} into Spanish #{i} {names_es[i]}", "",
             f"Result: **{'PASS' if report['ok'] else 'FAIL'}**. Candidate `{report['hashes']['candidate']}`, "
             f"{len(candidate):,} B ({growth:+,} B). Target {report['spanish']['seconds']} s -> "
             f"{report['english']['seconds']} s; LOOP {loop}; {report['later_samples_shifted']} later samples "
             f"shifted.", ""] + [f"- `{k}`: {v}" for k, v in checks.items()]
    (out / f"{args.exp}_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[2])
    for k, v in checks.items():
        if not v:
            print("FAILED:", k)
    print(f"checks {sum(bool(v) for v in checks.values())}/{len(checks)}; wrote {out.relative_to(REPO_ROOT)}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
