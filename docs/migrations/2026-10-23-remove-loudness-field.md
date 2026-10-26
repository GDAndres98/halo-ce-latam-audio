# 2026-10-23: legacy `loudness` setting removed (owner-authorized)

**Why.** Per-line loudness matching was removed on 2026-10-11
(`2026-10-11-reset-loudness-match.md`), but 83 recipes still carried the leftover
`loudness: {"mode": "off", "offset_db": 0}`. It did nothing. The owner does not want any per-line level
attribute: every line's level comes from the build setting in `config/audio_export.json` (`level_mode`:
`global_gain` with `global_gain_db`, or `match_spain`).

**What changed in the data.** `audio.edit.loudness` was removed from 83 recipes (all approved).
No audio changes: an off setting did nothing, and `audio_edit.normalize` already dropped it on every save.
Approved decisions stay approved: status, revision, approved_at and fingerprint are untouched, and nothing was
marked needs rework. Matches, subtitles, trims, cuts, silences, fades, radio / echo / interference, flags and
notes are as they were. The database and the JSON were written together through the mapping store; each slot
has a `slot_history` row, and the previous JSON is in `mappings/.history/`.

**Tool.** `python scripts/validate/migrate_remove_loudness_field.py`:

- the default run is a dry run;
- `--write` backs up, migrates and verifies;
- `--rollback work/migrations/<id>` undoes it (only while the file is still exactly what the migration wrote).

Run: `work/migrations/20261024T042445_remove_loudness_field/` (verified backup of the JSON, the local file and the database, plus `report.md`). All checks true; validator 0 errors, 0 fingerprint drift. The Studio was running (restarted on the new code); no save landed during the write (the verification compares against the file read at the start).

It was rehearsed first on a disposable copy of the real mappings (with a git baseline so the validator compared
against the pre-migration file): write, rollback (byte-identical to the original), write, and a second run that
found nothing. The file diff is exactly the 83 `loudness` blocks plus the comma before each.

**Verification (rehearsal).**

- Only that field differs (`mapping_store.proof_only_loudness_removed`); a loudness that is not off is never
  removed.
- Approvals and everything else unchanged; no loudness left; JSON and database in sync.
- Validator: 0 errors, 0 fingerprint drift. Its comparison with the last commit accepts exactly this change, one
  way only (`project_validation._only_level_settings_reset`: loudness switched off or removed, limiter removed).

**Code.** The schema no longer allows `audio.edit.loudness`. `audio_edit.normalize` still accepts an off
`loudness` from an old page and drops it; any other value is refused as before.

**Side effects (no audio changes).**

- A build made before the migration that contains one of these lines reports it as changed
  ("rebuild before installing"), because a build records the stored recipe. Rebuild; the rendered audio is the
  same.
- Public previews of these lines stop being served until they are published again
  (`scripts/build/publish_previews.py`), for the same reason.
