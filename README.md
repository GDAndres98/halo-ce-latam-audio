# Halo MCC Localization Studio

A local tool for a Latin American Spanish localization of *Halo: Combat Evolved* inside
*Halo: The Master Chief Collection* (MCC). You match MCC dialogue lines to *Halo: Campaign Evolved*
(CE) recordings and subtitles by hand, approve them, build replacement audio and subtitle files for
the game, and restore the originals.

Nothing is automatic: tools never match, approve or rewrite decisions. Game files and recordings are
never committed. Read [CLAUDE.md](CLAUDE.md) for the project rules and [docs/roadmap.md](docs/roadmap.md)
for the plan.

## Architecture

| Part | Where | Role |
|---|---|---|
| API server | `scripts/ui/m4_server.py`, `m4_app.py`, `build_api.py` | Python standard library only. Serves the JSON API and audio. |
| Decisions store | `scripts/common/mapping_store.py`, `mapping_db.py` | The only writer of decisions. SQLite database, JSON export. |
| Studio UI | `frontend/` | Vue 3 + TypeScript + Vite. Talks to the API. |
| Classic page | `scripts/ui/m4.html` | The original matching page. Still needed for matching, approvals and edits. |
| Build and install | `scripts/build/m6_build.py`, `m6_install.py` | Offline builds under `work/m6/`. Installing is separate and needs approval. |
| Catalogs and extraction | `scripts/catalog/`, `scripts/extraction/` | Build the dialogue catalogs under `work/`. |
| Validation | `scripts/validate/` | Read-only checks and one-time migrations. |

**Source of truth.** `mappings/manual_mappings.db` (SQLite) holds the decisions, the custom subtitles,
the mission progress and their change history. `mappings/manual_mappings.json` is an export of it,
written only by the store and checked on every read. Editing that JSON by hand is refused.
Deleting the database re-imports the JSON and loses the history, so do not delete it.

## Repository layout

```
scripts/common/     parsers, the store, audio processing, CELT and FSB5 writers
scripts/catalog/    catalog builders (CE and MCC)
scripts/extraction/ FSB decoding and CE audio export
scripts/build/      M6 build and install tools
scripts/ui/         API server, application logic, classic page, build API
scripts/validate/   validator and migrations
scripts/discovery/  research and experiments (not used by the Studio)
frontend/           Vue Studio (src/views, src/components, src/api)
mappings/           decisions (database + export), local custom text, progress
schemas/            JSON schemas for every user-owned file
tests/              unittest suite (Python)
docs/               design notes and reverse-engineering research
work/               generated, git-ignored: catalogs, audio, builds, backups
```

## Requirements

- Python 3.12 (standard library only for the server; `ffmpeg` on the PATH for the audio editor).
- Node.js 20 or newer, for the frontend.
- Your own legally obtained game files. Set their locations in `.env` (see `.env` comments; the
  folders are read-only to this project).
- vgmstream-cli and `libcelt-0110.dll` (from vgmstream), for decoding and CELT encoding. Defaults are in
  `scripts/ui/m4_server.py`; override them with the command-line options.

Build the catalogs once before the first run (see [docs/m4-user-guide.md](docs/m4-user-guide.md) §1).

## Install and run

```sh
# Frontend dependencies, once
cd frontend
npm install

# Run the Studio: the API server and the Vite dev server together
npm run dev
# then open http://localhost:5173
```

`npm run dev` starts `scripts/ui/m4_server.py` on 127.0.0.1:8765 and the Vite dev server on port 5173,
which forwards `/api` and `/audio` to the API. The classic page is at http://127.0.0.1:8765/.

To run only the API, from the repository root: `python scripts/ui/m4_server.py --no-open`.

## Screens

- **Dashboard:** progress per MCC level, Campaign Evolved missions, and whether the build pins match the
  installed game.
- **Dialogues:** lines for one level, filtered by status and searched (case- and accent-insensitive,
  Spanish and English text, identifiers, speakers). The filter and search are kept in the URL.
- **Line:** both recordings and the CE candidates, side by side, with the decision status and the
  subtitles in the game. Read-only for now.
- **Build & Test:** existing builds with validation and stale-decision status; dry-run builds of
  selected levels; the install actions, which are shown but disabled.

## Mapping and approval workflow

1. Match a line to CE lines on the classic page, or record a draft.
2. Choose the audio and the subtitle independently. An approval is always your own action.
3. Approved objects are immutable. Changing one means "needs rework", which bumps its revision.
4. Mission progress is set by you. A level is ready to build when every line is decided and has
   approved audio.

Every save keeps the previous file in `mappings/.history/` and the per-line history in the database.

## Building and restoring the game files

The Studio never installs anything. The steps are:

1. **Dry run:** `Build & Test` → choose levels → `Dry run build`, or
   `python scripts/build/m6_build.py --level a10 --name a10_test`. This writes only under `work/m6/`.
   Check that the build is not marked **stale**; rebuild it if the decisions changed.
2. **Install (needs your approval for that build, MCC closed):**
   `python scripts/build/m6_install.py --build <name> preflight`, then `install`. `status` shows the
   installed state. Read the build's `install_rollback.md` first.
3. **Restore originals:** `python scripts/build/m6_install.py --build <name> rollback`. It restores the
   files from the verified backups and checks them against the pinned originals.

Subtitle deployment is **disabled**. The variable-length subtitle writer has not been validated in the
game (see [docs/m6-build.md](docs/m6-build.md) §4).

## Testing and debugging

```sh
python -m unittest discover -s tests       # Python suite (about 25 s)
cd frontend && npm run build               # type check and production build
```

Debugging tips:
- The API returns `{"error": ..., "details": ...}` with a status code. 409 means a stale page or a
  conflict, such as a file changed outside the Studio.
- A file that "differs from the database" was edited outside the Studio. Restore it from git or from
  `mappings/.history/`, then reload.
- Startup takes about 1.5 s. Read timings: slot lists about 8 ms, CE search about 20 ms.

## Known limitations

- Matching, approvals and edits still happen on the classic page. The Studio currently browses and
  plays.
- The line list shows up to 500 rows per request, without virtualised scrolling.
- Audio editing (trims, cuts, loudness) is available on the classic page only.
- Subtitle deployment is disabled, and installs are not started from the UI.
- Nothing has been checked in a browser yet; the UI is verified by type check, build and API tests.
- The per-save file copies in `mappings/.history/` grow by about 1.3 MB per save. Pruning is a decision
  for the owner.
- Publishing to Steam Workshop is out of scope and needs separate approval (see CLAUDE.md).
