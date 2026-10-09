# B2 Research: Replacing Spanish (Spain) Dialogue in MCC Halo CE

**Status:** research and planning only (2026-10-08). Nothing was
encoded, rebuilt, installed or launched. No game file was modified. All
local analysis is read-only and ran on the install or on the pinned
copies in `reference-audio/stage1/`. Reproduce it with
`python scripts/discovery/b2_bank_inventory.py`, which writes
`work/mcc/reports/b2_bank_inventory.json`.

Scope: B2 research items R7 (FMOD version and encoder availability), R8
(constraints a rebuild must preserve) and R9 (mod loading), plus the
Workshop checkpoint WC-1 (docs only). The approved goal is
CE es-MX audio in the **Spain audio slot**, with one approved mapping
per slot (`slot_id = es:<name>#<occ>`). Matching stays manual.

Evidence labels:
- **VERIFIED**: read from the files here;
- **DOCUMENTED**: official docs or source code;
- **COMMUNITY**: community reports;
- **INFERRED**: deduced from the above.

## 1. What the runtime and the banks are (local, VERIFIED)

### 1.1 Runtime

| File | FileVersion |
|---|---|
| `halo1/fmodex64.dll` | **4.44.27** (FMOD Ex) |
| `halo1/fmod_event_net64.dll` | 4.44.27 |

- MCC's Halo CE uses **FMOD Ex 4.44.27**, not FMOD Studio. Even so, all
  nine `halo1/sound/pc/*.fsb` banks are **FSB5 version 1**.
- There are no `.fev` / `.bank` event files. Banks are addressed through
  the plain `.lst.bin` index files.

### 1.2 Codecs the runtime already loads (evidence from the install)

| Bank | Codec (FSB5 mode) | Samples | Rates | Channels | Size |
|---|---|---|---|---|---|
| `sounds_adpcm.fsb` | **IMA ADPCM (7)** | 3,106 | 22.05k / 44.1k | 1 / 2 | 88 MB |
| `sounds_debug.fsb` | CELT (12) | 2,245 | 44.1k | 1 / 2 | 95 MB |
| `sounds_dialogs*.fsb` (en, fr, de, it, **es**) | CELT (12) | 5,696–6,093 | 44.1k | 1 (40 stereo) | 309–356 MB |
| `sounds_music.fsb` | CELT (12) | 1,028 | 44.1k | 1 / 2 / 4 | 957 MB |
| `sounds_stream.fsb` | CELT (12) | 254 | 44.1k | 1 / 2 | 159 MB |

**FMOD Ex 4.44.27 provably decodes FSB5 CELT and FSB5 IMA ADPCM** in
this game, because both kinds ship and play. PCM, Vorbis and FADPCM are
not shipped, so their support here is **unknown** until tested.

### 1.3 Spanish dialogue bank: invariants a rebuild must keep

`sounds_dialogs_spanish.fsb`: SHA-256 `ed0ff3ec…faef6`,
309,320,800 B, Steam build `19905945`.

| Property | Value | Rebuild rule |
|---|---|---|
| Header | FSB5 v1, mode 12, flags `0x80000010`, 16-byte per-bank hash field | copy the flags; keep the hash field unchanged (risk B2-R4) |
| Samples | 5,696, in a fixed order with a name table | **same count, order and names** |
| `.lst.bin` | per-language file (`d5324861…`); its ranges sum to exactly 5,696, i.e. tag → contiguous index range in *this* bank | keep it **unchanged**, which needs identical indices |
| Sample header | packed 64-bit: next-chunk, freq index, stereo flag, data offset ×16, sample count | recompute offset and count |
| Data offsets | ascending, 32-byte aligned | keep the alignment |
| Extra chunk | LOOP (type 3, 8 B) on 5,648/5,696 samples, **always `start = 0, end = samples − 2`** | recompute from the new length |
| Sample rate | 44.1 kHz, every sample | resample 48 → 44.1 kHz |
| Channels | mono, except 40 stereo samples | keep each slot's channel count |
| CELT framing | every frame is `F3 0D C3 17` sync + u32 payload size + payload. The payload is **370 B mono / 464 B stereo**, constant bitrate, 512 samples per frame. Sample counts are multiples of 512 | a CELT encoder must reproduce this exactly |
| Length | 0.128–28.4 s, median 1.13 s; 417.4 M frames total (about 2.6 h) | — |

### 1.4 Source audio (CE es-MX, M1b decode, VERIFIED for M01)

There are 194 unique es-MX media in M01. All are **48 kHz, mono,
16-bit** after vgmstream decode. They run 0.37–43.4 s (median 2.59 s),
and none clip (peak ≤ 25,639).

Differences from the slots:
- the sample rate (48k vs 44.1k);
- the codec (decoded PCM vs CELT);
- possibly the channels (the 40 stereo slots);
- the **length**, per pair. That is decided by the user's manual
  mapping; tools only report the delta.

