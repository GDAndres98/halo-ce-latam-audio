"""MCC Halo CE dialogue catalog (milestone M2): records, slots, analysis.

Pure logic over already-parsed inputs: `.lst.bin` records (mcc_lst) and
FSB5 bank views (fsb5_lib.FsbBank or any object exposing `header`,
`samples`, `names`, `data`, `data_start`). Tests use synthetic banks.
Schema: docs/dialogue-catalog-design.md §4 (`mcc-dialogue-tag/3`).

Rules enforced here:
- sample identity comes from each bank's **own embedded name table**,
  resolved independently per language; the `.lst.bin` range is only a
  cross-check (`derived:lst_record_layout`). Fallback (campaign-wide
  catalogs, 2026-10-08): when the tag's basename finds no sample in the
  name table, or is shared by several `.lst.bin` tags (generic barks,
  cutscene permutations named `deathquiet 01`, `1`, ...), or its name hits
  are a strict subset of its range (`flood\\death` = `death`, `death2`, ...),
  the samples come from the tag's own `.lst.bin` range instead. Those samples carry
  `evidence: derived:lst_record_layout` and the record is flagged
  `samples_from_lst_range:<lang>`; nothing changes where names resolve;
- the replacement unit is the Spanish sample slot,
  `slot_id = "es:<name_in_spanish_bank>#<occurrence>"`;
- subtitle links stay `unresolved` (blocker B1); nothing is guessed;
- nothing is matched to Campaign Evolved.
"""
import hashlib
import re
from collections import Counter, defaultdict

from .asset_metadata import EXPLICIT, UNRESOLVED, derived

RECORD_SCHEMA = "mcc-dialogue-tag/3"
COVERAGE_SCHEMA = "mcc-coverage-report/1"
LANGUAGES = ("spanish", "english")  # Spanish first: it owns the slots
LST_EVIDENCE = derived("lst_record_layout")
SUBTITLE_UNRESOLVED = {"key_hash": None, "evidence": UNRESOLVED,
                       "reason": "blocker B1: no verified link from dialogue tag to a <LANG>_Halo1.bin key"}

_NAME_RE = re.compile(r"^(?P<level>[a-z]\d\d)_(?:(?P<flavor>flavor)_)?(?:(?P<insert>insert)_)?"
                      r"(?P<seq>\d+)_(?P<speaker>.+)$", re.I)


def tag_basename(tag):
    return tag.rsplit("\\", 1)[-1]


def parse_tag_name(tag):
    """Level / kind / sequence / speaker from the tag name only (all derived:tag_name)."""
    base = tag_basename(tag)
    m = _NAME_RE.match(base)
    if not m:
        return {"level": tag.split("\\")[2] if tag.count("\\") >= 3 else None, "kind": "other",
                "sequence": None, "speaker_from_name": None}
    kind = "flavor" if m["flavor"] else "insert" if m["insert"] else "scripted"
    return {"level": m["level"].lower(), "kind": kind, "sequence": m["seq"], "speaker_from_name": m["speaker"].lower()}


def sample_slices(bank):
    """[(start, end)] absolute byte ranges of each sample's compressed data in the bank."""
    offs = [s["data_offset"] for s in bank.samples]
    end_all = bank.header["data_size"]
    out = []
    for i, o in enumerate(offs):
        nxt = offs[i + 1] if i + 1 < len(offs) else end_all
        out.append((bank.data_start + o, bank.data_start + nxt))
    return out


class BankIndex:
    """Per-bank lookups built once: name -> indices, occurrence ordinal, data hashes."""

    def __init__(self, bank, language, file_name):
        self.bank, self.language, self.file_name = bank, language, file_name
        self.by_name = defaultdict(list)
        for i, n in enumerate(bank.names):
            if n is not None:
                self.by_name[n.lower()].append(i)
        self.occurrence = {}
        for idxs in self.by_name.values():
            for k, i in enumerate(idxs):
                self.occurrence[i] = k
        self.slices = sample_slices(bank)
        self._hash = {}

    def data_sha256(self, i):
        if i not in self._hash:
            a, b = self.slices[i]
            self._hash[i] = hashlib.sha256(self.bank.data[a:b]).hexdigest()
        return self._hash[i]

    def sample(self, i):
        s = self.bank.samples[i]
        a, b = self.slices[i]
        freq = s["frequency"]
        return {
            "index": i, "subsong": i + 1, "name_in_bank": self.bank.names[i],
            "name_occurrence_in_bank": self.occurrence.get(i, 0),
            "codec": self.bank.header["mode_name"], "codec_mode": self.bank.header["mode"],
            "freq": freq, "channels": s["channels"], "sample_count": s["sample_count"],
            "duration_s": round(s["sample_count"] / freq, 3) if isinstance(freq, int) else None,
            "duration_source": "fsb5_header",
            "data_offset": s["data_offset"], "data_bytes": b - a, "data_sha256": self.data_sha256(i),
            "metadata_chunks": [{"type": t, "size": z} for t, z in s["chunks"]],
            "evidence": EXPLICIT,
        }


