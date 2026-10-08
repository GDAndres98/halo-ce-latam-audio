# Dialogue Catalog & Manual Mapping — Design v2

**Status:** schema v2, planning only, 2026-10-08. Nothing in §3–§6 is
implemented yet except the single-line CE record produced by
`scripts/discovery/link_ce_line.py` (the source of the §3 shape).
Milestones and acceptance criteria: [`roadmap.md`](roadmap.md).
Inputs: [`feasibility.md`](feasibility.md),
[`remake-audio-research.md`](remake-audio-research.md),
[`subtitle-research.md`](subtitle-research.md),
[`poc-ce-line-link.md`](poc-ce-line-link.md) (manually verified).

**v2 changes from v1:**
- The MCC replacement unit is now the **Spanish FSB sample slot**, not
  the tag.
- Audio and subtitle decisions are **independent objects**, each with
  its own status and approval.
- Added custom-subtitle and unmatched-line support, plus a
  `verifications` file.
- Reserved v1.1 processing metadata.

---

## 1. Principles (unchanged, plus three additions)

1. **Two independent catalogs, one user-owned mapping.** The CE and MCC
   catalogs are built only from their own game's data. Cross-game links
   exist **only** in `mappings/manual_mappings.json`.
2. **No automatic matching.** No tool proposes, scores, ranks, or
   pre-fills CE↔MCC pairs.
3. **Every in-catalog association carries evidence:** `explicit`,
   `explicit:index`, `derived:<rule>`, or `unresolved` (§7). Never
   invent one.
4. **Stable IDs over positions.** Indices and media IDs are attributes
   re-resolved on each build.
5. **Catalogs are disposable. Mappings and verifications are precious.**
   Tools never rewrite approved decisions.
6. **No game data in Git.** Catalogs, decoded audio, subtitle text and
   custom text live in git-ignored paths.
7. **(new) Audio and subtitle choices are independent.** Each MCC slot
   has a separate audio decision and subtitle decision, approved
   separately.
8. **(new) Originals are immutable.** Decoded, converted or (v1.1)
   processed audio is always a *new* file keyed by its inputs' hashes.
   Nothing is ever edited in place.
9. **(new) Human verification is data.** "A person listened and
   confirmed" is recorded explicitly (§5) and never inferred from
   evidence levels.

## 2. Layout

```
docs/                                    (committed)
schemas/                                 (committed, M3)  JSON Schemas for every file below
mappings/manual_mappings.json            (committed)  decisions, IDs only, no game text
mappings/verifications.json              (committed)  human listening/reading checks, IDs only
mappings/mission_map.json                (committed)  user-defined level ↔ mission table
mappings/manual_mappings.local.json      (ignored)    custom subtitle text, local file paths
mappings/.history/                       (ignored)    timestamped backups before every save
work/ce/catalog/<mission>.jsonl          (ignored)    CE records (§3)
work/ce/build.json                       (ignored)    CE build pins
work/ce/audio/<wwise_language>/…         (ignored)    decoded media (on demand)
work/mcc/catalog/<level>.jsonl           (ignored)    MCC records (§4)
work/mcc/subtitles.jsonl                 (ignored)    MCC string pool, unlinked (until B1)
work/mcc/build.json                      (ignored)
work/derived/<sha256>/                   (ignored)    converted/processed audio + recipe.json (§6)
```

`.gitignore` already covers `/work/`, `/mappings/*.local.json` and
`/mappings/.history/`.

## 3. Campaign Evolved catalog — one record per voice asset

The shape follows the implemented PoC record (see `poc-ce-line-link.md`
§3). Key fields:

```jsonc
{
  "schema": "ce-voice-asset/2",
  "ce_line_key": "vo_scr_m01_00460_cryotech",      // canonical, lowercase (from LineKey, else export name)
  "display_key": "VO_SCR_M01_00460_CryoTech",      // original spelling from LineKey
  "family": "scripted",                              // scripted | cinematic | systemic (from VFS folder; derived)
  "mission": "M01",                                  // derived from folder name
  "voice_asset": {"vfs_path": "...", "container": "pakchunk0-Windows.utoc", "class": "HaloAudioVoiceVariations"},
  "entries": [                                       // one per VoiceEvents[] variation
    {
      "index": 0,
      "ce_line_ref": "vo_scr_m01_00460_cryotech#0",  // what mappings point at
      "event": {"package": "...", "event_id": 3768155368},
      "media": {"Spanish(Mexico)": {"evidence": "explicit", "media": [{"media_id": 132700376,
                 "vfs_path": "...", "container": "pakchunk4-Windows.pak", "wem_sha256": "...",
                 "duration_s": 3.629, "sample_rate": 48000, "channels": 1}]},
                "English(US)": {...}, "Spanish(Spain)": {...}},
      "transcription": {"type": "Subtitle", "string_table": "...", "line_key": "...",
                        "metadata": {"Character": "CRYOTECH", "Race": "UN"}},
      "subtitles": {"es-MX": {"namespace": "...", "key": "...", "evidence": "explicit", "text": "…"},
                    "en": {...}, "es-ES": {...}},
      "lipsync": {...}
    }
  ],
  "hops": [ {"hop": "...", "evidence": "..."} ],
  "flags": [],                                       // temp_asset | dlc_mission | no_transcription | multi_variation | ...
  "provenance": {"usmap": "...", "built_at": "...", "tool": "..."}
}
```

