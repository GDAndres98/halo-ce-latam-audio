# M4 — Minimum Viable Matching UI

**Status:** implemented 2026-10-08 (§7). It reuses the M1–M3 outputs and
`scripts/common/mapping_store.py`. No new dependencies. How to use it:
[`m4-user-guide.md`](m4-user-guide.md).

## 1. What it must do

You, the owner, work through the Spanish slots of one MCC level. For
each slot you:
1. **listen** to the MCC Spain recording, and to the English one for
   reference;
2. **listen** to Campaign Evolved candidates from the mapped mission,
   in es-MX and en;
3. **pick** zero or more CE lines (ordered), or mark *no equivalent* or
   *defer*;
4. **choose the subtitle:** CE es-MX text, your own custom text, or
   keep MCC's;
5. **approve audio and subtitle separately**;
6. **save** without being able to overwrite anything already approved.

The UI never suggests, ranks or pre-fills a match. A text search you
type yourself is a filter, not a suggestion.

## 2. Shape: one local page, one small server

```
python scripts/ui/m4_server.py --level a10        # http://127.0.0.1:8765, stdlib http.server only
```

- **Server:** `scripts/ui/m4_server.py`, about 400 lines, stdlib only.
  It binds to **127.0.0.1** only.
- **Page:** `scripts/ui/m4.html`, one static file with plain JS and no
  build step. It uses `<audio>` elements and `fetch` to the JSON API.

### Data it reads

All of it already exists:
- **MCC slots:** `work/mcc/catalog/<level>.jsonl`. It supplies the
  `slot_id`, tag, Spanish and English sample index, and duration.
- **MCC audio:** `work/mcc/audio/<level>/{spanish,english}/*.wav`
  (the M2 decodes).
- **MCC subtitles:** `SU`/`SP` text for the slot's tag, read from
  `work/mcc/loc/copies/*_Halo1.bin` with
  `mcc_loc.loc_key(tag)`, looked up per table.
- **CE lines:** `work/ce/catalog/<mission>.jsonl`. It supplies
  `ce_line_ref`, the es-MX/en/es-ES subtitle text and the media.
- **CE audio:** `work/ce/audio/<mission>/<lang>/*.wav` and its manifest
  (the M1b decodes). Missing decodes are run on demand with the
  existing `export_ce_audio.py`.
- **Level → mission:** `mappings/mission_map.json` (your `a10 ↔ M01`).
- **Decisions:**
  - `mappings/manual_mappings.json`, via `mapping_store.load`, which
    keeps the loaded SHA-256;
  - custom text in `mappings/manual_mappings.local.json`, which is
    git-ignored;
  - `mappings/verifications.json`, read-only, to show past checks.

### What it writes

Nothing else:
- `manual_mappings.json`, **only** through
  `mapping_store.save(path, doc, loaded_sha256, user_actions=…)`;
- `manual_mappings.local.json`, for custom text, through the same
  pattern: atomic write, a `.history/` backup, and a stale-hash
  refusal. This is a small helper next to `mapping_store`.

## 3. Screen (single page, three columns)

```
┌ Slots (a10) ───────────┐┌ Slot es:A10_140_cryotech#0 ──────────────┐┌ CE candidates (M01) ─────────────┐
│ filter: [unreviewed ▾] ││ ▶ Spain 4.30 s   ▶ English 4.57 s        ││ search [ text / id …        ]    │
│ search [            ]  ││ SU: «…LATAM text…»   SP: «…Spain text…»  ││ VO_SCR_M01_00460_CryoTech #0     │
│ ● A10_010_cryotech  ✔A ││ Match: [VO_SCR_M01_00460 #0] [×] [↑↓]    ││   ▶ es-MX 3.21 s  ▶ en 3.05 s    │
│ ○ A10_011_cryoassist   ││   ( ) matched ( ) no equivalent ( ) defer ││   es-MX: «…»  en: «…»            │
│ ◐ A10_020_cryotech  ✔S ││ Audio:  (•) CE  ( ) keep Spain            ││   [ + use for this slot ]        │
│ …                      ││         Δ duration vs Spain: −1.09 s      ││ VO_SCR_M01_00470_… #0            │
│                        ││         [Approve audio]  status: draft    ││   …                              │
│ legend: ✔A audio ok    ││ Subtitle: (•) CE es-MX ( ) custom ( ) keep││                                  │
│         ✔S subtitle ok ││   preview: «…» (n chars)                  ││ order: catalog order (no ranking)│
│                        ││   [Approve subtitle]  status: draft       ││                                  │
│                        ││ [Save]  [Mark needs rework…]  notes [  ]  ││                                  │
└────────────────────────┘└───────────────────────────────────────────┘└──────────────────────────────────┘
```

- **Candidate order:** CE candidates appear in **catalog order**. The
  search filters on your query (ID or any subtitle text) and never
  scores anything.
- **Duration delta:** shown as a plain fact, because CELT length and
  timing matter (E1b), not as a hint.
