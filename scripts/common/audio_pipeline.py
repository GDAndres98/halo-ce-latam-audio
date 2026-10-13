"""Source WAV -> MCC-ready CELT stream (B2 E3 and the future batch generator).

Pipeline (docs/b2-audio-research.md §5.10):
    source WAV (e.g. Campaign Evolved es-MX, 48 kHz mono 16-bit)
    -> ffmpeg (owner-approved, already installed): resample to 44,100 Hz, 16-bit, target channel count
    -> pad the end with CODEC_DELAY samples of silence, so the last real sample survives CELT's
       128-sample delay; the encoder then zero-pads to a whole 512-sample frame
    -> CELT 0.11 via libcelt-0110 with the MCC profile ("fmod": all intra, no transients; the only
       profile MCC's embedded decoder is proven to play, v-000017 vs v-000018)
    -> FMOD framing; sample_count = frames * 512 (as in every original MCC sample)

`derive` changes no content. `derive_processed` inserts the processing stages (common/audio_edit:
the owner's edit recipe of trims, cuts, fades and silences; the global
export gain, common/export_config) between the 44.1 kHz conversion and the padding, and records
every step. `codec_roundtrip` is what the M4 editor plays: the same encode,
decoded by the same libcelt, so the preview equals the bank content. Nothing here knows about
missions, slots or mappings. Every derived stream is written to work/derived/<stream sha256>/ with
recipe.json and the 44.1 kHz WAV it was encoded from.
"""
import hashlib
import json
import math
import subprocess
import wave
from array import array
from pathlib import Path

from . import audio_edit
from .celt011 import FRAME_SAMPLES, PROFILES, SAMPLE_RATE, fmod_frames, profile_violations

CODEC_DELAY = 128  # samples; CELT 0.11 overlap for the 44.1 kHz / 512 custom mode (measured, §5.7)
RECIPE_SCHEMA = "derived-audio-recipe/1"


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wav_info(path):
    with wave.open(str(path), "rb") as w:
        return {"sample_rate": w.getframerate(), "channels": w.getnchannels(), "sample_width": w.getsampwidth(),
                "frames": w.getnframes(), "seconds": round(w.getnframes() / w.getframerate(), 3)}


def ffmpeg_version(ffmpeg):
    out = subprocess.run([str(ffmpeg), "-hide_banner", "-version"], capture_output=True, text=True).stdout
    return out.splitlines()[0].strip() if out else None


