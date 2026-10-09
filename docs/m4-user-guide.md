# M4 matching UI — user guide

**For:** the project owner, matching MCC lines to Campaign Evolved lines one level at a time.
Design and rules: [`m4-matching-ui-design.md`](m4-matching-ui-design.md). Catalogs:
[`campaign-catalog.md`](campaign-catalog.md).

## 1. Start it

```
python scripts/catalog/build_ce_catalog.py --all               # once, or after a CE update
python scripts/catalog/build_mcc_catalog.py --all --no-audio   # once, or after an MCC update
python scripts/ui/m4_server.py                                 # opens http://127.0.0.1:8765
```

- The server listens on **127.0.0.1 only** and uses the Python standard library only.
- `Ctrl+C` stops it.
- Options:
  - `--port`;
  - `--no-open` (don't open a browser);
  - `--vgmstream-cli` (default `D:/Tools/vgmstream-r2117/vgmstream-cli.exe`);
  - `--oodle-dll` (default: FModel's bundled DLL, read-only).
- **Audio is decoded the first time you press ▶,** which takes under a second, and is cached
  under `work/`.
  - MCC audio comes from the pinned bank copies in `reference-audio/stage1/`.
  - CE audio comes from the installed paks, read-only, after a hash check against the catalog.
- **Links:** `http://127.0.0.1:8765/#level=a10&slot=es%3AA10_140_cryotech%230` opens one slot
  directly.

## 2. The screen

| Area | What it does |
|---|---|
| Header | Pick the level (grouped: campaign, cutscene, generic). Progress shows decided / audio approved / subtitle approved. Level status sets the workflow step (§4). |
| Left: MCC slots | Every Spanish slot of the level. Filter by state, or search the tag and its SU/SP text. ● matched, grey = no equivalent, orange = deferred. **A** / **S** = audio / subtitle approved, red = needs rework, `st` = stereo. |
| Middle: slot | ▶ Spain and ▶ English recordings with durations. SU (Latin America) and SP (Spain) subtitle text. Past checks from `verifications.json` (read-only). Then the decision: match, audio, subtitle, notes. |
| Right: CE lines | Campaign Evolved lines in **catalog order**. Scope: the missions you mapped for this level, all missions, or one mission. The search filters on ID and es-MX / en / es-ES text (accents and case ignored). It never ranks or suggests anything. |
| Footer | The validator's result after the last save. |

Keyboard: `J` / `K` next / previous slot, `Space` plays Spain, `1`–`9` plays candidate 1–9 (es-MX).

## 3. Deciding one slot

1. **Listen** to Spain (and English), then to the candidates.
2. **Match:** click **+ use for this slot** on each CE line that corresponds. Order them with
   ↑ / ↓ (several lines are concatenated in that order). Or choose *no equivalent* or *deferred*.
3. **Audio:** *keep Spain*, or *CE line(s) from the match* in es-MX (en and es-ES are allowed
   too). The duration difference against Spain is shown as a fact. *Flag for radio effect* is a
   v1.1 note only.
4. **Subtitle,** independently of the audio:
   - *keep MCC text*;
   - *CE text* (pick the line and the culture);
   - *custom*, typed in the box;
   - *none*.

   Custom text is stored only in the git-ignored `mappings/manual_mappings.local.json`.
5. **Save** keeps a draft. **Approve audio** / **Approve subtitle** save and approve. An approved
   part is read-only. To change it, use **Mark needs rework…**, which raises its revision by one.

**Errors:**
- **"changed since this page loaded it" (409):** the file was saved from somewhere else (another
  tab, for example). Reload the slot and redo the edit.
- **"not valid yet" (422):** the decision breaks a rule, for example CE audio from a line that
  isn't in the match. The message lists what to fix. Nothing was written.

## 4. Level workflow

| Step | Where | Level status |
|---|---|---|
| 1–4. Pick the level, review its lines, match, approve audio and subtitles | M4 | `in progress` |
| 5. Build the replacements from approved decisions | M6 (not built yet) | `ready for build`: allowed only when every slot is decided and has approved audio |
| 6. Test the level in MCC | M7, owner-approved install only | `tested in MCC`: asks for confirmation and an optional `v-NNNNNN` entry |
| 7. Mark the level as reviewed | M4 | `reviewed`: asks for confirmation |

The status is stored in `mappings/mission_progress.json` (`mission-progress/1`). The validator
warns if a level is marked ready or later while its slots no longer support it, for example after
a *needs rework*.

## 5. What it writes, and what it never does

- **It writes only these files, through the protected store:**
  - `mappings/manual_mappings.json`;
  - `mappings/manual_mappings.local.json`;
  - `mappings/mission_progress.json`;
  - plus audio caches under `work/`.

  Every write checks the loaded hash, validates the schema, backs up to `mappings/.history/` and
  replaces the file atomically.
- **It never:**
  - suggests, ranks or pre-fills a match;
  - approves anything without your click;
  - changes an approved decision;
  - writes `verifications.json` or `mission_map.json`;
  - touches game files or banks.
- Run `python scripts/validate/validate_project.py` before committing `mappings/`.
- **The E3 test pair** (`es:A10_010_cryotech#0` ← `vo_scr_m01_00460_cryotech#0`) appears only as
  the past check `v-000019`. It is not a mapping until you decide it here.
