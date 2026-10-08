"""Reproduce the B1 (MCC Halo CE subtitle) format findings. Read-only, statistics only.

Inputs are COPIES (hash-verified against the install beforehand):
    work/mcc/loc/copies/*.bin, localized_string_overrides.xml   (Data/ui/localization)
    work/mcc/s3dpak/initial_textures.s3dpak                    (halo1/prebuild/paks)
    reference-audio/stage1/lst/sounds_dialogs.lst.bin

Writes work/mcc/reports/b1_findings.json. Never prints or stores game text, never writes
a localization file, and never links a subtitle to an audio slot (no catalog/mapping change).
See docs/subtitle-research.md Part B.4-B.9.

Example:
    python scripts/discovery/b1_subtitle_research.py
"""
import json
import random
import re
import struct
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT  # noqa: E402
from common.mcc_loc import loc_key, parse_mcc_loc  # noqa: E402
from common.mcc_lst import parse_lst  # noqa: E402

LOC = REPO_ROOT / "work" / "mcc" / "loc" / "copies"
PAK = REPO_ROOT / "work" / "mcc" / "s3dpak" / "initial_textures.s3dpak"
LST = REPO_ROOT / "reference-audio" / "stage1" / "lst" / "sounds_dialogs.lst.bin"
BS = "\\"
TOK = re.compile(r"\{[^}]*\}|%[a-z0-9]|\$[A-Za-z_]+|<[^>]+>")


def table(name, **kw):
    return parse_mcc_loc((LOC / f"{name}.bin").read_bytes(), **kw)


def header_checks():
    out = {}
    for p in sorted(LOC.glob("*.bin")):
        unsorted = p.name.endswith("_Global.bin") and not p.name.startswith("DBG_")
        t = parse_mcc_loc(p.read_bytes(), allow_unsorted=unsorted)
        out[p.stem] = {k: t[k] for k in ("key_count", "keys_ascending", "name_hash_matches", "size_fields_match",
                                         "payload_size_matches", "filler_is_zero")}
    return out