def ffmpeg_args(src, channels):
    return ["-nostdin", "-hide_banner", "-v", "error", "-i", str(src), "-map_metadata", "-1",
            "-ac", str(channels), "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "s16le", "-"]


def to_mcc_pcm(ffmpeg, src, channels=1):
    """Resample/convert `src` to 44.1 kHz 16-bit PCM (raw, interleaved) with ffmpeg."""
    res = subprocess.run([str(ffmpeg)] + ffmpeg_args(src, channels), capture_output=True)
    if res.returncode != 0 or not res.stdout:
        raise RuntimeError(f"ffmpeg failed: {res.stderr.decode(errors='replace')[:300]}")
    return res.stdout


def encode_for_mcc(celt, pcm, channels=1, profile="fmod"):
    """44.1 kHz PCM -> dict(stream, sample_count, frames, packets). Refuses non-MCC-profile output."""
    if profile not in PROFILES:
        raise ValueError(f"unknown CELT profile {profile!r}")
    padded = pcm + b"\0" * (CODEC_DELAY * channels * 2)
    packets, frames = celt.encode(padded, channels=channels, profile=profile)
    bad = profile_violations(packets)
    if bad:
        raise ValueError(f"{len(bad)} packets outside the MCC CELT profile (first: {bad[0]})")
    return {"stream": fmod_frames(packets), "packets": packets, "frames": frames,
            "sample_count": frames * FRAME_SAMPLES}


def snr_db(ref, test, lag=CODEC_DELAY):
    """SNR (dB) of `test` against `ref` (16-bit mono PCM), with `test` delayed by `lag` samples."""
    a = array("h", ref)
    b = array("h", test[lag * 2:lag * 2 + len(ref)])
    n = min(len(a), len(b))
    sig = sum(v * v for v in a[:n])
    err = sum((u - v) ** 2 for u, v in zip(a[:n], b[:n]))
    return float("inf") if err == 0 else (float("-inf") if sig == 0 else 10 * math.log10(sig / err))


def derive(src, *, ffmpeg, celt, out_root, channels=1, profile="fmod", source_meta=None):
    """Run the pipeline for one source WAV. Writes work/derived/<sha>/ and returns the result dict."""
    src = Path(src)
    pcm = to_mcc_pcm(ffmpeg, src, channels)
    enc = encode_for_mcc(celt, pcm, channels, profile)
    decoded = celt.decode(enc["packets"], channels=channels)
    stream_sha = sha256_bytes(enc["stream"])
    in_samples = len(pcm) // (2 * channels)
    recipe = {
        "schema": RECIPE_SCHEMA,
        "source": {"file": src.name, "sha256": sha256_file(src), **wav_info(src), **(source_meta or {})},
        "steps": [
            {"op": "ffmpeg_convert", "version": ffmpeg_version(ffmpeg), "args": ffmpeg_args("<source>", channels)},
            {"op": "pad_end", "samples": CODEC_DELAY, "reason": "CELT 0.11 codec delay"},
            {"op": "celt_encode", "library": "libcelt-0110.dll (vgmstream r2117)", "profile": profile,
             "settings": {str(k): v for k, v in PROFILES[profile].items()}, "sample_rate": SAMPLE_RATE,
             "frame_samples": FRAME_SAMPLES, "packet_bytes": sorted({len(p) for p in enc["packets"]})},
        ],
        "content_changes": "none (no trim, gain or effects)",
        "pcm_44100": {"sha256": sha256_bytes(pcm), "samples": in_samples, "seconds": round(in_samples / SAMPLE_RATE, 3)},
        "output": {"stream_sha256": stream_sha, "stream_bytes": len(enc["stream"]), "frames": enc["frames"],
                   "sample_count": enc["sample_count"], "seconds": round(enc["sample_count"] / SAMPLE_RATE, 3),
                   "own_decode_snr_db": round(snr_db(pcm, decoded), 1) if channels == 1 else None},
    }
    out = _write_derived(out_root, stream_sha, pcm, channels, recipe)
    return {"recipe": recipe, "pcm": pcm, "decoded": decoded, "dir": out, **enc}


def _write_derived(out_root, stream_sha, pcm, channels, recipe):
    out = Path(out_root) / stream_sha
    out.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out / "mcc_44100.wav"), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    (out / "recipe.json").write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    return out


def needs_processing(edit, global_gain_db, level_mode="global_gain"):
    """False only for an unedited line with no global gain in global_gain mode: then `derive` (the original
    path) is used. match_spain always processes."""
    return not audio_edit.is_identity(edit) or bool(global_gain_db) or level_mode != "global_gain"


def render_edited(src, edit, *, ffmpeg, ref_lufs=None, global_gain_db=0.0, level_mode="global_gain", clicks=None,
                  static=None):
    """Source WAV -> 44.1 kHz PCM -> recipe -> level (global gain or match Spain).
    -> (source_pcm, audio_edit.render result). The single function both the M4 preview and the M6
    build call (mono only)."""
    source_pcm = to_mcc_pcm(ffmpeg, src, 1)
    return source_pcm, audio_edit.render(source_pcm, edit, ref_lufs=ref_lufs, global_gain_db=global_gain_db,
                                         level_mode=level_mode, clicks=clicks, static=static)


def codec_roundtrip(celt, pcm, profile="fmod"):
    """What MCC will play: the M6 encode of `pcm`, decoded by the same libcelt, codec delay removed,
    cut to the input length. M6 checks that vgmstream's decode of the bank equals this decode."""
    enc = encode_for_mcc(celt, pcm, 1, profile)
    decoded = celt.decode(enc["packets"], channels=1)
    return decoded[CODEC_DELAY * 2:CODEC_DELAY * 2 + len(pcm)], enc


