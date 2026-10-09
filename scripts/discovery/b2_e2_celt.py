"""B2 E2: qualify a CELT 0.11 encoding pipeline offline (docs/b2-audio-research.md §5.7).

Encoder/decoder: libcelt-0110.dll from the approved vgmstream r2117 (common/celt011.py). No new
software. Steps:
  1. decoder parity: our decode of FMOD's original packets == vgmstream's decode (bit-exact);
  2. synthetic suite (tones, sweep, noise, speech-like bursts, silence): encode -> FMOD frames ->
     one-sample-per-signal FSB5 test bank (fsb5_writer) -> vgmstream decode; checks CBR 370 B,
     frame count, decode success, codec delay and SNR;
  3. generation loss on real MCC audio: decode English A10_350, re-encode, decode again;
  4. E2 candidate bank: our re-encode of English A10_350 (198,144 samples, same length) in Spanish
     slot #30, validated like E1 (only that sample differs; all 5,696 subsongs decode);
  5. resampler probe (48 kHz -> 44.1 kHz) on a synthetic tone: stdlib audioop.ratecv and, if present,
     the already-installed ffmpeg; reports length and SNR against an ideal 44.1 kHz tone.

Outputs (git-ignored): work/b2/e2/{e2_report.json, e2_summary.md, test_bank.fsb,
sounds_dialogs_spanish.fsb}. MCC retail content and synthetic signals only; nothing is installed.

Example:
    python scripts/discovery/b2_e2_celt.py
"""
import argparse
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop  # stdlib up to 3.12: findfit (C speed alignment) and ratecv (probe only)
from array import array
import hashlib
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.celt011 import FRAME_SAMPLES, Celt011, fmod_frames, split_fmod_frames  # noqa: E402
from common.env import REPO_ROOT  # noqa: E402
from common.fsb5_writer import build, decompose, replace_sample, replacement_compatibility  # noqa: E402
from common.vgm import DEFAULT_VGMSTREAM, decode_all, decode_hash, decode_pcm, meta, meta_value  # noqa: E402

SR = 44100
REF = REPO_ROOT / "reference-audio" / "stage1" / "fsb"
OUT = REPO_ROOT / "work" / "b2" / "e2"
TARGET = 30  # Spanish/English #30 = A10_350 (same length in both banks)
MIN_SNR_DB = 12.0  # sanity floor for perceptual codecs on synthetic signals; reported, not a quality claim


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def pcm16(samples):
    return b"".join(struct.pack("<h", max(-32768, min(32767, int(round(v))))) for v in samples)


def signals():
    rnd = random.Random(1234)
    n = SR * 2
    tone = [8000 * math.sin(2 * math.pi * 440 * k / SR) for k in range(n)]  # periodic: lag is ambiguous
    sweep = [8000 * math.sin(2 * math.pi * (100 * k / SR + (8000 - 100) * (k / SR) ** 2 / (2 * 2))) for k in range(n)]
    noise = [rnd.gauss(0, 3000) for _ in range(n)]
    speechy = []
    for k in range(n):  # harmonic "voice" at 140 Hz with syllable-rate envelope and pauses
        env = max(0.0, math.sin(2 * math.pi * 3.5 * k / SR)) ** 2
        speechy.append(env * sum(5000 / h * math.sin(2 * math.pi * 140 * h * k / SR) for h in range(1, 12)))
    odd_len = tone[:SR + 123]  # not a multiple of 512 -> last frame zero-padded
    silence = [0.0] * SR
    return {"tone440": pcm16(tone), "sweep": pcm16(sweep), "noise": pcm16(noise), "speechy": pcm16(speechy),
            "tone_odd_length": pcm16(odd_len), "silence": pcm16(silence)}


def wav_data(wav):
    return wav[wav.index(b"data") + 8:]


