# MCC Halo CE `a10` dialogue catalog (M2)

**Date:** 2026-10-08. **Status:** built, awaiting owner review and
listening. Read-only throughout: the work used the verified copies in
`reference-audio/stage1/`, and the install was opened only to hash it.
No bank, `.lst.bin`, `.map` or localization file was modified. Nothing
is matched to *Halo: Campaign Evolved*; the two games' dialogue,
wording, timing and delivery may differ, and every replacement is the
owner's decision.

## 1. How to reproduce

```
python scripts/catalog/build_mcc_catalog.py --level a10   # ~8 s, vgmstream r2117 (approved)
python -m unittest discover -s tests
```

Code:
- `scripts/common/mcc_lst.py`: `.lst.bin` parser.
- `scripts/common/mcc_catalog.py`: records, slots, analysis, decode loop
  and review picks (pure logic with an injected decoder).
- `scripts/common/fsb5_lib.py`: the existing FSB5 parser, reused
  unchanged.
- `scripts/catalog/build_mcc_catalog.py`: the CLI.
- Tests: `tests/test_mcc_catalog.py`, which uses synthetic FSB5 and
  `.lst.bin` bytes.

Outputs (all git-ignored):

| Path | Content |
|---|---|
| `work/mcc/catalog/a10.jsonl` | 101 `mcc-dialogue-tag/3` records (deterministic) |
| `work/mcc/build.json` | copy + install SHA-256, Steam build, `.lst.bin` layout checks |
| `work/mcc/audio/a10/{spanish,english}/<tag>__<k>.wav` | 202 decoded samples |
| `work/mcc/audio/a10/manifest.json` | `mcc-audio-export/1`: per sample index, subsong, slot, WAV hash, frames, peak |
| `work/mcc/reports/a10_{coverage,issues}.json`, `a10_summary.md` | coverage, issues, readable digest |
| `work/mcc/reports/a10_review_picks.{json,md}` | five samples for listening |

## 2. Sources and identity

**Inputs.** The full SHA-256 of all four copies equals the pinned
values, and still equals the installed files (Steam build `19905945`,
app `976730`). The run refuses copies that don't match.

**Identity = each bank's embedded name table, per language.** For each
tag, `<level>_<…>` names are looked up case-insensitively in the
English bank and, separately, in the Spanish bank.

**`.lst.bin` layout: VERIFIED structure, interpretation
`derived:lst_record_layout`.** Each file is `u32 version=1`,
`u32 count=1903`, then `count` × `{u32 len, len bytes NUL-terminated
tag path, u32 first_sample_index, u32 sample_count}`. Three checks
hold in **both** languages:
1. the file is consumed exactly;
2. the ranges are contiguous from 0;
3. the counts sum to the bank's sample count (EN 6,093, ES 5,696).

This **resolves the feasibility §11.6 caveat**. The old ad-hoc parser
read each record's `(start, count)` as the *next* record's
`(flag, count)`, which caused the off-by-1,902. It also refines
feasibility §10.2: the second field is a sample count (permutations),
and the first is a start index. M2 uses `.lst.bin` only as a
cross-check of the name table.

**Spanish slot ID (approved by the owner, 2026-10-08):**
`slot_id = "es:<name_in_spanish_bank>#<occurrence>"`. The name keeps
the bank's exact casing (e.g. `es:A10_710_CORTANA#0`,
`es:a10_682_cortana#0`). IDs must never be silently renumbered: see
the M3 ID-change guard.
`<occurrence>` is the 0-based rank of that index among the Spanish
samples with the same name (case-insensitive). The suffix exists
because names are **not** unique bank-wide: 765 Spanish and 117
English names repeat, all outside `a10` (generic barks and
permutations). Every `a10` name is unique in both banks, so all `a10`
slots end in `#0` (e.g. `es:A10_350_captkeyes#0`).

## 3. Results (`a10`)

| | Spanish | English |
|---|---|---|
| tags (from `.lst.bin`, identical lists) | 101 | 101 |
| samples (1 per tag, no permutations) | 101 | 101 |
| bank indices | 0–100 | 0–100 |
| `.lst.bin` range agrees with name table | 101/101 | 101/101 |
| codec / rate / channels | CELT, 44.1 kHz, mono ×101 | same |
| header duration min / max / total | 0.511 / 8.104 / 343.959 s | 0.557 / 8.719 / 337.730 s |
| decoded OK, WAV frames == header `sample_count` | 101 / 101 | 101 / 101 |

- **Kinds** (derived from the name): 73 scripted, 28 `flavor`.
- **Missing / duplicate / failed: none.** Every tag has a sample in
  both languages, there are no stray `a10_*` bank samples without a
  tag, no duplicate audio data within either language, no Spanish
  sample byte-identical to its English one, and no `slot_id`
  collisions.
- **Indices** are the same in both languages for all 101 tags. This
  was verified per bank, not assumed.
- **Name casing differs** between the banks for 96 tags (e.g.
  `A10_350_CaptKeyes` vs `A10_350_captkeyes`). This is informational:
  identity matching is case-insensitive.
- 99 samples per bank carry one metadata chunk of type 3 (8 bytes).
  `a10_681_cortana` and `a10_flavor_300_captkeyes` have none. The
  meaning is still unconfirmed (feasibility §11.7).
- **Cross-check:** the five Stage 2A lines (feasibility §14) reproduce
  the same indices and durations.
- **Subtitles:** all 101 records are `subtitle: {key_hash: null,
  evidence: unresolved}`. **Blocker B1 remains open** and nothing was
  guessed.

## 4. Review picks (owner listening pending)

These were chosen deterministically for variety; they are not
matches. Details are in `work/mcc/reports/a10_review_picks.md`.

| # | Tag | Why | ES / EN s |
|---|---|---|---|
| 1 | `a10_170_cryoassist` | scripted cryo-bay, median | 2.810 / 2.148 |
| 2 | `a10_710_cortana` | scripted Cortana, median | 2.694 / 1.730 |
| 3 | `a10_flavor_150_captkeyes` | flavor line, median | 4.725 / 4.725 |
| 4 | `a10_670_bisenti` | another speaker, median | 2.380 / 2.067 |
| 5 | `a10_682_cortana` | largest ES vs EN length difference | 6.653 / 8.719 |

## 5. Outside `a10` (noted for later levels, not acted on)

Bank-wide, the tag name and the sample name at its start index differ
for 946 English and 869 Spanish `.lst.bin` records. Examples are
truncated names (`a30_insert_020_lifeboatpil`), renamed takes
(`b30_520_fitzgerald` → `B30_520_bisenti`) and generic barks named
per take (`captain\capt_flood` → `keyes_flood_1`). **Name-only
identity will not hold for every level.** Each level's catalog must
report these, and `.lst.bin` ranges may be needed as a second,
clearly labelled source.
