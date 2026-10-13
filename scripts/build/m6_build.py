"""M6 batch build: approved M4 decisions -> candidate MCC files (offline only).

Reads the owner's decisions (mappings/manual_mappings.json via mapping_store.load, plus the
git-ignored local file with custom subtitle text), the catalogs under work/, and pinned copies of the
game files. `--kind` chooses what is built for the selected level(s):

  audio      the Spanish dialogue bank: every eligible approved CE audio decision
             (common/m6_build.plan_audio) through the validated pipeline (common/audio_pipeline: CE WAV ->
             ffmpeg 44.1 kHz -> [owner's edit recipe, the same render the M4 editor previews] -> global gain
             -> pad codec delay -> CELT 0.11 "fmod" profile), assembled into ONE new bank from
             reference-audio/stage1/. Untouched samples stay byte-identical; .lst.bin is never written.
  subtitles  SU_Halo1.bin and SP_Halo1.bin from the approved subtitle decisions (common/m6_build.subtitle_plan:
             CE es-MX/EN text, custom text, or an approved empty entry; drafts, needs-rework, drift, conflicts
             and lines without a key are excluded and reported), written by common/mcc_loc_writer (variable
             length) from the pinned copies in work/mcc/loc/copies/. Untouched entries stay byte-identical.
  both       all three files; they are installed and restored together.

Validation (all must pass, else the build is marked FAILED):
  validator clean; bank / table copies = pins; audio: multi-sample structural checks, every subsong decodes
  and only the targets differ, per-target content checks, bank built twice -> identical bytes; subtitles:
  per table, an independent re-parse (header fields, LF slack, 8-byte padding, keys and order, every
  written entry == the approved text, every other entry byte-identical), re-serialisation, the plan made
  from the same baseline, written twice in a different order -> identical bytes.

Outputs (git-ignored) in work/m6/<name>/:
  sounds_dialogs_spanish.fsb and/or SU_Halo1.bin + SP_Halo1.bin, inventory.json, build_manifest.json,
  validation_report.json, test_report.md, install_rollback.md. Derived streams: work/derived/<sha>/.
Never installs anything, never changes or approves a mapping.

Example:
    python scripts/build/m6_build.py --level a10
    python scripts/build/m6_build.py --mission a10 --kind subtitles
    python scripts/build/m6_build.py --mission a10 --kind both --name a10_both
    python scripts/build/m6_build.py --all-mapped     # every folder you have mapped -> work/m6/all_mapped/
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import shutil
import sys
import time
from array import array
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
from common import mapping_store  # noqa: E402
from common import audio_edit, radio_clicks, radio_static  # noqa: E402
from common.audio_pipeline import derive, derive_processed, needs_processing, sha256_file, snr_db  # noqa: E402
from common.export_config import LEVEL_MODES, ConfigError, load_export_config  # noqa: E402
from common.celt011 import DEFAULT_DLL, Celt011  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_lib import parse_header  # noqa: E402
from common.m6_build import (  # noqa: E402
    BUILD_KINDS, FOLDER_GROUPS, SUBTITLE_COPY, SUBTITLE_INSTALL, SUBTITLE_PINS, SUBTITLE_TABLES, assemble, build_tables,
    compare_plans, compare_subtitle_plans, entry_group, folder_summary, mission_folders, multi_structural_checks,
    plan_audio, subtitle_plan)
from common.mcc_loc import parse_mcc_loc  # noqa: E402
from common.mcc_loc_writer import WRITER, TableError, charset  # noqa: E402
from common.ondemand_audio import CeAudio, MccAudio, ce_source_reader, vgmstream_decoder  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_all, decode_pcm, meta, meta_value  # noqa: E402
from m4_app import M4App  # noqa: E402

BANK = REPO_ROOT / "reference-audio" / "stage1" / "fsb" / "sounds_dialogs_spanish.fsb"
LST = REPO_ROOT / "reference-audio" / "stage1" / "lst" / "sounds_dialogs_spanish.lst.bin"
INSTALL_BANK = "halo1/sound/pc/sounds_dialogs_spanish.fsb"
DERIVED = REPO_ROOT / "work" / "derived"
MIN_SNR_DB = 30.0
MANIFEST_SCHEMA = "m6-build-manifest/1"


def run_validator():
    spec = importlib.util.spec_from_file_location("validate_project", REPO_ROOT / "scripts/validate/validate_project.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report, _ = mod.run(REPO_ROOT)
    return report


def inventory(doc, app, progress):
    """Every edited slot, by level and state (all levels; nothing assumed about missions)."""
    per = {}
    for m in doc["slots"]:
        hit = app.slot_index.get(m["slot_id"])
        lv = hit[0] if hit else "unknown"
        c = per.setdefault(lv, Counter())
        c["mappings"] += 1
        c[f"match:{m['match']['status']}"] += 1
        c[f"audio:{m['audio']['status']}:{m['audio']['source']}"] += 1
        c[f"subtitle:{m['subtitle']['status']}:{m['subtitle']['source']}"] += 1
        c["radio_effect"] += bool((m.get("radio_effect") or {}).get("needed"))
        c["different_but_fits"] += bool((m.get("different_but_fits") or {}).get("marked"))
    status = {e["mcc_level"]: e["status"] for e in progress.get("levels", [])}
    return {lv: {"slots_in_level": sum(len(r["slot_ids"]) for r in app.levels.get(lv, [])),
                 "level_status": status.get(lv), **dict(sorted(c.items()))}
            for lv, c in sorted(per.items())}


def content_checks(exe, cand_path, idx, res):
    """vgmstream decode of one target vs the pipeline's own decode and its 44.1 kHz source."""
    wav = decode_pcm(exe, cand_path, idx + 1)
    if wav is None:
        return {"vgm_target_decodes": False}, {}
    pcm = wav[wav.index(b"data") + 8:]
    src_a, dec_a = array("h", res["pcm"]), array("h", pcm)
    n_src = len(src_a)
    snr = snr_db(res["pcm"], pcm)
    after = dec_a[128 + n_src:]
    m = meta(exe, cand_path, idx + 1)
    full = sum(1 for v in dec_a if v in (32767, -32768))
    full_src = sum(1 for v in src_a if v in (32767, -32768))
    checks = {"vgm_target_decodes": True,
              "vgm_equals_own_decode": pcm == res["decoded"][:len(pcm)],
              "content_snr_vs_source_ok": snr >= MIN_SNR_DB,
              "vgm_sample_count": (meta_value(m, "stream total samples") or "").split(" ")[0] == str(res["sample_count"]),
              "vgm_encoding_custom_celt": meta_value(m, "encoding") == "Custom CELT",
              "duration_covers_source_plus_delay": n_src + 128 <= res["sample_count"] < n_src + 128 + 512,
              "no_new_clipping": full <= full_src,
              # after the end only the codec's ring-out of the line's own last frame may remain: below 64 LSB
              # (-54 dBFS), or below half the peak of the source's last 512 samples when the recording itself
              # ends abruptly at a higher level (room tone cut off without a fade)
              "silence_after_source_end": max(map(abs, after), default=0)
              < max(64, max(map(abs, src_a[-512:]), default=0) / 2)}
    return checks, {"content_snr_db": round(snr, 1) if math.isfinite(snr) else str(snr)}


