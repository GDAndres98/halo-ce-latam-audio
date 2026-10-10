"""M6 batch build (limited PoC): approved M4 mappings -> candidate MCC Spanish bank (offline only).

Reads the owner's decisions (mappings/manual_mappings.json via mapping_store.load, plus the
git-ignored local file), the catalogs under work/, and the pinned bank copy in reference-audio/stage1/.
For the selected level(s) it replaces every eligible approved CE audio decision
(common/m6_build.plan_audio) using the validated pipeline
(common/audio_pipeline: CE WAV -> ffmpeg 44.1 kHz -> [owner's edit recipe, common/audio_edit, the
same render the M4 editor previews] -> pad codec delay -> CELT 0.11 "fmod" profile, all intra, no
transients) and assembles ONE new bank. Unedited lines take exactly the original path. Untouched samples stay byte-identical; the
.lst.bin files are never written. Subtitles: dry run only (generation disabled, see docs/m6-build.md).

Validation (all must pass, else the build is marked FAILED):
  validator clean; plan has no conflicts; bank copy = pin;
  multi-sample structural checks; every one of the bank's subsongs decodes in the candidate and only
  the targets differ from the original; each target: vgmstream decode == own decode, content SNR vs
  its 44.1 kHz source >= 30 dB, sample count, Custom CELT, duration covers the source, no new
  clipping, silence after the end; whole build run twice -> identical bytes.

Outputs (git-ignored) in work/m6/<name>/:
  sounds_dialogs_spanish.fsb, inventory.json, build_manifest.json, validation_report.json,
  test_report.md, install_rollback.md. Derived streams: work/derived/<sha>/ (recipe.json).
Never installs anything, never changes or approves a mapping.

Example:
    python scripts/build/m6_build.py --level a10
    python scripts/build/m6_build.py --level a10 --level x10 --name a10_x10
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
from common import audio_edit  # noqa: E402
from common.audio_pipeline import derive, derive_processed, needs_processing, sha256_file, snr_db  # noqa: E402
from common.export_config import ConfigError, load_export_config  # noqa: E402
from common.celt011 import DEFAULT_DLL, Celt011  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_lib import parse_header  # noqa: E402
from common.m6_build import (  # noqa: E402
    FOLDER_GROUPS, assemble, compare_plans, entry_group, folder_summary, mission_folders, multi_structural_checks,
    plan_audio, subtitle_plan)
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
              "silence_after_source_end": max(map(abs, after), default=0) < 64}
    return checks, {"content_snr_db": round(snr, 1) if math.isfinite(snr) else str(snr)}


def build_once(original, targets, ce_audio, ffmpeg, celt, mcc_ref, cfg):
    """Encode every target and assemble the bank. -> (candidate bytes, {index: derive result}).
    mcc_ref(entry) -> loudness (LUFS) of the slot's original Spain recording, for edit recipes that
    match it. cfg: the export config (global gain, applied once to every replacement)."""
    results = {}
    gain = cfg["global_gain_db"]
    for e in targets:
        wav = ce_audio.wav(e["ce_mission"], e["language"], e["media"])
        meta = {"ce_line_ref": e["ce_line_ref"], "language": e["language"],
                "media_id": e["media"]["media_id"], "wem_sha256": e["media"]["wem_sha256"]}
        edit = e.get("edit") or audio_edit.EDIT_ZERO
        if needs_processing(edit, gain):
            ref = mcc_ref(e) if not audio_edit.is_identity(edit) and edit["loudness"]["mode"] == "match_mcc" else None
            try:
                res = derive_processed(wav, edit, ffmpeg=ffmpeg, celt=celt, out_root=DERIVED, ref_lufs=ref,
                                       global_gain_db=gain, profile="fmod", gain_source=cfg["source"],
                                       source_meta=dict(meta, mcc_reference_lufs=ref))
            except audio_edit.EditError as ex:
                raise SystemExit(f"{e['slot_id']}: audio cannot be processed: {ex}")
        else:  # unedited and no global gain: the original path, byte for byte
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


def test_report(name, manifest, report, app):
    ents = manifest["slots"]
    rep = [e for e in ents if e["action"] == "replace"]
    keep = [e for e in ents if e["action"] != "replace"]
    su = lambda e: (app._mcc_text(e["mcc_tag"])["SU"]["text"] or "")[:70]  # noqa: E731
    L = [f"# M6 test build `{name}` — {'PASS' if report['ok'] else 'FAILED'}", "",
         f"Built {manifest['built_at']} from `manual_mappings.json` sha256 `{manifest['inputs']['mappings_sha256'][:16]}…` "
         f"for level(s) {', '.join(manifest['levels'])}. **Audio only**: subtitle tables are not generated in "
         "this build (§5). Local test only; nothing is installed until the owner approves.", "",
         "## Output files", ""]
    L += md_table(manifest["install_files"], [("Install path", lambda f: f"`{f['install_rel']}`"),
                                               ("Candidate", lambda f: f"`{f['candidate']}`"),
                                               ("Candidate SHA-256", lambda f: f"`{f['candidate_sha256']}`"),
                                               ("Original (pinned) SHA-256", lambda f: f"`{f['original_sha256']}`")])
    L += ["", "Unchanged and never written: `halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin`, "
              "`SU_Halo1.bin`, `SP_Halo1.bin`, and every other game file.", "",
          f"## 1. Lines that will play in LATAM Spanish ({len(rep)})", ""]
    L += md_table(rep, [("Slot", lambda e: f"`{e['slot_id']}`"), ("CE line", lambda e: f"`{e['ce_line_ref']}`"),
                        ("Spain s", lambda e: e["original_seconds"]), ("LATAM s", lambda e: e["new_seconds"]),
                        ("Flags", lambda e: " ".join(x for x, on in (("R", e["radio_effect"]),
                                                                     ("≈", e["different_but_fits"]),
                                                                     ("E", bool(e.get("edit")))) if on)),
                        ("Current LATAM subtitle (SU, unchanged)", su)])
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
                           ("LUFS out / Spain", lambda e: f"{e['audio_stats']['output_lufs']} / "
                                                          f"{e['audio_stats']['mcc_reference_lufs']}"),
                           ("Match limiter dB", lambda e: e["audio_stats"]["limiter_max_reduction_db"])]) if edited \
        else ["- none"]
    g = manifest["global_gain"]
    short = [e for e in rep if (e.get("audio_stats") or {}).get("global_gain_shortfall_db")]
    L += ["", f"### Global gain: {g['configured_db']:+g} dB ({g['source']}), applied once to every replacement", "",
          f"Applied in full to {g['full']} line(s); **{len(short)} line(s) got less** because their peak would "
          f"pass {audio_edit.PEAK_CEILING_DB:g} dBFS (no limiting or compression is used for the global gain).", ""]
    if short:
        L += md_table(short, [("Slot", lambda e: f"`{e['slot_id']}`"),
                              ("Applied dB", lambda e: e["audio_stats"]["global_gain_applied_db"]),
                              ("Short dB", lambda e: e["audio_stats"]["global_gain_shortfall_db"]),
                              ("Peak before", lambda e: f"{round(e['audio_stats']['output_peak_dbfs'] - e['audio_stats']['global_gain_applied_db'], 2)} dBFS"),
                              ("Note", lambda e: "loudness-matched (already at the peak ceiling)"
                               if e["audio_stats"]["loudness_match"] else "")])
    radio = [e for e in rep if e["radio_effect"]]
    L += ["", f"## 3. Needs Radio Effect ({len(radio)}): recorded in the manifest, **no effect applied**", ""]
    L += [f"- `{e['slot_id']}` ← `{e['ce_line_ref']}`" for e in radio] or ["- none"]
    fits = [e for e in rep if e["different_but_fits"]]
    L += ["", f"Marked “different dialogue, but fits the scene” ({len(fits)}): "
              + (", ".join(f"`{e['slot_id']}`" for e in fits) or "none"), ""]
    s = manifest["subtitles"]["summary"]
    L += ["## 4. Subtitles", "",
          f"**No subtitle changes in this build.** {s['approved_text_changes']} approved subtitle decision(s) "
          f"would change text; keys found SU {s['keys_found'].get('SU')} / SP {s['keys_found'].get('SP')}; "
          f"same byte length SU {s['same_length'].get('SU')} / SP {s['same_length'].get('SP')}; variable length "
          f"SU {s['variable_length'].get('SU')} / SP {s['variable_length'].get('SP')}.",
          f"Reason: {s['reason']}. In game you will see MCC's original subtitles (LATAM `SU` text with the "
          "primary language set to Spanish (Latin America)), which may not match the new LATAM audio.", "",
          "## 5. Known limitations", "",
          "- Audio only; subtitle tables not generated (variable-length writer not validated).",
          "- Radio effects not applied (v1.1); flagged lines play the clean CE recording.",
          "- Not built: stereo slots, concatenations (`ce_concat`), user recordings (none approved here "
          "unless listed above). Edited lines (flag E) are built from their recipes.",
          f"- Global export gain {manifest['global_gain']['configured_db']:+g} dB on every replacement "
          "(lines listed under “Global gain” got less, to avoid clipping).",
          "- Durations differ from the Spain recordings (table §1); MCC proved it plays longer/shorter samples "
          "(E1b, E3), but timing against cutscenes/scripts is part of this test.", "",
          "## 6. In-game checklist", "",
          "Settings: Halo CE, primary language **Spanish (Latin America)**, fallback **Spanish (Spain)**, subtitles on.",
          "Launch with **Play Halo: MCC Anti-Cheat Disabled**. Test Classic graphics, then Anniversary.", "",
          "1. The game loads each mission in this build without a crash or hang; cinematics play through.",
          "2. Lines in §1 play in LATAM Spanish, completely (no cut-off start or end, no clicks, normal volume).",
          "3. The next line starts normally after a longer or shorter replacement (no overlap, no long silence).",
          "4. Lines in §2 still play the original Spain recording.",
          "5. Subtitles are MCC's originals (expected in this build).",
          "6. Note any line that sounds wrong: slot id or the moment in the mission.",
          "7. Close MCC completely before rollback (also after a crash).", ""]
    return "\n".join(L)


def install_sheet(name, manifest):
    f = manifest["install_files"][0]
    return "\n".join([
        f"# M6 `{name}`: install and rollback (LOCAL TEST ONLY; NEEDS THE OWNER'S EXPLICIT APPROVAL)", "",
        f"Replaces one file: `{f['install_rel']}` (original `{f['original_sha256'][:16]}…` -> candidate "
        f"`{f['candidate_sha256'][:16]}…`). Audio-only test; subtitle tables are not touched.", "",
        "```powershell",
        f"python scripts/build/m6_install.py --build {name} check       # read-only: MCC closed, build, hashes",
        f"python scripts/build/m6_install.py --build {name} preflight   # backup outside the install + verify, snapshot",
        f"python scripts/build/m6_install.py --build {name} install     # copy candidate, verify",
        "# Steam > Halo MCC > Play > \"Play Halo: MCC Anti-Cheat Disabled\"; test (test_report.md §6); CLOSE MCC",
        f"python scripts/build/m6_install.py --build {name} rollback    # restore + verify + compare snapshot",
        f"python scripts/build/m6_install.py --build {name} status",
        "```", "",
        "Every step refuses to run while MCC/EAC is open and stops on any hash mismatch. If a step fails "
        "after install, run `rollback`; if rollback fails, use Steam > Properties > Installed Files > "
        "Verify integrity of game files.", ""])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", action="append", help="MCC dialogue folder(s) to build (default a10)")
    ap.add_argument("--mission", help="playable map (e.g. a10): its own folder plus the cinematic folders only "
                                      "it uses, from work/mcc/level_folders.json (build_level_folders.py)")
    ap.add_argument("--all-mapped", action="store_true",
                    help="every MCC folder with at least one mapping (levels, cutscenes, generic barks); "
                         "build folder work/m6/all_mapped/")
    ap.add_argument("--name", help="build folder under work/m6/ (default: the levels joined by '_')")
    ap.add_argument("--inventory-only", action="store_true", help="report mappings and eligibility, build nothing")
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
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
    local = json.loads(local_p.read_text(encoding="utf-8")) if local_p.is_file() else None
    prog_p = REPO_ROOT / "mappings" / "mission_progress.json"
    progress = json.loads(prog_p.read_text(encoding="utf-8")) if prog_p.is_file() else {"levels": []}
    app = M4App(REPO_ROOT, run_validator=False)
    unknown = [lv for lv in levels if lv not in app.levels]
    if unknown:
        raise SystemExit(f"unknown level(s) {unknown}")
    idx = dict(slot_index=app.slot_index, ce_lines=app.ce_lines, ce_idx=app.ce_idx, mcc_idx=app.mcc_idx)
    inv = inventory(doc, app, progress)
    plan = plan_audio(doc, levels, local=local, **idx)
    subs = subtitle_plan(doc, set(levels), local=local, tables={t: app.loc.get(t) for t in ("SU", "SP")}, **idx)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps({"schema": "m6-inventory/1", "mappings_sha256": msha,
                                                    "levels": inv}, indent=2) + "\n", encoding="utf-8")
    acts = Counter(e["action"] for e in plan["entries"])
    print(f"mappings {len(doc['slots'])} in {len(inv)} level(s): " +
          ", ".join(f"{lv} {v['mappings']}" for lv, v in inv.items()))
    for f, v in folder_summary(plan["entries"]).items():
        print(f"  {f}: " + ", ".join(f"{g} {v[g]}" for g in FOLDER_GROUPS if v[g]) +
              f" (slots {v['slots']}, stereo {v['stereo']}, stereo replaced {v['stereo_replaced']})")
    print(f"plan {', '.join(levels)}: {acts.get('replace', 0)} replace, {acts.get('keep_original', 0)} keep Spain, "
          f"{acts.get('not_eligible', 0)} not eligible; conflicts {len(plan['conflicts'])}; subtitle text changes "
          f"{subs['summary']['approved_text_changes']} (generation disabled)")
    if args.inventory_only:
        return 0
    if plan["conflicts"] or subs["conflicts"]:
        raise SystemExit(f"conflicts: {plan['conflicts'] + subs['conflicts']}")
    targets = [e for e in plan["entries"] if e["action"] == "replace"]
    if not targets:
        raise SystemExit("nothing eligible to build")
    if not args.ffmpeg:
        raise SystemExit("ffmpeg not found")
    try:
        cfg = load_export_config(REPO_ROOT)
    except ConfigError as e:
        raise SystemExit(str(e))
    print(f"global gain {cfg['global_gain_db']:+g} dB ({cfg['source']})")

    pins = json.loads((REPO_ROOT / "work/mcc/build.json").read_text(encoding="utf-8"))["files"]
    original = BANK.read_bytes()
    checks = {"validator_clean": True,
              "bank_copy_matches_pin": hashlib.sha256(original).hexdigest() == pins["spanish.fsb"]["sha256"],
              "lst_copy_matches_pin": sha256_file(LST) == pins["spanish.lst"]["sha256"]}
    if not checks["bank_copy_matches_pin"]:
        raise SystemExit("Spanish bank copy does not match its pin")
    exe = args.vgmstream_cli
    ce_audio = CeAudio(REPO_ROOT, vgmstream_decoder(exe), ce_source_reader(args.oodle_dll))
    mcc_audio = MccAudio(REPO_ROOT, vgmstream_decoder(exe))
    refs = {}

    def mcc_ref(e):  # the original Spain recording, decoded from the pinned bank copy (verified)
        if e["slot_id"] not in refs:
            level, _rec, sample = app.slot_index[e["slot_id"]]
            refs[e["slot_id"]] = audio_edit.wav_loudness(mcc_audio.wav(level, "spanish", sample))
        return refs[e["slot_id"]]
    celt = Celt011()
    n_edit = sum(1 for e in targets if e.get("edit"))
    print(f"encoding {len(targets)} line(s), {n_edit} with edit recipes (pass 1)...")
    cand, results = build_once(original, targets, ce_audio, args.ffmpeg, celt, mcc_ref, cfg)
    print("encoding again (pass 2, determinism)...")
    cand2, results2 = build_once(original, targets, ce_audio, args.ffmpeg, celt, mcc_ref, cfg)
    celt.close()
    checks["deterministic_streams"] = all(results[k]["stream"] == results2[k]["stream"] for k in results)
    checks["deterministic_bank"] = cand == cand2
    del cand2, results2
    cand_path = out / "sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(cand)
    cand_sha = hashlib.sha256(cand).hexdigest()
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
    # The owner may keep saving in M4 (e.g. other levels) while this runs: the build must still match the
    # current approved decisions for the selected levels, so re-plan from the file as it is now.
    doc_after, msha_after = mapping_store.load(REPO_ROOT / "mappings" / "manual_mappings.json")
    local_after = json.loads(local_p.read_text(encoding="utf-8")) if local_p.is_file() else None
    # The build is consistent with the snapshot it read; later edits are reported, and m6_install.py
    # refuses to install a build whose replaced lines are no longer the approved decisions.
    drift_during = compare_plans(plan["entries"], plan_audio(doc_after, levels, local=local_after, **idx)["entries"])
    checks["lst_not_written"] = sha256_file(LST) == pins["spanish.lst"]["sha256"]
    ok = all(checks.values())

    for e in plan["entries"]:
        if e["action"] == "replace":
            r = results[e["spanish_index"]]
            e.update(new_sample_count=r["sample_count"], new_seconds=round(r["sample_count"] / 44100, 3),
                     source_wav=r["wav"].relative_to(REPO_ROOT).as_posix(), source_wav_sha256=r["wav_sha256"],
                     stream_sha256=r["recipe"]["output"]["stream_sha256"],
                     derived_dir=r["dir"].relative_to(REPO_ROOT).as_posix(),
                     content_snr_db=per_target[e["slot_id"]].get("content_snr_db"))
            st = r.get("edit_stats")
            e["audio_stats"] = st  # None: original path (no recipe, no global gain)
            e["global_gain_applied_db"] = st["global_gain_applied_db"] if st else 0.0
            e["warnings"] = st["warnings"] if st else []
    manifest = {
        "schema": MANIFEST_SCHEMA, "name": name, "levels": levels,
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "inputs": {"mappings_sha256": msha, "mappings_sha256_at_end": msha_after, "bank_copy": BANK.relative_to(REPO_ROOT).as_posix(),
                   "bank_copy_sha256": pins["spanish.fsb"]["sha256"], "lst_sha256": pins["spanish.lst"]["sha256"],
                   "libcelt_sha256": sha256_file(DEFAULT_DLL), "vgmstream_sha256": sha256_file(exe),
                   "ffmpeg": next(iter(results.values()))["recipe"]["steps"][0]["version"],
                   "celt_profile": "fmod (prediction 0, complexity 0: all intra, no transients)"},
        "install_files": [{"install_rel": INSTALL_BANK, "original_sha256": pins["spanish.fsb"]["sha256"],
                           "candidate": cand_path.relative_to(REPO_ROOT).as_posix(), "candidate_sha256": cand_sha,
                           "size": len(cand), "growth_bytes": len(cand) - len(original)}],
        "not_written": ["halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin", "Data/ui/localization/SU_Halo1.bin",
                        "Data/ui/localization/SP_Halo1.bin"],
        "decisions_changed_during_build": drift_during,
        "mission_association": association, "folders": folder_summary(plan["entries"]),
        "counts": dict(acts), "radio_effect_slots": [e["slot_id"] for e in plan["entries"] if e["radio_effect"]],
        "edited_slots": [e["slot_id"] for e in plan["entries"] if e["action"] == "replace" and e.get("edit")],
        "audio_edit_engine": audio_edit.ENGINE, "render_engine": audio_edit.RENDER_ENGINE,
        "global_gain": {"configured_db": cfg["global_gain_db"], "source": cfg["source"],
                        "config_sha256": cfg["sha256"], "peak_ceiling_dbfs": audio_edit.PEAK_CEILING_DB,
                        "rule": "linear, applied once after the recipe and the optional loudness match, "
                                "before CELT; reduced (never limited) when the peak would pass the ceiling",
                        "full": sum(1 for r in results.values() if not (r.get("edit_stats") or {}).get(
                            "global_gain_shortfall_db")),
                        "short": [e["slot_id"] for e in plan["entries"] if e["action"] == "replace"
                                  and (e.get("audio_stats") or {}).get("global_gain_shortfall_db")]},
        "warnings": {e["slot_id"]: e["warnings"] for e in plan["entries"] if e.get("warnings")},
        "slots": plan["entries"], "subtitles": subs, "level_status": inv,
    }
    report = {"schema": "m6-validation-report/1", "name": name, "ok": ok, "checks": checks,
              "per_target": per_target, "differing_subsongs": [k + 1 for k in differ],
              "candidate_sha256": cand_sha, "seconds": round(time.time() - t0, 1)}
    (out / "build_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "test_report.md").write_text(test_report(name, manifest, report, app), encoding="utf-8")
    (out / "install_rollback.md").write_text(install_sheet(name, manifest), encoding="utf-8")
    failed = [k for k, v in checks.items() if not v]
    bad_targets = {s: [k for k, v in t["checks"].items() if not v] for s, t in per_target.items()
                   if not all(t["checks"].values())}
    print(f"{'PASS' if ok else 'FAILED'}: {len(checks) - len(failed)}/{len(checks)} checks; "
          f"{len(results)} sample(s) replaced; candidate {cand_sha} ({len(cand) - len(original):+,} B); "
          f"{report['seconds']} s")
    g = manifest["global_gain"]
    print(f"  global gain {g['configured_db']:+g} dB ({g['source']}): full on {g['full']} line(s), reduced on "
          f"{len(g['short'])} to avoid clipping (test_report.md lists them)")
    for k in failed:
        print("  FAILED:", k)
    if drift_during["changed_or_revoked"] or drift_during["newly_eligible"]:
        print(f"  note: decisions changed in M4 during the build (built from the snapshot): "
              f"{len(drift_during['changed_or_revoked'])} changed/revoked, {len(drift_during['newly_eligible'])} "
              "newly approved; rebuild to include them (m6_install.py refuses changed/revoked ones)")
    for s, ks in list(bad_targets.items())[:10]:
        print("  target", s, "failed", ks)
    print(f"wrote work/m6/{name}/ (sounds_dialogs_spanish.fsb, build_manifest.json, validation_report.json, "
          "test_report.md, install_rollback.md)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
