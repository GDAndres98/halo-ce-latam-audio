# Roadmap — Halo CE (MCC) LATAM Spanish Localization

**Updated:** 2026-10-08. Planning document. Schemas:
[`dialogue-catalog-design.md`](dialogue-catalog-design.md) (v2).
Personal, local-only project, no distribution (owner decision,
2026-10-08).

## 1. Scope

### v1.0 — required

1. Replace what MCC plays for **Halo CE campaign dialogue in the Spanish
   (Spain) language slot** with Campaign Evolved **Spanish(Mexico)**
   recordings.
2. Replace MCC's **Spanish Halo CE subtitles** with CE **es-MX**
   subtitles **or the user's custom text**.
3. Audio and subtitle choices are **independent per line**.
4. **All cross-game matching is manual**, by the user.
5. **Approved mappings are never overwritten** by any tool.
6. **Unmatched lines and custom subtitles** are first-class. Unmatched
   slots keep the original Spain audio unless the user decides
   otherwise.

### v1.1 — potential

- Repair CE recordings that lack the radio effect the MCC context
  expects, via **non-destructive** processing. Originals and processing
  metadata are preserved (design §6). **Not implemented and no effect
  chosen yet.**

### Out of scope

- Adding a new "Spanish (Latin America)" menu entry (impossible as data
  only, per feasibility §10.6).
- Distribution.
- Automatic matching.
- Changes to Campaign Evolved.

## 2. Current status

| Area | Status | Evidence |
|---|---|---|
| MCC FSB5 parsing + CELT decode | ✅ 5 `a10` EN/ES pairs decoded, durations cross-checked | feasibility §14 |
| CE audio ↔ subtitle link | ✅ 1 line, all hops explicit, **manually verified by the user (2026-10-08)** | poc-ce-line-link.md |
| CE containers | ✅ unencrypted; Oodle + usmap reading works | remake-audio-research.md |
| MCC subtitle **replacement** | ⛔ **v1.0 blocker B1**: key↔string and tag↔subtitle unresolved | subtitle-research.md B.2 |
| FSB5 **rebuild** + game acceptance | ⛔ **v1.0 blocker B2**: unverified, not attempted | feasibility §10.8 |
| CE catalog, mission M01 | ✅ 220 voice assets, metadata only, deterministic (M1, 2026-10-08) | §3 M1 below, remake-audio-research.md §9 |
| MCC catalog, level a10 | ✅ 101 tags, 202 samples decoded, deterministic (M2, 2026-10-08) | mcc-a10-catalog.md |
| Mapping / UI | design only | dialogue-catalog-design.md |

## 3. Milestones and acceptance criteria

Each milestone needs explicit approval before it starts. Nothing in
M1–M5 writes outside `work/` or `mappings/`, or modifies a game file.

### M0 — CE line-link PoC ✅ DONE (2026-10-08)
- [x] Explicit chain voice asset → event → es-MX media and → StringTable
  → es-MX `.locres` for `VO_SCR_M01_00460_CryoTech`.
- [x] User listened to en / es-MX / es-ES and confirmed that audio
  matches subtitles.

### M1 — CE catalog for mission M01 (metadata only) ✅ BUILT (2026-10-08), user spot-check pending
Owner decision 2026-10-08: asset-name-based `ce_line_ref`
(`<record_id>#<n>`) is **approved**.
Plan in §4.1. Run: `python scripts/catalog/build_ce_catalog.py --mission M01`
(≈ 3 s). Outputs (all git-ignored): `work/ce/catalog/m01.jsonl`,
`work/ce/build.json`, `work/ce/reports/m01_{coverage,unresolved}.json`,
`work/ce/reports/m01_summary.md`. Results: remake-audio-research.md §9.
Acceptance:
- [x] Every voice asset under the M01 scripted and cinematic folders is
  either present in `work/ce/catalog/m01.jsonl`, or listed in a
  `skipped` report with a reason. **No silent drops.** → 220 files,
  220 records, 0 skipped (`accounted_for: true`).
- [x] Every record's es-MX media and es-MX subtitle carry an evidence
  value. Missing items are `unresolved` with a reason and are **never**
  filled from another culture. → 207 explicit / 13 unresolved each.
- [x] A coverage report lists counts by evidence level and by voice-asset
  class. Classes other than `HaloAudioVoiceVariations` are reported, not
  guessed. → all 220 are `HaloAudioVoiceVariations` with one
  `VoiceEvents` entry.
