"""Prompt 49 offline proofs (docs/mute-language-permutations.md). Offline only: reads the pinned copies in
reference-audio/stage1/, writes candidates and reports to work/p49/. Never installs, never touches mappings/.

  mute          Silence one Spanish sample (default a10_350_captkeyes, index 30, the E1 experiment line) with
                common/audio_pipeline.silent_stream, exactly as an approved "Mute / No replacement" is built by M6.
                Checks: same file size and layout, only that sample's bytes differ, every subsong decodes, the
                target decodes to digital silence of the original length, its packets equal MCC's own silence
                packet, and a census of MCC's silence packets / fully silent samples.
  permutations  Grunt `death_violent` (Spain 2 samples, English 4, the shared tag 4 permutations): a candidate
                Spanish bank + Spanish .lst.bin with the English samples 3 and 4 inserted after Spain's two
                (count 2 -> 4; every later range shifts by 2). Checks: the lst parses, its ranges are contiguous
                and cover the bank, every other tag still resolves to byte-identical samples, every subsong
                decodes, slot IDs of every other sample are unchanged. Whether MCC then plays 4 variations is
                NOT shown by any of this (in-game test only).

Example:
    python scripts/discovery/p49_offline_proofs.py mute
    python scripts/discovery/p49_offline_proofs.py permutations
"""
import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.audio_pipeline import silent_stream  # noqa: E402
from common.celt011 import Celt011, split_fmod_frames  # noqa: E402
from common.celt_header import frame_flags  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_writer import build, decompose, diff_ranges, sample_spans  # noqa: E402
from common.m6_build import assemble, multi_structural_checks  # noqa: E402
from common.mcc_lst import check_ranges, parse_lst  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_all, decode_pcm, meta, meta_value  # noqa: E402

STAGE1 = REPO_ROOT / "reference-audio" / "stage1"
OUT = REPO_ROOT / "work" / "p49"
PINS = {"spanish.fsb": "ed0ff3ec", "english.fsb": "8d072c1b", "spanish.lst": "d5324861"}  # prefixes, build.json has the full pins
DEATH_VIOLENT = r"sound\dialog\grunt\conditional\combat2\involuntary\death_violent"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def pinned(name, data):
    full = json.loads((REPO_ROOT / "work/mcc/build.json").read_text(encoding="utf-8"))["files"][name]["sha256"]
    if sha(data) != full:
        raise SystemExit(f"{name} copy does not match its pin {full[:16]}…")
    return full


def original_decodes(exe, bank_path, count, pin):
    """The M6 cache of every original subsong's decode hash (same key as scripts/build/m6_build.py)."""
    from common.audio_pipeline import sha256_file
    cache = REPO_ROOT / "work/m6/_cache/original_decode.json"
    key = f"{pin}:{sha256_file(exe)}"
    if cache.is_file():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("key") == key and len(c.get("hashes", [])) == count:
            return c["hashes"]
    return decode_all(exe, bank_path, count)


def slot_ids(names):
    """es:<name>#<occurrence> in bank order (the approved slot ID rule)."""
    seen, out = Counter(), []
    for n in names:
        out.append(f"es:{n.decode()}#{seen[n]}")
        seen[n] += 1
    return out


def write_lst(version, records):
    out = bytearray(struct.pack("<II", version, len(records)))
    for tag, first, count in records:
        raw = tag.encode("ascii") + b"\0"
        out += struct.pack("<I", len(raw)) + raw + struct.pack("<II", first, count)
    return bytes(out)


def silence_census(model):
    packets, full = Counter(), []
    for i, s in enumerate(model["samples"]):
        ps = split_fmod_frames(s["stream"])
        flags = [frame_flags(p)["silence"] for p in ps]
        packets.update(p for p, f in zip(ps, flags) if f)
        if all(flags):
            full.append({"index": i, "name": model["names"][i].decode(), "sample_count": s["sample_count"],
                         "channels": s["channels"]})
    return packets, full


