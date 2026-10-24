"""Compares the English audio of an MCC level folder with a CE Systemic folder, by sound (docs/suggested-matching.md).

    python scripts/catalog/build_audio_matches.py --level grunt                  # CE folder named like the level
    python scripts/catalog/build_audio_matches.py --level grunt --ce-folder vo_sys_grunt

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


def build(app, level, folder, jobs=8, log=print):
    """-> the result document (also written to work/). app: an M4App with mcc_audio and ce_audio."""
    root = app.root
    if level not in app.levels:
        raise SystemExit(f"unknown level {level}")
    recs = [r for r in app.missions.get("SYS", []) if r.get("folder") == folder]
    if not recs:
        raise SystemExit(f"no CE Systemic records in folder {folder}")
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
    p = out_path(root, level, folder)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    log(f"wrote {p.relative_to(root).as_posix()}")
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", required=True, help="MCC level folder, e.g. grunt")
    ap.add_argument("--ce-folder", help="CE Systemic folder (default: the one named like the level)")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--oodle-dll", type=Path)
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    decode = vgmstream_decoder(args.vgmstream_cli)
    app = M4App(args.root, mcc_audio=MccAudio(args.root, decode),
                ce_audio=CeAudio(args.root, decode, ce_source_reader(args.oodle_dll)), run_validator=False)
    folder = args.ce_folder or app._character_folder(args.level, None)
    if not folder:
        raise SystemExit(f"no CE Systemic folder is named like {args.level}; pass --ce-folder")
    build(app, args.level, folder, args.jobs)


if __name__ == "__main__":
    main()
