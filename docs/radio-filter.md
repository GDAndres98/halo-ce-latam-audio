# Radio filter (2026-10-13)

Owner request, 2026-10-13: find out how MCC's Spain and English versions filter the radio lines, and apply that
filter to the Campaign Evolved (CE) es-MX replacements from the matching interface.

Owner decisions (2026-10-13):
- the v1.1 "no effects yet" rule is lifted for this;
- the filter lives in the audio edit recipe, so approved lines go back to review when it is added;
- scope is **pilot-style radio only**. The 18 cryo-assistant lines noted "eco" are excluded, because an echo
  is reverb, not this filter. They got their own effect later the same day (§5).

## 1. Findings

Survey: `python scripts/discovery/radio_survey.py` (read-only, stdlib). It writes `work/reports/radio_survey.json`.

The survey covers:
- **Flagged lines:** the 58 mappings with "Needs radio effect", split into 40 with empty notes (pilot-style:
  Echo 419, Bravo 22 and the other pilots, Bisenti, Mendoza, the lifeboat pilot, `A10_643_cortana`, `sgt05g`)
  and 18 noted "eco".
- **Controls:** 60 unflagged scripted or cinematic lines with approved CE audio.
- **Recordings decoded per line:** the MCC Spain and English bank samples, and the CE es-MX and English
  recordings.
- **Measurements:**
  - the long-term spectrum of the active frames, in 1/3-octave bands relative to 1 kHz;
  - the 1 % and 99 % cumulative-energy frequencies;
  - the crest factor;
  - the noise floor of the quietest frame.

### 1.1 The effect is baked into the recordings

The decoded bank samples already carry the band-pass. They are what FMOD plays, and the FSB5 sample headers
hold only loop metadata, so the game applies no radio DSP of its own. A replacement therefore has to carry
the effect in its PCM before CELT encoding. The CE English recordings of these lines have the same spectrum as
MCC's English: the "vs CE" estimate is within about ±3 dB from 100 Hz to 6 kHz. So CE English reuses the
original (2001) English recordings, effect included.

### 1.2 Spain (pilot-style lines, 40, medians)

| Band (Hz) | 100 | 200 | 315 | 400 | 500 | 630 | 800 | 1k–3.15k | 4000 | 5000 | 6300 | 8000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Radio vs control, MCC Spain (dB) | −48 | −56 | −36 | −31 | −29 | −10 | −2 | 0 to −3 | −19 | −21 | −39 | −46 |

The Spain filter:
- **Shape:** a steep band-pass of about 700–3300 Hz, flat inside the band.
- **Energy:** the 1 %/99 % energy points are about 650 Hz and 3.0 kHz.
- **Dynamics:** the crest factor is about 2 dB below the CE source (11.2 vs 13.5 dB), which suggests light
  compression.
- **Noise:** no added hiss; the noise floor is about −67 dBFS.

### 1.3 English (same lines)

The English filter is gentler:
- a low cut of about −17 dB at 100 Hz and −11 dB at 630 Hz;
- a presence lift of +4 to +7 dB at 1.25–2 kHz;
- a high roll-off of −10 dB at 6.3 kHz and −19 dB at 8 kHz;
- baked-in hiss, with a noise floor of about −49 dBFS;
- a little clipping (0.09 % of samples).

### 1.4 CE es-MX is dry

The es-MX recordings of these lines are wide-band, like the controls: −27 dB at 8 kHz against −21 dB for
the controls. Only the lows are thinner. The remake presumably adds its radio sound at runtime, in Wwise;
this is not verified.

### 1.5 Lines worth a listen

In `sgt05g` and `D40_411_Pilot` the Spain originals have no band-pass at all, and in `c10_010_captpilot` it
is only mild. The flag or the preset may not be right for them.

### 1.6 The opening and closing clicks (owner feedback, same day)

The first version had no clicks; the owner noticed they were missing. The Spain originals carry a fixed key-up
click and a fixed release/squelch, spliced around the speech:

- **Opening click:** starts at about 16 ms and lasts about 24 ms, then a quiet bed (about −56 to −66 dB). It is
  the same sound in **35 of the 40** pilot-style Spain originals: correlation 0.79–1.00 against the reference,
  in two level variants about 2 dB apart. The other five (`sgt05g`, `lif_01`, `lif_05`, `c10_010_captpilot`,
  `D40_411_Pilot`) score 0.26 or less.
- **Closing click:** the last ~212 ms of the sample. A ~32 ms release burst, a short gap, an ~84 ms squelch,
  then an ~80 ms decay down to −63 dB, with nothing after it.
- **English** uses a different click of its own; it is not extracted.

The "eco" group shows a low cut below about 400 Hz and a small presence lift. The echo itself is
time-domain and not measured here.

