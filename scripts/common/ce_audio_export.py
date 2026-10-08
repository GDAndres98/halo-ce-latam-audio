"""M1b: plan, run and report the decode of catalog-linked Campaign Evolved
media to WAV. Pure logic plus small file helpers. Reading the containers
and running the decoder are injected callables, so tests drive everything
with synthetic records and a fake decoder.

Rules enforced here:
- one export unit per (language, media_id): repeated media references are
  decoded once and every referencing ce_line_ref is kept on the unit;
- records flagged `test_event` are excluded from decoding. They keep their
  catalog rows, and their status is `excluded:test_event`, not a failure;
- the source .wem must match the catalog's wem_sha256 or it isn't decoded;
- missing, empty, silent or failed audio is reported as such. Nothing is
  synthesized or substituted from another language;
- nothing is matched to MCC.
"""
import array
import hashlib
import json
import os
import statistics
import sys
import wave
from collections import Counter, defaultdict

EXPORT_SCHEMA = "ce-audio-export/1"
COVERAGE_SCHEMA = "ce-audio-coverage/1"
REVIEW_SCHEMA = "ce-audio-review-picks/1"
EXPORT_LANGUAGES = ("Spanish(Mexico)", "English(US)")
LANGUAGE_CULTURE = {"Spanish(Mexico)": "es-MX", "English(US)": "en", "Spanish(Spain)": "es-ES"}
EXCLUDE_FLAGS = {"test_event": "event is a test event with no dialogue language; catalog record kept, not decoded"}
# Flags marking a reference that replays another line's event (the M01 `...1` duplicates).
SECONDARY_FLAGS = ("no_transcription", "event_package_folder_mismatch")
MANUAL_REVIEW_FLAGS = ("foreign_string_table",)

OK, EMPTY, SILENT, UNREADABLE = "ok", "empty", "silent", "unreadable"
DECODE_FAILED, SOURCE_MISSING, SOURCE_HASH_MISMATCH = "decode_failed", "source_missing", "source_hash_mismatch"


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def ref_stem(ce_line_ref):
    """'vo_x#0' -> 'vo_x__0' (filesystem- and URL-safe; '/' of a qualified record_id -> '__')."""
    record_id, idx = ce_line_ref.rsplit("#", 1)
    return f"{record_id.replace('/', '__')}__{idx}"


def unit_key(language, media_id):
    return f"{language}:{media_id}"


# --------------------------------------------------------------------------- planning
def plan(records, languages=EXPORT_LANGUAGES):
    """-> (units {key: unit}, references [row]) from catalog records. Pure."""
    by_id = {r["record_id"]: r for r in records}
    units, refs = {}, []
    for r in sorted(records, key=lambda r: r["record_id"]):
        excluded = sorted(f for f in r["flags"] if f in EXCLUDE_FLAGS)
        for e in r["entries"]:
            for lang in languages:
                row = {"ce_line_ref": e["ce_line_ref"], "record_id": r["record_id"], "language": lang,
                       "family": r["family"], "units": []}
                refs.append(row)
                if excluded:
                    row.update(status=f"excluded:{excluded[0]}", reason=EXCLUDE_FLAGS[excluded[0]])
                    continue
                m = e["media"].get(lang)
                if not m or m.get("evidence") != "explicit":
                    row.update(status="missing_in_catalog",
                               reason=(m or {}).get("reason", "language not exported by the catalog"))
                    continue
                row["status"] = "linked"
                for item in m["media"]:
                    k = unit_key(lang, item["media_id"])
                    u = units.setdefault(k, {
                        "key": k, "language": lang, "media_id": item["media_id"],
                        "wem_vfs_path": item.get("vfs_path"), "container": item.get("container"),
                        "wem_sha256": item.get("wem_sha256"), "wem_bytes": item.get("wem_bytes"),
                        "source_name": item.get("source_name"), "references": [], "catalog_conflicts": []})
                    if item.get("wem_sha256") != u["wem_sha256"]:
                        u["catalog_conflicts"].append({"ce_line_ref": e["ce_line_ref"],
                                                       "wem_sha256": item.get("wem_sha256")})
                    if e["ce_line_ref"] not in u["references"]:
                        u["references"].append(e["ce_line_ref"])
                    row["units"].append(k)
    for u in units.values():
        def rank(ref):
            rec = by_id[ref.rsplit("#", 1)[0]]
            return (any(f in rec["flags"] for f in SECONDARY_FLAGS), ref)
        u["references"].sort(key=rank)
        u["primary_ref"] = u["references"][0]
        u["deduplicated"] = len(u["references"]) > 1
    # Stable filenames: the primary reference's stem; a suffix only if one entry lists several media.
    per_stem = defaultdict(list)
    for k in sorted(units, key=lambda k: (units[k]["language"], units[k]["primary_ref"], units[k]["media_id"])):
        per_stem[(units[k]["language"], units[k]["primary_ref"])].append(k)
    for (lang, ref), keys in per_stem.items():
        for n, k in enumerate(keys):
            suffix = "" if len(keys) == 1 else f"__m{n}"
            units[k]["wav_path"] = f"{lang}/{ref_stem(ref)}{suffix}.wav"
    refs.sort(key=lambda x: (x["ce_line_ref"], x["language"]))
    return units, refs


