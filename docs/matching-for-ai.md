# How matching works: reference for AI agents

**Audience:** AI coding agents working in this repo (and humans who want the precise model).
**Scope:** how an MCC Halo CE dialogue line gets a LATAM (Campaign Evolved es-MX) replacement, from the catalogs to
the decision file to the built game files. Written 2026-10-18 against the code at that date; when this doc and the
code disagree, the code wins. Read the "Rules for agents" section before changing anything under `mappings/`.

---

## 1. The model in one paragraph

There are two read-only **catalogs**: MCC (what the game plays: Spanish/Spain bank samples) and CE (what Campaign
Evolved has: es-MX recordings and subtitles). They never reference each other. The **only** place they meet is the
owner's decision file `mappings/manual_mappings.json`. For each MCC **slot** (one Spanish bank sample) the owner
records a **match** (which CE lines correspond), an **audio** decision (what plays) and a **subtitle** decision (what
text shows), each approved separately. Tools never create matches and never approve. The read-only Suggestions tab
(owner, 2026-10-23, `docs/suggested-matching.md`) scores and ranks candidates; it never writes or pre-fills.
The build (M6) reads only **approved** decisions and writes candidate game files; untouched data stays
byte-identical.

```
work/mcc/catalog/*.jsonl  (MCC slots, read-only)  ─┐
                                                    ├─► Studio (owner decides) ─► mappings/manual_mappings.json
work/ce/catalog/*.jsonl   (CE lines, read-only)   ─┘        (via M4App + mapping_store; SQLite is the source,
                                                              the JSON is its byte-exact export)
mappings/manual_mappings.json (approved only) ─► M6 build ─► sounds_dialogs_spanish.fsb (+ .lst.bin) + SU/SP_Halo1.bin
```

---

## 2. Identifiers

| ID | Form | Meaning | Defined by |
|---|---|---|---|
| `slot_id` | `es:<spanish_sample_name>#<occurrence>`, e.g. `es:A10_010_cryotech#0`, `es:deathviolent%2001#1` | One sample in the **Spanish** bank `sounds_dialogs_spanish.fsb`. The replacement unit. Name keeps the bank's exact casing; `%XX` escapes; occurrence = Spanish bank order. Stable; changes are detected, never renumbered. | MCC catalog (`build_mcc_catalog.py`) |
| `mcc_tag` | `sound\dialog\a10\a10_350_captkeyes` | The **sound** (tag path). One sound has 1..n Spanish samples ("takes" / permutations); see §4. | `.lst.bin` index |
| `ce_line_ref` | `<record_id>#<n>`, e.g. `vo_scr_m01_00460_cryotech#0` | One CE recording variation. | CE catalog (`build_ce_catalog.py`); `SYS` = systemic chatter |
| `mapping_id` | `m-NNNNNN` | One decision object (one per slot). | Studio, `_next_id` |
| `take_id` | `t-NNNNNN` | One added take. **Never reused**, even after removal (DB history). | Studio |
| `custom_ref` | `c-NNNNNN` | A custom subtitle; its text lives only in git-ignored `manual_mappings.local.json`. | Studio |
| `v-NNNNNN` | | A human check in `mappings/verifications.json` (append-only). Not an evidence level. | Owner |

MCC subtitle key = CRC-32/MPEG-2 of the upper-cased tag path (`mcc_loc.loc_key`). **All takes of a sound share one
subtitle entry.** `SU_Halo1.bin` = Latin America table, `SP_Halo1.bin` = Spain table.