SPAIN_LUFS_CACHE = REPO_ROOT / "work" / "m6" / "_cache" / "spain_lufs.json"


def spain_references(targets, app, decoder):
    """{slot_id: LUFS of the Spain recording the line replaces} (BS.1770, audio_edit.loudness), from the same
    on-demand decode the M4 preview measures. Cached by the sample's data hash (work/m6/_cache/)."""
    cache = {}
    if SPAIN_LUFS_CACHE.is_file():
        c = json.loads(SPAIN_LUFS_CACHE.read_text(encoding="utf-8"))
        if c.get("method") == audio_edit.RENDER_ENGINE:
            cache = c["values"]
    mcc = MccAudio(REPO_ROOT, decoder)
    out = {}
    for e in targets:
        level, _rec, sample = app.slot_index[e["slot_id"]]
        k = sample["data_sha256"]
        if k not in cache:
            cache[k] = audio_edit.wav_loudness(mcc.wav(level, "spanish", sample))
        out[e["slot_id"]] = cache[k]
    SPAIN_LUFS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SPAIN_LUFS_CACHE.write_text(json.dumps({"method": audio_edit.RENDER_ENGINE, "values": cache}), encoding="utf-8")
    return out


def level_summary(cfg, slots):
    """The manifest's `level` block: the settings the build used and what they did, line by line."""
    rep = [e for e in slots if e["action"] == "replace"]
    st_ = [(e, e.get("audio_stats") or {}) for e in rep]
    gains = sorted(s.get("total_gain_db", 0.0) or 0.0 for _, s in st_)
    vs = sorted(s["output_lufs"] - s["mcc_reference_lufs"] for _, s in st_
                if s.get("output_lufs") is not None and s.get("mcc_reference_lufs") is not None)
    lim = sorted(((s.get("match") or {}).get("limiter_max_reduction_db") or 0.0) for _, s in st_ if s.get("match"))

    def dist(v):
        return {"min": v[0], "median": v[len(v) // 2], "max": v[-1], "p10": v[len(v) // 10],
                "p90": v[9 * len(v) // 10]} if v else None
    return {"mode": cfg["level_mode"], "global_gain_db": cfg["global_gain_db"], "source": cfg["source"],
            "config_sha256": cfg["sha256"], "peak_ceiling_dbfs": audio_edit.PEAK_CEILING_DB,
            "match_max_limiting_db": audio_edit.MATCH_MAX_LIMITING_DB, "lines": len(rep),
            "effective_gain_db": dist([round(g, 2) for g in gains]),
            "constrained": [e["slot_id"] for e, s in st_ if (s.get("global_gain_shortfall_db") or 0) > 0
                            or ((s.get("match") or {}).get("shortfall_db") or 0) > 0],
            "fallback_to_global_gain": [e["slot_id"] for e, s in st_ if s.get("level_mode_used") not in
                                        (None, cfg["level_mode"])],
            "limiter_max_reduction_db": dist(lim),
            "loudness_vs_spain_db": dist([round(v, 2) for v in vs])}


def build_once(original, targets, ce_audio, ffmpeg, celt, cfg, refs=None, clicks=None, static=None):
    """Encode every target and assemble the bank. -> (candidate bytes, {index: derive result}).
    cfg: the export config (level mode and global gain, the same for every replacement); refs: Spain
    loudness per slot (the match target, or reported only); clicks: MCC's radio clicks
    (common/radio_clicks.py), required when a recipe has radio clicks on."""
    results = {}
    gain, mode = cfg["global_gain_db"], cfg["level_mode"]
    refs = refs or {}
    for e in targets:
        wav = ce_audio.wav(e["ce_mission"], e["language"], e["media"])
        meta = {"ce_line_ref": e["ce_line_ref"], "language": e["language"],
                "media_id": e["media"]["media_id"], "wem_sha256": e["media"]["wem_sha256"]}
        edit = e.get("edit") or audio_edit.EDIT_ZERO
        if needs_processing(edit, gain, mode):
            try:
                res = derive_processed(wav, edit, ffmpeg=ffmpeg, celt=celt, out_root=DERIVED,
                                       ref_lufs=refs.get(e["slot_id"]), global_gain_db=gain, level_mode=mode,
                                       profile="fmod", gain_source=cfg["source"], source_meta=meta,
                                       clicks=clicks, static=static)
            except audio_edit.EditError as ex:
                raise SystemExit(f"{e['slot_id']}: audio cannot be processed: {ex}")
        else:  # unedited, global_gain mode with no gain: the original path, byte for byte
            res = derive(wav, ffmpeg=ffmpeg, celt=celt, out_root=DERIVED, channels=1, profile="fmod",
                         source_meta=meta)
        res["wav"], res["wav_sha256"] = wav, sha256_file(wav)
        results[e["spanish_index"]] = res
    cand = assemble(original, {k: (r["stream"], r["sample_count"]) for k, r in results.items()})
    return cand, results


def decode_hashes_cached(exe, path, count, cache_file, key):
    if cache_file.is_file():
        c = json.loads(cache_file.read_text(encoding="utf-8"))
        if c.get("key") == key and len(c.get("hashes", [])) == count:
            return c["hashes"]
    hashes = decode_all(exe, path, count)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"key": key, "hashes": hashes}), encoding="utf-8")
    return hashes


def md_table(rows, cols):
    out = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(f(r)).replace("|", "\\|") for _, f in cols) + " |")
    return out


