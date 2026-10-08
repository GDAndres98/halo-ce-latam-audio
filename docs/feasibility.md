# Feasibility Investigation: Halo CE LATAM Audio Mod

**Status:** Read-only research complete (two passes). No files were
modified, no tools were installed or executed, no archives were
extracted, no game assets were copied. Everything below comes from
directory inventories, reading plain-text and small binary index files
already present on disk (parsed in place with a short throwaway Python
script — no third-party tool was installed to do this), and public web
sources (cited inline).

**Dates:** 2026-10-07 (initial pass, §1–9); 2026-10-07 continued
(§10–13, focused on replacing existing MCC campaign dialogue); 2026-10-08
(§14, Stage 2A — first tool install, first actual audio decode).

---

## 1. Executive summary

- MCC ships a single Spanish dub (**Spain**), and its own support docs
  confirm **Spanish (Latin America) has interface text only, no audio** —
  this is the real gap the project wants to fill. [^langs]
- The classic Halo CE engine (MCC's `halo1`) stores campaign dialogue two
  ways: baked into each mission's compiled `.map` cache file, and as
  global per-language **FMOD FSB** sound banks
  (`halo1/sound/pc/sounds_dialogs_*.fsb`). Both are inspectable with
  existing community tooling without touching DRM.
- *Halo: Campaign Evolved* (2026, UE5) stores **all** content — including
  audio — inside UE5 IoStore containers (`.pak`/`.ucas`/`.utoc`) via the
  Wwise middleware. No loose/localized audio files exist on disk; nothing
  indicates the per-chunk encryption state from the filesystem alone.
- The **official HEK mod tools** (HCEEK) are present and match the
  classic Halo CE tool chain (`guerilla.exe`, `sapien.exe`, `tool.exe`).
  The documented sound-import command is `tool sounds <data-folder>
  <class> <compression> <split>`. [^toolsounds] Critically, **the kit's
  public tag set excludes all campaign dialogue tags** — confirmed by a
  zero-match grep across all 11,538 entries in `bin\!public_tags.txt`.
- A candidate line was identified from a public transcript (not
  extracted from any file): Cortana's in-combat gameplay bark **"Keep
  your head down! There's two of us in here now, remember?"**, spoken
  during *The Pillar of Autumn* level. [^transcript]
- Biggest blocker isn't technical — it's that 343 Industries' own MCC
  modding FAQ restricts mods to **assets contained within the retail MCC
  install**, which reads as prohibiting use of *Campaign Evolved* assets
  in an MCC mod. [^eulafaq] That needs resolving (or dropping as a source)
  before any pipeline work starts.
- **Continued investigation (§10):** directly parsing MCC's own
  `sounds_dialogs*.lst.bin` index files (read in place, nothing
  installed or extracted) confirms campaign dialogue is referenced by a
  **stable, human-readable tag name shared identically across all 8
  shipped languages** (e.g. `sound\dialog\a10\a10_350_captkeyes`), with a
  separate per-language `.fsb` sample bank supplying the audio. This
  reframes the recommended strategy away from "rebuild the whole HEK tag
  pipeline" and toward **replacing the audio inside the existing Spanish
  (Spain) slot** — the one language that already has a complete,
  working dialogue pipeline end-to-end. See §10.6 for why, and the scope
  limitation it implies (this would replace, not add to, the Spanish
  option).
- **Stage 1 execution (§11):** hashed and copied the real English and
  Spanish dialogue banks, then — with a dependency-free, hand-written
  reimplementation of the public FSB5 format, no tool installed —
  **directly confirmed** (not hypothesized) that index 30 is
  `A10_350_CaptKeyes` in **both** banks' own embedded name tables, with
  matching codec (**CELT**), sample rate (44,100 Hz), channels (mono),
  and duration (4.493 s identical in both languages). Actually decoding
  it to confirm the spoken words needs **vgmstream** — identified as the
  right tool (confirmed CELT/FSB support) but **not yet installed**,
  pending approval.
- **Stage 2A (§14):** with explicit approval, installed the official
  vgmstream r2117 release (hash-verified against GitHub's own asset
  digest, standalone CLI, no system-wide changes), confirmed it reads
  our copied banks identically to the Stage 1 hand-rolled parser, then
  decoded **5 scripted `a10` lines x 2 languages = 10 WAVs**, all
  duration-matched against the header metadata. A reusable,
  no-hardcoded-paths extraction script now lives in `scripts/`.
  **Spoken content is not yet confirmed by a human** — that's the next
  step, not done here.

---

## 2. Source: *Halo: Campaign Evolved* (`HALO_REMAKE_FOLDER`)

Confirmed via Steam/press coverage: a full Unreal Engine 5 remake of the
original *Halo: Combat Evolved* campaign (10 original missions + 3 new
prequel missions), releasing 2026 on Xbox, PC, Steam, and PS5. [^cereveal]

Directory inventory (read-only `find`, depth-limited):

```
Halo Campaign Evolved/
  Engine/                      # UE5 engine binaries & plugins
    Plugins/Wwise/              # Audiokinetic Wwise middleware — confirms
                                 # Wwise, not FMOD, drives this game's audio
    Plugins/Halo.External/...   # DLSS/FSR4/XeSS — cosmetic, not relevant
  Meteorite/                    # the actual game project ("Meteorite" codename)
    Binaries/Win64/HaloCampaignEvolved.exe
    Content/
      Movies/CinematicsPreRenders/<mission-code>/...   # pre-rendered cutscene
                                                        # folders, named with
                                                        # the SAME mission codes
                                                        # as classic CE (A15,
                                                        # A30, A50, B30, B40,
                                                        # C10, C20, C45, D20,
                                                        # D40, E10, E20, E30)
      Paks/
        global.ucas / global.utoc
        pakchunk0-Windows.{pak,ucas,utoc}   # 40+ GB — bulk of game content
        pakchunk1..530-Windows.{pak,ucas,utoc}  # ~60 additional chunks
```

### Audio container inventory

No loose audio files, no unpacked localization folders (no `L10n`, no
`WwiseAudio`, no per-language directories) exist anywhere on disk. All
content — meshes, textures, strings, and audio — is sealed inside the
UE5 **IoStore** container pair (`.utoc` = table of contents, `.ucas` =
chunk/asset store), the standard UE5 packaging format since ~4.25.
[^iostore] `global.utoc` begins with the IoStore TOC magic bytes
(`2d3d3d2d 2d3d3d2d 2d3d3d2d 2d3d3d2d`, i.e. `"-==--==--==--==-"`),
confirmed directly:

```
00000000: 2d3d 3d2d 2d3d 3d2d 2d3d 3d2d 2d3d 3d2d  -==--==--==--==-
```

**What this means for LATAM dialogue:** Wwise projects conventionally
store per-language voice as separate SoundBank variants selected at
runtime by language setting, cooked into the same IoStore virtual
filesystem rather than shipped as separate files — so no amount of
plain filesystem inspection will show "a LATAM folder" even if a LATAM
dub exists in this build. Confirming whether one exists requires opening
the containers with an IoStore-aware tool (see §4). **This was not
attempted** — whether these `.ucas` chunks are AES-encrypted is unknown
from the outside, and encrypted IoStore containers are common in UE5
shipping titles. Per project rules, we stop at that boundary rather than
search for or apply a key.

---

## 3. Target: Halo CE inside MCC (`HALO_MCC_FOLDER/halo1`)

Confirmed classic *Blam* engine layout (same as the 2004/2014 Halo CE /
Anniversary release family):

```
halo1/
  maps/            # compiled scenario cache files — one per mission/map
    a10.map         # "The Pillar of Autumn" (108 MB)
    a30.map b30.map b40.map c10.map c20.map c40.map d20.map d40.map ...
    custom_edition/ # bitmaps.map / loc.map / sounds.map — shared resource
                     # maps used by Custom-Edition-style UGC, not the SP
                     # campaign (SP maps embed their own resources)
  sound/pc/
    sounds_dialogs.fsb              # English (default) campaign dialogue
    sounds_dialogs_spanish.fsb      # Spanish — Spain dub (see §3.2)
    sounds_dialogs_french.fsb
    sounds_dialogs_german.fsb
    sounds_dialogs_italian.fsb
    lst/sounds_dialogs*.lst.bin     # index/lookup tables per bank
  terminals/       # Halo Anniversary terminal videos (.bk2) + transcripts (.xml)
```

`fmodex64.dll` alongside these confirms the **classic audio engine is
FMOD**, distinct from Campaign Evolved's Wwise. `.fsb` is FMOD's Sample
Bank container format; `.lst.bin` files are Bungie/343i's own
name-to-index lookup tables for the engine's sound-tag system.

### 3.1 How campaign dialogue is actually stored

Two layers, both native to the engine, neither encrypted:

1. **Tag layer** — each mission's `.map` is a compiled cache of *Blam*
   tags. A `sound` (or `sound_looping`) tag holds metadata (permutations,
   gain, pitch range, per-language flag) referencing raw sample data.
   For singleplayer maps, `build_all.bat` (shipped in HCEEK — see §4)
   builds them with `RESOURCE_MAP_USAGE=read_write`, meaning each
   mission's cache file embeds its own resources rather than referencing
   the shared `custom_edition\*.map` resource files multiplayer/UGC maps
   use.
2. **Global per-language sample layer** — the `sounds_dialogs_<lang>.fsb`
   banks hold the actual compressed audio referenced by those tags, one
   bank per localized language, selected by the game's active language
   setting at runtime.

### 3.2 Confirmed: there is no LATAM Spanish bank today

`halo1/sound/pc/` contains exactly one Spanish bank:
`sounds_dialogs_spanish.fsb`. Historically and per Microsoft's own
support documentation, that is the **Spain** Spanish dub — MCC's
language-support matrix explicitly separates "Spanish (Spain)" (full
audio + subtitles) from "Spanish (Latin America)" (**interface text
only**): [^langs]

> Spanish (Latin America) is supported with Interface localization only,
> while Spanish (Spain) has full support including Interface, Full
> Audio, and Subtitles.

This directly confirms the premise of the project: no LATAM dub exists
to extract or reuse — any LATAM audio has to be newly recorded, not
"unlocked" from an existing bank.

---

## 4. Official Mod Tools (`HALO_MOD_KIT_FOLDER` — HCEEK)

This is 343 Industries' official "Halo CE Editing Kit" for MCC, the
modern continuation of the original 2004 Gearbox HEK. Present at the
kit root, not yet extracted from its `.7z`:

```
HCEEK/
  guerilla.exe          # tag editor
  sapien.exe             # scene/level editor (scenario preview & placement)
  tool.exe               # command-line tag compiler / cache-file builder
  halo_tag_test.exe
  HCEEK.7z               # ~1 GB — full tags/ + data/ source tree (NOT extracted)
  README_MODDING.txt     # instructs: extract HCEEK.7z to get tags/ + data/
  build_all.bat          # reference build script, see below
  bin/!public_tags.txt   # 11,538-line manifest of every tag the kit exposes
  bin/!public_tags_extra.txt
  tools/dx11/fxc.exe     # shader compiler
```

`README_MODDING.txt` states plainly that the kit intentionally does not
auto-extract the archive, "to avoid future tool updates overwriting any
content you may have made changes to" — i.e. the 1 GB archive is the
actual source-tag payload (`tags/`, `data/`), and nothing has touched it
yet in this investigation.

### 4.1 Official build / import workflow

`build_all.bat` (shipped, read as-is) shows the documented per-mission
build invocation:

```
tool build-cache-file levels\a10\a10 remastered read_write 1
```

one such line per singleplayer mission (`a10` = Pillar of Autumn, `a30`,
`a50`, `b30`, `b40`, `c10`, `c20`, `c40`, `d20`, `d40`), confirming the
tag-source directory layout is `tags\levels\<code>\<code>.scenario` plus
siblings, matching the classic HEK convention.

For sound specifically, the documented `tool.exe` subcommand (confirmed
against community HEK documentation/forums, since the kit's own
in-depth docs are inside the not-yet-extracted archive) is: [^toolsounds]

```
tool sounds <data-folder> <class> <compression> <split>
```

- `<data-folder>` — a folder of source `.wav` files (22 kHz mono,
  uncompressed PCM is the traditional expectation) under `data\sound\...`
  mirroring the target `tags\sound\...` path.
- `<class>` — sound tag class/encoding target (e.g. dialogue).
- `<compression>` — e.g. `ogg`, `none`.
- `<split>` — long-sound splitting behavior for streamed sounds.

This compiles a `.sound` tag (and, for actor lines, a companion
`.dialogue` tag grouping permutations by vocalization state) that
`guerilla.exe` can inspect/edit and that `tool build-cache-file` then
bakes into the mission's `.map`.

### 4.2 Key finding: campaign dialogue tags are withheld from the kit

`bin\!public_tags.txt` enumerates every tag path the official kit
exposes as editable source (11,538 lines). Grepping it for
`sound\dialog` or any `levels\a10\...sound...` entry returns **zero
matches** anywhere in the singleplayer campaign tree. The only
`sound\dialog` entries in the entire manifest live under
`digsite\sound\dialog\slug\...` — a bundled **sample mod** ("digsite",
also built by `build_all.bat`) with a complete, fully-provided example:

```
digsite\sound\dialog\slug\allclear.sound
digsite\sound\dialog\slug\communication.sound
digsite\sound\dialog\slug\death_falling.sound
digsite\sound\dialog\slug\evade.sound
digsite\sound\dialog\slug\idle_combat.sound
digsite\sound\dialog\slug\idle_noncombat.sound
digsite\sound\dialog\slug\pain.sound
digsite\sound\dialog\slug\retreat.sound
digsite\sound\dialog\slug\searching.sound
digsite\sound\dialog\slug\sighted.sound
digsite\sound\dialog\slug\taunting.sound
digsite\sound\dialog\slug\slug.dialogue
```

This matches the same restriction the original 2004 Gearbox HEK shipped
with: singleplayer campaign voice-over was never provided as editable
source, only as compiled retail data. Practically, this means:

- There is no "drop in a new .wav and rebuild" path for campaign
  dialogue using the kit alone.
- Any real campaign-VO replacement workflow needs the target tag's name
  and structure **read out of the compiled retail `a10.map`** first
  (read-only tag inspection, not decompilation of code, not DRM — the
  Blam map format is an open, well-documented binary structure with no
  encryption) before `guerilla`/`tool` can be used to author a
  replacement.
- The "digsite" sample is the right low-risk stand-in for first proving
  out the *mechanics* of the sound-import → tag → cache-build pipeline,
  since its source `.wav`/tag data is fully provided and sanctioned by
  the kit itself.

---

## 5. Candidate dialogue line in *The Pillar of Autumn*

Identified from Halopedia's public mission transcript — **not** extracted
from any binary — so this is a citation, not an asset: [^transcript]

> **Character:** Cortana
> **Context:** in-gameplay combat bark, triggered after the Chief takes
> damage while shields are down, during the corridor-fighting section
> after leaving the bridge.
> **Line:** *"Keep your head down! There's two of us in here now,
> remember?"*

This is a good first PoC candidate because:

- It's a gameplay **bark**, not a pre-rendered or lip-synced cutscene
  line — no facial-animation re-sync constraint.
- It's clearly a repeatable, discrete `sound` tag permutation (likely
  under a `characters\cortana\dialog\...`-style path, by analogy with
  the `characters\captain\...` and `characters\cortana\...` tag trees
  already visible in `!public_tags.txt`), rather than baked into a
  cinematic.

