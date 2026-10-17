"""Permutation experiment (owner, 2026-10-16): can MCC play more takes of a sound than Spain's bank provides?

Builds ONE controlled test, offline, from the pinned copies in reference-audio/stage1/:
  Grunt `death_violent`: Spain's 2 recordings stay first and untouched; the English bank's #3 and #4 (the same
  tag's permutations "3" and "4", long and audibly English) are inserted right after them. The Spanish bank and
  the Spanish sound index (.lst.bin: count 2 -> 4, every later range + 2) are written as one unit.

Output: work/m6/exp_grunt_death_violent_4/ (git-ignored), shaped like an M6 build of kind "experiment", so the
existing installer (scripts/build/m6_install.py) and the Studio's Build & Test page install and restore BOTH
files together, with the usual pins, verified backups, snapshot and automatic restore on failure:
  sounds_dialogs_spanish.fsb, sounds_dialogs_spanish.lst.bin   the candidates
  build_manifest.json, validation_report.json                  what the installer reads
  test_report.md, install_rollback.md                          the in-game procedure
  listen/*.wav                                                 the 4 death_violent takes + reference Grunt deaths
Not made from the mappings, never touches mappings/, never installs anything.

Example:
    python scripts/discovery/perm_experiment.py
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.celt011 import profile_violations, split_fmod_frames  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_writer import build, decompose  # noqa: E402
from common.mcc_lst import build_lst, check_ranges, parse_lst  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_all, decode_pcm  # noqa: E402

NAME = "exp_grunt_death_violent_4"
STAGE1 = REPO_ROOT / "reference-audio" / "stage1"
OUT = REPO_ROOT / "work" / "m6" / NAME
GRUNT = "sound\\dialog\\grunt\\conditional\\combat2\\involuntary\\"
TAG = GRUNT + "death_violent"
ADD = (3, 4)  # English permutations (1-based) inserted after Spain's
REFERENCES = ("death_quiet", "death_instant", "death_flying")  # other Grunt deaths, to tell them apart by ear
INSTALL = {"bank": "halo1/sound/pc/sounds_dialogs_spanish.fsb",
           "lst": "halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def pins():
    return {k: v["sha256"] for k, v in
            json.loads((REPO_ROOT / "work/mcc/build.json").read_text(encoding="utf-8"))["files"].items()}


def make(es, en, es_lst, en_lst):
    """-> (bank bytes, lst bytes, info). Pure: the same inputs always give the same bytes."""
    es_rec = {t: (f, c) for t, f, c in es_lst["records"]}
    en_rec = {t: (f, c) for t, f, c in en_lst["records"]}
    (ef, ec), (nf, nc) = es_rec[TAG], en_rec[TAG]
    add = [nf + k - 1 for k in ADD]
    if max(ADD) > nc:
        raise SystemExit(f"English has only {nc} takes of {TAG}")
    at = ef + ec
    new = dict(es, samples=list(es["samples"]), names=list(es["names"]))
    for j, i in enumerate(add):
        s = en["samples"][i]
        if s["head_bits"] != es["samples"][ef]["head_bits"] or s["channels"] != 1:
            raise SystemExit("an English take's frequency/channel bits differ from Spain's")
        name = f"EXTRA deathviolent en{ADD[j]:02d}".encode()
        if name in es["names"]:
            raise SystemExit(f"{name!r} is already in the bank")
        new["samples"].insert(at + j, s)
        new["names"].insert(at + j, name)
    records = [(t, f, c + len(add)) if t == TAG else (t, f + (len(add) if f >= at else 0), c)
               for t, f, c in es_lst["records"]]
    info = {"spanish": {"first": ef, "count": ec}, "english": {"first": nf, "count": nc}, "english_inserted": add,
            "inserted_at": at, "new_count": ec + len(add)}
    return build(new), build_lst(es_lst["version"], records), info


def slot_ids(names):
    seen, out = {}, []
    for n in names:
        out.append(f"es:{n.decode()}#{seen.get(n, 0)}")
        seen[n] = seen.get(n, 0) + 1
    return out


def original_decodes(exe, bank_path, count, pin):
    """The M6 cache of every original subsong's decode hash (same key as scripts/build/m6_build.py)."""
    cache = REPO_ROOT / "work/m6/_cache/original_decode.json"
    key = f"{pin}:{sha(Path(exe).read_bytes())}"
    if cache.is_file():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("key") == key and len(c.get("hashes", [])) == count:
            return c["hashes"]
    return decode_all(exe, bank_path, count)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    args = ap.parse_args()
    exe = args.vgmstream_cli
    p = pins()
    paths = {"es": STAGE1 / "fsb/sounds_dialogs_spanish.fsb", "en": STAGE1 / "fsb/sounds_dialogs.fsb",
             "es_lst": STAGE1 / "lst/sounds_dialogs_spanish.lst.bin", "en_lst": STAGE1 / "lst/sounds_dialogs.lst.bin"}
    raw = {k: v.read_bytes() for k, v in paths.items()}
    want = {"es": p["spanish.fsb"], "en": p["english.fsb"], "es_lst": p["spanish.lst"], "en_lst": p["english.lst"]}
    for k, h in want.items():
        if sha(raw[k]) != h:
            raise SystemExit(f"{paths[k]} does not match its pin; refusing to build from it")
    es, en = decompose(raw["es"]), decompose(raw["en"])
    es_lst, en_lst = parse_lst(raw["es_lst"]), parse_lst(raw["en_lst"])
    print(f"building {NAME}: {TAG}, Spain's takes + English #{ADD[0]} and #{ADD[1]}…")
    bank, lst, info = make(es, en, es_lst, en_lst)
    bank2, lst2, _ = make(decompose(raw["es"]), en, parse_lst(raw["es_lst"]), en_lst)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sounds_dialogs_spanish.fsb").write_bytes(bank)
    (OUT / "sounds_dialogs_spanish.lst.bin").write_bytes(lst)

    cm, cl = decompose(bank), parse_lst(lst)
    ef, ec, at, add = info["spanish"]["first"], info["spanish"]["count"], info["inserted_at"], info["english_inserted"]
    n_new = len(add)
    rng = check_ranges(cl["records"], len(cm["samples"]))
    old_rec, new_rec = es_lst["records"], cl["records"]
    shifted = lambda i: i + (n_new if i >= at else 0)  # noqa: E731 - original sample index -> candidate index
    print(f"decoding all {len(cm['samples'])} subsongs of the candidate (the original's are cached)…")
    dec_o = original_decodes(exe, paths["es"], len(es["samples"]), p["spanish.fsb"])
    dec_c = decode_all(exe, OUT / "sounds_dialogs_spanish.fsb", len(cm["samples"]))
    dec_en = {i: hashlib.sha256(decode_pcm(exe, paths["en"], i + 1) or b"").hexdigest() for i in add}
    checks = {
        "inputs_match_pins": True,  # refused above otherwise
        "deterministic": bank == bank2 and lst == lst2,
        "bank_round_trip": build(cm) == bank,
        "lst_writer_reproduces_the_shipped_index": build_lst(es_lst["version"], es_lst["records"]) == raw["es_lst"],
        "lst_round_trip": build_lst(cl["version"], cl["records"]) == lst,
        "lst_same_tags_same_order": [r[0] for r in new_rec] == [r[0] for r in old_rec],
        "lst_contiguous_from_zero": rng["contiguous_from_zero"],
        "lst_total_matches_bank": rng["total_matches_bank"],
        "lst_only_target_count_and_later_starts_change": all(
            (n == (t, f, c + n_new) if t == TAG else n == (t, shifted(f), c)) for (t, f, c), n in zip(old_rec, new_rec)),
        "bank_sample_count_plus_2": len(cm["samples"]) == len(es["samples"]) + n_new,
        "header_tail_unchanged": cm["header_tail"] == es["header_tail"] and cm["mode"] == es["mode"],
        "spain_takes_unchanged_and_first": all(cm["samples"][ef + k] == es["samples"][ef + k] for k in range(ec)),
        "inserted_takes_are_the_english_samples": all(cm["samples"][at + j] == en["samples"][i] for j, i in enumerate(add)),
        "inserted_takes_mcc_celt_profile": all(not profile_violations(split_fmod_frames(en["samples"][i]["stream"]))
                                               for i in add),
        "every_original_sample_kept_byte_identical": all(cm["samples"][shifted(i)] == s for i, s in enumerate(es["samples"])),
        "other_slot_ids_unchanged": [x for x in slot_ids(cm["names"]) if not x.startswith("es:EXTRA ")]
        == slot_ids(es["names"]),
        "vgm_all_subsongs_decode": None not in dec_c and len(dec_c) == len(cm["samples"]),
        "vgm_every_original_subsong_decodes_identically": all(dec_c[shifted(i)] == h for i, h in enumerate(dec_o)),
        "vgm_inserted_decode_equals_english": all(dec_c[at + j] == dec_en[i] for j, i in enumerate(add)),
    }
    ok = all(checks.values())

    # Listening references: the four takes the game may now pick, and the other Grunt deaths (Spain).
    listen = OUT / "listen"
    listen.mkdir(exist_ok=True)
    take_names = [f"violent_{k + 1}_spain_{(es['names'][ef + k]).decode().replace(' ', '_')}" for k in range(ec)] + \
                 [f"violent_{ec + j + 1}_EXTRA_english_take{ADD[j]}" for j in range(n_new)]
    takes = []
    for k, label in enumerate(take_names):
        wav = decode_pcm(exe, OUT / "sounds_dialogs_spanish.fsb", ef + k + 1)
        (listen / f"{label}.wav").write_bytes(wav)
        takes.append({"file": f"listen/{label}.wav", "seconds": round(cm["samples"][ef + k]["sample_count"] / 44100, 2),
                      "candidate_index": ef + k, "extra": k >= ec})
    refs = []
    for r in REFERENCES:
        f, c = dict((t, (f, c)) for t, f, c in old_rec)[GRUNT + r]
        for k in range(c):
            wav = decode_pcm(exe, paths["es"], f + k + 1)
            label = f"ref_{r}_{k + 1}_spain"
            (listen / f"{label}.wav").write_bytes(wav)
            refs.append({"file": f"listen/{label}.wav", "sound": r,
                         "seconds": round(es["samples"][f + k]["sample_count"] / 44100, 2)})

    files = []
    for key, data, orig in (("bank", bank, p["spanish.fsb"]), ("lst", lst, p["spanish.lst"])):
        name = Path(INSTALL[key]).name
        files.append({"install_rel": INSTALL[key], "original_sha256": orig,
                      "candidate": f"work/m6/{NAME}/{name}", "candidate_sha256": sha(data), "size": len(data),
                      "growth_bytes": len(data) - len(raw["es" if key == "bank" else "es_lst"])})
    experiment = {"question": "Does MCC play more takes of a sound than Spain's bank originally provides?",
                  "tag": TAG, **info, "takes": takes, "references": refs,
                  "map_tag": {"evidence": "parsed read-only from halo1/maps/a30.map (and the HEK source tag)",
                              "actual_permutation_count": 4, "permutation_names": ["1", "2", "3", "4"],
                              "skip_fraction": [0.0, 0.0, 1.0, 0.0]},
                  "dialogue_fields_using_this_sound": ["death violent", "death agonizing"],
                  "evidence_dialogue": "HCEEK grunt.dialogue: the 166 sound references in c20's field order"}
    manifest = {"schema": "m6-build-manifest/1", "name": NAME, "kind": "experiment", "levels": ["grunt"],
                "built_at": dt.datetime.now().isoformat(timespec="seconds"),
                "inputs": {"bank_copy_sha256": p["spanish.fsb"], "lst_sha256": p["spanish.lst"],
                           "english_bank_sha256": p["english.fsb"], "english_lst_sha256": p["english.lst"]},
                "install_files": files,
                "not_written": ["Data/ui/localization/SU_Halo1.bin", "Data/ui/localization/SP_Halo1.bin"],
                "counts": {"extra_takes": n_new}, "slots": [], "subtitles": {"enabled": False},
                "experiment": experiment}
    report = {"schema": "m6-validation-report/2", "name": NAME, "kind": "experiment", "ok": ok, "checks": checks,
              "candidate_sha256": files[0]["candidate_sha256"],
              "candidates": {f["install_rel"]: f["candidate_sha256"] for f in files}}
    (OUT / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUT / "test_report.md").write_text(test_sheet(manifest, report), encoding="utf-8")
    (OUT / "install_rollback.md").write_text(test_sheet(manifest, report), encoding="utf-8")
    bad = [k for k, v in checks.items() if not v]
    print(f"{'PASS' if ok else 'FAILED'}: {len(checks) - len(bad)}/{len(checks)} checks; "
          f"bank {files[0]['candidate_sha256'][:16]}… ({files[0]['growth_bytes']:+,} B), "
          f"lst {files[1]['candidate_sha256'][:16]}…")
    for k in bad:
        print("  FAILED:", k)
    print(f"wrote work/m6/{NAME}/ (2 candidates, manifest, report, test sheet, {len(takes) + len(refs)} WAVs in listen/)")
    return 0 if ok else 1


