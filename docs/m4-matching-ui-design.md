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
  - `user_recording` / `composite` audio sources are kept, but they can't be edited in the UI yet
    (`edit` recipes can since 2026-10-09, §9);
  - stereo slots are only badged (`st`).
- Clicking **+ use** on a CE line sets the match status to *matched* when it was *unreviewed* or
  *no equivalent*. That is the owner's own click, not a suggestion. The audio and subtitle choices
  are never changed by it.

## 8. Update 2026-10-08: search, missing subtitles, radio flag

- **Stack decision: kept Python (stdlib) with one static HTML/JS page.** A Node/TypeScript
  rewrite was allowed but brings no clear benefit here:
  - the app has to call the existing Python store, schemas, validator and audio tools in-process;
  - a second runtime would mean a toolchain, dependencies and a parallel implementation of the
    approval protections;
  - the page is about 600 lines of plain JS and needs no build step.

  Nothing new to install.
- **Search** (`m4_app.parse_query` / `fold`, mirrored by `foldMap` / `hl` in `m4.html`):
  - words match partially; `"quoted phrases"` must appear together;
  - case, accents and punctuation are ignored;
  - MCC slots search the SU, SP and **EN** (`EN_Halo1.bin`, speaker label kept apart) text plus
    the IDs, tag, bank name and speaker; `level=all` searches every level;
  - CE lines search the es-MX/en/es-ES text, ID, display key and folder; `subs=missing|present`
    filters on es-MX source text;
  - matches are highlighted in the page;
  - a search is still only a filter: catalog order, no scores (tested).
- **Missing source subtitles:**
  - `ce_line.has_source_subtitle` per culture;
  - a "no subtitle" badge with the catalog's reason;
  - a dashed notice on matched lines, with a shortcut to a custom subtitle;
  - cultures without text are disabled for *CE text*, and approving missing CE text is refused
    (422);
  - custom text stays a draft until approved separately, and persists in the local file;
  - the catalogs are never touched.
- **Needs radio effect:** the slot-level `radio_effect` in `manual-mappings/3`
  ([`dialogue-catalog-design.md`](dialogue-catalog-design.md) §5).
  - It is toggled with Save, independently of the approvals, with its own revision.
  - It survives *needs rework*.
  - It is only valid with selected CE audio.
  - It has a slot filter, an **R** badge, and a count in the level progress.
- **Stereo slots:** a badge, a slot filter and a notice. They are playable, but replacement is
  deferred.
- **Tests:** `tests/test_m4.py` (31 tests) covers search, the missing-subtitle flow, custom-text
  persistence across restarts, the radio flag, the v2→v3 migration and slot-ID round trips. The
  headless-Edge click-through was extended with search highlighting, the no-subtitle filter, a
  custom subtitle, and the radio flag across a reload.

### 8.1 Owner preference: CE defaults and "approve both" (2026-10-08)

- **CE defaults** (`applyCeDefaults` in `m4.html`) run only when the owner clicks **+ use** on a CE
  line, or removes the line a CE subtitle was using.
  - The audio changes from `keep_original` to `ce`/`ce_concat` over the picked lines.
  - The subtitle changes from `keep_original` to `ce_locres`, using es-MX of the first picked line
    with text.
  - They never choose a CE line, never override `custom`/`none` or approved parts, and never
    rewrite saved decisions on load. The "no suggestions, no pre-filled matches" rule still holds:
    the owner picks every line.
- **Approve audio + subtitle** sends both `approve` actions in one save, so there is one write and
  one backup (tested). It is shown only while neither part is approved.
- **Hide lines already used** (`/api/ce?hide_used=1&keep_slot=<slot>`) drops CE lines listed in any
  other mapping's `match.ce_line_refs`. The current slot's own lines stay visible. Each line
  carries `used_by`, and the page shows a "used ×N" badge. It is a filter only: the order is
  unchanged and nothing is selected (tested).
- **Different dialogue, but fits the scene:** an optional slot-level flag, `different_but_fits`.
  - It sits in the Match card because it describes the match.
  - It is toggled with Save, independently of the approvals, and needs a matched CE line.
  - It has a "different but fits" slot filter, a **≈** badge, and a count in the level progress.
  - Tests: `DifferentButFitsTests`, which include slots saved before the flag existed.

## 9. Audio editor (2026-10-09)

User guide §4.1. Goal: adjust a CE recording before M6 encodes it, without ever changing a file.

- **Where the recipe lives:** `audio.edit` (`manual-mappings/3`). The existing `{trim_start_s,
  trim_end_s, gap_s}` object gains optional fields, so no migration is needed and every existing
  file stays valid and byte-identical:
  - `engine`;
  - `for_source` (the CE line and language it was made for);
  - `cuts`, `fade_in_ms`/`fade_out_ms`, `crossfade_ms`;
  - `speed`, `gain_db`, `loudness {mode: off|match_mcc, offset_db}`, `limiter`.

  All zero is the identity and is stored in the old three-field form.
- **Why inside `audio`:** the recipe is part of the audio decision. Approval pins it, and the
  existing protections (tools never approve; approved is immutable; only *needs rework* + 1) cover
  it with no new rule. Owner flags (`radio_effect`, `different_but_fits`) stay outside and are
  untouched.
- **One implementation:**
  - `common/audio_edit.py` holds the pure DSP and recipe rules, with ffmpeg injected for the tempo.
  - `audio_pipeline.render_edited` / `derive_edited` / `codec_roundtrip` are shared by
    `common/edit_preview.py` (M4) and `scripts/build/m6_build.py`.
  - The *as encoded* preview is the libcelt decode of the stream M6 writes, so preview and build
    can't drift apart. A test asserts byte equality.
- **DSP choices:**
  - **Rubberband** (via the installed ffmpeg) for speed: deterministic and length-exact. `atempo`
    dropped about 20 ms at the end in a test.
  - **BS.1770-4 loudness** in pure Python. The K-weighting reproduces the standard's 48 kHz
    coefficients; a 997 Hz full-scale sine reads −3.01 LUFS.
  - **Equal-power crossfades** at cuts.
  - **Half-cosine edge fades.**
  - **A look-ahead peak limiter.** Every output sample is ≤ −1 dBFS by construction. Loudness
    matching re-measures after limiting, with secant steps.
- **Loudness reference:** the slot's own Spain recording, decoded from the pinned bank (never a
  global target).
- **Safety:**
  - An edit is bound to its source. Changing the line or language resets it, and the validator and
    builder refuse a `for_source` mismatch.
  - Recipes are checked against the source duration before saving.
  - Previews write only to `work/m4/preview/`.
- **Stack:** still the Python standard library plus one static page. Waveforms are drawn from Web
  Audio `decodeAudioData` on a `<canvas>`. Nothing new is installed: ffmpeg and libcelt were already
  approved.
