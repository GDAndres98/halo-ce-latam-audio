# Victor 933's damaged transmission (2026-10-13)

Owner requests (prompts 44 and 45): recreate MCC's damaged radio transmission on the CE es-MX recording
`vo_scr_m06_00740_victor933`, which replaces slot `es:c10_010_captpilot#0` (mapping `m-000482`). The
interference hides spoiler information.

This is a **one-off for this recording**, not a general effects system. The owner chose the 11 phrases and their
kinds. The approved custom subtitle (`c-000023`) is never changed, and the audio stays **needs rework** until
the owner approves it.

- **Prompt 44** (commit `e6c29e2`) masked 11 separate regions. It worked, but sounded chopped.
- **Prompt 45** replaced the regions with an **interference curve** the owner shapes like an automation
  envelope.

## 1. What MCC does

The MCC Spain and English recordings were compared with the CE es-MX source.

**Method:**
- 20 ms voicing: the normalised autocorrelation peak in the 2.5–12.5 ms range.
- Level, plus spectral flatness in 10 ms frames.
- 5 ms envelopes at the burst edges.

**The bursts are the same in both versions.** The static bursts sit at nearly identical times in MCC Spain and
English, so the dub kept the original static track:

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

How the interference behaves:
- **Rhythm:** bursts last 0.14–1.5 s and come in waves. The 20–22.5 s stretch is three bursts with brief
  speech in between, and 4.35–5.85 s is one long wash.
- **Inside a burst** the speech is replaced: voicing (median 0.26–0.28) equals pure noise. Between bursts the
  speech is fully voiced. There are no slow fades: speech and static meet directly.
- **Noise continues between bursts.** Spain has a constant hiss bed of about −34 dB (about 22 dB under the
  voice). English is far noisier: its static runs only about 3 dB under the voice, and the hiss bed is louder.
- **Texture:** crackle of ±2.1 dB in 5 ms frames, peaks up to −13 dB, and slower swells between bursts. Spain's
  static sits about 9.3 dB under the voiced speech (−20.9 vs −11.6 dB median).
- **Duration:** MCC Spain 28.43 s, MCC English 28.64 s, CE es-MX 29.22 s (28.75 s after the owner's cuts and
  trim). The pacing is close, and the CE "33" falls exactly where MCC's first burst is.

The Studio's **MCC reference** overlay (§3.3) draws this as a curve. Spain shows clear bursts against the bed;
English sits near full intensity most of the time (median 0.92), because its static is so loud.

## 2. The 11 phrase guides (owner decisions, prompt 44)

**Alignment:**
- The Windows es-ES speech recognizer (System.Speech dictation, part of Windows; nothing installed) gave word
  timings.
- Utterance 2 was anchored at +16.15 s on the recording's silences (20.25 s, 23.09 s).
- Every edge was snapped to the nearest energy valley (±50 ms) and reviewed against the 10 ms envelope.

Source timeline. The guides are in `config/interference/vo_scr_m06_00740_victor933.json` and are copied into the
recipe.

| # | Phrase | Kind | Start–end (s) |
|---|---|---|---|
| 1 | Aquí | partial (low but understandable) | 0.12–0.40 |
| 2 | 33 (spoken "nueve **treinta y tres**") | masked (not understandable) | 1.93–2.51 |
| 3 | necesito ayuda inmediata | partial | 5.23–6.64 |
| 4 | bajo un fuerte | partial | 7.42–7.99 |
| 5 | …til aliení… | masked | 9.51–10.08 |
| 6 | no es del Covenant | partial | 10.37–11.28 |
| 7 | hostiles. Estamos | partial | 13.91–14.96 |
| 8 | …an estruc… | masked | 16.11–16.59 |
| 9 | …empo podre… | masked | 18.99–19.57 |
| 10 | …víen ayuda si reciben esta transmis… | masked | 21.06–22.92 |
| 11 | intervalos | masked | 25.47–25.93 |