- [x] Every M01 StringTable key is accounted for: referenced by a voice
  asset, or listed as orphaned. → SCR 101/101 referenced; CIN 92/95
  (3 orphans); 1 cinematic asset uses `VO_SYS_Mendoza`.
- [x] New parser paths have synthetic-byte tests, and the whole test
  suite passes. → 27 tests (`tests/test_ce_catalog.py` +
  `tests/test_parsers.py`).
- [x] No decoding in M1 unless separately approved (decoding ≈ 200 lines
  × 2 languages is listed as option M1b). → `.wem` bytes are hashed
  (sha256) for fingerprints, never decoded or written; `duration_s` is
  `null`.
- [x] Output is deterministic (two runs → identical hashes) and carries
  schema + source build identifiers.
- [x] The user spot-checks ≥ 5 records (listening + reading). → All 5
  M1b picks **passed** (owner, 2026-10-08), recorded as
  `v-000002`–`v-000006` in `mappings/verifications.json`.

### M1b — Decode M01 es-MX + en media ✅ BUILT (2026-10-08), user listening pending
Run: `python scripts/extraction/export_ce_audio.py --mission M01`
(about 12 s, approved vgmstream r2117). Outputs (all git-ignored):
- `work/ce/audio/m01/<language>/<ref>.wav`
- `work/ce/media/<language>/<media_id>.wem` (byte-identical copies)
- `work/ce/audio/m01/manifest.json` (`ce-audio-export/1`)
- `work/ce/reports/m01_audio_{coverage.json,summary.md}`
- `work/ce/reports/m01_review_picks.{json,md}`

Results: remake-audio-research.md §10.
- [x] es-MX and en recordings of every linked catalog reference are
  decoded. → 207 references per language, 194 unique media each, 388
  WAVs, all `ok`.
- [x] The 13 `test_event` (`_lipsync`) records are excluded from
  decoding, but their catalog records and anomaly reports are kept.
  They are reported as `excluded:test_event`, not as failures.
- [x] Repeated media is decoded once per language. The 13 `…1` replays
  point at their `…0` sibling's file, and every reference is kept on
  the unit.
- [x] Filenames are stable and derived from the primary `ce_line_ref`
  (`<record_id>__<n>.wav`). The primary is never a replay.
- [x] The manifest records media ID, pak path, container, `.wem` sha256
  (verified against the catalog before decoding), WAV path, sha256,
  sample rate, channels, frames, duration and peak.
- [x] Missing, empty, silent, unreadable and failed audio, plus source
  hash mismatches, are detected and reported. Nothing is synthesized or
  substituted. → 0 problems.
- [x] The manifest and reports are deterministic (two runs → identical
  hashes, including every WAV sha256).
- [x] The cross-family Mendoza line is kept in `manual_review`.
- [x] Synthetic-fixture tests pass → 40 tests total.
- [x] The user listens to and reads the five review picks. → All passed
  (2026-10-08): correct dialogue, complete audio, matching subtitles.
  `00941` has no subtitle by design, so no subtitle check was recorded.

### M2 — MCC catalog for level a10 (copies only) ✅ BUILT (2026-10-08), user listening pending
Plan in §4.2. Run: `python scripts/catalog/build_mcc_catalog.py --level a10`
(about 8 s). Results and outputs: [`mcc-a10-catalog.md`](mcc-a10-catalog.md).
Acceptance:
- [x] All 101 `sound\dialog\a10\…` tags from `.lst.bin` are present,
  with their EN and ES samples taken from each bank's own name table.
  → 101/101 in both languages, resolved independently per bank. The
  `.lst.bin` ranges agree for 101/101.
- [x] Slot identity is verified. → `a10` names are unique in the
  Spanish bank, and no tag has permutations. The bank-wide repeated
  names (765) led to `slot_id = es:<name>#<occurrence>` for every level
  (design §4.1).
- [x] Count mismatches (EN vs ES samples per tag) are reported per tag.
  → none in `a10`.
- [x] `work/mcc/build.json` pins the bank SHA-256 values. Runs reuse
  the existing copies in `reference-audio/stage1/`. → The copies are
  verified against the pins, and the install still matches them (Steam
  build 19905945).
- [x] Subtitle fields stay `unresolved` (B1). → 101/101.
- [x] a10 WAVs are decoded in both languages. → 202/202 OK, with WAV
  frames == header sample count for every sample.
