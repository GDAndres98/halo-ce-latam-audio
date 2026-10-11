# 2026-10-11: loudness matching reset (owner-authorized)

**Why.** Five approved recipes had loudness set to "match Spain's recording". At build time those lines got
their own gain instead of the global export gain. In the builds of 2026-10-10 that meant +4.45 to +10.29 dB
of match gain and, after the peak limiter, 0 dB of the global +4 dB. The owner wants one level setting for
every replacement: the global export gain.

**What changed.** `audio.edit.loudness` became `{"mode": "off", "offset_db": 0}` on:

- `es:keyes04#0`
- `es:keyes04#1`
- `es:keyes07#1`
- `es:keyes10#0`
- `es:keyes12#0`

These were all approved and stay approved. Nothing else changed: status, revision, approved_at and
fingerprint are untouched, nothing was marked needs rework, and matches, subtitles, trims, cuts, fades,
flags and notes are as they were. The database and the JSON were written together through the mapping
store. Each slot has a `slot_history` row, and the previous JSON is in `mappings/.history/`.

**Tool.** `python scripts/validate/migrate_reset_loudness_match.py`:

- the default run is a dry run;
- `--write` backs up, migrates and verifies;
- `--rollback work/migrations/<id>` undoes it.

Run: `work/migrations/20261011T002112_reset_loudness_match/`. It holds the verified backup of the JSON, the
local file and the database (integrity check ok), plus `report.md`. It was rehearsed first on a
disposable copy (write, rollback, write, and a second run that found nothing).

**Verification.**

- Only those five fields differ (proof function, and the git diff: 5 lines).
- Approvals and everything else are unchanged.
- No loudness matching is left.
- The JSON and the database are in sync.
- The validator reports 0 errors and 0 drift. Its comparison with the last commit accepts exactly this
  change: loudness switched off, nothing else, one way only (`project_validation._only_loudness_turned_off`).

**Not changed.** The editor still offers "Match Spain's recording". Using it again on a line would give
that line its own gain again.
