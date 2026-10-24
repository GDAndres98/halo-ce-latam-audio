# Suggested matching (read-only Suggestions tab)

**Decided by the owner, 2026-10-23.** The owner asked for "a tab for AI suggested matching" and chose:

- **Read-only suggestions.** A separate tab lists, for each MCC sound, the Campaign Evolved lines that most likely
  match it, with a score and the reason. Nothing is saved, selected, pre-filled or approved. The owner opens the
  line in Matching and decides there as before.
- **English against English.** A local similarity between MCC's English subtitle (`EN_Halo1.bin`, per sound) and
  CE's English subtitle (`Subtitles/en`, per line) builds the shortlist. Claude re-ranks a shortlist on demand.

This lifts the earlier "no tool proposes, scores, ranks or pre-fills CE↔MCC pairs" rule **only for this tab**.
Everything else still holds:
- The Matching page lists CE lines in catalog order, filtered only.
- Tools never write `mappings/`.
- No pair is ever saved without the owner's click in Matching.
- Agents never pick pairs.

## 1. What the tab shows

`/#/suggest?level=a10&scope=mapped&show=undecided` (Studio nav: **Suggestions**; not in the public view).

- **Level**: one MCC level folder.
- **CE lines from**: the level's CE missions from `mission_map.json` (`mapped`, the default). It falls back to every
  mission when the level has no entry, e.g. cinematics `x10` and generic folders. It can also be every mission, or one
  mission.
- **Show**: sounds with no match decision on any take (the default), or every sound. A sound whose replacement set is
  in force counts as decided.
- For each sound: the MCC English line (with its speaker label), the SU text, the MCC players, and the top 5 CE lines
  with:
  - the score;
  - the CE id and mission, plus *same speaker* when the speakers agree;
  - *used* when another decision already lists the line;
  - the English text (shared words highlighted) and the es-MX text;
  - the es-MX player.
- **Open** (on a CE row) goes to Matching with the MCC line open, the CE list's mission set to the line's mission,
  and the CE search set to its id. That is a filter: the owner still presses *Use this recording*.
- Sounds without an English subtitle (barks) are compared by name instead (§2b).

## 2. The local score (`scripts/common/suggest.py`, `suggest/1`)

Stdlib only and deterministic (the same catalogs give the same order; ties keep catalog order).

| Part | Weight | What |
|---|---|---|
| words | 0.5 | TF-IDF cosine over folded words (case, accents and punctuation ignored); IDF from the CE English texts |
| chars | 0.3 | Dice coefficient of character trigrams (catches small rewordings) |
| sequence | 0.2 | `difflib.SequenceMatcher` ratio, computed only for the best few by the first two |
| speaker | +0.05 | MCC `speaker_from_name` equals the CE asset name's last part, or one abbreviates the other (4+ letters: `cryoassist` / `CryoAssistant`) |

The score is shown capped at 100%. The order uses the uncapped value, so the speaker still breaks a tie between two
identical texts.

**Measured on 2026-10-23** (read-only, real catalogs): of the 778 sounds the owner had already matched, the top
suggestion is one of the owner's chosen lines for **686 (88%)**. A full level scores in about 0.5 s (own missions) to
1 s (every mission).

## 2b. Barks: the name mode (`suggest-name/1`, owner request 2026-10-23)

AI combat chatter has no subtitle on either side:
- MCC's generic folders (e.g. `grunt`, 55 sounds) have no `EN_Halo1.bin` entry.
- CE's Systemic lines (`SYS`, 14,350 variations) have no Subtitles text; only 1 has English text.

Both sides name the sounds by situation, though, so a sound **without** an English subtitle is compared by name:

- **MCC side:** the tag's last part, plus its category below the level folder at half weight.
  E.g. `conditional\combat2\exclamations\surprise` gives `surprise` (+ `exclamations`).
- **CE side:** the record name without `vo_sys_default_` and the character suffix.
  E.g. `vo_sys_default_01contact_srprs_grunt` gives `01contact_srprs`.
- **Words:** CE's abbreviations are spelled out (`ABBREV`: `srprs`→surprise, `dth`→death, `rtrt`→retreat,
  `grnd`→grenade, `kllfoe`→kill foe…). Synonyms fold to one word (`CANON`: enemy→foe, doze/sleeping→sleep,
  celebration→cheer, taunt→threaten…), and a light stemmer drops -ing/-ed/-s.
- **Score:** 0.7 × TF-IDF token cosine + 0.3 × character-trigram Dice. Matches under 10% are not listed.
- **Candidates are CE records.** A record's variations are takes; the row shows how many.
- **CE folder:** by default the Systemic folder named like the level (`grunt` → `vo_sys_grunt`). The *CE folder for
  barks* menu can choose another one or every folder. With **CE lines from** = the level's missions (the default),
  barks are compared with SYS; another choice compares them with that scope's records.

**Measured on 2026-10-23** for `grunt` against `vo_sys_grunt`: of the 25 grunt sounds whose match lists CE lines, the
name score's top record is the owner's for 11, and the owner's is in its top 3 for 16. The misses are matches by
meaning, e.g. `panic_run_away` → `rtrt` and `retreat` → `flee`. That is what the Claude step is for.

## 2c. Barks by sound (`audio-match/1`, owner 2026-10-23)

The owner noted that many CE English grunt variations are MCC's English takes again, at another volume or slightly
changed. So barks are compared by their **English audio**, not by text (no speech-to-text: most barks are taunts and
noises). The name mode is the fallback.

