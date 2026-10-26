"""Compares the English audio of an MCC level folder with a CE Systemic folder, by sound (docs/suggested-matching.md).

    python scripts/catalog/build_audio_matches.py --level grunt                  # CE folder named like the level
    python scripts/catalog/build_audio_matches.py --level grunt --ce-folder vo_sys_grunt
    python scripts/catalog/build_audio_matches.py --mapped         # config/suggest_characters.json: own folders only
    python scripts/catalog/build_audio_matches.py --unmatched-all  # every other unmatched MCC sound vs all CE

For barks (no subtitles on either side; owner, 2026-10-23): many CE English variations are MCC's English takes again,
sometimes quieter or slightly changed. Every MCC English take of the level is compared with every CE English(US)
variation of the folder (common/audio_match.py); the best CE variations per take are written to
work/suggest/audio/<level>__<folder>.json, which the Suggestions tab reads.

Read-only for mappings/ and the catalogs. Decodes on demand into work/ like the Studio (vgmstream, the installed CE
paks read-only). Features are cached in work/suggest/audio/features/, so a second run only compares.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
from common import audio_match  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.ondemand_audio import AudioUnavailable, CeAudio, MccAudio, ce_source_reader, vgmstream_decoder  # noqa: E402
from m4_app import M4App  # noqa: E402

DEFAULT_VGMSTREAM = Path("D:/Tools/vgmstream-r2117/vgmstream-cli.exe")
OUT_DIR = "work/suggest/audio"
SCHEMA = "audio-match/1"
TOP = 5


def out_path(root, level, folder):
    return Path(root) / OUT_DIR / f"{level}__{folder}.json"


def _cached_features(root, kind, key, wav_path):
    p = Path(root) / OUT_DIR / "features" / kind / f"{key}.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    f = audio_match.features(wav_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(f), encoding="utf-8")
    return f


def build(app, level, folder, jobs=8, log=print, name=None):
    """Every English take of a level vs the CE Systemic folder(s) `folder` (a name or a list) -> the result document,
    also written to work/suggest/audio/<level>__<name or folder>.json. app: an M4App with mcc_audio and ce_audio."""
    root = app.root
    if level not in app.levels:
        raise SystemExit(f"unknown level {level}")
    folders = [folder] if isinstance(folder, str) else list(folder)
    recs = [r for r in app.missions.get("SYS", []) if r.get("folder") in folders]
    missing = [f for f in folders if not any(r.get("folder") == f for r in recs)]
    if missing:
        raise SystemExit(f"no CE Systemic records in folder(s) {', '.join(missing)}")
    folder = "+".join(folders)
    mcc = [(r["mcc_tag"], s) for r in app.levels[level] for s in r["samples"]["english"]]
    ce = []
    for r in recs:
        for e in r["entries"]:
            m = e["media"].get("English(US)") or {}
            if m.get("evidence") == "explicit" and m.get("media"):
                ce.append((r["record_id"], e["ce_line_ref"], m["media"][0]))
    log(f"{level}: {len(mcc)} MCC English takes; {folder}: {len(ce)} CE English variations")

    failed = []

    def mcc_feat(item):
        tag, s = item
        try:
            return _cached_features(root, "mcc", s["data_sha256"], app.mcc_audio.wav(level, "english", s))
        except (AudioUnavailable, OSError, ValueError) as e:
            failed.append({"side": "mcc", "english_index": s["index"], "error": str(e)})
            return None

    def ce_feat(item):
        _rid, ref, media = item
        try:
            return _cached_features(root, "ce", media["wem_sha256"], app.ce_audio.wav("SYS", "English(US)", media))
        except (AudioUnavailable, OSError, ValueError) as e:
            failed.append({"side": "ce", "ce_line_ref": ref, "error": str(e)})
            return None

    t = time.time()
    with cf.ThreadPoolExecutor(jobs) as pool:
        mf = list(pool.map(mcc_feat, mcc))
        cfeat = list(pool.map(ce_feat, ce))
    log(f"decoded and measured in {time.time() - t:.0f} s ({len(failed)} failed)")

    t = time.time()
    pairs = {}
    for (tag, s), fa in zip(mcc, mf):
        if not fa:
            continue
        scored = []
        for (rid, ref, _m), fb in zip(ce, cfeat):
            if not fb:
                continue
            score, lag, gain = audio_match.compare(fa, fb)
            if score > 0:
                scored.append({"ce_line_ref": ref, "record_id": rid, "score": score, "gain_db": gain,
                               "lag_ms": int(lag * audio_match.FRAME_S * 1000)})
        scored.sort(key=lambda x: (-x["score"], x["ce_line_ref"]))
        pairs[str(s["index"])] = scored[:TOP]
    log(f"compared in {time.time() - t:.0f} s")

    doc = {"schema": SCHEMA, "level": level, "ce_folder": folder, "method": audio_match.METHOD,
           "built_at": dt.date.today().isoformat(),
           "mcc_takes": [{"mcc_tag": tag, "english_index": s["index"], "duration_s": s["duration_s"]} for tag, s in mcc],
           "ce_variations": [{"ce_line_ref": ref, "record_id": rid} for rid, ref, _m in ce],
           "pairs": pairs, "failed": sorted(failed, key=lambda x: json.dumps(x, sort_keys=True))}
    p = out_path(root, level, name or folder)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    log(f"wrote {p.relative_to(root).as_posix()}")
    return doc


CHARACTERS = "config/suggest_characters.json"


def character_map(root):
    """The owner's MCC level -> CE Systemic folders map ({} when there is none). Mapped levels are compared only with
    their folders."""
    p = Path(root) / CHARACTERS
    return json.loads(p.read_text(encoding="utf-8"))["levels"] if p.is_file() else {}


def build_mapped(app, jobs=8, log=print):
    """Every mapped level: all its English takes vs only its CE folders -> work/suggest/audio/<level>__MAP.json. The
    level's other comparisons (__ALL, single-folder) are removed: the tab must not mix in other characters."""
    for level, folders in character_map(app.root).items():
        build(app, level, folders, jobs, log, name="MAP")
        for p in (Path(app.root) / OUT_DIR).glob(f"{level}__*.json"):
            if p.name != f"{level}__MAP.json":
                p.unlink()
                log(f"  removed {p.name} (other characters)")