KIND_TEXT = {"audio": "**Audio only**: the Spanish dialogue bank; subtitle tables are not changed",
             "subtitles": "**Subtitles only**: `SU_Halo1.bin` and `SP_Halo1.bin`; the dialogue audio is not changed",
             "both": "**Audio and subtitles**: the Spanish dialogue bank plus `SU_Halo1.bin` and `SP_Halo1.bin`, "
                     "installed and restored together"}


def short(text, n=70):
    text = (text or "").replace("\n", " ⏎ ")
    return text if len(text) <= n else text[:n - 1] + "…"


def subtitle_section(manifest):
    s = manifest["subtitles"]
    sm = s["summary"]
    if not s.get("enabled"):
        return ["## Subtitles", "",
                f"**No subtitle changes in this build.** {sm['approved_text_changes']} approved subtitle decision(s) "
                f"in scope would change text ({sm['keys_to_write']} entr(ies)). Build *subtitles* or *both* to "
                "write them. In game you will see MCC's original subtitles, which may not match the new audio.", ""]
    L = ["## Subtitles", "",
         f"{sm['approved_subtitles']} approved subtitle decision(s) in scope. Written: SU {sm['keys_written']['SU']}, "
         f"SP {sm['keys_written']['SP']} entr(ies) (variable length SU {sm['variable_length']['SU']}, SP "
         f"{sm['variable_length']['SP']}; empty \"no subtitle\" entries {sm['empty_entries']}). Every other entry "
         "is byte for byte the original. Both tables get the same LATAM text; keys are looked up in each "
         "table separately.", ""]
    L += md_table([{"t": t, **v} for t, v in s["tables"].items()],
                  [("Table", lambda r: r["t"]), ("Entries", lambda r: r["entries"]),
                   ("Written", lambda r: r["entries_written"]),
                   ("Same text as before", lambda r: r["entries_identical_to_before"]),
                   ("Size", lambda r: f"{r['size_before']:,} → {r['size_after']:,} B")])
    written = [k for k in s["keys"] if k["action"] == "write"]
    L += ["", f"### Entries written ({len(written)})", ""]
    L += md_table(written, [("Key", lambda k: f"`{k['key_hex']}`"), ("Line", lambda k: f"`{k['mcc_tag'].split(chr(92))[-1]}`"),
                            ("Before (SU)", lambda k: short(k["tables"]["SU"].get("old_text"))),
                            ("After", lambda k: short(k["text"]) or "*(no subtitle)*")])
    excluded = [r for r in s["rows"] if r["category"] in ("excluded", "conflict", "missing_key")]
    L += ["", f"### Excluded ({len(excluded)}): these lines keep MCC's subtitle", ""]
    L += md_table(excluded, [("Slot", lambda r: f"`{r['slot_id']}`"), ("Status", lambda r: r["status"]),
                             ("Why", lambda r: r["result"])]) if excluded else ["- none"]
    L += ["", f"### Conflicts ({len(s['conflicts'])})", ""]
    L += [f"- `{c['key_hex']}` `{c['mcc_tag']}`: {c['code'].replace('_', ' ')} ({', '.join(c['slots'])}); left "
          "unchanged" for c in s["conflicts"]] or ["- none"]
    for w in s.get("warnings", []):
        L += ["", f"**Warning:** {w}"]
    return L + [""]


