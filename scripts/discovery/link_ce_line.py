"""Build one evidence-annotated metadata record for a Campaign Evolved
voice line, following only explicit references in the game data.

Read-only: opens the installed containers for reading, writes only under
work/ (git-ignored). Any hop that can't be shown from a reference field
is recorded as derived or unresolved -- never guessed.

Example:
    python scripts/discovery/link_ce_line.py \
        --voice-asset Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech \
        --languages "Spanish(Mexico),English(US),Spanish(Spain)" \
        --vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.asset_metadata import (  # noqa: E402
    EXPLICIT, EXPLICIT_INDEX, UNRESOLVED, WWISE_TO_CULTURE, CEContext, derived, fnv1_32, hop,
    sha256_bytes)
from common.binreader import Reader  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.locres import parse_locres  # noqa: E402
from common.zen import UnsupportedProperty  # noqa: E402

WORK = REPO_ROOT / "work" / "ce"


def unwrap(v):
    """Strip parser wrappers: {'name': x} -> x, {'_default': True} -> None."""
    if isinstance(v, dict):
        if v.get("_default"):
            return None
        if set(v) == {"name"}:
            return v["name"]
    return v


def import_target(ref):
    """ObjectProperty value -> imported package path (explicit, from the import map)."""
    r = (ref or {}).get("ref") or {}
    t = r.get("target")
    return t.get("package") if isinstance(t, dict) else None


def read_string_table(ctx, game_path):
    pkg_info = ctx.load_package(ctx.game_path_to_vfs(game_path))
    if not pkg_info:
        return None
    pkg = pkg_info["package"]
    if pkg.exports[0]["class"] != "StringTable":
        return {"vfs_path": pkg_info["vfs_path"], "class": pkg.exports[0]["class"]}
    _props, r = pkg.read_export_properties(0)
    rr = Reader(r.data, r.pos)
    rr.i32()  # UObject HasGuid flag
    namespace = rr.fstring()
    keys = []
    for _ in range(rr.i32()):
        keys.append(rr.fstring())
        rr.fstring()  # source string (English) -- not stored here
    return {"vfs_path": pkg_info["vfs_path"], "container": pkg_info["container"],
            "class": "StringTable", "namespace": namespace, "keys": keys}


def read_event_cooked_data(ctx, game_path):
    pkg_info = ctx.load_package(ctx.game_path_to_vfs(game_path))
    if not pkg_info:
        return None, None
    pkg = pkg_info["package"]
    _props, r = pkg.read_export_properties(0)
    rr = Reader(r.data, r.pos)
    rr.i32()  # UObject HasGuid flag precedes the Wwise cooked-data struct
    cooked = pkg.read_struct(rr, "WwiseLocalizedEventCookedData")
    pkg_info["trailing_bytes"] = len(r.data) - rr.pos
    pkg_info["class"] = pkg.exports[0]["class"]
    return pkg_info, cooked


def decode_wem(vgmstream, wem_path, wav_path):
    res = subprocess.run([str(vgmstream), "-o", str(wav_path), str(wem_path)],
                         capture_output=True, text=True)
    if res.returncode != 0 or not wav_path.exists():
        return {"ok": False, "stderr": (res.stderr or "")[:300]}
    with wave.open(str(wav_path), "rb") as w:
        return {"ok": True, "wav": str(wav_path.relative_to(REPO_ROOT)),
                "duration_s": round(w.getnframes() / w.getframerate(), 3),
                "sample_rate": w.getframerate(), "channels": w.getnchannels()}


def build(ctx, voice_asset, languages, vgmstream=None):
    vfs = voice_asset if voice_asset.startswith("Meteorite/") else f"Meteorite/Content/{voice_asset}"
    if not vfs.endswith(".uasset"):
        vfs += ".uasset"
    info = ctx.load_package(vfs)
    if not info:
        raise SystemExit(f"voice asset not found in any container: {vfs}")
    pkg = info["package"]
    export = pkg.exports[0]
    props, _ = pkg.read_export_properties(0)
    hops = [hop("voice_asset.class", EXPLICIT, value=export["class"],
                source="zen export map + global script objects")]
    record = {
        "ce_line_key": None, "display_key": export["name"],
        "voice_asset": {"vfs_path": info["vfs_path"], "container": info["container"],
                        "package_name": pkg.name, "class": export["class"]},
        "entries": [],
        "hops": hops,
        "provenance": {"usmap": ctx.usmap_path.name, "built_at": dt.datetime.now().isoformat(timespec="seconds"),
                       "tool": "scripts/discovery/link_ce_line.py"},
    }
    voice_entries = props.get("VoiceEvents")
    if voice_entries is None and "PlayEvent" in props:  # HaloAudioSound shape
        voice_entries = [{"VoiceEvent": props["PlayEvent"], "Transcription": props.get("TranscriptionLine"),
                          "LipSync": None}]
    for n, ve in enumerate(voice_entries or []):
        entry = {"index": n}
        record["entries"].append(entry)
        p = f"VoiceEvents[{n}]"

        # --- audio: voice asset -> AkAudioEvent -> per-language media -------------
        event_path = import_target(ve.get("VoiceEvent"))
        hops.append(hop(f"{p}.VoiceEvent", EXPLICIT if event_path else UNRESOLVED,
                        target=event_path, source="voice asset ObjectProperty -> import map"))
        entry["event"] = {"package": event_path}
        if event_path:
            ev_info, cooked = read_event_cooked_data(ctx, event_path)
            entry["event"].update({"vfs_path": ev_info["vfs_path"], "container": ev_info["container"],
                                   "class": ev_info["class"], "trailing_bytes_unparsed": ev_info["trailing_bytes"]})
            event_name = event_path.rsplit("/", 1)[-1]
            ids = {unwrap(v["value"]["EventId"]) for v in cooked["EventLanguageMap"]}
            event_id = next(iter(ids)) & 0xFFFFFFFF if len(ids) == 1 else None
            entry["event"]["event_id"] = event_id
            hops.append(hop("event.EventId == fnv1(event name)", derived("wwise_shortid_fnv1"),
                            matches=event_id == fnv1_32(event_name), event_id=event_id))
            by_lang = {unwrap(kv["key"]["LanguageName"]): kv["value"] for kv in cooked["EventLanguageMap"]}
            entry["available_languages"] = sorted(by_lang)
            entry["media"] = {}
            for lang in languages:
                v = by_lang.get(lang)
                if not v:
                    entry["media"][lang] = {"evidence": UNRESOLVED, "reason": "language not in EventLanguageMap"}
                    continue
                media = [{"media_id": unwrap(m["MediaId"]) & 0xFFFFFFFF, "media_path": unwrap(m["MediaPathName"]),
                          "streaming": unwrap(m["bStreaming"]), "source_name": unwrap(m["DebugName"])}
                         for m in v["Media"]]
                banks = [{"bank_id": unwrap(b["SoundBankId"]) & 0xFFFFFFFF, "bank_path": unwrap(b["SoundBankPathName"]),
                          "bank_name": unwrap(b["DebugName"])} for b in v["SoundBanks"]]
                m_entry = {"evidence": EXPLICIT, "source": "AkAudioEvent.EventCookedData.EventLanguageMap",
                           "media": media, "soundbanks": banks}
                hops.append(hop(f"event -> media[{lang}]", EXPLICIT, media_ids=[m["media_id"] for m in media]))
                pak = ctx.pak_for_wwise_language(lang)
                for m in media:
                    vfs_media = f"Meteorite/Content/WwiseAudio/{m['media_path']}"
                    if pak and vfs_media in pak.files:
                        data = pak.read(vfs_media, ctx.oodle)
                        m.update({"container": pak.path.name, "vfs_path": vfs_media, "wem_bytes": len(data),
                                  "wem_sha256": sha256_bytes(data), "exists_evidence": EXPLICIT_INDEX})
                        if vgmstream:
                            out_dir = WORK / "audio" / lang
                            out_dir.mkdir(parents=True, exist_ok=True)
                            wem = out_dir / f"{m['media_id']}.wem"
                            wem.write_bytes(data)
                            m["decode"] = decode_wem(vgmstream, wem, out_dir / f"{export['name']}.wav")
                    else:
                        m["exists_evidence"] = UNRESOLVED
                entry["media"][lang] = m_entry

        # --- subtitle: voice asset -> StringTable + LineKey -> locres --------------
        tr = ve.get("Transcription") or {}
        table_path = import_target(tr.get("StringTable"))
        line_key = unwrap(tr.get("LineKey"))
        metadata = {kv["key"]: kv["value"] for kv in (unwrap(tr.get("MetaData")) or [])}
        entry["transcription"] = {"type": unwrap(tr.get("Type")), "string_table": table_path,
                                  "line_key": line_key, "metadata": metadata}
        hops.append(hop(f"{p}.Transcription", EXPLICIT if table_path and line_key else UNRESOLVED,
                        string_table=table_path, line_key=line_key,
                        source="HaloAudioTranscriptionLine{StringTable, LineKey}"))
        record["ce_line_key"] = (line_key or export["name"]).lower()
        if table_path and line_key:
            st = read_string_table(ctx, table_path)
            ns = st.get("namespace")
            present = line_key in st.get("keys", [])
            entry["string_table"] = {k: st[k] for k in ("vfs_path", "container", "class", "namespace") if k in st}
            entry["string_table"]["key_present"] = present
            entry["string_table"]["entry_count"] = len(st.get("keys", []))
            hops.append(hop("string_table.TableNamespace + key", EXPLICIT if present else UNRESOLVED,
                            namespace=ns, key_present=present))
            entry["subtitles"] = {}
            p0 = ctx.pak("pakchunk0-Windows.pak")
            for lang in languages:
                culture = WWISE_TO_CULTURE.get(lang)
                loc_path = f"Meteorite/Content/Localization/Subtitles/{culture}/Subtitles.locres"
                if not culture or loc_path not in p0.files:
                    entry["subtitles"][lang] = {"evidence": UNRESOLVED, "reason": "no Subtitles.locres for culture"}
                    continue
                _ver, table = parse_locres(p0.read(loc_path, ctx.oodle))
                hit = table.get(ns, {}).get(line_key)
                entry["subtitles"][lang] = {
                    "culture": culture, "locres": loc_path, "namespace": ns, "key": line_key,
                    "evidence": EXPLICIT if hit else UNRESOLVED,
                    "text": hit["text"] if hit else None,
                }
                hops.append(hop(f"locres[{culture}] (namespace, key)", EXPLICIT if hit else UNRESOLVED))

        # --- lip-sync ----------------------------------------------------------------
        lips = unwrap(ve.get("LipSync"))
        lip_path = lips.get("soft_path") if isinstance(lips, dict) else None
        entry["lipsync"] = {"soft_path": lip_path, "evidence": EXPLICIT if lip_path else UNRESOLVED}
        if lip_path:
            base_vfs = ctx.game_path_to_vfs(lip_path)
            li = ctx.load_package(base_vfs)
            entry["lipsync"]["class"] = li["package"].exports[0]["class"] if li else None
            entry["lipsync"]["vfs_path"] = li["vfs_path"] if li else None
            per_culture = {}
            for lang in languages:
                culture = WWISE_TO_CULTURE.get(lang)
                if culture and culture != "en":
                    l10n = base_vfs.replace("Meteorite/Content/", f"Meteorite/Content/L10N/{culture}/", 1)
                    hit = ctx.find_package(l10n)
                    per_culture[culture] = {"vfs_path": hit[1] if hit else None,
                                            "evidence": derived("ue_l10n_folder_convention") if hit else UNRESOLVED}
            entry["lipsync"]["localized_variants"] = per_culture
            hops.append(hop(f"{p}.LipSync", EXPLICIT, target=lip_path, cls=entry["lipsync"]["class"]))

    # --- Blam sound tag: same name, but not referenced by the voice asset -----------
    key = record["ce_line_key"] or ""
    parts = key.split("_")  # vo_scr_m01_00460_cryotech -> m01_00460_cryotech
    tag_guess = None
    if len(parts) >= 5:
        tag_guess = (info["vfs_path"].replace("/Audio/scripted/", "/Tags/sound/scripted/")
                     .rsplit("/", 1)[0] + "/" + "_".join(parts[2:]) + "-sound.uasset")
    tag_hit = ctx.find_package(tag_guess) if tag_guess else None
    record["blam_sound_tag"] = {"vfs_path": tag_hit[1] if tag_hit else None,
                                "evidence": derived("name_convention") if tag_hit else UNRESOLVED,
                                "note": "not referenced by the voice asset; relationship by name only"}
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice-asset", required=True)
    ap.add_argument("--languages", default="Spanish(Mexico),English(US),Spanish(Spain)")
    ap.add_argument("--vgmstream-cli", type=Path, help="decode media to WAV under work/ce/audio")
    ap.add_argument("--oodle-dll", type=Path)
    args = ap.parse_args()
    ctx = CEContext(oodle_dll=args.oodle_dll)
    try:
        rec = build(ctx, args.voice_asset, [x.strip() for x in args.languages.split(",")], args.vgmstream_cli)
    except UnsupportedProperty as e:
        raise SystemExit(f"stopped: unsupported property encountered ({e}); relationship left unresolved")
    out = WORK / "records" / f"{rec['ce_line_key']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    for h in rec["hops"]:
        print(f"  [{h['evidence']:<32}] {h['hop']}")


if __name__ == "__main__":
    main()