Uncertain edges:
- the end of 1 ("quí" runs straight into "la");
- both edges of 5 (the recognizer heard "oscilaría en escena");
- the start of 10 (there's no valley between "en-" and "-víen").

The owner's cuts (11.39–11.68 s, 23.22–23.40 s) lie in silences.

## 3. The interference curve (prompt 45)

### 3.1 Recipe and rendering (`scripts/common/interference.py`)

`audio.edit.interference` (engine `interference/2`, schema `manual-mappings/3`) holds:
- `points`: `[{t, v}]` (time in source seconds, intensity 0–1), at least 2 ms apart;
- `guides`: the 11 decisions;
- `flutter_db`: 0–6, default 2.5.

It is refused for every other recording.

**Render** (`audio-render/10`, step 0 on the source timeline, before trims and cuts, so edits never move it):
1. The curve is linear between points, sampled every 1 ms, and smoothed with a 3 ms one-pole filter run
   **forward and backward**. The smoothing has no lag and leaves no corners to click.
2. It is mapped nonlinearly to two gains, measured against the line's speech level (the median of its active
   20 ms frames):

| Intensity | Speech | Static (re. the speech level) |
|---|---|---|
| 0 | untouched | silent |
| 0.35 | untouched (the hiss bed) | −24 dB |
| 0.6 | −5 dB (low but understandable) | −20 dB |
| 0.85 | −20 dB | −14 dB |
| ≥ 0.95 | **removed** | −9.3 dB (MCC Spain's static vs voice) |

3. **The static is one continuous stream for the whole line.**
   - It is made of 160 ms sine-windowed grains (50 % overlap, constant power) taken from seeded random
     positions in MCC Spain's own pure-static stretch (`common/radio_static.py`; 4.40–5.80 s of
     `es:c10_010_captpilot#0`, pinned SHA-256, decoded on demand, no audio in git).
   - Consecutive grains jump at least 200 ms, so it never loops audibly.
   - A slow seeded "flutter" (low-passed noise, about 6 Hz, ±`flutter_db`) moves its level organically.
4. Then come the owner's edits, the radio filter (custom 700–3300 Hz, 12 dB/oct, hiss −40 dBFS, clicks, as the
   owner set it), the level stage and CELT. The preview and M6 run the same code, and renders are
   deterministic.

**The stats report every guide:** a masked one says whether it is fully hidden; a partial one gives how far its
speech is ducked. The Studio shows the same live.

### 3.2 The default curve (`interference.default_points`)

Built from the guides, deterministic (seed 933):
- **Bed:** a wobbling hiss bed (0.27–0.40) every 0.3 s.
- **Partial phrases:** a swell to 0.6 (±0.05 wobble) over the phrase.
- **Masked phrases:** a short build-up (0.5 at −200 ms, 0.7 at −80 ms), then a **full plateau from 30 ms before
  to 30 ms after the phrase**, then a quick fade (0.68 at +100 ms, the bed by +280 ms).

Masked phrases win structurally: no other point may sit inside a plateau or within 12 ms of it, and close
dropouts merge. A test over 200 random layouts (1,000 when developed), with phrases as close as 6 ms, checks
that every masked phrase stays at full intensity after smoothing.

### 3.3 Studio: the interference lane (`frontend/src/components/match/InterferenceLane.vue`)

The lane is shown only for this recording, in Audio editing. It draws:
- **Bands:** red = speech removed (≥ 0.95), amber = ducked, blue = the hiss bed (≤ 0.35).
- The CE waveform (server peaks, original timeline).
- The 11 guides, numbered (red = masked, amber = partial).
- The curve, with its points.
- The optional **MCC reference** overlay (Spain or English, dashed; `GET /api/interference/reference`, cached
  in `work/m4/interference/`). It is a visual reference only and never changes the curve.