# --------------------------------------------------------------------------- WAV inspection
def inspect_wav(path):
    """Header + content facts of a decoded WAV. Never raises."""
    try:
        with wave.open(str(path), "rb") as w:
            rate, ch, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            raw = w.readframes(frames)
    except (wave.Error, EOFError, OSError) as e:
        return {"status": UNREADABLE, "reason": f"{type(e).__name__}: {e}"}
    info = {"sample_rate": rate, "channels": ch, "sample_width_bytes": width, "frames": frames,
            "duration_s": round(frames / rate, 3) if rate else None, "peak": None}
    if width == 2 and raw:
        a = array.array("h")
        a.frombytes(raw[:len(raw) - len(raw) % 2])
        if sys.byteorder == "big":
            a.byteswap()
        info["peak"] = max(max(a), -min(a))
    if frames == 0 or not raw:
        info["status"] = EMPTY
    elif info["peak"] == 0:
        info["status"] = SILENT
    else:
        info["status"] = OK
    return info


# --------------------------------------------------------------------------- export
def export_units(units, out_root, media_root, read_source, decode):
    """Decode every unit. read_source(unit) -> bytes | None; decode(wem_path, wav_path) -> (ok, message).

    The .wem is kept byte-identical under media_root/<language>/<media_id>.wem and only decoded when it
    matches the catalog hash. WAVs are written to a temp name and then replaced, so a failed run never
    leaves a half-written file under the final name.
    """
    for k in sorted(units):
        u = units[k]
        for f in ("status", "reason", "wav_sha256", "wav"):
            u.pop(f, None)
        data = read_source(u)
        if data is None:
            u.update(status=SOURCE_MISSING, reason="media path not found in the language pak")
            continue
        got = hashlib.sha256(data).hexdigest()
        if got != u["wem_sha256"]:
            u.update(status=SOURCE_HASH_MISMATCH, reason=f"pak .wem sha256 {got[:16]}… != catalog; rebuild the catalog")
            continue
        wem = media_root / u["language"] / f"{u['media_id']}.wem"
        wem.parent.mkdir(parents=True, exist_ok=True)
        if not wem.exists() or sha256_file(wem) != got:
            wem.write_bytes(data)
        u["wem_copy"] = f"{u['language']}/{u['media_id']}.wem"  # relative to media_root
        wav = out_root / u["wav_path"]
        wav.parent.mkdir(parents=True, exist_ok=True)
        tmp = wav.with_name(wav.name + ".tmp")
        tmp.unlink(missing_ok=True)
        ok, msg = decode(wem, tmp)
        if not ok or not tmp.exists():
            tmp.unlink(missing_ok=True)
            u.update(status=DECODE_FAILED, reason=(msg or "decoder produced no file")[:300])
            continue
        info = inspect_wav(tmp)
        os.replace(tmp, wav)
        u["wav"] = {k2: v for k2, v in info.items() if k2 not in ("status", "reason")}
        u["wav_sha256"] = sha256_file(wav)
        u["status"] = info["status"]
        if info.get("reason"):
            u["reason"] = info["reason"]
    return units