def test_sheet(m, report):
    e = m["experiment"]
    t = e["takes"]
    L = [f"# Permutation experiment `{m['name']}` — {'PASS' if report['ok'] else 'FAILED'} offline", "",
         f"Question: {e['question']}", "",
         f"Grunt `death_violent`: Spain's {e['spanish']['count']} takes stay first; English takes "
         f"#{', #'.join(str(k) for k in ADD)} are added (count {e['spanish']['count']} → {e['new_count']}). "
         "The bank and the sound index are installed and restored together.", "",
         "## Takes (listen first: `listen/`)", "",
         "| # | File | Seconds | |", "|---|---|---|---|"]
    L += [f"| {k + 1} | `{x['file']}` | {x['seconds']} | {'**EXTRA (English)**' if x['extra'] else 'Spain'} |"
          for k, x in enumerate(t)]
    L += ["", "Other Grunt deaths (Spain, unchanged; so you can tell them apart): "
          + ", ".join(f"`{r['file']}`" for r in e["references"]), "",
          "## Files", ""]
    L += [f"- `{f['install_rel']}`: original `{f['original_sha256'][:16]}…` → candidate `{f['candidate_sha256'][:16]}…`"
          for f in m["install_files"]]
    L += ["", "Procedure and interpretation: docs/permutation-experiment.md."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