### 1.5 The bank flags field is the CELT bitstream version (VERIFIED + DOCUMENTED)

- All CELT banks carry `0x80000010` at header offset `0x1C` (the IMA
  ADPCM bank has `0`).
- vgmstream's FSB CELT decoder names `0x80000010` as the **CELT 0.11.0**
  bitstream ("newer FSB4 (FMOD ~4.34), FSB5"); `0x80000009` is the
  older, incompatible 0.6.1 bitstream. [^vgm-celt]
- Its framing matches §1.3 exactly: sync `0x17C30DF3`, u32 size, CBR
  packets, 512 samples per frame, and a CELT mode fixed at **44,100 Hz**.
- **Any CELT replacement must be CELT 0.11.0, 44.1 kHz, 512-sample
  frames, CBR 370 B (mono).**

### 1.6 HCEEK `tool.exe` embeds FMOD's own FSB5 writer (VERIFIED by string inspection only)

A plain string search of the kit's `tool.exe` (it was not executed or
disassembled) shows:
- **FMOD FSBankEx 4.x** compiled in. Its source paths include
  `…\h1\code\common\lib_3dpart\src\fmod\fmod4\tools\fsbankex\lib\src\fsbank_writer_fsb5.cpp`
  and `fsbank_encoder_*.cpp`.
- A **CELT encoder that is loaded from `celt_encoder.dll` at run time**
  (`celt_mode_create`, `celt_encoder_create_custom`, `celt_encode`,
  `celt_encoder_ctl`). It also references `twolame.dll` and
  `libmp3lame.dll`.
- FSBank messages, e.g. "CELT has a fixed sample rate" and "Source bit
  formats … must match for all sub-sounds".
- `export-sounds-to-fsb <tag dir>` (example `sound\sfx`), hard-wired to
  `data\sound\tags.lst` → `sounds_adpcm.lst.bin`. Official docs
  describe it as building the ADPCM SFX bank. [^c20-tool]
- The language names `spanish … latam_spanish` (tag/string-list
  enums).

`celt_encoder.dll` is **not** in the kit root or in `HCEEK.7z` (14,294
entries listed). **INFERRED:** MCC's dialogue banks were made with FMOD
Ex FSBankEx and CELT 0.11. The official kit can write FSB5, but it ships
no CELT encoder, and its export command targets the SFX bank, not
dialogue banks.

## 2. Format facts from sources (DOCUMENTED)

- **The codec is per bank.** FSB5 has one `mode` field, so CELT and
  PCM/ADPCM samples cannot be mixed in one bank. [^vgm-fsb5] Replacing
  a few samples therefore means either:
  - **encoding them as CELT 0.11** and splicing them into the existing
    bank; or
  - **re-encoding the whole bank** to another codec the runtime decodes.
- **Per-sample header** (vgmstream): a chunk flag, a frequency index
  (8 = 44,100), channels, the data offset `<<5` (32-byte units), and a
  30-bit sample count. A sample's stream ends at the next sample's
  offset, so streams must sit in header order with alignment padding.
  The file size must equal header + sample headers + name table + data.
  The name table is N u32 offsets followed by NUL-terminated strings.
  [^vgm-fsb5][^pyfsb5]
- **The LOOP chunk** is type 3, 8 bytes. In this bank it always holds
  `0, n−2` (§1.3).
- **Writers today:**
  - FMOD Studio-era **FSBank** writes PCM / Vorbis / FADPCM / Opus /
    console codecs, with **no CELT**. [^fsbank-enum]
  - FSBank Vorbis relies on setup IDs built into the runtime. FMOD has
    broken older-Vorbis compatibility before, so a modern FSBank Vorbis
    bank may not load in FMOD Ex 4.44. FADPCM postdates FMOD Ex.
    [^vgm-vorbis]
  - python-fsb5, vgmstream and Fmod5Sharp are decoders only. fsbext
    claims FSB5 repacking of already-encoded data (unverified).
    [^fsbext]
- **No public tool or report produces FMOD-compatible FSB CELT today**
  (searched 2026-10-08). The CELT 0.11.0 reference source exists
  (Mumble mirror, BSD). An encoder built from it, plus our own framing,
  would match the decoder vgmstream already uses on these banks.
  [^celt011]

## 3. Replacement strategies compared

