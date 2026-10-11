# Studio performance: architecture, measurements, decisions

Measured 2026-10-10 on the development machine, on disposable copies of the real data: 536 mappings,
1,903 MCC tags, 5,696 Spanish slots, 3,754 CE records and 18k+ CE lines. Commands are at the end.

## 1. Audit: how data flows

| Data | Stored in | Read by |
|---|---|---|
| Mapping decisions | SQLite `mappings/manual_mappings.db` (`slots`, one JSON body per slot, indexed status columns, `slot_history`). **Source of truth.** | Every API read goes through `mapping_store.load`, which checks the JSON export's hash against the database and parses the export (1.3 MB, about 12 ms). |
| JSON export `mappings/manual_mappings.json` | file, rewritten after each save | M6, the validator, git. Never read back unless it matches the database (see [mapping-storage.md](mapping-storage.md)). |
| Custom subtitles, mission progress | SQLite `documents`, with JSON exports | the same contract |
| MCC and CE catalogs | `work/*/catalog/*.jsonl` (generated, read-only) | loaded once at server start-up (1.3 s) into memory, with accent-folded search text per line |
| Audio | WAVs decoded on demand into `work/` | streamed by `/audio/*` |

Answers to the audit questions:

- **Is SQLite used, and is it the source of truth?** Yes for decisions and user documents, since the
  Studio cutover. Saves commit SQLite first, then write the JSON (with a crash-recovery flag). Approval rules
  are enforced in `mapping_store.check_transition` before anything is written. History rows are written in
  the same transaction as the slot rows.
- **Indexes:** status columns, `mcc_tag`, `slot_history.mapping_id`. Reads use the file export, not
  queries, so these indexes are not on a hot path. Nothing in the profile justified adding more.
- **WAL:** not enabled (journal mode `delete`). One process writes, and a save is one short transaction
  (about 5 ms commit). WAL would add `-wal`/`-shm` files to back up for no measured gain.
- **Migrations:** `PRAGMA user_version`, additive upgrades on open. v4 added `slot_history.reason`.
- **Catalog search:** a linear scan over pre-folded strings in memory, 10–26 ms for any query across all
  missions (below). **SQLite FTS5 was evaluated and not adopted.** Its tokenizer matches whole tokens or
  prefixes, so it cannot do the substring matches the Studio supports (`00460`, `acantil` inside
  `acantilado`) without a trigram tokenizer. Trigrams do not fold diacritics, so accent folding would
  need the same pre-folded column anyway. At these catalog sizes the scan already meets the 150 ms target
  by a factor of six.

## 2. What was slow, measured

API, in-process (`scripts/ui/profile_api.py`), warm median:

| Operation | Before | After |
|---|---|---|
| select a line (`/api/slot`) | 9 ms | 10 ms |
| open / switch level (`/api/slots`) | 12 ms | 12 ms |
| MCC search across all levels | 20 ms | 23 ms |
| CE search across all missions (word, accent-folded, phrase, partial id) | 19–21 ms | 21–26 ms |
| **save draft** | **5,659 ms** (p95 5,923) | **268 ms** (p95 386); 123 ms without the background report |
| **approve / needs rework** | **5,739 ms** | **266 ms** (p95 388) |

Reads were never the problem. A save was, and its 5.7 s broke down (cProfile) as:

1. **About 5.4 s: the full project validator ran synchronously after every save.** It re-read and
   schema-checked all 210 catalog files (about 28k records) that cannot change while the server runs,
   then rebuilt the CE index.
2. About 0.3 s in the store: two full-document schema checks, the 1.3 MB document serialized twice with
   Python's pure-Python indenting encoder, all 536 slot bodies encoded twice, and every database row
   deleted and re-inserted.
3. About 50 ms: a deep copy of the whole document per save, plus three parses of the export.

Browser, Playwright (`npm run perf`, Microsoft Edge). Each iteration takes a different undecided `a30`
line: select → search a CE recording → use it → save. Medians of the warm iterations:

| Step | Studio before | Studio after | Classic M4 before | Classic M4 after |
|---|---|---|---|---|
| select (heading + original waveform loaded) | 135 ms | **59 ms** | 60 ms | 116 ms |
| search (type → row shown) | see note | 324 ms | see note | 312 ms |
| use recording | 44 ms | 32 ms | 27 ms | 23 ms |
| save (click → confirmation) | 6,033 ms | **360 ms** | 6,168 ms | 355 ms |
| **total per line** | **6,233 ms** | **1,103 ms** (p95 1,135) | 6,270 ms | 1,174 ms (p95 1,498) |
| next line with `j` | 76 ms | **44 ms** | — | — |
| open workspace (cold) | 1,496 ms | 978 ms | — | — |

Note: the "before" run cleared the search to empty, which already listed the target recording, so its
search step (16 ms) under-measured. The after runs clear to a query with no results first. The search
step is mostly the 250 ms typing debounce plus a 20 ms request. The previous comparison (classic 6.2 s,
Studio 8.6 s) was dominated by the same 5.7 s save in both apps: the classic page calls the same API.

## 3. What changed

Server:

- **Validation off the save path.** The save still validates the new decision before writing (schema,
  protections, per-slot rules) and refuses on error, exactly as before. The project-wide report then runs
  in a background thread (`M4App.validate_soon`). Saves in quick succession share one run. The response
  carries the last complete report and `validation_pending`.
- **Catalog validation cache** (`validate_project.run(catalog_cache=...)`): records, findings and indexes
  are reused for catalog files whose size and mtime, and whose `build.json`, are unchanged. Rebuilding a
  catalog changes those, so the cache refreshes on its own. A warm report takes about 150 ms (was 5.4 s).
- **Incremental store writes:**
  - only changed slots are schema-checked (`mapping_store.schema_errors`; equivalence argued in the code
    and tested against full validation);
  - only changed slots are encoded;
  - only changed rows are written (`mapping_db.store_document`);
  - the export is assembled from the stored bodies (`serialize_from_bodies`), byte-identical to a full
    serialization (tested on the live file).

  Approval protections, stale-save refusal, history and the crash-recovery flag are unchanged.
- **The save response includes the saved list row and the level's progress** (server values), so the page
  updates in place.
- **Audio responses are cacheable:** `Cache-Control: private, no-cache` with an ETag (size + mtime). A
  revisited line, or the same clip in a second player, is revalidated with a body-less 304 instead of
  being downloaded again. A rebuilt file has a new ETag.

Frontend (no redesign):

- After a save, only that row and the counters change. The list, the selection, the scroll position, the
  filters and the candidate search stay. Previously the list was never refreshed, so its status marks went
  stale.
- The candidate list re-queries on a line change only when "hide recordings already used" is on (the only
  filter that depends on the line).
- **Save & next unmatched** (button, `Ctrl+Enter`, also from a text field) saves the draft and opens the next
  unmatched line in the list. It never approves; approval stays a confirmed button press. **`U`** jumps to
  the next unmatched line, asking first if there are unsaved changes.
- Already in place and kept: debounced searches with stale-response protection (latest request wins),
  candidate search kept in the address, paginated lists.

Test fixture: disposable roots now also link `reference-audio/` (read-only), so tests can decode MCC clips
that are not cached yet. Before, such clips failed with 503 only in tests.

## 4. Remaining costs

- **Search debounce: 250 ms per query.** The request itself takes about 20 ms; the delay is deliberate to
  avoid a request per keystroke.
- **Save: about 120 ms**, plus about 150 ms of background report that may overlap the next action. What
  remains is the full JSON export write (required, so M6 and git always see the database's state), the
  `.history/` copy of the previous file (1.3 MB per save, M3 rule 5), and SQLite commits with fsync.
- **Cold first visit to a line:** MCC clips not decoded yet cost about 280 ms (vgmstream), once per clip.
- **Server start: 1.3 s** to load and index the catalogs; the first report runs in the background.
- Each read parses the 1.3 MB export (about 12 ms of the 10–30 ms reads). Caching it is possible but was
  not needed for the targets.

## 5. Commands

```sh
python scripts/ui/profile_api.py --iterations 15 --label mine   # API timings -> work/reports/perf/api_mine.json
python scripts/ui/profile_api.py --cprofile save                # where one operation spends its time
cd frontend
PERF_ITERATIONS=10 PERF_LABEL=mine npm run perf                 # browser workflow, Studio and classic -> e2e/out/perf_mine.json
npm run test:navigation                                         # save in place, save & next, U, 304, stale searches
```

All of these make their own disposable copy of the mapping data, and the profiler refuses to run on the
real repository root.
