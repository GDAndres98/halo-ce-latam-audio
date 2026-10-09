# M4 matching UI — user guide

**For:** the project owner, matching MCC lines to Campaign Evolved lines one level at a time.
Design and rules: [`m4-matching-ui-design.md`](m4-matching-ui-design.md). Catalogs:
[`campaign-catalog.md`](campaign-catalog.md).

## 1. Start it

```
python scripts/ui/m4_server.py            # opens http://127.0.0.1:8765
```

**Setup:** nothing new to install.
- It needs the Python 3 already used by the project, standard library only, plus a modern browser.
- Audio uses the approved `vgmstream-cli` (`D:/Tools/vgmstream-r2117/`) and FModel's bundled Oodle
  DLL, read-only, exactly as the catalog tools do.

**First time only, or after a game update:** build the catalogs.

```
python scripts/catalog/build_ce_catalog.py --all
python scripts/catalog/build_mcc_catalog.py --all --no-audio
```

**Mapping file version:** if `mappings/manual_mappings.json` is still `manual-mappings/2`, the
app asks you to run `python scripts/validate/migrate_mappings.py --write`. The repository copy is
already `/3`.

- The server listens on **127.0.0.1 only**. `Ctrl+C` stops it.
- Options:
  - `--port`;
  - `--no-open` (don't open a browser);
  - `--vgmstream-cli`;
  - `--oodle-dll`;
  - `--ffmpeg` (default: the one on `PATH`) and `--celt-dll` (default: vgmstream's
    `libcelt-0110.dll`), both for the audio editor (§4.1). Without them the editor is disabled, and
    everything else works.
- **Audio is decoded the first time you press ▶,** which takes under a second, and is cached
  under `work/`.
- **Links:** `http://127.0.0.1:8765/#level=a10&slot=es%3AA10_140_cryotech%230` opens one slot.

## 2. The screen

| Area | What it does |
|---|---|
| Header | Pick the level (grouped: campaign, cutscene, generic). Progress shows decided / audio approved / subtitle approved / needs rework. Level status sets the workflow step (§5). |
| Left: MCC slots | Every Spanish slot of the level, in catalog order. See §3 for the filters and search. Badges: **A** / **S** = audio / subtitle approved (red = needs rework), **R** = needs radio effect, **stereo**. |
| Middle: slot | ▶ Spain and ▶ English recordings, then the **SU** (Latin America), **SP** (Spain) and **EN** (English, with its speaker label) subtitles. Past checks from `verifications.json` (read-only). Then the decision: match, audio, radio flag, subtitle, notes. |
| Right: CE lines | Campaign Evolved lines in **catalog order**. Scope: the missions mapped for the slot's level, all missions, or one mission. Filter: any subtitle / no es-MX subtitle / has es-MX subtitle. |
| Footer | The validator's result after the last save. |

Keyboard: `J` / `K` next / previous slot, `Space` plays Spain, `1`–`9` plays candidate 1–9 (es-MX),
`O` / `E` play the editor's original / edited line, `Esc` stops.

## 3. Searching

Both search boxes work the same way:
- **Words match partially.** `desp` finds *despierte*. All words must appear somewhere.
- **`"Quoted phrases"`** must appear together. Punctuation between the words is ignored:
  `"jefe maestro"` finds *Jefe Maestro.* and *jefe, maestro*.
- **Case, accents and punctuation are ignored.** `que paso` finds *¿Qué pasó?*.
- **What is searched:**
  - MCC slots: SU, SP and EN subtitle text, the EN speaker label, tag, slot ID, bank name, level
    and the speaker from the tag name.
  - CE lines: es-MX, en and es-ES text, plus the line ID, display key (it ends with the speaker)
    and folder.
- **Search every level** (left) searches all 28 MCC folders. Each hit shows its level and the
  matching subtitle line.
- **Highlighting:** matches are highlighted.
- **A search only filters.** Nothing is scored, ranked, selected or approved. A search with no hits
  shows nothing, never a "closest" result.
- **Lines without subtitles** stay reachable through their ID, speaker and folder, or through the
  **no es-MX subtitle** filter.

**Hide lines already used** (right, under the search box) hides CE lines already listed in
another slot's match, in any level.
- The current slot's own lines stay visible.
- The count line says how many lines were hidden.
- With the toggle off, a used line shows a **used ×N** badge; hover over it to see which slots use
  it.
- It is a filter only, remembered by your browser.

Slot filters (left):
- undecided, matched, no equivalent, deferred;
- audio / subtitle not approved;
- needs rework;
- **needs radio effect**;
- **different but fits**;
- **audio edited** (badge **E**);
- **stereo**.

## 4. Deciding one slot

1. **Listen** to Spain (and English), then to the candidates.
2. **Match:** click **+ use for this slot** on each CE line that corresponds. Order them with
   ↑ / ↓ (several lines are concatenated in that order). Or choose *no equivalent* or *deferred*.
3. **Audio:** *keep Spain*, or *CE line(s) from the match* in es-MX (en and es-ES are allowed
   too). The duration difference against Spain is a plain fact.
4. **Needs radio effect** (the **R** checkbox under Audio): your manual flag for the future v1.1
   radio repair. No effect is applied now.
   - It is saved with **Save** and survives restarts.
   - It is separate from the approvals: you can set or clear it even when the audio is approved,
     and that approval stays as it is.
   - *Needs rework* does not clear it.
   - Each change raises the flag's own revision and records the date.
   - It applies only to selected CE audio, so choosing *keep Spain* clears and disables it.
   - The future build pipeline reads it from `radio_effect` in `manual_mappings.json`.
   **Different dialogue, but fits the scene** (the **≈** checkbox under Match) is your note that the
   CE line says something different from the MCC line but works in that moment.
   - It needs at least one picked CE line, and clearing the match clears it.
   - Like the radio flag, it is saved with **Save**, survives restarts and *needs rework*, and
     never changes an approval.
   - Each change raises its own revision.
   - Find marked slots with the **different but fits** filter or the **≈** badge.
5. **Subtitle,** independently of the audio:
   - *keep MCC text*;
   - *CE text* (pick the line and the culture; cultures without text are disabled);
   - *custom*;
   - *none*.
6. **Save** keeps a draft. **Approve audio** / **Approve subtitle** save and approve one part.
   **Approve audio + subtitle** (next to Save) approves both in one save, after a confirmation that
   lists both choices. An approved part is read-only. To change it, use **Mark needs rework…**,
   which raises its revision by one.

**Defaults after you pick a line (owner preference, 2026-10-08):**
- **Audio** switches from *keep Spain* to *CE line(s) from the match*.
- **Subtitle** switches from *keep MCC text* to *CE text*: es-MX of the first picked line that has
  es-MX text. If none has text, it stays on *keep MCC text* and the "no source subtitle" notice
  appears.
- The defaults never pick a line for you, never replace *custom* or *none*, never change an
  approved part, and never change decisions already saved. Anything can still be changed before
  approving.

### 4.1 Audio editor (non-destructive)

When the audio is **one CE line** (mono slot), an editor appears under the Audio choice. Nothing you
do here changes a recording. You build a **recipe**, saved in the mapping's `audio.edit`, which M6
applies when it builds the bank.

**The screen:**
- **Top waveform:** the CE source.
  - Drag on it to **select**. Click to play from that point.
  - Drag the black **handles** at the edges to **trim**.
  - Grey = trimmed, red hatching = cut.
- **Spain** and **Edited, as M6 encodes it** are drawn on one shared time scale, so you can compare
  lengths.
- **Stats:** durations (source → edited, Spain, Δ), loudness (CE → output, Spain), applied gain,
  limiter reduction and peak. Warnings appear for heavy limiting (more than 6 dB), gain lowered for
  peaks, and strong speed changes.

| Control | What it does |
|---|---|
| ▶ Original / ▶ Selection | the CE recording, or only the selected part |
| **▶ Edited (as encoded)** | **exactly what MCC will play**: the recipe rendered, encoded with the MCC CELT profile and decoded by the same libcelt. M6 verifies that the bank decodes to these samples. |
| ▶ pre-codec | the edited audio before CELT (to judge the codec separately) |
| ▶ Spain / ■ | the original MCC recording / stop |
| ✂ **Cut selection** | removes an interior section. Each junction gets an equal-power **crossfade** (default 20 ms), and exactly the selected length is removed. Overlapping cuts merge. ▶ next to a cut plays the original around it; × removes it. |
| **Keep only selection** | sets both trims to the selection |
| Trim start / end, Fade in / out, Crossfade | exact values. Trimming an edge for the first time adds a 10 ms fade there; set it to 0 if you don't want one. |
| **Speed** | pitch- and formant-preserving tempo (ffmpeg `rubberband`). `1.10` = 10 % faster and shorter. **Fit to Spain duration** computes the speed that makes the edited line as long as the Spain one. |
| **Match Spain loudness** + offset | automatic gain to the ITU-R BS.1770 loudness of **this slot's original Spain recording**. The offset moves the target (for example −2 dB). |
| **Gain** | manual gain on top of everything (dB) |
| **Peak limiter** | on (default): a look-ahead limiter keeps peaks at −1 dBFS, so the loudness match can actually reach Spain's level. CE lines are about 7 dB quieter than the Spain recordings (`a10` survey: 58 of 60 can't reach it with gain alone). Off: the gain is lowered until the peak fits instead. |
| **Reset edits** | back to the unedited recording |

