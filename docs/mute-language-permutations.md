# Mute, a LATAM audio language, and more permutations (owner prompt 49, 2026-10-15)

**For:** the owner and later sessions. **Status:** feature 1 is implemented and validated offline; features 2
and 3 are research plus offline proofs. Nothing was installed, MCC was not launched, and no file under the
`.env` folders was changed.

Labels: **VERIFIED** = local evidence (file, hash, count, test); **DOCUMENTED** = cited source;
**INFERRED** = reasoning from verified data; **UNVERIFIED IN GAME** = needs an owner test.

Re-run everything with:

```sh
python scripts/discovery/p49_offline_proofs.py mute          # work/p49/mute_report.json
python scripts/discovery/p49_offline_proofs.py permutations  # work/p49/perm_report.json
python -m unittest tests.test_mute
```

---

## 1. Mute / No replacement

### 1.1 The decision

A new audio source, `mute`, in `manual-mappings/3` (additive: no migration; existing documents stay valid).

| Field | Rule |
|---|---|
| `audio.source = "mute"` | The line is omitted from gameplay. Distinct from `keep_original` (Spain plays), from an unmatched line (`match.status = unreviewed`, Spain plays) and from Needs rework (a status, not a source). |
| `audio.mute_reason` | Required with `mute`, refused otherwise (schema `if/then/else`), 1–500 characters. Part of the audio decision: immutable once approved. |
| `match.status` | Must be `no_equivalent` (validator `mute_requires_no_equivalent`). The slot ID and tag stay recorded as for every mapping. |
| `audio.sources`, `audio.edit` | Empty / identity. Radio flag refused (`radio_effect_without_selected_audio`). |
| `subtitle` | A separate decision. The Studio proposes `none` when you mute (unapproved subtitles only); you can keep MCC's text instead. A muted line with a CE/custom subtitle text is reported as `info`. |
| Reverting | Approved: Needs rework (revision + 1), then Keep Spain's audio (or Unmatch). Draft: just pick another option. `mute_reason` is removed with the source. |

Nothing mutes on its own: unmatched lines still keep Spain audio. Tools never create or approve a mute.

### 1.2 What M6 builds

`common/m6_build.plan_audio` gives an approved, mono, drift-free `mute` the action **`mute`**
(report group *muted*). `scripts/build/m6_build.py` replaces that sample with
`common/audio_pipeline.silent_stream`: CELT "fmod" profile, **exactly the original sample count**.
Not eligible (Spain stays, reported): drafts, needs rework, stereo slots, drift, a recipe, a match that is not
`no_equivalent`.

Checks per muted sample (in `validation_report.json`): vgmstream decode equals our decode; **decodes to digital
silence**; sample count equals the original; stream length equals the original; Custom CELT. The bank-wide
checks (only targets differ, every subsong decodes, deterministic) apply as for replacements. A build whose mute
was revoked since is stale (`compare_plans` now covers `mute`), so `m6_install.py` refuses it.

### 1.3 Why silence of the original length is safe (VERIFIED offline)

- All 5,696 Spanish samples are whole 512-sample CELT frames, CBR 370 B (mono).
- MCC's Spanish bank contains **33,294 mono CELT silence frames, all the same 370-byte packet**
  (`sha256 1a5a245e…`); stereo has one 464-byte silence packet (188 frames).
- libcelt 0.11 in our "fmod" profile encodes digital silence to **that exact packet** (`packets_equal_mcc_mono_silence_packet`).
- **Retail precedent:** Spain's `x70\cor_19` (index 5,685, 35,328 samples) is made **only** of that packet: MCC
  already ships a muted dialogue line. Its `SP` subtitle entry is empty too (§1.4).
- Same length + CBR ⇒ the stream has the same byte length, so the bank keeps its size and every offset.

Offline proof on the pinned bank, muting `A10_350_captkeyes` (#30, an experiment, not a mapping):
**27/27 checks**, candidate `07057494…` (`work/p49/mute_report.json`): same size and sample spans, only #30's
bytes differ, all 5,696 subsongs decode, only #31 differs and it decodes to all zeros.

Why the original length rather than a short one: scripts and AI conversations may wait for a line to finish;
keeping the length keeps the scene's timing exactly. (A shorter sample is possible structurally, since
replacements already change lengths, but it would change timing.)

### 1.4 Blank subtitles: what is and is not known

