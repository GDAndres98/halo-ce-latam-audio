# Campaign-wide catalogs and inventory (2026-10-08)

**Status:** built offline and validated. Three catalog-rule extensions are pending **owner review**
(§3). Nothing in this work matches lines across games. Everything lands in git-ignored `work/`.

## 1. How to rebuild everything

```
python scripts/catalog/build_ce_catalog.py --all           # 13 CE missions, ~6 s, metadata only
python scripts/catalog/build_mcc_catalog.py --all --no-audio   # 28 MCC folders, ~2 s, no decoding
python scripts/catalog/build_mcc_catalog.py --level a10        # optional: eager a10 decode (M2 reports)
python scripts/extraction/export_ce_audio.py --mission M01     # optional: eager M01 decode (M1b reports)
python scripts/catalog/campaign_inventory.py --scan-ce         # work/reports/campaign_inventory.{json,md}
python scripts/validate/validate_project.py
```

- **Per mission, one file each.** `work/ce/catalog/mNN.jsonl` and `work/mcc/catalog/<level>.jsonl`
  can each be rebuilt independently with `--mission` / `--level`.
- **Reproducible.** Two runs give identical bytes. A full `--all` rebuild reproduced the existing
  `m01.jsonl`, `a10.jsonl` and the `a10` audio manifest byte for byte.
- **The slot-ID guard still applies to every MCC level.** A rebuild that would remove, move or
  rename a slot ID stops and writes `work/mcc/reports/<level>_id_changes.json`. Only the owner
  passes `--accept-id-changes`.
- **No eager decoding.** Audio is decoded on demand by the M4 UI (`scripts/common/ondemand_audio.py`):
  - MCC: one subsong from the pinned bank copy into
    `work/mcc/audio/ondemand/<lang>/<index>_<sha12>.wav`;
  - CE: one `.wem` from the language pak, after a hash check against the catalog, into
    `work/ce/audio/ondemand/<lang>/<media_id>.wav`.

  Existing M1b/M2 decodes are reused.

## 2. What exists (inventory)

Source: `work/reports/campaign_inventory.md`, which has the full per-level and per-mission tables.

| Side | Built | Notes |
|---|---|---|
| MCC | **28 folders**, 1,903 tags, **all 5,696** Spanish bank samples as slots (none twice) | 10 campaign levels (`a10`–`d40`), 5 cutscene folders (`x10`–`x70`), 13 generic bark folders (`marines`, `grunt`, …) |
| CE | **13 missions** (M01–M10, M12–M14), 1,475 voice assets, 1,462 lines with es-MX audio | No M11 folder exists in this build. Every voice asset is accounted for (0 skipped) |

- **Validator:** 1,475 CE + 1,903 MCC records, no findings.
- **Speaker and duration facts:** the MCC records keep the tag-name speaker (`derived:tag_name`),
  the per-sample durations from the FSB5 header, and the bank index and name.
- **Localization and source facts:** the CE records keep the es-MX/en/es-ES subtitle text with
  their locres keys, the media IDs and `.wem` hashes, and the source build. None of these were
  changed.

## 3. Rule extensions (pending owner review)

`a10` is unaffected by all three: its catalog is byte-identical.

1. **MCC sample identity fallback to the `.lst.bin` range.**
   - **The problem:** generic barks and cutscene permutations use bank names that are not the tag
     name (`deathquiet 01`, `1`, `keyes_flood_3`). Their basenames also repeat across folders, for
     example `death_quiet` in `captain` and `grunt`. Name-only lookup either found nothing or
     grabbed other folders' samples, and 115 slot IDs collided across folders.
   - **The rule now:** if the tag's name finds no sample, or the basename is shared by several
     `.lst.bin` tags, or the name hits are a strict subset of the tag's range (`flood\death`: one
     permutation is named `death`, the others `death2`, `death10`, …), the samples come from the
     tag's own `.lst.bin` range. That range is
     contiguous and covers the bank exactly; this was verified for both languages.
     - These samples carry `evidence: derived:lst_record_layout`.
     - The record is flagged `samples_from_lst_range:<lang>`.
     - Where the name table resolves a unique tag name, nothing changes; the M2 rule stays.
   - **Result:** 0 slot-ID collisions campaign-wide, and every Spanish bank sample belongs to
     exactly one slot. Affected tags: 2–5 per campaign level, and most
     cutscene and generic tags (see the inventory column "From lst").
2. **Percent-encoding in `slot_id`.** Bank names with spaces broke the `es:<name>#<occ>` pattern
   (`\s` is not allowed). `%`, `#` and whitespace in the name are now written as `%XX`, for example
   `es:deathquiet%2001#2`. All other names, including every `a10` name, are unchanged.
3. **`tag_name` may contain single inner spaces.** Five real tags need this: `b30_350_pilot 2`,
   `killed enemy`, `getting shot`, `monitor humming` and `player dead1`. The pattern in
   `mcc-dialogue-tag-3.schema.json` was widened to `^[a-z0-9_]+( [a-z0-9_]+)*$`.

If the owner rejects (1), the affected levels need another identity rule before they can be
matched. No mappings exist for them yet.

## 4. Gaps (from the inventory)

| Gap | What it means | Next step |
|---|---|---|
| Levels without mission scope | Only `a10 ↔ M01` is in `mission_map.json`. | Owner adds entries (M4 also searches all missions). |
| Cutscene levels can't be scoped | `mission-map/1` allows only `a10`–`d40`. | Owner decision: widen the pattern to `x10`–`x70`. |
| Generic barks have no CE catalog | CE combat barks live under `Audio/Systemic` (2,280 packages), which the M1 builder does not cover. | Separate catalog design for Systemic (M1-style). |
| `temp_mocap_VO` (46 packages) not catalogued | It looks like temporary capture audio. | Owner decides whether to include it. |
| Stereo slots | `x20`: 4, `multiplayer1`: 36. | Owner choice per slot (handoff §8). |
| English bank samples without tag | `b40` 4 and `monitor` 5 (English only). | Reported in `<level>_issues.json`; English is reference audio only. |
| Tags without an `SU` subtitle key | All generic barks, plus 1 in `b30` and 1 in `c10`. | Expected for barks; such lines keep no subtitle. |
| CE es-MX unresolved | M01: 13 media and 13 subtitles (test events); 12 subtitles in M06/M09/M10/M12/M13. | Never filled from another culture. |
| CE missions not mapped | M02–M14. M12–M14 are named `m12dlc1`–`m14dlc3`. | Owner. |

## 5. Code

- `scripts/common/mcc_catalog.py`: `slot_id_for`, the shared-basename fallback in `build_record`.
- `scripts/catalog/build_mcc_catalog.py`: `--all`, `--no-audio`, `build_one`.
- `scripts/catalog/build_ce_catalog.py`: `--all` (`discover_missions`).
- `scripts/catalog/campaign_inventory.py`.
- `scripts/common/ondemand_audio.py`.
- Tests: `tests/test_mcc_catalog.py::test_generic_tags_fall_back_to_their_lst_range` and
  `tests/test_m4.py`.
