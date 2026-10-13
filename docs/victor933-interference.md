# Victor 933's damaged transmission (2026-10-13)

Owner request (prompt 44): recreate MCC's damaged radio transmission on the CE es-MX recording
`vo_scr_m06_00740_victor933`, replacing slot `es:c10_010_captpilot#0` (mapping `m-000482`). The interference
hides spoiler information. This is a **one-off for this recording**, not a general word-masking system.

The owner chose the 11 phrases and their kinds. The approved custom subtitle (`c-000023`) is unchanged, and the
audio stays **needs rework** until the owner approves it.

## 1. What MCC does

The MCC Spain and English recordings were compared with the CE es-MX source.

**Method:**
- 20 ms voicing: the normalised autocorrelation peak in the 2.5–12.5 ms range.
- Level, plus spectral flatness in 10 ms frames.
- Static = at least 120 ms that is unvoiced and 10 dB or more above the floor.

**The bursts are the same in both versions.** MCC Spain and MCC English share the static bursts at nearly
identical times, so the dub kept the original static track:

| MCC Spain (s) | MCC English (s) |
|---|---|
| 1.84–2.73 | 1.66–2.89 |
| 4.35–5.85 | 4.37–5.79 |
| 7.80–7.96 | 7.52–8.30 |
| 10.06–10.24 | 9.92–10.66 |
| 14.55–14.91 | 14.51–15.09 |
| 17.18–17.42 | 17.18–17.36 |
| 17.88–18.04 | 17.86–18.06 |
| 20.05–21.15 | 20.05–20.91 |
| 21.67–22.43 | 21.75–22.45 |
| — | 24.32–24.86 |

What the bursts do:
- **The speech is replaced, not covered.** Inside a burst the voicing (median 0.26–0.28) is the same as pure
  noise; no speech survives underneath.
- **No attack or decay ramps.** Speech flows straight into static and back.
- **Level and texture:** the static sits about **9.3 dB below the voiced speech** in Spain (−20.9 vs −11.6 dB
  median) and about 3 dB below it in English. It crackles: ±2.1 dB across 5 ms frames, peaks up to −13 dB.
- **Radio EQ:** the Spain recording has the pilot band-pass (docs/radio-filter.md §1.2). There is a constant hiss
  floor of about −34 dB between phrases, and no key-up click.
- **Duration and pacing:** MCC Spain 28.43 s, MCC English 28.64 s, CE es-MX 29.22 s (28.75 s after the owner's
  cuts and trim). The pacing is close, and the CE "33" falls exactly where MCC's first burst is.

## 2. Alignment of the 11 regions

The tool is the Windows es-ES speech recognizer (System.Speech, part of Windows; nothing installed):
- **Grammar alignment** on the owner's subtitle failed: the spoken text differs ("está capturado" against "fue
  capturado").
- **Dictation** gave word timings.
- **Utterance 2** was anchored at +16.15 s on the recording's silences (20.25 s and 23.09 s), and the anchor
  holds at every silence.
- **Every edge** was snapped to the nearest energy valley (±50 ms) and then reviewed against the 10 ms envelope.
  Fragment edges sit at consonant closures.

Times are on the CE source timeline. The defaults live in `config/interference/vo_scr_m06_00740_victor933.json`.

| # | Phrase | Effect | Start–end (s) | Note |
|---|---|---|---|---|
| 1 | Aquí | low but understandable | 0.12–0.40 | the line opens with 0.15 s of silence |
| 2 | 33 (spoken "nueve **treinta y tres**") | not understandable | 1.93–2.51 | same place as MCC's first burst |
| 3 | necesito ayuda inmediata | low but understandable | 5.23–6.64 | |
| 4 | bajo un fuerte | low but understandable | 7.42–7.99 | |
| 5 | …til aliení… | not understandable | 9.51–10.08 | from the "t" closure of "hostil" to the "g" of "alienígena" |
| 6 | no es del Covenant | low but understandable | 10.37–11.28 | |
| 7 | hostiles. Estamos | low but understandable | 13.91–14.96 | |
| 8 | …an estruc… | not understandable | 16.11–16.59 | from the "a" of "gran" to the closure before "-tura" |
| 9 | …empo podre… | not understandable | 18.99–19.57 | |
| 10 | …víen ayuda si reciben esta transmis… | not understandable | 21.06–22.92 | |
| 11 | intervalos | not understandable | 25.47–25.93 | |

Uncertain:
- **1:** "quí" runs into "la" with no pause, so the end (0.40 s) is an estimate.
- **5:** the recognizer heard "oscilaría en escena"; the edges come from the envelope.
- **10:** there's no valley between "en-" and "-víen", so the start (21.06 s) is an estimate. The final "-ión"
  of "transmisión" stays audible, as the phrase specifies.

The owner cuts (11.39–11.68 s and 23.22–23.40 s) lie in silences outside every region.