| Case | Evidence | Status |
|---|---|---|
| **Empty entry** (key present, text `""`) | Shipped tables already hold them for dialogue tags: SU 7, SP 8, EN 1 (e.g. `monitor humming`, `x20\bigboom`, `x20_unique1-3`, `d40_monitor_self/_player`; `x70\cor_19` is empty in **SP** but has text in **SU**; `c10_insert_050_pilot` is empty in **EN**). The writer reproduces empty entries byte for byte. | MCC **loads** tables with empty dialogue entries (it ships them). What it **displays** (nothing, or an empty box) is **UNVERIFIED IN GAME**. |
| **Missing key** | 954 of 1,903 dialogue tags have no SU/SP key (mostly AI barks, which are not subtitled). | Normal for barks. Never produced by our tools: keys are never added or removed. |
| **Deleted entry** | Would change a sorted table's structure. | Not supported; the writer refuses it. |

Free, unmodified in-game check (no file change): play the X70 epilogue with **Spain Spanish** audio and
subtitles (`SP`): Cortana's "Fancy a look?" (`cor_19`) is silent in Spain's bank and its SP entry is empty. What
the screen shows there is exactly what a muted line with `none` will show. With LATAM text (`SU`) the same line
shows "¿Quieres echar un vistazo?" over silence.

### 1.5 Subtitles shared by several recordings

A tag's subtitle key (CRC-32 of the tag path) is shared by all its takes. `subtitle_plan` already refused
disagreeing takes. New rule: an **empty** entry is written only when **every Spanish take of the tag** has an
approved `none`; otherwise it is a conflict (`empty_subtitle_not_agreed_by_every_take`, the takes without it are
listed) and the key stays unchanged, so a take that still plays keeps its subtitle. No current decision uses
`none`, so no existing build changes.

### 1.6 Studio

- Audio: a third choice, **Mute in game (no replacement)**, with a required reason. Choosing it marks the line
  No equivalent, drops its CE lines, edits and CE-only flags, and proposes subtitle `none` (draft only).
- List: filter **Muted in game**, and a red "muted" badge (icon and word) on the row.
- Progress: `muted` and `muted_approved` per level (a subset of No equivalent; never counted as matched);
  shown in the list header and on the Dashboard.
- Builds: scope preview and build details count muted lines; the test report lists them with their reasons.
- The classic page (`/classic`) does not offer mute. It shows a muted line's radio as CE, and a save from it
  fails validation (a `ce` source needs a line), so it cannot silently change a mute.

### 1.7 Still unverified (in game)

1. A muted sample plays as silence with no click, and the scene continues normally (expected from §1.3).
2. What MCC displays for an empty SU/SP entry (§1.4; the X70 check answers it without modding).

**Code:** `schemas/manual-mappings-3.schema.json`, `common/project_validation.py`, `ui/m4_app.py`,
`common/m6_build.py`, `common/audio_pipeline.py` (`silent_stream`), `build/m6_build.py`, `ui/build_api.py`,
frontend `matching/draft.ts` (`muteDraft`), `AudioDecision.vue`, `MccColumn.vue`, `DashboardView.vue`.
**Tests:** `tests/test_mute.py` (11), `frontend/src/matching/draft.test.ts` (3 new).

---

## 2. A separate es-MX audio language

### 2.1 How H1 in MCC picks dialogue audio

- **Dialogue banks on disk (VERIFIED):** `halo1/sound/pc/sounds_dialogs.fsb` (English), `_spanish`,
  `_french`, `_german`, `_italian`. `lst/` has 8 dialogue indexes: those five plus `_japan`, `_korean`,
  `_chinese` (their banks come with the optional language-pack DLC [^packs]).
- **File names are built from one pattern (VERIFIED):** `halo1.dll` contains `sounds_dialogs%s.fsb`,
  `sounds_dialogs%s.lst` and `sounds_dialogs_`, with no per-language names.
- **The suffix list is data, not code, but it is closed (VERIFIED in the research pass; INFERRED meaning):**
  `halo1/prebuild/paks/initial_ps.s3dpak` → `sound_config.ps` has
  `localizations { en=["en","default"], french="fr", spanish="es", italian="it", german="de", chinese="zh",
  japan="ja", korean="ko" }`. There is no LATAM / Mexican / es-MX key.
- **`halo1/game.cfg` (VERIFIED):** text `latam_spanish = …strings_latam_spanish.str`, and
  `AudioTrack_spanish = 04` but `AudioTrack_latam_spanish = 00` (the English track, for videos).
- **Other MCC games do have LATAM audio (VERIFIED):** `halo3/fmod/pc/mexican.fsb` beside `spanish.fsb`; also
  ODST, Reach, and `halo4/sound/pc/spanish(mexico)/`. H1 has none.
