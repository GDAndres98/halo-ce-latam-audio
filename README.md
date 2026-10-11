# Halo MCC Localization Studio

A local tool for a Latin American Spanish localization of *Halo: Combat Evolved* inside
*Halo: The Master Chief Collection* (MCC). You match MCC dialogue lines to *Halo: Campaign Evolved*
(CE) recordings and subtitles by hand, approve them, build replacement files for the game, and restore
the originals.

Nothing is automatic: tools never match, approve or rewrite decisions. Game files and recordings are
never committed. Read [CLAUDE.md](CLAUDE.md) for the project rules and [docs/roadmap.md](docs/roadmap.md)
for the plan.

## Architecture

| Part | Where | Role |
|---|---|---|
| API server | `scripts/ui/m4_server.py`, `m4_app.py`, `build_api.py` | Python standard library only. JSON API and audio. |
| Decisions store | `scripts/common/mapping_store.py`, `mapping_db.py` | The only writer of decisions. SQLite database, JSON export. |
| Studio UI | `frontend/` | Vue 3 + TypeScript + Vite. Talks to the API. |
| Classic page | `scripts/ui/m4.html` | The original M4 page. Kept as a reference until the Studio covers all of it. |
| Build and install | `scripts/build/m6_build.py`, `m6_install.py` | Offline builds under `work/m6/`. Installing is separate and needs approval. |
| Catalogs and extraction | `scripts/catalog/`, `scripts/extraction/` | Build the dialogue catalogs under `work/`. |
| Validation | `scripts/validate/` | Read-only checks and one-time migrations. |

**Source of truth.** `mappings/manual_mappings.db` (SQLite) holds the decisions, the custom subtitles,
the mission progress and their change history. `mappings/manual_mappings.json` is an export of it,
written only by the store and checked on every read. A JSON file edited by hand is refused. Do not
delete the database: removing it re-imports the JSON and loses the history.

## Repository layout

```
scripts/common/     parsers, the store, audio processing, CELT and FSB5 writers
scripts/catalog/    catalog builders (CE and MCC)
scripts/extraction/ FSB decoding and CE audio export
scripts/build/      M6 build and install tools
scripts/ui/         API server, application logic, build API, end-to-end helpers
scripts/validate/   validator and migrations
frontend/           Vue Studio (src/views, src/components/match, src/matching, e2e)
mappings/           decisions (database + export), custom text, progress
schemas/            JSON schemas for every user-owned file
tests/              unittest suite (Python)
docs/               design notes and reverse-engineering research
work/               generated, git-ignored: catalogs, audio, builds, backups
```

## Requirements

- Python 3.12 (standard library for the server; `ffmpeg` on the PATH for audio previews).
- Node.js 20 or newer, for the frontend. Microsoft Edge, for the browser test.
- Your own legally obtained game files, with their locations set in `.env`. This project only reads them.
- vgmstream-cli and `libcelt-0110.dll` (from vgmstream), for decoding and CELT encoding. Defaults are in
  `scripts/ui/m4_server.py`; override them with the command-line options.
- The catalogs under `work/`, built once (see [docs/m4-user-guide.md](docs/m4-user-guide.md) §1).

## Install and run

```sh
cd frontend
npm install

npm run dev          # starts the API and the Vite dev server together
# then open http://localhost:5173
```

`npm run dev` starts `scripts/ui/m4_server.py` on 127.0.0.1:8765 and Vite on port 5173, which forwards
`/api` and `/audio` to the API. The classic page is at http://127.0.0.1:8765/.

## Matching workflow

Open **Matching**. The screen has three columns.

- **Left: MCC lines.** Pick a level, filter (unmatched, draft, approved, needs rework, keep Spain audio,
  radio, different-but-fits), and search by ID, speaker or subtitle text. Accents and case are ignored;
  partial words work. Play a line with the ▶ button.
- **Centre: the decision for the selected line.** Both recordings and their durations side by side.
  Then:
  1. **Replacement audio:** keep Spain's audio, or use one of the matched Campaign Evolved recordings.
  2. **Audio editing:** trims and cuts on the replacement, with a waveform and a preview as the build
     would render it. Reset returns to the original. The original WAV is never changed.
  3. **Subtitle:** Spain's, Campaign Evolved's (es-MX or EN where it exists), your own LATAM Spanish text,
     or none (a decision to show no subtitle, shown differently from a missing text).
  4. **Flags and notes:** radio effect (a flag only; no processing) and "different but fits".
  5. **Save and approve:** save the draft, then approve audio and subtitle separately. Approval is always
     a button press with a confirmation. An approved decision is read-only until you mark it *Needs rework*.
- **Right: Campaign Evolved candidates.** Search by ID, English or LATAM text, pick a mission, hide
  recordings already used elsewhere. Results stay in catalog order. Nothing is selected for you: use
  **Use this recording** to choose one. A recording with no subtitle says so.

**Resuming.** Everything you save is in `mappings/manual_mappings.db`. The address keeps the selected
line and every filter, so reloading or using Back returns you to the same place. Unsaved typing is kept
in the browser session for the same stored version of the line; leaving a line with unsaved changes asks
first.