def test_report(name, manifest, report, app):
    kind = manifest.get("kind", "audio")
    audio = kind in ("audio", "both")
    ents = manifest["slots"]
    rep = [e for e in ents if e["action"] == "replace"]
    keep = [e for e in ents if e["action"] != "replace"]
    su = lambda e: (app._mcc_text(e["mcc_tag"])["SU"]["text"] or "")[:70]  # noqa: E731
    L = [f"# M6 test build `{name}` — {'PASS' if report['ok'] else 'FAILED'}", "",
         f"Built {manifest['built_at']} from `manual_mappings.json` sha256 `{manifest['inputs']['mappings_sha256'][:16]}…` "
         f"for level(s) {', '.join(manifest['levels'])}. {KIND_TEXT[kind]}. Local test only; nothing is installed "
         "until the owner approves.", "", "## Output files", ""]
    L += md_table(manifest["install_files"], [("Install path", lambda f: f"`{f['install_rel']}`"),
                                               ("Candidate", lambda f: f"`{f['candidate']}`"),
                                               ("Candidate SHA-256", lambda f: f"`{f['candidate_sha256']}`"),
                                               ("Original (pinned) SHA-256", lambda f: f"`{f['original_sha256']}`")])
    L += ["", "Unchanged and never written: " + ", ".join(f"`{p}`" for p in manifest["not_written"])
          + ", and every other game file.", ""]
    if audio:
        L += [f"## 1. Lines that will play in LATAM Spanish ({len(rep)})", ""]
        L += md_table(rep, [("Slot", lambda e: f"`{e['slot_id']}`"), ("CE line", lambda e: f"`{e['ce_line_ref']}`"),
                            ("Spain s", lambda e: e["original_seconds"]), ("LATAM s", lambda e: e["new_seconds"]),
                            ("Flags", lambda e: " ".join(x for x, on in (("R", e["radio_effect"]),
                                                                         ("≈", e["different_but_fits"]),
                                                                         ("E", bool(e.get("edit")))) if on)),
                            ("MCC LATAM subtitle (SU) before", su)])
        L += ["", "## Per folder", ""]
        L += md_table([{"f": f, **v} for f, v in manifest["folders"].items()],
                      [("Folder", lambda r: f"`{r['f']}`"), ("Slots", lambda r: r["slots"]),
                       ("LATAM (approved CE)", lambda r: r["replace"]),
                       ("Approved keep Spain", lambda r: r["approved_keep_spain"]),
                       ("Not approved", lambda r: r["not_approved"]), ("Unmapped", lambda r: r["unmapped"]),
                       ("Unsupported", lambda r: r["unsupported"]), ("Invalid", lambda r: r["invalid"]),
                       ("Stereo (replaced)", lambda r: f"{r['stereo']} ({r['stereo_replaced']})")])
    a = manifest.get("mission_association")
    if a:
        L += ["", f"Mission `{a['mission']}`: folders {', '.join(f'`{x}`' for x in a['selected'])} "
                  f"(cinematics only this map uses; evidence {a['evidence']}). Shared bark folders not touched: "
                  f"{', '.join(a['shared_not_selected'])}."]
    if audio:
        L += ["", f"## 2. Lines that keep their Spain Spanish audio ({len(keep)})", ""]
        for f in manifest["folders"]:
            fk = [e for e in keep if e["level"] == f]
            if fk:
                L += [f"**`{f}`** ({len(fk)}):", ""] + [f"- {n} × {g.replace('_', ' ')}: " + ", ".join(
                    f"`{e['slot_id']}`" for e in fk if entry_group(e) == g)
                    for g, n in Counter(entry_group(e) for e in fk).most_common()] + [""]
        reasons = Counter(e["reason"] for e in keep)
        L += ["All reasons:", ""] + [f"- {n} × {r}" for r, n in reasons.most_common()]
        odd = [e for e in keep if e["action"] == "not_eligible" or (e["mapping_id"] and e["reason"].startswith("audio "))]
        if odd:
            L += ["", "Mapped but not built:", ""]
            L += md_table(odd, [("Slot", lambda e: f"`{e['slot_id']}`"), ("Why", lambda e: e["reason"])])
        edited = [e for e in rep if e.get("edit")]
        L += ["", f"### Edited lines ({len(edited)}): the owner's recipes, rendered exactly as the M4 preview", ""]
        L += md_table(edited, [("Slot", lambda e: f"`{e['slot_id']}`"), ("Recipe", lambda e: e["edit_summary"]),
                               ("Source s", lambda e: e["audio_stats"]["source_s"]),
                               ("Edited s", lambda e: e["audio_stats"]["output_s"]),
                               ("LUFS out", lambda e: e["audio_stats"]["output_lufs"])]) if edited \
            else ["- none"]
        g = manifest["global_gain"]
        lv = manifest.get("level") or {}
        shortfall = [e for e in rep if (e.get("audio_stats") or {}).get("global_gain_shortfall_db")]
        if lv.get("mode") == "match_spain":
            vs, lim, eg = lv["loudness_vs_spain_db"], lv["limiter_max_reduction_db"], lv["effective_gain_db"]
            L += ["", "### Level: matched to the Spain recordings (build-level mode)", "",
                  f"Each line gets the gain that brings it to the loudness of the Spain recording it replaces "
                  f"(median {eg['median']:+.1f} dB, from {eg['min']:+.1f} to {eg['max']:+.1f}). A look-ahead limiter "
                  f"keeps peaks at {audio_edit.PEAK_CEILING_DB:g} dBFS and takes at most "
                  f"{lv['match_max_limiting_db']:g} dB off any peak (median {lim['median']:.1f}, max {lim['max']:.1f} dB). "
                  f"**{len(lv['constrained'])} line(s)** got less than their match because of that cap; "
                  f"{len(lv['fallback_to_global_gain'])} fell back to the global gain. Result vs Spain: median "
                  f"{vs['median']:+.1f} dB (p10 {vs['p10']:+.1f}, p90 {vs['p90']:+.1f}). The global gain "
                  f"({g['configured_db']:+g} dB) is not used in this mode.", ""]
            short_m = [e for e in rep if ((e.get("audio_stats") or {}).get("match") or {}).get("shortfall_db")]
            if short_m:
                L += md_table(short_m, [("Slot", lambda e: f"`{e['slot_id']}`"),
                                        ("Wanted dB", lambda e: e["audio_stats"]["match"]["requested_db"]),
                                        ("Applied dB", lambda e: e["audio_stats"]["match"]["applied_db"]),
                                        ("Limiter dB", lambda e: e["audio_stats"]["match"]["limiter_max_reduction_db"])])
        else:
            vs = lv.get("loudness_vs_spain_db")
            L += ["", f"### Global gain: {g['configured_db']:+g} dB ({g['source']}), applied once to every replacement", "",
                  f"Applied in full to {g['full']} line(s); **{len(shortfall)} line(s) got less** because their peak would "
                  f"pass {audio_edit.PEAK_CEILING_DB:g} dBFS (no limiting or compression is used for the global gain)."
                  + (f" Result vs the Spain recordings: median {vs['median']:+.1f} dB (p10 {vs['p10']:+.1f}, p90 "
                     f"{vs['p90']:+.1f})." if vs else ""), ""]
        if shortfall:
            L += md_table(shortfall, [("Slot", lambda e: f"`{e['slot_id']}`"),
                                      ("Applied dB", lambda e: e["audio_stats"]["global_gain_applied_db"]),
                                      ("Short dB", lambda e: e["audio_stats"]["global_gain_shortfall_db"]),
                                      ("Peak before", lambda e: f"{round(e['audio_stats']['output_peak_dbfs'] - e['audio_stats']['global_gain_applied_db'], 2)} dBFS")])
        radio = [e for e in rep if e["radio_effect"]]
        L += ["", f"## 3. Needs Radio Effect ({len(radio)}): recorded in the manifest, **no effect applied**", ""]
        L += [f"- `{e['slot_id']}` ← `{e['ce_line_ref']}`" for e in radio] or ["- none"]
        fits = [e for e in rep if e["different_but_fits"]]
        L += ["", f"Marked “different dialogue, but fits the scene” ({len(fits)}): "
                  + (", ".join(f"`{e['slot_id']}`" for e in fits) or "none"), ""]
    L += subtitle_section(manifest)
    L += ["## Known limitations", ""]
    if audio:
        L += ["- Radio effects not applied (v1.1); flagged lines play the clean CE recording.",
              "- Not built: stereo slots, concatenations (`ce_concat`), user recordings. Edited lines (flag E) are "
              "built from their recipes.",
              (f"- Level matched to each Spain recording, limiting capped at "
               f"{audio_edit.MATCH_MAX_LIMITING_DB:g} dB (lines listed under “Level” got less)."
               if (manifest.get("level") or {}).get("mode") == "match_spain" else
               f"- Global export gain {manifest['global_gain']['configured_db']:+g} dB on every replacement "
               "(lines listed under “Global gain” got less, to avoid clipping)."),
              "- Durations differ from the Spain recordings; MCC proved it plays longer/shorter samples (E1b, E3), "
              "but timing against cutscenes/scripts is part of this test."]
    if manifest["subtitles"].get("enabled"):
        L += ["- **Subtitle tables of a different size have not been loaded by MCC yet** (only same-length edits "
              "were verified in game, B1). This build is validated offline only; the in-game check below is the "
              "runtime verification.",
              "- Empty (\"no subtitle\") entries: what MCC shows for an empty entry is unverified.",
              "- Lines without an entry in SU/SP get none (keys are never added)."]
    else:
        L += ["- Subtitle tables not changed: in game you will see MCC's original subtitles."]
    L += ["", "## In-game checklist", "",
          "Settings: Halo CE, primary language **Spanish (Latin America)**, fallback **Spanish (Spain)**, subtitles on.",
          "Launch with **Play Halo: MCC Anti-Cheat Disabled**. Test Classic graphics, then Anniversary.", "",
          "1. The game starts and loads each mission in this build without a crash or hang; cinematics play through."]
    if audio:
        L += ["2. Replaced lines play in LATAM Spanish, completely (no cut-off start or end, no clicks, normal volume).",
              "3. The next line starts normally after a longer or shorter replacement (no overlap, no long silence).",
              "4. Lines that keep Spain audio still play the original recording."]
    if manifest["subtitles"].get("enabled"):
        L += ["5. Written subtitles show the new text in full, with accents, ¿ ¡ ñ and line breaks intact; a long one "
              "is not cut off. Note one shorter and one longer line.",
              "6. Lines that were not written still show MCC's text, unchanged (pick one before and one after a "
              "written line).",
              "7. The menus and other text (pause menu, settings) still read correctly."]
    else:
        L += ["5. Subtitles are MCC's originals (expected in this build)."]
    L += ["8. Note anything wrong: slot id or the moment in the mission.",
          "9. Close MCC completely before restoring (also after a crash).", ""]
    return "\n".join(L)


