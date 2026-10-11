# Mapping storage: SQLite, the JSON export, and recovery

## Design

| What | Where | Role |
|---|---|---|
| Decisions (536 slots) | `mappings/manual_mappings.db`, table `slots` | **Source of truth.** One row per slot; `body` is the slot's exact JSON, the status columns are derived from it and indexed. |
| Per-slot history | same database, `slot_history` | Before/after body of every changed slot; `reason` is NULL for a Studio save, `import:<sha256>` for a JSON import (schema v4). |
| Custom subtitles, mission progress | same database, `documents` (+ `document_history`) | Source of truth for `manual_mappings.local.json` and `mission_progress.json`. |
| `mappings/manual_mappings.json` | file, committed to git | **Export.** Rewritten from the database after every save (atomic temp + fsync + rename). Read by M6, the validator and git. |
| `mappings/.history/` | files | The previous JSON bytes before each save, database backups before each import, files replaced by an export. |

Every read of the decisions goes through `scripts/common/mapping_store.py`, which compares the file's SHA-256
with the export hash the database stored in the same transaction as the rows:

- **equal**: the file is read (M6, the validator and the Studio all see the database's state);
- **equal after converting CRLF to LF**: same content written with Windows line endings. It is read as
  in sync, and the next save writes LF again;
- **different**: refused (HTTP 409 in the Studio, an error in M6). Nothing is overwritten, and nothing is
  imported on its own, at start-up or otherwise.

A save commits SQLite first (with `pending_json_write = 1`), then writes the JSON, then clears the flag. A crash
between the two leaves the flag set, and the next read finishes the JSON write. `PRAGMA user_version` versions
the database. Upgrades are additive and run on open: v2→v3 added the documents tables, v3→v4 added
`slot_history.reason`.

The approval rules (`check_transition`: tools never approve; approved objects change only through Needs rework
with revision + 1) apply to every Studio save. An **import** is the one exception, because it is the owner
explicitly choosing a file's decisions. It always shows its preview first, including approvals it adds or
removes.

## When the file and the database disagree

Open **Data** in the Studio, or use the command line with the Studio closed:

```sh
python scripts/validate/mapping_sync.py status
python scripts/validate/mapping_sync.py preview-import --report work/reports/mapping_import_preview.json
python scripts/validate/mapping_sync.py import --file-sha256 <from preview> --db-sha256 <from preview>
python scripts/validate/mapping_sync.py export --file-sha256 <from status, or none>
```

- **Import from JSON**: use it when the file holds what you want (you edited it, or restored it from git on
  purpose). The preview lists every changed slot, with the database and file states side by side, and the
  approvals added or removed. The import needs the two hashes from that preview, so if the file or the
  database changed in between, it is refused. It backs up the database (`.history/manual_mappings.<time>.before-import.db`,
  SQLite online backup, integrity-checked), records each changed slot in `slot_history`, and keeps the
  original file bytes if they were CRLF.
- **Export database to JSON**: use it when the database holds what you want (the file was changed by
  mistake). The file it replaces is kept as `.history/manual_mappings.<time>.<sha>.replaced-by-export.json`.

Before either, close other Studio windows. Every action is logged, and nothing is deleted.

## Why it happened, and what prevents it

`core.autocrlf` is `true` in this repository. Any git operation that writes `manual_mappings.json` (checkout,
stash, restore, VS Code's "Discard changes") wrote it with CRLF. The bytes then differed from the LF export the
database recorded, and the Studio refused the file, even though nothing but line endings had changed.

- `.gitattributes` now has `mappings/*.json text eol=lf`, so git writes these files exactly as the Studio does.
- A CRLF-only difference is read as in sync (see above). It no longer blocks the Studio.
- A real outside change is still refused. The error message points to the Data page, and import and export
  are explicit, previewed, confirmed and backed up.

## Recovery of 2026-10-10 (owner-authorized)

**Symptom.** The Studio refused to load: *"manual_mappings.json differs from manual_mappings.db: it was edited
outside the Studio."*

**Evidence.**

- 22:21:01–22:22:44: three Studio saves on `m-000193` / `es:A30_090_cortana#0`, each recorded in
  `slot_history` and `.history/`:
  1. audio marked Needs rework;
  2. subtitle marked Needs rework;
  3. unmatched, keep Spain.
- 22:55:08: commit `d507049`. The A30 change was still uncommitted.
- 22:55:48: `manual_mappings.json` rewritten with CRLF. With CR removed, it is byte-identical to the
  committed version (`da4529be…`, also the snapshot before the A30 change). There is no reflog or stash
  entry. That fits "Discard changes" or `git restore`; the Studio never writes CRLF.
- The database still held the reworked A30 state.

**Discrepancy.** Exactly one slot, `m-000193`. In the file it is matched to `vo_scr_m02_00110_cortana#0`,
with audio and subtitle approved (rev 1, 2026-10-08). In the database it was unmatched, with audio and
subtitle needs_rework (rev 2). The other 535 slots, the pins, the custom subtitles and the mission progress
were identical.

**Decision.** The owner chose the JSON as authoritative, including returning A30 to its approved state.

**Steps.**

1. Stopped the Studio API and Vite.
2. Took a verified backup of all of `mappings/`: raw database copy, SQLite online backup with an `ok`
   integrity check, and a SHA-256 manifest. Saved in `work/recovery/20261010-mapping-sync/backup/`.
3. Wrote the discrepancy report: `discrepancy.json`.
4. Rehearsed the import on a copy: `rehearsal/`.
5. Ran `mapping_sync.py import` on the real data. Result in `import-result.json`; database backup
   `mappings/.history/manual_mappings.20261010T230626900272.before-import.db`.
6. Verified the result:
   - the database export equals the file (`da4529be…`), status `in_sync`;
   - the only database differences from the backup are that slot, one new history row
     (`import:15c34858…`) and the sync metadata (`db-before-after.json`);
   - the 3 earlier history rows were kept;
   - the validator reports 0 drift;
   - the M6 planner plans A30 as an approved replacement;
   - the Studio serves A30 as approved with no sync error.

The database also went from schema v3 to v4 (the additive `reason` column). The v3 file is the backup
above.