Level ↔ CE mission scope: `mappings/mission_map.json` (owner's, e.g. `a10 ↔ M01`). It only filters the candidate
list; it never pairs lines.

---

## 3. The decision file (`manual-mappings/3`)

Schema: `schemas/manual-mappings-3.schema.json`. Top-level keys, always in this order:

```json
{"schema": "manual-mappings/3",
 "pins": {"ce_build": "...", "mcc_steam_buildid": "19905945", "mcc_spanish_fsb_sha256": "..."},
 "slots": [ ...one object per decided slot... ],
 "added_takes": [ ... ],      // optional, never written empty
 "own_sets": [ ... ]}         // optional, never written empty; staged or active (§3.3)
```

### 3.1 A slot decision

```json
{"mapping_id": "m-000545",
 "slot_id": "es:deathviolent%2001#0",
 "mcc_tag": "sound\\dialog\\...\\death_violent",
 "match":    {"status": "matched", "ce_line_refs": ["vo_...#0"], "decided_at": "2026-10-18", "revision": 1},
 "audio":    {"status": "approved", "source": "ce",
              "sources": [{"kind": "ce", "ce_line_ref": "vo_...#0", "language": "Spanish(Mexico)"}],
              "edit": {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0},
              "fingerprint": {...}, "approved_at": "2026-10-18", "revision": 1},
 "subtitle": {"status": "draft", "source": "ce_locres",
              "ce_locres": {"ce_line_ref": "vo_...#0", "culture": "es-MX"}, "custom_ref": null,
              "mcc_key_hash": null, "mcc_key_verification": null,
              "fingerprint": null, "approved_at": null, "revision": 1},
 "radio_effect":       {"needed": false, "set_at": null, "revision": 1},
 "different_but_fits": {"marked": false, "set_at": null, "revision": 1},
 "needs_recording":    {"marked": true, "set_at": "...", "revision": 1},   // optional
 "notes": ""}
```

A slot with **no** entry is undecided: Spain audio and MCC subtitle stay (the v1.0 default).

**`match.status`**: `unreviewed` (no refs) · `matched` (≥1 ref) · `no_equivalent` (no refs) · `deferred`.
`ce_line_refs` is the owner's association list; it is not the audio choice.

**`audio.source`**:

| source | sources | Built by M6? | Notes |
|---|---|---|---|
| `keep_original` | none | yes (sample untouched) | Default. |
| `ce` | exactly 1 `ce` source, which must be in `match.ce_line_refs` | yes | The normal replacement. Language normally `Spanish(Mexico)`. |
| `mute` | none; requires `mute_reason` (1–500 chars); match must be `no_equivalent`; no edit recipe | yes (MCC's own CELT silence, exact original length) | |
| `ce_concat` | exactly 2 `ce` | yes (2026-10-19) | **Join**: part 1 then part 2, each with its own recipe, `gap_s` between (negative = overlap). `audio.edit` is a combine recipe (`audio-combine/1`). `docs/combine-recordings.md` |
| `ce_mix` | exactly 2 `ce` | yes (2026-10-19) | **Play together**: both unedited, the second starting `offset_s` later. Combine recipe too. |
| `user_recording`, `composite` | `r-NNNNNN` refs | **no** | Schema only. |

**`audio.edit`**: the non-destructive recipe (`scripts/common/audio_edit.py`, `audio-edit/1`): trims, cuts with
crossfades, inserted silences, fades, and optional `radio` (`spain`/`english`/`custom`/`*_eco`), `echo`,
`interference` (Victor 933 only). `for_source` binds it to one CE recording; choosing another recording resets it.
`{trim_start_s:0, trim_end_s:0, gap_s:0}` = identity. No per-line gain or speed (removed). The recipe **is part of the
approved audio object**.

**`subtitle.source`**: `keep_original` (MCC text stays) · `ce_locres` (a CE line's text in `es-MX`/`en`/`es-ES`) ·
`custom` (owner text, via `custom_ref`) · `none` (an empty entry; written only if **every** take of the sound has an
approved `none`).

**Owner flags** (`radio_effect`, `different_but_fits`, `needs_recording`): reminders, independent of approvals. Each
change bumps its own `revision`. The "Needs radio effect" flag is never applied to audio; only `audio.edit.radio` is.

### 3.2 Added takes (sound level)

```json
{"take_id": "t-000007", "mcc_tag": "...death_violent", "position": 1,
 "audio": { same object as a slot's audio, source "ce" only },
 "radio_effect": {...}, "notes": ""}
```

Extra CE recordings for a sound, inserted after its Spain takes. The game picks among all takes listed in the
Spanish `.lst.bin` range (proven in game: `v-000020`, `v-000021`). Allowed on **mono sounds** (owner, 2026-10-19:
with or without a SU/SP subtitle entry; before, barks only). Takes share one subtitle: on a subtitled sound without an
own set, the line subtitle decisions decide it (the Studio warns); with one, the set's subtitle (§3.3). Added takes on
scripted story lines are not yet proven in game. Warning above 12 takes.
Same approval rules as a slot's audio; the fingerprint also pins the sound's Spain samples.

### 3.3 Own take sets (sound level)

```json
{"mcc_tag": "...death_violent", "set_at": "2026-10-18"}
```

"Replace every take of this sound": the sound plays **only its added takes**; M6 removes its Spain samples (action
`dropped`) once ≥1 added take is approved and eligible. Same sound rules as added takes. While on, the sound's slots
must have **no** slot decisions (validator error) and the API refuses slot saves. Design:
`docs/custom-take-set-design.md`.

Optional `"subtitle"` (2026-10-19, sounds with a SU/SP entry only): the set's **one** subtitle, shaped like a slot's
subtitle object minus `mcc_key_hash`/`mcc_key_verification` (`keep_original` / `ce_locres` / `custom` / `none`; custom
text in the local file). Same lifecycle as a slot subtitle; the user action names the sound:
`UserAction(approve|needs_rework, <mcc_tag>, "subtitle")`. A set whose subtitle is approved cannot be removed until it
is reworked (off / cancel / undo add that step to their save). Built only while the set is in force and approved.

Two optional fields (2026-10-18, `docs/replacement-set-conversion.md`):
- `"state": "staged"`: a conversion of the sound's own selections is prepared but **not in force**. The line
  decisions still apply and stay editable; the takes it created are never built (`skip`). Absent = active. Ask
  `common/own_set_state.py` (`active_own_tags`, `staged_sets`, `staged_take_ids`); never treat every `own_sets` entry
  as active.
- `"provenance"`: the read-only record of what the set replaced: every line decision body exactly (approvals,
  fingerprints, notes, flags), the earlier added takes, custom-subtitle text hashes, which take came from which
  decisions, and the review codes the owner confirmed. `kind` `conversion` (`cv-…`) or `replace` (the 4th option,
  `rs-…`). `check_transition` refuses any change except setting `activated_at` once.

### 3.4 Local file (git-ignored)

`mappings/manual_mappings.local.json`: `custom_subtitles {c-NNNNNN: {text, updated_at}}` and `user_recordings`.
Text and paths never go into the committed file.

---

## 4. Sounds with several takes (permutations)

This is the part most often misread. **A sound is not a line.** The game plays a *sound* (`mcc_tag`); a sound can
have several recorded *takes*; each Spain take is a separate *slot* with its own decision.

### 4.1 How the game stores and picks takes

- The Spanish index `halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin` has one record per sound:
  `{tag, first_sample_index, sample_count}`. The sound's takes are the `sample_count` **contiguous** samples of
  `sounds_dialogs_spanish.fsb` starting at `first_sample_index`. Each of those samples is one slot:
  e.g. Grunt `...\involuntary\death_violent` → `es:deathviolent%2001#1` (take 1) and `es:deathviolent%2002#1`
  (take 2). Sample names come from the dub studio; the `#n` occurrence is bank order, not the take number.
- Each time the sound plays, the game **picks one take at random from that index range**. Proven in game: the take
  count comes from the Spanish index, not from the map's tag (`v-000021`: 6 takes heard on a 4-permutation tag),
  and the tag's per-permutation skip fraction does not apply to the range (`v-000020`). The exact weighting was
  not measured; treat it as uniform.
- Take counts differ per language: across 1,903 sounds, 329 have fewer Spain takes than English and 200 have more.
  The English sample of "the same take" (`english_index`, matched by ordinal) is only a reference and may not exist.
- **Subtitles are per sound, not per take.** The SU/SP key is the CRC of the tag path, so every take of a sound
  shows the same subtitle. Consequences: the approved subtitle decisions of a sound's takes must agree (different
  texts, or a text next to an approved "keep", is a *conflict*: the key is left unchanged and reported); `none`
  `none`
  (empty entry) is written only when **every** take approved `none`. Since 2026-10-19 extra takes and own sets are
  allowed on subtitled sounds too: without a set the line decisions above govern the key; with a set in force, the
  set's one subtitle does.

### 4.2 The three ways to handle a multi-take sound

| Mode | Data | What the game plays | Takes count | Who decides what |
|---|---|---|---|---|
| **A. Per take** (default) | one `slots[]` decision per Spain take | each Spain take replaced / kept / muted on its own | = Spain's | each line, independently (audio and subtitle) |
| **B. Spain + added takes** | slot decisions **plus** `added_takes[]` | Spain's takes (as decided in A) **plus** the added CE recordings | Spain's + added | each line for Spain's places; each added take on its own (approve per take) |
| **C. Own take set** ("replacement set") | `own_sets[]` entry + `added_takes[]`; **no** slot decisions for the sound | only the added takes; Spain's samples are removed | = added takes | the sound only (each added take approved on its own) |
| *C staged* | A's slot decisions + `added_takes[]` + `own_sets[]` entry with `state: "staged"` | **as A/B** (the staged takes are not built) | as A/B | each created take approved on its own; then the owner switches |

Rules that follow from the table:
- In A and B a **muted** Spain take stays in the rotation as silence (the game can pick it). C exists to avoid that:
  it removes Spain's takes instead.
- B and C are allowed for **mono sounds** (`M4App.take_rule`), with or without a SU/SP subtitle entry (owner,
  2026-10-19; the validator codes `added_take_on_subtitled_sound` / `own_set_on_subtitled_sound` are gone). A
  subtitled sound in C has one subtitle per set (`own_sets[].subtitle`); conversion prefills it as a draft only when
  every Spain take's subtitle decision agrees, and the switch needs it approved.
- Two ways into C:
  - **4th audio option** (`own_set_on`): new recordings; the sound's slot decisions are cleared (owner-confirmed;
    approved ones `needs_rework` then removed, in one save) and recorded in the set's provenance.
  - **Conversion** (`docs/replacement-set-conversion.md`): the slots' **selected** audio becomes the takes. Equal
    specifications (CE line, language and effective recipe) are merged, so take 1 → ce1, take 2 → ce2, take 3 → ce1
    gives [ce1, ce2]. It is staged first (A stays in force), every take is approved by the owner (approvals are never
    copied), then switched in one save.
- Back from C:
  - `own_set_off` leaves the lines undecided and keeps the added takes as B.
  - **Undo** (`convert/revert_preview` then `convert/revert`, sets with a provenance) restores the recorded slot
    decisions exactly, approvals included, through the store's narrowly scoped `restore` action (only for the exact
    recorded object of the set the same save removes, and only while its fingerprint still matches), and removes the
    takes the record created. Conflicts are shown before anything changes. Local text comes back from the git-ignored
    `mappings/take_set_recovery.local.json`; newer local text is never overwritten.
  - **Approve unchanged converted takes** (`convert/approvable` then `convert/approve_unchanged`): the owner's new
    approval of staged takes whose every source decision is approved, unchanged, drift-free and buildable, with the
    same specification and no review point. It is not a copy of slot approvals.