Its exact internal tag name and current `.fsb` sample index are
**unconfirmed** — that requires read-only inspection of the compiled
`a10.map` (§6), which has not been performed yet.

---

## 6. Compatible inspection tools (researched only — none installed)

| Tool | Purpose | Note |
|---|---|---|
| **Reclaimer** (Gravemind2401) | Open-source Halo `.map` viewer/extractor; reads Halo 1–4 `.map` tag structures, exports bitmaps/models, has partial sound support for later titles. [^reclaimer] | Would be used read-only, against a local copy of `a10.map`, solely to **read** the target tag's name/metadata — not to repack anything. |
| **Assembly** | Older, still-used community Halo tag editor/extractor predating Reclaimer. | Alternative to Reclaimer for the same read-only step. |
| **python-fsb5** / **vgmstream** | Decode FMOD FSB containers (`sounds_dialogs*.fsb`) to WAV/OGG for listening/inspection. [^fsb5] | Would only be run against the existing retail `sounds_dialogs_spanish.fsb`/`sounds_dialogs.fsb` locally, never redistributed. |
| **FModel** / **CUE4Parse** / **UnrealPak** / **repak** | Standard UE5 IoStore (`.pak`/`.ucas`/`.utoc`) browsers, used to confirm whether Campaign Evolved's containers are encrypted and, if not, to enumerate Wwise `.bnk`/`.wem` assets inside. | **Not attempted.** If the containers prove encrypted, this path stops — no key search, per project rules. |

