"""Read-only parser for MCC Halo CE `sounds_dialogs*.lst.bin` sound indexes.

Layout (verified 2026-10-08 against both shipped EN/ES copies, see
docs/mcc-a10-catalog.md §2):

    u32 version (1), u32 record_count,
    record_count x { u32 name_len, name_len bytes (ASCII tag path, NUL-terminated),
                     u32 first_sample_index, u32 sample_count }

`first_sample_index`/`sample_count` address the paired language's FSB5
bank. The interpretation rests on three checks that held for both
languages: the file is consumed exactly, the ranges are contiguous from
0, and they sum to the bank's sample count. It is therefore recorded as
`derived:lst_record_layout`, a cross-check of the bank's own name table,
which remains the identity source.
"""
import struct


def parse_lst(data):
    """-> {"version", "records": [(tag, first_sample_index, sample_count)]}. Raises ValueError on bad layout."""
    if len(data) < 8:
        raise ValueError("lst.bin too short")
    version, n = struct.unpack_from("<II", data, 0)
    off, recs = 8, []
    for i in range(n):
        if off + 4 > len(data):
            raise ValueError(f"record {i}: truncated length")
        (ln,) = struct.unpack_from("<I", data, off)
        off += 4
        if off + ln + 8 > len(data):
            raise ValueError(f"record {i}: truncated name/range")
        raw = data[off:off + ln]
        if not raw.endswith(b"\0"):
            raise ValueError(f"record {i}: name not NUL-terminated")
        off += ln
        start, count = struct.unpack_from("<II", data, off)
        off += 8
        recs.append((raw[:-1].decode("ascii"), start, count))
    if off != len(data):
        raise ValueError(f"{len(data) - off} trailing bytes after {n} records")
    return {"version": version, "records": recs}


def check_ranges(records, num_samples):
    """Layout checks used as evidence for the (first, count) reading. -> dict of booleans/numbers."""
    contiguous = bool(records) and records[0][1] == 0 and all(
        records[i][1] == records[i - 1][1] + records[i - 1][2] for i in range(1, len(records)))
    total = sum(c for _, _, c in records)
    return {"contiguous_from_zero": contiguous, "sample_total": total, "bank_samples": num_samples,
            "total_matches_bank": total == num_samples}