- [x] The JSONL catalog, manifest and reports are deterministic.
  Missing, duplicate and failed samples are reported (→ none).
- [x] Synthetic tests pass → 52 tests total.
- [x] The owner listens to the five review picks
  (`work/mcc/reports/a10_review_picks.md`). → All passed (2026-10-08):
  correct audio, complete recordings, expected dialogue. Recorded as
  `v-000007`–`v-000011`.
- [x] Owner decision (2026-10-08): `slot_id =
  es:<spanish_sample_name>#<occurrence>` is **approved**. Occurrence
  follows Spanish bank order. ID changes must be detected and never
  silently renumbered (guard implemented in M3).

### M3 — User-owned files, schemas, validators (no UI) ✅ BUILT (2026-10-08), awaiting owner review
Design: [`dialogue-catalog-design.md`](dialogue-catalog-design.md) §5.5. Run:
`python scripts/validate/validate_project.py`. On the current project
it reports 220 CE + 101 MCC records, 0 mappings, 11 verifications, no
findings and no drift.
- [x] `schemas/*.json` for the CE record, MCC record, mappings,
  local file and verifications. → Six versioned schemas, including
  `mission-map/1`. The CE and MCC catalog schemas are separate and
  reject each other's records.
- [x] `mappings/verifications.json` is created with the M0 verification
  (design §5.3). → Created early, 2026-10-08, at the owner's request.
  It now holds `v-000001`–`v-000011`.
- [x] A read-only validator flags unknown IDs, schema errors and
  fingerprint drift (written to `work/reports/drift.json`). It also
  checks:
  - duplicates and conflicting decisions, and reference resolution;
  - provenance against `build.json`;
  - append-only verifications and approved-object protection against
    `git HEAD`;
  - pins, local-file ignore status, and that no proprietary files are
    tracked.
- [x] Tests prove that a write path **cannot** change an `approved`
  `audio` or `subtitle` object, that backups are made before every
  save, and that a stale-hash save is refused. → `mapping_store.py`
  plus 20 tests in `tests/test_m3_validation.py`. Disabling either
  protection makes tests fail; this was checked once.
- [x] Independent audio/subtitle decisions, multiple audio sources
  (`ce`, `ce_concat`, `user_recording`, `composite`), custom text via
  the git-ignored local file.
- [x] Empty templates: `manual_mappings.json`, `mission_map.json`,
  `manual_mappings.local.example.json`.
- [x] Slot-ID change guard in `build_mcc_catalog.py`
  (`--accept-id-changes` to override) → `a10`: no changes.

### M4 — Local matching UI
- [ ] It runs on 127.0.0.1 and uses the stdlib only (no install
  without approval).
- [ ] It shows the MCC slot (EN + ES audio and durations), CE search
  filtered by the user's `mission_map.json`, CE en / es-MX audio and
  text, and evidence levels.
- [ ] Separate approve actions for audio and subtitle, a custom-subtitle
  editor (local file only), and "no equivalent" / "defer".
- [ ] No suggestions or ranking, and nothing is pre-filled.
- [ ] Decoding on demand stays under `work/`.

### M5 — a10 mapping complete (user work)
- [ ] Every a10 Spanish slot has `match.status ≠ unreviewed` and an
  approved `audio` object. `subtitle` may wait on B1.
- [ ] The validator is clean, and there are drift checks for the
  current builds.

### M6 — Build pipeline (gated by B1 + B2)
- [ ] Non-destructive conversion: CE es-MX media → MCC slot format, with
  recipes (design §6).
- [ ] The Spanish bank is rebuilt **as a new file in `work/`**. Every
  untouched sample stays byte-identical, and the result parses with
  `fsb5_lib` and vgmstream.
- [ ] Subtitle output follows whatever B1 establishes.

### M7 — Install / rollback + in-game test on a10 (gated, explicit approval)
- [ ] There is a documented backup → install → verify → restore
  procedure using hashes.
- [ ] Restore is proven byte-identical (feasibility §11.2 hashes).
- [ ] The user confirms in game: replaced a10 lines play, unmatched
  lines play Spain audio, and subtitles are as chosen.

### v1.0 — repeat M1–M7 for all levels
(a30, a50, b30, b40, c10, c20, c40, d20, d40, plus generic/systemic barks)

### v1.1 — radio-effect repair
Flagged lines get processed copies via recipes. A/B listening is
recorded in `verifications.json`.