Nobody has listened yet: these are measurements, not a listening verdict.

## 2. The filter (`audio.edit.radio`, `common/audio_edit.py`)

The filter is an optional part of the non-destructive recipe (schema `manual-mappings/3`, added without a
migration; absent or null means off):

```json
"radio": {"preset": "spain", "low_hz": 700, "high_hz": 3300, "slope_db_oct": 36,
          "presence_db": 0, "drive_db": 0, "noise_dbfs": null}
```

**Render order** (`audio-render/6`):
1. Trims, cuts, fades and silences.
2. The **radio filter:**
   - a Butterworth high-pass at `low_hz` and low-pass at `high_hz`, each of order `slope_db_oct / 6` (12, 24
     or 36 dB/oct), as RBJ biquads;
   - an optional peaking `presence_db` at the band's geometric centre (Q 1);
   - optional `drive_db` (tanh, unity at full scale);
   - optional hiss at `noise_dbfs`: Gaussian noise from a fixed seed through the same band-pass, so renders
     are deterministic.

   A peak above −1 dBFS after the filter gets a linear trim, which is reported.
3. The build's level mode (global gain or match Spain).
4. **MCC's clicks** (`clicks: true`) are joined around the line at the level they have in the game: not
   filtered and not gained. They are cut from one retail Spain sample, `es:A30_220_bisenti#0` in the pinned
   bank (`common/radio_clicks.py`):
   - the opening click is samples 0–2205 (50 ms, ending in a 5 ms fade);
   - the closing click is the last 9,582 samples (217 ms, starting with a 2 ms fade).

   Each is checked against a pinned SHA-256. No audio is stored in the repo. The line gets 0.267 s longer.
5. 16-bit, then CELT. The render engine is now `audio-render/7`.

The M4 preview and M6 use the same function, so the "as encoded" preview is still what the build writes
(`tests/test_audio_edit.py`).

**Ranges:**

| Field | Allowed values |
|---|---|
| `low_hz` | 100–2000 |
| `high_hz` | 1000–10000, and at least 1.5 × `low_hz` |
| `slope_db_oct` | 12, 24 or 36 |
| `presence_db` | −6 to +12 |
| `drive_db` | 0 to 24 |
| `noise_dbfs` | −80 to −30, or null |
| `clicks` | true or false (absent means false, as in recipes saved before the field existed) |

`preset` is a label only; the stored numbers are what renders.

**Presets**, fitted to §1:

| Preset | Low (Hz) | High (Hz) | Slope (dB/oct) | Presence (dB) | Drive (dB) | Hiss (dBFS) | Response (dB) |
|---|---|---|---|---|---|---|---|
| `spain` | 700 | 3300 | 36 | 0 | 0 | none | 400 Hz −29, 630 Hz −7, 4 kHz −11, 6.3 kHz −36 |
| `english` | 1000 | 5000 | 12 | +6 | 6 | −50 | |

The `spain` preset has `clicks` on; `english` has it off.

**Real-data check:** `es:A30_250_pilot#0`, rendered and encoded with the Spain preset. Against that line's own
Spain original, its first 45 ms correlate 0.88 and its last 200 ms 0.85.

## 3. In the Studio

The filter is set under **Audio editing → Radio filter**: Off, Spain radio, English radio or Custom, plus the
six values and **MCC clicks**. Changing a value turns the preset into Custom. Every change is undoable and re-renders the
automatic preview (B), as the other edits do. "Reset edits" keeps the filter; it has its own Off. The filter
is part of the audio decision, so an approved line must be marked Needs rework first. The "Needs radio
effect" flag stays a separate reminder, and the editor points to it when a flagged line has no filter.

Browser test: `npm run test:radio` (from `frontend/`; disposable data).

## 4. Migration

`scripts/validate/migrate_radio_preset.py` ran on 2026-10-13. Report:
[`migrations/2026-10-13-radio-preset.md`](migrations/2026-10-13-radio-preset.md).

The 40 pilot-style lines got the `spain` preset, with their existing edits kept. The 39 that were approved
went to needs rework (revision + 1), and the draft `C10_230_pilot` stayed a draft. Nothing else changed.

Until the owner re-approves them, the build leaves these lines out (they keep Spain audio). The backup and
rollback are in `work/migrations/20261013T120636_radio_preset/`.

`scripts/validate/migrate_radio_clicks.py` then ran the same day. Report:
[`migrations/2026-10-13-radio-clicks.md`](migrations/2026-10-13-radio-clicks.md). It turned the clicks on for
the 35 lines whose Spain original opens with the click (`radio_clicks.intro_similarity` ≥ 0.75). The five
without it were left off for the owner to decide. No approved audio was touched; all 40 were needs rework or
draft.