None of the above have been installed or run. Per the ground rules, the
next session should explicitly ask before doing so.

---

## 7. Blockers (ranked by how likely they are to kill the project as scoped)

1. **Cross-game asset-use restriction (policy, not technical).** 343
   Industries' MCC modding FAQ states: *"Only the assets contained within
   the retail version of MCC are allowed for use in modding efforts"* —
   read plainly, this excludes importing anything sourced from *Halo:
   Campaign Evolved* (a separate, 2026 product with its own EULA) into
   an MCC mod. [^eulafaq] *Campaign Evolved* itself has no official mod
   tools or stated modding policy yet; community mods for it already
   exist on Nexus Mods, but that doesn't establish a license to re-export
   its audio into a different game. **This should be resolved —
   ideally by treating Campaign Evolved purely as a non-redistributed
   creative/quality reference for a from-scratch LATAM recording, never
   as an audio source — before any pipeline is built.**
2. **Campaign dialogue tags are not in the official kit's source tree**
   (§4.2) — the only sanctioned way to learn the tag/permutation
   structure for a specific line is read-only inspection of the compiled
   retail map, which needs a third-party tool (ask-before-install).
3. **Campaign Evolved's container encryption status is unknown.** If
   encrypted, that source is closed off entirely under the "no
   DRM-bypassing" rule — but note this mostly matters only if blocker 1
   is somehow cleared, since otherwise Campaign Evolved isn't a licensed
   source anyway.
4. **No existing LATAM reference dub** (§3.2) — confirmed gap, not a
   blocker to *fixing* it, but it does mean there's no existing LATAM
   audio to use as a style/timing reference; new VO direction has to be
   created from scratch (likely against the English or Spain-Spanish
   track for timing only).

---

## 8. Licensing considerations

- **MCC asset reuse is explicitly sanctioned for modding** — "Anything
  contained within MCC is allowed to be used for modding efforts,"
  restricted to assets from the retail MCC install itself. [^eulafaq]
  This covers using the existing English/Spain-Spanish dialogue as a
  **local timing/reference guide** while directing new LATAM VO.
- **Monetization is currently disallowed** — 343i's FAQ states mods
  can't be sold or monetized (policy stated as subject to review). Keep
  this LATAM dub free/non-commercial.
- **Do not redistribute extracted original VO.** Even where reuse for
  local modding is permitted, nothing in the FAQ authorizes publishing a
  mod package that bundles ripped original English or Spain-Spanish
  dialogue audio. The shipped mod should contain **only the newly
  recorded LATAM lines** plus whatever tag/script glue is needed to wire
  them in — matching the `.gitignore`/repo rule of never committing
  original game audio.
- **Voice talent:** new recordings will need either licensed professional
  VO or clearly consented community contributors; this is a production
  concern for later, not a blocker to this feasibility pass, but worth
  flagging now since it affects scope/timeline.
- **Campaign Evolved as inspiration only:** given blocker 1, treat any
  listening/reference use of Campaign Evolved's dialogue (once
  technically accessible) as creative reference for direction/tone only
  — never as a redistributed or derived audio source in the shipped mod.

---

## 9. Proposed smallest practical proof-of-concept

Goal: prove the **mechanics** of the official sound-import → tag →
cache-build pipeline work end-to-end, without touching the cross-game
licensing question or any campaign VO yet.

1. **Ask for approval**, then extract `HCEEK.7z` (read-only payload
   unpack into the existing mod-kit folder — not a repo operation, no
   game files touched).
2. Record **one** short placeholder line (a throwaway line read by
   whoever is testing, in Spanish) as a 22 kHz mono WAV.
3. Use the already-provided, kit-sanctioned **"digsite" sample mod**
   dialogue slot (`digsite\sound\dialog\slug\allclear.sound` or similar)
   as the import target — replace its source `data\...\allclear.wav`
   with the placeholder recording.