| # | Strategy | Untouched 5,6xx samples | New tools | Runtime support | Size | Verdict |
|---|---|---|---|---|---|---|
| **S-A** | **CELT splice:** our own FSB5 writer copies every untouched CELT stream byte-for-byte and inserts CELT 0.11 encodes for replaced slots; it recomputes offsets, counts and LOOP. Header, flags, name table and order are kept | **byte-identical** | a CELT 0.11 encoder (build from source, or FMOD Ex SDK `celt_encoder.dll`); **needs approval** | proven (the game's own codec) | ≈ same (309 MB) | **recommended** |
| S-B | PCM16 whole bank (decode every CELT sample, store PCM) | re-stored as decoded PCM: audibly identical, not byte-identical | none (vgmstream already approved) | **unknown** for PCM in this runtime | ≈ 835 MB | fallback 1 |
| S-C | IMA ADPCM whole bank (our own stdlib encoder) | transcoded, so a small quality loss on every line | none | **proven** (`sounds_adpcm.fsb`) | ≈ 235 MB | fallback 2 |
| S-D | Modern FSBank Vorbis/FADPCM | transcoded | FMOD Studio FSBank (account, EULA) | doubtful in FMOD Ex 4.44 | small | rejected |
| S-E | HCEEK `export-sounds-to-fsb` | n/a | already installed | n/a | — | not applicable: it builds the SFX bank, and has no CELT DLL |

**Why S-A:**
- It is the only option that keeps every unmatched Spain line
  bit-exact. That meets M6's "untouched samples byte-identical" and v1.0
  rule 6.
- It keeps the runtime on the codec it already plays.
- It leaves `.lst.bin` unchanged.

Its one hard dependency is a CELT 0.11.0 encoder. The S-A writer and its
offline checks can be built and tested **before** any encoder exists
(experiments E0–E1 below). S-B and S-C stay as fallbacks if an encoder
can't be approved or validated. Both would need a runtime-acceptance
test first.

## 4. Audio handling rules (plan; applied non-destructively per design §6)

- **Sample rate:** CE 48 kHz → 44.1 kHz (CELT 0.11 mode is fixed at
  44.1k). This needs an approved, recorded resampler. Python's stdlib
  has none; the options are a pure-Python windowed-sinc implementation
  (slow but dependency-free) or an approved external tool. Every
  derived file is `work/derived/<sha256>/` + `recipe.json`.
- **Channels:** CE es-MX is mono. 5,656 Spanish slots are mono, so they
  are encoded mono. **40 slots are stereo:** the owner chooses per slot
  between duplicating mono to 2 channels (464 B frames) and
  `keep_original`. No automatic choice is made.
- **Length:** CELT frames are 512 samples, so a stream is padded with
  silence to a multiple of 512. The header `sample count` equals the
  padded length (as in every original sample), and LOOP =
  `0, n−2`.
  - Longer or shorter lines are allowed by the format. Whether the
    engine times dialogue from the FSB length or from tag/map data is
    **unknown**; E1b tests it.
  - Trims stay owner-approved recipe edits (design §5.1 `edit`).
- **Loudness:** CE vs MCC levels may differ. Tools report peak and RMS
  per slot; any gain is an owner-approved recipe field. It is never
  automatic.
- **Pairing:** the slot → CE line pairing always comes from an
  owner-approved `audio` object in `manual_mappings.json`. Experiments
  use only pairings the owner names. Nothing is matched by a tool.

## 5. Experiments (each needs approval; installs are always done by the owner, by hand)

| ID | What | Content used | Writes | New tools |
|---|---|---|---|---|
| **E0** | FSB5 **writer + identity rebuild**: parse the Spanish bank copy into header / sample headers / chunks / names / streams, re-serialise it, and require a **byte-identical** file (also the English bank) | MCC copies | `work/` only | none |
| **E1** | **Same-length transplant:** put the English bank's CELT stream for `a10_350_captkeyes` (198,144 frames in both banks) into `es:A10_350_captkeyes#0`; offline candidate plus checks | MCC retail only | `work/` | none |
| E1-game | Owner installs the E1 bank (backup → place → play `a10` to Keyes → restore). Expected: **Keyes speaks English**, and every other line is Spain Spanish | — | install (owner) | none |
| **E1b** | **Different-length transplant:** an `a10` line whose EN and ES lengths differ most (M2 review pick `a10_682_cortana`). Every later sample offset shifts | MCC retail only | `work/`, then owner install | none |
| E2 | **CELT encoder qualification (offline):** encode decoded MCC Spanish samples back to CELT 0.11. Check that vgmstream decodes them, the frames are 370 B CBR, the length is exact, and SNR against the source is above a set threshold | MCC copies | `work/` | **CELT 0.11 encoder (approval)** |
| E3 | **Single CE line:** one owner-named CE es-MX line → resample → CELT → splice into one owner-named slot; offline checks, then owner in-game test | CE es-MX (personal, local) | `work/`, owner install | resampler (approval if external) |
| E4 | **Multi-sample:** 5–10 `a10` slots from owner-approved mappings. They include longer and shorter lines, one `keep_original`, and optionally one stereo slot. Offline checks, then an owner playthrough of the `a10` opening | CE es-MX | `work/`, owner install | as E2/E3 |
| E5 | **Batch generator (M6):** approved `audio` objects → recipes → encodes → one splice build, with a report. Deterministic; untouched samples byte-identical; drift-gated | as mapped | `work/` | — |

**Offline acceptance checks (every candidate bank):**
- it parses with `fsb5_lib`;
- **vgmstream decodes every subsong**;
- the sample count is 5,696 and the names and order are identical;
- every untouched stream is byte-identical (by hash);
- the replaced streams equal the intended bytes;
- offsets are ascending and 32-byte aligned;
- the file-size equation holds;
- LOOP = `0, n−2`, and the flags, header hash field and name table are
  unchanged;
- the `.lst.bin` is unchanged;
- the output is deterministic across two runs.

**In-game acceptance (owner):**
- the replaced line plays the expected recording, start to end;
- neighbouring lines are unaffected;
- there is no hang or crash;
- the original is restored, with its hash verified (`ed0ff3ec…`).

Results are recorded as `verifications.json` entries, for example
`correct_audio` / `audio_complete` on the `mcc:es:…` slot.

### 5.1 E0 result — ✅ PASS (2026-10-08, owner-approved, offline)

Run: `python scripts/discovery/b2_e0_identity_rebuild.py` (about 3 s per
bank, using the approved vgmstream r2117). It writes git-ignored
`work/b2/e0/{sounds_dialogs,sounds_dialogs_spanish}.fsb` (631 MB;
`--no-keep` deletes them), `vgm/*.wav`, `e0_report.json` and
`e0_summary.md`.

**Writer:** `scripts/common/fsb5_writer.py`. It reuses `fsb5_lib`'s
`parse_header` and `bits`. `decompose()` turns a bank into an explicit
model; `build()` serialises it.
- **Carried verbatim:** the header tail `0x1C–0x3C` (CELT flags, hash,
  unknown bytes), sample-header bits 1–5 (frequency and channel flag),
  sample counts, every chunk payload (including unknown types), name
  bytes and order (duplicates included), and the CELT frame bytes.
- **Recomputed:** the four size fields, every data offset (32-byte
  aligned, so it reads the same under the fsb5_lib and vgmstream
  bit-layouts), the chunk `more` bits, the name offsets, the name-table
  padding (the data section starts 32-aligned), and the stream padding
  (zeros up to the next 32-byte boundary).
- **The model stores real CELT streams, not spans.** It walks the frames
  and requires `frames == ceil(samples / 512)`, and that the padding is
  zero and shorter than 32 bytes. A future replacement stream is
  therefore laid out by the same rules that reproduce the originals.

| | Spanish `sounds_dialogs_spanish.fsb` | English `sounds_dialogs.fsb` |
|---|---|---|
| Source copy SHA-256 (= M2 pin) | `ed0ff3ec…faef6` | `8d072c1b…cba4bb` |
| Rebuilt SHA-256 | **`ed0ff3ec…faef6` (identical)** | **`8d072c1b…cba4bb` (identical)** |
| Size | 309,320,800 B | 330,091,232 B |
| Differing byte ranges | **0** | **0** |
| Samples | 5,696 (5,656 mono, 40 stereo) | 6,093 (6,053 mono, 40 stereo) |
| Chunk types | LOOP (3) | LOOP (3) |

Checks per bank, all **pass**:
- byte-identical, same size, identical header;
- re-parsed with `fsb5_lib`: per-sample metadata (frequency, channels,
  offset, sample count, chunks) identical; names and order identical;
  per-sample payload SHA-256 identical;
- the bank contains both mono and stereo samples;
- vgmstream on 7 subsongs per bank (first, second and last mono, the
  longest, `a10_350`, and the first and last stereo): WAVs from the
  original and the rebuilt file are identical, and the `-m` metadata
  is identical (`Custom CELT`, 44,100 Hz, `stream count` 5,696 / 6,093).

**Tests:** 9 synthetic round-trip tests in `tests/test_fsb5_writer.py`
(the full suite has 97 tests, all passing). The fixtures are crafted by
hand, independently of `build()`. They cover:
- mono, stereo and multi-chunk samples, including an unknown chunk type;
- duplicate names;
- five padding variants;
- a non-CELT mode;
- a non-sequential name table, kept raw;
- a longer replacement stream, which shifts later offsets and leaves
  everything else unchanged;
- rejection of truncated files, wrong frame counts, dirty padding and
  overflow;
- `diff_ranges` across chunk boundaries.

A one-off mutation check showed the tests catch a wrong alignment (4
failures) and a dropped stereo bit (2 failures).

**What E0 proves:** our writer reproduces MCC's dialogue banks exactly,
with no FMOD tool. **What it does not prove:** that MCC accepts a bank
that *differs* from the original. That is E1.

### 5.2 Proposed E1 — same-length English→Spanish transplant (NOT approved)

**Why this line:** in both banks, sample #30 (`a10_350_captkeyes`;
English name `A10_350_CaptKeyes`) has identical header bits, sample
count (198,144), channels (mono), LOOP payload (`0, 198142`) and CELT
stream length (146,286 B). Only the audio differs (stream SHA-256 EN
`0442a6df…`, ES `ce2c0d9e…`).
- Swapping that one stream changes **only bytes inside sample #30's data
  span**. Every offset, size field, sample header, name and the header
  hash field stay identical.
