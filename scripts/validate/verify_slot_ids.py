"""Verify MCC slot identifiers campaign-wide (read-only; owner request 2026-10-08).

Checks, against the pinned bank copies in reference-audio/stage1/:
  1. deterministic: two independent in-memory builds of every level give identical records;
  2. stable: those builds equal the catalogs on disk (no ID added, removed, moved or renamed);
  3. unique: every slot_id appears once across all levels; every Spanish sample has exactly one;
  4. round trip: parse_slot_id(slot_id) == (name_in_bank, occurrence) and slot_id_for() gives it back;
  5. resolvable: (name, occurrence) leads back to the same bank index through the bank's own
     name table (case-insensitive grouping, exact-case name);
  6. compatible: every slot referenced by manual_mappings.json and verifications.json still exists
     with the same MCC tag; the a10 slot list equals its previous catalog (byte-identical file hash
     recorded in work/mcc/build.json).

Writes only work/reports/slot_id_verification.json. Exit 1 on any failure.

Example:
    python scripts/validate/verify_slot_ids.py
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_lib import FsbBank  # noqa: E402
from common.mcc_catalog import BankIndex, build_level, parse_slot_id, slot_id_for  # noqa: E402
from common.mcc_lst import parse_lst  # noqa: E402
from common.project_validation import dumps  # noqa: E402

COPIES = REPO_ROOT / "reference-audio" / "stage1"
FILES = {"english": ("fsb/sounds_dialogs.fsb", "lst/sounds_dialogs.lst.bin"),
         "spanish": ("fsb/sounds_dialogs_spanish.fsb", "lst/sounds_dialogs_spanish.lst.bin")}


def build_all(banks, lsts, levels, source):
    return {lv: build_level(lv, lsts["english"], lsts["spanish"], banks, source)[0] for lv in levels}


def main():
    build = json.loads((REPO_ROOT / "work/mcc/build.json").read_text(encoding="utf-8"))
    for lang, (fsb, lst) in FILES.items():
        pin = build["files"][f"{lang}.fsb"]["sha256"]
        if hashlib.sha256((COPIES / fsb).read_bytes()).hexdigest() != pin:
            raise SystemExit(f"{fsb} does not match its pin")
    banks = {lang: BankIndex(FsbBank(COPIES / f), lang, Path(f).name) for lang, (f, _) in FILES.items()}
    lsts = {lang: parse_lst((COPIES / l).read_bytes())["records"] for lang, (_, l) in FILES.items()}
    on_disk = {p.stem: [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
               for p in sorted((REPO_ROOT / "work/mcc/catalog").glob("*.jsonl"))}
    source = on_disk[next(iter(on_disk))][0]["source"]
    levels = sorted(on_disk)
    fails, checks = [], {}

    a, b = build_all(banks, lsts, levels, source), build_all(banks, lsts, levels, source)
    checks["deterministic"] = a == b
    if not checks["deterministic"]:
        fails.append("two builds differ")

    def ids(recs):
        return sorted((r["mcc_tag"], s["slot_id"], s["index"]) for r in recs for s in r["samples"]["spanish"])
    unstable = [lv for lv in levels if ids(a[lv]) != ids(on_disk[lv])]
    checks["stable_vs_disk"] = not unstable
    if unstable:
        fails.append(f"slot IDs differ from the catalogs on disk: {unstable}")

    samples = [(lv, r["mcc_tag"], s) for lv in levels for r in a[lv] for s in r["samples"]["spanish"]]
    counts = Counter(s["slot_id"] for _, _, s in samples)
    dup = sorted(k for k, n in counts.items() if n > 1)
    idx = Counter(s["index"] for _, _, s in samples)
    n_bank = banks["spanish"].bank.header["num_samples"]
    checks["unique"] = not dup
    checks["every_sample_once"] = sorted(idx) == list(range(n_bank)) and max(idx.values()) == 1
    if dup:
        fails.append(f"duplicate slot IDs: {dup[:10]}")
    if not checks["every_sample_once"]:
        fails.append("some Spanish bank samples have no slot or more than one")

    names = banks["spanish"].bank.names
    bad_rt, bad_res, encoded = [], [], 0
    for _, _, s in samples:
        sid = s["slot_id"]
        name, occ = parse_slot_id(sid)
        if (name, occ) != (s["name_in_bank"], s["name_occurrence_in_bank"]) or slot_id_for(name, occ) != sid:
            bad_rt.append(sid)
        encoded += "%" in sid
        group = [i for i, n in enumerate(names) if n is not None and n.lower() == name.lower()]
        if occ >= len(group) or group[occ] != s["index"] or names[group[occ]] != name:
            bad_res.append(sid)
    checks["round_trip"] = not bad_rt
    checks["resolves_to_same_bank_index"] = not bad_res
    if bad_rt:
        fails.append(f"round-trip failures: {bad_rt[:10]}")
    if bad_res:
        fails.append(f"slot IDs that don't resolve back to their bank index: {bad_res[:10]}")

    tag_of = {s["slot_id"]: tag for _, tag, s in samples}
    refs = []
    mm = json.loads((REPO_ROOT / "mappings/manual_mappings.json").read_text(encoding="utf-8"))
    refs += [(m["slot_id"], m["mcc_tag"], m["mapping_id"]) for m in mm["slots"]]
    ver = json.loads((REPO_ROOT / "mappings/verifications.json").read_text(encoding="utf-8"))
    refs += [(v["subject"][4:], v.get("mcc_tag"), v["id"]) for v in ver["verifications"]
             if v["subject"].startswith("mcc:")]
    broken = [r for r in refs if r[0] not in tag_of or (r[1] and tag_of[r[0]] != r[1])]
    checks["existing_references_resolve"] = not broken
    if broken:
        fails.append(f"existing references no longer resolve: {broken}")
    a10_file = REPO_ROOT / "work/mcc/catalog/a10.jsonl"
    a10_sha = hashlib.sha256(a10_file.read_bytes()).hexdigest()
    checks["a10_catalog_hash_matches_build_json"] = build["catalogs"]["a10"]["sha256"] == a10_sha
    checks["a10_ids_plain"] = all("%" not in s["slot_id"] and s["slot_id"].endswith("#0")
                                  for r in a["a10"] for s in r["samples"]["spanish"])

    report = {"schema": "slot-id-verification/1", "levels": len(levels), "slots": len(samples),
              "spanish_bank_samples": n_bank, "percent_encoded_ids": encoded,
              "references_checked": len(refs), "a10_catalog_sha256": a10_sha, "checks": checks, "failures": fails}
    out = REPO_ROOT / "work/reports/slot_id_verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(report), encoding="utf-8", newline="\n")
    print(f"{len(samples)} slot IDs over {len(levels)} levels ({encoded} percent-encoded); "
          f"{len(refs)} existing references; " + ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in checks.items()))
    for f in fails:
        print("  FAIL", f)
    sys.exit(1 if fails or not all(checks.values()) else 0)


if __name__ == "__main__":
    main()
