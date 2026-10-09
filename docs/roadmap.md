# Roadmap — Halo CE (MCC) LATAM Spanish Localization

**Updated:** 2026-10-08. Planning document. Schemas:
[`dialogue-catalog-design.md`](dialogue-catalog-design.md) (v2).
Development is local-only. **Intended v1.0 distribution platform:
Steam Workshop** (owner, 2026-10-08). This is planned as M8, gated on
asset rights and on explicit owner approval before any public
publishing. Until M8 is approved, nothing is packaged, uploaded or
shared.

## 1. Scope

### v1.0 — required

1. Replace what MCC plays for **Halo CE campaign dialogue in the Spanish
   (Spain) language slot** with Campaign Evolved **Spanish(Mexico)**
   recordings.
2. Replace MCC's **Spanish Halo CE subtitles** with CE **es-MX**
   subtitles **or the user's custom text**. One canonical approved
   subtitle per slot is written to **both** `SU_Halo1.bin` (LATAM) and
   `SP_Halo1.bin` (Spain). Every unmatched entry keeps its original
   text (owner decision, 2026-10-08; subtitle-research.md B.11).
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

### Language configuration (USER-VERIFIED, 2026-10-08)

Owner's setting: primary **Spanish (Latin America)**, fallback
**Spanish (Spain)**.

| | Current behaviour | v1.0 target |
|---|---|---|
| Subtitles | LATAM (`SU`) | the approved text, written to `SU` (and the same text to `SP`) |
| Audio | Spain Spanish | CE es-MX through the **Spain audio slot** |

First reported by the owner from normal play, then **verified** by the
owner in the B1 baseline (subtitle-research.md B.12 step 1): `SU` text
and Spain audio in both Classic and Anniversary. Recorded as
`v-000012`–`v-000014`.

Speaker names do not appear in Spanish, even with the speaker-name
option on. That is **out of scope**, and the original behaviour is
preserved.

### Distribution target (owner requirement, 2026-10-08)

- The intended final distribution platform for v1.0 is **Steam
  Workshop**, via MCC's official Excession tool (M8).
- This replaces the earlier "personal, local-only, no distribution"
  decision **for the final release only**. All development, catalogs,
  CE extractions and test installs stay local and git-ignored.
- **Known conflict:** 343i's MCC modding FAQ allows "only the assets
  contained within the retail version of MCC" (feasibility §7–8). CE
  es-MX audio and CE subtitle text are Campaign Evolved content. A
  public build that contains them is therefore presumed **not
  permitted** unless M8.1 finds otherwise. M8.2 plans authorized
  alternatives.
- Nothing is uploaded, made public or shared without the owner's
  explicit approval.

### Out of scope

- Adding a new "Spanish (Latin America)" menu entry (impossible as data
  only, per feasibility §10.6).
- Packaging, uploading or publishing anything before M8 is approved.
- Automatic matching.
- Changes to Campaign Evolved.

## 2. Current status

| Area | Status | Evidence |
|---|---|---|
| MCC FSB5 parsing + CELT decode | ✅ 5 `a10` EN/ES pairs decoded, durations cross-checked | feasibility §14 |
| CE audio ↔ subtitle link | ✅ 1 line, all hops explicit, **manually verified by the user (2026-10-08)** | poc-ce-line-link.md |
| CE containers | ✅ unencrypted; Oodle + usmap reading works | remake-audio-research.md |
| MCC subtitle **replacement** | ✅ **B1 resolved (user-reported, 2026-10-08)**: edited `*_Halo1.bin` text displays in game; originals restored and hash-verified; residuals (variable-length text, `SP` runtime sample, per-mode coverage) moved to M7 | subtitle-research.md B.4–B.12 |
| FSB5 **rebuild** + game acceptance | ⛔ **v1.0 blocker B2**: unverified, not attempted | feasibility §10.8 |
| CE catalog, mission M01 | ✅ 220 voice assets, metadata only, deterministic (M1, 2026-10-08) | §3 M1 below, remake-audio-research.md §9 |
| MCC catalog, level a10 | ✅ 101 tags, 202 samples decoded, deterministic (M2, 2026-10-08) | mcc-a10-catalog.md |
| Mapping / UI | design only | dialogue-catalog-design.md |
| Steam Workshop distribution | planned (M8). Compatibility checkpoint WC is planned inside B2. Not researched in depth yet | §3 M8, §6 B2 |

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