def dbg_pairing_and_hash():
    lbl, blk = table("DBG_LBL_Global")["entries"], table("DBG_BLNK_Global")["entries"]
    shared = set(lbl) & set(blk)
    pref = "DBG-BLK::"
    agree = sum(1 for k in shared if blk[k].startswith(pref) and blk[k][len(pref):].upper() == lbl[k].upper())
    ks = sorted(blk)
    shifted = dict(zip(ks, [blk[k] for k in ks[1:]] + [""]))
    agree_shift = sum(1 for k in shared if shifted[k][len(pref):].upper() == lbl[k].upper())
    orig = {k: v[len(pref):] for k, v in blk.items() if v.startswith(pref)}
    own = sum(1 for k, v in orig.items() if loc_key(v) == k)
    rnd = random.Random(0)
    fake = ("".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789") for _ in range(20)) for _ in range(20000))
    return {"dbg_lbl_vs_blnk_shared_keys": len(shared), "label_agrees_by_key": agree,
            "label_agrees_shifted_control": agree_shift,
            "orig_case_labels_hashing_to_own_key": f"{own}/{len(orig)}",
            "random_labels_hitting_any_key": f"{sum(loc_key(f) in lbl for f in fake)}/20000"}


def halo1_pairing():
    en = table("EN_Halo1")["entries"]
    res = {}
    for code in ("CS", "CT", "DE", "FR", "IT", "JP", "KO", "PB", "PR", "SP", "SU"):
        t = table(f"{code}_Halo1")["entries"]
        shared = sorted(set(en) & set(t))
        withtok = [k for k in shared if TOK.findall(en[k])]
        ks = sorted(t)
        sh = dict(zip(ks, [t[k] for k in ks[1:]] + [""]))
        res[code] = {"shared_keys": len(shared),
                     "token_agree": sum(1 for k in withtok if sorted(TOK.findall(en[k])) == sorted(TOK.findall(t[k]))),
                     "token_agree_shifted": sum(1 for k in withtok if sorted(TOK.findall(en[k])) == sorted(TOK.findall(sh[k]))),
                     "strings_with_tokens": len(withtok)}
    return res


def tag_path_rule():
    en = table("EN_Halo1")["entries"]
    sp, su = table("SP_Halo1")["entries"], table("SU_Halo1")["entries"]
    dialog = {k for k, v in en.items() if "&id" in v}
    tags = [t for t, _, _ in parse_lst(LST.read_bytes())["records"]]
    hits = {loc_key(t) for t in tags} & set(en)
    a10 = [t for t in tags if t.split(BS)[2] == "a10"]
    return {"lst_tags": len(tags), "tags_whose_path_hash_is_a_key": len(hits),
            "of_which_dialogue_keys": len(hits & dialog), "dialogue_keys_total": len(dialog),
            "a10_tags_with_key": sum(1 for t in a10 if loc_key(t) in en), "a10_tags": len(a10),
            "a10_nonempty_SP": sum(1 for t in a10 if sp.get(loc_key(t))),
            "a10_nonempty_SU": sum(1 for t in a10 if su.get(loc_key(t))),
            "expected_random_false_hits": round(len(tags) * len(en) / 2 ** 32, 4)}


def s3dpak_strings():
    d = PAK.read_bytes()
    n = struct.unpack_from("<I", d, 0)[0]
    offs = list(struct.unpack_from(f"<{n}I", d, 4))
    out = b"".join(zlib.decompress(d[a + 4:b]) for a, b in zip(offs, offs[1:] + [len(d)]))

    def entry(name):
        a = out.index(name.encode() + b"\x0e\x00\x00\x00")
        off, size, ln = struct.unpack_from("<III", out, a - 12)
        assert ln == len(name)
        rows = {}
        for line in out[off:off + size].decode("utf-16-le").splitlines():
            m = re.match(r"^﻿?\s*(sound\S+)\s+\"?(.*?)\"?\s*$", line)
            if m:
                rows[m.group(1).replace(BS + BS, BS).lower()] = m.group(2).replace(BS + '"', '"')
        return rows

    def norm(s):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().strip('"').strip()

    tabs = {c: table(f"{c}_Halo1")["entries"] for c in ("SP", "SU")}
    names = sorted({m.group().decode() for m in re.finditer(rb"strings_[a-z_]+", out)})
    res = {"chunks": n, "decompressed_bytes": len(out), "string_entries": names, "a10_comparison": {}}
    for name in ("strings_spanish", "strings_latam_spanish"):
        rows = entry(name)
        a10 = [k for k in rows if (BS + "a10" + BS) in k]
        for code, t in tabs.items():
            res["a10_comparison"][f"{name}~{code}_Halo1"] = \
                f"{sum(1 for k in a10 if norm(rows[k]) == norm(t.get(loc_key(k), '')))}/{len(a10)}"
    return res


def override_xml():
    root = ET.parse(LOC / "localized_string_overrides.xml").getroot()
    glob = set(table("EN_Global", allow_unsorted=True)["entries"])
    g = {c: table(f"{c}_Global", allow_unsorted=True)["entries"] for c in ("SP", "SU")}
    res = {}
    for lang in root:
        ent = {loc_key(e.get("key")): e.get("value") for e in lang}
        res[lang.get("name")] = {"entries": len(ent), "keys_in_Global": sum(1 for k in ent if k in glob),
                                 "value_equals_SP_Global": sum(1 for k, v in ent.items() if g["SP"].get(k) == v),
                                 "value_equals_SU_Global": sum(1 for k, v in ent.items() if g["SU"].get(k) == v)}
    return res


def main():
    findings = {"schema": "b1-findings/1", "header_checks": header_checks(), "dbg_tables": dbg_pairing_and_hash(),
                "halo1_key_string_pairing": halo1_pairing(), "tag_path_key_rule": tag_path_rule(),
                "override_xml": override_xml()}
    findings["s3dpak_initial_textures"] = s3dpak_strings() if PAK.exists() else "copy missing"
    out = REPO_ROOT / "work" / "mcc" / "reports" / "b1_findings.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: findings[k] for k in ("dbg_tables", "tag_path_key_rule")}, indent=1))
    print("s3dpak:", findings["s3dpak_initial_textures"]["a10_comparison"]
          if isinstance(findings["s3dpak_initial_textures"], dict) else findings["s3dpak_initial_textures"])
    print(f"wrote {out.relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
