# Permutation experiment: can MCC play more takes than Spain's bank provides? (owner, 2026-10-16)

**For:** the owner, before and after the in-game test.

> **RESULT (2026-10-17, owner, `v-000020`): PASS.** With `exp_grunt_death_violent_johnson` installed, the owner
> heard **all four** Johnson takes at Grunt deaths, including the two added after Spain's original two. MCC
> selects added takes through the per-language sound index. Take 3 sits on the map tag's permutation with skip
> fraction 1.0, so hearing it indicates the game picks within the index range and does not apply the tag's skip
> flag there. Not reported: counts, level, graphics mode. Still untested: more takes than the tag defines (5+).

**Status before the result:** prepared and validated offline. Nothing here is made from `mappings/`; the general "add another take" feature is not built.

## 1. What the test build contains

Build `exp_grunt_death_violent_4` (`work/m6/exp_grunt_death_violent_4/`, made by
`python scripts/discovery/perm_experiment.py`; about 1 minute):

| Take | Recording | Seconds | Where it comes from |
|---|---|---|---|
| 1 | `deathviolent 01` | 1.18 | Spain (unchanged) |
| 2 | `deathviolent 02` | 0.76 | Spain (unchanged) |
| 3 | **EXTRA**, English take 3 | 2.59 | English bank, same sound's permutation "3" |
| 4 | **EXTRA**, English take 4 | 2.37 | English bank, same sound's permutation "4" |

Two files are replaced **together**, and restored together:
- `halo1/sound/pc/sounds_dialogs_spanish.fsb`: 2 takes inserted after Spain's (+161,536 B), candidate `a74b9741…`;
- `halo1/sound/pc/lst/sounds_dialogs_spanish.lst.bin`: `death_violent` count 2 → 4, every later range + 2,
  candidate `c1b3c702…`.

Listen first: `work/m6/exp_grunt_death_violent_4/listen/` has the four takes (`violent_1_…` to
`violent_4_EXTRA_…`) and Spain's other Grunt deaths (`ref_death_quiet_*`, `ref_death_instant_*`,
`ref_death_flying_*`), so you can tell them apart.

**Offline validation: 19/19** (`validation_report.json`). Inputs match their pins; built twice, identical; the
index writer reproduces the shipped index byte for byte; only the target count and later starts change; Spain's
two takes are untouched and first; the inserted takes are the English samples, in MCC's CELT profile; every
original sample is byte-identical in its new place; every other slot ID is unchanged; all 5,698 recordings
decode; every original recording decodes identically; the extras decode exactly as English #3/#4.

**Install safety (rehearsed on a throw-away copy of the game folder, and unit-tested):** check → preflight
(verified backups of both originals) → install (both files verified, nothing else changed) → rollback (both
originals, snapshot unchanged). A failure after the first file restores **both**. Any build that replaces only
the bank now refuses to install while the index is not the original (`m6_install.companion_check`), so a normal
LATAM build can never sit on top of the experiment's index.

## 1b. Johnson variant (owner, 2026-10-16): `exp_grunt_death_violent_johnson`

`python scripts/discovery/perm_experiment.py --preset johnson`: all four `death_violent` takes are Sergeant
Johnson lines (Spain bank, `sargeant`), chosen because Halo (a30) never triggers them itself (Flood, Sentinels,
a betrayal). So **any Johnson voice when a Grunt dies comes from the experiment**, and each line tells which take
the game picked:

| Take | Johnson line | Seconds | Place | What hearing it means |
|---|---|---|---|---|
| 1 | `killedenemyfloodcombatcm 03` (`es:killedenemyfloodcombatcm%2003#5`) | 2.98 | Spain's take 1 | `death_violent` played (original range) |
| 2 | `killedenemysentinel 02` (`es:killedenemysentinel%2002#5`) | 1.46 | Spain's take 2 | `death_violent` played (original range) |
| 3 | `alliancebroken 02` (`es:alliancebroken%2002#5`) | 2.43 | **added** | the game picks from the index (the tag says skip take 3) |
| 4 | `killedenemyfloodcarriercm 02` (`es:killedenemyfloodcarriercm%2002#5`) | 1.29 | **added** | **added takes are selected** |

18/18 offline checks; bank `b6c3e881…` (+202,784 B), index `c1b3c702…` (the same index as the English variant:
only the count matters there). Listening files: `work/m6/exp_grunt_death_violent_johnson/listen/take1_…` to
`take4_EXTRA_…`. The procedure in §3 is the same; tally takes 1–4 instead of Spain/English. Spain's own
`death_violent` takes are not in this build, so every Grunt `death_violent` sound is a Johnson line.

## 2. When does the game play `death_violent`? (what is known)