def slot_id_for(name_in_bank, occurrence):
    """es:<name>#<occurrence>. Only '%', '#' and whitespace in the name are percent-encoded
    (generic bark names such as 'deathquiet 01'); every a10 name is unchanged."""
    enc = "".join(f"%{ord(ch):02X}" if ch in "%#" or ch.isspace() else ch for ch in name_in_bank)
    return f"es:{enc}#{occurrence}"


def build_record(tag, lst_ranges, banks, source, shared_basenames=None):
    """tag: lst path; lst_ranges: {lang: (start, count) | None}; banks: {lang: BankIndex}.

    shared_basenames: {lang: set of lowercased basenames used by more than one lst tag}; for those
    (and for names the bank doesn't have) the tag's own lst range is used (see module doc)."""
    info = parse_tag_name(tag)
    base = tag_basename(tag)
    rec = {"schema": RECORD_SCHEMA, "mcc_tag": tag, "tag_name": base.lower(), **info,
           "name_evidence": derived("tag_name"), "lst": {}, "samples": {}, "flags": [],
           "subtitle": dict(SUBTITLE_UNRESOLVED), "source": source}
    flags = set()
    for lang in LANGUAGES:
        bi = banks[lang]
        idxs = bi.by_name.get(base.lower(), [])
        rng = lst_ranges.get(lang)
        lst_idx = list(range(rng[0], rng[0] + rng[1])) if rng else []
        rec["lst"][lang] = ({"first_sample_index": rng[0], "sample_count": rng[1], "evidence": LST_EVIDENCE}
                            if rng else {"evidence": UNRESOLVED, "reason": "tag not in this language's lst.bin"})
        rec["lst"][lang]["agrees_with_name_table"] = lst_idx == idxs
        if lst_idx != idxs:
            flags.add(f"lst_disagrees_with_names:{lang}")
        shared = base.lower() in (shared_basenames or {}).get(lang, ())
        subset = bool(idxs) and set(idxs) < set(lst_idx)  # e.g. one permutation named exactly like the tag
        from_lst = (bool(lst_idx) and lst_idx != idxs and (not idxs or shared or subset)
                    and all(bi.bank.names[i] for i in lst_idx if i < len(bi.bank.names)))
        if from_lst:
            idxs = [i for i in lst_idx if i < len(bi.bank.names)]
            flags.add(f"samples_from_lst_range:{lang}")
        samples = [bi.sample(i) for i in idxs]
        for k, s in enumerate(samples):
            s["ordinal_in_tag"] = k
            if from_lst:
                s["evidence"] = LST_EVIDENCE
            if lang == "spanish":
                s["slot_id"] = slot_id_for(s["name_in_bank"], s["name_occurrence_in_bank"])
        rec["samples"][lang] = samples
        if not samples:
            flags.add(f"missing:{lang}")
            rec["samples"][lang] = []
            rec.setdefault("unresolved", []).append(
                {"field": f"samples.{lang}", "reason": f"no sample named {base} in {bi.file_name}"})
        if any(s["name_occurrence_in_bank"] for s in samples) or len(bi.by_name.get(base.lower(), [])) > 1:
            flags.add(f"name_repeats_in_bank:{lang}")
    es, en = rec["samples"]["spanish"], rec["samples"]["english"]
    if len(es) != len(en):
        flags.add("sample_count_differs_between_languages")
    if [s["index"] for s in es] != [s["index"] for s in en]:
        flags.add("index_differs_between_languages")
    if es and en and [s["name_in_bank"] for s in es] != [s["name_in_bank"] for s in en]:
        flags.add("name_case_differs_between_languages")
    if any(a["data_sha256"] == b["data_sha256"] for a, b in zip(es, en)):
        flags.add("identical_data_es_en")
    if len(es) > 1:
        flags.add("permutations")
    rec["slot_ids"] = [s["slot_id"] for s in es]
    rec["flags"] = sorted(flags)
    return rec


