# Halo CE LATAM Audio — Project Guide

## Goal

A Latin American Spanish localization of *Halo: Combat Evolved* inside *Halo: The Master Chief
Collection* (MCC). The source is *Halo: Campaign Evolved* (2026, UE5),
which ships a full `Spanish(Mexico)` dub and `es-MX` subtitles. The plan
and milestones are in [`docs/roadmap.md`](docs/roadmap.md); the schemas
are in [`docs/dialogue-catalog-design.md`](docs/dialogue-catalog-design.md) (v2).

- **v1.0 (required):**
  - Replace MCC Halo CE's Spanish (Spain) dialogue with CE es-MX
    recordings.
  - Replace the Spanish subtitles with CE es-MX text or the user's
    custom text.
  - Audio and subtitle choices are **independent** per line.
  - Matching is **manual only**.
  - Approved mappings are **never overwritten**.
  - Unmatched lines and custom subtitles are supported. Unmatched lines
    keep Spain audio by default.
- **v1.1 (potential):** non-destructive radio-effect repair. Preserve
  originals and recipe metadata. The owner lifted "no effects yet" for the
  pilot-style radio filter and the cryo assistant's "eco" intercom echo (2026-10-13, see "Radio filter" and
  "Eco lines" below); other effects are still not approved.
- **v1.0 blockers:**
  - **B1:** MCC subtitle replacement — **✅ resolved
    (user-reported, 2026-10-08).** Edited `*_Halo1.bin` text displays
    in MCC with anti-cheat disabled. Originals are restored and
    hash-verified. Residuals (variable-length text, an `SP` runtime
    sample, per-mode coverage) move to M7. See
    `docs/subtitle-research.md` B.12 step 3 result.
  - **B2:** ✅ **resolved in practice (2026-10-08):** a CE es-MX line plays in MCC (E3, `v-000019`). Research
    is done (`docs/b2-audio-research.md`):
    - The runtime is FMOD Ex 4.44.27, which plays FSB5 CELT 0.11 and
      IMA ADPCM. The codec is per bank.
    - No public CELT encoder exists. HCEEK `tool.exe` embeds FSBankEx
      but lacks `celt_encoder.dll`.
    - Recommended: the **S-A CELT splice** (untouched samples
      byte-identical).
    - **E0 done (2026-10-08):** `python
      scripts/discovery/b2_e0_identity_rebuild.py`, with the writer in
      `scripts/common/fsb5_writer.py` (`decompose`/`build`).
      - The Spanish and English bank copies rebuild **byte-identically**:
        0 differing ranges, SHA-256 equal to the pins.
      - Metadata, payload hashes and vgmstream output are identical.
      - Outputs are in `work/b2/e0/` (631 MB). There are 9 synthetic
        tests in `tests/test_fsb5_writer.py`.
    - **E1 offline done (2026-10-08):**
      `python scripts/discovery/b2_e1_transplant.py`, about 40 s. It
      puts the English `a10_350` CELT stream in Spanish slot #30.
      - Candidate: `work/b2/e1/sounds_dialogs_spanish.fsb`, SHA-256
        `86f787ac…f55c`.
      - 23/23 checks: only #30's bytes change, and the other 5,695
        payloads are identical. All 5,696 subsongs decode, and only #31
        differs (it equals the English decode).
      - The owner-run sheet is `work/b2/e1/e1_install_rollback.md`.
        There are 6 synthetic tests in `tests/test_b2_e1.py`.
    - **E1-game ✅ PASS, user-verified (2026-10-08).** The owner
      approved it explicitly.
      - `python scripts/discovery/b2_bank_install.py
        preflight|install|rollback|status` refuses to run while MCC is
        open and writes only the Spanish bank.
      - In Classic and Anniversary, Keyes's `a10_350` played in English,
        completely, with Spanish around it and the subtitles unchanged.
      - The bank is restored to `ed0ff3ec…`. The snapshot shows nothing
        else changed. The backup in `work/mcc/fsb/backup/19905945/` is
        kept. Recorded as `v-000015`.
      - **MCC accepts banks rebuilt by our writer**, and the header hash
        field is not checked.
    - **E1b offline done:** `python scripts/discovery/b2_transplant.py
      --exp e1b --name A10_140_cryotech`, 25/25 checks.
      - English `A10_140_CryoTech` (4.574 s) goes into Spanish #13.
      - The bank grows +9,088 B, and the 5,682 later samples shift
        uniformly. `.lst.bin` is unchanged.
      - Candidate: `6a861d02…`.
    - **E2 offline done:** the approved vgmstream ships
      `libcelt-0110.dll`, which exports the CELT 0.11 **encoder**.
      - `scripts/common/celt011.py` wraps it with ctypes (44.1 kHz /
        512, CBR 370 B, FMOD framing). `b2_e2_celt.py` passes 15/15.
      - Decoder parity with vgmstream is bit-exact. Re-encoded MCC
        speech keeps 47.9 dB SNR.
      - The self-encoded candidate is `950f93e5…`. For 48→44.1 kHz,
        ffmpeg (already installed) reaches 80 dB.
    - **E1b-game ✅** (`v-000016`): the longer English line played
      fully, and the next line started normally.
    - **E2-game ❌ CRASHED** (`v-000017`): access violation in
      `halo1.dll`, which embeds its own FMOD 4 and libcelt.
      - The E1 and E2 banks differ only in sample #30's CELT packets.
      - Every original MCC packet (1.69 M frames) is **intra-only with
        no transients**. Our default encode wasn't (38 transients, 341
        inter-predicted frames).
      - Root cause is likely this, but not proven. Minidumps were not
        opened.
    - **Fix: E2b.** `celt011.encode(profile="fmod")`, now the default,
      sets prediction 0 and complexity 0. `profile_violations()` is a
      hard guard. Candidate: `f23ddda5…`.
      - **Never encode game audio with `profile="default"`.**
      - Diagnostics: `scripts/common/celt_header.py`,
        `scripts/discovery/b2_celt_profile.py`.
    - **E2b-game ✅ PASS** (`v-000018`): our MCC-profile CELT encode
      plays correctly in MCC. **B2 is technically unblocked.**
    - **In-game installs** go through `python
      scripts/discovery/b2_bank_install.py --exp <id> …`, with the
      owner's approval for each experiment.
    - ffmpeg (already installed) is approved for offline audio
      conversion (owner, 2026-10-08).
    - **E3 pipeline (offline):** `scripts/common/audio_pipeline.py`
      (ffmpeg to 44.1 kHz, pad 128 for the codec delay, CELT `fmod`
      profile, `work/derived/<sha>/recipe.json`) and
      `scripts/common/bank_checks.py`.
      - `b2_pipeline_survey.py`: all 194 M01 es-MX lines pass (41–48 dB).
      - `b2_ce_replace.py --exp e3 --slot … --ce-ref … --owner-selected`
        refuses to run without owner selection.
      - **E3 offline ✅:** owner-selected pair `es:A10_010_cryotech#0`
        ← `vo_scr_m01_00460_cryotech#0` (experiment only, **not** in
        `manual_mappings.json`). Candidate `fc6f7161…`: 30/30 checks,
        3.553 s → 3.634 s, 45.1 dB, reproducible. Never pick pairings
        yourself.
      - **E3-game ✅** (`v-000019`): the es-MX line played correctly and
        naturally in MCC. The pairing stays an experiment, **not** an
        approved mapping. **B2 audio route proven end to end.**
    - **M4 implemented (2026-10-08):** `python scripts/ui/m4_server.py`
      (127.0.0.1:8765, stdlib only). Guide: `docs/m4-user-guide.md`;
      design §7: `docs/m4-matching-ui-design.md`. Logic is in
      `scripts/ui/m4_app.py` (tested in `tests/test_m4.py`). It saves only
      through `mapping_store` (`save` / `save_user_file`), and level status
      goes in `mappings/mission_progress.json`. Owner trial pending; **next
      is M5** (owner matches `a10`). Never make or approve decisions in
      `mappings/` yourself.
    - **M4 update (2026-10-08):** subtitle search (SU/SP/EN and CE text,
      phrases, accent-insensitive, highlighted, filter only), custom
      subtitles for CE lines without source text, and the "Needs radio
      effect" flag. The mappings file is now **`manual-mappings/3`**:
      `audio.fx_request` became the slot-level `radio_effect`, which is
      independent of approvals. The v2→v3 migration is
      `scripts/validate/migrate_mappings.py`. The stack stays Python stdlib
      plus one static page (design §8).
    - **Campaign-wide catalogs (2026-10-08):** `build_ce_catalog.py --all`
      (13 missions, 1,475 records) and `build_mcc_catalog.py --all
      --no-audio` (28 folders, 1,903 tags, all 5,696 Spanish samples as
      slots). Audio is decoded on demand (`scripts/common/ondemand_audio.py`).
      The inventory is `python scripts/catalog/campaign_inventory.py
      --scan-ce`. The three rule extensions (`docs/campaign-catalog.md`
      §3: the lst-range identity fallback, `%XX` in `slot_id`, spaces in
      `tag_name`) were **approved by the owner on 2026-10-08** and verified
      by `python scripts/validate/verify_slot_ids.py`: all 5,696 IDs are
      unique, deterministic, stable and round-trip; `a10` is unchanged.
      `mission-map/1` now accepts `x10`–`x70`. Never invent mission-map
      entries.
    - **M6 limited PoC (2026-10-08):** `python scripts/build/m6_build.py
      --level a10` builds an **audio-only** candidate bank from approved M4
      decisions into `work/m6/a10/` (90 lines, 24/24 checks, deterministic,
      candidate `7d8ac2ef…`). Subtitles: see "M6 subtitles" below.
      Multi-folder builds: `--level a10 --level x10 --level x20` (one bank;
      all dialogue is in `sounds_dialogs_spanish.fsb`), or `--mission a10`
      (own folder plus the cinematics only that map uses, from
      `work/mcc/level_folders.json`, built by
      `scripts/catalog/build_level_folders.py`; `a10` ->
      `x10`/`x20`/`x30`). `m6_install.py` refuses a build whose replaced
      lines were changed or revoked in M4 since.
      Install/rollback is `scripts/build/m6_install.py --build a10
      check|preflight|install|rollback|status`. **Never run
      preflight/install without the owner's explicit approval for that build.**
      The Studio's Build & Test page (2026-10-11) runs build/install/rollback through the same scripts only
      when the owner clicks and confirms; never drive it, or the install API, yourself against the real game.
    - **M6 subtitles (owner request, 2026-10-11):** `m6_build.py --kind audio|subtitles|both`.
      - `subtitles` writes `SU_Halo1.bin` + `SP_Halo1.bin` from the approved subtitle decisions through
        `scripts/common/mcc_loc_writer.py`, a variable-length writer. Its layout rules (LF slack inside `L`,
        8-byte padding) reproduce all 21 sorted shipped tables byte for byte (`docs/subtitle-research.md`
        B.13).
      - Drafts, needs-rework, drift, takes that disagree (conflicts) and lines without a key are excluded and
        listed, never guessed. Keys are never added.
      - Baseline: the pinned copies in `work/mcc/loc/copies/`.
      - `both` = bank + tables, installed and restored as one operation.
      - Studio: Build subtitles / Build audio + subtitles, a scope preview, build details, install history,
        and Restore restores every installed build.
      - `m6_install.py`: any failure restores every original. `--simulate-failure-after` is for throw-away
        folders only.
      - **Validated offline only. MCC loading a table whose size changed is the pending runtime check;**
        don't claim it works in game until the owner reports it.
    - **Audio editor (2026-10-09):** non-destructive per-mapping recipes in `audio.edit`
      (`audio-edit/1`, `scripts/common/audio_edit.py`). It covers trims, cuts with crossfades,
      inserted silences and fades. **No per-line level control** in recipes (per-recipe matching and its
      limiter were removed on 2026-10-11, `docs/migrations/2026-10-11-remove-limiter.md`).
      - **Level modes (owner, 2026-10-11, after measuring the installed bank):** `level_mode` in
        `config/audio_export.json` is a build setting.
        - `global_gain` (default, +4 dB): linear, never limited.
        - `match_spain`: each line matched to its Spain recording's loudness, with a look-ahead limiter
          capped at 6 dB (`audio-render/5`).
        - Cause of "too quiet": CE lines are more dynamic, about 16 dB peak-to-loudness against MCC's 11, so
          the peak rule cut the gain. Replacements played a median 5.1 dB below Spain; match Spain gives
          −1.7 dB (`docs/m6-build.md` §2.3, `scripts/discovery/level_survey.py`).
        - Don't raise the global gain as a fix; it can't get past the peak rule.
      - **Speed and per-line gain were removed (owner, 2026-10-09).** A one-time, owner-authorized
        migration (`scripts/validate/migrate_reset_speed_gain.py`) removed them from 9 approved
        recipes without touching approvals. See `docs/migrations/2026-10-09-reset-speed-gain.md`.
      - **Global export gain:** `config/audio_export.json` `global_gain_db`, +4 dB (since 2026-10-10) when the file is
        absent (`common/export_config.py`). It is applied once to every CE replacement, after the
        recipe, before CELT. It is linear, never limited, and lines that can't take it in
        full are reported.
      - M4 shows waveforms and previews (`common/edit_preview.py`, `work/m4/preview/`). The
        "as encoded" preview is byte-identical to the bank decode.
      - M6 renders every line with the same code (`audio_pipeline.derive_processed`). With the
        gain at 0, unedited lines are byte-identical to before.
      - The recipe is part of the approved audio object (needs rework to change). The "Needs radio
        effect" flag is never applied; only the recipe's own `radio` filter is.
      - Guide: `docs/m4-user-guide.md` §4.1. Owner hands-on test pending.
    - **Radio filter (owner, 2026-10-13):** `docs/radio-filter.md`.
      - MCC's radio sound is baked into the bank samples (Spain: steep band-pass about 700–3300 Hz,
        clean; English: gentler, with a presence lift and hiss). CE es-MX is dry. Survey:
        `python scripts/discovery/radio_survey.py`.
      - Optional recipe field `audio.edit.radio` (presets `spain` / `english` / `custom`), applied after
        the edits and before the level stage (`audio-render/6`). It is set in the Studio under Audio
        editing → Radio filter. Browser test: `npm run test:radio`.
      - Owner-authorized migration `scripts/validate/migrate_radio_preset.py` gave the 40 pilot-style lines
        (flagged, no notes) the Spain preset and set 39 approved ones to needs rework
        (`docs/migrations/2026-10-13-radio-preset.md`). Re-approval is the owner's. The 18 "eco" lines
        are out of scope.
      - `radio.clicks` (owner feedback, same day) joins MCC's own Spain key-up and release/squelch clicks
        around the line, after the level stage, at game level (`audio-render/7`). They are cut from
        `es:A30_220_bisenti#0` in the pinned bank at fixed samples, with SHA-256 pins
        (`scripts/common/radio_clicks.py`); nothing is synthesised or stored in git.
        `migrate_radio_clicks.py` turned them on for the 35 lines whose Spain original opens with the click;
        `sgt05g`, `lif_01`, `lif_05`, `c10_010_captpilot` and `D40_411_Pilot` were left off
        (`docs/migrations/2026-10-13-radio-clicks.md`).
      - Not listened to yet; `sgt05g`, `D40_411_Pilot` and `c10_010_captpilot` have little or no
        band-pass in Spain's original.
    - **Eco lines (owner, 2026-10-13):** `docs/radio-filter.md` §5. The 18 "eco" lines (cryo assistant) get
      an intercom EQ (`radio` presets `spain_eco` / `english_eco`, optional `presence_hz`) plus the new
      recipe field `audio.edit.echo` (slap tap, echo with feedback / diffusion / damping; the line gets longer by
      the ring-out; `audio-render/8`).
      - MCC English has two clean taps (30 and 150 ms, about −12 dB); MCC Spain has one smeared echo
        (140 ms with repeats). Survey: `scripts/discovery/eco_survey.py`.
      - `scripts/validate/migrate_eco_effect.py` gave all 18 the Spain intercom + Spain echo and set them to
        needs rework, with matches kept (`docs/migrations/2026-10-13-eco-effect.md`). Not listened to yet.
    - **Victor 933's damaged transmission (owner prompt 44, 2026-10-13):** `docs/victor933-interference.md`.
      - A ONE-OFF for `vo_scr_m06_00740_victor933` (`m-000482`) only: recipe field `audio.edit.interference`,
        engine `interference/2` since prompt 45, in `scripts/common/interference.py`. It is refused for any other
        line.
      - The field holds an intensity curve (points t/v) plus the 11 owner-chosen phrase guides. The curve drives
        speech ducking (removed at >= 0.95) and continuous static with flutter. The static's `texture` is
        "synthetic" (made from scratch, fitted to MCC's; the stored recipe's choice) or "mcc" (granular MCC Spain
        sample).
      - Applied on the source timeline before edits (`audio-render/10`). The static is MCC Spain's own burst
        (`scripts/common/radio_static.py`, pinned, decoded on demand).
      - Guides are in `config/interference/vo_scr_m06_00740_victor933.json`; the default curve is generated
        from them, and masked guides always stay fully hidden.
      - The Studio shows an automation lane (`InterferenceLane.vue`) for that line only: points/draw, zoom,
        an MCC reference overlay (`/api/interference/reference`), play from the cursor.
        Browser test: `npm run test:interference`.
      - Never extend it to other lines without the owner; never change the owner's subtitle `c-000023`.
    - **M-SYS catalogued (owner request, 2026-10-10):** `python
      scripts/catalog/build_ce_catalog.py --systemic` (also in `--all`) writes
      `work/ce/catalog/sys.jsonl`, the pseudo-mission `SYS` (`mission` null, `family` systemic).
      It has 28 character folders, 2,279 records and 14,350 variations, 14,349 with es-MX audio,
      and no subtitles. M4 defaults generic MCC folders to the SYS scope. M6 builds generic folders
      only when named with `--level`.
    - **Remote access (owner request, 2026-10-12):** `docs/remote-access.md`. One server, two listeners:
      the local `127.0.0.1:8765` (no sign-in; the **only** place install/restore/MCC-folder changes work) and an
      opt-in remote listener (`--lan` / `config/studio_server.json`, sign-in, CSRF, roles editor/admin).
      Accounts: `scripts/ui/studio_users.py` (scrypt hashes in git-ignored `config/studio_users.json`). Saves
      check the line's own version (`loaded_slot_sha256`); live updates via SSE `/api/events`. Internet access
      is Tailscale Serve, or the owner's Cloudflare Tunnel + Access (below). **Never** enable Tailscale Funnel, forward router ports, change firewall rules,
      or create accounts/enable remote access on the owner's machine yourself; never let a remote listener
      install into the game. Test: `npm run test:remote` (disposable data).
    - **Cloudflare deployment (owner prompt 47, 2026-10-14):** `docs/deploy-cloudflare.md`. The owner's
      `https://studio.andresgustavo.com` (tunnel `halo-studio`, dashboard-managed, `Cloudflared` service; route →
      `http://localhost:8080`; Access app on the whole hostname) reaches the remote listener on `127.0.0.1:8080`
      with `remote.auth: "cloudflare_access"` in git-ignored `config/studio_server.json`: every request needs a
      `Cf-Access-Jwt-Assertion` that `scripts/ui/cf_access.py` verifies (RS256, iss, aud, type app, times, email
      in `cloudflare_access.users`); no password sign-in there, installs still local-only. Start/stop/status/
      startup task: `scripts/deploy/studio.ps1` (`m4_server.py --stop` = clean stop file). Tests:
      `tests/test_cf_access.py`. Never read the tunnel token or change the Cloudflare config yourself.
    - **Mobile layout (owner prompt 46, 2026-10-13):** `docs/mobile.md`. Same Vue app and server, no
      backend change: `<html data-layout="phone|tablet|desktop">` from `frontend/src/layout/useLayoutMode.ts`
      (media queries, not innerWidth), styles in `frontend/src/styles/mobile.css`. Phones get one pane at a time
      (bottom nav, `pane=` in the URL), tablets a list beside Matching; all panels stay mounted. Desktop
      (>= 1000 px) is unchanged. Test: `npm run test:mobile` (touch via CDP, disposable data).
      Installable PWA ("Halo Studio", `vite-plugin-pwa` 1.3.0, owner-requested): app-shell precache only, never
      `/api`, `/audio`, `/classic`; update via a Reload prompt; icons from `npm run icons`. HTTPS (Tailscale) to
      install. Test: `npm run test:pwa` (docs/mobile.md §9).
    - **Mute / LATAM language / permutations (owner prompt 49, 2026-10-15):** `docs/mute-language-permutations.md`.
      - Audio source `mute` (+ required `audio.mute_reason`, match must be `no_equivalent`; additive, no migration).
        M6 action `mute` = `audio_pipeline.silent_stream`: exact original sample count, MCC's own CELT silence
        packet (retail `x70\cor_19` is already all silence). An empty subtitle (`none`) is written only when every
        take of the tag agrees. Studio: "Mute in game", filter, badge, `muted` counts. Never mute lines yourself.
      - A new H1 audio language is not supported (closed `localizations` list in `initial_ps.s3dpak`
        `sound_config.ps`; fallback is per language). Replacing the Spain bank stays the route.
      - `.lst.bin` sample ranges are per language (names identical, counts differ). Extra permutations are
        structurally possible (bank + Spanish `.lst.bin` together; offline proof
        `scripts/discovery/p49_offline_proofs.py permutations`); selection in game is unverified, and no installer
        writes the `.lst.bin` yet.
      - **Permutation experiment prepared (owner, 2026-10-16):** `docs/permutation-experiment.md`.
        `python scripts/discovery/perm_experiment.py` → build `exp_grunt_death_violent_4` (kind `experiment`, bank +
        Spanish `.lst.bin` as one unit, 19/19 offline). Installed/restored only by the owner from Build & Test
        (`m6_install.py` handles both files; bank-only builds refuse a non-original index: `companion_check`).
        The map tag has 4 permutations, #3 skip fraction 1.0. Johnson variant (`--preset johnson`): **in-game PASS
        (owner, 2026-10-17, `v-000020`): all 4 takes heard**, so MCC selects added takes via the Spanish index.
        More takes than the tag defines (5+) untested. General "add another take" feature not built yet.
    - **Deferred (owner):** `temp_mocap_VO` (backlog) and stereo replacement
      (stereo slots are only shown and played).
    - **Workshop**
      (WC-1): `docs/workshop-research.md`. No documented Workshop
      override exists for FSB or localization files.
    - Never install a bank or launch MCC without the owner's explicit
      approval for that specific experiment.

  Research options are in roadmap §6. Neither may be attempted with
  binary edits or repacking without explicit approval.
