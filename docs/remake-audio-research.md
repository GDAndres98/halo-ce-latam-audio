# Halo: Campaign Evolved — Audio & Wwise Research (Phase 2 discovery)

**Date:** 2026-10-08. **Scope:** read-only discovery. No game file was
modified, no tool was installed, nothing was decompressed, no audio was
decoded in this pass. Evidence comes from (a) the user's existing FModel
exports and log, (b) the user's UE4SS install/log, and (c) reading the
**uncompressed** table-of-contents structures of the game's own
`.pak`/`.utoc` containers with two throwaway, stdlib-only Python scripts
(kept in the session scratchpad, not in this repo).

> **Update 2026-10-08 (Phase 2B, approved Oodle read-only inspection):**
> the hypotheses in §5.3 and §6 are now **VERIFIED** for
> `VO_SCR_M01_00460_CryoTech`. The full chain is in
> [`poc-ce-line-link.md`](poc-ce-line-link.md). New facts:
> - The voice asset class is **`HaloAudioVoiceVariations`**:
>   `VoiceEvents[]` of `HaloAudioVoiceEntry{VoiceEvent, Transcription, LipSync}`.
>   (`HaloAudioSound{PlayEvent, StopEvent, Category, Tails, TranscriptionLine}`
>   exists in the usmap too.)
> - **AkAudioEvent → media is explicit**. After the (all-default) tagged
>   properties and UObject's `HasGuid` int32, the asset holds a
>   `WwiseLocalizedEventCookedData` struct. Its `EventLanguageMap` lists,
>   per Wwise language, `Media[]{MediaId, MediaPathName, DebugName = source
>   .wav}` and `SoundBanks[]`. Scripted lines are **streamed loose media**
>   (`bStreaming`) referenced from a per-mission bank (`VO_SCR_M01` =
>   1447133044), which is why §5.1 found mostly systemic banks.
> - The event `EventId` equals FNV-1 of the event name (corroborates §5.1).
> - **Lip-sync is localized per culture**: `Meteorite/Content/L10N/<culture>/Audio/LipSync/...`
>   copies exist for es-MX, es-ES and others (MetaHuman `AnimSequence`).
> - The FModel `.usmap` blocker (§7) and the Oodle risk (§8) are bypassed.
>   Our own stdlib parsers read the containers with FModel's bundled
>   Oodle DLL (decompression only) and the `USMAP_FILEC` mappings.

Evidence labels used below:

- **VERIFIED** — observed directly in a file on disk.
- **DERIVED** — computed from verified data (e.g. a hash), reproducible.
- **HYPOTHESIS** — consistent with the evidence, not yet observed.
- **UNKNOWN** — open question.

---

## 1. Where the user's material is