- **The `.lst.bin` index is per language (VERIFIED, corrects older notes):** all 8 list the same 1,903 tag
  names in the same order, but the sample ranges differ (totals EN 6,093, ES 5,696, FR 5,840, DE 5,723,
  IT 5,722, JA 6,092, KO 5,861, ZH 5,765). Each index belongs to its bank.
- **Observed behaviour (owner, `v-000012`–`v-000014`):** LATAM primary + Spain fallback ⇒ SU text, Spain audio.

**Fallback level (INFERRED):** the **language** level. The shell's audio language is mapped to one of H1's 8
keys; LATAM is not one, so H1 uses Spain's. Nothing points to fallback per bank, tag or sample: every index
covers every tag (no zero counts), and a missing bank is reported to stop the game rather than fall back [^gs].

### 2.2 The four options

| | What | Verdict |
|---|---|---|
| **A** | A new selectable H1 audio language with per-recording fallback to Spain | **Not supported.** It needs a new `localizations` key inside a packed `.s3dpak` plus code that maps the shell's Mexican Spanish to it: unverified, a modified install, anti-cheat sensitive. Per-recording fallback does not exist in the format: one bank + one index must cover all 1,903 tags. |
| **B** | A separate es-MX bank loaded through an existing slot | **Only by taking a slot over.** `sounds_dialogs_latam.fsb` would never be loaded. Using `_japan`/`_korean`/`_chinese` would make players pick that language and collides with Steam DLC files. In practice B = D. |
| **C** | A custom campaign / Workshop package with LATAM audio | **Unproven, unlikely.** Dialogue banks are global, not per map; no documented Excession/Workshop way to ship FSB banks or localization tables [^exc]; HEK `tool` builds only the SFX bank (b2-audio-research §1.6). |
| **D** | Replace the Spain Spanish bank | **Confirmed** in game (`v-000015`–`v-000019`). Spain players also hear es-MX. Per-recording "fallback" is what we already do: every unmatched line keeps Spain's original sample in the same bank. |

**Answer:** *Can MCC recognize es-MX as an independent selectable audio language with per-recording fallback to
Spain Spanish?* **No, not without modifying packed game data and relying on unverified code paths.** The best
supported route remains D, which already gives per-recording fallback (Spain stays wherever no es-MX line is
approved) and, with LATAM primary + Spain fallback, shows SU text over es-MX audio.

Full notes, offsets and string neighbourhoods: `work/reports/lang_research_p49.md` (git-ignored).

---

## 3. More permutations for system audio

Research case: Grunt `sound\dialog\grunt\conditional\combat2\involuntary\death_violent`.

### 3.1 Where the counts come from

| Source | death_violent | death_quiet | grenade_startle | Status |
|---|---|---|---|---|
| HEK source tag (`HCEEK.7z`, English): `actual permutation count` / permutations | 4 / 4 (`1`–`4`; #3 has skip fraction 1.0) | 6 / 6 | 2 / 2 | VERIFIED (selective extraction to `work/hceek/`) |
| English bank (`lst` count, sample names) | 4 (`1`–`4`) | 6 | 2 | VERIFIED |
| Spain bank | 2 (`deathviolent 01/02`) | 4 | **3** | VERIFIED |
| Campaign Evolved es-MX (`vo_sys_default_11involuntary_die_ass_grunt`) | 6 entries, all with es-MX media | | | VERIFIED |

Across all 1,903 tags, 529 sample counts differ between English and Spain: 329 have fewer in Spain, **200 have
more**. Spain's samples carry the dub studio's own names, not the tag's permutation names.

**What that implies (INFERRED, strong):** the campaign `.map` files are shared by every language, so the tag's
permutation count is the same for all of them, yet Spain's bank holds 2 samples where the tag has 4 and 3 where
it has 2. The game must therefore find a tag's samples through the **language's `.lst.bin` range**
(`first_sample_index`, `sample_count`), not through the tag alone. *How* it picks within that range (random over
the `.lst` count; or the tag's permutation index clamped / wrapped into it) is compiled code we have not read;
community docs agree that permutations are chosen at random, with a per-permutation skip fraction [^hm][^c20].

### 3.2 Can the Spanish bank hold more playable samples?

Structurally yes (VERIFIED offline): `p49_offline_proofs.py permutations` inserts English #3 and #4 after
Spain's two `death_violent` samples and rewrites the Spanish `.lst.bin` (count 2 → 4, every later range + 2):
**12/12 checks** (`work/p49/perm_report.json`; bank `f775357c…`, lst `c1b3c702…`): the index parses, is
contiguous and covers 5,698 samples; every other tag resolves to byte-identical samples; every other slot ID is
unchanged; all 5,698 subsongs decode.

Constraints for added samples: mono CELT, 44.1 kHz, the MCC "fmod" profile (E2 crash), whole 512-sample frames,
a LOOP chunk `0, n-2`, and the bank's head bits; a unique name (slot IDs are names + occurrence). The `.lst.bin`
must change with the bank: **our installers never write it today**, so this needs a new, owner-approved install
step (bank + index together).

### 3.3 Answer

*Can we make MCC randomly play more variations than currently defined in the Spain Spanish resources?*
**Yes, up to the tag's own permutation count: confirmed in game on 2026-10-17 (`v-000020`, all 4 takes of
`death_violent` heard, 2 of them added; docs/permutation-experiment.md). Beyond the tag's count is still untested.**
Original assessment: likely, at least up to the tag's own permutation count (4 for `death_violent`). The
data says the per-language index, not the tag, defines Spain's set (Spain already ships 200 tags with more
samples than the tag defines, and 329 with fewer, without problems). Whether extra samples are actually
**selected** can only be shown in game.