- This isolates the question "does MCC play a modified dialogue bank?"
  from offset shifting (E1b) and from encoding (E2).
- It uses MCC retail content only, with no CE content and no new tools.

**E1 offline** (`work/b2/e1/`):
1. Verify both copies against their pins.
2. `decompose()` the Spanish and English copies. Set Spanish
   `samples[30].stream` to the English stream, and keep everything else
   from the Spanish model (name, head bits, count, LOOP).
3. `build()` and write `work/b2/e1/sounds_dialogs_spanish.fsb`. Then
   check:
   - **the diff lies only inside sample #30's span**;
   - the same size as the original;
   - the other 5,695 payload hashes are identical;
   - the header, sample headers and name table are byte-identical;
   - re-parse with `fsb5_lib`;
   - `decompose(build())` round-trips;
   - deterministic over two runs;
   - `.lst.bin` is not touched.
4. vgmstream: subsong 31 decodes to the **same WAV as the English
   bank's subsong 31**, and the E0 picks other than #30 decode
   identically to the original. The report records the original and
   candidate SHA-256.
5. Generate an owner-run install and rollback sheet, as in B1. The
   file is 309 MB, and the backup goes to
   `work/mcc/fsb/backup/19905945/`. The procedure is:
   - pre-check the installed hash `ed0ff3ec…`;
   - back up and verify the backup;
   - place the candidate and verify it;
   - restore and verify.