- **VERIFIED** (HEK `grunt.dialogue`, its 166 sound references in c20's field order [^c20]): the Grunt's
  `death_violent` sound is used for two death types, **death violent** and **death agonizing**. Death quiet and
  death instant have their own sounds; death falling and death flying share `death_flying`.
- **VERIFIED** (the shipped `a30.map`, read-only): the game's own `death_violent` tag has **4 permutations**
  named 1–4, and permutation **3 has skip fraction 1.0**: the engine is told to always skip it (in English too).
- **NOT KNOWN:** which kills produce "violent" or "agonizing" deaths. No documentation says so [^c20][^sr]. From
  the names only (INFERRED): explosions and heavy hits are the best candidates for *violent*; headshots
  probably give *instant*; killing an unaware Grunt probably gives *quiet*; being thrown gives *flying*.

So don't count every Grunt death. Count only the deaths where you hear one of the four `death_violent` takes.

## 3. In-game procedure (you do every step)

1. **Restore the originals** in Build & Test (**Restore originals**). Your LATAM build
   `all_mapped_both_20261016225347` is installed now, and the experiment refuses to install on top of it.
   Close MCC first.
2. **Listen** to the files in `listen/` for a minute: two short Spain takes, two long English ones.
3. **Install** `exp_grunt_death_violent_4` from Build & Test (it says *Experiment*; the confirmation lists both
   files). MCC must be closed.
4. Start **Halo: MCC Anti-Cheat Disabled**. Audio language: **Spanish (Spain)** (or LATAM with Spain as the
   fallback, which plays the same bank). Classic or Anniversary graphics both work.
5. Play **Halo** (`a30`) from the start, Easy or Normal. Marines and Sergeant Johnson talk constantly there:
   **sanity check**: their lines must sound right. Every Marine, Johnson, Jackal and cutscene line sits after
   the insertion point in the index, so a misread index would show up at once as wrong lines.
6. Kill Grunts **with explosions** (frag and plasma grenades, a stuck plasma grenade, a group hit by one blast),
   then also with an assault rifle to the body, and a few headshots and melees. Keep a tally of each
   `death_violent` take you hear: **S** (a short Spain take, 1 or 2), **E-long** (an English one, 3 or 4).
   Recording the session (Win + Alt + R, Xbox Game Bar) lets you replay doubtful ones.
7. Stop after about **15 `death_violent` sounds** (any takes), or 20–30 minutes.
8. Close MCC, then **Restore originals** in Build & Test (both files come back, verified). Reinstall your LATAM
   build afterwards if you want it back.
9. Tell me the tally, which English take(s) you heard if you can tell them apart (3 = 2.59 s, 4 = 2.37 s), and
   whether anything else sounded wrong.

## 4. What the result means

| What you hear | Meaning | Next |
|---|---|---|
| English takes appear (about 1 in 3 or more of the `death_violent` sounds) | **MCC selects the added takes.** | Build the general feature: extra CE es-MX takes per sound in the Studio. |
| …including take **3** | The game picks from the index range and **ignores the tag's skip fraction**, so adding more takes than the tag defines should also work (a second test with 5–6 takes would confirm it). | |
| …only take **4**, never 3 (after 15+) | The game uses the **tag's permutation list** (4 entries, #3 skipped) mapped onto the index: extra takes work **up to the tag's count** (4 here). | The feature is limited per sound to the map tag's permutation count. |
| Only Spain's short takes, 10+ times, no English | The added takes are **not selected** (chance of missing take 4 by luck after 10: about 2 %). | Investigate (below) before proposing another approach. |
| Wrong lines elsewhere, silence, or a crash | The index is not read the way we think. | Restore at once, then report. |

**If they are not selected, what I will investigate next (offline, in this order):**
1. *Sound-tag references:* whether the map's tag carries per-permutation data that ties a permutation to a
   specific bank sample (the 124-byte permutation blocks hold fields we have not decoded yet).
2. *Permutation metadata:* whether Spain's extra samples on the 200 sounds where Spain has more than the tag
   (e.g. `grenade_startle`, 3 vs 2) are ever heard, which tells whether counts above the tag are ever used.
3. *Runtime selection:* whether the count comes from the bank's own sample names or order rather than the
   index (compare how other languages' indexes and names relate to their tags).

[^c20]: c20, [dialogue tag](https://c20.reclaimers.net/h1/tags/dialogue/) (field list; no per-field trigger rules).
[^sr]: The Sounds Resource, [Grunts (Halo: CE, Xbox)](https://sounds.spriters-resource.com/xbox/halocombatevolved/asset/413479/) lists the sound groups (death_violent 4 variants), with no trigger rules.