# ------------------------------------------------------------------------------------------- every unmatched sound
_CE = {}  # worker state: CE features sorted by frame count (set by _init)


def _init(ce_items):
    _CE["items"] = ce_items
    _CE["frames"] = [f["frames"] for _ref, _rid, f in ce_items]


def _best_for(job):
    """One MCC take against every CE clip of a comparable length -> (english_index, top pairs)."""
    import bisect
    idx, fa = job
    la = fa["frames"]
    lo = bisect.bisect_left(_CE["frames"], int(la * audio_match.LENGTH_RATIO))
    hi = bisect.bisect_right(_CE["frames"], int(la / audio_match.LENGTH_RATIO) + 1)
    scored = []
    for ref, rid, fb in _CE["items"][lo:hi]:
        score, lag, gain = audio_match.compare(fa, fb)
        if score >= 0.3:
            scored.append({"ce_line_ref": ref, "record_id": rid, "score": score, "gain_db": gain,
                           "lag_ms": int(lag * audio_match.FRAME_S * 1000)})
    scored.sort(key=lambda x: (-x["score"], x["ce_line_ref"]))
    return idx, scored[:TOP]


def _features_temp(root, kind, key, cached_path, decode, keep_wavs):
    """Features from the cache; else decode (decode() -> wav path), measure, and delete a WAV this run created."""
    p = Path(root) / OUT_DIR / "features" / kind / f"{key}.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    existed = cached_path is not None
    wav = decode()
    try:
        return _cached_features(root, kind, key, wav)
    finally:
        if not existed and not keep_wavs:
            Path(wav).unlink(missing_ok=True)