**E1-game** (a separate approval; the owner, by hand, MCC closed during
copies, anti-cheat disabled):
- **Settings:** primary Spanish (Latin America), fallback Spanish
  (Spain), the verified Spain-audio configuration.
- **Play** `a10` through the cryo sequence to Captain Keyes's line, in
  Classic and in Anniversary.
- **Expected:** Keyes speaks **English** at `a10_350`, while the cryo
  lines and the lines around it stay Spain Spanish, and the `SU`
  subtitle is unchanged.
- **Then:** restore and verify `ed0ff3ec…`.

| Observation | Meaning | Next |
|---|---|---|
| English Keyes, others Spanish, no errors | MCC accepts a modified bank; the hash field isn't checked against content | record a `correct_audio` + `audio_complete` verification; propose E1b |
| Original Spanish Keyes | the bank wasn't reloaded, or a cached copy exists | check the file was placed (hash), and that MCC was fully restarted |
| Silence at that line, or skipped | the stream or header is rejected for that sample | restore; compare with vgmstream; investigate B2-R4 |
| Hang, crash or anti-cheat message | the bank was rejected | restore and verify immediately; stop and report |

### 5.3 E1 offline result — ✅ PASS (2026-10-08, owner-approved, offline only)

Run: `python scripts/discovery/b2_e1_transplant.py` (approved vgmstream
r2117). It uses the E0 writer plus three new pure helpers in
`fsb5_writer.py`:
- `same_length_compatibility`;
- `replace_stream`, which does not mutate its input;
- `sample_spans`.

Outputs (git-ignored, `work/b2/e1/`):
- `sounds_dialogs_spanish.fsb` (the candidate);
- `vgm/*.wav`;
- `e1_report.json`, `e1_summary.md`;
- `e1_install_rollback.md` (owner-run; **E1-game not approved**).