**Order of operations** (always the same, in M4 and M6): trims and cuts → fades → speed → gain
(loudness match + manual) → limiter → 16-bit. Recipe times are on the source's timeline (the top
waveform).

**Rules:**
- **Previews are rendered on the server** about 0.4 s after a change. The first render of a line
  takes about a second; later renders of the same recipe are instant, from the cache in
  `work/m4/preview/`.
- **Save** keeps the recipe in the draft. **Approve audio** approves it together with the audio
  choice, and the confirmation lists the edit. After that it's **read-only**: you can still listen
  and select, but changing or resetting the edit needs **Mark needs rework…** (revision + 1).
- **An edit belongs to one recording.** If you switch the line or its language, the edit is reset.
  Choosing *keep Spain* or several lines clears it when you save.
- **The radio flag** stays as it is. No radio processing is applied. Editing never changes it.
- **Invalid recipes are refused:** for example a trim past the end, overlapping cuts, or keeping
  less than 0.05 s. Nothing is written.
- **Heavy limiting:** above about 6 dB of reduction, peaks may sound squashed. A negative loudness
  offset is gentler.

### Lines with no source subtitle

Some CE lines have spoken dialogue but no subtitle.
- **In the candidate list,** they carry a **no subtitle** badge, and each culture shows "no …
  subtitle (reason)". You can still play them and use them for the slot.
