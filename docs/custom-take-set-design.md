# Own take set per sound (owner, 2026-10-18)

**For:** the owner. **Status:** steps 1–3 built (offline, tested); step 4, the in-game check, is the owner's.
Requested on 2026-10-18 ("create my own set of permutations"). The owner chose **replace Spain's takes entirely**,
**clear the sound's line decisions** when the set is turned on, **barks only** (no subtitle entry), and **build
everything, then test in game**. **2026-10-19 (owner): barks only is lifted**: mono sounds with a SU/SP subtitle entry
may have an own set too, with **one subtitle per set** (§2.1). Added takes on scripted story lines are not yet proven
in game.

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
- **Rules (validator):** mono sounds only (with or without a subtitle entry since 2026-10-19); no line decisions left
  on the sound (error); a warning while no take is approved; for a subtitled sound in force, a warning while the set's
  subtitle is not approved (`own_set_subtitle_not_approved`); a set subtitle on a sound without an entry is an error
  (`own_set_subtitle_without_entry`), as are an unknown CE line / custom ref.

### 2.1 One subtitle per set (owner, 2026-10-19)

A sound with a SU/SP entry shows ONE text for every take (the key is the tag path). Turning a set on (or switching a
conversion) clears the line decisions, their subtitles included, so the set carries the sound's subtitle itself:

```json
{"mcc_tag": "sound\\dialog\\d40\\d40_monitor_player", "set_at": "2026-10-19",
 "subtitle": {"status": "draft", "source": "custom", "ce_locres": null, "custom_ref": "c-000031",
              "fingerprint": null, "approved_at": null, "revision": 1}}
```

- **Shape:** a line's subtitle object without `mcc_key_hash`/`mcc_key_verification` (schema `own_set_subtitle`).
  Sources: `keep_original` (MCC text stays), `ce_locres` (a CE line's text in es-MX / en / es-ES), `custom` (owner
  text; the text lives only in the git-ignored `manual_mappings.local.json`), `none` (an empty entry). Optional;
  absent = undecided. Only on sounds with an entry.
- **Lifecycle:** exactly a line subtitle's. Saved as a draft; approved only by the owner's explicit action
  (`UserAction("approve", <mcc_tag>, "subtitle")`, fingerprint `own_set_subtitle_fingerprint`: the sound, the
  source, the CE subtitle identity or the custom text hash); approved = immutable except `needs_rework` (revision + 1),
  enforced by `mapping_store.check_transition`. A set holding an approved subtitle cannot be removed until it is
  reworked: *Back to Spain's takes*, *Cancel* and *Undo* add that step to their one save. Tools never approve.
- **Studio:** *Takes of this sound* → **Subtitle of this sound** (`SetSubtitle.vue`) for a staged or active set:
  choose, *Save subtitle*, *Approve subtitle*, *Needs rework*, *Clear* (`POST /api/takes/set_subtitle`). The 4th audio
  option (`WholeSoundReplace.vue`) offers it in the same flow (decide later / keep MCC's text / no subtitle / my own
  text), saved as a draft with the set (`own_set_on` body `subtitle`). Without an own set, added takes on a subtitled
  sound show a warning that every take shows the same text.
- **Build:** only while the set is in force: approved → write the text / write empty / keep; not approved or undecided
  → the key is excluded and listed (MCC text stays). Keys are never added. Staged sets change nothing.
- **Switch:** a staged conversion of a subtitled sound switches only when its set subtitle is approved and drift-free.
- **Public view:** the set's text is shown like a line's custom subtitle text; nothing else is exposed.

## 3. The build (M6)

`plan_inserts` as before. A sound in own-set mode **with at least one take to insert** is in `own_set_drops`; its
slots get the action `dropped`, and `insert_takes(…, drop_tags)` leaves its Spain samples out, so its index range
holds only its inserted takes. A sound in own-set mode with no approved take keeps Spain's takes (never an empty
sound; `insert_takes` refuses one). Checks added: exactly the own-set sounds' samples are removed, each holds only
its takes, every other sample is byte-identical at its new place, the index stays contiguous. `dropped` counts as a
bank change, so `m6_install.py` refuses a build if the set was turned off (or changed) since.

Subtitles (`subtitle_plan`): for a sound whose set is in force, the set's approved subtitle is the key's only outcome
(row `slot_id` = `own set <tag_name>`, `own_set: true`); line rows of such a sound never apply.

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
