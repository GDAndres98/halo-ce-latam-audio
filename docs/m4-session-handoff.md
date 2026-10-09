# M4 Session Handoff — Manual Dialogue-Matching UI

**For:** a new Claude Code session that builds M4. **Written:** 2026-10-08.
Read [`CLAUDE.md`](../CLAUDE.md) first: it has the hard rules and the full status. This file is
only the M4 starting point; it does not repeat other documents.

## 1. Goal and where we are

- **Project:** replace MCC Halo CE's Spanish (Spain) dialogue with Halo: Campaign Evolved **es-MX**
  recordings, and the Spanish subtitles with CE es-MX or custom text. Audio and subtitle choices are
  independent per line, and **matching is manual only** ([`docs/roadmap.md`](roadmap.md) §1).
- **Both v1.0 blockers are resolved in practice:**
  - **B1 subtitles:** edited `SU`/`SP_Halo1.bin` text displays in game
    ([`subtitle-research.md`](subtitle-research.md) B.11–B.12).
  - **B2 audio:** a CE es-MX line, converted by our pipeline, plays in MCC (E3, `v-000019`;
    [`b2-audio-research.md`](b2-audio-research.md) §5.10–5.12).
- **Next milestone: M4.** It lets the owner pair MCC slots with CE lines and approve audio and
  subtitle choices. M5 is filling in `a10`; M6 is the batch build; M7 is the full-level in-game test.

## 2. Build exactly this

The design is [`docs/m4-matching-ui-design.md`](m4-matching-ui-design.md); follow it.
- A stdlib-only server (`scripts/ui/m4_server.py`) that binds **127.0.0.1 only**.
- One static page (`scripts/ui/m4.html`).
- Three columns: MCC slots / slot detail / CE candidates.
- Candidates appear in **catalog order**, and search filters only on what the owner types.
- **No suggestions, scores or pre-fills.**
- Audio and subtitle are approved separately. Approved objects are read-only until the owner
  chooses *needs rework*.

Acceptance criteria are in design §5 and roadmap M4.

## 3. Data (all git-ignored, under `work/`, already built)

| What | Where | Produced by |
|---|---|---|
| MCC slots for `a10` (101 tags; `slot_id = es:<name>#<occ>`) | `work/mcc/catalog/a10.jsonl` (`mcc-dialogue-tag/3`) | `scripts/catalog/build_mcc_catalog.py --level a10` |
| MCC decoded audio | `work/mcc/audio/a10/{spanish,english}/<tag>__<k>.wav` plus `manifest.json` | same |
| MCC subtitle text | `work/mcc/loc/copies/{SU,SP}_Halo1.bin`; key = `mcc_loc.loc_key(tag path)`; look it up **per table** | B1 research |
| CE lines for M01 (220 records; `ce_line_ref = <record_id>#<n>`; es-MX/en/es-ES subtitle text inside) | `work/ce/catalog/m01.jsonl` (`ce-voice-asset/3`) | `scripts/catalog/build_ce_catalog.py --mission M01` |
| CE decoded audio | `work/ce/audio/m01/{Spanish(Mexico),English(US)}/*.wav` plus `manifest.json` | `scripts/extraction/export_ce_audio.py --mission M01` |
| Level ↔ mission scope | `mappings/mission_map.json` (`a10 ↔ M01`, owner decision) | owner |

If `work/` is missing, rebuild it with those commands. The install paths come from `.env`.

## 4. What it may write, and the protections

- **`mappings/manual_mappings.json`** (`manual-mappings/2`), **only** through
  `scripts/common/mapping_store.py`: `load()` → edit → `save(path, doc, loaded_sha256,
  user_actions=[UserAction("approve" | "needs_rework", mapping_id, field)])`.
  - The store refuses stale saves and approvals not made by a user action.
  - It refuses any change to an `approved` object without `needs_rework` (revision + 1), and
    deleting or retargeting approved mappings.
  - It backs up to `mappings/.history/` and writes atomically.
  - Fingerprints come from `project_validation.audio_fingerprint` / `subtitle_fingerprint`.
  - Rules: design §5.4–5.5 ([`dialogue-catalog-design.md`](dialogue-catalog-design.md)).
- **`mappings/manual_mappings.local.json`** (`manual-mappings-local/1`, git-ignored): custom
  subtitle text and recording paths only. The template is
  `mappings/manual_mappings.local.example.json`.
- **Never write:** `mappings/verifications.json` (append-only human checks; owner-reported results
  only), catalogs, game files.
- **Schemas** (in `schemas/`, checked by `scripts/common/jsonschema_lite.py`):
  `manual-mappings-2`, `manual-mappings-local-1`, `verifications-1`, `mission-map-1`,
  `ce-voice-asset-3`, `mcc-dialogue-tag-3`.
- **Current state:** `manual_mappings.json` has **0 slots**. Its pins are set (CE build, MCC Steam
  build `19905945`, Spanish FSB SHA-256).

## 5. The one tested pair (an experiment, not a mapping)

The owner selected and in-game verified `es:A10_010_cryotech#0` ← `vo_scr_m01_00460_cryotech#0`
(Spanish(Mexico)):
- E3, `v-000019`;
- build manifest `work/b2/e3/e3_manifest.json`.

It is **not** in `manual_mappings.json`. The owner decides it through M4 like any other line. The
UI may show the existing `verifications.json` entries for a slot or line as read-only context.

## 6. Commands

```
python -m unittest discover -s tests          # 124 tests, all passing at handoff
python scripts/validate/validate_project.py   # read-only; run before every commit touching mappings/
```

The validator reported, at handoff: 220 CE + 101 MCC records, 0 mappings, 19 verifications, no
findings, no drift.

## 7. Git

Branch `master`. Checkpoints:

| Commit | Content |
|---|---|
| `5df43a5`–`a4bbd68` | M3: schemas, validator, `mapping_store` |
| `64e2ec3` | the M4 design |
| `1c97825` | the E3 pipeline (`audio_pipeline.py`, `bank_checks.py`) |
| `41bc1f7` | E3 offline |
| the commit after it | E3 in-game result + this handoff |

## 8. Limits and out of scope for M4

- **Local only.** No network beyond 127.0.0.1, no installs (stdlib), no new tools without approval.
- **No auto-matching**, ranking or pre-filling of any kind.
- **M4 does not touch audio banks or subtitle tables.** Building banks is M6 (reuse
  `scripts/common/audio_pipeline.py`, `fsb5_writer.py`, `bank_checks.py`). Installing is always an
  owner-approved step (`scripts/discovery/b2_bank_install.py`).
- **Stereo slots** (40 bank-wide; **none in `a10`**: all 101 are mono) need an owner choice; there is no
  tooling for them yet.
- **CE coverage:** only M01 is catalogued and decoded. Other missions need M1/M1b runs first.
- **Speaker labels** are out of scope (B1).

### Future blockers (keep visible)

- **Steam Workshop:** there is no documented way to ship replaced FSB banks or localization tables;
  our route replaces installed files ([`workshop-research.md`](workshop-research.md), WC-2/3 pending).
- **Redistribution:** CE audio and text are another game's assets. A public release containing them
  is presumed not permitted under the MCC FAQ (`workshop-research.md` §2; roadmap M8.1–M8.2).
  Development stays local.
