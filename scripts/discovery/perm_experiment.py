"""Permutation experiment (owner, 2026-10-16): can MCC play more takes of a sound than Spain's bank provides?

Builds ONE controlled test, offline, from the pinned copies in reference-audio/stage1/: Grunt `death_violent`
(Spain 2 takes, English 4, the map's tag 4 permutations) gets the takes listed in --takes, in order. The first
takes take the places of Spain's own (same names, so every slot ID stays); the rest are inserted right after
them, and the Spanish sound index (.lst.bin) gets the new count, every later range shifted. Bank and index are
written as one unit. Take sources:
  spain:K       Spain's own take K of this sound (unchanged)
  en:K          the English bank's take K of this sound
  slot:<id>     any recording of the Spanish bank by slot ID, as the Studio shows it (slot:es:alliancebroken%2002#5)

Presets: `--preset english` (default; exp_grunt_death_violent_4: Spain 1-2 + English 3-4) and `--preset johnson`
(exp_grunt_death_violent_johnson: four Johnson lines Halo/a30 never plays, so any Johnson voice at a Grunt's
death comes from the experiment; takes 1-2 in Spain's places, 3-4 added).

Output: work/m6/<name>/ (git-ignored), shaped like an M6 build of kind "experiment", so the existing installer
(scripts/build/m6_install.py) and the Studio's Build & Test page install and restore BOTH files together, with
the usual pins, verified backups, snapshot and automatic restore on failure:
  sounds_dialogs_spanish.fsb, sounds_dialogs_spanish.lst.bin   the candidates
  build_manifest.json, validation_report.json                  what the installer reads
  test_report.md, install_rollback.md                          the takes and files
  listen/*.wav                                                 the takes + reference Grunt deaths
Not made from the mappings, never touches mappings/, never installs anything. docs/permutation-experiment.md.

Example:
    python scripts/discovery/perm_experiment.py --preset johnson
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.celt011 import profile_violations, split_fmod_frames  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_writer import build, decompose  # noqa: E402
from common.mcc_lst import build_lst, check_ranges, parse_lst  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_all, decode_pcm  # noqa: E402

STAGE1 = REPO_ROOT / "reference-audio" / "stage1"
GRUNT = "sound\\dialog\\grunt\\conditional\\combat2\\involuntary\\"
TAG = GRUNT + "death_violent"
PRESETS = {
    "english": ("exp_grunt_death_violent_4", ["spain:1", "spain:2", "en:3", "en:4"]),
    # Johnson (sargeant) lines for Flood, Sentinels and a betrayal: none of them is triggered in Halo (a30).
    "johnson": ("exp_grunt_death_violent_johnson", ["slot:es:killedenemyfloodcombatcm%2003#5",
                                                    "slot:es:killedenemysentinel%2002#5",
                                                    "slot:es:alliancebroken%2002#5",
                                                    "slot:es:killedenemyfloodcarriercm%2002#5"]),
}
REFERENCES = ("death_quiet", "death_instant", "death_flying")  # other Grunt deaths, to tell them apart by ear
INSTALL = {"bank": "halo1/sound/pc/sounds_dialogs_spanish.fsb",
           "lst": "halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def pins():
    return {k: v["sha256"] for k, v in
            json.loads((REPO_ROOT / "work/mcc/build.json").read_text(encoding="utf-8"))["files"].items()}


def slot_ids(names):
    """es:<name>#<occurrence> in bank order (the approved slot ID rule)."""
    seen, out = {}, []
    for n in names:
        out.append(f"es:{n.decode()}#{seen.get(n, 0)}")
        seen[n] = seen.get(n, 0) + 1
    return out