- `duration_s` is filled only when the media is actually decoded (on
  demand). Otherwise it is `null`. It is never estimated.
- An asset with no `Transcription`, or a key missing from a culture's
  `.locres`, gets `evidence: "unresolved"` plus a reason, and a flag.
  It never falls back to another culture.
- `temp_mocap_VO`/`metz_*` paths are flagged `temp_asset` and kept, so
  nothing silently disappears.

## 4. MCC catalog — one record per dialogue tag, slots per sample

```jsonc
{
  "schema": "mcc-dialogue-tag/2",
  "mcc_tag": "sound\\dialog\\a10\\a10_350_captkeyes",   // from .lst.bin; identical across languages
  "level": "a10", "sequence": "350", "speaker_from_name": "captkeyes",
  "kind": "scripted",                                     // scripted | flavor | generic (name shape; derived)
  "samples": {
    "spanish": [                                          // the replacement targets
      {"slot_id": "es:A10_350_captkeyes", "index": 30, "name_in_bank": "A10_350_captkeyes",
       "freq": 44100, "channels": 1, "sample_count": 198144, "duration_s": 4.493, "codec": "CELT",
       "evidence": "explicit"}
    ],
    "english": [ {"index": 30, "name_in_bank": "A10_350_CaptKeyes", "...": "..."} ]
  },
  "subtitle": {"key_hash": null, "evidence": "unresolved"},   // blocker B1 (roadmap)
  "provenance": {"fsb_sha256": {"spanish": "ed0f…", "english": "8d07…"}, "built_at": "…"}
}
```

**Slot identity.** `slot_id = "es:" + name_in_bank` of the
**Spanish** bank sample. This is what a mapping replaces. A tag can
have several samples (permutations), and the Spanish bank has fewer
samples than English (5,696 vs 6,093), so slots are **per Spanish
sample, not per tag and not per English sample**.

Two things M2 must verify. If either fails, the fallback
`slot_id = "es:" + mcc_tag + "#" + ordinal` is used and documented:
- name uniqueness within the Spanish bank;
- how permutation samples are named.

`work/mcc/subtitles.jsonl` is kept separately and is never joined to
tags until blocker B1 produces an explicit link.

## 5. User-owned files

### 5.1 `mappings/manual_mappings.json` (committed, IDs only)

```jsonc
{
  "schema_version": 2,
  "pins": {"ce_build": "Meteorite-2607-CU4-c838a8ac", "mcc_spanish_fsb_sha256": "ed0ff3ec…"},
  "slots": [
    {
      "mapping_id": "m-000001",                 // never reused
      "slot_id": "es:<name_in_spanish_bank>",
      "mcc_tag": "sound\\dialog\\a10\\…",        // denormalized for readability/validation
      "match": {                                // the user's cross-game pairing (may be empty)
        "status": "matched",                    // unreviewed | matched | no_equivalent | deferred
        "ce_line_refs": ["<ce_line_key>#<variation>"],   // 0..n, ordered
        "decided_at": "…", "revision": 1
      },
      "audio": {
        "status": "approved",                   // draft | approved | needs_rework
        "source": "ce",                         // ce | ce_concat | keep_original | user_recording
        "ce_language": "Spanish(Mexico)",
        "edit": {"trim_start_s": 0.0, "trim_end_s": 0.0, "gap_s": 0.0},   // planned, applied non-destructively
        "fx_request": null,                     // v1.1: e.g. "radio" (manual flag only, §6)
        "fingerprint": {"ce": [{"ref": "…#0", "media_id": 0, "wem_sha256": "…"}],
                        "mcc": {"index": 30, "sample_count": 198144}},
        "approved_at": "…", "revision": 2
      },
      "subtitle": {
        "status": "draft",                      // draft | approved | needs_rework
        "source": "ce_locres",                  // ce_locres | custom | keep_original | none
        "ce_locres": {"culture": "es-MX", "namespace": "…", "key": "…"},
        "custom_ref": null,                     // key into manual_mappings.local.json when source=custom
        "mcc_key_hash": null,                   // target row in SP_Halo1.bin -- unresolved until B1
        "approved_at": null, "revision": 1
      },
      "notes": ""
    }
  ]
}
```

