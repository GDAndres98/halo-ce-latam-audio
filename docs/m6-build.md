# M6 — building a test mod from M4 mappings

**For:** the project owner. **Status (2026-10-08):** first limited proof of concept.
- `a10` builds **audio-only**: 90 approved CE lines, 24/24 checks.
- Subtitle generation is disabled (§4).
- Nothing is installed without the owner's explicit approval.

## 1. Build

```
python scripts/build/m6_build.py --level a10                          # ~1 min; work/m6/a10/
python scripts/build/m6_build.py --level a10 --inventory-only         # report only, build nothing
python scripts/build/m6_build.py --level a10 --level x10 --name a10_x10   # several levels, one bank
```

- **Mission-independent.** `--level` takes any MCC catalog folder.
- **Several levels go into one candidate bank.** MCC has one Spanish dialogue bank for the whole
  game, so every installed build must contain every level you want to hear.
- **Rebuilding after approving more dialogue** in M4: run the same command again.
  - The build reads `manual_mappings.json` at that moment.
  - It overwrites `work/m6/<name>/`.
  - It reuses cached decodes (`work/m6/_cache/`) and derived streams (`work/derived/`).
  - The same approved decisions always give a byte-identical bank.
- **You can keep working in M4 while it builds.** The build only fails if the selected levels' plan
  changed in the meantime (`plan_unchanged_during_build`).

**Inputs, read-only:**
- `mappings/manual_mappings.json` (through `mapping_store.load`) and the git-ignored local file;
- the catalogs under `work/`;
- the pinned bank copy `reference-audio/stage1/fsb/sounds_dialogs_spanish.fsb`;
- CE `.wem`s from the installed paks, decoded on demand after a hash check.

**Outputs, all git-ignored, in `work/m6/<name>/`:**

| File | Content |
|---|---|
| `sounds_dialogs_spanish.fsb` | the candidate bank |
| `inventory.json` | every edited slot in every level, by state (Task 1) |
| `build_manifest.json` | every slot in scope: replaced or preserved and why; CE source, `.wem` / WAV / stream hashes; durations; radio and ≈ flags; the subtitle dry run; install files with original and candidate SHA-256 |
| `validation_report.json` | all checks, plus per-line content checks and SNR |
| `test_report.md` | what will change in game, limitations, and the in-game checklist |
| `install_rollback.md` | the exact install and rollback commands |

## 2. What gets built (eligibility)

From `common/m6_build.plan_audio`. Nothing is approved, changed or paired by the builder.

| Decision in M4 | Build action |
|---|---|
| Audio **approved**, source *CE line* (one line), mono slot, no trims, media resolved, fingerprint unchanged | **replace** the slot's sample with the CE recording |
| Audio approved *keep Spain* | keep original (byte-identical) |
| Audio draft or needs rework; slot not mapped | keep original, reason reported |
| `ce_concat`, user recording, composite, trims; stereo slot | **not eligible**: unsupported in this build, reported |
| Fingerprint drift, unknown or test-event line, several mappings for one slot or sample | **not eligible**: invalid or conflict. Duplicate mappings stop the build |

Rules:
- **Target index:** the slot's index in the **Spanish** bank's own name table (from the MCC
  catalog). English indices are never used.
- **Untouched samples** stay byte-identical; later samples only move.
- **Header fields:** sample counts, offsets, 32-byte alignment, data size and the LOOP chunk
  (0, n−2) are recomputed by `fsb5_writer`.
- **`.lst.bin`** files are never written.
- **Radio and ≈ flags** are carried in the manifest only. No effect is applied.

## 3. Validation (`validation_report.json`; every check must pass)

- **Inputs:** the validator is clean; the bank and `.lst` copies match their pins; there are no
  conflicts.
- **Structure:** same sample count and names; untouched sample headers and payloads byte-identical;
  offsets shift by the cumulative growth; alignment; the size equation; the targets' streams,
  counts, loops and head bits; round trip.
- **Decoding:** vgmstream decodes all 5,696 subsongs of the candidate, and **only the targets
  differ** from the original.
- **Per line:**
  - vgmstream decode == the encoder's own decode;
  - content SNR vs the 44.1 kHz source ≥ 30 dB (the `a10` run: 41–48 dB);
  - sample count; Custom CELT;
  - duration covers source + codec delay;
  - no new clipping; silence after the end.
- **Determinism:** the whole build runs twice in one go and gives identical bytes (also identical
  across separate runs).
- **Stability:** the selected levels' plan is unchanged at the end; `.lst` not written.

## 4. Subtitles: disabled for now

- **The need:** the dry run (`subtitle_plan`) found **91 approved `a10` subtitle changes**. Their
  keys are present in both tables, and the text is valid UTF-8 without NUL.
- **The problem:** only **9 (SU) / 5 (SP)** are the same byte length as the current entry.
- `common/mcc_loc_patch.py` only patches **same-length** entries; that is what B1 verified in game.
- Its general `rebuild()` recomputes the size fields, but it has never been used on a real table,
  and MCC loading a size-changed table is an open B1 residual.
- **What this build does:** it writes **no** subtitle table. It doesn't truncate, pad or apply only
  the same-length subset. The plan, with lengths per table, is in `build_manifest.json`
  `subtitles`.
- **Next step** (needs approval):
  - validate variable-length writing offline: rebuild, re-parse, every other key byte-identical;
  - then run a one-entry in-game test (B1 §B.12 style);
  - then enable SU+SP generation in this builder;
  - `m6_install.py` already supports several files.

## 5. Install and rollback (only after the owner approves)

`scripts/build/m6_install.py` reads the install file list from the build manifest. An audio-only
build replaces one file; a later build may also list `SU`/`SP`.

```
python scripts/build/m6_install.py --build a10 check       # read-only
python scripts/build/m6_install.py --build a10 preflight
python scripts/build/m6_install.py --build a10 install
#   Steam > Play "Halo: MCC Anti-Cheat Disabled" > test > close MCC
python scripts/build/m6_install.py --build a10 rollback
```

**For each file it:**
1. checks the installed original against its pin;
2. backs it up outside the install (`work/mcc/backup/19905945/…`);
3. verifies the backup;
4. installs only the validated candidate;
5. verifies the installed file;
6. re-hashes `halo1/sound/pc` and `SU`/`SP` to prove no other file changed;
7. on `rollback`, restores and verifies every original, then compares a full snapshot (hashes plus
   size/mtime of every install file) against preflight.

**Safety:**
- Every step refuses to run while MCC/EAC is open.
- Any failure during install restores the originals.
- Last resort: Steam "Verify integrity of game files".

## 6. Code and tests

- **Code:**
  - `scripts/common/m6_build.py`: `plan_audio`, `subtitle_plan`, `assemble`,
    `multi_structural_checks`;
  - `scripts/build/m6_build.py`;
  - `scripts/build/m6_install.py`.
- **Reuse:** `audio_pipeline.derive`, `celt011` (MCC "fmod" profile), `fsb5_writer`, `vgm`,
  `ondemand_audio`.
- **Tests:** `tests/test_m6_build.py`:
  - several replacements of different lengths, including the first and last sample;
  - order-independence and determinism;
  - collateral-change detection;
  - eligibility categories: draft, stereo, drift, `ce_concat`, duplicate mapping;
  - the subtitle dry run.
