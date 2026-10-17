# Added takes: design for review (owner, 2026-10-17)

**For:** the owner, to approve or change before anything is built. **Status:** proposal only; no code yet.

## 1. Goal

Let a sound play more Campaign Evolved es-MX recordings than Spain's bank has for it. Example: Grunt
`death_violent` has 2 Spain takes; Campaign Evolved has 6 es-MX Grunt death screams. Today you can only put CE
recordings in Spain's 2 places. With added takes, all 6 can play and the game picks among them.

## 2. What is already proven

| Fact | Evidence |
|---|---|
| The game picks among all takes listed in the Spanish index (`.lst.bin`), including added ones | in game: `v-000020` (4 takes), `v-000021` (6 takes, beyond the map's 4) |
| The take count comes from the index, not the map's sound definition | `v-000021` |
| Bank + index can be built, validated, installed and restored as one unit | `exp_grunt_death_violent_*`, `m6_install.py` |
| Inserting takes never changes another line's audio or slot ID | 18/18 offline checks on every experiment |
| No campaign dialogue sound has chained takes or more than one take list | read-only scan of the 10 campaign maps: 1,867 dialogue sounds, 0 chained |

**Not yet proven:** that added takes work on **scripted story lines** (only combat chatter was tested), and in
Anniversary mode (graphics mode was not reported).

## 3. Questions for you (my recommendation first)

1. **Which sounds may get added takes?**
   *Recommended:* only sounds with **no subtitle entry** (AI chatter: Grunt deaths, Marine barks, Johnson's
   combat lines). Scripted story lines play once at a fixed moment, and their subtitle is shared by every take:
   an added take that says something else would show the wrong text. If you want story lines too, I'd allow them
   only when the added take says the same sentence, and mark them clearly.
2. **Can a take be added before Spain's own places are decided?** *Recommended:* yes. They are independent
   decisions, like audio and subtitle today.
3. **A limit per sound?** *Recommended:* no hard limit; a warning above 12 takes (bank size and variety).
4. **What does a Spain-only player hear?** Unchanged answer: everyone who selects Spanish hears this bank
   (docs/mute-language-permutations.md §2). Added takes are LATAM recordings like every replacement.

## 4. How it would work

### 4.1 Your decisions (mappings)

A new optional list in `manual_mappings.json`, **`added_takes`**, next to `slots` (additive: no migration, nothing
existing changes):

```json
{"take_id": "t-000001",
 "mcc_tag": "sound\\dialog\\grunt\\conditional\\combat2\\involuntary\\death_violent",
 "position": 1,
 "audio": {"status": "draft", "source": "ce",
           "sources": [{"kind": "ce", "ce_line_ref": "vo_sys_default_11involuntary_die_ass_grunt#2",
                        "language": "Spanish(Mexico)"}],
           "edit": {"trim_start_s": 0, "trim_end_s": 0, "gap_s": 0},
           "fingerprint": null, "approved_at": null, "revision": 1},
 "radio_effect": {"needed": false, "set_at": null, "revision": 1},
 "notes": ""}
```

- **`take_id`**: a new, stable identity (`t-NNNNNN`), never reused. Existing slot IDs do not change.
- **`position`**: the order of the added takes within the sound (1 = first after Spain's).
- **`audio`**: the same object as a line's audio today, with the same rules: tools never approve; an approved
  take changes only through Needs rework (revision + 1); edits, radio and echo work the same way; the approval
  fingerprint covers the CE recording and the sound's Spain takes, so drift is detected.
- **No subtitle**: the sound's subtitle belongs to the sound (shared by all takes), as today.
- **Removing** a take is allowed while it is not approved (approved: Needs rework first), like other decisions.
- Storage: the database gets an `added_takes` table and its history (database schema v5, additive, upgraded
  on open); the JSON export and the import/export checks cover it.

### 4.2 In the Studio

- On the Matching page, a section **"Added takes for this sound"** under the line, listing the sound's
  Spain takes (read-only, with their current decision) and its added takes.
- **Add take**: uses the Campaign Evolved recording selected on the right, as a draft. Each added take has its
  own audio decision, editor, preview, approve and Needs rework, exactly like a line. Reorder with ↑ ↓.
- The list shows a "+N takes" badge on the sound's lines; a filter "Has added takes"; progress counts added
  takes separately (never as matched lines).
- Sounds that are not allowed (question 1) show why instead of the Add button.

### 4.3 The build

- `plan_audio` gets a new action, **insert**, for approved added takes (draft / needs rework / drift: left out
  and listed, as today).
- The bank is built as now (replacements, mutes), then the added takes are inserted after each sound's Spain
  takes, in `position` order, with unique names (`LATAM t000001`).
- **Only when a build inserts at least one take**, it also writes the Spanish `.lst.bin` (counts + shifted
  ranges) and installs/restores **both files together**. Builds without added takes stay exactly as today
  (bank only).
- New checks (added to the current ones): every original sample byte-identical at its shifted place; the index
  reproduced from its rules; every sound resolves to its expected takes; all subsongs decode; inserted takes in
  the MCC CELT profile; deterministic; stale-build detection includes inserts.
- Already in place: the installer handles bank + index (`m6_install.py`), and a bank-only build refuses to
  install over a changed index.

## 5. Order of work

1. Schema + validator + store/database (with history) + tests.
2. Studio backend: add / edit / approve / reorder / remove a take; the allowed-sound rule.
3. Studio page: the section, badge, filter, counts; browser test (`npm run test:takes`).
4. M6: insert action, index writer in the build, checks, reports, test report section; tests.
5. One in-game check of a real build: a few added es-MX takes on 2–3 chatter sounds, plus a normal LATAM build
   alongside, then restore.

Estimated size: about the size of the radio filter work; steps 1–4 are offline and fully testable.

## 6. Not part of this

- Removing Spain's own takes (a sound always keeps its Spain places, replaced or not).
- Other languages' banks, stereo takes (still deferred), Workshop packaging.