- `python scripts/catalog/build_audio_matches.py --level grunt` (CE folder named like the level, or
  `--ce-folder vo_sys_grunt`):
  - decodes every MCC English take of the level and every CE English(US) variation of the folder (on demand, like the
    Studio);
  - compares every pair;
  - writes the best 5 CE variations per MCC take to `work/suggest/audio/<level>__<folder>.json`.
  Features are cached in `work/suggest/audio/features/`. Grunt: 385 × 372 clips, 13 s to decode and measure and 3 s
  to compare. It never touches `mappings/`.
- **Comparison** (`scripts/common/audio_match.py`, stdlib):
  - 20 ms frames, with the leading and trailing silence cut at −45 dB;
  - three features: frame level with the clip's mean removed (gain-free), spectral tilt (first-difference energy
    minus energy) and zero-crossing rate;
  - each feature is z-scored, then correlated at the best ±60 ms offset;
  - the score is 0.5 / 0.3 / 0.2 of the three correlations, × overlap ÷ the longer length. Clips more than 0.6× apart
    in length are not compared;
  - the result also gives the loudness difference in dB.
- **In the tab:** a bark is listed *by sound* when its level and folder were compared and at least one of its takes
  matched (best ≥ 0.5). Each take votes for the CE record of its best variation, most votes first. A row shows
  "*n* of *m* English takes" and each pair *MCC take ≈ CE variation*, both playable, with the score and the volume
  difference. Every MCC English and Spain take, and every CE variation (EN and MX), has a player.
- **Measured on 2026-10-23** (grunt vs `vo_sys_grunt`):
  - 278 of 385 MCC English takes have a CE variation scoring ≥ 0.8, and 118 score ≥ 0.95. The median gap to the
    second-best variation is 0.4. The volume difference of strong pairs runs from −8.5 to +15.4 dB (median −1.1).
  - Of the 25 grunt sounds whose match lists CE lines, the audio's top record is the owner's for **22**; the name
    mode got 11.
  - The 3 misses: `group_uncover` (the owner chose `charge`/`cower`, the audio says `newordr_advance`),
    `death_quiet` (a weak 1-take vote) and `grunty_thirst` (the owner's line is scripted M10, outside the folder).

**Ask Claude to match all barks of a level** sends one request (`POST /api/suggest/folder`, admin remotely, cached).
- **Sent:** every unsubtitled sound name of the level with its take count, and every CE record in scope with its
  raw and spelled-out name, folder and variation count. At most 400 records per request: choose a folder.
- **Answer:** up to 3 picks per sound, with the same verdicts. The page calls them same situation / close situation
  / related / different.
- The per-sound **Ask Claude** on a bark uses the same bark prompt, on that sound's top 8.

## 3. The Claude re-rank (`scripts/common/suggest_ai.py`, `suggest-ai/1`)

**Ask Claude** on a sound card sends one request. The server recomputes the shortlist itself (it never trusts the
page's copy).

- **Sent:** the MCC sound's English subtitle, speaker, level and tag name; the English line before and after it in
  the level; for each of the 8 shortlisted CE lines, the id, speaker, mission and English subtitle.
- **Never sent:** audio, Spanish text, paths or decisions.
- **Model and request:** `claude-opus-5-5`, effort `medium`, structured output (a JSON schema). The server-side
  refusal fallback is on (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`).
- **Answer:** for each candidate, a verdict (`same_line` / `reworded` / `related` / `different`), a confidence (0–1)
  and a short reason, best first. Ids that were not asked about are dropped, and so are repeats.
- **Cache:** answers go in `work/m4/suggest/ai/<sha256>.json` (git-ignored), keyed by model, prompt version, system
  prompt, schema and request text. Asking again is free.
- **Failures:** a refusal, a cut-off answer, an answer that isn't JSON, a missing SDK or an API error all give a 503
  with the reason. Nothing is cached from a failure.
- **Who:** on the remote listener the endpoint needs an admin account (`ADMIN_POSTS`), because it calls a paid API.
  The public listener refuses it, as it refuses every POST.

**Setup (owner):**
- Install the SDK (`pip install anthropic`). CLAUDE.md rule 5: it is not installed yet.
- Provide a credential in one of these ways:
  - `ANTHROPIC_API_KEY` in the environment;
  - the same key in the git-ignored `.env`;
  - an `ant auth login` profile.
- Until then the button is disabled and says why.

The server modules themselves stay stdlib only: `anthropic` is imported only inside `suggest_ai.rerank`, on demand.

## 4. API

| Endpoint | Does |
|---|---|
| `GET /api/suggest?level=&scope=mapped\|all\|M01&show=undecided\|all&limit=5&character=vo_sys_grunt\|all` | Scores for every sound of the level; `ai` = SDK/credential status |
| `POST /api/suggest/rerank` `{mcc_tag, scope, character}` | Claude's ranking of that sound's shortlist (cached) |
| `POST /api/suggest/folder` `{level, scope, character}` | Barks: Claude's picks for every unsubtitled sound of a level, one request (cached) |

Both are read-only for `mappings/`. Neither is in `public_view.PUBLIC_GETS`.

## 5. Tests

- `python -m unittest tests.test_suggest`: scoring, scope, filters, the read-only guarantee, and the re-rank with a
  stub client (shortlist only, no Spanish sent, unknown ids dropped, cache, refusal → 503).
- `npm run test:suggest` (browser, disposable data): the page lists scored lines, *Open* goes to Matching with the
  filter, the page fits at phone width, and the disposable and real mappings are unchanged.