# --------------------------------------------------------------------------- reports
def manual_review_items(records):
    """Unusual relationships kept for later manual review (never resolved here)."""
    out = []
    for r in sorted(records, key=lambda r: r["record_id"]):
        hit = [f for f in r["flags"] if f in MANUAL_REVIEW_FLAGS]
        if not hit:
            continue
        for e in r["entries"]:
            out.append({"ce_line_ref": e["ce_line_ref"], "flags": hit, "family": r["family"],
                        "event": e["event"].get("package"),
                        "string_table": e["transcription"].get("string_table"),
                        "line_key": e["transcription"].get("line_key"),
                        "note": "voice asset family differs from its event/subtitle family; kept as-is"})
    return out


def coverage(units, refs, languages=EXPORT_LANGUAGES):
    cov = {"schema": COVERAGE_SCHEMA, "languages": {}}
    for lang in languages:
        lr = [r for r in refs if r["language"] == lang]
        lu = [u for u in units.values() if u["language"] == lang]
        st = Counter(r["status"] for r in lr)
        ustat = Counter(u.get("status", "not_run") for u in lu)
        ok = [u for u in lu if u.get("status") == OK]
        durs = sorted(u["wav"]["duration_s"] for u in ok)
        linked_ok = sum(1 for r in lr if r["status"] == "linked"
                        and all(units[k].get("status") == OK for k in r["units"]))
        cov["languages"][lang] = {
            "references": len(lr),
            "reference_status": dict(sorted(st.items())),
            "references_with_ok_audio": linked_ok,
            "units": len(lu),
            "deduplicated_units": sum(1 for u in lu if u["deduplicated"]),
            "references_saved_by_dedup": sum(len(u["references"]) - 1 for u in lu),
            "unit_status": dict(sorted(ustat.items())),
            "sample_rates": dict(sorted(Counter(u["wav"]["sample_rate"] for u in ok).items())),
            "channels": dict(sorted(Counter(u["wav"]["channels"] for u in ok).items())),
            "duration_s": {"min": durs[0], "median": statistics.median(durs), "max": durs[-1],
                           "total": round(sum(durs), 3)} if durs else None,
            "catalog_conflicts": sum(1 for u in lu if u["catalog_conflicts"]),
        }
    # Distinct media IDs whose decoded audio is byte-identical: reported, not merged.
    by_hash = defaultdict(list)
    for u in units.values():
        if u.get("wav_sha256"):
            by_hash[(u["language"], u["wav_sha256"])].append(u["key"])
    cov["identical_audio_different_media_id"] = sorted(sorted(v) for v in by_hash.values() if len(v) > 1)
    problems = [{"key": u["key"], "status": u.get("status"), "reason": u.get("reason"),
                 "references": u["references"]} for u in sorted(units.values(), key=lambda u: u["key"])
                if u.get("status") != OK]
    cov["problem_units"] = problems
    cov["missing_in_catalog"] = [{"ce_line_ref": r["ce_line_ref"], "language": r["language"], "reason": r["reason"]}
                                 for r in refs if r["status"] == "missing_in_catalog"]
    cov["excluded"] = dict(sorted(Counter(r["status"] for r in refs if r["status"].startswith("excluded:")).items()))
    accounted = all(r["status"] != "linked" or all(k in units for k in r["units"]) for r in refs)
    cov["all_references_accounted_for"] = accounted
    return cov