## 5. The "eco" lines: intercom EQ + echo (owner request, 2026-10-13)

These are the 18 lines flagged "Needs radio effect" with the note "eco": the cryo assistant in a10 (17
`A10_*_cryoassist` lines and `ass03`). Their effect is not the pilot band-pass. Survey:
`python scripts/discovery/eco_survey.py` (run `radio_survey.py` first), which writes
`work/reports/eco_survey.json`.

### 5.1 What MCC does

- **English (MCC, and CE English, which reuses the 2001 recordings):** two clean taps with no feedback.
  - The sample autocorrelation of every eco line peaks at **30 ms** and **150 ms** (median about 0.22 each).
    Nothing appears at 60, 300 or 450 ms, and the small 120 ms cross-term is where two taps predict it.
  - That corresponds to taps of about **−12 dB** each.
  - EQ: a muffled PA. Against the controls, about +9 dB at 400–630 Hz and −14 dB at 3 kHz, falling to −25 dB
    at 10 kHz.
- **Spain:** one smeared echo with repeats.
  - Sample autocorrelation shows nothing (about 0.01), but the envelope autocorrelation peaks at **140 ms**
    (0.30) and stays raised to about 300 ms (0.11 at 280 ms). Control lines sit near 0.
  - The tails after the last word show repeats at about 140 and 340 ms.
  - EQ: a steep low cut below about 350 Hz (−20 dB at 125–200 Hz), a +3 to +6 dB lift between 1.2 and
    5 kHz, and a steep cut above 8 kHz.
- **CE es-MX** recordings of these lines are dry.

### 5.2 The recipe

- **`radio`** gains an optional `presence_hz` (200–8000; absent means the band's geometric centre) and two
  intercom presets, fitted to the spectra above:

  | Preset | Low (Hz) | High (Hz) | Slope (dB/oct) | Presence | Clicks |
  |---|---|---|---|---|---|
  | `spain_eco` | 350 | 8000 | 36 | +8 dB at 2.5 kHz | none |
  | `english_eco` | 150 | 2250 | 12 | +8 dB at 400 Hz | none |

- **`echo`** is a new optional field, applied after the radio filter and before the level stage
  (`audio-render/8`):
  - `slap_ms` / `slap_db`: a short tap (`null` = off);
  - `delay_ms` / `echo_db`: the main echo;
  - `feedback_db`: repeats (`null` = one repeat);
  - `diffusion` (0–1): three allpasses that smear the repeats;
  - `damping_hz`: a low-pass in the echo path (`null` = none).

  The line is extended until the repeats are 60 dB down (at most 2 s).

  | Preset | Slap | Echo | Feedback | Diffusion | Damping |
  |---|---|---|---|---|---|
  | `spain` | none | 140 ms, −11 dB | −15 dB | 1 | 4 kHz |
  | `english` | 30 ms, −12 dB | 150 ms, −12 dB | none | 0 | none |

- **Calibration:** the Spain preset was chosen by a grid over delay, level, feedback and diffusion on 10 eco
  lines. `eco_survey.py` then checked both presets on all 18, applied to the dry CE es-MX recordings:

  | Measure | Preset | MCC | Verdict |
  |---|---|---|---|
  | English sample correlation, 30 ms | 0.22 | 0.22 | matches |
  | English sample correlation, 150 ms | 0.23 | 0.17 | slightly strong; −14 dB would match better |
  | Spain envelope correlation, 80 / 140 / 200 / 280 ms | 0.20 / 0.35 / 0.22 / 0.21 | 0.18 / 0.30 / 0.19 / 0.11 | repeats last longer than Spain's |
  | Spain sample correlation | about 0.01 | about 0.01 | smeared, as in Spain |

  If the Spain echo sounds too long, lower **Repeats** (feedback), e.g. to −20 dB.
- **Individual lines vary:** `A10_170` comes out stronger than its original, `A10_220` close to it. Tune by ear.
- **Length:** with the Spain preset a line gets 0.75 s longer (the ring-out).

In the Studio, **Audio editing → Echo** offers Off, Spain echo, English echo or Custom, with every value
editable. The radio filter's preset list adds "Spain intercom (eco lines)" and "English intercom (eco lines)".

### 5.3 Migration

`scripts/validate/migrate_eco_effect.py` ran on 2026-10-13. Report:
[`migrations/2026-10-13-eco-effect.md`](migrations/2026-10-13-eco-effect.md).

The 18 eco lines got `radio = spain_eco` and `echo = spain`, with existing edits kept. All 18 were approved and
went to **needs rework** (revision + 1). Their matches, meaning the chosen CE recordings, were kept. The backup
and rollback are in `work/migrations/20261013T150942_eco_effect/`. Nobody has listened yet.