def build_level(level, lst_en, lst_es, banks, source):
    """-> (records, issues). lst_*: parsed records [(tag, start, count)]."""
    prefix = f"sound\\dialog\\{level}\\".lower()
    en = {t: (s, c) for t, s, c in lst_en if t.lower().startswith(prefix)}
    es = {t: (s, c) for t, s, c in lst_es if t.lower().startswith(prefix)}
    issues = []
    if list(en) != list(es):
        issues.append({"code": "lst_tag_lists_differ", "only_english": sorted(set(en) - set(es)),
                       "only_spanish": sorted(set(es) - set(en))})
    tags = list(dict.fromkeys(list(en) + list(es)))
    shared = {lang: {b for b, n in Counter(tag_basename(t).lower() for t, _, _ in lst).items() if n > 1}
              for lang, lst in (("english", lst_en), ("spanish", lst_es))}
    records = [build_record(t, {"english": en.get(t), "spanish": es.get(t)}, banks, source, shared)
               for t in tags]
    # Bank samples carrying the level prefix but owned by no tag (would otherwise be silently dropped).
    names = {r["tag_name"] for r in records}
    for lang in LANGUAGES:
        bi = banks[lang]
        claimed = {s["index"] for r in records for s in r["samples"][lang]}  # incl. lst-range fallbacks
        stray = sorted(i for n, idxs in bi.by_name.items() if n.startswith(f"{level.lower()}_") and n not in names
                       for i in idxs if i not in claimed)
        if stray:
            issues.append({"code": "bank_samples_without_tag", "language": lang,
                           "samples": [{"index": i, "name": bi.bank.names[i]} for i in stray]})
    # Duplicate audio data inside the level, per language (reported, never merged).
    for lang in LANGUAGES:
        g = defaultdict(list)
        for r in records:
            for s in r["samples"][lang]:
                g[s["data_sha256"]].append(s["index"])
        dups = sorted(v for v in g.values() if len(v) > 1)
        if dups:
            issues.append({"code": "duplicate_sample_data", "language": lang, "index_groups": dups})
    slot_counts = Counter(sid for r in records for sid in r["slot_ids"])
    clash = sorted(s for s, c in slot_counts.items() if c > 1)
    if clash:
        issues.append({"code": "slot_id_collision", "slot_ids": clash})
    return records, issues


def coverage(level, records, issues, export_units=None):
    cov = {"schema": COVERAGE_SCHEMA, "level": level, "tags": len(records),
           "by_kind": dict(sorted(Counter(r["kind"] for r in records).items())),
           "flags": dict(sorted(Counter(f for r in records for f in r["flags"]).items())),
           "issues": dict(sorted(Counter(i["code"] for i in issues).items())),
           "subtitle_evidence": dict(Counter(r["subtitle"]["evidence"] for r in records)),
           "languages": {}}
    for lang in LANGUAGES:
        ss = [s for r in records for s in r["samples"][lang]]
        d = sorted(s["duration_s"] for s in ss if s["duration_s"] is not None)
        cov["languages"][lang] = {
            "samples": len(ss),
            "tags_with_samples": sum(1 for r in records if r["samples"][lang]),
            "tags_missing": sorted(r["mcc_tag"] for r in records if not r["samples"][lang]),
            "codecs": dict(Counter(s["codec"] for s in ss)),
            "freqs": dict(sorted(Counter(s["freq"] for s in ss).items())),
            "channels": dict(sorted(Counter(s["channels"] for s in ss).items())),
            "lst_agrees": sum(1 for r in records if r["lst"][lang].get("agrees_with_name_table")),
            "header_duration_s": {"min": d[0], "max": d[-1], "total": round(sum(d), 3)} if d else None,
        }
    if export_units is not None:
        for lang in LANGUAGES:
            us = [u for u in export_units if u["language"] == lang]
            cov["languages"][lang]["decode_status"] = dict(sorted(Counter(u.get("status") for u in us).items()))
            cov["languages"][lang]["frames_match_header"] = sum(1 for u in us if u.get("frames_match_header"))
    return cov