- **Distribution (owner, 2026-10-08):** development is local-only. The
  intended v1.0 release platform is **Steam Workshop** (roadmap **M8**,
  via Excession). The early compatibility checkpoint **WC** sits inside
  B2 and comes before full-campaign production.
  - Planning only. Never package, upload or change Workshop visibility.
  - Public publishing needs explicit owner approval.
  - A public build may not contain CE content unless M8.1 finds it
    permitted (MCC FAQ conflict).
  - **B1 stays the immediate priority.**

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
   FModel, python-fsb5/vgmstream, or extracting `HCEEK.7z`). Approved so
   far: vgmstream r2117 (`D:\Tools\vgmstream-r2117\`), and read-only,
   decompress-only use of FModel's bundled `oodle-data-shared.dll`.
   `HCEEK.7z` is still **not** extracted.
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
  the retail `.map` cache files. **Corrected 2026-10-08:** that list
  covers only the unextracted kit root. `HCEEK.7z` itself contains 1,920
  `tags/sound/dialog/…` tags, including `a10` (feasibility §4.2 note).
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
  future sessions need to reinstall, just point `scripts/extraction/
  extract_dialogue_samples.py --vgmstream-cli` at it). 5 scripted `a10`
  lines were decoded from both language copies (10 WAVs, all duration-
  matched); see `reference-audio/stage1/wav/` and
  `stage2a_report.csv` (both git-ignored). **Nobody has listened yet** —
  don't claim spoken content is confirmed until the user says so.

- **Phase 2 discovery done (2026-10-08)** — see
  `docs/remake-audio-research.md`, `docs/subtitle-research.md`,
  `docs/dialogue-catalog-design.md`. Headlines:
  - CE containers are **not encrypted** (all `.utoc` Encrypted flags
    unset, all `.pak` indexes unencrypted, zero key GUIDs). Paks are
    **Oodle**-compressed; `.locres`/package contents need FModel (or an
    approved Oodle reader) to read.
  - CE ships a full **`Spanish(Mexico)`** Wwise voice track in
    `pakchunk4-Windows.pak` (es-ES = chunk 3, en-US = chunk 2). Media IDs
    are per-language (zero overlap); bank IDs = FNV-1 of lowercased name.
  - CE subtitles: UE localization target `Subtitles`,
    `Localization/Subtitles/es-MX/Subtitles.locres` (separate from es-ES).
    Line→subtitle-key link **verified (Phase 2B)**, see below.
  - CE line key e.g. `VO_SCR_M01_00460_CryoTech` is shared (case-
    insensitively) by UE audio asset, `Play_` AkAudioEvent, LipSync and
    `Tags/sound/...-sound`. CE numbering is unrelated to MCC's
    `a10_NNN` — matching is manual only.
  - MCC Halo CE subtitles: `Data/ui/localization/<LANG>_Halo1.bin`
    (`SP_` = Spain, `SU_` = Latin America). *Superseded by the B1
    research below:* key↔string and the key hash are now solved.
  - User's tools: FModel portable at
    `%USERPROFILE%\Downloads\858461d19e29803479555059acb59a03a0986de8\`
    (exports under `Output\Exports`, audio only, no JSON yet; `.usmap`
    not loaded in FModel per its log). UE4SS v3.0.1 is installed by the
    user inside the CE install (`Binaries\Win64\ue4ss\`, `Paks\LogicMods\`)
    — treat as read-only; its only dump is the `.usmap`.

- **Phase 2B PoC done and MANUALLY VERIFIED (2026-10-08)** —
  `docs/poc-ce-line-link.md`. The user listened to the en / es-MX / es-ES
  recordings of `VO_SCR_M01_00460_CryoTech` and confirmed they match
  their subtitles (future `verifications.json` entry `v-000001`).
  Approved decisions: read-only use of FModel's bundled
  `Output\.data\oodle-data-shared.dll` (decompress only); `.usmap` path
  comes from `.env` **`USMAP_FILEC`** (exact name); personal, local-only
  project, **no distribution**.
  - Explicit CE chain: `Audio/scripted/.../<LINE>` (`HaloAudioVoiceVariations`)
    → `VoiceEvents[i].VoiceEvent` (import) → `Play_<LINE>` AkAudioEvent →
    `EventCookedData.EventLanguageMap["Spanish(Mexico)"].Media[].MediaId`
    → `Media/Spanish(Mexico)/NN/<id>.wem` in pakchunk4; and
    `VoiceEvents[i].Transcription{StringTable, LineKey}` → StringTable
    `TableNamespace` → `Subtitles/es-MX/Subtitles.locres[ns][LineKey]`.
  - Run it: `python scripts/discovery/link_ce_line.py --voice-asset
    Audio/scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech
    --vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe`
    (output in `work/ce/`). Tests: `python -m unittest discover -s tests`.
  - MCC `*_Halo1.bin`: fully decoded in the B1 research
    (`scripts/common/mcc_loc.py`, read-only). Editing or placing a
    modified table needs explicit approval (PoC in subtitle-research.md
    B.11).
  - Script layout: `scripts/common/` (parsers), `scripts/catalog/`
    (catalog builders), `scripts/discovery/`
    (inspectors/PoC), `scripts/extraction/` (FSB decode). All outputs go
    to git-ignored `work/`.

## Catalog / mapping rules (from the Phase 2 design)

- Two separate catalogs (CE, MCC) under git-ignored `work/`; cross-game
  links exist **only** in the user-owned `mappings/manual_mappings.json`.
- Never auto-match, rank, or pre-fill CE↔MCC pairs.
- Every in-catalog association records evidence: `explicit`,
  `derived:<rule>`, or `unresolved`. Never invent one.
- Tools never create or modify `approved` mapping entries. `audio` and
  `subtitle` are approved separately, and each is immutable to tools
  once approved. Drift goes to `work/reports/`, never into the manifest.
- The MCC replacement unit is the **Spanish FSB sample slot**
  (`slot_id = "es:" + name_in_spanish_bank`), not the tag and not the
  English sample. The Spanish bank has fewer samples (5,696 vs 6,093).
- Human checks are recorded in `mappings/verifications.json`
  (append-only). They are not an evidence level.
- Derived audio (resample to 44.1 kHz, trims, v1.1 FX) is always a new
  file under `work/derived/<sha256>/` with a `recipe.json`. Originals
  are never edited.
- **Approvals (owner, 2026-10-08):** M1, M1b, M2, B1 R1–R4, `HCEEK.7z`
  extraction, B2 R7–R9. These run **sequentially, with owner review
  between tasks**. Start only the task the owner names.
- **M1 done (2026-10-08):**
  `python scripts/catalog/build_ce_catalog.py --mission M01` writes
  `work/ce/catalog/m01.jsonl` (`ce-voice-asset/3`, deterministic),
  `work/ce/build.json` and `work/ce/reports/m01_*`. It produces 220
  records and 0 skipped. Findings are in remake-audio-research.md §9.
  The owner **approved** asset-name-based
  `ce_line_ref = <record_id>#<n>` (design §3.1).
- **M1b done (2026-10-08), awaiting owner review + listening:**
  `python scripts/extraction/export_ce_audio.py --mission M01` (default
  `--vgmstream-cli D:/Tools/vgmstream-r2117/vgmstream-cli.exe`, about
  12 s) decodes es-MX + en into `work/ce/audio/m01/<language>/<ref>.wav`.
  It keeps byte-identical `.wem` copies in `work/ce/media/` and writes
  `work/ce/audio/m01/manifest.json` (`ce-audio-export/1`,
  deterministic) and `work/ce/reports/m01_audio_*` /
  `m01_review_picks.*`. One WAV is written per (language, media_id),
  and `test_event` records are excluded, not failed. Findings are in
  remake-audio-research.md §10.
- **M2 done and reviewed (2026-10-08):**
  `python scripts/catalog/build_mcc_catalog.py --level a10` reads only
  the pinned copies in `reference-audio/stage1/` and writes
  `work/mcc/catalog/a10.jsonl` (`mcc-dialogue-tag/3`), `work/mcc/build.json`,
  `work/mcc/audio/a10/` (202 WAVs + manifest) and `work/mcc/reports/a10_*`.
  **Approved ID (owner):** `slot_id = es:<spanish_sample_name>#<occurrence>`.
  The name keeps the bank's exact casing, and occurrence follows
  Spanish bank order. ID changes must be detected, never silently
  renumbered. The `.lst.bin` layout is resolved (`{len, tag,
  first_sample_index, sample_count}`). See `docs/mcc-a10-catalog.md`.
- `mappings/verifications.json` exists (committed, IDs only):
  `v-000001`–`v-000011`, all passed (`ce:` = CE line refs, `mcc:` =
  Spanish slots). It is append-only; never rewrite entries.
- **M3 done and approved (2026-10-08)**, including the `manual-mappings/2` (now `/3`)
  changes:
  - **Schemas:** six versioned schemas in `schemas/`, checked by
    `scripts/common/jsonschema_lite.py`, a stdlib subset that refuses
    unknown keywords.
  - **Validator:** `python scripts/validate/validate_project.py` is
    read-only and writes only `work/reports/{validation,drift}.json`.
    Run it before every commit that touches `mappings/`.
  - **Store:** `scripts/common/mapping_store.py` is the **only** allowed
    writer of `manual_mappings.json`. Tools never approve, and approved
    objects change only via a user `needs_rework` action (revision + 1).
  - **Files:** `manual_mappings.json` has no slots yet, and its pins
    are set from the verified builds (CE exe FileVersion, MCC Steam
    build `19905945`, Spanish FSB SHA-256). `mission_map.json` holds the
    owner's `a10 ↔ M01`. Custom text and recording paths go only in the
    git-ignored `manual_mappings.local.json`.
  - **ID changes:** `build_mcc_catalog.py` refuses slot-ID changes
    unless `--accept-id-changes` is given. **Never pass
    `--accept-id-changes` on your own initiative:** the owner reviews
    `<level>_id_changes.json` and decides (owner rule, 2026-10-08).
    Design §5.5.
- **B1 research done (2026-10-08)**, see `docs/subtitle-research.md`
  B.4–B.12 and `scripts/discovery/b1_subtitle_research.py`:
  - **Format:** `<LANG>_Halo1.bin` keys start at `0x80`; string i ↔ key i
    (VERIFIED, byte-exact rebuild). `0x7C` is the string-data length,
    not a key.
  - **Key:** key = CRC-32/MPEG-2(UPPER(label)). The Halo 1 dialogue
    label is the tag path (a10: 101/101), which is
    `derived:mcc_loc_key_crc32_tag_path`. Catalog subtitles stay
    `unresolved` until owner in-game confirmation.
  - **Languages:** **`SP` = Spain, `SU` = Latin American Spanish**
    (VERIFIED via Saber `strings_spanish` / `strings_latam_spanish` in
    `halo1/prebuild/paks/initial_textures.s3dpak`, a second identical
    store).
  - **Loading:** no official localization modding exists. The community
    replaces the `.bin` with EAC off (MCCLocalizationEditor, not
    installed). Load behaviour is unverified.
  - **Kit:** `HCEEK.7z` contains `tags/sound/dialog/a10/*.sound` (relevant
    to B2). Selective extraction is in `work/hceek/`.
- **B1 revision (owner, 2026-10-08)**, see subtitle-research.md
  B.11–B.12:
  - **Language behaviour (USER-VERIFIED, B.12 step 1):** with primary
    Spanish (Latin America) and fallback Spanish (Spain), the game shows
    `SU` subtitles and plays Spain audio, in both Classic and Anniversary
    (`v-000012`–`v-000014`). Speaker names don't appear in Spanish. That
    is **out of scope**: preserve the original behaviour and never touch
    speaker labels.
  - **Target:** LATAM audio through the Spain audio slot, plus matching
    subtitles.
  - **Approved strategy (plan only):** patch **both** `SU_Halo1.bin` and
    `SP_Halo1.bin` from **one canonical** approved `subtitle` per slot.
    - Unmatched entries keep their original bytes.
    - Keys are looked up independently in each table; never reuse an
      index across tables.
    - Audio and subtitle mappings stay independent.
  - **Revised PoC (B.12, not executed):**
    0. pre-flight hashes;
    1. baseline observation first;
    2. two one-entry, same-length ASCII-marker candidates (`[B1-SU]` /
       `[B1-SP]`) built offline in `work/`;
    3. in-game tests one table at a time (3a `SU`, 3b `SP`), using MCC's
       anti-cheat-disabled mode with hash-verified backup and restore.

    **Each step needs separate owner approval.**
  - **Approved (owner, 2026-10-08):** the SU+SP strategy; the check
    names `subtitle_key_link` and `subtitle_load`.
    - **Structural** key verification is done by tools, for every key
      in every table.
    - **Representative** runtime verification is done by the owner,
      with a few lines per table.
    - There is no in-game test for every key.
  - **Step 0 done:** `python scripts/discovery/b1_baseline.py`
    (read-only). Build `19905945`; installed `SU`/`SP` match the copies
    and the pins. `a10_350`'s SU/SP texts differ only in case, so the
    baseline uses discriminator lines `a10_080/130/150_cryotech`.
    `--match "<text>"` classifies typed on-screen text. Step 1 is done
    (owner baseline).
  - **Step 2 done (2026-10-08):**
    `python scripts/discovery/b1_build_poc_candidates.py`, using the
    patcher `scripts/common/mcc_loc_patch.py` (same-length one-entry
    only). It writes `work/mcc/loc/poc/{SU,SP}_Halo1.bin` with markers
    `[B1-SU]`/`[B1-SP] a10_350` padded with `.`, at 16/16 checks each.
    Candidate SHA-256: `SU` `de8cc7ee…d9be`, `SP` `9856cfde…b63f`.
    Report: `work/mcc/reports/b1_poc_candidates.json`. Owner-run
    commands: `b1_poc_install_rollback.md`.
  - **Step 3 done by the owner, by hand:** "custom subtitles work"
    (user-reported).
    - The table, text, modes and line were not reported. Don't assume
      them.
    - On-disk evidence: an `SU` backup exists, with no `SP` backup.
      Installed `SU`/`SP` equal the originals again (verified).
    - No `verifications.json` entry yet. The `subtitle_load` entry (next free ID;
      `v-000015` is B2 E1) waits for the owner's details.
    - Never copy into the install or launch MCC yourself.
- Not started: B2 E4+, WC-2/3, M5 (owner work), M6, M8, M-SYS (CE `Systemic` catalog), stereo replacement, v1.1 effects other than the radio filter and the eco echo. Audio processing (resample,
  trims, FX), FSB repacking, map changes, any install change,
  packaging and any upload are still not approved (beyond M6 builds the
  owner installs from the Studio; M6 subtitle generation was requested
  by the owner on 2026-10-11).
- ⚠ The user's goal uses CE es-MX audio/subtitles as the source. That
  conflicts with 343i's MCC asset FAQ (feasibility §7).
  - Development stays local.
  - The Workshop release (M8) is gated on the M8.1 rights memo and the
    M8.2 alternatives.
  - Never commit or redistribute CE content.

Full findings, open questions, and the proposed next experiment are in
[`docs/feasibility.md`](docs/feasibility.md) and the Phase 2 docs above.
