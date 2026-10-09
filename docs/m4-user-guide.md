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
  - `--oodle-dll`.
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

Keyboard: `J` / `K` next / previous slot, `Space` plays Spain, `1`–`9` plays candidate 1–9 (es-MX).

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

Slot filters (left):
- undecided, matched, no equivalent, deferred;
- audio / subtitle not approved;
- needs rework;
- **needs radio effect**;
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
5. **Subtitle,** independently of the audio:
   - *keep MCC text*;
   - *CE text* (pick the line and the culture; cultures without text are disabled);
   - *custom*;
   - *none*.
6. **Save** keeps a draft. **Approve audio** / **Approve subtitle** save and approve. An approved
   part is read-only. To change it, use **Mark needs rework…**, which raises its revision by one.

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
  - plus audio caches under `work/`.

  Every write checks the loaded hash, validates the schema, backs up to `mappings/.history/` and
  replaces the file atomically.
- **It never:**
  - suggests, ranks or pre-fills a match;
  - approves anything without your click;
  - changes an approved decision;
  - writes `verifications.json`, `mission_map.json` or the catalogs;
  - touches game files or banks.
- Run `python scripts/validate/validate_project.py` before committing `mappings/`.
- **The E3 test pair** (`es:A10_010_cryotech#0` ← `vo_scr_m01_00460_cryotech#0`) appears only as
  the past check `v-000019`. It is not a mapping until you decide it here.