def build_unmatched(app, jobs=8, keep_wavs=False, log=print):
    """Every MCC sound with no match decision (English takes) against every CE English(US) recording of every mission.
    Writes work/suggest/audio/<level>__ALL.json per level (ce_folder "ALL")."""
    import multiprocessing as mp
    root = app.root
    doc, _sha = app._mappings()
    by_slot = {m["slot_id"]: m for m in doc["slots"]}
    own = app._own_tags(doc)
    mapped = character_map(root)  # those levels are compared only with their own CE folders (build_mapped)
    mcc = []
    for level, recs in app.levels.items():
        if level in mapped:
            continue
        for r in recs:
            decided = r["mcc_tag"] in own or any(
                (by_slot.get(s) or {}).get("match", {}).get("status", "unreviewed") != "unreviewed" for s in r["slot_ids"])
            if not decided:
                mcc += [(level, r["mcc_tag"], s) for s in r["samples"]["english"]]
    ce = []
    for mission, recs in app.missions.items():
        for r in recs:
            for e in r["entries"]:
                m = e["media"].get("English(US)") or {}
                if m.get("evidence") == "explicit" and m.get("media"):
                    ce.append((mission, r["record_id"], e["ce_line_ref"], m["media"][0]))
    log(f"{len(mcc)} English takes of unmatched MCC sounds; {len(ce)} CE English recordings (every mission)")
    failed = []

    def mcc_feat(item):
        level, _tag, s = item
        try:
            return _features_temp(root, "mcc", s["data_sha256"], app.mcc_audio.cached(level, "english", s),
                                  lambda: app.mcc_audio.wav(level, "english", s), keep_wavs)
        except (AudioUnavailable, OSError, ValueError) as e:
            failed.append({"side": "mcc", "english_index": s["index"], "error": str(e)})
            return None

    def ce_feat(item):
        mission, _rid, ref, media = item
        try:
            return _features_temp(root, "ce", media["wem_sha256"], app.ce_audio.cached(mission, "English(US)", media),
                                  lambda: app.ce_audio.wav(mission, "English(US)", media), keep_wavs)
        except (AudioUnavailable, OSError, ValueError) as e:
            failed.append({"side": "ce", "ce_line_ref": ref, "error": str(e)})
            return None

    # Several lines can share one recording (same .wem): each recording is decoded and measured once, never by two
    # threads at a time (one would delete the WAV the other is reading).
    t = time.time()
    mcc_first = {s["data_sha256"]: (lv, tag, s) for lv, tag, s in reversed(mcc)}
    ce_first = {media["wem_sha256"]: (m, rid, ref, media) for m, rid, ref, media in reversed(ce)}
    with cf.ThreadPoolExecutor(jobs) as pool:
        mcc_by = dict(zip(mcc_first, pool.map(mcc_feat, mcc_first.values())))
        log(f"MCC measured in {time.time() - t:.0f} s")
        ce_by = dict(zip(ce_first, pool.map(ce_feat, ce_first.values())))
    mf = [mcc_by[s["data_sha256"]] for _lv, _tag, s in mcc]
    cfeat = [ce_by[media["wem_sha256"]] for _m, _rid, _ref, media in ce]
    log(f"CE measured in {time.time() - t:.0f} s ({len(failed)} failed)")

    ce_items = sorted(((ref, rid, f) for (_m, rid, ref, _x), f in zip(ce, cfeat) if f and f["frames"]),
                      key=lambda x: (x[2]["frames"], x[0]))
    work = [(s["index"], f) for (_lv, _tag, s), f in zip(mcc, mf) if f and f["frames"]]
    t = time.time()
    pairs = {}
    with mp.Pool(max(1, (mp.cpu_count() or 2) - 1), initializer=_init, initargs=(ce_items,)) as pool:
        for n, (idx, top) in enumerate(pool.imap_unordered(_best_for, work, chunksize=8), 1):
            pairs[str(idx)] = top
            if n % 500 == 0:
                log(f"  compared {n}/{len(work)} takes ({time.time() - t:.0f} s)")
    log(f"compared in {time.time() - t:.0f} s")

    today = dt.date.today().isoformat()
    written = []
    for level in app.levels:
        takes = [(tag, s) for lv, tag, s in mcc if lv == level]
        if not takes:
            continue
        out = {"schema": SCHEMA, "level": level, "ce_folder": "ALL", "method": audio_match.METHOD, "built_at": today,
               "scope": "MCC sounds with no match decision on the day it ran, against every CE English recording",
               "mcc_takes": [{"mcc_tag": tag, "english_index": s["index"], "duration_s": s["duration_s"]}
                             for tag, s in takes],
               "ce_variations": [], "ce_variation_count": len(ce_items),
               "pairs": {str(s["index"]): pairs.get(str(s["index"]), []) for _tag, s in takes},
               "failed": sorted((x for x in failed if x["side"] == "ce" or
                                 x.get("english_index") in {s["index"] for _t, s in takes}),
                                key=lambda x: json.dumps(x, sort_keys=True))}
        p = out_path(root, level, "ALL")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        written.append(level)
    log(f"wrote {len(written)} files: work/suggest/audio/<level>__ALL.json for {', '.join(written)}")
    return pairs, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", help="MCC level folder, e.g. grunt")
    ap.add_argument("--unmatched-all", action="store_true",
                    help="every MCC sound with no match decision against every CE English recording")
    ap.add_argument("--mapped", action="store_true",
                    help="the levels of config/suggest_characters.json, each only against its own CE folders")
    ap.add_argument("--keep-wavs", action="store_true", help="keep the WAVs this run decodes (default: features only)")
    ap.add_argument("--ce-folder", help="CE Systemic folder (default: the one named like the level)")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--oodle-dll", type=Path)
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    decode = vgmstream_decoder(args.vgmstream_cli)
    app = M4App(args.root, mcc_audio=MccAudio(args.root, decode),
                ce_audio=CeAudio(args.root, decode, ce_source_reader(args.oodle_dll)), run_validator=False)
    if args.mapped:
        build_mapped(app, args.jobs)
        return
    if args.unmatched_all:
        build_unmatched(app, args.jobs, args.keep_wavs)
        return
    if not args.level:
        ap.error("--level or --unmatched-all is required")
    folder = args.ce_folder or app._character_folder(args.level, None)
    if not folder:
        raise SystemExit(f"no CE Systemic folder is named like {args.level}; pass --ce-folder")
    build(app, args.level, folder, args.jobs)


if __name__ == "__main__":
    main()
