"""Offline validation of a one-sample replacement in an MCC Spanish bank (E1b, E3, batch builds).

Generic: any target index, any replacement length. Pure checks on bytes plus optional vgmstream
decodes. Returns named booleans; callers require all of them.
"""
from .fsb5_lib import parse_header
from .fsb5_writer import ALIGN, build, decompose, sample_spans
from .vgm import decode_all, meta, meta_value


def structural_checks(original, candidate, index, stream, sample_count):
    """Checks that `candidate` == `original` with only sample `index` replaced by (stream, sample_count)."""
    mo, mc = decompose(original), decompose(candidate)
    so, sc = sample_spans(original), sample_spans(candidate)
    ho, hc = parse_header(original), parse_header(candidate)
    growth = (sc[index][1] - sc[index][0]) - (so[index][1] - so[index][0])
    data_start = so[0][0]
    t = mc["samples"][index]
    loop_ok = all(p == (0).to_bytes(4, "little") + (sample_count - 2).to_bytes(4, "little")
                  for ty, p in t["chunks"] if ty == 3)
    return {
        "same_sample_count_and_names": len(mc["samples"]) == len(mo["samples"]) and mc["names"] == mo["names"],
        "header_tail_identical": mc["header_tail"] == mo["header_tail"],
        "sample_headers_size_unchanged": hc["sample_headers_size"] == ho["sample_headers_size"],
        "target_stream_is_expected": t["stream"] == stream,
        "target_sample_count": t["sample_count"] == sample_count,
        "target_loop_0_n_minus_2": loop_ok,
        "target_head_bits_and_chunk_types_unchanged": t["head_bits"] == mo["samples"][index]["head_bits"]
        and [ty for ty, _ in t["chunks"]] == [ty for ty, _ in mo["samples"][index]["chunks"]],
        "other_samples_identical": all(a == b for k, (a, b) in enumerate(zip(mo["samples"], mc["samples"]))
                                       if k != index),
        "payloads_by_index_identical_except_target": all(
            original[a:b] == candidate[c:d] for k, ((a, b), (c, d)) in enumerate(zip(so, sc)) if k != index),
        "earlier_offsets_unchanged": sc[:index + 1] == so[:index] + [(so[index][0], sc[index][1])],
        "later_offsets_shift_by_growth": all(c[0] - o[0] == growth for o, c in zip(so[index + 1:], sc[index + 1:])),
        "all_offsets_32_aligned": all((a - data_start) % ALIGN == 0 for a, _ in sc),
        "size_equation": len(candidate) == hc["base_header_size"] + hc["sample_headers_size"]
        + hc["name_table_size"] + hc["data_size"],
        "data_size_delta_equals_growth": hc["data_size"] - ho["data_size"] == growth
        and len(candidate) - len(original) == growth,
        "round_trip": build(mc) == candidate,
    }


def decode_checks(exe, original_path, candidate_path, index, sample_count, count):
    """vgmstream: every subsong decodes in both banks, only the target differs, target length correct."""
    full_o = decode_all(exe, original_path, count)
    full_c = decode_all(exe, candidate_path, count)
    m = meta(exe, candidate_path, index + 1)
    return {
        "vgm_all_subsongs_decode": None not in full_o and None not in full_c and len(full_c) == count,
        "vgm_only_target_differs": [k + 1 for k, (a, b) in enumerate(zip(full_o, full_c)) if a != b] == [index + 1],
        "vgm_target_sample_count": (meta_value(m, "stream total samples") or "").split(" ")[0] == str(sample_count),
        "vgm_target_encoding_custom_celt": meta_value(m, "encoding") == "Custom CELT",
    }, m