def cmd_mute(args):
    bank_path = STAGE1 / "fsb" / "sounds_dialogs_spanish.fsb"
    original = bank_path.read_bytes()
    pin = pinned("spanish.fsb", original)
    model = decompose(original)
    k = args.index
    target = model["samples"][k]
    if target["channels"] != 1:
        raise SystemExit("mono samples only (stereo replacement is deferred)")
    print(f"muting #{k} {model['names'][k].decode()} ({target['sample_count']} samples)…")
    celt = Celt011()
    try:
        res = silent_stream(celt, target["sample_count"])
        again = silent_stream(celt, target["sample_count"])
    finally:
        celt.close()
    repl = {k: (res["stream"], res["sample_count"])}
    cand = assemble(original, repl)
    OUT.mkdir(parents=True, exist_ok=True)
    cand_path = OUT / "mute_sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(cand)
    print("census of MCC's own silence frames…")
    sil_packets, fully_silent = silence_census(model)
    ours = split_fmod_frames(res["stream"])
    exe = args.vgmstream_cli
    count = len(model["samples"])
    print(f"decoding all {count} subsongs of the original (cached) and the candidate…")
    full_o = original_decodes(exe, bank_path, count, pin)
    full_c = decode_all(exe, cand_path, count)
    pcm = decode_pcm(exe, cand_path, k + 1)
    pcm = pcm[pcm.index(b"data") + 8:]
    m = meta(exe, cand_path, k + 1)
    checks = {
        **multi_structural_checks(original, cand, repl),
        "deterministic": again["stream"] == res["stream"] and assemble(original, repl) == cand,
        "same_file_size": len(cand) == len(original),
        "same_sample_spans": sample_spans(cand) == sample_spans(original),
        "only_target_bytes_differ": all(sample_spans(original)[k][0] <= a and b <= sample_spans(original)[k][1]
                                        for a, b in diff_ranges(original, cand, limit=1000)),
        "sample_count_equals_original": res["sample_count"] == target["sample_count"],
        "stream_length_equals_original": len(res["stream"]) == len(target["stream"]),
        "every_packet_is_a_silence_frame": all(frame_flags(p)["silence"] for p in ours),
        "packets_equal_mcc_mono_silence_packet": set(ours) == {p for p in sil_packets if len(p) == 370}
        and len({p for p in sil_packets if len(p) == 370}) == 1,
        "vgm_all_subsongs_decode": None not in full_c and len(full_c) == count,
        "vgm_only_target_differs": [i for i, (a, b) in enumerate(zip(full_o, full_c)) if a != b] == [k],
        "vgm_target_is_digital_silence": not pcm.strip(b"\0"),
        "vgm_target_sample_count": (meta_value(m, "stream total samples") or "").split(" ")[0] == str(res["sample_count"]),
        "vgm_encoding_custom_celt": meta_value(m, "encoding") == "Custom CELT",
    }
    report = {"schema": "p49-mute-proof/1", "target": {"index": k, "subsong": k + 1, "name": model["names"][k].decode(),
                                                      "sample_count": target["sample_count"],
                                                      "seconds": round(target["sample_count"] / 44100, 3)},
              "original_sha256": pin, "candidate": cand_path.relative_to(REPO_ROOT).as_posix(),
              "candidate_sha256": sha(cand), "checks": checks, "ok": all(checks.values()),
              "mcc_silence": {"distinct_silence_packets": len(sil_packets),
                              "per_packet": [{"bytes": len(p), "frames": n, "sha256": sha(p)} for p, n in sil_packets.items()],
                              "silence_frames": sum(sil_packets.values()),
                              "silence_packet_sha256": [sha(p) for p in sil_packets],
                              "fully_silent_samples": fully_silent},
              "note": "offline only; nothing installed. In-game behaviour of a muted line is unverified."}
    (OUT / "mute_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bad = [c for c, v in checks.items() if not v]
    print(f"{'PASS' if not bad else 'FAILED'}: {len(checks) - len(bad)}/{len(checks)} checks; candidate {sha(cand)[:16]}…")
    for c in bad:
        print("  FAILED:", c)
    print(f"MCC silence packets: {len(sil_packets)} distinct, {sum(sil_packets.values())} frames; fully silent samples: "
          + ", ".join(f"#{x['index']} {x['name']}" for x in fully_silent))
    return 0 if not bad else 1


def cmd_permutations(args):
    es_bank, en_bank = (STAGE1 / "fsb" / "sounds_dialogs_spanish.fsb").read_bytes(), (STAGE1 / "fsb" / "sounds_dialogs.fsb").read_bytes()
    es_lst_b = (STAGE1 / "lst" / "sounds_dialogs_spanish.lst.bin").read_bytes()
    en_lst_b = (STAGE1 / "lst" / "sounds_dialogs.lst.bin").read_bytes()
    pins = {"spanish.fsb": pinned("spanish.fsb", es_bank), "english.fsb": pinned("english.fsb", en_bank),
            "spanish.lst": pinned("spanish.lst", es_lst_b), "english.lst": pinned("english.lst", en_lst_b)}
    es, en = decompose(es_bank), decompose(en_bank)
    del en_bank
    es_lst, en_lst = parse_lst(es_lst_b), parse_lst(en_lst_b)
    es_rec = {t: (f, c) for t, f, c in es_lst["records"]}
    en_rec = {t: (f, c) for t, f, c in en_lst["records"]}
    tag = args.tag
    (ef, ec), (nf, nc) = es_rec[tag], en_rec[tag]
    add = list(range(nf + ec, nf + nc))  # the English permutations Spain does not have (by position)
    print(f"{tag}: Spain {ec} sample(s) at {ef}, English {nc} at {nf}; inserting English #{add} after Spain's")
    new = dict(es)
    new["samples"], new["names"] = list(es["samples"]), list(es["names"])
    at = ef + ec
    used = set(es["names"])
    for j, i in enumerate(add):
        s = dict(en["samples"][i])
        if s["head_bits"] != es["samples"][ef]["head_bits"] or s["channels"] != 1:
            raise SystemExit("the English sample's frequency/channel bits differ from Spain's")
        name = f"p49 {tag.rsplit(chr(92), 1)[1]} en{i - nf + 1:02d}".encode()
        if name in used:
            raise SystemExit(f"name {name!r} already in the bank")
        new["samples"].insert(at + j, s)
        new["names"].insert(at + j, name)
    cand = build(new)
    records = []
    for t, f, c in es_lst["records"]:
        if t == tag:
            records.append((t, f, c + len(add)))
        else:
            records.append((t, f + (len(add) if f >= at else 0), c))
    lst = write_lst(es_lst["version"], records)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "perm_sounds_dialogs_spanish.fsb").write_bytes(cand)
    (OUT / "perm_sounds_dialogs_spanish.lst.bin").write_bytes(lst)
    cm, cl = decompose(cand), parse_lst(lst)
    rng = check_ranges(cl["records"], len(cm["samples"]))

    def resolved(model, recs):
        return {t: [(model["samples"][i]["stream"], model["samples"][i]["sample_count"], model["samples"][i]["chunks"],
                     model["samples"][i]["head_bits"]) for i in range(f, f + c)] for t, f, c in recs}
    before, after = resolved(es, es_lst["records"]), resolved(cm, cl["records"])
    old_ids, new_ids = slot_ids(es["names"]), slot_ids(cm["names"])
    exe = args.vgmstream_cli
    count = len(cm["samples"])
    print(f"decoding all {count} subsongs of the candidate…")
    dec = decode_all(exe, OUT / "perm_sounds_dialogs_spanish.fsb", count)
    checks = {
        "round_trip": build(cm) == cand,
        "sample_count_plus_inserted": len(cm["samples"]) == len(es["samples"]) + len(add),
        "lst_parses_and_same_tags": [r[0] for r in cl["records"]] == [r[0] for r in es_lst["records"]],
        "lst_contiguous_from_zero": rng["contiguous_from_zero"], "lst_total_matches_bank": rng["total_matches_bank"],
        "target_tag_count": dict((t, c) for t, _, c in cl["records"])[tag] == ec + len(add),
        "target_keeps_spain_samples_first": after[tag][:ec] == before[tag],
        "target_new_samples_are_english": after[tag][ec:] == [(en["samples"][i]["stream"], en["samples"][i]["sample_count"],
                                                               en["samples"][i]["chunks"], en["samples"][i]["head_bits"])
                                                              for i in add],
        "every_other_tag_resolves_to_identical_samples": all(after[t] == before[t] for t in before if t != tag),
        "other_slot_ids_unchanged": [x for x in new_ids if not x.startswith("es:p49 ")] == old_ids,
        "vgm_all_subsongs_decode": None not in dec and len(dec) == count,
        "inputs_still_match_pins": all(sha((STAGE1 / d / f).read_bytes()) == pins[k] for k, d, f in (
            ("spanish.fsb", "fsb", "sounds_dialogs_spanish.fsb"), ("english.fsb", "fsb", "sounds_dialogs.fsb"),
            ("spanish.lst", "lst", "sounds_dialogs_spanish.lst.bin"), ("english.lst", "lst", "sounds_dialogs.lst.bin"))),
    }
    report = {"schema": "p49-permutation-proof/1", "tag": tag, "spanish": {"first": ef, "count": ec},
              "english": {"first": nf, "count": nc}, "inserted_english_indices": add, "inserted_at": at,
              "pins": pins, "candidates": {"bank": sha(cand), "lst": sha(lst)},
              "lst_ranges": rng, "checks": checks, "ok": all(checks.values()),
              "note": "offline structural proof only. MCC selecting the extra samples is unverified; the shipped "
                      "installers write the bank only, never the .lst.bin."}
    (OUT / "perm_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bad = [c for c, v in checks.items() if not v]
    print(f"{'PASS' if not bad else 'FAILED'}: {len(checks) - len(bad)}/{len(checks)} checks; bank {sha(cand)[:16]}…, "
          f"lst {sha(lst)[:16]}…")
    for c in bad:
        print("  FAILED:", c)
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mute")
    m.add_argument("--index", type=int, default=30, help="Spanish bank sample index (default 30, a10_350_captkeyes)")
    p = sub.add_parser("permutations")
    p.add_argument("--tag", default=DEATH_VIOLENT)
    args = ap.parse_args()
    return cmd_mute(args) if args.cmd == "mute" else cmd_permutations(args)


if __name__ == "__main__":
    raise SystemExit(main())
