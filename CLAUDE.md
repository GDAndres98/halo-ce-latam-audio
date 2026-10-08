# Halo CE LATAM Audio — Project Guide

## Goal

A **personal, local-only** (no distribution) Latin American Spanish
localization of *Halo: Combat Evolved* inside *Halo: The Master Chief
Collection* (MCC). The source is *Halo: Campaign Evolved* (2026, UE5),
which ships a full `Spanish(Mexico)` dub and `es-MX` subtitles. The plan
and milestones are in [`docs/roadmap.md`](docs/roadmap.md); the schemas
are in [`docs/dialogue-catalog-design.md`](docs/dialogue-catalog-design.md) (v2).

- **v1.0 (required):**
  - Replace MCC Halo CE's Spanish (Spain) dialogue with CE es-MX
    recordings.
  - Replace the Spanish subtitles with CE es-MX text or the user's
    custom text.
  - Audio and subtitle choices are **independent** per line.
  - Matching is **manual only**.
  - Approved mappings are **never overwritten**.
  - Unmatched lines and custom subtitles are supported. Unmatched lines
    keep Spain audio by default.
- **v1.1 (potential):** non-destructive radio-effect repair. Preserve
  originals and recipe metadata. **Do not implement effects yet.**
- **v1.0 blockers:**
  - **B1:** MCC subtitle replacement is unresolved.
  - **B2:** FSB5 rebuild and game acceptance are unverified.

  Research options are in roadmap §6. Neither may be attempted with
  binary edits or repacking without explicit approval.

## Local environment (see `.env`, not committed)

- `HALO_MCC_FOLDER` — retail MCC install (contains `halo1/`, the classic
  Halo CE/Blam-engine runtime: maps, FMOD sound banks, tags baked into
  `.map` cache files).
- `HALO_REMAKE_FOLDER` — *Halo: Campaign Evolved* install (UE5, codename
  "Meteorite"; Wwise audio middleware; all content packed into UE5 IoStore
  containers, `.pak`/`.ucas`/`.utoc`).
- `HALO_MOD_KIT_FOLDER` — HCEEK, the **official** Halo CE Editing Kit for
  MCC (`guerilla.exe`, `sapien.exe`, `tool.exe`). Ships as a `.7z` plus a
  partially-extracted root; the full `tags/`/`data/` tree is not extracted
  yet (see `docs/feasibility.md`).

## Hard rules (do not violate)

1. **Never modify installed game files.** Everything under the three
   `.env` folders is read-only material for this project.
2. **Do not bypass encryption or DRM.** If a container (e.g. a UE5
   `.ucas`/`.pak` pair) turns out to be encrypted, stop and report it —
   do not search for or apply AES keys.
3. **Keep game assets outside Git.** No `.map`, `.pak`, `.ucas`, `.utoc`,
   `.fsb`, `.wav`, `.ogg`, `.bnk`, `.wem`, or extracted archive ever gets
   committed (enforced in `.gitignore`). The repo holds scripts, docs, and
   small text manifests only — never audio or binary game data, including
   original or dubbed voice lines.
4. **Cite sources** for technical claims (official docs, community tool
   docs, EULA/FAQ text) — see `docs/feasibility.md` for the citation list.
