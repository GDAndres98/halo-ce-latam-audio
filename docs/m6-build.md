# M6 — building a test mod from M4 mappings

**For:** the project owner. **Status (2026-10-08):** limited proof of concept.
- Builds so far: `a10`; then `a10` + `x10` + `x20` (165 lines, 23/23 checks, candidate
  `053c9741…`).
- `a10` builds **audio-only**: 90 approved CE lines, 24/24 checks.
- **Subtitles (2026-10-11):** `--kind subtitles` writes `SU_Halo1.bin` and `SP_Halo1.bin` from the
  approved subtitle decisions, with any text length (§4); `--kind both` builds the bank and the two tables
  together. Validated offline only: MCC loading a table whose size changed is still to be checked in game.
- **From the Studio (2026-10-11):** Build & Test runs these builds, then install and rollback through
  `m6_install.py`, after the owner confirms the listed files (README, "Building and restoring the game
  files"). The safeguards are the script's own. `--mcc-root/--backup-root/--state-dir` exist for the
  browser test's throw-away game folder (`npm run test:deploy`).
- **Audio edit recipes (2026-10-09):** approved lines with an M4 edit (trims, cuts, silences,
  fades) are built from their recipe (§2.1). Loudness matching and its limiter were removed on 2026-10-11.
- **Global export gain (2026-10-09):** +4 dB by default on every CE replacement (+3 dB until 2026-10-10) (§2.2). Speed and
  per-line gain were removed. `--mission a10` with the new code: 182 lines, 23/23 checks;
  every unedited line's stream is byte-identical to the earlier build (166/166 compared).
- Nothing is installed without the owner's explicit approval.

## 1. Build

```
python scripts/catalog/build_level_folders.py                         # once: which folders each map uses
python scripts/build/m6_build.py --mission a10                        # a10 + its cinematics x10, x20, x30
python scripts/build/m6_build.py --level a10 --level x10 --level x20  # explicit folders -> work/m6/a10_x10_x20/
python scripts/build/m6_build.py --level a10 --inventory-only         # report only, build nothing
python scripts/build/m6_build.py --all-mapped                         # every folder you mapped -> work/m6/all_mapped/
python scripts/build/m6_build.py --mission a10 --kind subtitles       # SU_Halo1.bin + SP_Halo1.bin only (seconds)
python scripts/build/m6_build.py --mission a10 --kind both            # the bank and both tables, installed together
```

`--kind audio` (the default) builds the bank, `subtitles` the two tables, `both` all three files. The scope
options are the same for every kind.

**`--all-mapped`** selects every MCC folder holding at least one mapping: campaign levels,
cutscenes and generic bark folders such as `marines` or `sarge2`. It is the "everything I have done
so far" test build. Install it with `--build all_mapped`.

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
- **Shared generic bark folders** (`marines`, `grunt`, …) appear in many maps, so `--mission` reports
  them but never selects them.
  - Their CE source, the systemic voice sets (SYS), is catalogued since 2026-10-10.
  - Build them by naming them, for example `--level a10 --level x10 --level x20 --level marines
    --level grunt`.
  - Remember that one bank holds everything: every installed build must contain all the folders
    you want to hear.

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
- **The render path** is `audio_pipeline.derive_processed`, with render engine `audio-render/4`:
  1. CE WAV → ffmpeg 44.1 kHz;
  2. the recipe: trims and cuts with crossfades → fades → inserted silences;
  3. the **global export gain** (§2.2), the only level change;
  4. 16-bit → codec padding → CELT `fmod` profile.
  - This is the same function the M4 preview calls. The preview's *as encoded* audio is the
    libcelt decode of this exact stream.
  - The simulation on `es:A10_010_cryotech#0`: the preview is byte-identical to vgmstream's decode
    of the candidate bank.
- **Unedited lines** (`{trim_start_s: 0, trim_end_s: 0, gap_s: 0}`) get only the global gain. With
  the gain set to 0 they take the original `derive` path, byte for byte.
- **Reports:**
  - `work/derived/<sha>/recipe.json` lists the steps (`audio_edit`, `loudness_match`, `global_gain`
    with requested / applied / shortfall) and the render stats;
  - `build_manifest.json` has:
    - `edited_slots`, `global_gain` (configured value, source, config hash, the lines that got
      less) and `warnings`;
    - per line: `edit`, `edit_summary`, `audio_stats` and `global_gain_applied_db`;
  - `test_report.md` flags them **E** and has an "Edited lines" table.
- **Checks:** the per-line content checks (§3) compare against the *edited* 44.1 kHz PCM.
- **Install guard:** the recipe is part of what a built line depends on, so `m6_install.py` refuses
  a build whose recipe changed or was reset since.
- **The radio flag** is still not applied.

### 2.2 Global export gain

- **The setting:** `global_gain_db` in `config/audio_export.json` (schema `audio-export-config/1`;
  `common/export_config.py`).
  - **Default +4 dB** when the file doesn't exist.
  - Range −12 to +12. Copy `config/audio_export.example.json` to start.
- **Applied once per line** in `global_gain` mode (the default; §2.3): to every CE replacement, after
  the recipe, before CELT.
- **Linear only:** no limiting, compression or clipping.
  - If the peak would pass −1 dBFS, the line gets only as much as fits, never below 0 dB.
  - The shortfall is reported in the build output, in `test_report.md` ("Global gain") and in the
    manifest.
- **Determinism:** the setting is part of the build inputs and the M4 preview cache key.
- **Changing it:** edit the file and rebuild. Installed builds keep the value they were built with,
  as recorded in their manifest.

### 2.3 Level modes: global gain or match Spain (2026-10-11)

**Why (measured).** The owner reported that replacements were noticeably quieter in game. The Studio's
gain was set to +5 dB. A survey of the last installed build (`all_mapped_4`, 618 lines; 62 sampled
across 18 folders with `scripts/discovery/level_survey.py`, decoding the bank the game reads) found:

| | Spain (MCC original) | CE es-MX source | Decoded replacement |
|---|---|---|---|
| Loudness, median (LUFS, BS.1770) | −11.5 | −20.3 | −17.3 |
| Sample peak, median | −0.2 dBFS | −3.9 dBFS | −1.0 dBFS |
| Peak-to-loudness, median | 11.0 dB | 16.3 dB | 16.3 dB |

- **The gain worked.** Rendered minus source equals the applied gain (median difference 0.00 dB). CELT
  keeps the level (decoded minus rendered: −0.24 to +0.45 dB). The installed bank matched its manifest.
- **But the peak rule cut it.** 494 of 618 lines got less than the requested +5 dB (median +2.85 dB).
  Each line sat right at the −1 dBFS ceiling.
- **The cause is the material, not the setting.** The Spain recordings are mastered with heavy
  limiting: 11 dB peak-to-loudness, peaking at 0 dBFS. The CE recordings are natural: 16 dB. A linear
  gain can never bring a line above −1 dBFS minus its own peak-to-loudness ratio, which is −17.3 LUFS on
  the median line, exactly what was measured. Replacements were therefore a median **5.1 dB quieter**
  than the line they replace (p10 −8.4, p90 −1.6), and Cortana lines up to 10.8 dB quieter. Raising the
  global gain to +6 or +8 dB changes almost nothing; only lines with headroom get louder.
- **Strategies tried on the same 62 lines:**

  | Strategy | Result vs Spain, median (p10 / p90) | Limiting on the peaks |
  |---|---|---|
  | +4 dB, linear (before this change) | −5.3 (−8.3 / −2.2) | none |
  | +4 dB with a peak limiter | −4.8 (−7.9 / −1.7) | median 1.1, max 3.7 dB |
  | Match Spain, limiter uncapped | −1.6 (−3.1 / −0.1) | median 4.8, max 10.7 dB |
  | **Match Spain, limiting ≤ 6 dB** (chosen) | −1.7 (−4.4 / −0.1) | median 4.8, max 6.0 dB |

**The mode** (owner decision after these numbers): `level_mode` in `config/audio_export.json`, a build
setting chosen on Build & Test.
- **`global_gain` (default):** §2.2, unchanged. The default gain stays +4 dB.
- **`match_spain`:**
  - Each line gets the gain that brings its loudness to that of the Spain recording it replaces. The
    reference is measured from the same pinned decode the M4 preview uses, and cached by sample hash in
    `work/m6/_cache/spain_lufs.json`.
  - A look-ahead peak limiter keeps every sample at −1 dBFS or below: 5 ms look-ahead, 80 ms release.
    It is the audio-render/2 limiter, restored.
  - The gain is lowered so the limiter never takes more than **6 dB** off a peak
    (`audio_edit.MATCH_MAX_LIMITING_DB`). The lines that got less are reported.
  - Lines louder than their Spain recording are lowered, with no limiting.
  - The global gain is kept but not used. Without a measurable Spain reference, a line falls back to
    the global gain (reported).
  - Recipes hold no level setting. Per-line gain and the per-recipe "match" stay removed, so every line
    of a build follows the same rule.
- **Engine:** `audio-render/5`. Previews are cached by mode, and what the editor plays is what the build
  writes.

**Verified on the decoded FSB5 output** (disposable builds, 2026-10-11):
- **Match Spain, every mapped folder (618 lines):**
  - replacements at −14.3 LUFS median against Spain's −11.5, so −1.7 dB (p10 −4.1, p90 −0.1), down from
    −5.1;
  - effective gain from −5.0 to +13.8 dB (median +7.7); 204 lines limited by the 6 dB cap;
  - per-line loudness follows the original game: correlation with Spain's per-line loudness 0.33 → 0.76.
    The quietest lines stay quiet (−18.8 → −18.9 LUFS);
  - peak-to-loudness 13.3 dB, still more dynamic than MCC's 11 dB;
  - codec: ±0.3 dB.
- **Global gain, `a10` at +4 vs 0 dB (101 lines):** the decoded difference per line equals the gain the
  build recorded, within 0.006 dB. Only 5 of 26 sampled lines had room for the full +4 dB.
- **All three builds:** unreplaced samples byte-identical, every subsong decodes, deterministic.
- **Tail check:** `silence_after_source_end` now allows the codec's ring-out of a recording that ends
  abruptly while still audible: below 64 LSB, or below half the peak of the source's last 512 samples. One
  match-mode line (`A10_200_cryoassist`, room tone cut without a fade, +9.4 dB) rang out at 65 LSB.

**Reporting.**
- The manifest's `level` block holds:
  - the mode, gain and source;
  - the effective gain (distribution);
  - the constrained lines and the fallbacks;
  - the limiter reduction;
  - loudness vs Spain (distribution), measured in both modes.
- Build & Test shows each build's level (Level column), and for the installed build its settings next to
  the Studio's current ones, with a warning when they differ.
- A build made in another mode is stale. The global gain only makes `global_gain` builds stale.
- `m6_build.py --level-mode … --global-gain …` overrides the saved setting for one build (recorded as the
  source). It is meant for disposable comparisons.

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
  - no new clipping; silence after the end (the codec's ring-out of an abrupt, still-audible ending is
    allowed, §2.3).
- **Determinism:** the whole build runs twice in one go and gives identical bytes (also identical
  across separate runs).
- **Stability:** `.lst` not written. Edits made in M4 during the build are reported; the install
  tool guards against stale builds (§1).

## 4. Subtitles (`--kind subtitles` or `both`)

**Status (2026-10-11):** works offline; the runtime check in MCC is pending (subtitle-research.md B.13).

**Planning** (`common/m6_build.subtitle_plan`, read-only). For every mapping in the selected folders:

| Subtitle decision | Build action |
|---|---|
| Approved CE es-MX / EN text, or approved custom text | **write** it into the entry for the line's key, in SU and in SP |
| Approved "no subtitle" (`none`) | **write** an empty entry |
| Approved "keep MCC text" | keep the entry byte for byte |
| Draft, needs rework | **excluded**: MCC's text stays; listed |
| Approved, but its fingerprint drifted, its text is missing, or the text can't go into a table (NUL, control characters, over 2,048 bytes) | **excluded** as invalid; listed |
| The takes of one line (one key) disagree: different texts, or a text next to an approved keep | **conflict**: the key stays unchanged; listed. Never guessed |
| The line has no entry in SU/SP (3 lines in the current data) | **excluded** (keys are never added); listed |

- **The key** is the tag path's CRC-32/MPEG-2 (`derived:mcc_loc_key_crc32_tag_path`, B.6). It is looked up
  in each table separately; the same canonical LATAM text goes into both (B.11.2).
- **Text** is stored as LF only and NFC.
- **Characters** not used anywhere in MCC's SU/SP/EN tables are reported as a warning, because the game font
  may lack them.
- The plan is part of `build_manifest.json` (`subtitles`):
  - `rows`, one per mapping, with its `category` and `result`;
  - `keys`, one per key, with the text, the old text in each table and the slots;
  - `conflicts`, `summary`, `tables` and `warnings`.
- The Studio shows the same plan for the selected scope before you build.

**Writing** (`common/mcc_loc_writer`, B.13):
- Baseline: the hash-verified copies `work/mcc/loc/copies/{SU,SP}_Halo1.bin` (pins in
  `common/m6_build.SUBTITLE_PINS`, Steam build 19905945). The installed files are never read by a build.
- Only the planned entries change. Every other entry, the keys and their order stay byte for byte.
- `L`, the size fields and the 8-byte padding are recomputed.
- Outputs: `work/m6/<name>/SU_Halo1.bin` and `SP_Halo1.bin`.

**Checks** (per table, in `validation_report.json` as `SU:<check>` / `SP:<check>`):
- the copy matches its pin;
- the plan's "before" text equals the baseline entry (the plan was made from the same bytes);
- `verify_table`: header, LF slack, padding, keys, every written entry, every other entry byte-identical,
  UTF-8 and re-serialisation;
- written twice in reverse order → identical bytes;
- the file on disk equals what was verified.

The `a10` mission (`a10`, `x10`, `x20`, `x30`): 190 entries per table, 45/45 checks, identical across runs.

**Stale builds:** a subtitle build is stale when the decisions or the custom-text file changed. The global
gain only affects audio builds. `m6_install.py` refuses to install a build when a subtitle it wrote is no
longer the approved text (`compare_subtitle_plans`).

## 5. Install and rollback (only after the owner approves)

`scripts/build/m6_install.py` reads the install file list from the build manifest:
- an audio build replaces the bank;
- a subtitle build replaces `Data/ui/localization/SU_Halo1.bin` and `SP_Halo1.bin`;
- a combined build replaces all three, **as one operation**: if any step fails, every file of the build is
  restored.

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
- Any failure during install restores every original: a hash mismatch, an error while copying, or an
  unexpected change. `--simulate-failure-after N` proves this in tests. It is refused unless `--mcc-root`
  names a throw-away folder.
- Only builds whose validation passed can be installed, from the Studio or the script.
- Every install, failed install and rollback is appended to `work/m6/deploy_history.jsonl`
  (`--history`), shown on Build & Test.
- **Restore originals** in the Studio rolls back every installed build, for example an audio build and a
  subtitle build installed one after the other.
- Last resort: Steam "Verify integrity of game files".

## 6. Code and tests

- **Code:**
  - `scripts/common/m6_build.py`: `plan_audio`, `subtitle_plan`, `table_changes`, `build_tables`,
    `compare_subtitle_plans`, `assemble`, `multi_structural_checks`;
  - `scripts/common/mcc_loc_writer.py`: the variable-length table writer (B.13);
  - `scripts/common/audio_edit.py` (recipes, rendering), `common/export_config.py` (global gain) and `audio_pipeline.derive_processed`;
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
  - the subtitle plan.
- **Subtitle tests:**
  - `tests/test_mcc_loc_writer.py`: the writer, on synthetic tables and on the shipped copies;
  - `tests/test_m6_subtitles.py`: approved and unapproved decisions, needs rework, drift, custom and empty
    text, takes that agree or conflict, missing keys, the install guard, and both tables from one plan;
  - `tests/test_m6_install.py`: a combined install and restore in a throw-away folder, failures part-way,
    refusals;
  - `tests/test_build_api.py`: kinds, staleness, coordinated restore, test-only failure simulation;
  - `npm run test:subtitles`: the whole flow in the browser.