**Prepared (2026-10-16): docs/permutation-experiment.md.** Original sketch: install the `perm_` bank + index
together, then kill Grunts violently (grenades, explosions) ~20 times with Spanish audio. English #3/#4 are
longer (2.6 s / 2.4 s vs Spain's 1.2 s / 0.8 s) and audibly different. Any English death ⇒ the extra samples are
selected. A stronger second case puts **5 or 6** samples on `death_violent` (above the tag's 4): if those play
too, the selection uses the index count. Also check that tags after the Grunt range in the bank (e.g. Marine barks) still play their own
lines, which proves the shifted index is read.

**Risk:** if the game used the tag count to index *without* the `.lst` range, later tags would play the wrong
samples; the test above detects that immediately. Keep the usual install/rollback safeguards.

---

## 4. Recommended milestones (by feasibility and risk)

1. **P49-1 (low):** owner trial of Mute in the Studio, then a combined audio + subtitle build with one or two
   muted lines; in game: silence, timing, and the subtitle. Free check first: the X70 `cor_19` observation (§1.4).
2. **P49-2 (low):** record the results (`verifications.json`, `mute_load` / `subtitle_empty_entry`).
3. **P49-3 (medium):** permutation in-game test (§3.3): extend `b2_bank_install.py` (or `m6_install.py`) to
   install and restore the Spanish `.lst.bin` with the bank as one operation, then the owner's test.
4. **P49-4 (medium, after P49-3 passes):** a permutation model in the Studio: extra CE es-MX takes per tag
   (e.g. the 6 `die_ass` lines), a new mapping concept ("added take"), M6 insertion + index rewriting, catalog
   and slot-ID handling for inserted samples. A schema addition, designed once P49-3 shows what the game does.
5. **Not recommended:** option A (a new H1 audio language) or any executable / packed-config change.

[^packs]: Halo Support, [How to install Portuguese, Chinese, Japanese and Korean language packs on Steam](https://support.halowaypoint.com/hc/en-us/articles/360037082732-Halo-The-Master-Chief-Collection-MCC-How-to-Install-Portuguese-Chinese-Japanese-and-Korean-Language-Packs-on-Steam); [Which languages can I play MCC in?](https://support.halowaypoint.com/hc/en-us/articles/360057636612-Which-Languages-Can-I-Play-Halo-The-Master-Chief-Collection-In).
[^gs]: Game*Spark, [CE Anniversary not launching in Japanese without the language pack](https://www.gamespark.jp/article/2020/03/04/97231.html) (secondary source).
[^exc]: Microsoft Learn, [Excession folder structure](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/setup/folderstructure); see also `docs/workshop-research.md`.
[^hm]: Halo Maps forum threads on sound permutations and skip fractions, e.g. [topic 50342](https://halomaps.haloman30.com/index.cfm%3Fpage=topic&topicID=50342), [topic 28309](https://halomaps.haloman30.com/index.cfm%3Fpage=topic&topicID=28309) (community).
[^c20]: c20, [dialogue tag](https://c20.reclaimers.net/h1/tags/dialogue/): "The randomization of voice lines is not part of the dialogue tag but rather the referenced sound tags, which can contain multiple permutations."
