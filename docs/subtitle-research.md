# Subtitle Research: Campaign Evolved (es-MX) and MCC Halo CE

**Date:** 2026-10-08. Read-only discovery. Evidence labels as in
[`remake-audio-research.md`](remake-audio-research.md): VERIFIED / DERIVED
/ HYPOTHESIS / UNKNOWN. No subtitle text is reproduced in this repo
beyond speaker labels and counts. Subtitle text is game data and stays
in git-ignored local folders only.

---

## Part A — Halo: Campaign Evolved

### A.1 Storage: a dedicated `Subtitles` localization target — VERIFIED

UE compiles each localization target into one binary `.locres` per
culture plus a `.locmeta` describing the target. [^ue-loc] Campaign
Evolved has two game targets (from `pakchunk0-Windows.pak`'s index):

| Target | Files | Purpose |
|---|---|---|
| `Game` | `Localization/Game/<culture>/Game.locres` (14 cultures) | UI/general text |
| **`Subtitles`** | `Localization/Subtitles/<culture>/Subtitles.locres` (14 cultures) | **Dialogue subtitles** |

`Subtitles.locmeta` is stored uncompressed and was read directly. It
declares **native culture `en`** and compiled cultures including
**`es-ES` and `es-MX` as distinct cultures** (also da-DK, de-DE, fi-FI,
fr-FR, it-IT, ja-JP, ko-KR, nb-NO, pl-PL, pt-BR, pt-PT, ru-RU, zh-CN,
zh-TW). `.locres` files actually present in the pak: de-DE, en, es-ES,
**es-MX**, fr-FR, it-IT, ja-JP, ko-KR, pl-PL, pt-BR, ru-RU, zh-CN, zh-TW.

| File | Uncompressed size |
|---|---|
| `Subtitles/en/Subtitles.locres` | 172,433 B |
| `Subtitles/es-ES/Subtitles.locres` | 251,214 B |
| `Subtitles/es-MX/Subtitles.locres` | 259,726 B |

These are **Oodle-compressed** in the pak, so their contents (keys/text)
have **not** been read yet.

**LATAM conclusion:** Campaign Evolved stores LATAM Spanish subtitles as
the `es-MX` culture of the `Subtitles` localization target. That target
is separate from Spain Spanish and from UI text, and it pairs with the
`Spanish(Mexico)` Wwise voice language.

### A.2 `.locres` structure (public format) — background

A `.locres` maps **(namespace, key) → localized string**, with a string
table de-duplicating text. Keys are the stable identifiers. The hashes
inside the file are lookup accelerators over namespace/key, not IDs a
catalog should rely on. [^locres] The text for a culture is selected at
runtime by the active culture. The game decides which namespace/key a
line uses.

### A.3-update (2026-10-08) — VERIFIED for one line

Candidate 1 below is confirmed. `Subtitles.locres` is version 3 with 29
namespaces: en 1,465 entries, es-MX 1,456, es-ES 1,458. Each namespace
is a mission/family string table (`VO_SCR_M01PILLAROFAUTUMN`,
`VO_CIN_M06GUILTYSPARK`, …) and keys are line keys. The voice asset
carries `HaloAudioTranscriptionLine{Type=Subtitle, StringTable=<import>,
LineKey, MetaData{Character, Race}}`. The StringTable asset's
`TableNamespace` equals the `.locres` namespace (101 keys in the M01
scripted table, and 101 in that namespace for en / es-MX / es-ES). Full
chain: [`poc-ce-line-link.md`](poc-ce-line-link.md). Small per-culture
entry-count differences (1,465 vs 1,456 vs 1,458) mean some keys lack a
translation in some cultures. A catalog must record that per line as
`unresolved`, not fall back silently.

### A.3 The line → subtitle-key link — original hypothesis (kept for history)

Three candidate carriers. Only the first is backed by direct evidence:

1. **`Audio/Transcription/Subtitles/<family>/VO_*` (28 assets)**: one per
   mission per family (`scripted/VO_SCR_M01PILLAROFAUTUMN`,
   `cinematic/VO_CIN_M01PILLAROFAUTUMN`, …, M12–M14) plus some systemic
   characters (`Systemic/VO_SYS_Mendoza`, `VO_SYS_GuiltySpark`). Their
   names mirror the VO folder names exactly, and their path says
   "Transcription/Subtitles". Most likely a **StringTable** or
   **DataTable** keyed by line name whose text is gathered into the
   `Subtitles` target. **Class and row schema UNKNOWN** until exported.
2. The per-line `Audio/scripted/…/<LINE>` asset may hold an `FText`
   property (namespace + key) or a reference to a row in (1).
3. The `Tags/sound/…-sound` Blam tag may carry a subtitle string ID.

Until one of these is read, **no audio↔subtitle association is
asserted.** Matching by "the key looks like the line name" counts as
DERIVED evidence at best, and the catalog must label it that way
(see design doc §3.3).

### A.4 Rendering side — VERIFIED (names only)

`ui/Subtitles/BP_MeteoriteGenericSubtitle`,
`ui/Hud/cinematic/WBP_CinematicSubtitles`, `DT_DialogueSubtitleColors`,
`DT_SubtitleColors`. Speaker colouring is data-driven. Not needed for
the catalog.

---

## Part B — MCC (Halo CE inside MCC)

### B.1 Where Halo CE subtitles live — VERIFIED

Not in the `.map` files: `a10.map` contains no "subtitle" string, though
it does contain `sound\dialog\a10\a10_350_captkeyes` and the FSB sample
name. Not in the FSB banks. Not in the TTML files:
`halo1/terminals/*.xml` are TTML, but only for the Anniversary terminal
videos.

They live in the **MCC shell's per-language, per-game string tables**:

```
HALO_MCC_FOLDER\Data\ui\localization\<LANG>_Halo1.bin
```

Language prefixes present for Halo1: `CS CT DE EN FR IT JP KO PB PR SP SU`.
~~`SP_Halo1.bin` is the Spanish table. No separate LATAM (`es-MX`) table
exists for Halo 1.~~ **Superseded by B.5 (2026-10-08):** `SP_Halo1.bin`
is **Spain** Spanish, and **`SU_Halo1.bin` is Latin American Spanish**.
MCC already ships LATAM subtitles for Halo CE; its LATAM support is
text-only, not audio. (Prefixes like `DA DU FI NO PO RU` exist for
`Global`/other titles only.)

### B.2 Format — PARTLY VERIFIED

```
0x00  u32 magic 0x90CE6B7A, u32 size, u32 size, … (0x40-byte block)
0x40  u32 magic 0x90CE6B7A, char[] "EN_Halo1" (padded)
0x68  u32 payload size        0x70  u32 = 8 (meaning UNKNOWN)
0x78  u32 hashTableBytes      (EN 13,604 = 3,401 entries; SP 13,600 = 3,400)
0x7C  u32 keyHash[n]          strictly ascending 32-bit hashes
…     UTF-8 string data, NUL-terminated
```

- Dialogue strings use the shape `<abbr>&id<SPEAKER>` + **U+E900** +
  `<text>` in the English table, e.g. speaker labels `cor&idCORTANA`
  (457), `mar&idMARINE` (269), `343&id343 GUILTY SPARK` (210),
  `key&idKEYES` (111). 1,306 English strings carry a speaker label.
  The table also holds Halo 1 UI strings.
- **EN and SP share 3,399 of their key hashes** (EN-only 2, SP-only 1).
  So MCC's own EN↔ES subtitle alignment is by **identical key hash**.
  VERIFIED.
- The Spanish table contains **no `&id` speaker markers** at all, so
  speaker labels are handled differently there. UNKNOWN.

**Unresolved:**

1. **Key → string alignment.** The string area splits into 3,939
   NUL-separated segments (3,350 non-empty) for 3,401 keys. So it is
   *not* simply "string *i* belongs to hash *i*". There must be an
   offset/length encoding not yet identified. **Until solved, no MCC
   subtitle text is attached to a key in any catalog.**
2. **What the keys hash.** None of crc32, FNV-1, FNV-1a, djb2, sdbm or
   murmur3 over 27 variants of the 1,903 `sound\dialog\…` tag names
   (full path, basename, case, UTF-16, `.sound`, permutation suffix…)
   hits any key. **There is currently no explicit link between an MCC
   dialogue tag and its MCC subtitle.** The link is presumably inside
   `halo1.dll` or the map's scenario/script data. We will not
   reverse-engineer the executable.
3. Web search found **no public documentation** of this format. [^mccbin]

> **B.2 is superseded by B.4–B.6 (B1 research, 2026-10-08).** Unresolved
> items 1 (key → string) and 2 (what the keys hash) are both solved. The
> "3,401 entries" count above was right, and the B.2-update's "+1" key
> count below was wrong.

### B.2-update (2026-10-08) — investigation on copies, then stopped (superseded, kept for history)

Copies in `work/mcc/loc/` (SHA-256 EN `f88785ab…7cb61`, SP
`794deac3…42dda`, identical to the installed files).
`scripts/discovery/inspect_mcc_subtitles.py` reproduces everything
below.

- **Key table (INFERRED, consistent):** the u32 at `0x78` is the byte
  offset of the *last* key relative to `0x7C`, so EN has **3,402** keys
  and SP **3,401** (strictly ascending, ending at `0xFFEEB88E` in both).
  EN/SP share **3,400** keys (EN-only 2, SP-only 1).
- **Encoding (VERIFIED):** the string pool is UTF-8, NUL-terminated,
  with `\t`/`\n` allowed inside strings. EN dialogue uses
  `<abbr>&id<SPEAKER>` + U+E900 + text (1,306 strings). **SP has no
  speaker labels at all.** The EN pool also contains some non-English
  UI strings (Italian, Spanish, Japanese), so it isn't a pure
  English table.
- **Key ↔ string (UNRESOLVED):** EN has 3,938 segments (588 empty) and
  SP 3,940 (602 empty) against 3,402/3,401 keys, and there is no offset
  table. Comparing format tokens (`{STRING}`, `>>`, digits) by position
  between EN and SP agrees only in the first ~400 segments, then drifts
  to 0%. So **pool order is not key order**, and strings are not
  paired across languages by position either.
- **Tag ↔ subtitle (UNRESOLVED):** crc32 / FNV-1 / FNV-1a over 13,732
  variants of the 1,903 `sound\dialog\…` names (plus earlier djb2 /
  sdbm / murmur3 runs) give 0 hits. Key values appear only 6 times as
  aligned u32s in all of `a10.map` (~27 M words) and never in
  `sounds_dialogs.lst.bin` / `cine_preload.ps`. That's no evidence of
  a reference table.
- **Stopped here** per project rule: the next step would be undocumented
  reverse engineering of how `halo1.dll`/the MCC shell indexes this
  pool. No file was modified or repacked.

### B.3 Consequence for the mod (original; see B.9–B.12 for the current view)

- **Audio side** of MCC is well understood (FSB5 name table,
  `feasibility.md` §11–14).
- **Subtitle side** of MCC is located but **not yet linkable** to audio
  tags. The MCC catalog therefore carries subtitles as a separate,
  key-hash-indexed table. A subtitle is attached to an audio tag only
  through a **manual** decision in the mapping manifest, the same way
  CE lines are attached. The UI can show the user both texts side by
  side so that decision is quick.
- **Writing** a modified `SP_Halo1.bin` requires solving B.2(1) and the
  MCC-side modding rules. That's out of scope until approved.

---

## Part B (B1 research, 2026-10-08) — format solved, loading still unverified

Scope: research only, under the owner's approval of B1 options R1–R4,
`HCEEK.7z` extraction, and research items 1–10.
- No localization, pack or game file was modified or repacked.
- Nothing was disassembled, and no process memory was read.
- Nothing was installed. The built-in Windows `tar` (libarchive) read
  `HCEEK.7z`, and Python stdlib `zlib` read the `.s3dpak`.
- All analysis ran on hash-verified copies in git-ignored
  `work/mcc/loc/copies/`, `work/mcc/s3dpak/` and `work/hceek/`.
- No subtitle text is reproduced here.
- **No subtitle was linked to an audio slot in any catalog or mapping.**

Reproduce with `python scripts/discovery/b1_subtitle_research.py`
(about 1 s, statistics only). It writes
`work/mcc/reports/b1_findings.json`.

### B.4 `<LANG>_<Game>.bin` format — VERIFIED

```
0x00 u32 magic 0x90CE6B7A     0x04 u32 file_size-16    0x08 u32 file_size-16
0x28 u32 CRC-32/MPEG-2(UPPER(table name)), e.g. "SP_HALO1"
0x40 u32 magic 0x90CE6B7A     0x44 char[36] table name
0x68 u32 8 + 4n + L           0x70 u32 8 (meaning unknown, constant)
0x78 u32 4n  (key-table bytes)            0x7C u32 L (string-data bytes)
0x80 u32 key[n]               strictly ascending (Halo1, DBG, Debug tables)
...  n NUL-terminated UTF-8 strings, string i belongs to key i
...  zero filler (a run of NULs inside L, plus padding after it)
```

**Evidence:**
- **Byte-exact rebuild:** all 20 Halo1/DBG/Debug tables rebuild
  byte-identically in memory from (header, keys, strings, filler).
  Nothing was written.
- **Header fields:** the `0x04/0x08/0x28/0x68` relationships hold for
  all 25 tables copied, including `*_Global`.
- **Correction:** the u32 at `0x7C` is the string-data length, **not a
  key**. The earlier parser read it as key 0, which shifted every
  pairing by one. That is why strings and keys "drifted" in B.2-update.
  The surplus "segments" were the zero filler: in every table, the
  surplus equals the trailing NUL run exactly.
- **key i ↔ string i, Global (VERIFIED):** `DBG_LBL_Global` (labels) and
  `DBG_BLNK_Global` (`DBG-BLK::<label>`) are independent files. For
  their 9,098 shared keys, 9,059 label pairs agree by key; the other
  39 are display aliases, e.g. `DUEL` / `GT_SLAYER_DUEL`. Shifting one
  table by a single position gives **0** agreements.
- **key i ↔ string i, Halo1 (VERIFIED):** across EN vs each of 11 other
  languages, format placeholders agree for 100–101 of 101 keyed
  strings, against 0 when shifted. Empty-value agreement is
  0.991–0.997.
- `*_Global` tables share the header, but their keys are not sorted and
  they have extra trailing entries. They are only partly understood
  and not needed for Halo 1 subtitles.
- `scripts/common/mcc_loc.py` now implements this model, read-only,
  with synthetic tests in `tests/test_parsers.py`.

### B.5 Language prefixes — VERIFIED for Spanish

| Prefix | Language (MCC name) | Evidence |
|---|---|---|
| `SP` | **Spain Spanish** (`Iberian-Spanish`; Saber `spanish`) | `SP_Halo1` == Saber `strings_spanish` for **123/123** `a10` rows (vs 59/123 for `SU`); 76 Spain-only markers (vosotros forms, *vale*) vs 1 LATAM in dialogue |
| `SU` | **Latin American Spanish** (`Spanish`; Saber `latam_spanish`) | `SU_Halo1` == Saber `strings_latam_spanish` for **123/123** `a10` rows (vs 59/123 for `SP`); 12 Spain vs 4 LATAM markers |
| `PR` / `PB` | Portuguese (Portugal) / Brazilian Portuguese | script statistics (ã/õ/ç), same base+variant pattern |

- The Saber entries are named explicitly by the game data (`strings_spanish`,
  `strings_latam_spanish`), so the mapping no longer rests on dialect
  statistics alone.
- `SP` and `SU` share 3,400 keys. 637 of the 1,306 dialogue strings
  differ between them.
- `halo1/game.cfg` (plain text) declares
  `latam_spanish = …strings_latam_spanish.str` and
  `AudioTrack_latam_spanish = 00`, the same as `AudioTrack_english = 00`,
  while `AudioTrack_spanish = 04`. That is consistent with MCC's
  "LATAM = text only" support. Whether the classic engine plays the
  English or the Spain FSB under LATAM is **UNKNOWN** (needs R4).
  **Update (2026-10-08):** the owner reports that with primary
  language Spanish (Latin America) and fallback Spanish (Spain), the
  game shows LATAM subtitles and plays Spain audio. **Owner-verified
  in the B.12 baseline** (three lines, both graphics modes;
  `v-000012`–`v-000014`); see B.11.1. The engine mechanism (fallback vs
  `AudioTrack` value) is still not known, and isn't needed.
- The override XML and `Data/ui/config/fontdefinition.xml` list
  `Spanish` and `Iberian-Spanish` as distinct languages. The XML's
  `Iberian-Spanish` values match `SP_Global` best (93 vs 89), and
  `Spanish` matches `SU_Global` best (89 vs 85). That corroborates the
  mapping, weakly.

### B.6 Key hashing and the tag → subtitle link

- **Key = CRC-32/MPEG-2(UPPER(label), UTF-8)** (poly `0x04C11DB7`, init
  `0xFFFFFFFF`, unreflected, no final XOR; check value `0x0376E6E7`).
  **VERIFIED:** 9,098/9,098 `DBG_BLNK` original-case labels hash to
  their own key, and 20,000 random labels hit 0 keys. MCCLocalizationEditor
  states the same ("CRC32MPEG hashes"). [^mccloc] Earlier attempts
  failed because they used zlib's *reflected* CRC-32.
- **Halo 1 dialogue label = the dialogue tag path, as in `.lst.bin`**
  (e.g. `sound\dialog\a10\a10_350_captkeyes`).
  - Of the 1,903 `sounds_dialogs` tags, 949 hash to an `EN_Halo1` key,
    948 of them dialogue keys. About 0.0015 such hits would be expected
    by chance.
  - **`a10`: 101/101 tags have a key**, with non-empty `SP` and `SU`
    text for all 101.
  - Every level's scripted folder is covered: a30 132/132, b30 76/77,
    c10 22/23, and every other level folder fully. Generic barks have
    no subtitles.
  - The Saber `strings_*` files use the *same plaintext tag paths* as
    keys (escaped `\\`), and their text is identical to the `.bin`
    entries.
- **Evidence level:** the hash rule is VERIFIED. Its application to a
  tag is `derived:mcc_loc_key_crc32_tag_path`: an exact hash match, not
  a reference field read from a tag. Per the owner rule ("keep MCC
  subtitle links unresolved unless verified"), **catalog `subtitle`
  fields stay `unresolved`**. The rule is a candidate for a new
  evidence value once the owner confirms one line in game (B.12
  step 1), per table.
- 358 dialogue keys are not explained by any `.lst.bin` path, most
  likely generic barks (permutation-level). HUD messages (`a10`
  `hud_message_text` names) hash to none of the six path forms tried.
  Neither affects `a10` dialogue.

### B.7 Two subtitle stores (Halo CE in MCC)

| Store | Location | Keyed by | Languages | Editable how |
|---|---|---|---|---|
| MCC shell tables | `Data/ui/localization/<LANG>_Halo1.bin` | CRC of tag path | 12, incl. `SP` (Spain) and `SU` (LATAM) | binary rewrite (format fully known, B.4) |
| Saber/CEA strings | `halo1/prebuild/paks/initial_textures.s3dpak` → `strings_<lang>` (UTF-16, `path<TAB×4>"text"`) | plaintext tag path | 10 incl. `spanish`, `latam_spanish` (English not in this pack) | edit text, re-zlib, repack the `.s3dpak` (community "SuP"; not installed) |

- `.s3dpak` layout seen: `u32 count`, `count × u32` chunk offsets, and
  chunks of `u32 128 KiB size + zlib`. The directory entries are
  `{u32 off, u32 size, u32 name_len, name, u32 type=0x0e, u32 0, u32 0}`.
- The Open Carnage CEA subtitle tutorial edits this store and says only
  dialogue under `sound\dialog\` played by script or AI conversations is
  subtitled. [^ocsub]
- **Which store renders the subtitle** (classic vs Anniversary graphics,
  pause/replay screens) is **UNKNOWN**. Their content is identical, so
  observing unmodified play can't tell them apart (B.12).

### B.8 Official and community support, and how MCC loads changes

- **Official:**
  - The MCC modding docs (Excession, `ModInfo.json`) cover map/campaign
    packages, metadata (`Title: {"Neutral": …}`) and
    `GameModContents{HasSharedFiles, HasCampaign, …}`. **Nothing**
    covers localization tables, subtitles or overriding `Data/ui` files.
    [^excession][^modinfo]
  - The HCEEK (`HCEEK.7z`, listed with built-in `tar`; 14,294 entries)
    has no localization documentation; its `readme.txt` is an asset
    history index.
  - The kit's `a10_350_captkeyes.sound` tag holds only the permutation
    name and Vorbis source audio, **with no subtitle or string field**
    (R6 answered for sound tags).
  - Correction to feasibility §4.2: the archive *does* contain 1,920
    `tags/sound/dialog/…` tags, including `a10`. That note only
    concerned the unextracted root's `!public_tags.txt`. It is relevant
    to B2 and was not pursued.
- **Shipped override layer:** `Data/ui/localization/localized_string_overrides.xml`
  is plaintext `<language name=…><entry key=LABEL value=TEXT/>`, with 15
  languages and about 121 entries each. 120–121 of each language's
  keys hash, under the B.6 rule, to `Global` table keys. **It contains
  no Halo1 keys**, and whether MCC applies it to `*_Halo1` tables is
  **UNKNOWN**.
- **Community tools (researched, none installed):**
  - **MCCLocalizationEditor** (Lord-Zedd) opens and saves these
    `.bin` files and edits via XML. Its README says: games reference
    keys as `$KEY` and show the key when it's missing; a wrong filename
    hash makes the game **hang**; and "any changes you make will flag
    the anticheat". It is deployed by placing the edited `.bin` back
    in `data\ui\localization\`. [^mccloc]
  - **SuP** for Saber packs (via the Open Carnage tutorial). [^ocsub]
  - Nexus "Improved Subtitles" ships edited CE subtitles. Its page
    blocks automated fetches (HTTP 403), so its method is unconfirmed.
    [^impsub]
- **Loading conclusion:** the only documented path is to **replace the
  installed file, with EAC off**. No mod-folder override of
  `Data/ui/localization` is documented. Integrity checks beyond EAC
  are unknown, apart from the filename-hash hang.

### B.9 Editing / loading strategy comparison

| # | Strategy | Touches | Meets v1.0 (CE es-MX or custom text)? | Risk | Unknowns |
|---|---|---|---|---|---|
| S0 | **Select MCC's Latin American Spanish** (`SU` text) | nothing | No: it is MCC's own LATAM translation of the 2001 script, not CE es-MX or custom text. It is a zero-risk baseline | none | which FSB plays under LATAM (English per `game.cfg` AudioTrack, or Spain) |
| S1 | **Rewrite `SP_Halo1.bin` (or `SU_Halo1.bin`)** with replaced strings | 1 file in `Data/ui/localization` | **Yes** (any text per key) | EAC flag (offline/EAC-off only); hang if the name hash is wrong; overwritten by MCC updates | whether it alone drives the in-game subtitle (vs the Saber store); max string length/escapes |
| S2 | Add Halo1-key entries to `localized_string_overrides.xml` | 1 plaintext file | Yes, if honoured | EAC flag likely; overwritten by updates | **whether the XML applies to Halo1 tables at all** |
| S3 | Edit Saber `strings_spanish` / `strings_latam_spanish` in `initial_textures.s3dpak` | 1 large pack (repack) | Yes | heavier repack; same EAC issue | which graphics mode uses it |
| S4 | Steam Workshop mod (`ModInfo.json`) | none in the install | Unknown | lowest | **no documented support for localization/data overrides** |

**Recommendation:** S1 for v1.0, since its format is fully verified and
a byte-exact rebuild was demonstrated. ~~Choose `SP` or `SU` as the
target table by an owner decision.~~ **Superseded (owner decision,
2026-10-08): S1 is applied to both `SU_Halo1.bin` and `SP_Halo1.bin`**
from one canonical subtitle mapping. See B.11.

Run S2 and S4 only as cheap side checks. Keep S3 in reserve, in case
the Saber store renders in some mode.

### B.10 Remaining blockers (B1) — revised 2026-10-08

1. **(c) Load behaviour, per table:** does MCC display an edited
   `SU_Halo1.bin` string? Separately, does it display an edited
   `SP_Halo1.bin` string? In which graphics modes, with EAC off? Only
   the B.12 PoC can answer this. Each table is tested on its own, and
   each in-game step needs its own approval.
2. **Which store renders:** `.bin` vs Saber `.s3dpak`, per mode. The
   same PoC answers this, because it edits only the `.bin` store.
3. ~~**Language routing.**~~ **Closed (owner baseline, 2026-10-08):**
   LATAM primary + Spain fallback shows `SU` text and plays Spain audio
   in Classic and Anniversary (B.11.1).
4. ~~**Speaker labels.**~~ **Out of scope (owner, 2026-10-08):** in the
   baseline, no speaker names appear in Spanish, even with the
   speaker-name option on. That matches `SP`/`SU` having no `&id`
   labels. Original behaviour is preserved: no tool adds, removes or
   edits speaker labels.
5. **Update overwrite:** any MCC update may restore the tables, so the
   pins and hashes in the PoC procedure are mandatory.
6. Policy, unchanged: CE es-MX text in an MCC file stays personal and
   local-only (feasibility §7).

### B.11 Language configuration and the two-table strategy (owner decision, 2026-10-08)

#### B.11.1 Language behaviour — USER-VERIFIED (B.12 baseline, 2026-10-08)

| Setting | Value |
|---|---|
| Primary language | **Spanish (Latin America)** |
| Fallback language | **Spanish (Spain)** |

| | Current (unmodified game) | v1.0 target |
|---|---|---|
| Subtitles | LATAM text (expected from `SU_Halo1.bin`) | the approved subtitle per line; MCC's original text where none is approved |
| Audio | Spain Spanish (expected from `sounds_dialogs_spanish.fsb`) | CE es-MX audio through the **Spain audio slot**; Spain audio where none is approved |

- **Evidence level: user-verified.** First it was the owner's report of
  normal play. The B.12 baseline then confirmed it on the unmodified
  game (B.12 step 1, `v-000012`–`v-000014`):
  - **Classic:** `SU` subtitles and Spain Spanish audio.
  - **Anniversary:** `SU` subtitles and Spain Spanish audio.
  - **Speaker names:** they don't appear, even with the option on. This
    is out of scope, and the original behaviour is preserved.

  The engine mechanism (fallback vs `game.cfg` `AudioTrack`) is still
  unknown. It doesn't affect the design.
- Consequence: the v1.0 audio target is unchanged (the Spain FSB
  slot). The subtitle target is **`SU`** for the primary configuration.
  `SP` is patched as well (B.11.2), so the Spain-fallback and
  Spain-primary paths show the same approved text.

#### B.11.2 Approved strategy: one canonical mapping, two tables

- **Both tables are planned targets:** `SU_Halo1.bin` (LATAM, primary)
  and `SP_Halo1.bin` (Spain, fallback).
- **One canonical subtitle decision per slot.** The `subtitle` object
  in `manual_mappings.json` stays the only place a subtitle is chosen
  and approved. There are no per-table subtitle mappings. The text
  comes from CE `es-MX` or from the user's custom text.
- **The same approved text goes to both tables.** A build writes that
  text into the `SU` entry and the `SP` entry for the slot's key.
- **Unmatched entries are preserved.** Every entry without an approved
  subtitle keeps its original bytes in each table, so `SU` keeps MCC's
  LATAM text and `SP` keeps MCC's Spain text. UI strings and other
  levels' entries are never touched.
- **Keys are validated independently in each table.** The key rule
  (B.6) is table-independent. Even so, a build looks the key up in each
  table separately. It requires exactly one hit per table and never
  carries an entry index from one table to the other. A miss in either
  table stops that slot from being written to either table, and it is
  reported. Today both tables hold 3,400 keys, and `0x26FA1B53` is
  entry #497 in each. Each was found independently on the copies, but
  that is a fact about this build, not an assumption to rely on.
- **Audio and subtitle stay independent.** The subtitle written for a
  slot does not depend on its `audio` decision (CE, kept Spain audio, or
  none), and vice versa (design §5.1).
- **Two kinds of verification (owner decision, 2026-10-08).** An
  in-game test is **not** required for every key.
  - **Structural key verification (tool, every key, every table):** a
    build proves for each approved slot, in each target table, that the
    key `CRC-32/MPEG-2(UPPER(tag path))` occurs exactly once and the
    table parses and passes its header checks. It also proves that only
    the intended entries change. This is a machine check recorded in
    build reports, not in `verifications.json`.
  - **Representative runtime verification (owner, a few lines per
    table):** in-game observations that a table is actually used, and
    that the key rule picks the line that is played. They are recorded
    in `verifications.json` with the approved check names:
    - **`subtitle_key_link`**: the on-screen text for a played line
      equals that table's entry for the line's key;
    - **`subtitle_load`**: an edited entry in that table is displayed
      (B.12 step 3).

    Each fingerprint names the table and its SHA-256. A `pass` for `SU`
    says nothing about `SP`. The `verifications/1` schema already
    allows both check names. They were approved by the owner on
    2026-10-08.
- **Not approved by this decision:** bulk editing, generating complete
  tables, writing CE text into any table, FSB repacking, and any change
  to the installed game. The strategy describes what M6 will do *after*
  B1 and B2 close. The next executable step is the B.12 PoC, and each of
  its steps needs approval.
- **Data-model follow-up (planned, not implemented):** the
  `subtitle.mcc_key_hash` comment in design §5.1 ("target row in
  `SP_Halo1.bin`") becomes "the key in every target table". Under the
  split above, the validator rule changes:
  - **From:** "a passing `subtitle_key_link` for this slot".
  - **To:** the key is accepted when two things hold:
    1. a **structural** check finds it exactly once in each target
       table;
    2. **representative** `subtitle_key_link` passes exist for each
       target table (not necessarily for this slot).
  This is a `manual-mappings` schema/validator change and needs owner
  approval before it is made.

### B.12 Revised B1 PoC — one entry, each table independently (NOT executed; each step needs explicit approval)

**Target line:** `sound\dialog\a10\a10_350_captkeyes`, slot
`es:A10_350_captkeyes#0`, key `0x26FA1B53`. In the hash-verified copies
under `work/mcc/loc/copies/`, it is entry #497 of 3,400 in both tables,
found independently in each:

| Table | Copy SHA-256 | Size |
|---|---|---|
| `SU_Halo1.bin` | `247d25298af3d5f990cd20ff5177e05078173347b7bdf395c3995a59c60244d0` | 203,848 B |
| `SP_Halo1.bin` | `794deac326d401a1fb6f5de50f8979f921159a412b095a368ef5424ed4342dda` | 204,128 B |

~~`SP` and `SU` texts differ for this line, so either table can be
recognised on screen.~~ **Corrected by step 0:** they differ only in the
case of two letters, which is too weak to tell the tables apart on
screen. The baseline therefore adds three cryo-opening
**discriminator lines** whose `SU`/`SP` texts differ by 3 words each.
`a10_350_captkeyes` stays the PoC target for steps 2–3, where the
distinct markers tell the tables apart.

| Line | Key | Entry (SU / SP) | Word differences SU vs SP | Purpose |
|---|---|---|---|---|
| `a10_350_captkeyes` | `0x26FA1B53` | 497 / 497 | 0 (case only) | PoC target |
| `a10_080_cryotech` | `0xE0874E33` | 2946 / 2946 | 3 | baseline discriminator |
| `a10_130_cryotech` | `0x3A6657C5` | 761 / 761 | 3 | baseline discriminator |
| `a10_150_cryotech` | `0x260F7CCF` | 482 / 482 | 3 | baseline discriminator |

Each entry was found independently in each table. Across all of `a10`,
46 of 101 lines differ in words between `SU` and `SP`.

**Safety rules for every step:**
- Nothing under `HALO_MCC_FOLDER` is modified before step 3, and step 3
  needs a separate approval for each sub-step.
- Tests use only MCC's own **anti-cheat-disabled launch mode** (the
  mode Halo Support documents for playing mods [^modinfo]). EAC is not
  bypassed or tampered with.
- Before any change: back up the original outside the install, and
  verify its SHA-256 both before and after copying.
- Backups, candidates and reports stay in git-ignored `work/`. No table
  copy, candidate or subtitle text is committed.
- Only one entry is changed, in one table, per candidate. There is no
  bulk editing and no FSB work.

#### Step 0 — Pre-flight (read-only) — ✅ DONE 2026-10-08

Run: `python scripts/discovery/b1_baseline.py` (read-only; it writes only
git-ignored `work/mcc/reports/b1_step0_preflight.json` and
`b1_baseline_sheet.md`). Results:
- Steam app `976730`, build **`19905945`** (from `appmanifest_976730.acf`)
  = expected.
- Installed `SU_Halo1.bin` SHA-256 `247d2529…44d0` and `SP_Halo1.bin`
  `794deac3…2dda` both **equal the copies and the pins**. Both parse,
  pass every header check, and hold 3,400 keys.
- All four baseline tags are in `sounds_dialogs.lst.bin`. Each key is
  found **exactly once in each table**, looked up independently.
- The helper's `--match "<text>"` mode compares typed on-screen text
  with the `SU` and `SP` entries. It returns `inconclusive` for
  case-only differences, by design. Synthetic tests are in
  `tests/test_b1_baseline.py`.

Original plan:

- Hash the installed `SU_Halo1.bin` and `SP_Halo1.bin`. They must equal
  the copy hashes above. Also record the MCC Steam build ID; it must be
  `19905945`. If anything differs, **stop**: the copies are stale and
  B.4–B.6 must be re-run first.
- A local, git-ignored helper prints the `SU` and `SP` text for key
  `0x26FA1B53`, so the owner can compare on screen. (Writing this helper
  is part of the approval for step 1.)

#### Step 1 — Baseline observation (no modification; R4) — ✅ DONE, owner-verified 2026-10-08

**Result:** in primary LATAM + fallback Spain, with subtitles on and the
game unmodified:

| Mode | Subtitles | Audio | Speaker name |
|---|---|---|---|
| Classic | `SU` text | Spain Spanish | not shown (option on) |
| Anniversary | `SU` text | Spain Spanish | not shown (option on) |

- **Recorded** as `v-000012` (`es:A10_080_cryotech#0`), `v-000013`
  (`A10_130`) and `v-000014` (`A10_150`).
  - Check: `subtitle_key_link`, `pass`.
  - The fingerprint holds the `SU_Halo1` name, SHA-256, key and entry,
    plus the Spanish sample, both graphics modes and the language
    settings.
- These are the first **representative runtime** verifications for
  `SU`. Together with the structural check, they support the B.6 key
  rule for `SU`.
- **Not recorded:**
  - `a10_350`, whose `SU`/`SP` texts differ only in case, so the table
    can't be attributed. Step 3a's marker will settle it.
  - Any `SP` key link: `SP` wasn't displayed, and the optional
    Spain-primary run wasn't done.
- **Gate passed:** the result matches B.11.1, so step 2 may proceed.

Plan as written:

The owner plays the `a10` opening through the three discriminator lines
and up to `a10_350`, in the **user-reported configuration** (primary LATAM, fallback Spain), in **classic** and
**Anniversary** graphics. For each mode, they record:
- which text appears: `SU`, `SP`, or neither;
- the audio language: Spain, English, or other.

*Optional:* repeat once with Spanish (Spain) as the primary language.
This is a settings change, not a file change. It gives the baseline for
step 3b. Afterwards, set the configuration back to primary LATAM.

**Record:** append verifications to `mappings/verifications.json` with
subject `mcc:es:A10_350_captkeyes#0`:
- `subtitle_key_link` for `SU_Halo1`, if `SU` text was shown;
- `subtitle_key_link` for `SP_Halo1`, if the optional run showed `SP`
  text.

Each fingerprint names the table and its SHA-256, the graphics mode,
and the language settings. Record the audio observation in the note.

**Gate:** if the baseline contradicts B.11.1 (e.g. `SP` text or English
audio under LATAM primary), **stop** and re-plan with the owner before
step 2.

#### Step 2 — Build two one-entry candidates offline (copies only) — ✅ DONE 2026-10-08

**Run:** `python scripts/discovery/b1_build_poc_candidates.py` (about 1 s).
- **Patcher:** `scripts/common/mcc_loc_patch.py`, pure functions.
  - It does same-byte-length one-entry replacement only.
  - It cross-checks the splice against a full re-serialisation from the
    parsed model.
- **Inputs:** the pinned copies only. The installed tables were hashed
  and never written.
- **Outputs (git-ignored):**
  - `work/mcc/loc/poc/{SU,SP}_Halo1.bin`;
  - `work/mcc/reports/b1_poc_candidates.json`;
  - `work/mcc/reports/b1_poc_install_rollback.md`.

| | `SU_Halo1.bin` | `SP_Halo1.bin` |
|---|---|---|
| Original SHA-256 (copy = install = pin) | `247d25298af3d5f990cd20ff5177e05078173347b7bdf395c3995a59c60244d0` | `794deac326d401a1fb6f5de50f8979f921159a412b095a368ef5424ed4342dda` |
| **Candidate SHA-256** | `de8cc7ee68c5e575ce117146ca9bebb14a7f96d35cfbca186aca3912fa2ad9be` | `9856cfdea74e00e864f1cf9596e7d0431d7a58ca434f3fd0aa6690295c11b63f` |
| Size (unchanged) | 203,848 B | 204,128 B |
| Key / entry (own lookup) | `0x26FA1B53` / #497 of 3,400 | `0x26FA1B53` / #497 of 3,400 |
| Entry span | `0x9FB9`, 91 B | `0xA009`, 91 B |
| Replacement (ASCII) | `[B1-SU] a10_350` + 76 `.` | `[B1-SP] a10_350` + 76 `.` |
| Bytes differing | 89, all inside the entry | 89, all inside the entry |
| Checks | 16/16 | 16/16 |

The 16 checks run per table:
- Rebuilding the unmodified and the patched file from the model gives
  byte-identical output.
- The size and all header fields are identical. Header checks pass, and
  the table name and name hash are unchanged.
- The keys are identical. The key is found once, at the same index.
- The target holds exactly the marker, and every other entry and span
  is byte-identical.
- The diff lies inside the target entry, and the target is valid UTF-8.
- The build is deterministic: it runs twice in memory, and a second
  script run gives the same file hashes.
- The installed file equals the original.

**Tests:** 10 synthetic tests are in `tests/test_mcc_loc_patch.py`. They
cover:
- the key rule;
- identity rebuilds with several filler sizes;
- variable-length size recomputation (model only, not used);
- a one-entry patch, determinism, and per-table names;
- refusal of a wrong length, NUL, a missing key, unsorted/duplicate
  keys, and invalid UTF-8;
- marker padding;
- collateral-change detection.

Plan as written:

| Candidate | Source | Change |
|---|---|---|
| `work/mcc/loc/poc/SU_Halo1.bin` | verified `SU` copy | entry for `0x26FA1B53` → `[B1-SU] a10_350` |
| `work/mcc/loc/poc/SP_Halo1.bin` | verified `SP` copy | entry for `0x26FA1B53` → `[B1-SP] a10_350` |

- **Distinct markers** say which table rendered. The markers are ASCII
  only, with no CE text and no subtitle text.
- **Same byte length (recommended first variant):** pad each marker with
  `.` to the original entry's UTF-8 byte length. Then the file size and
  every header field stay identical, and the only bytes that differ are
  inside that one entry. A variable-length edit (needed later for real
  text) is a separate follow-up after this PoC. It recomputes
  `0x04/0x08/0x68/0x7C` (B.4).
- **Per-table checks:** each table is checked on its own, and a failed
  check stops that candidate.
  1. The key is found by lookup in *this* table, exactly once. The index
     is not taken from the other table.
  2. Rebuilding the untouched copy with `mcc_loc` gives a byte-identical
     file.
  3. The candidate parses, and its table name and name hash (`0x28`)
     are unchanged and match its own name.
  4. The other 3,399 entries are byte-identical, and the byte diff lies
     entirely inside the target entry's span.
  5. The keys are unchanged and ascending, and the filler is zero.
- **Report:** `work/mcc/reports/b1_poc_candidates.json` records the
  source and candidate SHA-256, key, index, entry span and check
  results for each table.
- Synthetic-byte tests cover the patch function (one entry, same length,
  key lookup per table) before it touches a real copy.

#### Step 3 — In-game tests, one table at a time (separate approval for each sub-step) — NOT APPROVED, not started

**Prepared (2026-10-08):** step 2 writes the exact commands for this
machine to `work/mcc/reports/b1_poc_install_rollback.md`. That file is
git-ignored because it holds local paths. It covers 3a (`SU` only) and
3b (`SP` only) separately. Each sub-step has these PowerShell blocks,
and every block stops on any hash mismatch:
1. Pre-check that the installed file equals the original.
2. Back up to `work/mcc/loc/backup/19905945/` and verify the backup.
3. Verify the candidate hash, place the candidate, and verify the
   placed hash.
4. Roll back: restore the original and verify its hash. This runs
   always, even after a hang or failure.

| Table | Original SHA-256 (pre-check and rollback target) | Candidate SHA-256 (placed-file check) |
|---|---|---|
| `SU_Halo1.bin` | `247d2529…44d0` | `de8cc7ee…d9be` |
| `SP_Halo1.bin` | `794deac3…2dda` | `9856cfde…b63f` |

The owner runs every command by hand. Tools never copy into the install
and never launch MCC. In 3a/3b, only one table is replaced at a time.

**Common procedure:**
1. Close MCC.
2. Hash the installed file. It must match step 0.
3. Copy it to `work/mcc/loc/backup/19905945/` and verify the copy's
   hash.
4. Place the candidate, then verify that the installed hash equals the
   candidate hash.
5. Launch with anti-cheat disabled and play to the line in both graphics
   modes.
6. Close MCC, restore the original, and verify that the installed hash
   equals the recorded original.

Steam's "Verify integrity of game files" is the second safety net.
Never have more than one table replaced at a time in 3a/3b.

| Sub-step | File placed | Settings | Expected if the `.bin` drives subtitles | What it answers |
|---|---|---|---|---|
| **3a** | `SU` candidate only (`SP` original) | primary LATAM, fallback Spain | `[B1-SU] …` shown | Does the primary path load an edited `SU`? |
| **3b** | `SP` candidate only (`SU` original) | primary LATAM, fallback Spain; then primary Spain | LATAM: original `SU` text (no marker). Spain: `[B1-SP] …` | Does MCC load an edited `SP`? Does the fallback ever read `SP` for subtitles? |
| 3c *(optional, later)* | both candidates | primary LATAM | `[B1-SU] …` only | That the combined two-table deployment loads cleanly |

**Outcomes and next actions:**

| Observation | Meaning | Next |
|---|---|---|
| Marker shown in both modes | `.bin` store drives subtitles for that table | record `pass`; B1(c) closed for that table |
| Original text shown in a mode | another store renders there (likely Saber `strings_*`, B.7) | record; S3 for that mode, as a separate approval |
| Hang, crash, or EAC message | integrity check or format error | restore immediately, verify hash, stop, report |
| `[B1-SP]` shown under LATAM primary | fallback reads `SP` for subtitles | record; contradicts B.11.1, so re-plan with owner |

#### Step 4 — Record

- Write the outcomes into this section and the roadmap.
- Append one verification **per table and per test** (`subtitle_load`
  with result `pass`/`fail`, a fingerprint with the table, candidate
  hash, graphics mode and settings).
- Catalog `subtitle` fields stay `unresolved` until the owner approves
  promoting `derived:mcc_loc_key_crc32_tag_path` for verified tables.

**After the PoC (not part of it, each a separate approval):**
- a variable-length one-entry test;
- the data-model follow-up in B.11.2;
- then M6's generator, which writes the approved text into both
  tables.

#### Superseded: single-table PoC (original B.11, 2026-10-08)

The first plan patched only `SP_Halo1.bin` with one marker and treated
the target table as an open owner decision. It is replaced by B.12:
both tables are targets (B.11.2), each is tested independently with its
own marker, and the user-reported configuration is the baseline.

| | Campaign Evolved | MCC Halo CE |
|---|---|---|
| Container | `.locres` in Oodle-compressed `.pak` | plain `.bin` in `Data/ui/localization` |
| LATAM culture | **`es-MX`** (separate from `es-ES`) | **`SU`** (LATAM text; `SP` = Spain) — B.5; v1.0 patches both (B.11) |
| Key type | UE namespace + key strings | CRC-32/MPEG-2 of upper-cased label (B.6) |
| Line↔subtitle link | **explicit**: voice asset → `HaloAudioTranscriptionLine{StringTable, LineKey}` (VERIFIED 2026-10-08) | **derived**: key = hash of the dialogue tag path (101/101 `a10`); in-game confirmation pending, per table (B.12 step 1) |
| Speaker label | expected in data (colour tables exist) | inline `&id` prefix (EN only) |
| Readable now? | needs FModel JSON or Oodle | yes (structure partly decoded) |

---

## Sources

[^ue-loc]: Epic Games, [Localization overview for Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine/localization-overview-for-unreal-engine). LocRes are the compiled per-culture runtime files of a localization target. See also the [UE 4.26 localization overview](https://docs.unrealengine.com/4.26/en-US/ProductionPipelines/Localization/Overview) and [FTextLocalizationMetaDataResource::CompiledCultures](https://docs.unrealengine.com/4.27/en-US/API/Runtime/Core/Internationalization/FTextLocalizationMetaDataResourc-/CompiledCultures/index.html) (the `.locmeta` culture list).
[^locres]: `.locres` namespace/key/string-table layout as implemented by [CUE4Parse](https://github.com/FabianFG/CUE4Parse) (`FTextLocalizationResource`), the library FModel uses.
[^mccloc]: Lord-Zedd, [MCCLocalizationEditor](https://github.com/Lord-Zedd/MCCLocalizationEditor) README (read 2026-10-08): keys are "CRC32MPEG hashes", the bin stores "an all-caps hash of the filename", an incorrect hash makes the game hang, and "any changes you make will flag the anticheat". Not installed.
[^ocsub]: Open Carnage, [CEA Custom Subtitles](https://opencarnage.net/index.php?/topic/8307-cea-custom-subtitles/) (search-result excerpt; the page returns 403 to automated fetches): subtitles in `initial_textures.s3dpak` `strings_<language>`, keyed by tag path; only `sound\dialog\` sounds played by script / AI conversations are eligible; edited with SuP.
[^excession]: Microsoft Learn, [Excession Tool Overview](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/excessionoverview) and [Creating a Mod Package](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/creatingmodpackage/creatinghome): mod packages are maps, campaigns, game variants and metadata. Nothing on localization.
[^modinfo]: `ModInfo.json` example fields (`Title.Neutral`, `GameModContents.HasSharedFiles/HasCampaign`) per a [Steam Workshop discussion](https://steamcommunity.com/workshop/filedetails/discussion/2962107814/5966762781879998278/) and [Halo Support: Steam Workshop mods](https://support.halowaypoint.com/hc/en-us/articles/28916975982868-How-to-Download-and-Play-Mods-for-Halo-The-Master-Chief-Collection-via-the-Steam-Workshop).
[^impsub]: [Improved Subtitles (Nexus #2536)](https://www.nexusmods.com/halothemasterchiefcollection/mods/2536), per its search-result summary: it fixes CE subtitle typos and speaker names. The install method was not readable (403).
[^mccbin]: Searched 2026-10-08. No format docs found. The official MCC modding docs ([Excession overview](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/excessionoverview)) do not cover the shell string tables.
