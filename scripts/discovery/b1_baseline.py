"""B1 PoC steps 0-1 helper (docs/subtitle-research.md B.12). Read-only.

Step 0 (default):
  - reads the MCC Steam build id from the appmanifest (read-only);
  - hashes the INSTALLED SU_Halo1.bin / SP_Halo1.bin (read-only) and compares them with the
    work/mcc/loc/copies/ copies and the pinned hashes;
  - confirms each baseline tag is in sounds_dialogs.lst.bin and looks its CRC key up
    independently in each table (exactly one hit per table; never reuses an index across tables);
  - writes work/mcc/reports/b1_step0_preflight.json (no game text) and
    work/mcc/reports/b1_baseline_sheet.md (SU/SP text + observation form; git-ignored).

Step 1 support:
  --match "TEXT"   finds the closest baseline line and compares the text with its SU and SP entries.

Never writes any game file, never launches the game, never patches a table.

Examples:
    python scripts/discovery/b1_baseline.py
    python scripts/discovery/b1_baseline.py --show-text
    python scripts/discovery/b1_baseline.py --match "texto que vi en pantalla"
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.ce_assets import parse_steam_acf  # noqa: E402
from common.env import REPO_ROOT, load_env, require_path  # noqa: E402
from common.mcc_loc import loc_key, parse_mcc_loc  # noqa: E402
from common.mcc_lst import parse_lst  # noqa: E402

BS = "\\"
# The PoC line (B.12) plus three cryo-opening lines whose SU/SP texts differ in words. The PoC
# line's SU/SP texts differ only in the case of two letters, too weak to tell the tables apart.
LINES = [
    ("sound\\dialog\\a10\\a10_350_captkeyes", "poc_target"),
    ("sound\\dialog\\a10\\a10_080_cryotech", "discriminator"),
    ("sound\\dialog\\a10\\a10_130_cryotech", "discriminator"),
    ("sound\\dialog\\a10\\a10_150_cryotech", "discriminator"),
]
EXPECTED_BUILD = "19905945"
TABLES = {  # table -> (role, pinned sha256 of the verified copy; docs/subtitle-research.md B.12)
    "SU_Halo1": ("LATAM Spanish (primary)", "247d25298af3d5f990cd20ff5177e05078173347b7bdf395c3995a59c60244d0"),
    "SP_Halo1": ("Spain Spanish (fallback)", "794deac326d401a1fb6f5de50f8979f921159a412b095a368ef5424ed4342dda"),
}
COPIES = REPO_ROOT / "work" / "mcc" / "loc" / "copies"
LST = REPO_ROOT / "reference-audio" / "stage1" / "lst" / "sounds_dialogs.lst.bin"
REPORTS = REPO_ROOT / "work" / "mcc" / "reports"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def steam_build(mcc_root):
    for acf in sorted(mcc_root.parent.parent.glob("appmanifest_*.acf")):
        kv = parse_steam_acf(acf.read_text(encoding="utf-8", errors="replace"))
        if kv.get("installdir", "").lower() == mcc_root.name.lower():
            return {"appid": kv.get("appid"), "buildid": kv.get("buildid"), "manifest": acf.name}
    return {"appid": None, "buildid": None, "manifest": None}


def normalize(s):
    s = unicodedata.normalize("NFC", s).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def distinguishing_words(a, b):
    """Words present in one text but not the other, ignoring case and punctuation."""
    wa, wb = normalize(a).split(), normalize(b).split()
    only_a, only_b = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=wa, b=wb, autojunk=False).get_opcodes():
        if op != "equal":
            only_a += wa[i1:i2]
            only_b += wb[j1:j2]
    return only_a, only_b


def similarity(a, b):
    return difflib.SequenceMatcher(a=normalize(a), b=normalize(b), autojunk=False).ratio()


def match(seen, texts):
    """Closest (tag, per-table similarity, verdict) for on-screen text.

    The verdict names a table only with >= 0.8 similarity and a >= 0.02 lead over the other
    table (SU/SP differ by a few words, so whole-line ratios are close); otherwise "inconclusive".
    """
    tag = max(texts, key=lambda t: max(similarity(seen, x) for x in texts[t].values()))
    scores = {name: round(similarity(seen, txt), 3) for name, txt in texts[tag].items()}
    best = max(scores, key=scores.get)
    lead = scores[best] - min(scores.values())
    verdict = best if scores[best] >= 0.8 and lead >= 0.02 else "inconclusive"
    return tag, scores, verdict


def step0(mcc_root):
    checks, problems = {}, []
    build = steam_build(mcc_root)
    checks["steam_build_matches"] = build["buildid"] == EXPECTED_BUILD
    if not checks["steam_build_matches"]:
        problems.append(f"Steam build {build['buildid']} != expected {EXPECTED_BUILD}")

    loc_dir = mcc_root / "Data" / "ui" / "localization"
    tables, parsed = {}, {}
    for name, (role, pinned) in TABLES.items():
        inst, copy = loc_dir / f"{name}.bin", COPIES / f"{name}.bin"
        inst_hash = sha256_file(inst) if inst.is_file() else None
        copy_hash = sha256_file(copy) if copy.is_file() else None
        t = parse_mcc_loc(copy.read_bytes()) if copy_hash else None
        parsed[name] = t
        row = {
            "role": role, "install_sha256": inst_hash, "install_size": inst.stat().st_size if inst_hash else None,
            "copy_sha256": copy_hash, "pinned_sha256": pinned,
            "install_matches_copy": inst_hash is not None and inst_hash == copy_hash,
            "copy_matches_pin": copy_hash == pinned, "key_count": t["key_count"] if t else None,
            "header_ok": bool(t) and all(t[k] for k in ("name_hash_matches", "size_fields_match",
                                                        "payload_size_matches", "keys_ascending", "filler_is_zero")),
        }
        for k in ("install_matches_copy", "copy_matches_pin", "header_ok"):
            if not row[k]:
                problems.append(f"{name}: {k} is false")
        tables[name] = row

    lst_tags = {t.lower() for t, _, _ in parse_lst(LST.read_bytes())["records"]}
    lines, texts = [], {}
    for tag, purpose in LINES:
        key = loc_key(tag)
        line = {"tag": tag, "purpose": purpose, "key": f"0x{key:08X}", "in_lst": tag.lower() in lst_tags,
                "per_table": {}}
        if not line["in_lst"]:
            problems.append(f"{tag} not in {LST.name}")
        texts[tag] = {}
        for name, t in parsed.items():  # independent lookup per table
            hits = [i for i, k in enumerate(t["keys"]) if k == key] if t else []
            if len(hits) != 1:
                problems.append(f"{name}: key 0x{key:08X} ({tag}) found {len(hits)} times (need exactly 1)")
                line["per_table"][name] = {"key_hits": len(hits), "entry_index": None}
                continue
            txt = t["strings"][hits[0]]
            texts[tag][name] = txt
            line["per_table"][name] = {"key_hits": 1, "entry_index": hits[0],
                                       "entry_utf8_bytes": len(txt.encode("utf-8")), "entry_empty": not txt.strip()}
        if len(texts[tag]) == 2:
            only_su, only_sp = distinguishing_words(texts[tag]["SU_Halo1"], texts[tag]["SP_Halo1"])
            line["raw_text_differs"] = texts[tag]["SU_Halo1"] != texts[tag]["SP_Halo1"]
            line["word_differences"] = max(len(only_su), len(only_sp))
            line["visually_distinguishable"] = line["word_differences"] > 0
        lines.append(line)
    checks["all_keys_found_once_per_table"] = all(
        v["key_hits"] == 1 for ln in lines for v in ln["per_table"].values())
    checks["discriminator_available"] = any(
        ln.get("visually_distinguishable") for ln in lines if ln["purpose"] == "discriminator")
    if not checks["discriminator_available"]:
        problems.append("no baseline line has SU/SP texts that differ in words")
    report = {
        "schema": "b1-step0-preflight/2", "key_rule": "CRC-32/MPEG-2(UPPER(tag path))",
        "steam": build, "expected_buildid": EXPECTED_BUILD, "tables": tables, "lines": lines, "checks": checks,
        "problems": problems, "ok": not problems,
        "note": "read-only; no game file written; text kept out of this file (see b1_baseline_sheet.md)",
    }
    return report, texts


def write_sheet(report, texts, path):
    out = [
        "# B1 baseline sheet: a10 opening (LOCAL ONLY, git-ignored, do not commit)", "",
        "Settings: primary Spanish (Latin America), fallback Spanish (Spain). No file is modified.", "",
    ]
    for ln in report["lines"]:
        tag = ln["tag"]
        su, sp = texts[tag].get("SU_Halo1", ""), texts[tag].get("SP_Halo1", "")
        only_su, only_sp = distinguishing_words(su, sp)
        idx = {n: v["entry_index"] for n, v in ln["per_table"].items()}
        none = "(none; only case/punctuation differs)"
        out += [
            f"## `{tag.split(BS)[-1]}` ({ln['purpose']}), key `{ln['key']}`", "",
            f"**SU_Halo1 (LATAM)**, entry #{idx.get('SU_Halo1')}:", "", "```", su, "```", "",
            f"**SP_Halo1 (Spain)**, entry #{idx.get('SP_Halo1')}:", "", "```", sp, "```", "",
            "Words only in SU: " + (", ".join(only_su) or none), "",
            "Words only in SP: " + (", ".join(only_sp) or none), "",
        ]
    out += [
        "## Observation form", "",
        "| Line | Mode | Subtitle shown? | Text seen | SU / SP / neither | Audio language | Speaker name? |",
        "|---|---|---|---|---|---|---|",
    ]
    for ln in report["lines"]:
        for mode in ("Classic", "Anniversary"):
            out.append(f"| {ln['tag'].split(BS)[-1]} | {mode} | | | | | |")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show-text", action="store_true", help="also print SU/SP text to the terminal")
    ap.add_argument("--match", metavar="TEXT", help="compare on-screen text with SU and SP")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    env, _ = load_env()
    mcc_root = require_path(env, "HALO_MCC_FOLDER", kind="dir")
    report, texts = step0(mcc_root)

    if args.match is not None:
        tag, scores, verdict = match(args.match, texts)
        print(json.dumps({"closest_line": tag, "similarity": scores, "verdict": verdict}, indent=2))
        return 0

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "b1_step0_preflight.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_sheet(report, texts, REPORTS / "b1_baseline_sheet.md")
    print(json.dumps({k: report[k] for k in ("steam", "checks", "problems", "ok")}, indent=2))
    for name, row in report["tables"].items():
        print(f"{name}: install {str(row['install_sha256'])[:12]}... matches copy={row['install_matches_copy']} "
              f"pin={row['copy_matches_pin']} header_ok={row['header_ok']} keys={row['key_count']}")
    for ln in report["lines"]:
        idx = {n[:2]: v["entry_index"] for n, v in ln["per_table"].items()}
        print(f"{ln['tag'].split(BS)[-1]:<22} {ln['key']} SU#{idx.get('SU')} SP#{idx.get('SP')} "
              f"word_diffs={ln.get('word_differences')} ({ln['purpose']})")
    if args.show_text:
        for tag, by_table in texts.items():
            for name, txt in by_table.items():
                print(f"\n[{tag.split(BS)[-1]} / {name}]\n{txt}")
    print("\nwrote work/mcc/reports/b1_step0_preflight.json and b1_baseline_sheet.md (git-ignored)")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