### M3 — User-owned files, schemas, validators (no UI) ✅ DONE (2026-10-08), approved by the owner
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
  (`--accept-id-changes` to override) → `a10`: no changes. **Owner
  rule:** ID changes are never accepted automatically. Only the owner
  passes the override, after reviewing the report.
- [x] Owner decisions (2026-10-08):
  - the `manual-mappings/2` changes are approved;
  - `a10 ↔ M01` is entered in `mission_map.json`;
  - pins are populated from the verified builds, written through
    `mapping_store`.

### M4 — Local matching UI
Design: [`m4-matching-ui-design.md`](m4-matching-ui-design.md) (stdlib server on 127.0.0.1, one static page, saves only via `mapping_store`).
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
  `fsb5_lib` and vgmstream. The method is the B2 strategy S-A (CELT
  0.11 splice, `b2-audio-research.md` §3) unless E2 forces a
  fallback. The sample count, order, names and `.lst.bin` stay
  unchanged.
- [ ] Subtitle output (once B1 closes): one generator writes each
  approved `subtitle` into **both** `SU_Halo1.bin` and `SP_Halo1.bin`,
  as new files in `work/`.
  - The key is looked up independently in each table, and a miss in
    either table skips the slot and reports it.
  - Unapproved entries stay byte-identical.
  - The output does not depend on the slot's `audio` decision.
  - Bulk generation needs its own approval, after the PoC.

### M7 — Install / rollback + in-game test on a10 (gated, explicit approval)
- [ ] There is a documented backup → install → verify → restore
  procedure using hashes.
- [ ] Restore is proven byte-identical (feasibility §11.2 hashes).
- [ ] The user confirms in game, in the configuration primary LATAM +
  fallback Spain:
  - replaced a10 lines play;
  - unmatched lines play Spain audio;
  - subtitles are as chosen;
  - unmatched subtitles show MCC's original LATAM text.
- [ ] Backup and restore cover **both** subtitle tables and the Spanish
  FSB, each with its own hash.
- [ ] B1 residuals:
  - a **variable-length** subtitle entry displays correctly;
  - one representative **`SP`** runtime sample (Spain as primary)
    passes;
  - both graphics modes are checked.

  Each result is recorded as a `subtitle_load` / `subtitle_key_link`
  verification.

Note: M7's install method (backup → overwrite → restore) is a
**local test method only**. A Workshop release must install without
overwriting retail files (M8.4). The WC checkpoint (§6 B2) must
therefore settle the delivery route before full-campaign production.

### v1.0 — repeat M1–M7 for all levels
(a30, a50, b30, b40, c10, c20, c40, d20, d40, plus generic/systemic barks)

**Gate:** full-campaign production does not start until the Workshop
compatibility checkpoint **WC** (§6 B2) is reported and the owner has
chosen a delivery route. a10 work (M4–M7) may continue before WC.

### M8 — Steam Workshop packaging and publishing (planning only; not approved)

**Status:** planned. No packaging, no tool installs, no uploads. Each
sub-step needs its own owner approval. **Public publishing needs a
separate, explicit owner approval**, given after the owner reviews the
final package. B1 stays the immediate priority. After B1, M8.1 is the
one sub-step worth starting early, because its answer can change the
audio and subtitle sources for the whole project.

Known so far (official docs, not yet tested):
- Excession is MCC's official tool for configuring mods and uploading
  them to Steam Workshop, and it supports Halo: Combat Evolved
  ([Excession overview](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/excessionoverview),
  [Creating a mod package](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/creatingmodpackage/creatinghome)).
  - A package has a Mod Folder, Mod ID, Steam Workshop ID, title,
    description, Mod Version (`major.minor.patch`) and **Min./Max.
    Game Version**. Both Excession and the game check the version
    range.
  - Content is added through **Campaign / Multiplayer Maps / Firefight
    Maps** sections, so the package is **map-centric**.