## 4. First-mission catalog generation plan (M1 + M2)

### 4.1 CE side — M01 "Pillar of Autumn" (read-only)

Inputs come from the IoStore indexes (counts from Phase 2 discovery):

| Source | Count | Notes |
|---|---|---|
| `Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/` | 114 packages | PoC class `HaloAudioVoiceVariations` |
| `Audio/scripted/vo_scr_m01pillarofautumn_lipsync/` | 13 | probably the same lines with a lip-sync variant; check the class |
| `Audio/cinematic/vo_cin_m01pillarofautumn/` | 93 | class not yet observed |
| StringTables `VO_SCR_M01PILLAROFAUTUMN` / `VO_CIN_M01PILLAROFAUTUMN` | 101 keys / unknown | the authority for subtitle keys |
| Systemic per-character banks | many | **deferred** to after a10 scripted/cinematic |

Steps:
1. Enumerate packages in the three folders (`inspect_iostore --find`).
2. Run the linker per package, extended for:
   - multiple `VoiceEvents` entries;
   - the `HaloAudioSound` shape;
   - unknown classes, which are recorded as unresolved rather than
     guessed.
3. Cross-check against the StringTable key lists to produce the
   orphan/coverage report.
4. Write `work/ce/catalog/m01.jsonl` + `work/ce/build.json`.
   Optionally (M1b, separate approval) decode es-MX + en media for M01
   into `work/ce/audio/`.

Expected anomalies to report, not fix: 114 voice packages vs 101
subtitle keys; possible duplicate lines in the `_lipsync` folder;
temporary mocap assets.

**Outcome (M1):** the 114 vs 101 gap is 13 `…1`-suffixed assets that
replay their `…0` sibling's event and media and carry no transcription.
The 13 `_lipsync` assets reuse real line keys but play a muted test
event. There are no temp-mocap assets in M01. Details in
remake-audio-research.md §9.

### 4.2 MCC side — level a10 (copies only)

1. Reuse `reference-audio/stage1/{fsb,lst}` copies (hashes already
   recorded).
2. For each of the 101 `a10` tags, read every EN and ES sample whose
   name-table entry belongs to that tag. This answers how permutations
   are named.
3. Write `work/mcc/catalog/a10.jsonl` + `build.json`. Decode only on
   demand (existing `scripts/extraction/extract_dialogue_samples.py`).

**Mission map** (user-owned, not inferred): the first entry the user
will confirm is `a10 ↔ M01`. MCC `a10` tags include both cutscene and
in-mission lines (e.g. `a10_010_cryotech`), so the user will search
both CE scripted and cinematic records.

## 5. Automation vs manual review

| Task | Who | Notes |
|---|---|---|
| Enumerate assets, resolve explicit links, label evidence | **tool** | read-only |
| Coverage / orphan / anomaly reports | **tool** | never auto-fixes |
| Hashing, pins, drift detection | **tool** | drift goes to a report only |
| Decoding for listening | **tool, on demand** | into `work/` |
| Schema / ID validation | **tool** | read-only |
| Level ↔ mission map | **user** | `mission_map.json` |
| Cross-game pairing, 1→n splits, concatenation order | **user** | the core manual work |
| Audio approval, trims | **user** | per slot |
| Subtitle source choice + custom text | **user** | independent of audio |
| `no_equivalent` / `deferred` decisions | **user** | default = keep Spain audio |
| Listening QA of CE records (sampling) | **user** | recorded in `verifications.json` |
| Radio-effect flags (v1.1) | **user** flags, **tool** processes | non-destructive |
| In-game acceptance | **user** | M7 |

Volume estimate: 1,903 MCC dialogue tags. a10 alone has 101 tags and
roughly 200 CE candidate assets. Pairing is the dominant cost.

## 6. v1.0 blockers and research options (no binary edits)

"No binary edits" means:
- read-only analysis of copies;
- documentation research;
- observation of the unmodified game.

Anything that patches, repacks or injects is excluded until separately
approved.

### B1 — MCC Halo CE subtitle replacement

Unknowns:
- (a) how a key maps to its string in `<LANG>_Halo1.bin`;
- (b) how a dialogue tag maps to a key;
- (c) whether MCC loads a modified/overridden table at all.

