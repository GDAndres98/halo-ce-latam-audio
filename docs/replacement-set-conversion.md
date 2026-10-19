# Replacement sets from existing selections (owner, 2026-10-18/19)

**For:** the owner and agents changing the takes code. **Status:** built and tested offline on disposable data
(`tests/test_take_set_conversion.py`, `npm run test:take-sets`). **Not applied to the real mappings**: staging,
approving, switching and undoing are the owner's actions. Not checked in game: a build that removes Spain samples is
still the owner's pending check (`docs/custom-take-set-design.md` §5).

## 1. What it is for

A multi-take sound (e.g. a Grunt death with 3 Spain takes) used to be matched take by take. When several takes got the
same recording, the sound played that recording more than once in its rotation. A **replacement set** works at the
sound level:

```
per take (before)            replacement set (after)
Spain take 1 -> ce1          the sound -> [ce1, ce2]
Spain take 2 -> ce2          "3 original MCC takes -> 2 replacement takes"
Spain take 3 -> ce1
```

It is **not a new model**. A replacement set is the existing own take set (`own_sets` + `added_takes`,
`docs/custom-take-set-design.md`). What is new:
- a way to build one **from the selections already made**: Preview → Stage → (approve) → Switch;
- a staged state;
- a recovery record;
- an undo that restores the earlier behaviour.

Eligibility is unchanged: mono sounds without a SU/SP subtitle entry (`M4App.take_rule`). Nothing switches a sound to
another mode on its own.

## 2. Modes

| Mode (`sound.mode`) | Data | Plays |
|---|---|---|
| `per_take` | line decisions | each Spain take as decided |
| `spain_plus_added` | line decisions + `added_takes` | Spain's takes (as decided) + added takes |
| `replacement_set_staged` | line decisions + `added_takes` + `own_sets` entry with `state: "staged"` | **as before**: staging changes no build |
| `replacement_set` | `own_sets` entry (no `state`) + `added_takes`; no line decisions | only the set's takes; Spain's samples removed |

`common/own_set_state.py` answers which sets are in force (`active_own_tags`, `staged_sets`, `staged_take_ids`);
every consumer (store, validator, build planner, Studio) asks it.

## 3. Conversion rules

- **Grouping:** by the exact `mcc_tag`.
- **What becomes a take:** only audio the owner selected: `audio.source = "ce"` with exactly one CE line. A match
  without selected audio never does (`match_only`). Nothing is inferred, ranked or paired.
- **One take per specification:** two selections are one take only when `[ce_line_ref, language, effective recipe]`
  is equal. The effective recipe is the whole `audio.edit` (trims, cuts, silences, fades, `radio` with clicks and
  presence, `echo`, `interference`, `for_source`) minus `gap_s`. The same recording with different trims or effects
  stays two takes.
- **Duplicates are removed on purpose.** The old take count and the old playback odds are not kept.
- **Order:** the sound's existing added takes keep their IDs and positions. New takes follow, in the order of the
  first Spain take (bank order) that selected them.
- **Existing added takes** join the set unchanged. A selection equal to one reuses it.
- **New takes** are drafts:
  - The recipe is copied exactly.
  - `radio_effect.needed` is set if any merged decision had it.
  - Notes are copied only when the merged decisions agree.
  - IDs come from `used_take_ids` (current and history) and are never reused.

## 4. The preview and its review points

`take_set_conversion.plan_sound` classifies every Spain take:
- **blocked:** `unsupported_source`, `unresolved_media`, `invalid_recipe`, `gap_on_one_line`, `conflicting_decision`,
  `duplicate_decision`, `nothing_selected`.
- **review:** `undecided_take`, `keep_original`, `mute`, `match_only`, `needs_rework_source`, `approved_drift`,
  `subtitle_text`, `custom_subtitle_missing`, `needs_recording`, `radio_flag_conflict`, `notes_differ`.
- **info:** the rest.

Sounds with review points are staged **one by one** from the line panel, each point ticked. A bulk stage takes only
`ready` sounds.

The preview token (= `sound.sound_version`) hashes everything a conversion reads:
- the sound's line decisions, added takes and own-set entry;
- the custom subtitle texts;
- its Spain samples' catalog facts;
- its eligibility;
- the CE catalog facts of the lines it names.

## 5. Staged until the switch: proven build-neutral

| Point | Line decisions | Staged takes | Earlier added takes | Build |
|---|---|---|---|---|
| Before | in force | none | normal (`insert` when approved) | as decided |
| Right after Stage | in force | drafts, `skip` | **unchanged**, still `insert` | **identical** |
| Some staged takes approved | in force | `skip` (staged) | unchanged | **identical** |
| All approved, before Switch | in force | `skip` (staged) | unchanged | **identical** |
| After Switch | removed (in the record) | `insert` | `insert` (part of the set) | Spain samples `dropped`, set inserted |

Only the takes a staged record **created** are held back (`staged_take_ids`, checked in `plan_inserts`).
`own_set_drops` and `plan_audio` treat a staged set as not in force, so Spain's slots keep their decisions.