**Keyboard** (not while typing in a field). The keys follow the classic M4 page where it had them:

| Key | Action |
|---|---|
| `j` / `k` | next / previous MCC line |
| `Space` (or `m`) | play Spain's recording |
| `1` to `9` | play the first nine candidates (es-MX); plays only, selects nothing |
| `↑` / `↓` | move the candidate highlight; selects nothing |
| `s` | use the highlighted recording as the replacement |
| `e` / `n` | play the highlighted (or chosen) recording in es-MX / English |
| `/` / `\` | focus the MCC search / the candidate search |
| `Ctrl+S` | save the draft |
| `Esc` | stop playback |

Approval has no shortcut.

**Panels.** Drag the dividers between the three panels, or focus a divider and use the arrow keys (Shift for
bigger steps). Each side panel has a minimum width, and the centre panel keeps at least 420 px. Widths are
kept on the computer and restored on the next visit; *Reset layout* returns to the defaults. On a narrow
window the panels stack and the dividers are hidden.

**Concurrency.** Every save sends the hashes the page was loaded from. If another window changed the
line, the save is refused with nothing written, and your edits stay on screen: use *Reload and keep my
edits*, check them, and save again.

## Global audio gain

Build & Test has a *Global audio gain* card. It is one number for every Campaign Evolved replacement,
applied once when a build is exported. The default is **+4 dB**, the range is −12 to +12 dB, and *Reset to
default* returns to +4 dB. The value is saved in `config/audio_export.json` (git-ignored; the previous file is
kept in `config/.history/`).

Changing the gain does not rebuild anything. Every build made with another gain is marked **stale**, with the
reason, and stays as it is until you rebuild it.

Processing order for each replacement, as the build applies it:

1. Sources are converted to 44.1 kHz mono.
2. The edit recipe: trims, cuts, fades and inserted silences.
3. Optional loudness match to Spain's recording (only where chosen on the line).
4. The global gain, applied once, linearly and never limited. A line that would peak above −1 dBFS gets less,
   and the build reports it.
5. Rounding to 16-bit, then encoding for the game (CELT).

Previews in the editor use the same steps, so what you hear is what the build writes.

## Theme

Colours, fonts and radii are defined once, in `frontend/src/theme/tokens.ts`. The palette is original and
inspired by the interfaces of Halo: Combat Evolved (dark navy and charcoal, olive accents, a restrained cyan
focus ring). No Halo artwork, fonts or logos are used. Unit tests check the contrast of every text colour
against its surface (WCAG AA), and the browser checks run the same test on the live pages.

## Building and restoring the game files

The Studio does not install anything. The steps are:

1. **Dry run:** Build & Test → choose levels → Dry run build, or
   `python scripts/build/m6_build.py --level a10 --name a10_test`. This writes only under `work/m6/`.
   A build marked **stale** was made from older decisions; rebuild it before any install.
2. **Install** (needs your approval for that build, MCC closed):
   `python scripts/build/m6_install.py --build <name> preflight`, then `install`. `status` shows the
   installed state. Read the build's `install_rollback.md` first.
3. **Restore originals:** `python scripts/build/m6_install.py --build <name> rollback`.

Subtitle deployment is **disabled**: the variable-length subtitle writer has not been validated in the
game (see [docs/m6-build.md](docs/m6-build.md) §4).

## Testing

```sh
python -m unittest discover -s tests          # Python suite (about 25 s)
cd frontend
npm run typecheck                             # Vue and TypeScript
npm test                                      # unit tests of the matching rules
npm run build                                 # type check and production build
npm run test:e2e                              # browser test of the workflow (needs Microsoft Edge)
npm run test:ux                               # browser checks: panels, gain, theme, responsive, keyboard
npm run compare:m4                            # the same task in the classic page and the Studio, timed
```

The browser test starts its own API server and Vite server on a copy of your mapping data (made by
`scripts/ui/e2e_fixture.py`). It drives Microsoft Edge through the workflow: choose a recording, save,
write a subtitle, approve each part, flag radio, trim and preview, restart both servers, check that every
decision persisted, check that approved decisions are protected, check the M6 planner
(`scripts/ui/e2e_check_m6.py`), and check that the real mapping files did not change. Its screenshots and
report go to `frontend/e2e/out/`, which is git-ignored because the screenshots show game text.

Debugging: the API returns `{"error": ..., "details": ...}`. A 409 means a stale page or a protected
decision; a file that "differs from the database" was edited outside the Studio.

## Known limitations

- Audio editing covers trims and cuts. Silences and fades remain in the classic page.
- The candidate list shows the mission and folder, not a speaker: the Campaign Evolved catalogue does not
  record speakers.
- Silences, the validation footer, level status and several recordings for one subtitle are on the classic
  page only (see docs/studio-ux-comparison.md).
- The line list shows up to 300 lines per page ("show more"), not virtual scrolling.
- Radio effects are only flagged; no processing is applied yet.
- Subtitle deployment is disabled, and installs are not started from the Studio.
- The per-save file copies in `mappings/.history/` grow by about 1.3 MB per save. Pruning is a decision
  for the owner.
- Publishing to Steam Workshop is out of scope and needs separate approval (see CLAUDE.md).