def pair_durations(units, refs, a="Spanish(Mexico)", b="English(US)"):
    """{ce_line_ref: (dur_a, dur_b)} for references with exactly one OK unit in both languages."""
    got = defaultdict(dict)
    for r in refs:
        if r["status"] == "linked" and len(r["units"]) == 1 and units[r["units"][0]].get("status") == OK:
            got[r["ce_line_ref"]][r["language"]] = units[r["units"][0]]["wav"]["duration_s"]
    return {ref: (d[a], d[b]) for ref, d in sorted(got.items()) if a in d and b in d}


def recommend(records, units, refs, already_verified=(), n=5):
    """Deterministic, varied picks for a human listening/reading check. Not a match suggestion."""
    by_ref = {e["ce_line_ref"]: (r, e) for r in records for e in r["entries"]}
    pairs = pair_durations(units, refs)
    primary = {u["primary_ref"] for u in units.values()}
    cands = [ref for ref in pairs if ref not in already_verified]

    def speaker(ref):
        return by_ref[ref][1]["transcription"].get("metadata", {}).get("Character")

    def median_pick(pool):
        pool = sorted(pool, key=lambda ref: (sum(pairs[ref]), ref))
        return pool[len(pool) // 2] if pool else None

    slots = [
        ("cinematic line, median length", lambda used: median_pick(
            [x for x in cands if by_ref[x][0]["family"] == "cinematic" and x in primary
             and set(by_ref[x][0]["flags"]) <= {"no_lipsync"}])),
        ("scripted line, different speaker, median length", lambda used: median_pick(
            [x for x in cands if by_ref[x][0]["family"] == "scripted" and x in primary
             and speaker(x) and speaker(x) not in {speaker(u) for u in used}
             and not any(f in by_ref[x][0]["flags"] for f in SECONDARY_FLAGS)])),
        ("cross-family subtitle relationship (manual review item)", lambda used: next(
            (x for x in cands if any(f in by_ref[x][0]["flags"] for f in MANUAL_REVIEW_FLAGS)), None)),
        ("deduplicated media: this reference shares its audio file with another", lambda used: next(
            (x for x in cands if x not in primary), None)),
        ("largest es-MX vs en duration ratio (new speaker preferred)", lambda used: max(
            (x for x in cands if x in primary and x not in used and min(pairs[x]) > 0),
            key=lambda x: (speaker(x) not in {speaker(u) for u in used}, max(pairs[x]) / min(pairs[x]), x),
            default=None)),
    ]
    picks = []
    for reason, fn in slots:
        ref = fn([p["ce_line_ref"] for p in picks])
        if ref and ref not in {p["ce_line_ref"] for p in picks}:
            picks.append({"ce_line_ref": ref, "why": reason})
    for ref in cands:  # top up deterministically if a slot had no candidate
        if len(picks) >= n:
            break
        if ref in primary and ref not in {p["ce_line_ref"] for p in picks}:
            picks.append({"ce_line_ref": ref, "why": "fill-in (slot had no candidate)"})
    out = []
    for p in picks[:n]:
        r, e = by_ref[p["ce_line_ref"]]
        item = {**p, "family": r["family"], "speaker": speaker(p["ce_line_ref"]), "flags": r["flags"],
                "audio": {}, "subtitles": {}}
        for row in refs:
            if row["ce_line_ref"] == p["ce_line_ref"] and row["status"] == "linked":
                u = units[row["units"][0]]
                item["audio"][row["language"]] = {"wav_path": u["wav_path"], "duration_s": u["wav"]["duration_s"],
                                                  "media_id": u["media_id"], "shared_with": u["references"]}
        for lang in EXPORT_LANGUAGES:
            s = e["subtitles"].get(LANGUAGE_CULTURE[lang], {})
            item["subtitles"][LANGUAGE_CULTURE[lang]] = (
                {"namespace": s.get("namespace"), "key": s.get("key"), "text": s.get("text")}
                if s.get("evidence") == "explicit" else {"evidence": s.get("evidence"), "reason": s.get("reason")})
        out.append(item)
    return {"schema": REVIEW_SCHEMA, "picks": out}


def dumps_json(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