4. Run `tool sounds digsite\sound\dialog\slug dialogue ogg 0` (exact
   flags to confirm against the kit's own docs once extracted) to
   recompile the `.sound`/`.dialogue` tag.
5. Run `tool build-cache-file digsite\levels\dusk\dusk remastered
   read_write 1` and load the result in `sapien.exe` to confirm the new
   line plays back correctly in-engine.
6. **Report back** whether the import pipeline behaved as documented,
   and only then take up: (a) resolving the cross-game asset question
   with Microsoft/343i or by dropping Campaign Evolved as a source
   entirely, and (b) the separate, higher-risk step of read-only
   `a10.map` tag inspection via Reclaimer to locate the real Cortana
   line's tag name.

This PoC deliberately never touches campaign maps, never touches
Campaign Evolved's containers, and never needs a LATAM recording of
actual licensed dialogue — it only proves the HEK's own documented,
sanctioned sound-import mechanism works on this machine.

---

## 10. Continued investigation: replacing *existing* MCC campaign dialogue

The first pass (§1–9) established that HCEEK can import sounds in
general, but that the campaign's dialogue tags are withheld from the
kit's public source tree. This pass stays within that constraint and
asks a narrower question: **can an existing campaign line, as it ships
today in MCC, be replaced — without the HEK's missing source tags?**

Method note: to answer §10.1–§10.2 below, two small per-language index
files already present in the retail install
(`halo1/sound/pc/lst/sounds_dialogs.lst.bin` and
`sounds_dialogs_spanish.lst.bin`) were read and parsed in place with a
~30-line throwaway Python script (fixed-width record parser: a 4-byte
flag, a 4-byte integer, a 4-byte length, then that many bytes of ASCII
text). This is a plain binary-structure read, not a tool install, not an
archive extraction, and not a modification — the files were opened
read-only and nothing on disk changed.

### 10.1 How campaign dialogue is stored and referenced — **VERIFIED**

Every `sounds_dialogs*.lst.bin` file is a flat, fixed-schema index of
**1,903 records**, each `(flag: int32, count: int32, name: string)`.
Directly parsed examples from the English file:

```
(1,    1903, "sound\dialog\a10\a10_010_cryotech")
(0,    1,    "sound\dialog\a10\a10_011_cryoassist")
(1,    1,    "sound\dialog\a10\a10_020_cryotech")
...
(29,   1,    "sound\dialog\a10\a10_350_captkeyes")
...
(?,    1,    "sound\dialog\a10\a10_641_cortana")   # one of many a10 Cortana lines
...
(?,    1,    "sound\dialog\a10\a10_flavor_010_cortana")  # ambient/idle "flavor" bark
```

**101 of the 1,903 entries belong to `a10` (*The Pillar of Autumn*)**,
with readable, self-describing names following a `<level>_<sequence>_
<character>` scheme — e.g. `a10_350_captkeyes`, `a10_570_bisenti`,
`a10_580_aussie`, plus a `a10_flavor_0NN_cortana` block (ambient combat
barks — almost certainly where a line like the §5 Cortana quote lives)
and a `a10_6NN`–`a10_8NN_cortana` block (scripted sequence lines).

**Comparing all 8 shipped language files** (`sounds_dialogs[.{spanish,
french,german,italian,japan,korean,chinese}].lst.bin`) confirms their
**name lists are 100% identical, same order, same 1,903 entries, for
every language**, including Spanish. This is the mechanism behind
per-language dialogue switching: one shared, language-independent index
of tag *names*, paired with one `sounds_dialogs_<lang>.fsb` sample bank
per language — not (as in the original 2004 PC release) entirely
separate per-language installs.

**What's unconfirmed:** the exact *selection logic* the game executable
uses to pick a `.lst.bin`/`.fsb` pair based on the active language
setting lives in compiled game code, not in any file inspected here —
that part is inferred from the data layout, not observed directly.

### 10.2 The `(flag, count)` fields are not fully understood — **MIXED: verified data, hypothesis on meaning**

Comparing the `(flag, count)` pair position-by-position between the
English and Spanish index (not just the names, which match 100%):
the **first ~690 entries match exactly** (this covers all per-level
scripted campaign dialogue, including every `a10` entry), but **1,212 of
the remaining ~1,213 entries differ** — all of them generic,
non-level-prefixed character barks such as
`sound\dialog\captain\pain_major` or
`sound\dialog\crewman\conditional\combat\actions\flee`.

Working hypothesis (not verified against source code or documentation):
the second field is a **permutation count**, not a positional pointer —
scripted single-take lines (like our Cortana/Keyes candidates) always
show `count = 1` and therefore match across every language, while
generic ambient barks have language-specific alternate-take counts (a
dub studio may have recorded a different number of variants per
language), which is why only that block diverges. **This matters for
§10.7**: a real `a10` line replacement likely only has to deal with
`count = 1` (simple one-for-one swap), which is the easier case — but
this has not been confirmed against the actual `.fsb` binary layout or
any authoritative format doc, and should be treated as a hypothesis to
validate, not a design assumption to build on yet.

### 10.3 Can HCEEK or community tools replace it? — **VERIFIED (capability), ⚠ (workflow gap remains)**

- **HCEEK / official `tool.exe`:** No change from §4 — still cannot
  touch campaign dialogue, because the source tags for it are withheld
  from the kit regardless of which lookup table exists at runtime.
- **Invader** (open-source, GPLv3, actively maintained,
  `github.com/SnowyMouse/invader`): confirmed via its own GitHub repo to
  explicitly support **`mcc-cea`** as a build-engine target alongside
  `gbx-custom`/`gbx-retail`/the Xbox variants. [^invader] Its
  `invader-extract` tool extracts tags from a cache file, with recursive
  dependency extraction, back into editable source form. This means a
  campaign map's tags **can, in principle, be pulled out of the retail
  `a10.map` into editable source** — sidestepping the "not in the public
  kit" blocker entirely, since the source would come from the compiled
  map itself, not the kit. However, `invader-build` (like `tool.exe`)
  rebuilds **whole cache files from a complete tag directory** — there
  is no documented "patch just this one tag back into the existing map"
  shortcut; a full campaign map rebuild would be needed. Not attempted.
- **Reclaimer** (open-source, `github.com/Gravemind2401/Reclaimer`):
  its own GitHub page explicitly lists **".map files from Halo MCC PC"**
  as a supported format (distinct from, and in addition to, original
  Xbox/Custom Edition formats), confirming direct compatibility with the
  exact `a10.map` in this install. [^reclaimer2] Its documentation (as
  fetched) emphasizes geometry/model export; it does not clearly
  document sound-tag extraction, so whether it can pull a `.sound` tag's
  audio out of `a10.map` specifically is **unconfirmed** and would need
  hands-on testing.
- **Assembly**: 343 Industries' own MCC modding FAQ names "HEK, Assembly,
  and Reclaimer" together as tools modders are permitted to use.
  [^eulafaq] This confirms *sanction*, not *capability* — I found no
  direct technical documentation confirming Assembly's current support
  for MCC's specific map build, so treat that as **unconfirmed,
  needs-verification** rather than assumed working.

### 10.4 Whether campaign sound tags can be reconstructed — **HYPOTHESIS, with supporting precedent**

Reconstructing a full, editable `.sound`/`.dialogue` tag for an `a10`
line (needed for the "rebuild the whole map" path in §10.3) has not been
attempted here. But there is now a close **precedent on the other
engine**: community mods for *Halo: Campaign Evolved* itself already do
the equivalent job on its (different) Wwise/UE5 system. Nexus Mods
hosts, among others:

- **"Cortana Restored"** — replaces Campaign Evolved's re-recorded
  Cortana lines with the original Combat Evolved performance, using
  **wwiser** for Wwise SoundBank/HIRC structure parsing and **repak**
  for Unreal `.pak` extraction/repackaging. [^cortanarestored]
- **"VF Originale 2001"** — restores the original 2001 French dub into
  Campaign Evolved by the same kind of process. [^vforiginale]
- **"Odyssey – Classic Audio"** — notably, its author states the mod
  recreates classic-game audio *without using any original game assets*,
  by sourcing the same commercial stock sound libraries the original
  developers used. [^odyssey]

These mods confirm that line-level dialogue/audio replacement — including
porting a specific character's lines **between the classic engine and
Campaign Evolved** — is an established, tool-supported community practice
today, using FModel, vgmstream, wwiser, repak, ffmpeg, faster-whisper,
Audacity, and Python. [^cortanarestored] None of the located mods go in
our project's actual direction (MCC ← Campaign Evolved); they all go the
other way (Campaign Evolved ← classic Combat Evolved) or stay within one
game. That still doesn't resolve the §7 cross-game-asset-use question for
our direction — if anything, the "Odyssey" author's choice to avoid
reusing original assets entirely is the more risk-averse model to follow.

### 10.5 How MCC language selection affects voice playback — **PARTLY VERIFIED**

Verified (§10.1): a stable, language-independent name index selects
*which* line, and a separate per-language `.fsb` supplies *the audio*
for the player's selected language. Unverified: the in-engine trigger
that reads the player's language setting and chooses which `.lst.bin`/
`.fsb` pair to load — that logic lives in compiled code we have not
inspected (and should not reverse-engineer beyond this structural
read). It's also unconfirmed whether `.map`-embedded tag metadata
(e.g., the classic per-tag "language" field reported anecdotally in
older Halo CE modding discussions) plays any role alongside this MCC-era
`.lst.bin`/`.fsb` layer, or whether MCC's layer has fully superseded it
for dialogue specifically — treat any claim about a tag-level "language"
field as **unconfirmed** until seen directly in an extracted tag.

### 10.6 Could Spanish (Spain) audio be the replacement target? — **Recommended strategy, not yet validated**

Yes — of every candidate, this is now the most structurally promising
path, and is the **recommended strategy** going forward:

- Spanish is the **only** non-English slot with a complete, working,
  end-to-end pipeline already wired into the shipped game — interface,
  subtitles, *and* audio (§3.2). [^langs]
- Its `.lst.bin` is byte-for-byte identical in name and (for every
  scripted campaign line, including all of `a10`) in structure to
  English's (§10.1–§10.2) — meaning the "slot" a LATAM line would need
  to fill already exists, indexed, loaded, and exercised by the game
  every time a player picks Spanish.
- This reframes the mod from "teach the engine a new language" (which
  would need compiled-code changes, out of scope for any tags/data mod)
  to **"replace the audio inside the existing Spanish slot"** — a data
  swap, not a new feature.

The hard limitation this implies, and that should be set as explicit
scope with whoever commissions this mod: **there is no way, as a
data-only mod, to add a selectable "Spanish (Latin America)" option
next to "Spanish (Spain)" in the options menu.** The language list itself
is compiled into the game executable. What's achievable is a full
replacement of what plays when a player selects "Spanish" — i.e., this
would ship as a *Spanish (Spain) dub replacement*, not an additive LATAM
option, unless 343 Industries themselves added a new slot. That's a
product/scope decision, not a technical one, and should be surfaced to
whoever is sponsoring this mod before further work.

### 10.7 Proof of concept: replacing one campaign line — **proposed, not executed**

Still not attempted (would require tool installation — ask first — and,
for the final steps, a sandboxed copy rather than the live install):

1. **Ask for approval**, then use a read-only FSB5 decoder (e.g.
   python-fsb5 or vgmstream — not yet installed) against a **copy** of
   `sounds_dialogs_spanish.fsb` to extract the sample at the same
   ordinal position as a known, `count = 1` `a10` entry (e.g. position 29,
   `a10_350_captkeyes`, chosen because it's short, early, and
   unambiguous). Listen to confirm it is indeed that line in Spanish, and
   that the same ordinal position in the English bank is the matching
   English line. This single step validates or kills the "ordinal
   position = same line across languages" hypothesis from §10.1/§10.2
   before anything else is built on it.
2. If confirmed: record **one** throwaway placeholder line (not a real
   localization take) at matching sample-rate/channel settings.
3. Using an FSB5 rebuild tool (e.g. FSBLib) against the **copy**, replace
   only that one sample, preserving every other sample and the bank's
   internal structure, and regenerate a matching `.lst.bin` (likely
   just copying the original, since names/order don't change).
4. Point a local, non-destructive test setup (not the live MCC
   install) at the modified copy and confirm the game — or, failing
   that, vgmstream/a standalone FMOD sample player — accepts the
   rebuilt file and plays the new sample at the right position.
5. Report back findings on both the `.fsb` rebuild tool's reliability
   (per §10.3's noted limitation: FSB5 repacking tools are less mature
   than extraction tools) and whether the game actually loads a modified
   bank at all without additional hashes/signature checks we haven't
   looked for yet.

This deliberately still avoids: extracting HCEEK's archive, touching any
`.map` file, and touching anything from Campaign Evolved.

### 10.8 Technical limitations and distribution restrictions

- **FSB5 repacking is the weak link.** Multiple sources note that
  rebuilding an FSB5 file while perfectly preserving its original
  internal metadata/structure is harder than extracting from one, and
  typically needs either FMOD's own `fsbank` tooling or a dedicated
  library (e.g. FSBLib). [^fsbrepack] This is the single biggest
  technical unknown blocking §10.7 from being more than a plan.
- **No additive new language slot** is possible without engine code
  changes (§10.6) — a hard ceiling on scope for a tags/data-only mod.
- **Distribution still sits inside 343i's MCC modding FAQ** (§7–8):
  non-commercial only, retail-MCC-assets only. Building the replacement
  Spanish `.fsb` from **newly recorded LATAM audio only** (never
  redistributing the original Spain dub's extracted samples) keeps the
  shipped mod's own legal position clean regardless of how the
  cross-game question resolves, matching the "Odyssey" mod's own stated
  approach (§10.4).
- **Community precedent exists, but isn't a legal green light.** The
  Campaign Evolved dialogue-replacement mods in §10.4 show 343i has not
  (as of this writing) evidently acted against this category of mod —
  useful context, not a substitute for actually resolving the §7
  cross-game-asset question if Campaign Evolved audio is ever used as a
  reference.

---

## 11. Stage 1 execution: identifying, hashing, and index-mapping the Spanish dialogue bank

Executed 2026-10-07, scoped strictly to **Stage 1** of the replacement
plan (identify/verify/inspect one existing line — no repacking, no
installed tools, nothing touched in place). Everything below was done
against **copies**; the live MCC install was only ever opened for
reading, to compute hashes and to make the copies.

### 11.1 File paths — **VERIFIED**

| Role | Path | Size |
|---|---|---|
| English dialogue bank | `HALO_MCC_FOLDER\halo1\sound\pc\sounds_dialogs.fsb` | 330,091,232 bytes |
| Spanish dialogue bank | `HALO_MCC_FOLDER\halo1\sound\pc\sounds_dialogs_spanish.fsb` | 309,320,800 bytes |
| English index | `HALO_MCC_FOLDER\halo1\sound\pc\lst\sounds_dialogs.lst.bin` | 120,876 bytes |
| Spanish index | `HALO_MCC_FOLDER\halo1\sound\pc\lst\sounds_dialogs_spanish.lst.bin` | 120,876 bytes |

### 11.2 Original file hashes (SHA-256) — **VERIFIED**

Computed in place, before any copying:

```
8d072c1b73b9a8f6d7269ff1e3bb8d99b49d76a6e040ea0edf997446cbcba4b  sounds_dialogs.fsb
ed0ff3ec240546611a62d2a23d6ce66b5cd7af17527bf1b12834a77fa91faef  sounds_dialogs_spanish.fsb
566235e5b844f6e859b454fa732f9dec8f316cdeb56eb49602c3b7226174619  sounds_dialogs.lst.bin
d5324861186f079c8d436f598b0adcafba259259eaa56be57d987df68cdaffc  sounds_dialogs_spanish.lst.bin
```

### 11.3 Working copies — **VERIFIED**

All subsequent inspection used copies at
`reference-audio/stage1/{fsb,lst,extract}/` inside this repo — a path
already covered by `.gitignore` (confirmed with `git check-ignore`), and
outside the Steam library entirely. Hashes of the copies were
re-verified identical to §11.2 immediately after copying (bit-for-bit,
no corruption/transform during copy).

### 11.4 FSB5 inspection tool — **researched, not installed**

No third-party tool was installed for Stage 1. Metadata-level inspection
was done with a ~100-line, dependency-free Python script written for
this session, implementing the publicly documented FSB5 container
format: a fixed 60-byte header (`magic, version, numSamples,
sampleHeadersSize, nameTableSize, dataSize, mode`, + reserved fields),
followed by one 64-bit packed bitfield per sample (next-chunk flag,
frequency-table index, mono/stereo flag, data offset, sample count),
optional per-sample metadata chunks, and an optional name table. This
layout was reconstructed from the published structure of the
`HearthSim/python-fsb5` project (read, not installed, not imported — the
parser here is an independent reimplementation). [^pyfsb5]

For **decoding** (actually turning a sample into audible audio), that
same reimplementation is not viable: see §11.7. A real decode needs an
installed tool — **not yet done, pending approval** (see §13/Stage 2
below).

### 11.5 Locating one `a10` scripted dialogue entry — **VERIFIED**

Both banks carry their own internal name table (one name per sample,
`nameTableSize` > 0), independent of the `.lst.bin` files. Searching it
for `captkeyes` surfaces, among others, index **30**:

- English bank, index 30: name `A10_350_CaptKeyes`
- Spanish bank, index 30: name `A10_350_captkeyes`

This is a short, early, single-character scripted line (Captain Keyes,
*The Pillar of Autumn*) — a good minimal PoC target, distinct from the
earlier §5 Cortana combat-bark candidate (which remains locatable the
same way, by searching both banks' name tables for `cortana` under the
`a10` prefix — not repeated here to keep Stage 1 minimal).

### 11.6 Verifying the index-to-sample mapping — **VERIFIED (stronger than the §10 hypothesis)**

§10.1–§10.2 had hypothesized that `.lst.bin` position alone maps a line
across languages. That is now superseded by a direct, stronger check:
**each FSB5 file carries its own embedded sample name**, so no
positional inference is needed at all — index 30 is independently
confirmed to be `A10_350_CaptKeyes`/`A10_350_captkeyes` **by reading the
name directly out of each bank**, in both languages. This is the
authoritative mapping mechanism for this task; the `.lst.bin` files are
a secondary/alternate index whose exact internal field semantics remain
only partly understood (see caveat below) and are not needed for this
mapping.

**Caveat, honestly flagged:** a cross-check attempt — summing the
numeric "count" field across all 1,903 `.lst.bin` entries and comparing
it to each bank's actual `numSamples` (6,093 English; 5,696 Spanish) —
did **not** match (off by exactly 1,902 in both languages, suggestive of
an off-by-one/header artifact in how this session's ad hoc parser
splits the first record from the rest, not re-derived further). The
`.lst.bin` record-level field meaning is therefore marked **unresolved**
rather than asserted. It doesn't block anything: the FSB5 name table in
§11.5 already gives a clean, direct answer.

### 11.7 Inspecting the sample — codec, duration, rate, channels, metadata — **VERIFIED (metadata); NOT decoded**

For the index-30 sample, in both banks:

| Field | Value | How known |
|---|---|---|
| Codec (`mode`) | `12` | read directly from the FSB5 header |
| Codec name | **CELT** | `mode` 12 maps to `CELT` in python-fsb5's published `SoundFormat` enum order (`NONE, PCM8, PCM16, PCM24, PCM32, PCMFLOAT, GCADPCM, IMAADPCM, VAG, HEVAG, XMA, MPEG, CELT, AT9, XWMA, VORBIS`) [^pyfsb5], independently corroborated by vgmstream's own format docs listing "CELT (FSB)" / `CELT_FSB` as a real, supported FSB/FSB5 codec [^vgmformats] |
| Sample rate | 44,100 Hz | FSB5 frequency-index lookup table |
| Channels | 1 (mono) | FSB5 per-sample channel bit |
| Sample count | 198,144 | FSB5 per-sample header |
| Approx. duration | **4.493 s** | `sample_count / frequency`; identical in both languages for this line (consistent with a cutscene-length-locked take) |
| Compressed size | 146,304 bytes | derived from this sample's data offset to the next sample's data offset |
| Attached metadata chunk | type `3`, size 8 bytes | present on nearly every sample in both banks; **meaning not confirmed** — plausibly a loop-point pair, typically inert for non-looping dialogue, not decoded or interpreted further |

The 146,304-byte compressed blob was copied out **byte-for-byte, with no
decoding**, for both languages, to
`reference-audio/stage1/extract/a10_350_captkeyes_{en,es}.celt.raw`.
These are **not standalone playable files** — they are raw CELT frame
data sliced out of the bank, not a self-contained CELT/WAV/OGG container
— and are excluded from Git by the existing `*.raw`-catching ignore
rules (`*.wav`/`*.ogg` patterns plus the blanket `/reference-audio/`
rule).

**Spoken-content confirmation (§8 "confirm its spoken dialogue") was
NOT completed.** CELT is an old, non-self-describing speech codec
(Xiph's pre-Opus codec); it is not something this session can safely
hand-decode, and I (the assistant) have no audio-playback capability in
any case. Confirming what index 30 actually says needs either a human
listening to a decoded export, or a speech-to-text tool — both require
an approved next step (§13).

### 11.8 Recommended decode tool for Stage 2 — **researched, not installed**

- **python-fsb5** was useful for understanding the *container* format
  (§11.4) but its own documentation only advertises PCM/MPEG/Vorbis
  sample decoding — **not CELT** — so it is the wrong tool for actually
  decoding this specific sample.
- **vgmstream** (open-source, widely used in game-audio preservation;
  the same tool cited by the existing Campaign Evolved dialogue-mod
  precedent in §10.4) explicitly lists **CELT (FSB)** support for both
  legacy FSB and FSB5 containers in its own format documentation, with
  no external DLL dependency noted. [^vgmformats] This makes it the
  clear recommended choice if/when decoding is approved.

Neither has been installed. Per the ground rules, that's an explicit
ask, not a default next action — see the Stage 2 proposal below.

---

## 12. Updated facts for CLAUDE.md / future sessions

- `sound\dialog\a10\a10_350_captkeyes` is a verified, concrete, minimal
  example of a line that exists, identically named and indexed (index
  30), in both the English and Spanish dialogue banks — useful as the
  running example for any future PoC work.
- The authoritative way to map a dialogue line across language banks is
  each **FSB5 file's own embedded name table** (§11.5–11.6), not the
  `.lst.bin` files (whose exact field semantics remain unresolved).
- The dialogue codec is **CELT** (confirmed), which rules out
  python-fsb5 for decoding and points to **vgmstream** instead.

---

## 13. Proposed Stage 2 (not started) + rollback instructions

**Stage 2 goal:** go from "verified metadata" to "confirmed audible
content," still without repacking anything or touching the live
install.

1. **Ask for approval** to install **vgmstream** (CLI build), the tool
   identified in §11.8. Nothing else needs installing for this step.
2. Run it only against the **copies** in `reference-audio/stage1/fsb/`
   (never the live install), decoding index 30 from both
   `sounds_dialogs.fsb` and `sounds_dialogs_spanish.fsb` to WAV.
3. Hand the two WAV files to a human (or, if separately approved, a
   speech-to-text tool) to confirm what Captain Keyes' `A10_350`
   line actually says in each language, and that both decode cleanly
   (no garbage audio, which would indicate a bitfield-parsing mistake
   in §11.4's reimplementation).
4. Only *after* that confirmation, start scoping actual repacking
   (still not part of Stage 2): what FSB5 rebuild tool can re-insert a
   replacement CELT or re-encoded sample at index 30 while leaving
   every other byte of the bank untouched, and whether the game
   validates the bank's integrity (hash/signature) at load time —
   unknown, not yet investigated.

**Rollback instructions (for everything done in Stage 1, and anything
Stage 2 would add):**

- Nothing under the Steam install (`HALO_MCC_FOLDER`) was ever opened
  for writing. There is nothing to roll back there — the original
  files were only read, and §11.2's hashes are recorded precisely so a
  future session (or the user) can re-verify that remains true at any
  time with `sha256sum` (or `Get-FileHash` in PowerShell).
- Everything written by Stage 1 lives under
  `reference-audio/stage1/` in this repo (copies, the raw `.celt.raw`
  slices) — already git-ignored. Deleting that one folder fully
  reverts Stage 1's on-disk footprint; nothing else in the repo or the
  game install needs any cleanup.
- If vgmstream is installed for Stage 2, it should be installed as a
  standalone CLI tool in a user-chosen location outside both the Steam
  library and this repo (e.g. a tools folder), so uninstalling is just
  deleting that folder — not a system-wide install, no registry/PATH
  changes should be made without a separate, explicit ask.

---

## 14. Stage 2A execution: tool install + decoding 5 scripted `a10` lines

Executed 2026-10-08, with explicit user approval to install vgmstream
from its official GitHub releases. Still no repacking, no writes to any
`.fsb`, and no touching the live MCC install beyond the read-only
hashing already done in Stage 1.

### 14.1 Installing vgmstream — source and compatibility verified first

- Queried the **official** `vgmstream/vgmstream` GitHub repo's releases
  API directly (`api.github.com/repos/vgmstream/vgmstream/releases/latest`),
  not a mirror or third-party download site. Latest release: **r2117**,
  published 2026-05-19 by `bnnm` — a long-standing vgmstream maintainer
  whose account is linked from the project itself.
- Downloaded `vgmstream-win64.zip` (the correct asset for this Win64
  machine) via its `browser_download_url`, and verified it **byte-for-
  byte against the SHA-256 digest GitHub itself computed and attached to
  the release asset** (not a digest vgmstream's authors published
  separately, but GitHub's own `digest` field on the asset object) —
  computed hash matched exactly:
  `6c4a8a3813864fefed081bbd337dbc0ad93bf88e0b92f5db98d7ab258b22dc6c`.
- Extracted as a **standalone, no-installer** CLI tool to
  `D:\Tools\vgmstream-r2117\` — outside both the Steam library and this
  git repo, nothing added to PATH or the registry. The archive itself
  (`vgmstream-win64.zip`) and the extracted folder are **not** part of
  this repo (a separate location entirely, not even covered by this
  project's `.gitignore` since it isn't under the repo at all).
- License: permissive ISC-style ("Copyright (c) 2008-2026 Adam Gashlin,
  ..., bnnm, ... Permission to use, copy, modify, and distribute this
  software for any purpose with or without fee is hereby granted..."),
  bundled `COPYING` file read directly.
- **Compatibility verified before any decoding**: ran
  `vgmstream-cli -m -s 31` (metadata-only, no file written) against both
  copied banks at the known index-30 sample. Output matched this
  session's independent Stage-1 FSB5 parser **exactly** — same sample
  rate, channel count, sample count/duration, and sample name — and
  additionally identified the codec precisely as **"Custom CELT"**
  (vgmstream's own, more specific label; it ships two bundled codec
  DLLs, `libcelt-0061.dll` and `libcelt-0110.dll`, confirming native,
  no-extra-setup CELT/FSB support exactly as §11.8 predicted).

### 14.2 Samples selected

Five named, single-take scripted `a10` lines (none of the random-
permutation `flavor` barks), each confirmed present **at the same
index in both language banks** by direct name-table lookup (same method
as §11.5/§11.6, extended to more names):

| Sample | English index | Spanish index | Same index? |
|---|---|---|---|
| `a10_010_cryotech` | 0 | 0 | yes |
| `a10_011_cryoassist` | 1 | 1 | yes |
| `a10_350_captkeyes` | 30 | 30 | yes |
| `a10_370_captkeyes` | 32 | 32 | yes |
| `a10_641_cortana` | 51 | 51 | yes |

### 14.3 Reusable extraction script

Added to this repo (plain code, no game data, safe to commit):

- [`scripts/fsb5_lib.py`](../scripts/fsb5_lib.py) — the Stage 1 FSB5
  parser, promoted from a scratch script into a small reusable module
  (`FsbBank` class: parses header/samples/name-table, `.find(name)`,
  `.duration_seconds(index)`).
- [`scripts/extract_dialogue_samples.py`](../scripts/extract_dialogue_samples.py)
  — takes `--en-fsb`, `--es-fsb`, `--vgmstream-cli`, `--names`,
  `--out-dir`, `--csv-out` as **required arguments** (no hardcoded
  Steam/tool/repo paths anywhere), looks up each name in both banks,
  shells out to `vgmstream-cli -s <subsong> -o <wav>` to decode, reads
  the resulting WAV's own duration back with Python's stdlib `wave`
  module, and writes one CSV row per (sample, language) pair.

### 14.4 Results — **VERIFIED**

All 10 (5 samples × 2 languages) decoded successfully
(`vgmstream_returncode = 0` for every row), and every row's
`duration_match` is `True` — the WAV file vgmstream produced has the
exact same duration as this session's hand-rolled FSB5 header parser
computed independently, which is a strong cross-validation that both
the Stage-1 parser and the decode are correct and self-consistent.

| sample_name | language | index | freq | ch | codec | header_dur_s | wav_dur_s | match |
|---|---|---|---|---|---|---|---|---|
| a10_010_cryotech | english | 0 | 44100 | 1 | CELT | 3.564 | 3.564 | ✓ |
| a10_010_cryotech | spanish | 0 | 44100 | 1 | CELT | 3.553 | 3.553 | ✓ |
| a10_011_cryoassist | english | 1 | 44100 | 1 | CELT | 2.334 | 2.334 | ✓ |
| a10_011_cryoassist | spanish | 1 | 44100 | 1 | CELT | 2.926 | 2.926 | ✓ |
| a10_350_captkeyes | english | 30 | 44100 | 1 | CELT | 4.493 | 4.493 | ✓ |
| a10_350_captkeyes | spanish | 30 | 44100 | 1 | CELT | 4.493 | 4.493 | ✓ |
| a10_370_captkeyes | english | 32 | 44100 | 1 | CELT | 1.173 | 1.173 | ✓ |
| a10_370_captkeyes | spanish | 32 | 44100 | 1 | CELT | 1.173 | 1.173 | ✓ |
| a10_641_cortana | english | 51 | 44100 | 1 | CELT | 4.679 | 4.679 | ✓ |
| a10_641_cortana | spanish | 51 | 44100 | 1 | CELT | 4.702 | 4.702 | ✓ |

Full machine-readable report (same data as above, plus the local WAV
paths): `reference-audio/stage1/stage2a_report.csv` — **git-ignored**,
not part of this repo.

Decoded WAV files, for manual listening, all under
`reference-audio/stage1/wav/` (git-ignored):

- `a10_010_cryotech_english.wav` / `a10_010_cryotech_spanish.wav`
- `a10_011_cryoassist_english.wav` / `a10_011_cryoassist_spanish.wav`
- `a10_350_captkeyes_english.wav` / `a10_350_captkeyes_spanish.wav`
- `a10_370_captkeyes_english.wav` / `a10_370_captkeyes_spanish.wav`
- `a10_641_cortana_english.wav` / `a10_641_cortana_spanish.wav`

### 14.5 What is *not* claimed yet

**Spoken dialogue content has not been verified by anyone in this
session.** Everything in §14.4 is metadata/duration cross-validation,
not a transcript check — I (the assistant) have no audio-playback
capability and did not claim otherwise. Whether e.g.
`a10_350_captkeyes_english.wav` actually says a given line, and whether
its Spanish counterpart is a faithful dub of it, is pending the user's
own listen. Until that happens, treat "these are the right, playable
lines" as **well-supported but user-unconfirmed**.

No FSB5 bank was modified or repacked. The only new on-disk state is:
the `D:\Tools\vgmstream-r2117\` install (outside the repo and Steam),
and the git-ignored `reference-audio/stage1/wav/*.wav` +
`stage2a_report.csv` (outside Git, inside the repo's working tree).

---

## Sources

[^langs]: [Which Languages Can I Play Halo: The Master Chief Collection In?](https://support.halowaypoint.com/hc/en-us/articles/360057636612-Which-Languages-Can-I-Play-Halo-The-Master-Chief-Collection-In) — Halo Support.
[^cereveal]: [Halo: Campaign Evolved – Answering the Big Questions About This Ambitious Remake](https://news.xbox.com/en-us/?p=213485) — Xbox Wire.
[^iostore]: Unreal Engine IoStore/`.utoc`/`.ucas` container format — standard UE5 packaging since 4.25; TOC magic bytes confirmed directly against `global.utoc` in this repo's target install.
[^toolsounds]: `tool sounds` command usage — community-documented on the Halo Custom Edition modding forum (halomaps.haloman30.com), consistent with the classic HEK `tool.exe` command set used by `build_all.bat` in this install's HCEEK.
[^reclaimer]: [Reclaimer](https://github.com/Gravemind2401/Reclaimer) / [ModDB listing](https://www.moddb.com/games/halo-combat-evolved/downloads/reclaimer-1-5-245) — open-source Halo 1–4 map/tag viewer and extractor.
[^fsb5]: [python-fsb5](https://pypi.org/project/refinery/) and vgmstream — open-source FMOD FSB audio extraction tools.
[^transcript]: [The Pillar of Autumn (Halo: Combat Evolved level)](https://www.halopedia.org/The_Pillar_of_Autumn_(Halo:_Combat_Evolved_level)) — Halopedia mission transcript.
[^eulafaq]: [MCC's EULA: The FAQ](https://www.halowaypoint.com/news/mccs-eula-the-faq) — Halo Waypoint, official 343 Industries modding policy FAQ.
[^invader]: [Invader](https://github.com/SnowyMouse/invader) — open-source Halo CE modding toolkit (GPLv3), confirmed `mcc-cea` build-engine target.
[^reclaimer2]: [Reclaimer](https://github.com/Gravemind2401/Reclaimer) — confirmed support for ".map files from Halo MCC PC".
[^cortanarestored]: ["Cortana Restored"](https://www.nexusmods.com/halocampaignevolved/mods/78) — Halo: Campaign Evolved Nexus Mods page; tools cited: wwiser, repak.
[^vforiginale]: ["VF Originale 2001 - Le Doublage Francais Historique"](https://www.nexusmods.com/halocampaignevolved/mods/52) — Halo: Campaign Evolved Nexus Mods page.
[^odyssey]: ["Odyssey - Classic Audio"](https://www.nexusmods.com/halocampaignevolved/mods/43) — Halo: Campaign Evolved Nexus Mods page; author states original assets were not reused.
[^fsbrepack]: [FSBLib](https://www.nuget.org/packages/FSBLib) and the [FMOD FSBank API reference](https://www.fmod.com/docs/2.00/api/fsbank-api.html) — FSB5 rebuilding/repacking tooling, as distinct from extraction-only tools.
[^pyfsb5]: [python-fsb5](https://github.com/HearthSim/python-fsb5) — published FSB5 header/bitfield/name-table layout and `SoundFormat` codec enum, used here only as a structural reference (reimplemented independently, not installed/imported).
[^vgmformats]: [vgmstream FORMATS.md](https://github.com/vgmstream/vgmstream/blob/master/doc/FORMATS.md) — lists "CELT (FSB)" / `CELT_FSB` support for both legacy FSB and FSB5 containers.
