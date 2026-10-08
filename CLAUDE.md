# Halo CE LATAM Audio — Project Guide

## Goal

Produce a Latin American Spanish voice localization **mod** for *Halo: Combat
Evolved* as it runs inside *Halo: The Master Chief Collection* (MCC), using
official mod tools only. *Halo: Campaign Evolved* (2026, Unreal Engine 5) is
being explored only as a possible **reference** source — see blockers below
before assuming its assets can be reused.

## Local environment (see `.env`, not committed)

- `HALO_MCC_FOLDER` — retail MCC install (contains `halo1/`, the classic
  Halo CE/Blam-engine runtime: maps, FMOD sound banks, tags baked into
  `.map` cache files).
- `HALO_REMAKE_FOLDER` — *Halo: Campaign Evolved* install (UE5, codename
  "Meteorite"; Wwise audio middleware; all content packed into UE5 IoStore
  containers, `.pak`/`.ucas`/`.utoc`).
- `HALO_MOD_KIT_FOLDER` — HCEEK, the **official** Halo CE Editing Kit for
  MCC (`guerilla.exe`, `sapien.exe`, `tool.exe`). Ships as a `.7z` plus a
  partially-extracted root; the full `tags/`/`data/` tree is not extracted
  yet (see `docs/feasibility.md`).

## Hard rules (do not violate)

1. **Never modify installed game files.** Everything under the three
   `.env` folders is read-only material for this project.
2. **Do not bypass encryption or DRM.** If a container (e.g. a UE5
   `.ucas`/`.pak` pair) turns out to be encrypted, stop and report it —
   do not search for or apply AES keys.
3. **Keep game assets outside Git.** No `.map`, `.pak`, `.ucas`, `.utoc`,
   `.fsb`, `.wav`, `.ogg`, `.bnk`, `.wem`, or extracted archive ever gets
   committed (enforced in `.gitignore`). The repo holds scripts, docs, and
   small text manifests only — never audio or binary game data, including
   original or dubbed voice lines.
4. **Cite sources** for technical claims (official docs, community tool
   docs, EULA/FAQ text) — see `docs/feasibility.md` for the citation list.
5. **Ask before installing or running additional tools** (e.g. Reclaimer,
   FModel, python-fsb5/vgmstream, or extracting `HCEEK.7z`). None of that
   has been done yet as of the initial feasibility pass.
6. **No speculative extraction.** Don't write pipeline/import code before
   a human has reviewed the feasibility findings and approved a specific
   next step.

## Key facts established so far

- MCC's official localization for **Spanish (Latin America) is
  interface-only — there is no LATAM audio dub today**, only Spanish
  (Spain) has full voice + subtitles. This is the gap the mod addresses.
  (Halo Support: "Which Languages Can I Play Halo: The Master Chief
  Collection In?")
- The official HEK's public tag set (`bin\!public_tags.txt` in HCEEK)
  contains **zero** campaign dialogue (`sound\dialog`) tags for any
  singleplayer level, including `a10` (*The Pillar of Autumn*). Campaign
  VO is not shipped as moddable source in the kit — only compiled into
  the retail `.map` cache files.
- 343 Industries' MCC modding FAQ: *"Only the assets contained within the
  retail version of MCC are allowed for use in modding efforts"* — this
  reads as prohibiting reuse of *Halo: Campaign Evolved* (a different,
  2026 game) assets inside an MCC mod. Treat cross-game asset reuse as
  blocked pending clarification.
- **Campaign dialogue IS addressable, just not via HEK.** MCC's own
  `halo1/sound/pc/lst/sounds_dialogs*.lst.bin` files are a plain,
  parseable index of 1,903 stable tag names (e.g.
  `sound\dialog\a10\a10_350_captkeyes`), **identical across all 8
  shipped languages**, each paired with a per-language `.fsb` sample
  bank. This is a separate, lighter-weight target than rebuilding HEK
  tags — see `docs/feasibility.md` §10 for the recommended strategy:
  **replace the audio inside the existing Spanish (Spain) slot**, since
  it's the only non-English language with a complete, already-wired
  dialogue pipeline. Hard limit: a data-only mod cannot add a *new*
  selectable "Spanish (Latin America)" menu entry — only replace what
  plays when "Spanish" is selected.
- **Stage 1 (§11 in feasibility.md) is done, no tools installed.**
  `sound\dialog\a10\a10_350_captkeyes` is a verified, concrete worked
  example: index 30 in *both* `sounds_dialogs.fsb` (English) and
  `sounds_dialogs_spanish.fsb` (Spanish), confirmed via each bank's own
  embedded FSB5 name table (not inferred from `.lst.bin` position).
  Codec is **CELT** (mode 12) — this rules out python-fsb5 for decoding;
  **vgmstream** is the identified tool that can decode it (confirmed
  CELT/FSB5 support in its own docs). Working copies + hashes live in
  the git-ignored `reference-audio/stage1/`.
- **Stage 2A done (feasibility.md §14).** vgmstream r2117 is installed
  standalone at `D:\Tools\vgmstream-r2117\` (official GitHub release,
  hash-verified, outside Steam and outside this repo — not something
  future sessions need to reinstall, just point `scripts/
  extract_dialogue_samples.py --vgmstream-cli` at it). 5 scripted `a10`
  lines were decoded from both language copies (10 WAVs, all duration-
  matched); see `reference-audio/stage1/wav/` and
  `stage2a_report.csv` (both git-ignored). **Nobody has listened yet** —
  don't claim spoken content is confirmed until the user says so.

Full findings, open questions, and the proposed next experiment are in
[`docs/feasibility.md`](docs/feasibility.md).