def install_sheet(name, manifest):
    files = "\n".join(f"- `{f['install_rel']}`: original `{f['original_sha256'][:16]}…` -> candidate "
                      f"`{f['candidate_sha256'][:16]}…`" for f in manifest["install_files"])
    return "\n".join([
        f"# M6 `{name}`: install and rollback (LOCAL TEST ONLY; NEEDS THE OWNER'S EXPLICIT APPROVAL)", "",
        f"{KIND_TEXT[manifest.get('kind', 'audio')]}. Replaces {len(manifest['install_files'])} file(s), together:", "",
        files, "",
        "Use Build & Test in the Studio, or:", "",
        "```powershell",
        f"python scripts/build/m6_install.py --build {name} check       # read-only: MCC closed, build, hashes",
        f"python scripts/build/m6_install.py --build {name} preflight   # backups outside the install + verify, snapshot",
        f"python scripts/build/m6_install.py --build {name} install     # copy the candidates, verify (all or nothing)",
        "# Steam > Halo MCC > Play > \"Play Halo: MCC Anti-Cheat Disabled\"; test (test_report.md); CLOSE MCC",
        f"python scripts/build/m6_install.py --build {name} rollback    # restore + verify + compare snapshot",
        f"python scripts/build/m6_install.py --build {name} status",
        "```", "",
        "Every step refuses to run while MCC/EAC is open and stops on any hash mismatch. Any failure during install "
        "restores every original. If rollback fails, use Steam > Properties > Installed Files > Verify integrity "
        "of game files.", ""])


def read_local(path):
    """The git-ignored custom-text file (custom subtitles) and the SHA-256 of its bytes (None if absent)."""
    if not path.is_file():
        return None, None
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def build_audio(out, targets, original, args, cfg, pins, app):
    """The audio stage: encode, assemble, validate the bank. -> (checks, results, per_target, report extras)."""
    checks = {"bank_copy_matches_pin": hashlib.sha256(original).hexdigest() == pins["spanish.fsb"]["sha256"],
              "lst_copy_matches_pin": sha256_file(LST) == pins["spanish.lst"]["sha256"]}
    if not checks["bank_copy_matches_pin"]:
        raise SystemExit("Spanish bank copy does not match its pin")
    exe = args.vgmstream_cli
    ce_audio = CeAudio(REPO_ROOT, vgmstream_decoder(exe), ce_source_reader(args.oodle_dll))
    print(f"measuring the loudness of the {len(targets)} Spain recording(s) being replaced...")
    refs = spain_references(targets, app, vgmstream_decoder(exe))
    checks["spain_references_measured"] = sum(v is not None for v in refs.values()) == len(targets) \
        or cfg["level_mode"] != "match_spain"
    clicks = None
    if any(((e.get("edit") or {}).get("radio") or {}).get("clicks") for e in targets):
        try:
            clicks = radio_clicks.load(MccAudio(REPO_ROOT, vgmstream_decoder(exe)), app.slot_index)
        except Exception as ex:  # noqa: BLE001 (decode failure or pin mismatch: the build stops)
            raise SystemExit(f"radio clicks unavailable: {ex}")
        checks["radio_clicks_match_pins"] = clicks["sha256"] == radio_clicks.PINNED
    static = None
    if any((e.get("edit") or {}).get("interference") for e in targets):
        try:
            static = radio_static.load(MccAudio(REPO_ROOT, vgmstream_decoder(exe)), app.slot_index)
        except Exception as ex:  # noqa: BLE001 (decode failure or pin mismatch: the build stops)
            raise SystemExit(f"radio static unavailable: {ex}")
        checks["radio_static_matches_pin"] = static["sha256"] == radio_static.PINNED
    celt = Celt011()
    n_edit = sum(1 for e in targets if e.get("edit"))
    print(f"encoding {len(targets)} line(s), {n_edit} with edit recipes (pass 1)...")
    cand, results = build_once(original, targets, ce_audio, args.ffmpeg, celt, cfg, refs, clicks, static)
    print("encoding again (pass 2, determinism)...")
    cand2, results2 = build_once(original, targets, ce_audio, args.ffmpeg, celt, cfg, refs, clicks, static)
    celt.close()
    checks["deterministic_streams"] = all(results[k]["stream"] == results2[k]["stream"] for k in results)
    checks["deterministic_bank"] = cand == cand2
    del cand2, results2
    cand_path = out / "sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(cand)
    checks.update(multi_structural_checks(original, cand, {k: (r["stream"], r["sample_count"])
                                                           for k, r in results.items()}))
    count = parse_header(original)["num_samples"]
    print(f"decoding all {count} subsongs of the original (cached) and the candidate...")
    vkey = f"{pins['spanish.fsb']['sha256']}:{sha256_file(exe)}"
    full_o = decode_hashes_cached(exe, BANK, count, REPO_ROOT / "work/m6/_cache/original_decode.json", vkey)
    full_c = decode_all(exe, cand_path, count)
    differ = sorted(k for k, (a, b) in enumerate(zip(full_o, full_c)) if a != b)
    checks["vgm_all_subsongs_decode"] = None not in full_o and None not in full_c and len(full_c) == count
    checks["vgm_only_targets_differ"] = differ == sorted(results)
    per_target, all_target_ok = {}, True
    for e in targets:
        k = e["spanish_index"]
        c, extra = content_checks(exe, cand_path, k, results[k])
        per_target[e["slot_id"]] = {"checks": c, **extra}
        all_target_ok &= all(c.values())
    checks["every_target_content_ok"] = all_target_ok
    checks["lst_not_written"] = sha256_file(LST) == pins["spanish.lst"]["sha256"]
    install = {"install_rel": INSTALL_BANK, "original_sha256": pins["spanish.fsb"]["sha256"],
               "candidate": cand_path.relative_to(REPO_ROOT).as_posix(), "candidate_sha256": hashlib.sha256(cand).hexdigest(),
               "size": len(cand), "growth_bytes": len(cand) - len(original)}
    return checks, results, per_target, {"differing_subsongs": [k + 1 for k in differ]}, install