| # | Option | Cost | What it could answer |
|---|---|---|---|
| R1 | Read-only analysis of the **debug tables** `DBG_ID_Global.bin`, `DBG_LBL_Global.bin`, `DBG_BLNK_Global.bin`, `DBG_MAX_Global.bin` (copies). Debug "languages" often render string IDs or labels as text | low | key derivation (a/b) via the Global tables, applied to Halo1 |
| R2 | Compare **all 12 `*_Halo1.bin` + `*_Global.bin`** tables structurally: key sets, segment counts, empty-segment positions | low | pool indexing scheme (a) |
| R3 | **Hash-of-text hypothesis**: test whether keys = hash(English text) or hash(label) for common hash functions | very low | (a) |
| R4 | **Ground truth by observation**: the user plays the first minutes of a10 in Spanish with subtitles and notes about 10 subtitle lines. No modification | user time | validation pairs for R1–R3 and evidence for (b) |
| R5 | Documentation: official MCC modding docs, HCEEK docs (inside `HCEEK.7z`, **extraction needs approval**), community wikis | low | whether subtitles are moddable through official tools (c) |
| R6 | HCEEK tag definitions (after R5 approval): check for subtitle/string fields in MCC-era sound or scenario tag definitions | medium | whether subtitles originate in tags (b, c) |

Excluded without new approval:
- disassembling or debugging `halo1.dll` / MCC executables;
- reading process memory;
- writing any file in the MCC install.

### B2 — FSB5 rebuild + game acceptance

Unknowns:
- a tool able to write FSB5 with the bank's codec (CELT);
- whether a bank must be single-codec;
- whether MCC validates banks;
- how a mod is loaded/overridden safely.

| # | Option | Cost | What it could answer |
|---|---|---|---|
| R7 | Documentation research on the FMOD version in use (version resource of `fmodex64.dll`, read-only), FSB5 + CELT encoder availability, and FMOD tool licensing | low | which encoder can produce compatible samples |
| R8 | Read-only re-analysis of the Spanish bank: per-sample codec (FSB5 has one `mode` per bank), alignment, metadata chunk type 3 | low | constraints a rebuild must preserve |
| R9 | Research MCC's official mod loading for Halo CE (Workshop/mod folders, EAC-off requirement per 343i FAQ) | low | (c) without touching the install |
| R10 | *(needs approval later)* Sandbox rebuild of a **copy** in `work/`, validated with `fsb5_lib` + vgmstream | medium | rebuild correctness (M6) |
| R11 | *(needs approval later)* Reversible in-game test with a hash-verified backup/restore | high | game acceptance (M7) |

Also note: CE media decode at 48 kHz while MCC slots are 44.1 kHz CELT,
so resampling is a v1.0 requirement, independent of v1.1 effects.

## 7. Risks (carried forward)

| Risk | Impact | Mitigation |
|---|---|---|
| B1 unresolvable without RE | v1.0 subtitles blocked | R1–R6. If all fail, the owner decides whether to approve deeper research or defer subtitles |
| B2 encoder or acceptance fails | v1.0 audio blocked | R7–R9 before any rebuild |
| Duration mismatch (CE es-MX ≠ MCC Spain sample length; cinematics time-locked) | lines cut off or overlap | durations + delta in UI, trims recorded |
| Game patches (CE or MCC) | stale IDs | pins + drift reports; approvals never auto-edited |
| CE content divergence (rewrites, M12–M14 DLC, splits) | unmatched slots | `no_equivalent` + keep Spain audio + custom subtitle |
| Spanish bank has fewer samples than English | slot confusion | slots keyed on Spanish samples (design §4) |
| Local copies of game data (work/, reference-audio/) | accidental commit | `.gitignore`; review `git status` before every commit |

## 8. Approvals

Granted by the owner on 2026-10-08, to be executed **sequentially with
review between tasks**: M1, M1b, M2, B1 research R1–R4, extraction of
`HCEEK.7z` (for R5/R6), and B2 research R7–R9.

| Task | Status |
|---|---|
| M1 | ✅ built; awaiting owner review + spot-check |
| M1b (decode M01 es-MX + en media into `work/`) | ✅ built; awaiting owner review + listening |
| M2 (MCC a10 catalog from existing copies) | ✅ done; 5 samples verified (`v-000007`–`v-000011`) |
| M3 (schemas, validators, protected store) — approved 2026-10-08 | ✅ built; awaiting owner review |
| B1 R1–R4, `HCEEK.7z` extraction | approved, not started |
| B2 R7–R9 | approved, not started |
