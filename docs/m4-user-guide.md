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
python scripts/catalog/build_ce_catalog.py --all        # every CE mission + SYS (barks, taunts)
python scripts/catalog/build_mcc_catalog.py --all --no-audio
```

`python scripts/catalog/build_ce_catalog.py --systemic` rebuilds only the CE systemic voice sets
(about 40 s). They cover marine, crew and civilian chatter, Covenant taunts and combat barks, and
appear in M4 as the CE scope **SYS**.

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
| Right: CE lines | Campaign Evolved lines in **catalog order**. Scope: the missions mapped for the slot's level, all missions, one mission, or **SYS** (systemic barks and taunts, by character folder such as `vo_sys_grunt`). For MCC's generic folders (`marines`, `grunt`, …) the scope starts on SYS. Filter: any subtitle / no es-MX subtitle / has es-MX subtitle. |
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
   - **Takes of this sound** (2026-10-17, docs/added-takes-design.md): for a sound **without** a subtitle
     entry (AI chatter such as Grunt deaths), add extra Campaign Evolved recordings: focus one on the right, then
     *Add as extra take*. Each added take is approved, reworked, reordered or removed on its own; the game picks
     among all the sound's takes. Lines whose sound has added takes show **+N**; filter *Has added takes*.
     Several at once, and *Replace every take of this sound*: see §4.3.
   - **Join two matched recordings** / **Play two matched recordings at the same time** (2026-10-19,
     `docs/combine-recordings.md`): match two Campaign Evolved lines first, then choose which plays first.
     *Join*: each part gets its own editor (trims, cuts, silences, fades), and you set the gap between them
     (negative = they overlap). *Play together*: both play unedited; set when the second starts. A radio filter
     or echo applies to the combined result. There is no volume per recording; if the two add up too loud, the
     result is lowered just enough and the panel says so. The result is rendered as the build makes it and heard as
     B in Listen and compare. In a join, the keyboard shortcuts act on the part you clicked last (outlined).
   - **Mute in game (no replacement)** (Studio only, 2026-10-15): the line is omitted; the build
     writes silence of the same length, so the scene's timing stays. Say why (required). It marks
     the line *no equivalent* and proposes subtitle *none* (a tag's subtitle is only removed when
     every take of it has an approved *none*). Undo it with *keep Spain* (after *Needs rework* if
     approved). Find muted lines with the **Muted in game** filter. See
     `docs/mute-language-permutations.md` §1.
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
  - Drag on it to **select**. Click to set the **cursor** (thin line) and play from that point.
  - Drag the black **handles** at the edges to **trim**.
  - Grey = trimmed, red hatching = cut, green marker = inserted silence (labelled with its length).
- **Spain** and **Edited, as M6 encodes it** are drawn on one shared time scale, so you can compare
  lengths.
- **Stats:**
  - durations (source → edited, Spain, Δ);
  - loudness (CE → output, Spain) and peak, for information only;
  - the **global export gain** as applied / requested, and where it comes from.
- **Warnings appear for** a line that couldn't take the full global gain.

| Control | What it does |
|---|---|
| ▶ Original / ▶ Selection | the CE recording, or only the selected part |
| **▶ Edited (as encoded)** | **exactly what MCC will play**: the recipe rendered, encoded with the MCC CELT profile and decoded by the same libcelt. M6 verifies that the bank decodes to these samples. |
| ▶ pre-codec | the edited audio before CELT (to judge the codec separately) |
| ▶ Spain / ■ | the original MCC recording / stop |
| ✂ **Cut selection** | removes an interior section. Each junction gets an equal-power **crossfade** (default 20 ms), and exactly the selected length is removed. Overlapping cuts merge. ▶ next to a cut plays the original around it; × removes it. |
| **Keep only selection** | sets both trims to the selection |
| **＋ Insert silence** (length in s) | adds that much silence at the cursor, or at the start of the selection. Inserting again at the same point lengthens it. Refused inside a cut or a trimmed part. |
| **Replace selection with silence** | sets a pause to an exact length: cuts the selection and puts exactly the given silence in its place. Select a pause and enter `0.10` to shorten it to 0.1 s, or a longer value to lengthen it. |
| Silences list | `+0.25 s @ 0.90 s ×`: × removes one. Cuts and trims drop any silence that ends up inside them. |
| Trim start / end, Fade in / out, Crossfade | exact values. Trimming an edge for the first time adds a 10 ms fade there; set it to 0 if you don't want one. |
| **Reset edits** | back to the unedited recording (the radio filter is kept; it has its own Off) |
| **Transmission interference** | Only on Victor 933's damaged transmission (`vo_scr_m06_00740_victor933`): an automation lane. The interference curve (Points: click to add, drag, double-click or Delete to remove, arrows to nudge; Draw: paint a stretch) sits over the waveform with the 11 phrase guides (live status: masked "hidden" / partial speech level), zoom, Static (synthetic from scratch / MCC Spain sample), Flutter, Reset curve, an MCC Spain/English reference overlay, and play from the cursor (CE processed / original, MCC Spain / English). See `docs/victor933-interference.md`. |
| **Echo** | Off / **Spain echo** / **English echo** / Custom: delay, echo level, repeats, diffusion, damping, slap. For the cryo assistant's intercom ("eco" lines, with the radio presets *Spain/English intercom*). The line gets longer by the ring-out. See `docs/radio-filter.md` §5. |
| **Radio filter** | Off / **Spain radio** / **English radio** / Spain or English **intercom** (eco lines) / Custom, plus low cut, high cut, slope, presence, drive, hiss and **MCC clicks** (Spain's key-up click before the line and the release/squelch after it; on in Spain radio). Changing a value makes it Custom. Heard in the preview like every other edit. See `docs/radio-filter.md`. |

**Removed (owner, 2026-10-09):**
- **Speed** sounded unnatural.
- **Per-line manual gain** is replaced by one **global export gain** for every line (§4.2).
- Saved speed and gain values were cleared once by
  `scripts/validate/migrate_reset_speed_gain.py`. See `docs/migrations/2026-10-09-reset-speed-gain.md`.

**Removed (owner, 2026-10-11):** loudness matching to Spain's recording (with its offset) and its
limiter. They gave a line its own level; the global export gain is now the only level setting. See
`docs/migrations/2026-10-11-reset-loudness-match.md` and `docs/migrations/2026-10-11-remove-limiter.md`.

**Order of operations** (always the same, in M4 and M6): original es-MX WAV → trims, cuts, fades,
inserted silences → **radio filter** (if set) → **echo** (if set) → **global export gain** → **MCC radio clicks** (if set) → 16-bit → CELT. Recipe
times are on the source's timeline (the top waveform).

**About inserted silences:**
- A 0.30 s silence lasts exactly 0.30 s.
- The audio on either side gets a short fade (half the crossfade setting, 10 ms by default), so
  there is no click.
- The silence is digital silence, not room tone. CE's studio dialogue is normally clean, but listen
  for an audible "drop" in noisy lines.

**Rules:**
- **Previews are rendered on the server** about 0.4 s after a change. The first render of a line
  takes about a second; later renders of the same recipe are instant, from the cache in
  `work/m4/preview/`.
- **Save** keeps the recipe in the draft. **Approve audio** approves it together with the audio
  choice, and the confirmation lists the edit. After that it's **read-only**: you can still listen
  and select, but changing or resetting the edit needs **Mark needs rework…** (revision + 1).
- **An edit belongs to one recording.** If you switch the line or its language, the edit is reset.
  Choosing *keep Spain* or several lines clears it when you save.
- **The radio flag** ("Needs radio effect") is a reminder only; editing never changes it. The filter
  itself is the recipe's **Radio filter** (added 2026-10-13). The editor notes when a flagged line has none.
- **Invalid recipes are refused:** for example a trim past the end, overlapping cuts, or keeping
  less than 0.05 s. Nothing is written.

### 4.2 Global export gain (volume for every line)

All Campaign Evolved replacements get one gain at export, **+4 dB by default** (raised from +3 dB on 2026-10-10). It is the same
in the M4 preview and the M6 build.
- **Applied once:** after the edits, and before CELT encoding. It is the only level change.
- **No limiting or compression:** the gain is linear. If a line's peak would pass −1 dBFS, that line
  gets less gain (never less than 0 dB). The editor and the M6 test report list those lines under
  "Global gain".
- **To change it:** create `config/audio_export.json` (copy `config/audio_export.example.json`):

  ```json
  {"schema": "audio-export-config/1", "global_gain_db": 2.0}
  ```

  - The range is −12 to +12 dB. `0` turns it off.
  - Delete the file to go back to the default, +4 dB.
  - The M4 preview picks it up immediately.
  - For M6, **rebuild** the bank (`python scripts/build/m6_build.py …`). Every build records the
    value and its source in `build_manifest.json` (`global_gain`).
- **Your mappings are never changed by this setting.**

### 4.3 Sounds with several takes

**A sound is not a line.** The game plays a *sound*; many sounds (especially AI chatter: Grunt deaths, Marine
barks) have several recorded **takes**, and each time the sound plays the game picks one take at random. In the
list, every Spain take is its own line: rows of the same sound are joined by a bar on the left and say
**Spain take 1/2**, **Spain take 2/2**, and the panel says "Spain take 1 of 2 of this sound". Spain and English
often have a different number of takes.

**One subtitle per sound.** All takes of a sound share one subtitle. If you approve different subtitles on two
takes of the same sound, the build leaves that subtitle unchanged and reports a conflict. *None* (no subtitle) is
written only when every take agrees.

**Three ways to handle a sound with several takes:**

| Way | How | What the game plays |
|---|---|---|
| **One take at a time** (default) | Decide each Spain take as its own line: keep, replace or mute. | Spain's takes, each as you decided it. |
| **Add takes** | Under **Takes of this sound**: *Add as extra take* (the recording selected on the right) or *Add several takes…* (tick several). Approve each added take. | Spain's takes **plus** your added ones. |
| **Replace every take** | Replacement audio → option 4, **Replace every take of this sound**: it lists every Spain take it replaces (press **ES** to hear each), then tick the recordings to play instead and confirm. Approve each take under **Takes of this sound**. | **Only** your takes; Spain's are removed. |
| **Replacement set from your selections** | Already matched the takes one by one? Under **Takes of this sound**, *Preview a replacement set from my selections*, then *Stage*, approve each take, *Switch*. See below. | **Only** the set's takes; equal choices become one take. |

The header of **Takes of this sound** says which way the sound uses (*per take*, *Spain + added takes*, *replacement
set*, *replacement set staged*) and sums it up, e.g. **3 original MCC takes → 2 replacement takes**.

**Turning your per-take work into a replacement set** (`docs/replacement-set-conversion.md`):
1. **Preview** (nothing is saved). If take 1 → ce1, take 2 → ce2 and take 3 → ce1, you get two takes, [ce1, ce2]:
   the same recording with the same language and the same edits is one take. The same recording with different trims
   or effects stays two. Only audio you **chose** counts; a recording that is only matched does not.
2. Points that need your review are listed with a tick box each: a take with no decision or kept as Spain (the set
   removes it), a muted take (the set removes it instead of playing silence), a take marked Needs rework, a subtitle
   text on a sound without subtitles, and so on. Things that can't become a take (missing recording, bad edit) block
   it.
3. **Stage.** New takes are added as drafts. Nothing changes in a build yet: your line decisions still apply.
4. **Approve the takes.** *Approve unchanged converted takes…* lists the takes that carry exactly audio you already
   approved: unchanged since staging, still valid, no review point. It also lists the ones it leaves out and why
   (for example, merged with a draft line). Confirm the list to approve those takes; it's a new approval of each
   take, not a copy. Approve the others one by one. Nothing is approved if anything changed since the list was shown.
5. **Switch to the replacement set**, once every take is approved and can be built. Its lines' decisions stop
   applying (approved ones are marked Needs rework, then removed, in one save) and are kept in the set's record. This
   changes your decisions and the next build; it doesn't touch the installed game.
6. Changed your mind? **Cancel the conversion** while staged: your lines were never touched, and approved takes are
   marked Needs rework, then removed. Or **Undo the replacement set** after switching: a preview shows what comes
   back and any conflict first. Undo brings the line decisions back exactly, approvals included (as long as they
   still match the catalogs), and the build is what it was before.

After the switch, if a take of the set is marked Needs rework or its recording changes, the next build leaves that
take out (the panel says so). If no take is left, the build plays Spain's own recordings for that sound.
"Needs a new recording" and "needs radio effect" reminders of the replaced lines stay visible: on the line, in the
list filters and counters, and under *Takes of this sound*.

The **Take sets** page lists every sound with several takes and what its set would be. Filter it by *ready*,
*needs review*, *blocked*, *staged*… and use *Stage N ready* or *Switch N staged* to do many at once. Both ask
you first, and nothing happens if any of those sounds changed since the list loaded. Sounds that need review are
staged one by one from the line panel.

Good to know:
- A **muted** take is still picked by the game: it plays silence. If you want a sound without silent takes, use
  *Replace every take* instead of muting one of them.
- *Add takes*, *Replace every take* and replacement sets are only for sounds **without** a subtitle (barks, deaths,
  chatter). Story lines are always decided one take at a time.
- *Replace every take* clears the decisions of that sound's lines (the confirmation lists them first). They are kept
  in the set's record: *Undo the replacement set* brings them back, approvals included. *Back to Spain's takes* turns the
  set off and leaves the lines undecided.
- Until at least one of your takes is approved, the build keeps Spain's takes.
- While a sound plays your own takes, its lines show **own set 6/6** (approved/total) and their M/A/S marks show
  the sound's state; the line itself has nothing to save or approve.
- The order of added takes doesn't change how often each one plays.
- A build with added or replaced takes also writes the Spanish sound index, and Build & Test installs and restores
  both together. The in-game check of a build that removes Spain's takes is still pending.

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