def resolve(spec, es, en, es_rec, en_rec):
    """A take source -> (bank "es"/"en", sample index, label)."""
    kind, _, arg = spec.partition(":")
    if kind in ("spain", "en"):
        f, c = (es_rec if kind == "spain" else en_rec)[TAG]
        k = int(arg)
        if not 1 <= k <= c:
            raise SystemExit(f"{spec}: this sound has {c} takes in that bank")
        return ("es" if kind == "spain" else "en"), f + k - 1, f"{kind} take {k}"
    if kind == "slot":
        ids = slot_ids(es["names"])
        raw = unquote(arg)  # the catalog writes %XX for characters such as spaces (docs/campaign-catalog.md §3)
        if raw not in ids:
            raise SystemExit(f"{spec}: no such Spanish slot")
        return "es", ids.index(raw), raw
    raise SystemExit(f"unknown take source {spec!r} (spain:K, en:K, slot:<id>)")


def make(es, en, es_lst, en_lst, takes):
    """-> (bank bytes, lst bytes, info). Pure: the same inputs always give the same bytes."""
    es_rec = {t: (f, c) for t, f, c in es_lst["records"]}
    en_rec = {t: (f, c) for t, f, c in en_lst["records"]}
    ef, ec = es_rec[TAG]
    if len(takes) < ec:
        raise SystemExit(f"give at least {ec} takes (Spain's places are never left empty)")
    banks = {"es": es, "en": en}
    sources = [resolve(t, es, en, es_rec, en_rec) for t in takes]
    new = dict(es, samples=list(es["samples"]), names=list(es["names"]))
    for p, (bank, i, _label) in enumerate(sources):
        s = banks[bank]["samples"][i]
        if s["head_bits"] != es["samples"][ef]["head_bits"] or s["channels"] != 1:
            raise SystemExit(f"take {p + 1}: frequency/channel bits differ from Spain's takes")
        if p < ec:
            new["samples"][ef + p] = s  # Spain's place: the name (and so the slot ID) stays
        else:
            spec = takes[p]  # English takes keep the names of the first build (exp_grunt_death_violent_4)
            name = (f"EXTRA deathviolent en{int(spec[3:]):02d}" if spec.startswith("en:")
                    else f"EXTRA deathviolent take{p + 1:02d}").encode()
            if name in es["names"]:
                raise SystemExit(f"{name!r} is already in the bank")
            new["samples"].insert(ef + p, s)
            new["names"].insert(ef + p, name)
    n_new = len(takes) - ec
    at = ef + ec
    records = [(t, f, c + n_new) if t == TAG else (t, f + (n_new if f >= at else 0), c)
               for t, f, c in es_lst["records"]]
    info = {"spanish": {"first": ef, "count": ec}, "english": dict(zip(("first", "count"), en_rec[TAG])),
            "takes": [{"source": spec, "bank": b, "index": i, "label": lab} for spec, (b, i, lab) in zip(takes, sources)],
            "inserted_at": at, "new_count": len(takes), "added": n_new}
    return build(new), build_lst(es_lst["version"], records), info


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
    ap.add_argument("--preset", choices=sorted(PRESETS), default="english")
    ap.add_argument("--takes", nargs="+", help="override the preset's takes (spain:K, en:K, slot:<id>)")
    ap.add_argument("--name", help="build folder under work/m6/ (default: the preset's)")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    args = ap.parse_args()
    name, takes = PRESETS[args.preset]
    name, takes = args.name or name, args.takes or takes
    out = REPO_ROOT / "work" / "m6" / name
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
    banks = {"es": es, "en": en}
    print(f"building {name}: {TAG} <- {', '.join(takes)}")
    bank, lst, info = make(es, en, es_lst, en_lst, takes)
    bank2, lst2, _ = make(decompose(raw["es"]), en, parse_lst(raw["es_lst"]), en_lst, takes)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sounds_dialogs_spanish.fsb").write_bytes(bank)
    (out / "sounds_dialogs_spanish.lst.bin").write_bytes(lst)

    cm, cl = decompose(bank), parse_lst(lst)
    ef, ec, at, n_new = info["spanish"]["first"], info["spanish"]["count"], info["inserted_at"], info["added"]
    srcs = [(t["bank"], t["index"]) for t in info["takes"]]
    replaced = {ef + k for k in range(ec) if srcs[k] != ("es", ef + k)}  # Spain's places given another recording
    rng = check_ranges(cl["records"], len(cm["samples"]))
    old_rec, new_rec = es_lst["records"], cl["records"]
    shifted = lambda i: i + (n_new if i >= at else 0)  # noqa: E731 - original sample index -> candidate index
    print(f"decoding all {len(cm['samples'])} subsongs of the candidate (the original's are cached)…")
    dec_o = original_decodes(exe, paths["es"], len(es["samples"]), p["spanish.fsb"])
    dec_c = decode_all(exe, out / "sounds_dialogs_spanish.fsb", len(cm["samples"]))
    dec_src = [dec_o[i] if b == "es" else hashlib.sha256(decode_pcm(exe, paths["en"], i + 1) or b"").hexdigest()
               for b, i in srcs]
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
        "bank_sample_count": len(cm["samples"]) == len(es["samples"]) + n_new,
        "header_tail_unchanged": cm["header_tail"] == es["header_tail"] and cm["mode"] == es["mode"],
        "every_take_is_its_source_sample": all(cm["samples"][ef + k] == banks[b]["samples"][i]
                                               for k, (b, i) in enumerate(srcs)),
        "takes_mcc_celt_profile": all(not profile_violations(split_fmod_frames(banks[b]["samples"][i]["stream"]))
                                      for b, i in srcs),
        "every_other_original_sample_byte_identical": all(cm["samples"][shifted(i)] == s for i, s in enumerate(es["samples"])
                                                          if i not in replaced),
        "slot_ids_unchanged": [x for x in slot_ids(cm["names"]) if not x.startswith("es:EXTRA ")] == slot_ids(es["names"]),
        "vgm_all_subsongs_decode": None not in dec_c and len(dec_c) == len(cm["samples"]),
        "vgm_every_other_original_decodes_identically": all(dec_c[shifted(i)] == h for i, h in enumerate(dec_o)
                                                            if i not in replaced),
        "vgm_every_take_decodes_as_its_source": all(dec_c[ef + k] == dec_src[k] for k in range(len(srcs))),
    }
    ok = all(checks.values())

    listen = out / "listen"
    listen.mkdir(exist_ok=True)
    for old in listen.glob("*.wav"):
        old.unlink()
    take_rows = []
    for k, t in enumerate(info["takes"]):
        extra = k >= ec
        label = f"take{k + 1}_{'EXTRA_' if extra else ''}{t['label'].replace('es:', '').replace(' ', '_').replace('#', '_')}"
        label = "".join(ch for ch in label if ch.isalnum() or ch in "_-")
        (listen / f"{label}.wav").write_bytes(decode_pcm(exe, out / "sounds_dialogs_spanish.fsb", ef + k + 1))
        take_rows.append({"take": k + 1, "file": f"listen/{label}.wav", "source": t["source"], "label": t["label"],
                          "seconds": round(cm["samples"][ef + k]["sample_count"] / 44100, 2),
                          "candidate_index": ef + k, "extra": extra})
    refs = []
    rec = {t: (f, c) for t, f, c in old_rec}
    for r in REFERENCES:
        f, c = rec[GRUNT + r]
        for k in range(c):
            lab = f"ref_{r}_{k + 1}_spain"
            (listen / f"{lab}.wav").write_bytes(decode_pcm(exe, paths["es"], f + k + 1))
            refs.append({"file": f"listen/{lab}.wav", "sound": r,
                         "seconds": round(es["samples"][f + k]["sample_count"] / 44100, 2)})

    files = []
    for key, data, orig in (("bank", bank, p["spanish.fsb"]), ("lst", lst, p["spanish.lst"])):
        files.append({"install_rel": INSTALL[key], "original_sha256": orig,
                      "candidate": f"work/m6/{name}/{Path(INSTALL[key]).name}", "candidate_sha256": sha(data),
                      "size": len(data), "growth_bytes": len(data) - len(raw["es" if key == "bank" else "es_lst"])})
    experiment = {"question": "Does MCC play more takes of a sound than Spain's bank originally provides?",
                  "tag": TAG, **info, "takes": take_rows, "references": refs,
                  "map_tag": {"evidence": "parsed read-only from halo1/maps/a30.map (and the HEK source tag)",
                              "actual_permutation_count": 4, "permutation_names": ["1", "2", "3", "4"],
                              "skip_fraction": [0.0, 0.0, 1.0, 0.0]},
                  "dialogue_fields_using_this_sound": ["death violent", "death agonizing"],
                  "evidence_dialogue": "HCEEK grunt.dialogue: the 166 sound references in c20's field order"}
    manifest = {"schema": "m6-build-manifest/1", "name": name, "kind": "experiment", "levels": ["grunt"],
                "built_at": dt.datetime.now().isoformat(timespec="seconds"),
                "inputs": {"bank_copy_sha256": p["spanish.fsb"], "lst_sha256": p["spanish.lst"],
                           "english_bank_sha256": p["english.fsb"], "english_lst_sha256": p["english.lst"]},
                "install_files": files,
                "not_written": ["Data/ui/localization/SU_Halo1.bin", "Data/ui/localization/SP_Halo1.bin"],
                "counts": {"extra_takes": n_new, "takes": len(takes)}, "slots": [], "subtitles": {"enabled": False},
                "experiment": experiment}
    report = {"schema": "m6-validation-report/2", "name": name, "kind": "experiment", "ok": ok, "checks": checks,
              "candidate_sha256": files[0]["candidate_sha256"],
              "candidates": {f["install_rel"]: f["candidate_sha256"] for f in files}}
    (out / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    sheet = test_sheet(manifest, report)
    (out / "test_report.md").write_text(sheet, encoding="utf-8")
    (out / "install_rollback.md").write_text(sheet, encoding="utf-8")
    bad = [k for k, v in checks.items() if not v]
    print(f"{'PASS' if ok else 'FAILED'}: {len(checks) - len(bad)}/{len(checks)} checks; "
          f"bank {files[0]['candidate_sha256'][:16]}… ({files[0]['growth_bytes']:+,} B), "
          f"lst {files[1]['candidate_sha256'][:16]}…")
    for k in bad:
        print("  FAILED:", k)
    for t in take_rows:
        print(f"  take {t['take']}: {t['label']} ({t['seconds']} s){' EXTRA' if t['extra'] else ''} -> {t['file']}")
    print(f"wrote work/m6/{name}/")
    return 0 if ok else 1


def test_sheet(m, report):
    e = m["experiment"]
    L = [f"# Permutation experiment `{m['name']}` — {'PASS' if report['ok'] else 'FAILED'} offline", "",
         f"Question: {e['question']}", "",
         f"Grunt `death_violent` gets {e['new_count']} takes (Spain has {e['spanish']['count']}); the bank and the sound "
         "index are installed and restored together.", "",
         "| Take | Recording | Seconds | | File |", "|---|---|---|---|---|"]
    L += [f"| {t['take']} | `{t['label']}` | {t['seconds']} | {'**added**' if t['extra'] else 'in Spain' + chr(39) + 's place'} "
          f"| `{t['file']}` |" for t in e["takes"]]
    L += ["", "Other Grunt deaths (Spain, unchanged): " + ", ".join(f"`{r['file']}`" for r in e["references"]), "",
          "## Files", ""]
    L += [f"- `{f['install_rel']}`: original `{f['original_sha256'][:16]}…` → candidate `{f['candidate_sha256'][:16]}…`"
          for f in m["install_files"]]
    L += ["", "Procedure and interpretation: docs/permutation-experiment.md."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