def export_plan(records):
    """One decode unit per (language, sample index), named from the language-independent tag name."""
    units = []
    for r in sorted(records, key=lambda r: r["tag_name"]):
        for lang in LANGUAGES:
            for s in r["samples"][lang]:
                suffix = f"__{s['ordinal_in_tag']}"
                units.append({"key": f"{lang}:{s['index']}", "language": lang, "index": s["index"],
                              "subsong": s["subsong"], "mcc_tag": r["mcc_tag"], "name_in_bank": s["name_in_bank"],
                              "slot_id": s.get("slot_id"), "header_sample_count": s["sample_count"],
                              "data_sha256": s["data_sha256"],
                              "wav_path": f"{lang}/{r['tag_name']}{suffix}.wav"})
    return sorted(units, key=lambda u: u["key"])


def recommend(records, units, n=5):
    """Deterministic, varied MCC samples for a human listening check (Spanish slot + English). Not a match."""
    ok = {(u["language"], u["index"]): u for u in units if u.get("status") == "ok"}
    cands = [r for r in records if r["samples"]["spanish"] and r["samples"]["english"]
             and all(("spanish", s["index"]) in ok for s in r["samples"]["spanish"])
             and all(("english", s["index"]) in ok for s in r["samples"]["english"])]

    def dur(r, lang):
        return sum(ok[(lang, s["index"])]["wav"]["duration_s"] for s in r["samples"][lang])

    def median(pool):
        pool = sorted(pool, key=lambda r: (dur(r, "spanish"), r["tag_name"]))
        return pool[len(pool) // 2] if pool else None

    picks = []

    def take(r, why):
        if r and r["mcc_tag"] not in {p[0]["mcc_tag"] for p in picks}:
            picks.append((r, why))

    used = lambda: {p[0]["speaker_from_name"] for p in picks}  # noqa: E731
    take(median([r for r in cands if r["kind"] == "scripted" and r["speaker_from_name"].startswith("cryo")]),
         "scripted cryo-bay line, median length")
    take(median([r for r in cands if r["kind"] == "scripted" and r["speaker_from_name"] == "cortana"]),
         "scripted Cortana line, median length")
    take(median([r for r in cands if r["kind"] == "flavor"]), "flavor (ambient) line, median length")
    take(median([r for r in cands if r["kind"] == "scripted" and r["speaker_from_name"] not in used()
                  and not r["speaker_from_name"].startswith("cryo")]),
         "scripted line from another speaker, median length")
    take(max((r for r in cands if r["mcc_tag"] not in {p[0]["mcc_tag"] for p in picks} and dur(r, "english") > 0),
             key=lambda r: (abs(dur(r, "spanish") - dur(r, "english")), r["tag_name"]), default=None),
         "largest Spanish vs English duration difference")
    for r in cands:
        if len(picks) >= n:
            break
        take(r, "fill-in (slot had no candidate)")
    out = []
    for r, why in picks[:n]:
        item = {"mcc_tag": r["mcc_tag"], "why": why, "kind": r["kind"], "speaker_from_name": r["speaker_from_name"],
                "slot_ids": r["slot_ids"], "flags": r["flags"], "audio": {}}
        for lang in LANGUAGES:
            item["audio"][lang] = [{"index": s["index"], "wav_path": ok[(lang, s["index"])]["wav_path"],
                                    "duration_s": ok[(lang, s["index"])]["wav"]["duration_s"]}
                                   for s in r["samples"][lang]]
        out.append(item)
    return {"schema": "mcc-review-picks/1", "picks": out}


def export_units(units, out_root, decode, inspect_wav, sha256_file):
    """Decode each unit with decode(unit, tmp_wav) -> (ok, message); write atomically; check frames vs header.

    Status: ok | empty | silent | unreadable (from inspect_wav) | decode_failed. Nothing is substituted.
    """
    import os
    for u in units:
        for f in ("status", "reason", "wav", "wav_sha256", "frames_match_header"):
            u.pop(f, None)
        wav = out_root / u["wav_path"]
        wav.parent.mkdir(parents=True, exist_ok=True)
        tmp = wav.with_name(wav.name + ".tmp")
        tmp.unlink(missing_ok=True)
        ok, msg = decode(u, tmp)
        if not ok or not tmp.exists():
            tmp.unlink(missing_ok=True)
            u.update(status="decode_failed", reason=(msg or "decoder produced no file")[:300])
            continue
        info = inspect_wav(tmp)
        os.replace(tmp, wav)
        u["wav"] = {k: v for k, v in info.items() if k not in ("status", "reason")}
        u["wav_sha256"] = sha256_file(wav)
        u["status"] = info["status"]
        if info.get("reason"):
            u["reason"] = info["reason"]
        u["frames_match_header"] = info.get("frames") == u["header_sample_count"]
    return units