Controls:
- **Points:** click empty space to add a point (and drag it); drag a point; double-click or press Delete to
  remove one; arrow keys nudge the selected point (10 ms / 0.02). Its time and intensity can also be typed.
- **Draw:** drag to paint a stretch of the curve; the stroke replaces the points under it.
- **Zoom** 1–16×, scrolling sideways. **Flutter** in dB. **Reset curve** regenerates it from the guides.
- **Transport:** play from the cursor (click the time ruler) as CE processed (the M6 render, mapped through
  trims and cuts), CE original, MCC Spain or MCC English. Switching source while playing keeps the position;
  MCC runs on its own timeline.
- **Guide list:** live status per phrase. A masked phrase shows "hidden", or "audible!" when the curve lets
  speech through. A partial phrase shows its speech level.
- Every gesture is one undoable change (Ctrl+Z). The B player under "Listen and compare" plays the result,
  against the MCC Spain original as A.

**Data:** `scripts/validate/apply_victor933_interference.py`.
- `--upgrade` turned `m-000482`'s old `interference/1` regions into guides plus the default curve.
- `--reset-curve` regenerates the curve from the recipe's guides.

The audio was already needs rework, and nothing else changed. Backups are in `work/migrations/*_victor933_*`.

## 4. Verification (focused, prompt 45)

**On the stored recipe, real recording, through the Studio preview path:**
- **Masked phrases:** all 6 are hidden. The residual speech (static silenced) is about 175 dB under the
  original; there is none.
- **Partial phrases:** speech is 3.8–5.9 dB down, under the static.
- **Static:** continuous over the whole line, never below −55 dB in any 50 ms frame (bed about −45 dB, bursts
  up to −27 dB).
- **Length:** unchanged. **Peak:** −1.0 dBFS. **No clicks:** the largest sample step is 0.152, against the
  original recording's 0.155.

**Intelligibility proxy** (Windows es-ES dictation on the curve without the band-pass):
- **Every masked phrase is lost:** "nueve treinta y tres", "oscilaría en escena", "a la estructura", "tiempo
  podrá", "envíe … transmisión", "intervalos".
- **Partial phrases:** "aquí", "necesita(mos) … inmediata" and "…estamos" are recognized. "bajo un fuerte" and
  "no es del Covenant" are not; they weren't with the region version either. The recognizer is harsher than a
  listener.
- **Unmasked lines** ("del descenso", "si alguien puede", "capitán", "un minuto") came through after the
  dropout build-up was shortened.

**Tests:**
- `tests/test_audio_edit.py`:
  - this line only, and the old format refused;
  - the mapping, which is monotonic;
  - masked → no speech, partial → −5 dB;
  - continuous static, deterministic, same length, stable under trims and cuts;
  - the default curve hides every masked guide in 200 random layouts;
  - preview = M6.
- Frontend unit tests for the curve rules, the mapping and the time mapping.
- `npm run test:interference` (disposable data): the lane with its 11 guides; add, drag and Delete; Draw over a
  masked phrase warns, then Ctrl+Z restores; zoom, the reference overlay and play from the cursor; save and
  reload persist; Reset; no lane on another line; the real mappings unchanged.

## 5. What to listen for

- **The six masked phrases** should be unrecognizable, inside a natural wave of static rather than a cut. If a
  dropout sounds too long or too abrupt, move its build-up and fade points, but keep its guide "hidden".
- **"bajo un fuerte" and "no es del Covenant":** if they're too buried, lower the curve under them toward
  0.45–0.5. The guide shows the speech level as you drag.
- **The bed between phrases** (0.27–0.40): it should sound like a live channel, not added noise. Lower it if
  it's too present, or raise **Flutter** for more movement.
- **The A/B:** compare with MCC Spain (the reference overlay plus play from the cursor) for the rhythm of the
  waves; the English original is much noisier overall.
- **Edges near your cuts** (11.4 s, 23.2 s) and the end of the line: there should be no clicks.