def build_subtitles(out, subs):
    """The subtitle stage: SU and SP from the plan, from the pinned copies. -> (checks, install files, tables)."""
    originals = {}
    checks = {}
    for t in SUBTITLE_TABLES:
        src = REPO_ROOT / SUBTITLE_COPY.format(table=t)
        originals[t] = src.read_bytes()
        checks[f"{t}:copy_matches_pin"] = hashlib.sha256(originals[t]).hexdigest() == SUBTITLE_PINS[t]
        if not checks[f"{t}:copy_matches_pin"]:
            raise SystemExit(f"{src.relative_to(REPO_ROOT)} does not match its pin; refusing to build from it")
    try:
        built = build_tables(originals, subs)
    except TableError as e:
        raise SystemExit(f"subtitle tables cannot be written: {e}")
    known = charset([parse_mcc_loc(b) for b in originals.values()]
                    + [parse_mcc_loc((REPO_ROOT / SUBTITLE_COPY.format(table="EN")).read_bytes())])
    files, tables = [], {}
    for t, (cand, info, c) in built.items():
        path = out / f"{t}_Halo1.bin"
        path.write_bytes(cand)
        sha = hashlib.sha256(cand).hexdigest()
        c["file_on_disk_verified"] = sha256_file(path) == sha
        checks.update({f"{t}:{k}": v for k, v in c.items()})
        files.append({"install_rel": SUBTITLE_INSTALL.format(table=t), "original_sha256": SUBTITLE_PINS[t],
                      "candidate": path.relative_to(REPO_ROOT).as_posix(), "candidate_sha256": sha,
                      "size": len(cand), "growth_bytes": len(cand) - len(originals[t])})
        tables[t] = {"candidate": path.relative_to(REPO_ROOT).as_posix(), "candidate_sha256": sha,
                     "original_sha256": SUBTITLE_PINS[t], "entries": info["entries"],
                     "entries_written": len(info["changed"]),
                     "entries_identical_to_before": sum(1 for x in info["changed"].values() if x["unchanged"]),
                     "size_before": info["size_before"], "size_after": info["size_after"]}
    new_chars = sorted({ch for k in subs["keys"] if k["action"] == "write" for ch in k["text"]} - known)
    warnings = ([f"characters not used anywhere in MCC's SU/SP/EN tables (the game font may lack them): "
                 + " ".join(f"{ch} U+{ord(ch):04X}" for ch in new_chars)] if new_chars else [])
    return checks, files, tables, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", action="append", help="MCC dialogue folder(s) to build (default a10)")
    ap.add_argument("--mission", help="playable map (e.g. a10): its own folder plus the cinematic folders only "
                                      "it uses, from work/mcc/level_folders.json (build_level_folders.py)")
    ap.add_argument("--all-mapped", action="store_true",
                    help="every MCC folder with at least one mapping (levels, cutscenes, generic barks); "
                         "build folder work/m6/all_mapped/")
    ap.add_argument("--kind", choices=BUILD_KINDS, default="audio",
                    help="audio: the Spanish bank; subtitles: SU_Halo1.bin + SP_Halo1.bin; both: all three files, "
                         "installed and restored together")
    ap.add_argument("--name", help="build folder under work/m6/ (default: the levels joined by '_')")
    ap.add_argument("--inventory-only", action="store_true", help="report mappings and eligibility, build nothing")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    ap.add_argument("--oodle-dll", type=Path)
    ap.add_argument("--level-mode", choices=LEVEL_MODES,
                    help="override config/audio_export.json level_mode for this build (recorded in the manifest)")
    ap.add_argument("--global-gain", type=float, metavar="DB",
                    help="override config/audio_export.json global_gain_db for this build (recorded in the manifest)")
    args = ap.parse_args()
    want_audio, want_subs = args.kind in ("audio", "both"), args.kind in ("subtitles", "both")
    association = None
    if args.mission:
        lf = json.loads((REPO_ROOT / "work/mcc/level_folders.json").read_text(encoding="utf-8"))
        association = {"mission": args.mission.lower(), **mission_folders(lf, args.mission.lower())}
        print(f"mission {args.mission}: folders {association['selected']} ({association['evidence']}); "
              f"shared, not selected: {association['shared_not_selected']}")
    mapped = []
    if args.all_mapped:  # every folder holding at least one of the owner's mappings (any state)
        app0 = M4App(REPO_ROOT, run_validator=False)
        doc0, _ = mapping_store.load(REPO_ROOT / "mappings" / "manual_mappings.json")
        mapped = sorted({app0.slot_index[s["slot_id"]][0] for s in doc0["slots"] if s["slot_id"] in app0.slot_index})
        print(f"all mapped folders ({len(mapped)}): {', '.join(mapped)}")
    levels = sorted({lv.lower() for lv in (args.level or [])} | set((association or {}).get("selected", []))
                    | set(mapped) or {"a10"})
    if args.all_mapped and not args.level and not association:
        name = args.name or "all_mapped"
    else:
        name = args.name or (f"mission_{association['mission']}" if association and not args.level else "_".join(levels))
    out = REPO_ROOT / "work" / "m6" / name
    t0 = time.time()

    val = run_validator()
    errors = [f for f in val["findings"] if f["severity"] == "error"]
    if errors:
        raise SystemExit(f"validator reports {len(errors)} error(s); fix them first: {errors[:3]}")
    doc, msha = mapping_store.load(REPO_ROOT / "mappings" / "manual_mappings.json")
    local_p = REPO_ROOT / "mappings" / "manual_mappings.local.json"
    local, local_sha = read_local(local_p)
    prog_p = REPO_ROOT / "mappings" / "mission_progress.json"
    progress = json.loads(prog_p.read_text(encoding="utf-8")) if prog_p.is_file() else {"levels": []}
    app = M4App(REPO_ROOT, run_validator=False)
    unknown = [lv for lv in levels if lv not in app.levels]
    if unknown:
        raise SystemExit(f"unknown level(s) {unknown}")
    idx = dict(slot_index=app.slot_index, ce_lines=app.ce_lines, ce_idx=app.ce_idx, mcc_idx=app.mcc_idx)
    inv = inventory(doc, app, progress)
    plan = plan_audio(doc, levels, local=local, **idx)
    subs = subtitle_plan(doc, set(levels), local=local, tables={t: app.loc.get(t) for t in SUBTITLE_TABLES}, **idx)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps({"schema": "m6-inventory/1", "mappings_sha256": msha,
                                                    "levels": inv}, indent=2) + "\n", encoding="utf-8")
    acts = Counter(e["action"] for e in plan["entries"])
    ss = subs["summary"]
    print(f"build kind: {args.kind}")
    print(f"mappings {len(doc['slots'])} in {len(inv)} level(s): " +
          ", ".join(f"{lv} {v['mappings']}" for lv, v in inv.items()))
    for f, v in folder_summary(plan["entries"]).items():
        print(f"  {f}: " + ", ".join(f"{g} {v[g]}" for g in FOLDER_GROUPS if v[g]) +
              f" (slots {v['slots']}, stereo {v['stereo']}, stereo replaced {v['stereo_replaced']})")
    print(f"plan {', '.join(levels)}: audio {acts.get('replace', 0)} replace, {acts.get('keep_original', 0)} keep Spain, "
          f"{acts.get('not_eligible', 0)} not eligible; audio conflicts {len(plan['conflicts'])}")
    print(f"subtitles: {ss['approved_subtitles']} approved decision(s) in scope; {ss['keys_to_write']} entr(ies) to "
          f"write (SU {ss['keys_written']['SU']}, SP {ss['keys_written']['SP']}; variable length SU "
          f"{ss['variable_length']['SU']}, SP {ss['variable_length']['SP']}); excluded {ss['excluded']} "
          f"({', '.join(f'{k} {v}' for k, v in ss['rows'].items())}); conflicts {ss['conflicts']}")
    for c in subs["conflicts"]:
        print(f"  subtitle conflict {c['key_hex']} {c['mcc_tag']}: {c['code']} ({', '.join(c['slots'])}); left unchanged")
    if args.inventory_only:
        return 0
    if want_audio and plan["conflicts"]:
        raise SystemExit(f"conflicts: {plan['conflicts']}")
    targets = [e for e in plan["entries"] if e["action"] == "replace"]
    if want_audio and not targets:
        raise SystemExit("nothing eligible to build: no approved Campaign Evolved audio in this scope")
    if want_subs and not ss["keys_to_write"]:
        raise SystemExit("nothing eligible to build: no approved subtitle text in this scope")
    if want_audio and not args.ffmpeg:
        raise SystemExit("ffmpeg not found")
    try:
        cfg = load_export_config(REPO_ROOT)
    except ConfigError as e:
        raise SystemExit(str(e))
    if args.level_mode or args.global_gain is not None:  # a one-off build setting, not saved
        cfg = dict(cfg, source="command line (" + ", ".join(
            x for x in (args.level_mode and f"--level-mode {args.level_mode}",
                        args.global_gain is not None and f"--global-gain {args.global_gain:g}") if x) + ")",
                   level_mode=args.level_mode or cfg["level_mode"],
                   global_gain_db=cfg["global_gain_db"] if args.global_gain is None else args.global_gain)
    if want_audio:
        print(f"level: {cfg['level_mode']}" + (f", global gain {cfg['global_gain_db']:+g} dB"
                                               if cfg["level_mode"] == "global_gain" else
                                               f" (limiting capped at {audio_edit.MATCH_MAX_LIMITING_DB:g} dB; "
                                               "global gain not used)") + f" ({cfg['source']})")

    pins = json.loads((REPO_ROOT / "work/mcc/build.json").read_text(encoding="utf-8"))["files"]
    checks = {"validator_clean": True}
    install_files, results, per_target, audio_extra = [], {}, {}, {"differing_subsongs": []}
    original = None
    if want_audio:
        original = BANK.read_bytes()
        a_checks, results, per_target, audio_extra, bank_file = build_audio(out, targets, original, args, cfg, pins,
                                                                            app)
        checks.update(a_checks)
        install_files.append(bank_file)
    sub_tables, sub_warnings = {}, []
    if want_subs:
        print(f"writing SU and SP ({ss['keys_to_write']} entr(ies) each at most) from the pinned copies...")
        s_checks, s_files, sub_tables, sub_warnings = build_subtitles(out, subs)
        checks.update(s_checks)
        install_files += s_files
    # The owner may keep saving in M4 (e.g. other levels) while this runs: the build is consistent with the
    # snapshot it read; later edits are reported, and m6_install.py refuses to install a build whose lines
    # are no longer the approved decisions.
    doc_after, msha_after = mapping_store.load(REPO_ROOT / "mappings" / "manual_mappings.json")
    local_after, local_sha_after = read_local(local_p)
    drift_during = compare_plans(plan["entries"] if want_audio else [],
                                 plan_audio(doc_after, levels, local=local_after, **idx)["entries"]) \
        if want_audio else {"changed_or_revoked": [], "newly_eligible": []}
    if want_subs:
        sub_after = subtitle_plan(doc_after, set(levels), local=local_after,
                                  tables={t: app.loc.get(t) for t in SUBTITLE_TABLES}, **idx)
        sd = compare_subtitle_plans(subs, sub_after)
        drift_during = {k: drift_during[k] + sd[k] for k in drift_during}
    ok = all(checks.values())

    for e in plan["entries"]:
        if want_audio and e["action"] == "replace":
            r = results[e["spanish_index"]]
            e.update(new_sample_count=r["sample_count"], new_seconds=round(r["sample_count"] / 44100, 3),
                     source_wav=r["wav"].relative_to(REPO_ROOT).as_posix(), source_wav_sha256=r["wav_sha256"],
                     stream_sha256=r["recipe"]["output"]["stream_sha256"],
                     derived_dir=r["dir"].relative_to(REPO_ROOT).as_posix(),
                     content_snr_db=per_target[e["slot_id"]].get("content_snr_db"))
            st = r.get("edit_stats")
            e["audio_stats"] = st  # None: original path (no recipe, no global gain)
            e["global_gain_applied_db"] = st["global_gain_applied_db"] if st else 0.0
            e["total_gain_db"] = st["total_gain_db"] if st else 0.0
            e["warnings"] = st["warnings"] if st else []
    slots = plan["entries"] if want_audio else []
    counts = dict(acts) if want_audio else {}
    if want_subs:
        counts.update(subtitle_entries=ss["keys_to_write"], subtitle_excluded=ss["excluded"],
                      subtitle_conflicts=ss["conflicts"])
    all_files = [f["install_rel"] for f in install_files]
    manifest = {
        "schema": MANIFEST_SCHEMA, "name": name, "kind": args.kind, "levels": levels,
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "inputs": {"mappings_sha256": msha, "mappings_sha256_at_end": msha_after,
                   "local_sha256": local_sha, "local_sha256_at_end": local_sha_after,
                   "bank_copy": BANK.relative_to(REPO_ROOT).as_posix(),
                   "bank_copy_sha256": pins["spanish.fsb"]["sha256"], "lst_sha256": pins["spanish.lst"]["sha256"],
                   "subtitle_copies": {t: {"path": SUBTITLE_COPY.format(table=t), "sha256": SUBTITLE_PINS[t]}
                                       for t in SUBTITLE_TABLES} if want_subs else None,
                   "subtitle_writer": WRITER if want_subs else None,
                   "libcelt_sha256": sha256_file(DEFAULT_DLL) if want_audio else None,
                   "vgmstream_sha256": sha256_file(args.vgmstream_cli) if want_audio else None,
                   "ffmpeg": next(iter(results.values()))["recipe"]["steps"][0]["version"] if want_audio else None,
                   "celt_profile": "fmod (prediction 0, complexity 0: all intra, no transients)" if want_audio else None},
        "install_files": install_files,
        "not_written": [p for p in ("halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin", INSTALL_BANK,
                                    *(SUBTITLE_INSTALL.format(table=t) for t in SUBTITLE_TABLES)) if p not in all_files],
        "decisions_changed_during_build": drift_during,
        "mission_association": association, "folders": folder_summary(plan["entries"]),
        "counts": counts,
        "radio_effect_slots": [e["slot_id"] for e in slots if e["radio_effect"]],
        "edited_slots": [e["slot_id"] for e in slots if e["action"] == "replace" and e.get("edit")],
        "audio_edit_engine": audio_edit.ENGINE, "render_engine": audio_edit.RENDER_ENGINE,
        "level": level_summary(cfg, slots) if want_audio else None,
        "global_gain": {"configured_db": cfg["global_gain_db"], "source": cfg["source"],
                        "level_mode": cfg["level_mode"],
                        "config_sha256": cfg["sha256"], "peak_ceiling_dbfs": audio_edit.PEAK_CEILING_DB,
                        "applies": want_audio and cfg["level_mode"] == "global_gain",
                        "rule": "linear, applied once after the recipe, "
                                "before CELT; reduced (never limited) when the peak would pass the ceiling",
                        "full": sum(1 for r in results.values() if not (r.get("edit_stats") or {}).get(
                            "global_gain_shortfall_db")),
                        "short": [e["slot_id"] for e in slots if e["action"] == "replace"
                                  and (e.get("audio_stats") or {}).get("global_gain_shortfall_db")]},
        "warnings": {e["slot_id"]: e["warnings"] for e in slots if e.get("warnings")},
        "slots": slots,
        "subtitles": {**subs, "enabled": want_subs, "tables": sub_tables, "warnings": sub_warnings},
        "level_status": inv,
    }
    report = {"schema": "m6-validation-report/2", "name": name, "kind": args.kind, "ok": ok, "checks": checks,
              "per_target": per_target, "differing_subsongs": audio_extra["differing_subsongs"],
              "candidate_sha256": install_files[0]["candidate_sha256"] if want_audio else None,
              "candidates": {f["install_rel"]: f["candidate_sha256"] for f in install_files},
              "seconds": round(time.time() - t0, 1)}
    (out / "build_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "test_report.md").write_text(test_report(name, manifest, report, app), encoding="utf-8")
    (out / "install_rollback.md").write_text(install_sheet(name, manifest), encoding="utf-8")
    failed = [k for k, v in checks.items() if not v]
    bad_targets = {s: [k for k, v in t["checks"].items() if not v] for s, t in per_target.items()
                   if not all(t["checks"].values())}
    print(f"{'PASS' if ok else 'FAILED'}: {len(checks) - len(failed)}/{len(checks)} checks; "
          f"{len(results)} sample(s) replaced; {ss['keys_to_write'] if want_subs else 0} subtitle entr(ies) written; "
          f"{report['seconds']} s")
    for f in install_files:
        print(f"  {f['install_rel']}: candidate {f['candidate_sha256'][:16]}… ({f['growth_bytes']:+,} B)")
    if want_audio:
        lv = manifest["level"]
        eg, vs = lv["effective_gain_db"], lv["loudness_vs_spain_db"]
        print(f"  level {lv['mode']}: effective gain median {eg['median']:+.1f} dB (min {eg['min']:+.1f}, max "
              f"{eg['max']:+.1f}); {len(lv['constrained'])} line(s) held back (" + ("6 dB limiting cap" if lv["mode"] == "match_spain" else "peak rule") + "); loudness vs Spain "
              + (f"median {vs['median']:+.1f} dB (p10 {vs['p10']:+.1f}, p90 {vs['p90']:+.1f})" if vs else "n/a"))
    for w in sub_warnings:
        print("  warning:", w)
    for k in failed:
        print("  FAILED:", k)
    if drift_during["changed_or_revoked"] or drift_during["newly_eligible"]:
        print(f"  note: decisions changed in M4 during the build (built from the snapshot): "
              f"{len(drift_during['changed_or_revoked'])} changed/revoked, {len(drift_during['newly_eligible'])} "
              "newly approved; rebuild to include them (m6_install.py refuses changed/revoked ones)")
    for s, ks in list(bad_targets.items())[:10]:
        print("  target", s, "failed", ks)
    print(f"wrote work/m6/{name}/ ({', '.join(Path(f['candidate']).name for f in install_files)}, build_manifest.json, "
          "validation_report.json, test_report.md, install_rollback.md)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