| | Value |
|---|---|
| Original bank (copy = pin = **installed**, hashed read-only) | `ed0ff3ec240546611a62d2a23d6ce66b5cd7af17527bf1b12834a77fa91faef6` |
| **Candidate bank** | **`86f787ac184897619d471897e41650c04a4f1cb490df1b174c0f6f8793c6f55c`**, 309,320,800 B (same size) |
| Target | Spanish #30 `A10_350_captkeyes` (slot `es:A10_350_captkeyes#0`, subsong 31) ← English #30 `A10_350_CaptKeyes` |
| Target stream | 146,286 B, 198,144 samples, mono, LOOP `0, 198142`; ES `ce2c0d9e…` → EN `0442a6df…` |
| Changed bytes | 138,181, all inside file bytes 3,258,496–3,404,800 (sample #30's span) |

All **23/23** checks pass:
- **Inputs:** the copies (both banks and the Spanish `.lst.bin`) match
  their pins. The target name, occurrence, case-insensitive English
  match and English uniqueness all check out. All six compatibility
  checks are equal: head bits, channels, sample count, chunks, stream
  length and CELT frame sizes (370 B).
- **Byte level:**
  - same size;
  - **every byte outside the target span is identical** (full-file
    comparison);
  - the header, sample headers and name table are identical;
  - **only payload #30 changed**, and the other **5,695** payloads are
    identical;
  - the target payload equals the English span byte for byte.
- **Re-parse:** `fsb5_lib` metadata, names and order are identical; the
  file round-trips through `decompose`/`build`; the build is
  deterministic; the `.lst.bin` is untouched.
- **vgmstream:**
  - subsong 31 decodes to **the same WAV as English subsong 31**
    (`39211c79…`, the E0 English value) and differs from the Spanish
    original (`741eefa4…`), with identical `-m` metadata;
  - neighbours 29, 30, 32 and 33 (`A10_330`–`A10_370`) decode
    identically to the original;
  - so do the representatives 1, 2, 573 (the longest), 4160 and 5600
    (stereo) and 5696;
  - **full bank:** every one of the **5,696 subsongs decodes** from both
    the original and the candidate. The decoded PCM is hashed from
    stdout and no files are written; the check takes about 40 s in
    parallel. **Only subsong 31 differs**, and it equals the English
    decode.

**Tests:** 6 synthetic tests in `tests/test_b2_e1.py` cover:
- the compatible target, and that only the target span changes;
- that Spanish names, header and other samples are kept;
- that the input model isn't mutated;
- flagging of incompatible count, length, channels, frame size and
  LOOP;
- CELT frame-size parsing.

~~**Not yet shown:** that MCC plays the candidate.~~ Shown in §5.4.

### 5.4 E1-game result — ✅ PASS, USER-VERIFIED (2026-10-08)

**Approval:** the owner explicitly approved E1-game. Claude ran the
install and restore with
`python scripts/discovery/b2_bank_install.py {preflight|install|rollback|status}`.
The owner launched MCC with the official **anti-cheat-disabled** option
and played.

Each subcommand refuses to run while MCC or EAC processes exist. Only
`halo1/sound/pc/sounds_dialogs_spanish.fsb` is ever written. State files
are in git-ignored `work/b2/e1/game/`.

| Step | Result |
|---|---|
| Pre-flight | MCC closed; Steam build `19905945`, StateFlags 4 (fully installed, no pending update); installed bank = original `ed0ff3ec…`; candidate = `86f787ac…`, differing from the installed file only inside sample #30 |
| Snapshot | SHA-256 of all 26 files in `halo1/sound/pc` plus `SU`/`SP_Halo1.bin`; size and mtime of all 5,286 install files |
| Backup | `work/mcc/fsb/backup/19905945/sounds_dialogs_spanish.fsb`, verified = original, **kept** |
| Install | the placed bank verified = candidate `86f787ac…` |
| **Owner test** (primary Spanish (Latin America), fallback Spanish (Spain), subtitles on) | **Classic and Anniversary both passed:** Keyes's `a10_350` played **in English, completely**; surrounding dialogue stayed Spain Spanish; the LATAM subtitles were unchanged; no crash, stutter or missing audio |
| Rollback | refused at first, because `MCC-Win64-Shipping.exe` was still running. After the owner closed it, the bank was restored and verified = original `ed0ff3ec…` |
| Snapshot after the restore | 0 hashed files changed; 0 install files added, removed or changed (size or mtime), apart from the bank itself |

**Recorded:** `v-000015` on `mcc:es:A10_350_captkeyes#0`, with checks
`correct_audio` and `audio_complete`, `pass`.
- The fingerprint identifies the retail slot through `samples.spanish`,
  so the validator's drift check stays meaningful.
- An `experiment` block holds the candidate bank, the replacement stream
  and the replaced stream SHA-256 values, plus the modes and settings.

**What E1 establishes:**
- **B2-R2 is resolved:** MCC (FMOD Ex 4.44.27) plays a dialogue bank
  rebuilt by our writer.
- **B2-R4 is resolved:** the 16-byte header hash field is not validated
  against the content. It was left unchanged while one sample's bytes
  changed.
- In both graphics modes, the classic and the Anniversary audio paths
  read the same `sounds_dialogs_spanish.fsb`.

**Still open:**
- **offset shifting**, i.e. a different-length stream (E1b);
- **timing:** does the engine use the FSB length (B2-R3)? (E1b);
- **encoding** CELT ourselves (E2).

### 5.5 Proposed E1b — different-length English→Spanish transplant (NOT approved)

**Candidate survey** (read-only, pinned copies). Pairs are matched by
case-insensitive name, unique in both banks:
- **85 `a10` pairs differ in length.** 83 of them are fully compatible:
  mono, identical frequency and channel bits, LOOP-only chunks, and
  every frame 370 B. The other 2 lack a LOOP chunk on one side.
- Bank-wide, 460 or more compatible pairs differ in length.

**Recommended pair:** `A10_140_cryotech`, Spanish #13 ← English #13
`A10_140_CryoTech`.

| | Spanish (current) | English (replacement) | Change |
|---|---|---|---|
| Samples | 189,440 (4.296 s) | 201,728 (4.574 s) | **+12,288 (+0.279 s), English longer** |
| CELT frames (370 B) | 370 | 394 | +24 |
| Stream / padded span | 139,860 / 139,872 B | 148,932 / 148,960 B | **+9,088 B** |
| LOOP chunk | `0, 189438` | `0, 201726` | follows the `0, n−2` rule |

**Why this pair:**
- It is early in the cryo sequence, just before E1's baseline lines
  (`a10_150`), so it is quick to reach.
- The replacement is **longer**, which is the riskier direction. It
  shows whether the engine cuts a line at the original length or lets
  the next line overlap (B2-R3).
- Index 13 shifts **5,682** later samples, so offset rewriting is
  exercised across almost the whole bank.
- Reserve pair, also MCC-only: `a10_682_cortana` (+2.067 s, 573 →
  751 frames, the largest `a10` delta). It is later in the level, and
  a candidate if the timing effect in `a10_140` is too small to judge.
  It would need a separate approval.

**What the writer must change** (an in-memory dry run confirmed this;
**no file was written**):
- **Sample #13:**
  - the stream is replaced;
  - the `sample_count` field is set to 201,728;
  - LOOP is set to `0, 201726`;
  - the frequency and channel bits are unchanged.
- **Samples #14–#5,695:** the data offset moves **+9,088 B**, which
  keeps 32-byte alignment. Every byte of their streams, counts and
  chunks stays identical.
- **Header:** `data_size` goes from 309,095,808 to 309,104,896.
  `sample_headers_size` (the LOOP chunk keeps its 8 B), the name table
  and the 32-byte header tail (flags and hash) are unchanged.
- **File size:** 309,320,800 → **309,329,888 B**.
- **`.lst.bin`: unchanged.** It maps tags to sample *index* ranges and
  counts, not byte offsets or durations, so it stays valid.
- One small writer API addition is needed: replace a sample's
  `sample_count` and `chunks` together with the stream. Today
  `replace_stream` only swaps the stream. A
  `different_length_compatibility` check would require identical head
  bits and channels, LOOP-only chunks, 370 B frames, and
  `frames == ceil(n / 512)`.

**E1b offline checks:**
- copies verified against their pins;
- payload by **index**: 5,695 identical, and #13 equal to English #13;
- every later offset shifted by exactly +9,088, 32-byte aligned;
- the size equation holds;
- the name table, header tail and other sample headers are identical,
  apart from offset bits;
- re-parse plus round trip; deterministic;
- `.lst.bin` untouched;
- **vgmstream on all 5,696 subsongs:** only #14 differs, and it equals
  English subsong 14 with the new length in `-m`. The neighbours
  (`A10_101`, `A10_130`, `A10_150`) and the representatives are
  unchanged.

**E1b-game** (separate approval; same procedure and script pattern as
E1, with the size change allowed in the snapshot):
- **Expected:** at `a10_140`, the Cryo Tech speaks **English** for about
  4.57 s. All other lines are Spain Spanish, and the LATAM subtitles are
  unchanged.
- **Owner observes:**
  - whether the line plays to the end or is **cut at about 4.30 s**;
  - whether the **next line** (`a10_150`) starts late, overlaps, or
    behaves normally;
  - any stutter or desync.
- **Interpretation:**
  - plays fully with no overlap → the engine follows the FSB length;
  - cut off → length comes from tag or map data, and longer lines need
    trims (recipes) or a different approach;
  - overlap → note it for timing-sensitive slots in M4/M6.

### 5.6 E1b offline result — ✅ PASS (2026-10-08)

Run: `python scripts/discovery/b2_transplant.py --exp e1b --name A10_140_cryotech`
(about 40 s). This general transplant tool handles any length; `fsb5_writer`
gained `replacement_compatibility`, `replace_sample` and `loop_chunk`.
- **Candidate:** `work/b2/e1b/sounds_dialogs_spanish.fsb`, SHA-256
  `6a861d0240640aa4395a6dda3ade55b13680613d32e47334a2eb0fb1db6cbbc7`.
  The size is 309,329,888 B (**+9,088 B**).
- **Slot #13:** 4.296 s → 4.574 s (201,728 samples), LOOP `0, 201726`,
  frequency and channel bits unchanged.
- **25/25 checks pass:**
  - every one of the other 5,695 samples is identical, including the
    model and the payload by index;
  - earlier offsets are unchanged, and the 5,682 later offsets all shift
    by exactly +9,088, 32-byte aligned;
  - `data_size` and the file size are +9,088, and the size equation
    holds;
  - the header tail, `sample_headers_size`, name-table bytes, names and
    order are identical;
  - the file round-trips and the build is deterministic;
  - `.lst.bin` is untouched;
  - vgmstream: all 5,696 subsongs decode, only #14 differs, it equals
    English #14, and `-m` reports 201,728 samples.
- **Install path:** `scripts/discovery/b2_bank_install.py --exp e1b`
  (the E1 script, renamed and generalised). Its pre-flight now checks,
  by model comparison, that only the target sample differs. The sheet is
  `work/b2/e1b/e1b_install_rollback.md`. **E1b-game is not approved.**

## 6. Risks

| ID | Risk | Impact | Mitigation / test |
|---|---|---|---|
| B2-R1 | No approvable CELT 0.11 encoder, or FMOD-incompatible encodes | S-A blocked | E2 qualifies the encoder offline against vgmstream; fall back to S-B/S-C |
| B2-R2 | Runtime rejects a rebuilt bank | no audio replacement | E1 tests acceptance with zero encoding risk |
| B2-R3 | Engine times dialogue from tag/map data, not FSB length | longer lines cut off, overlaps | E1b; length deltas shown in the M4 UI; trims as recipes |
| B2-R4 | The 16-byte header hash field is checked | rebuilt bank rejected | E1 keeps it unchanged; if rejected, research before any change |
| B2-R5 | 40 stereo slots, mono source | channel mismatch | owner per-slot choice (§4) |
| B2-R6 | Resampling or loudness artefacts | quality | recipes, A/B listening, owner approval |
| B2-R7 | MCC updates replace the bank | mod silently gone or stale | pins, drift reports, re-verify after updates |
| B2-R8 | A 309 MB bank in place, with EAC off | rollback burden | hash-verified backup and restore, as in B1; Steam "Verify integrity" as a safety net |
| B2-R9 | **Workshop cannot deliver it:** Excession documents map packages only, with no documented override of `halo1/sound/pc/*.fsb` or `Data/ui/localization/*.bin`. Whether a custom H1 `.map` can carry its own playable dialogue audio is unknown | release channel | WC (roadmap §6) answers before full production; likely outcome B or C |
| B2-R10 | **Redistribution:** the MCC FAQ allows only retail MCC assets; the Content Usage Rules allow personal, non-commercial use. CE audio and text are another game's assets | a public build with CE content presumed not permitted | M8.1 memo; `public` profile with zero CE bytes; new recordings or owner text (M8.2). A delta/patch delivery would still embed CE-derived audio, so it does not solve this |

[^vgm-celt]: vgmstream, [`src/coding/celt_fsb_decoder.c`](https://github.com/vgmstream/vgmstream/blob/master/src/coding/celt_fsb_decoder.c): CELT 0.6.1 (`0x80000009`) and 0.11.0 (`0x80000010`), sync `0x17C30DF3`, 512-sample CBR frames, 44,100 Hz mode.
[^vgm-fsb5]: vgmstream, [`src/meta/fsb5.c`](https://github.com/vgmstream/vgmstream/blob/master/src/meta/fsb5.c): header layout, per-bank codec `mode`, sample header bitfield, chunk types, size equation.
[^pyfsb5]: HearthSim, [python-fsb5](https://github.com/HearthSim/python-fsb5/blob/master/fsb5/__init__.py): same layout; decoder only (no CELT rebuild).
[^vgm-vorbis]: vgmstream, [`src/coding/vorbis_custom_utils_fsb.c`](https://github.com/vgmstream/vgmstream/blob/master/src/coding/vorbis_custom_utils_fsb.c): FSB Vorbis setup packets are external (runtime-built), referenced by setup ID.
[^fsbank-enum]: LWJGL, [FSBank bindings](https://javadoc.lwjgl.org/org/lwjgl/fmod/FSBank.html): `FSBANK_FORMAT_*` = PCM, XMA, AT9, VORBIS, FADPCM, OPUS (no CELT).
[^fsbext]: [fsbext](https://github.com/HanabishiRecca/fsbext): claims FSB rebuild from extracted data; not verified for FSB5.
[^celt011]: [mumble-voip/celt-0.11.0](https://github.com/mumble-voip/celt-0.11.0): CELT 0.11.0 source, including the encoder.
[^c20-tool]: Reclaimers c20, [H1 Tool](https://c20.reclaimers.net/h1/h1-ek/h1-tool/) (`export-sounds-to-fsb`, `build-cache-file … resource-map-usage`) and [H1 maps](https://c20.reclaimers.net/h1/maps/) ("sounds are now in FMOD sound banks").

Further sources, already cited in the project:
- the Excession docs and Halo Support EAC article (roadmap M8);
- the MCC EULA FAQ, [halowaypoint.com/news/mccs-eula-the-faq](https://www.halowaypoint.com/news/mccs-eula-the-faq);
- Microsoft [Game Content Usage Rules](https://www.xbox.com/en-US/developers/rules).

Unreachable this session (blocked or JS-only): fmod.com docs and
licensing, Nexus mod pages, Halo Support pages, Steam discussions.
