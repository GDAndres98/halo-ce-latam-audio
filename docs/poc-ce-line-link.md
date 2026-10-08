# PoC: Campaign Evolved audio ↔ subtitle link for `VO_SCR_M01_00460_CryoTech`

**Date:** 2026-10-08. **Result: ✅ explicit link established, end to end.**
**Status: ✅ MANUALLY VERIFIED by the user (2026-10-08).** The user
listened to all three decoded recordings (Spanish(Mexico), English(US),
Spanish(Spain)) and confirmed each matches its culture's subtitle
(es-MX, en, es-ES). The fingerprint of what was verified is media IDs
`132700376` / `932939327` / `518750516` (wem SHA-256 in §3), build
`Meteorite-2607-CU4-c838a8ac`. This becomes entry `v-000001` in
`mappings/verifications.json` once that file exists (roadmap M3).
Read-only throughout. Installed games were only opened for reading.
Outputs were written only under the git-ignored `work/`. No Campaign
Evolved text or audio is in this repo.

## 1. How to reproduce

```
python scripts/discovery/link_ce_line.py \
    --voice-asset Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech \
    --vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe
python -m unittest discover -s tests
```

Inputs: `.env` (`HALO_REMAKE_FOLDER`, `USMAP_FILEC`). Oodle comes from
FModel's `Output\.data\oodle-data-shared.dll`; override it with
`--oodle-dll`. Output: `work/ce/records/vo_scr_m01_00460_cryotech.json`
(full record incl. subtitle text) and
`work/ce/audio/<Wwise language>/*.wem|*.wav`. Runtime ≈ 3 s.

## 2. The chain (every arrow is a reference field read from game data)

```
Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech      class HaloAudioVoiceVariations
 └─ VoiceEvents[0]  (struct HaloAudioVoiceEntry)
     ├─ VoiceEvent   ──import──▶  /Game/WwiseAudio/Events/.../Play_VO_SCR_M01_00460_CryoTech   (AkAudioEvent)
     │                              └─ EventCookedData.EventLanguageMap["Spanish(Mexico)"]
     │                                   ├─ Media[0].MediaId       = 132700376
     │                                   ├─ Media[0].MediaPathName = Media/Spanish(Mexico)/13/132700376.wem  → pakchunk4-Windows.pak
     │                                   ├─ Media[0].DebugName     = Scripted\VO_SCR_M01PILLAROFAUTUMN\VO_SCR_M01_00460_CryoTech.wav
     │                                   └─ SoundBanks[0]          = 1447133044 "VO_SCR_M01"
     ├─ Transcription  (struct HaloAudioTranscriptionLine)
     │    ├─ Type        = Subtitle
     │    ├─ StringTable ──import──▶ /Game/Audio/Transcription/Subtitles/Scripted/VO_SCR_M01PILLAROFAUTUMN  (StringTable)
     │    │                             └─ TableNamespace = "VO_SCR_M01PILLAROFAUTUMN", 101 keys, contains LineKey
     │    ├─ LineKey     = "VO_SCR_M01_00460_CryoTech"
     │    └─ MetaData    = {Character: CRYOTECH, Race: UN}
     │         └─ Localization/Subtitles/es-MX/Subtitles.locres [namespace VO_SCR_M01PILLAROFAUTUMN][key VO_SCR_M01_00460_CryoTech]  ✓
     │            (also en ✓, es-ES ✓)
     └─ LipSync      ──soft path──▶ /Game/Audio/LipSync/Scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech  (AnimSequence)
```

The StringTable → `.locres` step relies on standard UE behaviour: a
string-table entry's localized text is looked up under the table's own
namespace and the entry key. [^ue-st] Both values were read directly:
`TableNamespace` from the StringTable asset, and the key from
`LineKey`.

## 3. Structured record (redacted copy; full one in `work/`)

