# Two recordings in one replacement: join or play together (owner, 2026-10-19)

**For:** the owner and agents. **Status:** built and tested offline: `tests/test_combine_recordings.py` (including
preview == build parity) and `npm run test:combine` on disposable data. Not checked in game.

## 1. What it does

Two new choices under **Replacement audio** for one MCC line (line decisions only; added takes and replacement sets
still use one recording per take):

| Choice | Source | What plays | What you control |
|---|---|---|---|
| **Join two matched recordings (one after the other)** | `ce_concat` | recording 1, then recording 2 | each part's own edits (trims, cuts, inserted silences, fades) on its own waveform; the **gap** between them (positive = silence, 0 = right after, negative = part 2 starts before part 1 ends and both play during the overlap) |
| **Play two matched recordings at the same time** | `ce_mix` | both at once | the **start offset** of the second (0 = together, positive = it starts later, negative = the first starts later); both play unedited |

Both:
- use Campaign Evolved recordings only, and both must be matched lines;
- use one language, applied to both;
- take a radio filter and an echo **on the combined result** (the owner's choice).

There is no volume control per recording (owner's choice; per-line gain was removed 2026-10-09). Where the two add up
past the peak ceiling (-1 dBFS), the combined audio is lowered just enough, linearly, and the render says so ("lowered
by X dB where the recordings add up"). This is the same rule as the existing effects trim. Then the usual build-level
stage applies (global gain or match Spain), with the radio clicks if the radio filter has them, then CELT `fmod`.

Choosing other recordings, swapping their order, or switching between join and play together starts the recipe again
(unedited parts, no gap, no offset). A recipe never silently moves to other recordings; the server enforces the same
rule.

## 2. Decision format

`audio.source` is `ce_concat` or the new `ce_mix` (schema enum; additive, no migration). `audio.sources` holds
exactly the two CE lines, in order. `audio.edit` holds the **combine recipe** (`audio-combine/1`,
`schemas/manual-mappings-3.schema.json` `$defs/edit_combine`):

```json
{"engine": "audio-combine/1", "mode": "concat",
 "for_sources": [{"ce_line_ref": "a#0", "language": "Spanish(Mexico)"}, {"ce_line_ref": "b#0", "language": "Spanish(Mexico)"}],
 "parts": [{...audio-edit/1 recipe for a...}, {...for b...}], "gap_s": -0.2,
 "radio": {...}, "echo": {...}}
```

An overlay (`"mode": "mix"`) has `offset_s` instead of `parts` / `gap_s`.

`audio.edit` is now either one recording's recipe (`$defs/edit_recipe`, unchanged: the move was proven equivalent)
or this one (`oneOf`). The radio filter and echo definitions moved to `$defs/radio` and `$defs/echo`; their rules did
not change.

The recipe is part of the approved audio object, so the usual rules apply: the fingerprint pins both CE recordings,
it is immutable once approved, and changes go through Needs rework.

## 3. Code

| What | Where |
|---|---|
| Rules, render (pure) | `scripts/common/audio_combine.py`: `normalize`, `problems`, `summary`, `render`. It reuses `audio_edit.edit_stage` (a part's edits) and `audio_edit.finish` (effects, level, clicks, 16-bit). `audio_edit.render` was split into those stages with byte-identical output (checked on a baseline of 8 renders) |
| Pipeline | `audio_pipeline.render_combined` / `derive_combined` (both recordings converted, combined, encoded; `recipe.json` lists both sources) |
| Studio | `M4App._normalize_combined` (save), `POST /api/edit/preview_combined`. UI: two options in `AudioDecision.vue` with first/second recording selects; `CombineEditor.vue` (two part editors reusing `AudioEditor.vue` with `partOnly`, the gap or offset, the effects on the result, the rendered result); `useEditPreview` renders it automatically as B in Listen and compare |
| Build (M6) | `m6_build._plan_combined`: `replace` when approved, mono, both lines resolved, no drift, a valid recipe of the right mode for exactly those two. `compare_plans` also compares both sources' media, so a changed second recording makes `m6_install.py` refuse the old build. The CLI renders it with `derive_combined` |
| Validator | `combine_needs_two_lines`, `combine_recipe_missing`, `combine_recipe_mode`, `invalid_audio_edit`; a combine recipe on another source is `audio_edit_unsupported_source` |
| Not covered | replacement-set conversion: a join or overlay is not one recording, so `take_set_conversion` reports it `unsupported_source` (blocked) |

In a join, each part's editor has its own waveform, undo history and keyboard shortcuts. The shortcuts act on the
part last clicked or focused (outlined), never on both.

## 4. Limits

- Two recordings only, and the same language for both.
- No per-recording volume. An overlay plays both unedited.
- Not available for added takes or replacement-set takes.
- Not checked in game. Longer or shorter samples are already proven to play (E1b, E3); timing against cutscenes is
  part of each in-game test.
