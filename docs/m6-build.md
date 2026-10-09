# M6 — building a test mod from M4 mappings

**For:** the project owner. **Status (2026-10-08):** limited proof of concept.
- Builds so far: `a10`; then `a10` + `x10` + `x20` (165 lines, 23/23 checks, candidate
  `053c9741…`).
- `a10` builds **audio-only**: 90 approved CE lines, 24/24 checks.
- Subtitle generation is disabled (§4).
- **Audio edit recipes (2026-10-09):** approved lines with an M4 edit (trim, cuts, speed, loudness)
  are built from their recipe (§2.1). `--mission a10` with the new code: 182 lines, 23/23 checks;
  every unedited line's stream is byte-identical to the earlier build (166/166 compared).
- Nothing is installed without the owner's explicit approval.

## 1. Build

```
python scripts/catalog/build_level_folders.py                         # once: which folders each map uses
python scripts/build/m6_build.py --mission a10                        # a10 + its cinematics x10, x20, x30
python scripts/build/m6_build.py --level a10 --level x10 --level x20  # explicit folders -> work/m6/a10_x10_x20/
python scripts/build/m6_build.py --level a10 --inventory-only         # report only, build nothing
```

**Which folders belong to a mission (`--mission`).** `build_level_folders.py` scans each installed
campaign `.map` (read-only) for the dialogue tag paths it contains, and writes
`work/mcc/level_folders.json` (`derived:map_tag_path_scan`).
- **The selection:** the map's own folder, plus the cinematic `xNN` folders used by no other map.
- **Results (2026-10-08):**

  | Map | Cinematic folders found in it |
  |---|---|
  | `a10` (The Pillar of Autumn) | `x10` 41/41, `x20` 36/36, `x30` 16/16 tags |
  | `c10` | `x50` |
  | `d40` | `x70` |
  | `a30`–`b40`, `c20`, `c40`, `d20` | none |

  `multiplayer1` is used by no campaign map.
- **Shared generic bark folders** (`marines`, `grunt`, …) appear in many maps. They are reported but
  never selected (milestone M-SYS, deferred).

**One bank for everything.** Every `sound\dialog\…` folder lives in the single
`sounds_dialogs_spanish.fsb` (`a10` = samples 0–100, `x10` = 5523–5563, `x20` = 5564–5599). A
multi-folder build is one candidate bank with replacements in several ranges. The `.lst.bin` is
unchanged.

- **Mission-independent.** `--level` takes any MCC catalog folder.
- **Several levels go into one candidate bank.** MCC has one Spanish dialogue bank for the whole
  game, so every installed build must contain every level you want to hear.
- **Rebuilding after approving more dialogue** in M4: run the same command again.
  - The build reads `manual_mappings.json` at that moment.
  - It overwrites `work/m6/<name>/`.
  - It reuses cached decodes (`work/m6/_cache/`) and derived streams (`work/derived/`).
  - The same approved decisions always give a byte-identical bank.
- **You can keep working in M4 while it builds.**
  - The build uses the decisions it read at the start.
  - Anything you change meanwhile is listed in `build_manifest.json` (`decisions_changed_during_build`).
  - `m6_install.py` re-plans from your **current** mappings at `check`, `preflight` and `install`. It
    **refuses** if a line in the build was changed or revoked since (rebuild), and only **notes**
    newer approvals that the build doesn't contain yet.

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
| Audio **approved**, source *CE line* (one line), mono slot, media resolved, fingerprint unchanged | **replace** the slot's sample with the CE recording, **with its edit recipe if it has one** (§2.1) |
| Audio approved *keep Spain* | keep original (byte-identical) |
| Audio draft or needs rework; slot not mapped | keep original, reason reported |
| `ce_concat`, user recording, composite; a `gap_s` on one line; stereo slot | **not eligible**: unsupported in this build, reported |
| Fingerprint drift, unknown or test-event line, invalid edit recipe or one made for another line/language, several mappings for one slot or sample | **not eligible**: invalid or conflict. Duplicate mappings stop the build |

Rules:
- **Target index:** the slot's index in the **Spanish** bank's own name table (from the MCC
  catalog). English indices are never used.
- **Untouched samples** stay byte-identical; later samples only move.
- **Header fields:** sample counts, offsets, 32-byte alignment, data size and the LOOP chunk
  (0, n−2) are recomputed by `fsb5_writer`.
- **`.lst.bin`** files are never written.
- **Radio and ≈ flags** are carried in the manifest only. No effect is applied.

### 2.1 Edited lines (owner recipes from the M4 audio editor)

- **The recipe** is the approved `audio.edit` (`audio-edit/1`, `common/audio_edit.py`). It is part of
  the approved audio object, so it can only change through *needs rework*.
- **The render path:** `audio_pipeline.derive_edited` runs CE WAV → ffmpeg 44.1 kHz → recipe
  (trims and cuts with crossfades → fades → rubberband speed → inserted silences → gain: loudness
  match + manual → −1 dBFS look-ahead limiter → 16-bit) → codec padding → CELT `fmod` profile.
  - This is the same function the M4 preview calls. The preview's *as encoded* audio is the
    libcelt decode of this exact stream.
  - The simulation on `es:A10_010_cryotech#0`: the preview is byte-identical to vgmstream's decode
    of the candidate bank.
- **The loudness reference** is the slot's original Spain sample, decoded from the pinned bank copy
  (hash-checked) and measured with ITU-R BS.1770-4 gated loudness.
- **Unedited lines** (`{trim_start_s: 0, trim_end_s: 0, gap_s: 0}`) take the original `derive` path
  unchanged.
- **Reports:**
  - `work/derived/<sha>/recipe.json` has an `audio_edit` step with the recipe, the source PCM hash
    and the render stats (durations, loudness, gain, limiter);
  - `build_manifest.json` lists `edited_slots`, plus `edit`, `edit_summary` and `edit_stats` per line;
  - `test_report.md` flags them **E** and has an "Edited lines" table.
- **Checks:** the per-line content checks (§3) compare against the *edited* 44.1 kHz PCM.
- **Install guard:** the recipe is part of what a built line depends on, so `m6_install.py` refuses
  a build whose recipe changed or was reset since.
- **The radio flag** is still not applied.

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
- **Stability:** `.lst` not written. Edits made in M4 during the build are reported; the install
  tool guards against stale builds (§1).

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
  - `scripts/common/audio_edit.py` (recipes, rendering) and `audio_pipeline.derive_edited`;
  - `scripts/build/m6_build.py`;
  - `scripts/build/m6_install.py`.
- **Reuse:** `audio_pipeline.derive`, `celt011` (MCC "fmod" profile), `fsb5_writer`, `vgm`,
  `ondemand_audio`.
- **Tests:** `tests/test_audio_edit.py` (recipes, M6 planning of edited lines, install guard, preview
  == build parity), and `tests/test_m6_build.py`:
  - several replacements of different lengths, including the first and last sample;
  - order-independence and determinism;
  - collateral-change detection;
  - eligibility categories: draft, stereo, drift, `ce_concat`, duplicate mapping;
  - the subtitle dry run.