- **Independence:** `audio` and `subtitle` each have their own source,
  status, approval and revision. Any combination is valid. For example:
  CE audio + custom text, kept Spain audio + CE es-MX text, or CE audio
  + no subtitle change.
- **Unmatched lines:** `match.status = "no_equivalent"` (or `deferred`)
  with `audio.source = "keep_original"` is the default for any slot the
  user hasn't decided. A user can still give such a slot a custom
  subtitle. `user_recording` is reserved for the user's own recordings
  (the path goes in the local file). It's a schema slot only, with no
  tooling in v1.0.
- **Concatenation:** `ce_concat` uses `ce_line_refs` in order, with an
  optional `gap_s`.

### 5.2 `mappings/manual_mappings.local.json` (git-ignored)

```jsonc
{ "custom_subtitles": {"c-000001": {"text": "…", "updated_at": "…"}},
  "user_recordings":  {"r-000001": {"path": "D:/…/take3.wav", "sha256": "…"}} }
```

Custom text stays local by default because it is often derived from
game text.

### 5.3 `mappings/verifications.json` (committed, IDs only)

```jsonc
{ "schema_version": 1,
  "verifications": [
    {"id": "v-000001", "subject": "ce:vo_scr_m01_00460_cryotech#0",
     "checks": ["audio_matches_subtitle"],
     "languages": ["Spanish(Mexico)", "English(US)", "Spanish(Spain)"],
     "fingerprint": {"media_ids": [132700376, 932939327, 518750516]},
     "result": "pass", "by": "user", "at": "2026-10-08",
     "note": "Phase 2B PoC, docs/poc-ce-line-link.md"} ] }
```

The first entry above is the actual PoC verification. It'll be written
to the file once M3 creates it.

### 5.4 Safety rules (enforced by every tool)

1. Tools never set `approved`. Only an explicit user action can,
   separately for `audio` and `subtitle`.
2. **Approved objects are immutable to tools.** On drift (fingerprint
   mismatch after a rebuild or game patch) a tool writes a separate
   `work/reports/drift.json`. Only the user can move an object to
   `needs_rework`, and that bumps `revision`.
3. Atomic writes (temp file → fsync → rename), a backup in
   `mappings/.history/` before every save, and a refusal to save if the
   file's content hash changed since it was loaded.
4. Validators are read-only. Unknown IDs are reported, never deleted.
5. Verifications are append-only.
6. Git history is the second safety net.

## 6. Derived audio (v1.0 conversion, v1.1 effects) — plan only

v1.0 needs **format conversion** regardless of effects. CE media decode
to 48 kHz mono, while the MCC Spanish slots are CELT at 44.1 kHz mono.
The conversion recipe is unknown until blocker B2. Every derived file
is described by a recipe and stored under its own hash:

```jsonc
// work/derived/<output_sha256>/recipe.json
{ "inputs": [{"kind": "ce_media", "wem_sha256": "…", "media_id": 0}],
  "steps": [{"op": "decode", "tool": "vgmstream r2117"},
            {"op": "trim", "start_s": 0.0, "end_s": 0.0},
            {"op": "resample", "to_hz": 44100},
            {"op": "fx", "preset": "radio_v1", "params": {}}],    // v1.1 only, not implemented
  "output": {"sha256": "…", "duration_s": 0.0},
  "created_at": "…", "tool_versions": {} }
```

- v1.1 radio repair: the user flags lines in `audio.fx_request`, and
  the processing step reads the flag. No effect is implemented or
  chosen yet.
- Originals (`.wem`, decoded WAV) are never modified. Changing a recipe
  produces a new hash and a new folder.

## 7. Evidence vocabulary

| Value | Meaning | Trusted for build? |
|---|---|---|
| `explicit` | read from a reference field in game data | yes |
| `explicit:index` | path exists in a container/bank index | existence only |
| `derived:<rule>` | computed or naming convention | only after user confirmation |
| `unresolved` | unknown (with `reason`) | no |

Human checks are **not** an evidence level. They live in
`verifications.json` (§5.3).

## 8. Local matching UI

Unchanged from v1 (stdlib `http.server` on 127.0.0.1, MCC work queue
on the left, CE search on the right, no suggestions or ranking), plus
two v2 changes:
- separate Approve buttons for audio and subtitle;
- a custom-subtitle editor that writes only to the local file.

**Not started.** Gated by milestone M4 in [`roadmap.md`](roadmap.md).

## 9. Risks

See [`roadmap.md`](roadmap.md) §5. The v1.0 blockers are **B1 (MCC
subtitle replacement)** and **B2 (FSB5 rebuild + game acceptance)**.
