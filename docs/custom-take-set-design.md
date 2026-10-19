# Own take set per sound (owner, 2026-10-18)

**For:** the owner. **Status:** steps 1–3 built (offline, tested); step 4, the in-game check, is the owner's.
Requested on 2026-10-18 ("create my own set of permutations"). The owner chose **replace Spain's takes entirely**,
**clear the sound's line decisions** when the set is turned on, **barks only** (no subtitle entry), and **build
everything, then test in game**.

## 1. What it does

For one sound (e.g. Grunt `death_violent`), the game plays exactly the recordings you list, in any number.
Spain's own takes of that sound are removed from the bank and the Spanish index.

Before: Spain 1 = `dth_mjr_grunt#0`, Spain 2 = muted, added `t-000007`, `t-000008` → 4 takes, one silent.
With an own set: only the added takes → e.g. 3 grunt screams, no silent one.

## 2. How it is built (one switch + the added takes)

The set **is** the sound's added takes: adding (one, or several with the picker), reordering, previewing, approving
and Needs rework work exactly as for added takes. The new part is a per-sound switch:

- **Data:** optional list `own_sets` in `manual_mappings.json`: `{"mcc_tag": …, "set_at": "YYYY-MM-DD"}` (additive;
  never written empty). Database schema **v6** adds the `own_sets` table and its history (upgraded on open, additive).
- **Turning it on** is the 4th audio option of any line of the sound (Replacement audio → *Replace every take of
  this sound (choose several recordings)*, owner request 2026-10-18, `WholeSoundReplace.vue`). It lists every Spain
  take that would be replaced, each playable (ES) with its current decision, and the takes already added; the owner
  ticks several Campaign Evolved recordings (`TakePicker.vue`, also used by *Add several takes…*) and confirms.
  The confirmation lists every line decision that will be cleared. The server then, in one request
  (`/api/takes/own_set_on` with `audio_list`) and **one save** (`mapping_store.save_sequence`, since 2026-10-18;
  before, these were two separate saves), (1) marks every approved one Needs rework (a user action, revision + 1),
  (2) removes the sound's line decisions, turns the set on and adds the ticked recordings as draft takes. The removed
  decisions are kept exactly in the set's `provenance` (`kind: "replace"`). The page must name exactly the decisions
  it showed and the sound's version (`loaded_sound_sha256`), or nothing happens; at least one take must result.
  Approval rules are unchanged: the store still refuses to delete an approved decision directly.
- **From the owner's own selections:** a sound's per-take selections can become the set instead
  (`docs/replacement-set-conversion.md`): staged first, every take approved, then switched.
- **While on:** the 4th option stays selected on every line of the sound (with the takes it plays and *Add more
  recordings*); the sound's Spain lines take no decision (the API refuses a save; the panel is locked and says why),
  the list shows an **own set** pill, the level progress counts those lines as decided (audio approved once the
  sound has an approved take).
- **Turning it off** (*Back to Spain's takes*, in the same panel): the sound plays Spain's takes + added takes again; its lines start
  undecided. **Undo the replacement set** (under *Takes of this sound*, sets with a record) instead restores the
  recorded line decisions, each approval as Needs rework (`docs/replacement-set-conversion.md` §8).
- **Rules (validator):** mono sounds without a subtitle entry only; no line decisions left on the sound (error);
  a warning while no take is approved.

## 3. The build (M6)

`plan_inserts` as before. A sound in own-set mode **with at least one take to insert** is in `own_set_drops`; its
slots get the action `dropped`, and `insert_takes(…, drop_tags)` leaves its Spain samples out, so its index range
holds only its inserted takes. A sound in own-set mode with no approved take keeps Spain's takes (never an empty
sound; `insert_takes` refuses one). Checks added: exactly the own-set sounds' samples are removed, each holds only
its takes, every other sample is byte-identical at its new place, the index stays contiguous. `dropped` counts as a
bank change, so `m6_install.py` refuses a build if the set was turned off (or changed) since.

## 4. What is known

| Fact | Evidence |
|---|---|
| The game picks among the takes in the Spanish index, beyond the map tag's count | `v-000020`, `v-000021` |
| Retail Spain already has 329 sounds with **fewer** samples than the map tag | docs/mute-language-permutations.md §4 |
| Removing samples: offline only | `tests/test_added_takes.py` (synthetic banks) |

**Not proven:** a build of ours that removes samples, in game.

## 5. Step 4 (owner): the in-game check

Turn the own set on for `death_violent`, approve its takes, build audio for its folder from Build & Test, install,
and listen to Grunts dying (Classic and Anniversary): only your takes should play, never Spain's, and other lines
should be unchanged. Restore from Build & Test afterwards if anything is wrong.