def derive_processed(src, edit, *, ffmpeg, celt, out_root, ref_lufs=None, global_gain_db=0.0, profile="fmod",
                     source_meta=None, gain_source=None, level_mode="global_gain", clicks=None, static=None):
    """`derive` with the processing stages (recipe, level: global export gain or match Spain)
    applied after the 44.1 kHz conversion and before CELT (mono)."""
    src = Path(src)
    source_pcm, r = render_edited(src, edit, ffmpeg=ffmpeg, ref_lufs=ref_lufs, global_gain_db=global_gain_db,
                                  level_mode=level_mode, clicks=clicks, static=static)
    pcm, st = r["pcm"], r["stats"]
    enc = encode_for_mcc(celt, pcm, 1, profile)
    decoded = celt.decode(enc["packets"], channels=1)
    stream_sha = sha256_bytes(enc["stream"])
    n = len(pcm) // 2
    identity = audio_edit.is_identity(edit)
    steps = [{"op": "ffmpeg_convert", "version": ffmpeg_version(ffmpeg), "args": ffmpeg_args("<source>", 1)}]
    if not identity:
        steps.append({"op": "audio_edit", "engine": audio_edit.ENGINE, "recipe": edit,
                      "summary": audio_edit.summary(edit), "source_pcm_sha256": sha256_bytes(source_pcm)})
    if st["level_mode_used"] == "match_spain":
        steps.append({"op": "match_spain", "spain_lufs": st["mcc_reference_lufs"],
                      "line_lufs_before": st["loudness_before_gain_lufs"], **st["match"], "source": gain_source,
                      "rule": f"gain to the Spain recording's loudness (BS.1770); look-ahead limiter at "
                              f"{audio_edit.PEAK_CEILING_DB:g} dBFS taking at most {audio_edit.MATCH_MAX_LIMITING_DB:g} "
                              "dB off any peak (gain lowered otherwise)"})
    else:
        steps.append({"op": "global_gain", "requested_db": st["global_gain_requested_db"],
                      "applied_db": st["global_gain_applied_db"], "shortfall_db": st["global_gain_shortfall_db"],
                      "source": gain_source,
                      "rule": f"linear; reduced to keep the peak <= {audio_edit.PEAK_CEILING_DB:g} dBFS; never limited"})
    if st.get("interference"):
        steps.append({"op": "interference", **st["interference"],
                      "rule": "Victor 933 only: an intensity curve on the source timeline drives speech ducking (removed "
                              "at >= 0.95) and MCC's continuous static (common/interference.py)"})
    if st.get("echo"):
        steps.append({"op": "echo", **{k: v for k, v in st["echo"].items()},
                      "rule": "applied with the recipe (audio_edit.echo_effect); the line is extended by the ring-out"})
    if (st.get("radio") or {}).get("clicks"):
        steps.append({"op": "radio_clicks", **st["radio"]["clicks"],
                      "rule": "MCC Spain key-up click before, release/squelch after, at their game level"})
    steps += [
        {"op": "pad_end", "samples": CODEC_DELAY, "reason": "CELT 0.11 codec delay"},
        {"op": "celt_encode", "library": "libcelt-0110.dll (vgmstream r2117)", "profile": profile,
         "settings": {str(k): v for k, v in PROFILES[profile].items()}, "sample_rate": SAMPLE_RATE,
         "frame_samples": FRAME_SAMPLES, "packet_bytes": sorted({len(p) for p in enc["packets"]})}]
    recipe = {
        "schema": RECIPE_SCHEMA, "render_engine": audio_edit.RENDER_ENGINE,
        "source": {"file": src.name, "sha256": sha256_file(src), **wav_info(src), **(source_meta or {})},
        "steps": steps,
        "content_changes": ("owner edit recipe: " + audio_edit.summary(edit) + "; " if not identity else "")
        + (f"matched to Spain {st['total_gain_db']:+g} dB, limiter {st['match']['limiter_max_reduction_db']:g} dB"
           if st["level_mode_used"] == "match_spain" else f"global gain {st['global_gain_applied_db']:+g} dB")
        + (" (effects in the recipe: " + ", ".join(
            x for x in ("transmission interference" if st.get("interference") else None,
                        "radio filter" if st.get("radio") else None, "echo" if st.get("echo") else None,
                        "MCC clicks" if (st.get("radio") or {}).get("clicks") else None) if x) + ")"
           if st.get("radio") or st.get("echo") or st.get("interference") else " (no effects)"),
        "stats": st,
        "pcm_44100": {"sha256": sha256_bytes(pcm), "samples": n, "seconds": round(n / SAMPLE_RATE, 3)},
        "output": {"stream_sha256": stream_sha, "stream_bytes": len(enc["stream"]), "frames": enc["frames"],
                   "sample_count": enc["sample_count"], "seconds": round(enc["sample_count"] / SAMPLE_RATE, 3),
                   "own_decode_snr_db": round(snr_db(pcm, decoded), 1)},
    }
    out = _write_derived(out_root, stream_sha, pcm, 1, recipe)
    return {"recipe": recipe, "pcm": pcm, "decoded": decoded, "dir": out, "edit_stats": st, **enc}