| Field | Value | Evidence |
|---|---|---|
| `ce_line_key` | `vo_scr_m01_00460_cryotech` (display: `VO_SCR_M01_00460_CryoTech`) | explicit (`LineKey`) |
| voice asset | `Meteorite/Content/Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech.uasset` in `pakchunk0-Windows.utoc`, class `HaloAudioVoiceVariations` | explicit |
| event | `…/Play_VO_SCR_M01_00460_CryoTech.uasset`, `AkAudioEvent`, EventId `3768155368` | explicit (+ FNV-1 of name matches: derived) |
| languages in event | 12 (incl. `Spanish(Mexico)`, `Spanish(Spain)`, `English(US)`) | explicit |
| es-MX media | `132700376` → `pakchunk4-Windows.pak`, 54,981 B, sha256 `42b21129…a3849`, decoded 3.629 s @ 48 kHz mono | explicit |
| en media | `932939327` → `pakchunk2`, 45,738 B, 3.559 s | explicit |
| es-ES media | `518750516` → `pakchunk3`, 54,715 B, 3.545 s | explicit |
| soundbank | `1447133044` "VO_SCR_M01" (same in all languages) | explicit (+ FNV-1 matches) |
| subtitle es-MX | `Subtitles/es-MX/Subtitles.locres` [`VO_SCR_M01PILLAROFAUTUMN`][`VO_SCR_M01_00460_CryoTech`], 73 chars | explicit |
| subtitle en / es-ES | same namespace/key, 77 / 58 chars | explicit |
| speaker | `CRYOTECH` (transcription metadata) | explicit |
| lip-sync | `Audio/LipSync/scripted/…/VO_SCR_M01_00460_CryoTech` (`AnimSequence`) | explicit |
| lip-sync es-MX / es-ES | `L10N/es-MX/Audio/LipSync/…`, `L10N/es-ES/…` exist | derived (UE `L10N` localized-asset convention) |
| Blam sound tag | `Tags/sound/scripted/VO_SCR_M01PILLAROFAUTUMN/m01_00460_cryotech-sound` | **derived (name only)**: not referenced by the voice asset |

## 4. Not resolved / caveats

- ~~Listening check pending.~~ **Done 2026-10-08.** The user confirmed
  audio ↔ subtitle for all three languages (see the status line at the
  top).
- `AkAudioEvent` has **16 trailing bytes** after the cooked-data struct
  that were not interpreted (recorded as `trailing_bytes_unparsed`).
- Lip-sync bodies (`AnimSequence`) are not parsed. The parser stops on
  `AnimNotifyEvent` (a schema slot missing from the usmap). Only the
  class and existence are recorded.
- The Blam `-sound` tag's relationship is name-only, so it isn't trusted.
- Only `HaloAudioVoiceVariations` (and the `HaloAudioSound` shape, which
  is handled but untested) have been exercised. Cinematic and systemic
  lines may use other shapes.

## 5. Tooling built (all stdlib + approved Oodle DLL)

| Module | Purpose |
|---|---|
| `scripts/common/pak.py` | pak v11 index + entry read (refuses encryption) |
| `scripts/common/iostore.py` | `.utoc` TOC/dir index + `.ucas` chunk read (refuses encryption) |
| `scripts/common/oodle.py` | `OodleLZ_Decompress` via ctypes (decompress only) |
| `scripts/common/usmap.py` | `.usmap` v0–4 schema reader |
| `scripts/common/zen.py` | UE5.5 zen package + unversioned properties |
| `scripts/common/locres.py` | `.locres` v0–3 |
| `scripts/common/mcc_loc.py` | MCC `<LANG>_Halo1.bin` structure (keys and pool kept separate) |
| `scripts/common/asset_metadata.py` | `.env` context, evidence vocabulary, FNV-1 |
| `scripts/discovery/link_ce_line.py` | this PoC |
| `scripts/discovery/inspect_iostore.py` / `inspect_localization.py` / `inspect_mcc_subtitles.py` | small inspectors |
| `tests/test_parsers.py` | 15 tests on synthetic bytes |

[^ue-st]: Epic Games, [Using String Tables for Text in Unreal Engine](https://dev.epicgames.com/documentation/unreal-engine/using-string-tables-for-text-in-unreal-engine). String tables give localized text one place to live, and their entries are identified by table namespace + key. Also see the [localization overview](https://dev.epicgames.com/documentation/en-us/unreal-engine/localization-overview-for-unreal-engine).