- **When a matched line has no es-MX text,** the slot shows a dashed notice with **Write a custom
  subtitle**. Type your LATAM Spanish text: the preview shows it and its length.
- **Save** keeps the text as an undecided draft, stored only in the git-ignored
  `mappings/manual_mappings.local.json`. **Approve subtitle** approves it on its own, whatever the
  audio's state.
- **To leave it undecided,** just don't approve it. Status *undecided (draft)* is a valid state;
  only *ready for build* needs every slot's audio approved.
- The extracted catalogs are never changed.

### Stereo slots

Stereo slots (`x20`: 4, `multiplayer1`: 36) are marked **stereo**. You can play them and record
decisions, but stereo replacement is not implemented yet.

**Errors:**
- **"changed since this page loaded it" (409):** the file was saved from somewhere else (another
  tab, for example). Reload the slot and redo the edit.
- **"not valid yet" (422):** the decision breaks a rule, for example CE audio from a line not in
  the match, a radio flag on kept Spain audio, or approving CE text that doesn't exist. Nothing was
  written.

## 5. Level workflow

| Step | Where | Level status |
|---|---|---|
| 1–4. Pick the level, review its lines, match, approve audio and subtitles | M4 | `in progress` |
| 5. Build the replacements from approved decisions | M6 (not built yet) | `ready for build`: allowed only when every slot is decided and has approved audio |
| 6. Test the level in MCC | M7, owner-approved install only | `tested in MCC`: asks for confirmation and an optional `v-NNNNNN` entry |
| 7. Mark the level as reviewed | M4 | `reviewed`: asks for confirmation |

The status is stored in `mappings/mission_progress.json`. The validator warns if a level's status
gets ahead of its decisions.

**Mission scope:** add `{mcc_level, ce_missions, decided_at, note}` entries to
`mappings/mission_map.json` by hand. Cutscene folders `x10`–`x70` are accepted. Tools never add or
infer one. "All missions" stays available for every level.

## 6. What it writes, and what it never does

- **It writes only these files, through the protected store:**
  - `mappings/manual_mappings.json` (`manual-mappings/3`);
  - `mappings/manual_mappings.local.json`;
  - `mappings/mission_progress.json`;
  - plus audio caches under `work/` (decodes, and editor previews in `work/m4/preview/`).

  Every write checks the loaded hash, validates the schema, backs up to `mappings/.history/` and
  replaces the file atomically.
- **It never:**
  - suggests, ranks or pre-fills a match;
  - approves anything without your click;
  - changes an approved decision;
  - writes `verifications.json`, `mission_map.json` or the catalogs;
  - touches game files or banks;
  - edits or replaces an original recording (CE `.wem`/WAV, MCC bank copy). Edits are recipes only.
- Run `python scripts/validate/validate_project.py` before committing `mappings/`.
- **The E3 test pair** (`es:A10_010_cryotech#0` ← `vo_scr_m01_00460_cryotech#0`) appears only as
  the past check `v-000019`. It is not a mapping until you decide it here.