- Players subscribe on Workshop and launch MCC with anti-cheat
  disabled. Mods do not run with EAC on
  ([Halo Support: Workshop mods](https://support.halowaypoint.com/hc/en-us/articles/28916975982868-How-to-Download-and-Play-Mods-for-Halo-The-Master-Chief-Collection-via-the-Steam-Workshop)).
- **Unverified:** whether a Workshop mod can replace or override either
  of these shared files:
  - the FMOD bank `halo1/sound/pc/sounds_dialogs_spanish.fsb`;
  - `Data/ui/localization/{SU,SP}_Halo1.bin`.

  The community sound mods found so far tell users to copy files into
  the install by hand, outside Workshop. That is the opposite of M8.4.
  WC answers this first.

#### M8.1 — Asset rights and redistribution (gate for everything below)
- [ ] A rights memo in `docs/`, with citations, covering:
  - 343i's MCC modding FAQ (retail MCC assets only, non-commercial);
  - the Campaign Evolved EULA and any CE modding policy;
  - Microsoft's Game Content Usage Rules;
  - the Steam Workshop / Subscriber Agreement terms for uploaded
    content.
- [ ] A conclusion for each content class: allowed, not allowed, or
  needs permission. The classes are:
  - CE es-MX audio;
  - CE es-MX subtitle text;
  - MCC retail assets, including the existing `SU` LATAM text;
  - owner-authored text;
  - new recordings.
- [ ] If CE content is restricted: a draft written permission request
  to Halo Studios / Microsoft. **The owner decides whether to send it;**
  tools never contact anyone.
- [ ] Until written permission exists, the public build must contain
  **zero CE-derived bytes or text**.

#### M8.2 — Authorized alternatives (if redistribution is restricted)
Evaluate each option, with its cost and what it keeps of v1.0:
- [ ] **New LATAM recordings** by licensed or consenting voice talent
  (feasibility §8), wired through the same slot mappings. The
  `user_recording` source already exists in `manual-mappings/2`.
- [ ] **Owner-authored subtitles** (original text, not copied from CE),
  using the existing custom-subtitle path.
- [ ] **MCC-only content**, for example reusing MCC's own `SU` LATAM
  text, which the FAQ permits.
- [ ] **Two build profiles:**
  - `personal` may use CE sources and never leaves this machine;
  - `public` refuses any slot whose approved source is CE-derived.

  This is a plan only. It needs a per-source `redistributable` rule in
  the schema, approved before any change.
- [ ] **Rejected** unless the owner decides otherwise after M8.1:
  shipping a tool that extracts CE content from the player's own CE
  copy. It still imports non-MCC assets (FAQ), and Workshop cannot run
  tools.

#### M8.3 — Packaging via Excession
- [ ] Read the full Excession docs (setup, root folder, campaign mods,
  upload) and record what a Halo CE package can contain.
- [ ] Choose the package shape from the WC outcome. It is either a
  shared-file override, or rebuilt campaign `.map` files with
  replacement sound tags. The second is the HCEEK route, with a much
  larger scope.
- [ ] Getting or running Excession needs approval (hard rule 5).
- [ ] The mod folder lives outside the repo and outside the MCC
  install. Packaged files never enter Git.

#### M8.4 — Installation without overwriting retail files
- [ ] Confirm that the mod installs only through a Workshop subscription
  and MCC's mod loader, and never writes into the retail install.
- [ ] Prove it by hashing the relevant retail files at three points:
  before subscribing, after subscribing and playing, and after
  unsubscribing. All three hashes must match.
- [ ] If some content cannot be delivered without overwriting retail
  files, Workshop is **not viable for that content**. Report it and let
  the owner choose (WC outcome C).

#### M8.5 — Versioning, compatibility and uninstall
- [ ] Versioning: Excession's Mod Version is the project's release
  semver, with a changelog for each release.
- [ ] Compatibility:
  - map the tested MCC Steam build (currently `19905945`) to the game
    version string that Excession checks;
  - set Min./Max. Game Version to tested builds only;
  - record the CE build used for sources (pins already exist).
- [ ] An MCC update that changes the Spanish bank, the `SU`/`SP` tables
  or slot IDs triggers the existing drift and ID-change reports. It
  blocks a new release until the content is re-verified.
- [ ] Uninstall means unsubscribing, plus any documented manual step,
  verified by the M8.4 hash check. Document it for players in Spanish
  and English.

#### M8.6 — Workshop page, images and documentation
- [ ] Draft the title and description (Spanish first, English second).
  They cover:
  - what the mod changes;
  - the required language settings: primary Spanish (Latin America),
    fallback Spanish (Spain);
  - the EAC-off launch, install and uninstall;
  - known issues and credits;
  - a non-affiliation disclaimer and a non-commercial notice.
- [ ] Images: only screenshots of the modded game that the owner
  captures. No CE artwork. Logos and branding only as the usage rules
  allow.
- [ ] Player docs and a support/issue contact. Drafts live in `docs/`.
  No images or game captures are committed.

#### M8.7 — Release gate
- [ ] A pre-release checklist confirms:
  - the M8.1 conclusions are met;
  - the `public` build profile validates;
  - the M8.4 hash proof passed;
  - the page is reviewed.
- [ ] An optional private or friends-only test upload needs a
  **separate owner approval.**
- [ ] Public publishing needs **explicit owner approval only.** Tools
  never change Workshop visibility.

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

**B1 research results (2026-10-08)** — details in
[`subtitle-research.md`](subtitle-research.md) B.4–B.12. Reproduce with
`python scripts/discovery/b1_subtitle_research.py`.
- **(a) SOLVED, VERIFIED:** keys start at `0x80`, and string *i*
  belongs to key *i*. All 20 tables rebuild byte-exactly from the
  model. (R1, R2)
- **(b) SOLVED, DERIVED:** key = CRC-32/MPEG-2(UPPER(label)); verified
  on 9,098/9,098 debug labels. For Halo 1 dialogue the label is the
  tag path: **101/101 `a10` tags** have a key. Catalog subtitles stay
  `unresolved` until the owner confirms one line in game. (R3)
- **New, VERIFIED:** `SP_Halo1` = Spain Spanish, **`SU_Halo1` = Latin
  American Spanish**. MCC already ships LATAM subtitles for Halo CE.
  There is a second, identical store in `initial_textures.s3dpak`
  (`strings_spanish`, `strings_latam_spanish`).
- **(c) OPEN:** load behaviour. No official localization override is
  documented. The community replaces the `.bin` with EAC off. A
  shipped `localized_string_overrides.xml` exists, but it holds Global
  keys only.
- R4 (owner observation) is still to do; it is step 1 of the PoC. R5
  and R6 are done: `HCEEK.7z` was listed and selectively extracted, and
  the sound tags have no subtitle field.
- ~~**Next (needs approval):** the reversible one-subtitle PoC in
  subtitle-research.md B.11. Recommended strategy: S1, rewrite one
  `*_Halo1.bin`.~~ Superseded by the revision below.

**B1 revision (owner decision, 2026-10-08)** — subtitle-research.md
B.11–B.12:
- **Language behaviour:** primary LATAM + fallback Spain gives `SU`
  subtitles and Spain audio. **Owner-verified** in the baseline, in both
  graphics modes. Speaker names are out of scope.
- **Strategy:** S1 is applied to **both** `SU_Halo1.bin` and
  `SP_Halo1.bin`.
  - One canonical approved subtitle mapping is written to both tables.
  - All unmatched entries are preserved.
  - Keys are validated independently in each table.
  - Audio and subtitle mappings stay independent.
- **Revised PoC (B.12); each step needs approval:**
  0. Pre-flight: hash and pin the installed `SU`/`SP`, read-only. ✅
     Done; all match.
  1. **Baseline first:** observe the unmodified game on three
     cryo-opening discriminator lines and `a10_350_captkeyes`. ✅ Done:
     `SU` text and Spain audio in both modes (`v-000012`–`v-000014`).
  2. Two **one-entry**, same-length, ASCII-marker candidates (`[B1-SU]`,
     `[B1-SP]`) are built **offline** in `work/`. ✅ Done: 16/16 checks
     per table, deterministic. Candidate SHA-256: `SU` `de8cc7ee…d9be`,
     `SP` `9856cfde…b63f`. Install/rollback commands are prepared.
  3. In-game tests, **one table at a time** (3a `SU`, 3b `SP`, optional
     3c both). They use MCC's anti-cheat-disabled launch mode, with a
     hash-verified backup and restore.
  4. Record the results per table in `verifications.json`.
- **Still excluded:** bulk table editing, CE text in any table, FSB
  repacking, and any install change without explicit approval.
- **B1 RESULT (2026-10-08): resolved, user-reported.** The owner
  tested custom subtitles in MCC by hand, and they work.
  - The installed `SU`/`SP` are restored and equal the original hashes.
    An `SU` backup exists; there is no `SP` backup.
  - The details (table, text, modes) were not reported and are not
    assumed.
  - The residuals go to M7 (below).

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
| WC | **Workshop compatibility checkpoint** (below) | low–medium | whether the B2 delivery route works as a Workshop mod |

#### WC — early Steam Workshop compatibility checkpoint (inside B2)

WC runs after R7–R9 and **before full-campaign production**. It also
comes before M6 bulk generation is approved. It decides whether the
current design can ship through Workshop at all. That design replaces
the Spanish FSB slot and patches `SU`/`SP`. WC is planning only, and
each step needs approval.

1. **WC-1, docs (read-only):** read the Excession and MCC modding docs
   to answer three questions:
   - Can a Halo CE Workshop mod override shared files outside `.map`
     files, such as the FMOD banks under `halo1/sound/pc/` and
     `Data/ui/localization/*.bin`?
   - Can a campaign mod reuse the retail campaign and change only audio
     and text?
   - How does MCC choose between mod files and retail files?
2. **WC-2, observation (needs approval):** inspect, read-only, the
   folder layout of one existing Halo CE Workshop mod that the owner
   chooses to subscribe to. No game file changes.
3. **WC-3, report** (`docs/workshop-research.md`). It ends with one of
   three outcomes, and the owner chooses:
   - **A.** The current route works as a Workshop mod → continue.
   - **B.** Workshop needs rebuilt campaign `.map` files with
     replacement sound tags → re-plan B2/M6 (HCEEK route) before
     scaling.
   - **C.** Workshop cannot deliver this content → the owner chooses
     another channel, or the release stays local.

WC never packages, uploads or modifies the install.

Also note: CE media decode at 48 kHz while MCC slots are 44.1 kHz CELT,
so resampling is a v1.0 requirement, independent of v1.1 effects.

**B2 research results (2026-10-08)** — full report:
[`b2-audio-research.md`](b2-audio-research.md). Reproduce with
`python scripts/discovery/b2_bank_inventory.py` (read-only).
- **R7:** the runtime is **FMOD Ex 4.44.27** (`halo1/fmodex64.dll`), and
  it loads FSB5. The banks shipped in the install prove it decodes
  **CELT** (the dialogue, music, stream and debug banks) and
  **IMA ADPCM** (`sounds_adpcm.fsb`). PCM, Vorbis and FADPCM are
  untested.
- **R8, the Spanish bank's invariants:**
  - FSB5 v1, CELT **0.11.0** (flags `0x80000010`).
  - 5,696 samples, all at 44.1 kHz; 5,656 mono and 40 stereo.
  - CBR frames: 370 B mono / 464 B stereo, 512 samples each.
  - 32-byte-aligned ascending offsets.
  - LOOP = `0, n−2` on 5,648 samples.
  - The `.lst.bin` is a **per-language** index into the bank's sample
    positions, so a rebuild must keep the count, order and names.
- **The codec is per bank**, so samples cannot mix codecs. **No public
  tool writes FMOD-compatible CELT today.** HCEEK `tool.exe` embeds
  FMOD FSBankEx 4.x (including an FSB5 writer), but its CELT path needs
  a `celt_encoder.dll` that the kit doesn't ship. Its
  `export-sounds-to-fsb` builds only the SFX ADPCM bank.
- **R9 / WC-1 (docs only):** Excession documents map packages only.
  There is no documented way for a Workshop mod to override
  `halo1/sound/pc/*.fsb` or `Data/ui/localization/*.bin`. WC outcome B
  or C is likely; this still needs WC-2/3.
- **Recommended strategy, S-A "CELT splice":** our own FSB5 writer
  copies every untouched stream byte-for-byte and inserts CELT 0.11
  encodes only for approved slots. Fallbacks:
  - **S-B**, a PCM16 whole bank;
  - **S-C**, an IMA ADPCM whole bank.

**B2 experiment ladder.** Each step needs approval. In-game steps are
done by the owner, by hand, with a hash-verified backup and restore.

| Step | Acceptance criteria |
|---|---|
| **E0** writer + identity rebuild (offline, no new tools) — ✅ **PASS 2026-10-08** | [x] Re-serialising the Spanish and English bank copies gives **byte-identical** files (0 differing ranges; SHA-256 = pins). [x] Synthetic tests for the writer (offsets, alignment, chunks, name table, size equation): 9 tests, mutation-checked. [x] Deterministic. [x] Re-parse, per-sample metadata and payload hashes identical; mono and stereo covered; vgmstream WAV and `-m` output identical on 7 subsongs per bank. See `b2-audio-research.md` §5.1. |
| **E1** same-length transplant (offline; MCC retail content only) — ✅ **PASS 2026-10-08** | [x] The candidate (`86f787ac…`) puts the English CELT stream of `a10_350_captkeyes` into `es:A10_350_captkeyes#0`. [x] It passes every offline check in report §5 (23/23, `b2-audio-research.md` §5.3): vgmstream decodes all 5,696 subsongs, and only #31 differs (it equals the English decode); untouched streams are byte-identical (5,695 payloads, and every byte outside the target span); names and order are identical; LOOP, flags and the hash field are unchanged; `.lst.bin` is unchanged; the build is deterministic. |
| E1-game (owner) — ✅ **PASS, user-verified 2026-10-08** | [x] Keyes speaks English at `a10_350`, completely, and the neighbouring lines play Spain Spanish, in Classic and Anniversary; the LATAM subtitles are unchanged. [x] No hang, crash, stutter or missing audio. [x] The original bank is restored and its hash `ed0ff3ec…` verified; the snapshot shows no other install file changed; the backup is kept. [x] Recorded as `v-000015`. See `b2-audio-research.md` §5.4. |
| **E1b** different-length transplant — ✅ **offline PASS 2026-10-08** (`b2-audio-research.md` §5.6; candidate `6a861d02…`) | [x] Offline: English `A10_140_CryoTech` (201,728 samples) into Spanish #13 `A10_140_cryotech` (189,440). [x] The 5,682 later samples shift by exactly +9,088 B, 32-aligned. [x] 5,695 payloads identical by index. [x] `data_size` and the file size are +9,088, and nothing else in the header changes. [x] `.lst.bin` is unchanged. [x] vgmstream: all 5,696 subsongs decode, and only #14 differs (it equals English #14). [ ] In game (separate approval): the whole English line plays (about 4.57 s), and the behaviour of the next line (`a10_150`) is noted for B2-R3. The reserve pair is `a10_682_cortana` (+2.07 s). |
| **E2** CELT 0.11 encoder qualification — ✅ **offline PASS 2026-10-08** (`b2-audio-research.md` §5.7; the encoder is vgmstream's bundled `libcelt-0110.dll`, nothing installed) | [x] Encodes are CBR 370 B, 512-sample frames. [x] vgmstream decodes them (`Custom CELT`, frames × 512 samples). [x] The sample count is exact. [x] SNR: re-encoded MCC speech 47.9 dB; sweep/speech-like 46–48 dB; decoder parity with vgmstream is bit-exact. [x] In game: self-encoded candidate `950f93e5…` **FAILED: MCC crashed** (access violation in `halo1.dll`) when the line played (`v-000017`). Cause (evidence, not proven): our default libcelt encode used inter-frame prediction and transients, while every MCC packet is intra-only with no transients (`b2-audio-research.md` §5.8). |
| **E2b** MCC-profile CELT encode (intra-only, complexity 0) — ✅ **offline PASS 2026-10-08** | [x] 0 transients, 387/387 intra (matches 1.69 M original MCC frames). [x] A hard profile guard rejects the E2 bank (negative control). [x] Re-encoded speech 47.8 dB; all 5,696 subsongs decode, and only #31 differs. [x] In game: candidate `f23ddda5…` played English Keyes correctly and naturally, with no crash (**user-verified 2026-10-08**, `v-000018`). |
| **E3** one CE es-MX line (owner-named pairing) — pipeline ✅ offline 2026-10-08 (`b2-audio-research.md` §5.10) | [x] Resample recipe recorded (`work/derived/<sha>/recipe.json`). [x] Pipeline proven on all 194 M01 es-MX lines (41–48 dB). [x] The owner named `es:A10_010_cryotech#0` ← `vo_scr_m01_00460_cryotech#0` (experiment pairing only, not in `manual_mappings.json`). [x] Candidate `fc6f7161…` passes 30/30 offline checks: only slot #0 changes, all 5,696 decode, 45.1 dB, no clipping or truncation, reproducible (§5.11). [ ] In game (separate approval), the LATAM line plays in the slot. |
| **E4** multi-sample (5–10 `a10` slots, owner-approved mappings) | [ ] Includes longer and shorter lines, and at least one `keep_original`. [ ] All checks pass. [ ] An owner playthrough of the `a10` opening confirms that replaced lines play and unmatched lines stay Spain. |
| **E5** batch generator (= M6 audio) | [ ] Built only from approved `audio` objects. [ ] Deterministic, with untouched samples byte-identical. [ ] Drift-gated, with a per-slot report. |

If E2 fails, or no encoder is approved: run E1-style acceptance tests
first for **S-B** (PCM16) and then **S-C** (IMA ADPCM, using a stdlib
encoder of our own). The owner decides whether a transcoded bank is
acceptable.

## 7. Risks (carried forward)

| Risk | Impact | Mitigation |
|---|---|---|
| B1 unresolvable without RE | v1.0 subtitles blocked | R1–R6. If all fail, the owner decides whether to approve deeper research or defer subtitles |
| Language routing differs from the user report (e.g. fallback reads `SP`, or the Saber store renders) | wrong table patched, or the patch is invisible | baseline first (B.12 step 1); patch both tables; test each table alone |
| `SU`/`SP` key sets diverge after an MCC update | a slot is patched in one table only | per-table key lookup; a miss in either table skips the slot and reports it |
| B2 encoder or acceptance fails | v1.0 audio blocked | R7–R9 before any rebuild |
| Duration mismatch (CE es-MX ≠ MCC Spain sample length; cinematics time-locked) | lines cut off or overlap | durations + delta in UI, trims recorded |
| Game patches (CE or MCC) | stale IDs | pins + drift reports; approvals never auto-edited |
| CE content divergence (rewrites, M12–M14 DLC, splits) | unmatched slots | `no_equivalent` + keep Spain audio + custom subtitle |
| Spanish bank has fewer samples than English | slot confusion | slots keyed on Spanish samples (design §4) |
| Local copies of game data (work/, reference-audio/) | accidental commit | `.gitignore`; review `git status` before every commit |
| CE content may not be redistributed (MCC FAQ: retail MCC assets only) | a public v1.0 cannot ship CE audio or text | M8.1 rights memo first; M8.2 alternatives; the `public` build profile refuses CE sources |
| Workshop mods may not be able to override shared FMOD banks or localization tables | the FSB-slot route cannot ship through Workshop | WC before full-campaign production; outcome B or C re-plans early |
| Mods require EAC off, and MCC updates change versions | a player's mod breaks or does not load | Min./Max. Game Version pinned to tested builds; drift reports gate releases |
| Accidental public upload | publication that cannot be undone | no upload without explicit owner approval; tools never change visibility |

## 8. Approvals

Granted by the owner on 2026-10-08, to be executed **sequentially with
review between tasks**: M1, M1b, M2, B1 research R1–R4, extraction of
`HCEEK.7z` (for R5/R6), and B2 research R7–R9.

| Task | Status |
|---|---|
| M1 | ✅ built; awaiting owner review + spot-check |
| M1b (decode M01 es-MX + en media into `work/`) | ✅ built; awaiting owner review + listening |
| M2 (MCC a10 catalog from existing copies) | ✅ done; 5 samples verified (`v-000007`–`v-000011`) |
| M3 (schemas, validators, protected store) — approved 2026-10-08 | ✅ done and approved |
| B1 R1–R4, `HCEEK.7z` extraction | ✅ research done |
| B1 two-table strategy (`SU` + `SP`, one canonical mapping) | ✅ **approved** by the owner 2026-10-08 |
| Check names `subtitle_key_link`, `subtitle_load`; structural vs representative verification, no per-key in-game test | ✅ **approved** by the owner 2026-10-08 |
| B1 PoC step 0 (read-only pre-flight) | ✅ done 2026-10-08: build `19905945`, `SU`/`SP` installed = copies = pins, keys found once per table |
| B1 PoC step 1 (baseline, owner in game) | ✅ done 2026-10-08: `SU` text + Spain audio, Classic and Anniversary (`v-000012`–`v-000014`) |
| B1 PoC step 2 (offline one-entry candidates) | ✅ done 2026-10-08: `SU`/`SP` candidates 16/16 checks, deterministic; install/rollback prepared |
| B1 PoC step 3 (in-game, owner by hand) | ✅ done: "custom subtitles work" (user-reported). Table/text/modes not reported; `SU` backup present, no `SP` backup; originals restored and verified. `subtitle_load` entry (next free ID) pending owner details |
| `manual-mappings` key-verification change (B.11.2) | planned; needs approval |
| B2 R7–R9 | ✅ research done 2026-10-08 (`b2-audio-research.md`); WC-1 docs part answered (no documented FSB/loc override) |
| B2 E0 (writer + identity rebuild, offline) | ✅ approved and done 2026-10-08: both banks byte-identical (`scripts/common/fsb5_writer.py`, `b2_e0_identity_rebuild.py`) |
| B2 E1 offline | ✅ approved and done 2026-10-08: candidate `86f787ac…`, 23/23 checks; owner sheet `work/b2/e1/e1_install_rollback.md` prepared |
| B2 E1-game | ✅ approved and done 2026-10-08: **user-verified pass** in Classic and Anniversary; restored and verified; `v-000015` |
| B2 E1b offline | ✅ done 2026-10-08 (25/25) |
| B2 E2 | offline ✅; **E2-game ❌ FAILED 2026-10-08** (crash in `halo1.dll`; `v-000017`); bank restored and verified |
| B2 E1b-game | ✅ **user-verified pass** 2026-10-08 (`v-000016`): the longer line plays fully, with no overlap |
| B2 E2b (MCC-profile encoder) | offline ✅; **E2b-game ✅ user-verified pass 2026-10-08** (`v-000018`); bank restored and verified. **B2 technically unblocked** |
| B2 E3 offline | ✅ done 2026-10-08: candidate `fc6f7161…` (30/30); **E3-game not approved** (`b2_bank_install.py --exp e3`) |
| B2 E4–E5 | not approved |
| WC (Workshop compatibility checkpoint, inside B2) | WC-1 (docs) ✅ done 2026-10-08 (`workshop-research.md`): no documented override of FSB/loc files; WC-2 (inspect one subscribed CE mod) needs approval |
| M4 matching UI | design done 2026-10-08 (`m4-matching-ui-design.md`); implementation not started |
| M8 (Steam Workshop packaging and publishing), each sub-step M8.1–M8.7 | planned; not approved |
| Any upload (private test or public) | **not approved**; public publishing needs explicit owner approval |

**Priority (owner, 2026-10-08):** B1 is still the immediate priority. WC
and M8 do not start until the owner names them.
