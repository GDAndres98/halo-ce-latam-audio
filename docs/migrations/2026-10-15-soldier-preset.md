# Migration: Soldier radio preset retuned (2026-10-15)

Owner request: the `soldier` radio preset (added the same day) was retuned in the Studio, and every line set to
it should follow. The preset is now 1000–5000 Hz, 24 dB/oct, presence 0 dB, drive 1 dB, hiss −70 dBFS, MCC
clicks on (before: presence +6 dB, drive 6 dB, hiss −80 dBFS).

`python scripts/validate/migrate_soldier_preset.py --write` (store: `mapping_store.retune_radio`) updated the
four recipes labelled `soldier`, all approved rev 2: `es:A30_220_bisenti#0`, `es:A30_720_Bisenti#0`,
`es:A30_720_Mendoza#0`, `es:A50_710_bisenti#0`. Only those `audio.edit.radio` values changed; approvals
(status, revision, approved_at, fingerprint) were kept, as the owner asked for the lines to follow the preset.
Verification: proof of the change, idempotent, JSON and database in sync, 0 validator errors, 0 drift.

Backup, report and rollback: `work/migrations/20261015T002401_soldier_preset/`
(`--rollback work/migrations/20261015T002401_soldier_preset`).