Proven by `BuildNeutralTests.test_staged_takes_never_reach_the_build_until_the_switch`, which compares the full
effective plan (each slot's action, audio and recipe, the inserted takes, the dropped sounds) at the four points. The
sound has an approved added take from before, and that take keeps being inserted.

**Cancel** (staged) removes the created takes, approved ones through an explicit Needs rework step in the same save,
and drops the staged set. The line decisions were never touched. After cancelling with every take approved, the
decisions file is byte-identical to before staging and the plan is equal
(`test_cancel_after_every_take_is_approved_returns_to_the_pre_stage_state`).

## 6. "Approve unchanged converted takes" (owner decision 2026-10-19)

An owner-confirmed batch action in the staged state. It is a **new** approval of each listed take. It does not copy
any slot approval object.

`take_set_conversion.approvable()` lists each created take as included or excluded, with its source decisions (slot,
approval date) and, when excluded, every reason. A take is included only when **all** of these hold:
1. The take still exists, is a draft at revision 1, and its specification equals the one recorded at staging
   (`provenance.takes[].spec_sha256`). That means it was not edited since staging.
2. Every contributing decision is still in force, unchanged since staging, with **approved** audio.
3. Each of those approvals is still valid:
   - its fingerprint equals the current one (no drift);
   - the build would replace that line with it (`plan_audio` → `replace`: resolved media, valid recipe for that
     recording, mono).
4. Each contributing decision selects exactly the take's specification.
5. No review point (or blocked code) is attached to any contributing decision. The contributors agree on "needs radio
   effect" and on notes.
6. The sound is still eligible.

One approved contributor never stands in for another. A take merged from an approved and a draft (or Needs rework)
decision is excluded.

**Confirm:** the page shows the list. The confirmation names the takes and their sources. The server then:
- recomputes everything under the save lock;
- requires the sound version the page had **and** an approvable list equal to the one confirmed, or nothing is
  approved (no partial batch);
- approves each take with an explicit user `approve` action, today's date and a fresh `added_take_fingerprint`.

Each history row carries the reason `take-set:approve-unchanged:<record>`. The Studio audit log records the take IDs.

## 7. Switch readiness (strict) and what happens later

`switch_problems()` must be empty. It checks:
- the sound is still eligible;
- the line decisions equal the recorded ones;
- the set holds exactly the recorded takes (none added or removed since staging), each with the specification
  recorded at staging;
- every take is approved **and buildable now**: `plan_inserts` → `insert` on the sound as if switched. That covers
  resolved media, a valid recipe for its recording, no drift, mono and no subtitle entry. "Approved" alone is not
  ready.

Any problem stops the switch with the full list (409), and nothing changes. The switch is one save:
1. approved line objects become Needs rework (user actions);
2. the line decisions are removed, `state` is removed and `activated_at` is set.

It changes the decisions file and therefore what the next build produces. It never touches installed game files
(`test_switch_changes_the_decisions_only` compares every file outside `mappings/`). Building and installing stay
separate owner actions on Build & Test.

**After the switch, the readiness check protects nothing further.** Every build re-plans from the current decisions:

| Later event | Build (`plan_inserts` / `own_set_drops`) | Reported |
|---|---|---|
| A set take marked Needs rework | that take is `skip` (left out); the sound plays its other takes; Spain's samples stay dropped | the take's badge in *Takes of this sound*; "The next build leaves out N of M take(s)" under the set; the build CLI's "added takes: … not approved" line |
| A set take drifts (recording or Spain samples changed since its approval) | that take is `not_eligible` (left out), the same way | "changed since approval" badge; the same notice; validator `approved_fingerprint_drift`; the build lists it under own take sets |
| No take of the set left buildable | the sound is **not** dropped: Spain's **own** recordings play (`keep_original`). The old CE line replacements do not come back | the notice says so; validator `own_set_without_approved_take` when none is approved |

The build does not block on these. `m6_install.py` refuses to install a build whose inserted takes or dropped samples
no longer match the current plan.

## 8. The record and the local recovery snapshot

`own_sets[].provenance` (committed, read-only for the store; only `activated_at` may be set once):
- `slots`: every line decision exactly (approvals, fingerprints, revisions, notes, flags, match, subtitle);
- `added_takes`: the earlier added takes;
- `custom_subtitles`: `custom_ref` + text hash;
- `takes`: take ID, created/existing, source mapping IDs and `spec_sha256`;
- `acknowledged`: the review codes ticked.

The 4th option writes one too (`kind: "replace"`).

**Local-only data** (custom subtitle text, user recording paths) never goes in the committed file. When a record's
decisions name any, Stage and the 4th option first write a snapshot to git-ignored
`mappings/take_set_recovery.local.json`. Schema: `take-set-recovery-1`. It is stored as a database document with its
own history and holds, per record ID:
- the texts with their SHA-256;
- the paths with their hashes;
- refs that were already missing.

Records are only added, never changed. Integrity is checked on use: snapshot hash = text = the record's hash.

**Operational vs historical metadata** once a set is in force:

| Kept for history only (in the record; shown in the record list and the Undo preview) | Still operational (surfaced) |
|---|---|
| match refs, subtitle decisions, approvals and fingerprints, revisions, `different_but_fits`, acknowledged codes | **needs a new recording** and **needs radio effect** of an archived decision: the line's row shows the flag (`archived_reminders`), the *recording* / *radio* list filters find it, the level counters count it, and *Takes of this sound* lists "Reminders from the replaced line decisions" with the notes. No merge policy: each reminder is shown per original line |

## 9. Undo: restores the earlier behaviour, after a preview

`revert_plan()` plans everything first, and `GET /api/takes/convert/revert_preview` shows it. Nothing changes until
the owner confirms that exact plan (token = plan + sound version); any change in between refuses.

**Restores:**
- the previous mode;
- every recorded line decision **exactly**, approvals included;
- missing local text, from the recovery snapshot.

**Removes:** the takes the record created (approved ones through Needs rework in the same save). Their history stays
and their IDs are never reused.

**Leaves as they are now:** the sound's earlier added takes (a later change to them is reported, not undone).

With unchanged inputs, the effective build plan after Undo equals the original one, including earlier approved added
takes (`test_round_trip_restores_the_original_effective_state`: original → Stage → approve → Switch → Undo).

**How approvals come back:** a narrowly scoped store action, `UserAction("restore", mapping_id, field)`
(`mapping_store.check_transition`). It is accepted only when all of these hold:
- the decision does not exist before;
- its object equals, byte for byte, the one in the record of a set that the **same** save removes;
- it is for the same slot and sound.

It cannot approve anything else, cannot be used while the set stays, and cannot carry a changed body
(`test_restore_is_only_for_the_record_being_undone`). Restoring also needs the approval to be valid **now**: each
restored fingerprint must equal the current one.

**Conflicts** (shown in the preview; nothing changes while any remain):

| Code | When | Way out |
|---|---|---|
| `take_added_after` | a take joined the set after it was made | remove it, or keep the set |
| `slot_not_in_catalog` / `slot_decided` | a recorded Spain take vanished, or has a decision now | resolve by hand |
| `mapping_id_in_use` | the recorded ID belongs to another line (new IDs now skip recorded ones) | resolve by hand |
| `approval_drift` | a recorded approval no longer matches the catalogs (or the local text it pinned) | the owner may tick "bring the drifted decisions back as Needs rework instead" (a new preview and token): only those come back as Needs rework, the rest exactly |
| `local_text_changed` | local custom text (or a recording path) differs from the snapshot | never overwritten; restore the text by hand, or keep the set |
| `local_text_unrecoverable` | the text is missing and the snapshot cannot restore it | resolve by hand |
| `custom_ref_in_use` | another line uses the recorded custom ref | resolve by hand |

Sets made before 2026-10-18 have no record and no Undo; nothing tries to recover them automatically.

## 10. Same checks on the 4th option

*Replace every take of this sound* (`own_set_on`) stays an immediate replacement with new recordings (its takes start
as drafts; the build keeps Spain's takes until one is approved, as designed). It shares the protections that apply:
- the sound version (`loaded_sound_sha256`);
- eligibility;
- refused while a conversion is staged;
- one atomic save with a read-only record, spec hashes and the local recovery snapshot;
- the validator run;
- the same previewed, conflict-checked Undo with exact approval restore.

## 11. Tools and tests

| What | Where |
|---|---|
| Planner (pure) | `scripts/common/take_set_conversion.py`: `plan_sound`, `inventory`, `stage`, `approvable`, `approve_unchanged`, `switch_problems`, `activate`, `cancel`, `revert_plan`, `recovery_record` |
| Store | `mapping_store.save_sequence` (several checked steps, one commit); `check_transition` rules for the record and for `restore` |
| Studio API | `GET /api/takes/convert/preview`, `/inventory`, `/approvable`, `/revert_preview`; `POST /api/takes/convert/stage`, `/approve_unchanged`, `/activate`, `/cancel`, `/revert` (`M4App.convert_*`) |
| Studio UI | `ReplacementSet.vue` (preview, stage, approve unchanged, switch, cancel, next-build notice, undo preview), `AddedTakes.vue` (mode, summary, reminders), `TakeSetsView.vue` (inventory; own sets on single-take sounds under their own filter and count; bulk stage of ready sounds; bulk switch) |
| Read-only inventory | `python scripts/validate/take_set_inventory.py` (JSON + catalogs; the DB only with SQLite `mode=ro`) |
| Tests | `tests/test_take_set_conversion.py`: `PreviewTests`, `StageActivateTests`, `BuildNeutralTests`, `ApproveUnchangedTests`, `SwitchTests`, `RecoveryTests`, `LocalRecoveryTests`, `VisibilityTests`, `BuildTests`, `ReadOnlyInventoryTests`; `npm run test:take-sets` |

## 12. Still open

- Partial switch (≥1 approved) and bulk staging of review cases: not built (owner chose strict and one by one).
- `mappings/.history/` keeps a full JSON copy per save (4.4 GB on 2026-10-19). Not pruned in this task.
- Sets made before 2026-10-18 have no record: no automatic recovery.