## 3. Implementation

- **Recipe:** the optional field `audio.edit.interference` = `{engine: "interference/1", regions: [{label, kind,
  start_s, end_s, intensity_db}]}` (schema `manual-mappings/3`). `audio_edit.normalize` and `problems` refuse it
  for any recording other than `audio_edit.INTERFERENCE_LINES`. Regions must be in order, not overlapping, inside
  the recording, with intensity between −12 and 12 dB.
- **Render** (`audio_edit.interference_effect`, `audio-render/9`): step 0, on the **source timeline**, before
  trims and cuts, so edits never move the masks. The length is unchanged.
  - **masked:** speech gain goes to 0 inside the region, with half-cosine ramps of 15 ms just outside it. MCC
    static is crossfaded in at the line's speech level − 9.3 dB + intensity.
  - **partial:** speech is ducked by 5 dB + intensity, with static at the masked level − 14 dB + intensity.
    These defaults come from the recognizer test in §4; the first attempt (8 dB duck, −4 dB static) left too
    little understandable.
  - **Speech level:** the median RMS of the line's active 20 ms frames.
  - **Static:** looped, with a 20 ms equal-power crossfade, starting at a different offset in each region.
    Deterministic.
  - **Chain:** after the interference come the owner's edits, the radio filter (Spain preset, no clicks), the
    level stage and CELT. The preview and M6 use the same code (`tests/test_audio_edit.py` parity test).
- **Static texture:** `common/radio_static.py`, MCC Spain's own pure-static stretch 4.40–5.80 s of
  `es:c10_010_captpilot#0` (samples 194,040–255,780). It comes from the pinned bank at fixed samples, is checked
  against a SHA-256 pin (`7677792f…`) and is decoded on demand. No audio is in git.
- **Studio:** a "Transmission interference" section in Audio editing that appears only for this recording. It
  lists the 11 phrases with their effect, start, end and intensity, all editable and undoable. Each row has a
  play button for that span of the original. "Reset to the aligned timings" and "Remove the interference" are
  at the bottom. The automatic B preview plays the whole processed transmission, and Needs rework protection is
  unchanged.
- **Data:** `scripts/validate/apply_victor933_interference.py` added the 11 regions to `m-000482`, whose audio
  was already needs rework. It backed up and verified that only that mapping changed. Rollback:
  `--rollback work/migrations/20261013T172936_victor933_interference`.

## 4. Verification (focused)

- **Masked (6):** the speech left inside is 75–171 dB below the unmasked render (only filter ringing). Static is
  at about −33 dB.
- **Partial (5):** speech is exactly 5 dB down, with static under it.
- **Intelligibility proxy:** the Windows es-ES dictation was run on the processed line without the band-pass
  (which starves the recognizer).
  - Masked phrases, all lost: "nueve treinta y tres" → "dictamen", "oscilaría en escena" → "dos de",
    "a la estructura" → "una lectura" ("-tura" is meant to remain), "tiempo podrá" → "te de",
    "envíe … transmisión" → gone, "intervalos" → "jerónimo".
  - Partial phrases: "aquí", "necesita ayuda inmediata" and "…estamos" are recognized. "bajo un fuerte" and
    "del Covenant" are not. The recognizer is harsher than a listener; raise or lower each region's intensity
    by ear.
- **Unmasked dialogue:** unchanged except the band-pass ringing within 7.6 ms of a region's ramp (up to 0.004,
  about −48 dBFS). The length is equal.
- **No clicks:** the largest sample step near region edges is 0.037, below the line's own 99.9th-percentile
  step (0.038).
- **No clipping:** the peak is −1.0 dBFS and there are no warnings.
- **Tests:**
  - `tests/test_audio_edit.py`: refused for other lines, rules, mute/duck, unchanged outside, deterministic,
    stable under trims and cuts, preview = M6.
  - `frontend` unit tests for the region rules.
  - Browser test: `npm run test:interference` (disposable data). It shows 11 regions only on this line, edits
    re-render, overlaps are refused, Reset works and the real mappings are unchanged.

## 5. What to listen for

- **Masked phrases:** no syllable of "treinta y tres", "hostil alien…", "gran estruc…", "tiempo podre…",
  "envíen … transmis…" or "intervalos" should come through. Listen most closely at the edges of region 10 (its
  start is an estimate) and region 5.
- **Partial phrases:** "bajo un fuerte" and "no es del Covenant" may be too buried. Try −3 dB intensity on those
  rows, or +3 dB if a phrase sounds too clean.
- **The static itself** is MCC's own crackle at Spain's level relative to the voice. Check that it doesn't
  sound looped in region 10, the longest (1.9 s).
- **Region 1 "Aquí"** is short and partial; check that the ramp doesn't clip the start of "la nave".
- **Pacing:** the CE line is 0.3 s longer than MCC Spain's; nothing here changes the timing.