def align_and_snr(src, dec):
    """(lag in samples, SNR dB) of `dec` against `src`, 16-bit mono."""
    n = len(src) // 2
    if audioop.rms(src, 2) == 0:
        return 0, (float("inf") if audioop.rms(dec, 2) == 0 else float("-inf"))
    start = min(4096, n // 4)
    ref = src[start * 2:(start + 2048) * 2]
    off, _ = audioop.findfit(dec[:min(len(dec), (start + 4096) * 2)], ref)
    lag = off - start
    a = src[max(0, -lag) * 2:]
    b = dec[max(0, lag) * 2:]
    m = min(len(a), len(b)) // 2 * 2
    a, b = a[:m], b[:m]
    xa, xb = array("h", a), array("h", b)
    sig = sum(v * v for v in xa)
    err = sum((u - v) ** 2 for u, v in zip(xa, xb))
    return lag, (float("inf") if err == 0 else 10 * math.log10(sig / err))


def test_bank(spanish_model, streams):
    """Small FSB5 bank (header/name layout of the Spanish bank) with one mono sample per stream."""
    template = spanish_model["samples"][0]
    samples, names = [], []
    for name, (stream, count) in streams.items():
        samples.append(dict(template, stream=stream, sample_count=count,
                            chunks=[(3, struct.pack("<II", 0, count - 2))]))
        names.append(name.encode())
    return build(dict(spanish_model, samples=samples, names=names))


def resample_probe(ffmpeg):
    n48 = 48000
    src48 = pcm16(8000 * math.sin(2 * math.pi * 1000 * k / 48000) for k in range(n48))
    ideal = pcm16(8000 * math.sin(2 * math.pi * 1000 * k / SR) for k in range(SR))
    out = {}
    conv, _ = audioop.ratecv(src48, 2, 1, 48000, SR, None)
    out["audioop.ratecv"] = {"samples": len(conv) // 2, "snr_db": round(align_and_snr(ideal, conv)[1], 1)}
    if ffmpeg:
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "in.wav", Path(td) / "out.wav"
            with wave.open(str(a), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(48000), w.writeframes(src48)
            r = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(a), "-ar", str(SR), "-ac", "1",
                                "-c:a", "pcm_s16le", str(b)], capture_output=True, text=True)
            if r.returncode == 0:
                with wave.open(str(b), "rb") as w:
                    res = w.readframes(w.getnframes())
                out["ffmpeg (swresample default)"] = {"samples": len(res) // 2,
                                                      "snr_db": round(align_and_snr(ideal, res)[1], 1)}
            else:
                out["ffmpeg"] = {"error": r.stderr.strip()[:200]}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vgmstream-cli", type=Path, default=DEFAULT_VGMSTREAM)
    args = ap.parse_args()
    exe = args.vgmstream_cli
    OUT.mkdir(parents=True, exist_ok=True)
    pins = {k: v["sha256"] for k, v in json.loads((REPO_ROOT / "work" / "mcc" / "build.json")
                                                  .read_text(encoding="utf-8"))["files"].items()}
    es_path, en_path = REF / "sounds_dialogs_spanish.fsb", REF / "sounds_dialogs.fsb"
    es, en = es_path.read_bytes(), en_path.read_bytes()
    if sha256(es) != pins["spanish.fsb"] or sha256(en) != pins["english.fsb"]:
        raise SystemExit("bank copies do not match their pins")
    m_es, m_en = decompose(es), decompose(en)
    c = Celt011()
    checks, report = {}, {"schema": "b2-e2/1", "encoder": "libcelt-0110.dll (vgmstream r2117), CELT 0.11.0, "
                          "custom mode 44100 Hz / 512, CBR 370 B mono"}

    # 1. decoder parity on original FMOD packets (a few mono samples incl. the target)
    parity = []
    for k in (0, 13, TARGET, 5695):
        ours = c.decode(split_fmod_frames(m_es["samples"][k]["stream"]))
        vgm = wav_data(decode_pcm(exe, es_path, k + 1))
        parity.append(ours[:len(vgm)] == vgm and len(ours) >= len(vgm))
    checks["decoder_parity_with_vgmstream"] = all(parity)

    # 2. synthetic suite
    sigs = signals()
    streams, suite = {}, {}
    for name, pcm in sigs.items():
        packets, frames = c.encode(pcm)
        own = c.decode(packets)
        streams[name] = (fmod_frames(packets), frames * FRAME_SAMPLES)
        suite[name] = {"samples_in": len(pcm) // 2, "frames": frames, "packet_sizes": sorted(set(map(len, packets))),
                       "own_decode_lag_snr": [round(x, 1) if isinstance(x, float) else x
                                              for x in align_and_snr(pcm, own)]}
    tb = test_bank(m_es, streams)
    tb_path = OUT / "test_bank.fsb"
    tb_path.write_bytes(tb)
    for idx, name in enumerate(sigs):
        wav = decode_pcm(exe, tb_path, idx + 1)
        dec = wav_data(wav) if wav else b""
        lag, snr = align_and_snr(sigs[name], dec) if dec else (None, None)
        m = meta(exe, tb_path, idx + 1)
        suite[name].update({"vgm_decoded": bool(dec), "vgm_samples": len(dec) // 2,
                            "vgm_encoding": meta_value(m, "encoding"), "lag": lag,
                            "snr_db": None if snr is None else (round(snr, 1) if math.isfinite(snr) else str(snr))})
    checks["cbr_370_every_packet"] = all(s["packet_sizes"] == [370] for s in suite.values())
    checks["frames_ceil_n_over_512"] = all(s["frames"] == -(-s["samples_in"] // 512) for s in suite.values())
    checks["vgmstream_decodes_all_synthetic"] = all(s["vgm_decoded"] and s["vgm_encoding"] == "Custom CELT"
                                                    for s in suite.values())
    checks["vgm_length_equals_frames_x512"] = all(s["vgm_samples"] == s["frames"] * 512 for s in suite.values())
    finite = [s["snr_db"] for n, s in suite.items() if n not in ("silence", "noise") and isinstance(s["snr_db"], float)]
    checks["synthetic_snr_floor"] = bool(finite) and min(finite) >= MIN_SNR_DB
    checks["silence_stays_silent"] = suite["silence"]["snr_db"] in ("inf", None) or suite["silence"]["vgm_samples"] > 0

    # 3. generation loss on real MCC audio (English A10_350)
    en_pcm = wav_data(decode_pcm(exe, en_path, TARGET + 1))
    pk, fr = c.encode(en_pcm)
    regen = c.decode(pk)
    lag, snr = align_and_snr(en_pcm, regen)
    gen = {"frames": fr, "samples": len(en_pcm) // 2, "lag": lag, "snr_db_vs_first_decode": round(snr, 1),
           "packet_sizes": sorted(set(map(len, pk))),
           "bytes_equal_fmod_original": fmod_frames(pk) == m_en["samples"][TARGET]["stream"]}
    checks["regen_same_frame_count"] = fr == len(split_fmod_frames(m_en["samples"][TARGET]["stream"]))

    # 4. E2 candidate bank: our re-encode of English A10_350 into Spanish slot #30
    src = dict(m_es["samples"][TARGET], stream=fmod_frames(pk), sample_count=fr * FRAME_SAMPLES)
    compat = replacement_compatibility(m_es["samples"][TARGET], src)
    cand = build(replace_sample(m_es, TARGET, src["stream"], src["sample_count"]))
    cand_path = OUT / "sounds_dialogs_spanish.fsb"
    cand_path.write_bytes(cand)
    m_c = decompose(cand)
    full_o, full_c = decode_all(exe, es_path, len(m_es["samples"])), decode_all(exe, cand_path, len(m_c["samples"]))
    cand_target = wav_data(decode_pcm(exe, cand_path, TARGET + 1))
    checks.update({
        "candidate_compatible": all(compat.values()),
        "candidate_same_size_as_original": len(cand) == len(es),
        "candidate_other_samples_identical": all(a == b for k, (a, b) in enumerate(zip(m_es["samples"], m_c["samples"]))
                                                 if k != TARGET),
        "candidate_all_subsongs_decode": None not in full_o and None not in full_c,
        "candidate_only_target_differs": [k + 1 for k, (a, b) in enumerate(zip(full_o, full_c)) if a != b]
        == [TARGET + 1],
        "candidate_target_equals_own_decode": cand_target == regen[:len(cand_target)],
        "candidate_round_trip": build(m_c) == cand,
    })

    # 5. resampler probe
    ffmpeg = shutil.which("ffmpeg")
    resample = resample_probe(ffmpeg)
    c.close()

    report.update({"checks": checks, "ok": all(checks.values()), "decoder_parity": parity, "synthetic": suite,
                   "generation": gen, "candidate": {"path": cand_path.relative_to(REPO_ROOT).as_posix(),
                                                    "sha256": sha256(cand), "size": len(cand), "target_index": TARGET,
                                                    "compatibility": compat,
                                                    "target_meta": meta(exe, cand_path, TARGET + 1)},
                   "hashes": {"original_bank": pins["spanish.fsb"], "candidate": sha256(cand)},
                   "target": {"index": TARGET}, "resample_probe": resample, "ffmpeg": ffmpeg,
                   "note": "offline only; synthetic signals and MCC retail audio only; nothing installed"})
    (OUT / "e2_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [f"# B2 E2: CELT 0.11 encoder qualification — {'PASS' if report['ok'] else 'FAIL'}", ""]
    lines += [f"- `{k}`: {v}" for k, v in checks.items()]
    lines += ["", "| signal | frames | packets | vgm decoded | lag | SNR dB |", "|---|---|---|---|---|---|"]
    lines += [f"| {n} | {s['frames']} | {s['packet_sizes']} | {s['vgm_decoded']} | {s['lag']} | {s['snr_db']} |"
              for n, s in suite.items()]
    lines += ["", f"Generation loss (English A10_350 re-encoded): {gen}", "",
              f"Candidate: `{sha256(cand)}`", "", f"Resample probe: {resample}"]
    (OUT / "e2_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
