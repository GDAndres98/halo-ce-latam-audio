# 2026-10-11: limiter setting removed (owner-authorized)

**Why.** Every audio recipe carried `limiter: true`. It only mattered with loudness matching ("match Spain's
recording"): a look-ahead peak limiter at −1 dBFS let the match reach its target by compressing peaks. The
owner does not want limiting on any match and does not want the attribute. Loudness matching now always
lowers its own gain when the peak would pass −1 dBFS; nothing is ever limited or compressed.

**What changed in the data.** `audio.edit.limiter` was removed from 92 recipes
(90 approved, 2 drafts).
No audio changes: no recipe uses loudness matching (reset earlier the same day), and the setting only
applied there. Approved decisions stay approved: status, revision, approved_at and fingerprint are
untouched, and nothing was marked needs rework. Matches, subtitles, trims, cuts, silences, fades, loudness,
flags and notes are as they were. The database and the JSON were written together through the mapping store;
each slot has a `slot_history` row, and the previous JSON is in `mappings/.history/`.

**Tool.** `python scripts/validate/migrate_remove_limiter.py`:

- the default run is a dry run;
- `--write` backs up, migrates and verifies;
- `--rollback work/migrations/<id>` undoes it.

Run: `work/migrations/20261011T045623_remove_limiter/` (verified backup of the JSON, the local file and the database, plus
`report.md`). It was rehearsed first on a disposable copy: write, rollback, write, and a second run that
found nothing. The Studio was stopped during the run.

**Verification.**

- Only those fields differ: the proof function, and the file diff against the backup (92 `"limiter"`
  lines removed, plus the commas that removal implies).
- Approvals and everything else unchanged (True); no limiter left
  (True); JSON and database in sync (True).
- Validator: 0 errors, 0 fingerprint drift. Its comparison
  with the last commit accepts exactly this change, one way only
  (`project_validation._only_level_settings_reset`: loudness switched off and/or limiter removed).

**Code.** `audio_edit.py` has no limiter any more (render engine `audio-render/3`, so previews cached by the
old engine are not reused); a stored `limiter` is ignored and dropped on save. The schema no longer allows
the field. Both editors (the Studio and the classic page) lost the checkbox.

**Follow-up the same day (owner): loudness matching removed.** "Match Spain's recording" (with its offset)
is gone from both editors, the renderer (`audio-render/4`), the M6 build and the server: the global export
gain is the only level setting. A recipe that asks for matching is refused. Older recipes still store
`loudness: {"mode": "off", "offset_db": 0}`; the schema accepts only that value, and the renderer and the
Studio ignore it (a save drops it). Spain's loudness is still measured, for information only.