- In C, the build keeps Spain's takes until **at least one** added take is approved and eligible (never an empty
  sound). The validator warns `own_set_without_approved_take` meanwhile.
- `position` orders added takes in the bank (after Spain's in B; alone in C). It does not change the odds.

### 4.3 What the build does with takes

- Mode A only: samples are replaced in place; the bank keeps its sample count; **`.lst.bin` is not written**.
- Any approved added take (B) or own set with an insertable take (C): `insert_takes` rebuilds the bank with the
  sound's range = [kept Spain samples] + [inserted takes] (C: inserted takes only; Spain's slots get action
  `dropped`), every later sample shifts, and the Spanish `.lst.bin` is rewritten with the new starts and counts.
  The bank and the index are **installed and restored together** (`m6_install.py`). Checks prove every other
  sample is byte-identical at its new place, the index is contiguous and covers the bank, and each sound resolves
  to its old samples first (or, in C, only to its takes).
- Slot IDs never change when samples shift: they are names + occurrence, not bank positions.
- Status in game: added takes proven with experiment builds (`v-000020`, `v-000021`); a real Studio build with
  added takes, and a build that removes samples (C), are still the owner's pending checks.

### 4.4 Where takes appear in the Studio

- MCC list: each multi-take row shows **Spain take n/N** and a bracket joins rows of the same sound; `+N` = added
  takes; **own set a/b** = own set with a approved of b takes (the row's M/A/S pills then show the sound's state:
  M ✓, A from the takes, S ⊘ "no subtitle entry").
