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
`SP_Halo1.bin` is the Spanish table. No separate LATAM (`es-MX`) table
exists for Halo 1, consistent with MCC's documented "LATAM =
interface only" support. (Prefixes like `DA DU FI NO PO RU` exist for
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

### B.2-update (2026-10-08) — investigation on copies, then stopped

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

### B.3 Consequence for the mod

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

## Part C — Comparison

| | Campaign Evolved | MCC Halo CE |
|---|---|---|
| Container | `.locres` in Oodle-compressed `.pak` | plain `.bin` in `Data/ui/localization` |
| LATAM culture | **`es-MX`** (separate from `es-ES`) | none (only `SP` = Spain) |
| Key type | UE namespace + key strings | 32-bit hash (origin unknown) |
| Line↔subtitle link | **explicit**: voice asset → `HaloAudioTranscriptionLine{StringTable, LineKey}` (VERIFIED 2026-10-08) | **not found** |
| Speaker label | expected in data (colour tables exist) | inline `&id` prefix (EN only) |
| Readable now? | needs FModel JSON or Oodle | yes (structure partly decoded) |

---

## Sources

[^ue-loc]: Epic Games, [Localization overview for Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine/localization-overview-for-unreal-engine). LocRes are the compiled per-culture runtime files of a localization target. See also the [UE 4.26 localization overview](https://docs.unrealengine.com/4.26/en-US/ProductionPipelines/Localization/Overview) and [FTextLocalizationMetaDataResource::CompiledCultures](https://docs.unrealengine.com/4.27/en-US/API/Runtime/Core/Internationalization/FTextLocalizationMetaDataResourc-/CompiledCultures/index.html) (the `.locmeta` culture list).
[^locres]: `.locres` namespace/key/string-table layout as implemented by [CUE4Parse](https://github.com/FabianFG/CUE4Parse) (`FTextLocalizationResource`), the library FModel uses.
[^mccbin]: Searched 2026-10-08. No format docs found. The official MCC modding docs ([Excession overview](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/excessionoverview)) do not cover the shell string tables.