5. **Ask before installing or running additional tools** (e.g. Reclaimer,
   FModel, python-fsb5/vgmstream, or extracting `HCEEK.7z`). Approved so
   far: vgmstream r2117 (`D:\Tools\vgmstream-r2117\`), and read-only,
   decompress-only use of FModel's bundled `oodle-data-shared.dll`.
   `HCEEK.7z` is still **not** extracted.
6. **No speculative extraction.** Don't write pipeline/import code before
   a human has reviewed the feasibility findings and approved a specific
   next step.

## Key facts established so far

- MCC's official localization for **Spanish (Latin America) is
  interface-only — there is no LATAM audio dub today**, only Spanish
  (Spain) has full voice + subtitles. This is the gap the mod addresses.
  (Halo Support: "Which Languages Can I Play Halo: The Master Chief
  Collection In?")
- The official HEK's public tag set (`bin\!public_tags.txt` in HCEEK)
  contains **zero** campaign dialogue (`sound\dialog`) tags for any
  singleplayer level, including `a10` (*The Pillar of Autumn*). Campaign
  VO is not shipped as moddable source in the kit — only compiled into
  the retail `.map` cache files.
- 343 Industries' MCC modding FAQ: *"Only the assets contained within the
  retail version of MCC are allowed for use in modding efforts"* — this
  reads as prohibiting reuse of *Halo: Campaign Evolved* (a different,
  2026 game) assets inside an MCC mod. Treat cross-game asset reuse as
  blocked pending clarification.
- **Campaign dialogue IS addressable, just not via HEK.** MCC's own
  `halo1/sound/pc/lst/sounds_dialogs*.lst.bin` files are a plain,
  parseable index of 1,903 stable tag names (e.g.
  `sound\dialog\a10\a10_350_captkeyes`), **identical across all 8
  shipped languages**, each paired with a per-language `.fsb` sample
  bank. This is a separate, lighter-weight target than rebuilding HEK
  tags — see `docs/feasibility.md` §10 for the recommended strategy:
  **replace the audio inside the existing Spanish (Spain) slot**, since
  it's the only non-English language with a complete, already-wired
  dialogue pipeline. Hard limit: a data-only mod cannot add a *new*
  selectable "Spanish (Latin America)" menu entry — only replace what
  plays when "Spanish" is selected.
- **Stage 1 (§11 in feasibility.md) is done, no tools installed.**
  `sound\dialog\a10\a10_350_captkeyes` is a verified, concrete worked
  example: index 30 in *both* `sounds_dialogs.fsb` (English) and
  `sounds_dialogs_spanish.fsb` (Spanish), confirmed via each bank's own
  embedded FSB5 name table (not inferred from `.lst.bin` position).
  Codec is **CELT** (mode 12) — this rules out python-fsb5 for decoding;
  **vgmstream** is the identified tool that can decode it (confirmed
  CELT/FSB5 support in its own docs). Working copies + hashes live in
  the git-ignored `reference-audio/stage1/`.
- **Stage 2A done (feasibility.md §14).** vgmstream r2117 is installed
  standalone at `D:\Tools\vgmstream-r2117\` (official GitHub release,
  hash-verified, outside Steam and outside this repo — not something
  future sessions need to reinstall, just point `scripts/extraction/
  extract_dialogue_samples.py --vgmstream-cli` at it). 5 scripted `a10`
  lines were decoded from both language copies (10 WAVs, all duration-
  matched); see `reference-audio/stage1/wav/` and
  `stage2a_report.csv` (both git-ignored). **Nobody has listened yet** —
  don't claim spoken content is confirmed until the user says so.

- **Phase 2 discovery done (2026-10-08)** — see
  `docs/remake-audio-research.md`, `docs/subtitle-research.md`,
  `docs/dialogue-catalog-design.md`. Headlines:
  - CE containers are **not encrypted** (all `.utoc` Encrypted flags
    unset, all `.pak` indexes unencrypted, zero key GUIDs). Paks are
    **Oodle**-compressed; `.locres`/package contents need FModel (or an
    approved Oodle reader) to read.
  - CE ships a full **`Spanish(Mexico)`** Wwise voice track in
    `pakchunk4-Windows.pak` (es-ES = chunk 3, en-US = chunk 2). Media IDs
    are per-language (zero overlap); bank IDs = FNV-1 of lowercased name.
  - CE subtitles: UE localization target `Subtitles`,
    `Localization/Subtitles/es-MX/Subtitles.locres` (separate from es-ES).
    Line→subtitle-key link **verified (Phase 2B)**, see below.
  - CE line key e.g. `VO_SCR_M01_00460_CryoTech` is shared (case-
    insensitively) by UE audio asset, `Play_` AkAudioEvent, LipSync and
    `Tags/sound/...-sound`. CE numbering is unrelated to MCC's
    `a10_NNN` — matching is manual only.
  - MCC Halo CE subtitles: `Data/ui/localization/<LANG>_Halo1.bin`
    (`SP_` = Spain). Keys are 32-bit hashes of an unknown string; EN/SP
    share 3,399 keys; key→string alignment and tag→subtitle link are
    **unresolved**.
  - User's tools: FModel portable at
    `%USERPROFILE%\Downloads\858461d19e29803479555059acb59a03a0986de8\`
    (exports under `Output\Exports`, audio only, no JSON yet; `.usmap`
    not loaded in FModel per its log). UE4SS v3.0.1 is installed by the
    user inside the CE install (`Binaries\Win64\ue4ss\`, `Paks\LogicMods\`)
    — treat as read-only; its only dump is the `.usmap`.

- **Phase 2B PoC done and MANUALLY VERIFIED (2026-10-08)** —
  `docs/poc-ce-line-link.md`. The user listened to the en / es-MX / es-ES
  recordings of `VO_SCR_M01_00460_CryoTech` and confirmed they match
  their subtitles (future `verifications.json` entry `v-000001`).
  Approved decisions: read-only use of FModel's bundled
  `Output\.data\oodle-data-shared.dll` (decompress only); `.usmap` path
  comes from `.env` **`USMAP_FILEC`** (exact name); personal, local-only
  project, **no distribution**.
  - Explicit CE chain: `Audio/scripted/.../<LINE>` (`HaloAudioVoiceVariations`)
    → `VoiceEvents[i].VoiceEvent` (import) → `Play_<LINE>` AkAudioEvent →
    `EventCookedData.EventLanguageMap["Spanish(Mexico)"].Media[].MediaId`
    → `Media/Spanish(Mexico)/NN/<id>.wem` in pakchunk4; and
    `VoiceEvents[i].Transcription{StringTable, LineKey}` → StringTable
    `TableNamespace` → `Subtitles/es-MX/Subtitles.locres[ns][LineKey]`.
  - Run it: `python scripts/discovery/link_ce_line.py --voice-asset
    Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech
    --vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe`
    (output in `work/ce/`). Tests: `python -m unittest discover -s tests`.
  - MCC `SP_Halo1.bin`: structure partly decoded
    (`scripts/common/mcc_loc.py`), but key↔string and tag↔subtitle are
    **unresolved**; investigation **stopped** at the "undocumented
    reverse engineering" line. Don't resume without approval.
  - Script layout: `scripts/common/` (parsers), `scripts/catalog/`
    (catalog builders), `scripts/discovery/`
    (inspectors/PoC), `scripts/extraction/` (FSB decode). All outputs go
    to git-ignored `work/`.

## Catalog / mapping rules (from the Phase 2 design)

- Two separate catalogs (CE, MCC) under git-ignored `work/`; cross-game
  links exist **only** in the user-owned `mappings/manual_mappings.json`.
- Never auto-match, rank, or pre-fill CE↔MCC pairs.
- Every in-catalog association records evidence: `explicit`,
  `derived:<rule>`, or `unresolved`. Never invent one.
- Tools never create or modify `approved` mapping entries. `audio` and
  `subtitle` are approved separately, and each is immutable to tools
  once approved. Drift goes to `work/reports/`, never into the manifest.
- The MCC replacement unit is the **Spanish FSB sample slot**
  (`slot_id = "es:" + name_in_spanish_bank`), not the tag and not the
  English sample. The Spanish bank has fewer samples (5,696 vs 6,093).
- Human checks are recorded in `mappings/verifications.json`
  (append-only). They are not an evidence level.
- Derived audio (resample to 44.1 kHz, trims, v1.1 FX) is always a new
  file under `work/derived/<sha256>/` with a `recipe.json`. Originals
  are never edited.
- **Approvals (owner, 2026-10-08):** M1, M1b, M2, B1 R1–R4, `HCEEK.7z`
  extraction, B2 R7–R9. These run **sequentially, with owner review
  between tasks**. Start only the task the owner names.
- **M1 done (2026-10-08), awaiting owner review:**
  `python scripts/catalog/build_ce_catalog.py --mission M01` writes
  `work/ce/catalog/m01.jsonl` (`ce-voice-asset/3`, deterministic),
  `work/ce/build.json` and `work/ce/reports/m01_*`. It produces 220
  records and 0 skipped. Findings are in remake-audio-research.md §9.
  `ce_line_ref` is now `<record_id>#<n>` (design §3.1).
- Not started: M1b, M2, B1, B2. Matching UI, audio processing, FSB
  repacking and subtitle patching are still not approved.
- ⚠ The user's goal uses CE es-MX audio/subtitles as the source. That
  conflicts with 343i's MCC asset FAQ (feasibility §7). The user has
  decided this is a personal, local-only project with no distribution.
  Never commit or redistribute CE content.

Full findings, open questions, and the proposed next experiment are in
[`docs/feasibility.md`](docs/feasibility.md) and the Phase 2 docs above.