- Line panel: "Spain take n of N of this sound"; **Takes of this sound** lists Spain's takes (with each one's
  decision; crossed out in C) and the added takes (play, approve, Needs rework, reorder, remove; *Add as extra
  take* = the recording focused on the right; *Add several takes…* = multi-select picker).
- Replacement audio, option 4 **Replace every take of this sound** = mode C: lists every Spain take it replaces
  (playable), the takes already added, a multi-select picker, and *Back to Spain's takes*. While C is on, the
  line's own options and the save/approve bar are replaced by the sound's status. Disabled while a conversion is
  staged.
- *Takes of this sound* header: the mode badge (per take / Spain + added takes / replacement set / replacement set
  staged) and a summary ("3 original MCC takes → 2 replacement takes"). It lists the original takes (playable,
  reference) and the replacement or added takes. `ReplacementSet.vue` handles *Preview a replacement set from my
  selections* → stage (review codes ticked one by one) → *Switch* / *Cancel*, and *Undo the replacement set*.
- **Take sets** page (`TakeSetsView.vue`): every multi-take sound previewed, filters by status, bulk stage (ready
  only) and bulk switch (all takes approved), each owner-confirmed and all-or-nothing.

---

## 5. Status, approval and protection rules

Each of `audio` and `subtitle` (and each added take's `audio`) has its own lifecycle:

```
 draft ──(owner "approve" action)──► approved ──(owner "needs_rework" action, revision+1)──► needs_rework
   ▲                                                                                              │
   └───────────────────────────── edits allowed again ◄─────────────────────────────────────────┘
```

- **Approval** requires an explicit `UserAction("approve", id, field)`. On approval the server stores
  `approved_at` and a **fingerprint** of what was approved (`project_validation.audio_fingerprint` /
  `subtitle_fingerprint` / `added_take_fingerprint`: the MCC sample identity + data hash, the CE media IDs, the
  custom text hash...).
- **Approved objects are immutable.** The only allowed change is `needs_rework` with `revision + 1`
  (`mapping_store.check_transition`). An approved slot cannot be deleted; an approved take cannot be removed.
- **Drift:** when a catalog changes so the current fingerprint ≠ the approved one, the decision is reported in
  `work/reports/drift.json` and M6 refuses to build it. Nothing rewrites the approval.
- `match` has no approval; it has `revision` + `decided_at`.
- Audio and subtitle are independent: approving one never touches the other.
- Turning an own set on (4th option) or switching a staged conversion is the one place decisions get removed. It
  runs as the owner's confirmed action, as **one** save of two checked steps (`mapping_store.save_sequence`):
  (1) every approved object of the sound's slots gets `needs_rework` (a user action, revision + 1), (2) the slots
  are removed. The removed bodies are kept in the set's provenance. The store's rules are unchanged. Before
  2026-10-18 these were two separate saves; a failure between them could leave decisions downgraded.

---

## 6. Write path (who may write what)

```
Vue Studio (frontend/src)  ──HTTP──►  scripts/ui/m4_server.py  ──►  scripts/ui/m4_app.py (M4App)
                                                                       │ validate (project_validation)
                                                                       ▼
                                                    scripts/common/mapping_store.py   ◄── ONLY writer
                                                       │ check_transition (approval rules), schema
                                                       ▼
                                   mappings/manual_mappings.db (SQLite, git-ignored, source of truth, v6)
                                                       │ export, byte-identical
                                                       ▼
                                   mappings/manual_mappings.json (committed)
```

- `mapping_store.save(path, new_doc, loaded_sha256, user_actions=...)` refuses a stale hash (`StaleError`), a
  forbidden transition (`ProtectedError`) or a schema error (`StoreError`). It keeps per-row history in the DB
  (`slot_history`, `added_take_history`, `own_set_history`). See `docs/mapping-storage.md`.
- Concurrency: a line save names the line's own version (`loaded_slot_sha256` = `slot_version()`), so saves of
  other lines don't make it stale; take requests name the sound's version (`loaded_takes_sha256` =
  `takes_version()`, which covers the sound's added takes and own-set entry). Requests that also consume the line
  decisions (the 4th option, conversions) name `loaded_sound_sha256` = `sound_version`
  (`take_set_conversion.sound_inputs`: slots, takes, set, custom texts, catalog facts, eligibility). 409 = changed
  elsewhere.
- A hand-edited JSON is never read back silently: the owner imports it explicitly (Data page,
  `mapping_store.preview_import` / `import_json`).

### 5.1 API (decision-related)

| Endpoint | Body | Does |
|---|---|---|
| `GET /api/slots?level=&status=&q=` | | MCC list rows (decision summary, `added_takes` count, `own_set` status) |
| `GET /api/slot?id=` | | One slot: MCC texts, decision, the sound's takes (`sound`) |
| `GET /api/ce?mission=&q=&subs=&hide_used=` | | CE candidates (catalog order; search filters only, never ranks) |
| `GET /api/suggest?level=&scope=&show=` | | Suggestions tab: scored CE lines per sound (MCC EN vs CE EN); read-only |
| `POST /api/suggest/rerank` | `{mcc_tag, scope}` | Claude re-ranks that sound's shortlist (admin remotely; cached); read-only |
| `POST /api/save` | `{slot_id, loaded_slot_sha256, match?, audio?, subtitle?, radio_effect?, different_but_fits?, needs_recording?, notes?, actions?}` | Saves one slot; `actions` = `[{action: approve\|needs_rework, field: audio\|subtitle}]` |
| `POST /api/takes/save` | `{mcc_tag, loaded_takes_sha256, take_id?, audio?, actions?}` | New take (no `take_id`) or change/approve/rework one |
| `POST /api/takes/add_many` | `{mcc_tag, loaded_takes_sha256, audio_list}` | Several new draft takes in one save |
| `POST /api/takes/approve_many` | `{mcc_tag, loaded_takes_sha256, take_ids, confirm: true}` | The owner's confirmed approval of exactly the listed takes, one save (all or nothing); never called by agents |
| `POST /api/takes/move` / `remove` | | Reorder / remove (not while approved) |
| `POST /api/takes/own_set_on` | `{mcc_tag, loaded_takes_sha256, loaded_sound_sha256, clear_mapping_ids, audio_list?, subtitle?}` | Replace every take: clear the listed slot decisions (recorded), turn the set on, add drafts |
| `POST /api/takes/own_set_off` | `{mcc_tag, loaded_takes_sha256}` | Back to Spain's takes (lines undecided; use undo to restore; an approved set subtitle is reworked in the same save) |
| `POST /api/takes/set_subtitle` | `{mcc_tag, loaded_takes_sha256, subtitle?: {source, ce_locres?, custom_text?} \| null, actions?: [{action: approve\|needs_rework}]}` | The set's one subtitle (subtitled sound with a staged or active set) |
| `GET /api/takes/convert/preview?mcc_tag=` / `inventory?level=` | | Read-only conversion preview of one sound / every multi-take sound |
| `POST /api/takes/convert/stage` | `{items: [{mcc_tag, token, acknowledged?}], bulk?, confirm: true}` | Staged set + draft takes; line decisions untouched |
| `GET /api/takes/convert/approvable?mcc_tag=` | | Read-only: staged takes "approve unchanged" would approve, and the excluded ones with reasons |
| `POST /api/takes/convert/approve_unchanged` | `{mcc_tag, loaded_sound_sha256, take_ids, confirm: true}` | New approvals of exactly the listed takes, or none |
| `POST /api/takes/convert/activate` | `{items: [{mcc_tag, loaded_sound_sha256}], confirm: true}` | The switch (every take approved and buildable; set and decisions as recorded) |
| `POST /api/takes/convert/cancel` | `{mcc_tag, loaded_sound_sha256}` | Cancel a staged one |
| `GET /api/takes/convert/revert_preview?mcc_tag=&rework_drifted=1` | | Read-only: the undo's plan and conflicts, with its token |
| `POST /api/takes/convert/revert` | `{mcc_tag, token, rework_drifted?, confirm: true}` | Undo exactly as previewed |

---

## 7. The Studio flow (what the owner does)

Matching page: **left** = MCC lines of a level (pills M/A/S = match, audio, subtitle state; own-set lines show the
sound's takes state); **middle** = the open line; **right** = CE candidates for the level's mission scope.

1. Open an MCC line; listen to Spain (ES) and English (EN).
2. Find the CE line on the right (search ID/EN/es-MX text). Pressing **Use this recording** (`s`) is the explicit
   choice: it adds the ref to `match.ce_line_refs`, sets `match.status = matched`, `audio.source = ce`. If the
   subtitle is still the untouched default and the CE line has es-MX text, the draft **proposes** that subtitle
   (`proposeSubtitle`); the owner can change it. Nothing is saved yet.
3. **Replacement audio** has 6 options:
   1. Keep Spain's audio · 2. Use a matched CE recording · 2b. **Join two matched recordings** (`ce_concat`) ·
   2c. **Play two matched recordings at the same time** (`ce_mix`) · 3. Mute in game (reason required) ·
   4. **Replace every take of this sound** (own take set; sound level, see §3.3 and §4).
   2b/2c need two matched lines; their editor is `CombineEditor.vue` (`docs/combine-recordings.md`).
4. Optional: Audio editing (recipe), flags, notes, subtitle choice.
5. **Save draft** (never approves) → **Approve audio** / **Approve subtitle** / **Approve both** (each confirmed).
6. To change an approved object: **Needs rework**, edit, save, approve again.

"Takes of this sound" (below the audio choice) shows the sound's Spain takes and its added takes, with
add one / **Add several takes…** (multi-select picker) / approve / rework / reorder / remove.

Client rules mirror the server for usability only (`frontend/src/matching/draft.ts`: `draftProblems`,
`canApprove`, `buildSaveBody`); **the server is the authority**.

---

## 8. From decisions to game files (M6)

`scripts/common/m6_build.py` (pure plans) + `scripts/build/m6_build.py` (CLI). Per slot in the chosen levels:

| Action | When |
|---|---|
| `replace` | audio approved, source `ce`, mono slot, one resolved es-MX media, no drift, valid recipe for that source |
| `mute` | audio approved, source `mute`, match `no_equivalent`, no recipe, no drift |
| `dropped` | the slot's sound has an own set with ≥1 insertable take (`own_set_drops`) |
| `keep_original` | no decision, not approved, or approved keep Spain |
| `not_eligible` | unsupported source, stereo, drift, unresolved media, bad recipe, duplicate target (reported) |

Added takes (`plan_inserts`): approved + eligible → `insert` after the sound's Spain samples (or as the whole sound
when dropped); the Spanish `.lst.bin` is then rewritten and installed with the bank as one unit.
Subtitles (`subtitle_plan`): approved decisions only, per key, per table (SU and SP independently); takes of one
sound that disagree = conflict, left unchanged; keys are never added. A sound whose own set is in force: the set's
approved subtitle is the key's outcome (row `own set <tag_name>`); not approved = excluded, MCC text stays.
Every CE replacement goes through the same render as the Studio preview: ffmpeg 44.1 kHz → recipe → level stage
(`config/audio_export.json`) → CELT 0.11 **`fmod` profile** (never `default`: it crashed MCC, `v-000017`).
`m6_install.py` refuses a build whose built lines no longer match the current approved decisions.

---

## 9. Rules for agents (do not violate)

- **Never** create, change, approve or rework decisions in `mappings/` yourself; never pick CE↔MCC pairs, never
  pre-fill or auto-match. Matching is manual only. The Suggestions tab's scores and Claude rankings are the owner's
  reading aid, never a decision: don't turn them into saves. Never turn own sets on, add takes or mute lines yourself;
  never stage, switch, cancel or undo a replacement set on the real mappings (the read-only
  `scripts/validate/take_set_inventory.py` is fine).
- Write `manual_mappings.json` only through `mapping_store` (and only from code paths driven by an owner action).
  Never edit the JSON or the SQLite DB by hand. Run `python scripts/validate/validate_project.py` (read-only) before
  any commit that touches `mappings/`.
- A migration that changes approved objects needs explicit owner authorization and must prove it changes only the
  intended fields (see `docs/migrations/`).
- Never pass `--accept-id-changes` to the MCC catalog builder; the owner reviews ID changes.
- `verifications.json` is append-only and owner-reported; never invent entries or claim in-game results.
- Never install builds, launch MCC or drive the Build & Test install API against the real game.
- Tests must use disposable roots (`tests/` fixtures, `scripts/ui/e2e_fixture.py`). The browser tests copy the live
  data; they assert the real mappings are unchanged.
- Opening the real DB with newer code upgrades it (additive); a running older Studio then refuses it. Don't run
  tools against the live `mappings/` while the owner's Studio is running old code.
- No game audio or binaries in git; CE content is never committed or redistributed.

---

## 10. Where to look

| Topic | Code | Doc |
|---|---|---|
| Schema | `schemas/manual-mappings-3.schema.json` | `docs/dialogue-catalog-design.md` |
| Store, approval rules | `scripts/common/mapping_store.py`, `mapping_db.py` | `docs/mapping-storage.md` |
| Validator, fingerprints, drift | `scripts/common/project_validation.py` | |
| Studio backend | `scripts/ui/m4_app.py`, `m4_server.py` | `docs/m4-matching-ui-design.md` |
| Studio frontend | `frontend/src/views/MatchView.vue`, `components/match/*`, `matching/draft.ts`, `composables/useMatch.ts` | `docs/m4-user-guide.md` |
| Edit recipes | `scripts/common/audio_edit.py` | `docs/radio-filter.md`, `docs/victor933-interference.md` |
| Mute | | `docs/mute-language-permutations.md` |
| Added takes / own sets | `AddedTakes.vue`, `TakePicker.vue`, `WholeSoundReplace.vue` | `docs/added-takes-design.md`, `docs/custom-take-set-design.md` |
| Replacement-set conversion | `scripts/common/take_set_conversion.py`, `own_set_state.py`, `ReplacementSet.vue`, `TakeSetsView.vue`, `scripts/validate/take_set_inventory.py` | `docs/replacement-set-conversion.md` |
| Suggestions (read-only) | `scripts/common/suggest.py`, `suggest_ai.py`, `SuggestView.vue` | `docs/suggested-matching.md` |
| Build / install | `scripts/common/m6_build.py`, `scripts/build/m6_build.py`, `m6_install.py` | `docs/m6-build.md` |
| Tests | `tests/test_m4.py`, `test_added_takes.py`, `test_take_set_conversion.py`, `test_mute.py`, `test_mapping_*`; `npm run test:workflow`, `test:takes`, `test:take-sets`, `test:mute` | |
