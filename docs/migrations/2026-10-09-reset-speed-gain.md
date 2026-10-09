# Migration `reset_speed_gain` (20261009T015850_reset_speed_gain)

Owner-authorized one-time reset of the audio editor's `speed` and manual `gain_db` (removed 2026-10-09). Mode: **write**.

- Mappings: 197; with a recipe holding speed and/or gain_db: **9** (approved 9, draft 0, needs rework 0).
- With a non-default value (speed ≠ 1 or gain ≠ 0): **3**.
- Local file: 8 custom subtitle(s), 0 user recording(s), no editing recipes (recipes live only in manual_mappings.json audio.edit); unchanged.
- File before: `10d278d87d2a55ef4df50b1cff0dbfe1e2beebb10d65896d5c98df63db7e6ddb`; after: `7177e0d95f43c38a60065d0348864c790bdc5319c198a64b65ed1785395438cb`

| Mapping | Slot | Audio | Previous speed | Previous gain dB |
|---|---|---|---|---|
| `m-000107` | `es:sgt07#0` | approved rev 2 | 1.16 | 0 |
| `m-000115` | `es:keyes04#0` | approved rev 2 | 1 | 0 |
| `m-000117` | `es:keyes02#0` | approved rev 2 | 1 | 0 |
| `m-000119` | `es:sgt05g#0` | approved rev 2 | 1.11 | 0 |
| `m-000145` | `es:cor06#1` | approved rev 2 | 1.17 | 0 |
| `m-000156` | `es:keyes04#1` | approved rev 2 | 1 | 0 |
| `m-000159` | `es:keyes07#1` | approved rev 3 | 1 | 0 |
| `m-000162` | `es:keyes10#0` | approved rev 2 | 1 | 0 |
| `m-000164` | `es:keyes12#0` | approved rev 2 | 1 | 0 |

## Verification

- written_sha_matches: True
- same_changes_as_planned: True
- only_speed_gain_removed: True
- approvals_flags_subtitles_unchanged: True
- no_speed_or_gain_left: True
- idempotent_second_pass_changes_nothing: True
- local_file_unchanged: True
- validator_errors: 0
- approved_fingerprint_drift: 0

Backup: `work/migrations/20261009T015850_reset_speed_gain` (verified: True).

## How it was done

- **Owner authorization (2026-10-09):** reset saved speed and manual gain on all mappings, approved
  ones included. Only these two parameters; no needs rework.
- **Run:** `python scripts/validate/migrate_reset_speed_gain.py --write`, through
  `mapping_store.reset_removed_edit_fields`.
  - The store refuses unless the result differs from the loaded file only by the removed `speed` /
    `gain_db` keys (`proof_only_removed_fields`).
  - It uses the usual stale check, `mappings/.history/` backup and atomic write.
- **Unchanged in every one of the 197 mappings** (re-checked independently after the run):
  - the selected CE sources;
  - audio status, revision, `approved_at` and fingerprint;
  - subtitles, the match, the radio and ≈ flags, notes;
  - trims, cuts, silences, fades, loudness settings.
- **Unchanged files** (byte-identical): `manual_mappings.local.json`, `mission_progress.json`,
  `mission_map.json`, `verifications.json`.
- **Second run:** "nothing to do", and the file is unchanged.
- **The backup** (git-ignored, it includes the local file) is in the folder above.
- **Rollback**, only together with reverting the code, since the restored file holds the removed
  fields again:
  `python scripts/validate/migrate_reset_speed_gain.py --rollback work/migrations/20261009T015850_reset_speed_gain`.