| What | Location | Notes |
|---|---|---|
| FModel (portable) | `%USERPROFILE%\Downloads\858461d19e29803479555059acb59a03a0986de8\FModel.exe` | Settings in `%APPDATA%\FModel\AppSettings.json` |
| FModel output | `…\858461d19e…\Output\Exports\` | 1.5 GB: 2,971 `.wem` + 349 `.wav`, **no JSON/property exports, no `.locres`** |
| FModel log | `…\858461d19e…\Output\Logs\FModel-Log-2026-10-07.log` | 25,817 lines; ~22,000 unique asset paths opened |
| UE4SS install | `HALO_REMAKE_FOLDER\Meteorite\Binaries\Win64\ue4ss\` (+ `dwmapi.dll` proxy) | v3.0.1 Beta, build `c838a8ac` |
| UE4SS "dump" | `…\ue4ss\Meteorite-5.5.4-1121610+++Meteorite+Rel-i343-Meteorite-2607-CU4-c838a8ac.usmap` | Unversioned-property **mappings** only. No object dump or header dump was generated |
| UE4SS copy | `…\858461d19e…\UE4SS_v3.0.1\` | Same `.usmap` |
| User Blueprint mods folder | `HALO_REMAKE_FOLDER\Meteorite\Content\Paks\LogicMods\` | Created for UE4SS's BP mod loader |

> ⚠ The user's UE4SS install and `LogicMods/` folder sit **inside the
> game install**. Hard rule 1 applies to this project's tooling, which
> must never write there. Future sessions should treat those files as
> read-only too.

**Exported audio inventory — VERIFIED**

| Export folder | Files | What it is |
|---|---|---|
| `Exports/Meteorite/Content/WwiseAudio/<bankId>/` (48 dirs) | 3,081 (`.wem` + some `.wav`) | Non-localized SFX/music banks |
| `…/WwiseAudio/Spanish(Mexico)/<bankId>/<mediaId>.wav` | **222 WAV in 17 bank folders** | Localized **es-MX** voice media |
| `…/WwiseAudio/English(US)/1430355330/` | 8 WAV | English voice media |
| `…/WwiseAudio/Korean/2874891402/` | 5 WAV | Korean voice media |
| `Exports/*.wav`, `output.mp3` | 5 | Ad-hoc single saves from FModel's player |

The exports are keyed **only by numeric Wwise IDs** (`bankId/mediaId`).
There is no line name, event name, or subtitle key anywhere in the exported
files. The link to a dialogue line has to come from the event assets (§5).

All 222 es-MX media IDs were cross-checked against the es-MX language
pak's own index: **222/222 present there, 0/222 present in the English
pak** — VERIFIED.

---

## 2. Encryption status — VERIFIED: not encrypted

Rule 2 had left this open in `feasibility.md` §2. It is now resolved:

- Every `.utoc` header has `EIoContainerFlags` = `0x08` or `0x09`
  (Indexed ± Compressed). The **Encrypted bit (0x02) is unset in all 28**,
  and every `EncryptionKeyGuid` is all-zero.
- Every `.pak` footer has `bEncryptedIndex = 0` and a zero key GUID.
- FModel's settings have an empty `mainKey` and no dynamic keys. Its log
  line `AES: 1/1` is FModel's built-in zero-key placeholder for the
  default GUID, not a real key.

No key was searched for, needed, or used.

**Compression:** all paks use **Oodle** (footer compression-method table
= `["Oodle"]`). Small files and most `.wem` media are stored
uncompressed. The `.locres` files and the IoStore packages (`.uasset`
contents) are Oodle-compressed, so reading their *contents* needs an
Oodle-capable reader such as FModel/CUE4Parse (§8).

---

## 3. Container layout — VERIFIED

| Container | Mount | Contents |
|---|---|---|
| `pakchunk0-Windows.pak` (14,704 files) | `../../../` | Loose non-package files: `.locres`/`.locmeta`, configs, 9,870 non-localized Wwise media |
| `pakchunk0-Windows.utoc` (122,745 chunks) + `pakchunk115…530.utoc` | `Meteorite/Content/` | All UE packages (`.uasset`/`.umap`), including the `Audio/`, `WwiseAudio/Events/`, and `Tags/` trees |
| `pakchunk1…13-Windows.pak` (15,444 files each) | `Meteorite/Content/WwiseAudio/` | **One Wwise voice language per chunk**: 53 localized `.bnk` + 15,391 localized `.wem` |

**Language → chunk map (VERIFIED from each pak's directory index):**

| Chunk | Wwise language | | Chunk | Wwise language |
|---|---|---|---|---|
| 1 | German | | 7 | Japanese |
| 2 | English(US) | | 8 | Korean |
| 3 | **Spanish(Spain)** | | 9 | Polish |
| 4 | **Spanish(Mexico)** | | 10 | Portuguese(Brazil) |
| 5 | French(France) | | 12 | Chinese(PRC) |
| 6 | Italian | | 13 | Chinese(Taiwan) |

(No chunk 11 is present.) Paths inside a language chunk:

```
WwiseAudio/Spanish(Mexico)/<bankShortId>.bnk            # 53 localized banks
WwiseAudio/Media/Spanish(Mexico)/<NN>/<mediaId>.wem      # 15,391 localized media
```

**Campaign Evolved ships a complete Latin American Spanish voice track**
(Wwise language `Spanish(Mexico)`), separate from Spain Spanish. This is
VERIFIED from the containers themselves, not from marketing copy.

---

## 4. Dialogue asset families — VERIFIED (names), HYPOTHESIS (roles)

Counts come from the IoStore directory indexes (all `.utoc` files):

| Family | Path pattern | Count | Example |
|---|---|---|---|
| Scripted VO (in-mission) | `Audio/scripted/<MISSION_FOLDER>/<LINE>.uasset` | 1,035 | `Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech` |
| Cinematic VO | `Audio/cinematic/vo_cin_<mission>/<LINE>.uasset` | 488 (incl. 46 `temp_mocap_VO`) | `Audio/cinematic/vo_cin_m01pillarofautumn/vo_cin_m01_cin01_sc02_bridge_00010_keyes` |
| Systemic/combat VO | `Audio/Systemic/vo_sys_<character>/…` | 2,280 | `Audio/Systemic/vo_sys_johnson/vo_sys_default_01contact_ambush_johnson` |
| Wwise events | `WwiseAudio/Events/<family>/<folder>/<line>/Play_<LINE>.uasset` | 18,580 (all families) | `WwiseAudio/Events/scripted/VO_SCR_M01PILLAROFAUTUMN/vo_scr_m01_00460_cryotech/Play_VO_SCR_M01_00460_CryoTech` |
| Lip-sync | `Audio/LipSync/{scripted,cinematic,Systemic}/…/<LINE>.uasset` | 11,698 | `Audio/LipSync/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech` |
| Blam sound tags (converted) | `Tags/sound/scripted/<MISSION_FOLDER>/<mNN_NNNNN_speaker>-sound.uasset` (+`.ubulk`) | 2,102 scripted, 4,754 `dialog/combat` | `Tags/sound/scripted/VO_SCR_M01PILLAROFAUTUMN/m01_00460_cryotech-sound` |
| Mission dialogue tags | `Tags/sound/scripted/<MISSION_FOLDER>/<mission>-ai_mission_dialogue.uasset` | per mission | `…/vo_scr_m08twobetrayals-ai_mission_dialogue` |
| **Subtitle transcription** | `Audio/Transcription/Subtitles/{scripted,cinematic,Systemic}/VO_*.uasset` | 28 | `Audio/Transcription/Subtitles/scripted/VO_SCR_M01PILLAROFAUTUMN` |

**Stable line key (VERIFIED as a naming pattern):** one dialogue line has
the same identifier across up to five asset families, differing only in
case and prefix/suffix:

```
VO_SCR_M01_00460_CryoTech
  ├─ Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech        (UE audio asset)
  ├─ WwiseAudio/Events/scripted/…/vo_scr_m01_00460_cryotech/Play_VO_SCR_M01_00460_CryoTech  (AkAudioEvent)
  ├─ Audio/LipSync/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech (lip-sync)
  └─ Tags/sound/scripted/VO_SCR_M01PILLAROFAUTUMN/m01_00460_cryotech-sound     (Blam sound tag)
```

Grammar: `VO_<FAMILY>_<MISSION>_<SEQ>_<Speaker>`. FAMILY is `SCR`/`CIN`/`SYS`.
MISSION is `M01`…`M10` for the original campaign and `M12`…`M14` for the
new DLC/prequel missions. Cinematic keys insert `cinNN_scNN_<shot>`.
Case varies across folders (`VO_SCR_M01PILLAROFAUTUMN` vs
`vo_scr_m03reconciliation`), so the catalog must compare
**case-insensitively** and keep the original spelling for display.

**Matching the name across families proves only a naming convention.**
The *explicit* links between families (which event plays which media,
which subtitle key a line uses) live inside the asset properties (§5).
Those haven't been read yet.

### 4.1 No shared ID with MCC — VERIFIED

Campaign Evolved numbers lines **independently** of classic Halo CE:
`m01_00460_cryotech` vs MCC `a10_010_cryotech`. Mission codes differ too
(`M01PILLAROFAUTUMN` vs `a10`). The only classic-style names are in
`Tags/Cinematics/a10/…` (cinematic tags, not VO). No tag or asset name
anywhere in the CE index matches an MCC `sound\dialog\…` name.
**Cross-game matching therefore has to be manual**, which is what the
project already planned.

---

## 5. Wwise IDs: what links to what

### 5.1 Bank IDs = FNV-1 hash of bank name — DERIVED, VERIFIED on 30+ banks

Wwise ShortIDs for named objects are the 32-bit FNV-1 hash of the
lowercased name. Hashing the asset folder names reproduces the numeric
bank IDs seen in the language paks and in the user's exports. Examples
from the es-MX export:

| Bank ID (export folder) | Name it hashes from |
|---|---|
| 1422995586 | `vo_sys_johnson` |
| 362848843 | `VO_SYS_Williams` |
| 1064924014 | `vo_sys_masterchief` |
| 1005569379 | `vo_sys_mendoza` |
| 3904710290 | `vo_sys_guiltyspark` |
| 84450521 | `VO_SYS_Bisenti` |

So the **222 es-MX WAVs the user exported are almost entirely systemic
combat chatter** (per-character banks), not scripted or cinematic
story lines. Banks `1430355328/29/30` and `2874891401/04/06` remain
**UNKNOWN**. Their names didn't hash-match any folder name tried.

### 5.2 Media IDs are per language — VERIFIED

Each language chunk holds 15,391 media files. Across English(US),
Spanish(Spain), and Spanish(Mexico) the **media-ID overlap is zero**, while
the 53 bank IDs are identical in every language. So:

- a media ID identifies **one language's recording** of a line;
- you cannot go from an English media ID to its es-MX counterpart by
  ID arithmetic or position;
- the language-independent anchor is the **event** (or the line key).

### 5.3 Event → per-language media — ~~HYPOTHESIS~~ VERIFIED 2026-10-08 (see poc-ce-line-link.md)

In current Wwise–Unreal integrations, an `AkAudioEvent` asset carries
cooked data per language. Per that integration's design, it lists the
soundbanks and media each language needs. [^wwise-ue] FModel/CUE4Parse
uses exactly this to resolve an event to playable `.wem` files. That is
how the user's exports ended up foldered by bank/media. [^fmodel]
Expected shape (to be **confirmed** against a real JSON export, not
assumed):

```
Play_VO_SCR_M01_00460_CryoTech (AkAudioEvent)
  EventCookedData.EventLanguageMap:
    Spanish(Mexico) -> { SoundBanks: [...], Media: [{ MediaId, MediaPathName, ... }] }
    English(US)     -> { ... }
```

If confirmed, this is the **explicit, authoritative link** from a stable
line key to its es-MX recording.

---

## 6. Subtitles (summary — details in `subtitle-research.md`)

- Dedicated UE localization target **`Subtitles`**, compiled to
  `Localization/Subtitles/<culture>/Subtitles.locres`. **`es-MX` and
  `es-ES` are separate cultures.** VERIFIED.
- 28 `Audio/Transcription/Subtitles/…` assets, one per mission per
  family plus some systemic characters. **VERIFIED 2026-10-08:** they
  are `StringTable` assets whose `TableNamespace` equals the `.locres`
  namespace. The voice asset references them explicitly via
  `HaloAudioTranscriptionLine{StringTable, LineKey}`.

---

## 7. What the user's FModel session tells us about blockers

- The FModel log shows **`MappingException: Package has unversioned
  properties but mapping file is missing`** up to 23:35, after the
  `.usmap` was generated (23:26). In FModel's settings the endpoint path
  points to the `.usmap` but is marked `IsValid: false`. **The mapping
  file does not appear to be loaded in FModel**, so FModel can't
  deserialize any property data yet: event cooked data, transcription
  tables, or lip-sync. Raw audio export still works because it doesn't
  need property parsing.
- `WwiseProvider.LoadExternalWwiseFiles` warned that no external Wwise
  directory exists under `Content/`. That's expected: everything is
  in-pak.

---

## 8. Risks specific to the CE side

| Risk | Impact | Mitigation |
|---|---|---|
| **Licensing / cross-game asset use** (`feasibility.md` §7–8) | The user's stated goal now uses CE es-MX audio and subtitles **as the shipped source**. 343i's MCC FAQ limits mods to retail-MCC assets. | **Unresolved; owner's decision.** Keep everything local and git-ignored. Never commit or redistribute CE audio/text. Revisit before any distribution. |
| Oodle-compressed `.locres`/packages | Can't read subtitle text or event data with stdlib | Use FModel (already installed by the user) for JSON exports, or, with explicit approval, load the Oodle DLL FModel already bundles |
| Unversioned properties | No `.usmap` → no property data | Fix FModel's mapping-file setting (§7) |
| Game patches | Build string `Meteorite-2607-CU4` pins the current IDs. A patch may renumber media IDs | Record build string + container hashes in every catalog. Rebuild and diff after updates |
| Re-written / re-recorded lines | CE dialogue isn't a 1:1 copy of 2001 lines. M12–M14 are new missions with no MCC counterpart | Manual mapping supports 1→n, n→1, and `no_equivalent` |
| `temp_mocap_VO` & `metz_*_iPhone` assets | Development scratch audio shipped in the build | Exclude from the catalog by path rule |
| Lip-sync/timing | CE line lengths ≠ MCC sample lengths (cinematics are time-locked) | Catalog both durations. The UI shows the delta. Decisions stay manual |

---

## Sources

[^wwise-ue]: Audiokinetic Q&A on the Wwise–Unreal workflow and event-based packaging: ["what's the loading strategy that events and banks use in EBP"](https://blog.audiokinetic.com/qa/10607/whats-the-loading-strategy-that-events-and-banks-use-in-ebp), ["localised defined soundbanks / SetCurrentAudioCultureAsync"](https://blog.audiokinetic.com/qa/13912/localised-defined-soundbanks-setcurrentaudiocultureasync), ["best practice multiple languages, external sources, Unreal"](https://audiokinetic.com/qa/9192/best-practice-multiple-languages-external-sources-unreal). The exact field names in §5.3 are **not** confirmed by these sources and must be checked against a real export.
[^fmodel]: [FModel](https://github.com/4sval/FModel) / [CUE4Parse](https://github.com/FabianFG/CUE4Parse). Behaviour inferred from the user's own FModel log (`CUE4Parse.UE4.Wwise.WwiseProvider`, `SaveAndPlaySound`) and export folder layout.
- UE pak v11 footer/index, IoStore `.utoc` header (`EIoContainerFlags`) and directory index: Unreal Engine 5.5 source layout, as implemented by CUE4Parse; read here with independent stdlib parsers.
- Wwise ShortID = FNV-1 32-bit of the lowercased name: reproduced empirically on 30+ bank IDs in this install (§5.1).