- **Approved objects are read-only.** Changing one requires *Mark needs
  rework*, which asks for confirmation. That sends
  `UserAction("needs_rework")`, and the store bumps the revision.
- **Approve buttons** send `UserAction("approve", mapping_id, field)`.
  The server fills in the `fingerprint` with
  `project_validation.audio_fingerprint` / `subtitle_fingerprint`; the
  schema requires one for approval.
- **Keyboard:** `J`/`K` move between slots, `Space` plays Spain,
  `1`–`9` play a candidate. That's all.

## 4. API (JSON, localhost)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/slots?level=a10&status=` | the slot list with status badges |
| GET | `/api/slot/<slot_id>` | the slot detail, its SU/SP text and the current decision |
| GET | `/api/ce?mission=M01&q=` | CE lines (filtered by `q` only), with texts and durations |
| GET | `/audio/mcc/<lang>/<file>`, `/audio/ce/<lang>/<file>` | WAVs, served only from whitelisted `work/` folders |
| POST | `/api/save` | `{loaded_sha256, slot, user_actions[], custom_text?}`. It returns the new SHA-256, or **409** on a stale save or a protected change, with the store's message |

After every save, the server runs the read-only validator in-process
and shows any findings.

## 5. Build plan (about 1–2 sessions) and acceptance

1. Server and read-only views: lists, detail, audio playback.
2. Save path: match, no equivalent, defer and notes, via
   `mapping_store.save`, with a 409 on a stale save.
3. The approve and needs-rework actions, with fingerprints.
4. Custom text in the local file.
5. Tests: API handlers against a temp mappings file. They prove three
   things:
   - an approved object can't be changed without `needs_rework`;
   - a stale save gets a 409;
   - nothing is written outside `mappings/`.

Acceptance criteria (they extend roadmap M4):
- [ ] It binds 127.0.0.1 only and uses the stdlib only.
- [ ] Both MCC languages and the CE es-MX/en recordings play in the
  browser.
- [ ] Match, no equivalent, defer, approve audio, approve subtitle,
  custom text and needs rework all work.
- [ ] There are no suggestions, scores or pre-fills, and candidates
  appear in catalog order.
- [ ] A save can never change an approved object (store-enforced and
  tested). A stale save is refused.
- [ ] The validator is clean after a session.

## 6. Decisions you can make later (defaults in bold)

- **Concatenation** (`ce_concat`, several CE lines in one slot): **in
  the first version**, as an ordered chip list.
- **Show CE es-ES text too:** **yes, collapsed**. It helps with
  matching, since MCC's Spain dub may follow es-ES wording.
- **Show the SU/SP texts** that the chosen subtitle would replace:
  **yes**.

## 7. As implemented (2026-10-08)

- **Files:**
  - `scripts/ui/m4_server.py`: HTTP, 127.0.0.1 only, with a Host/Origin check;
  - `scripts/ui/m4_app.py`: the logic, no HTTP, so tests drive it directly;
  - `scripts/ui/m4.html`: the page;
  - `scripts/common/ondemand_audio.py`: decoding.
- **Tests:** `tests/test_m4.py` (23 tests) covers the three proofs from §5 plus HTTP, audio and
  progress. A headless-Edge click-through on a scratch copy of the data also passed: draft,
  reorder, approve, custom subtitle, a stale-save 409, needs rework, the progress gate and the
  filter-only search.
- **Campaign scope, not just one level:**
  - the level picker lists every MCC catalog (28 folders);
  - CE candidates can come from the mapped missions, all missions, or one mission, always in
    catalog order (mission, file, entry).
- **On-demand audio:** a recording is decoded the first time it is played. Existing M1b/M2
  decodes are reused (design §2 said "missing decodes run with `export_ce_audio.py`"; per-line
  decoding replaced that).
- **Save rules, enforced before anything is written:**
  - `mapping_store.check_transition`, then `validate_mappings` errors for that mapping, then
    `mapping_store.save`;
  - custom text goes through `mapping_store.save_user_file` (stale check, schema, backup, atomic
    write);
  - changing the text of an approved custom subtitle counts as a change and needs *needs rework*.
- **Level status (new):** `mappings/mission_progress.json` (`mission-progress/1`) holds the
  owner-set steps `in_progress`, `ready_for_build`, `in_game_tested` and `reviewed`.
  - `ready_for_build` and later need every slot decided with approved audio (the M5 criterion).
  - `in_game_tested` and `reviewed` need an explicit confirmation.
  - The validator checks the file.
- **UI-only limits:**
  - `user_recording` / `composite` audio sources and `edit` trims are kept, but they can't be
    edited in the UI yet;
  - stereo slots are only badged (`st`).
- Clicking **+ use** on a CE line sets the match status to *matched* when it was *unreviewed* or
  *no equivalent*. That is the owner's own click, not a suggestion. The audio and subtitle choices
  are never changed by it.
