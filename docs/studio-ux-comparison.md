# Classic M4 page versus the Studio matching workspace

How the two compare, measured in Microsoft Edge with Playwright on disposable data, and by reading both
implementations. The classic page (`scripts/ui/m4.html`) is the functional reference. Its look is not.

Reproduce the measurements: `npm run compare:m4` in `frontend/` (writes `frontend/e2e/out/compare.json`,
which is git-ignored). The browser checks of the Studio are `npm run test:e2e` and `npm run test:ux`.

## The same task in both

Task: choose line `a10_010_cryotech`, choose recording `vo_scr_m01_00460_cryotech#0` as the replacement,
save the draft. Each run starts from its own fresh copy of the mapping data.

| | Actions | Time (s) | Notes |
|---|---|---|---|
| Classic M4 | 4 | 6.2 | Click the line; type in the candidate search; click "+ use for this slot"; click Save. |
| Studio | 4 | 8.6 | Click the line; type in the candidate search; click "Use this recording"; click Save draft. |

The Studio is about two seconds slower here. The likely causes are the 250 ms search debounce and the
wait for the candidate list. This has not been profiled yet.

## Controls on the first screen

Visible controls at 1440 × 960, counted in the browser:

| | Buttons | Text inputs | Selects | Checkboxes |
|---|---|---|---|---|
| Classic M4 | 1 | 2 | 5 | 2 |
| Studio | 1 | 2 | 4 | 1 |

The classic page is denser: each MCC row has status letters, durations and the speaker on one line,
and a progress bar and keyboard legend sit above the lists. The Studio's rows are taller and more spacious.

## What the classic page did better, and what the Studio now does

| Interaction | Classic M4 | Studio before | Studio now |
|---|---|---|---|
| Next and previous MCC line | `j` / `k` | `[` / `]` only | `j` / `k` (and `[` / `]` removed to avoid two keys for one job) |
| Play Spain's recording | `Space` | `m` | `Space` and `m` |
| Play a candidate | `1`–`9` (es-MX) | none | `1`–`9` (es-MX), plays without selecting |
| Move through candidates | mouse only | none | `↑` / `↓`, highlight only, never selects |
| Keyboard legend | on screen | none | on screen, above the panels |
| Status per MCC row | letters with colour | words in badges (large) | letters with a glyph and a word (`A✓`, `S•`, `R`), never colour alone |
| Level progress | bar and count | count only | bar and count |
| Search every level | checkbox | none | "All levels" in the level list |
| es-MX subtitle filter for candidates | `any` / `missing` / `present` | none | `Any` / `Has one` / `None` |
| Audio fades | yes | none | fade in and out (ms) |
| Loudness matched to Spain, with limiter | yes | none | loudness mode, offset and limiter |
| Silences inserted | yes | none | still classic only |
| Several recordings for one subtitle (`ce_concat`) | yes | none | still classic only |
| Level status (in progress, ready, tested) | yes | progress only | still classic only |
| Validation footer | yes | none | still classic only |

## What the Studio does that the classic page did not

- Panels can be resized by dragging the dividers, with the arrow keys, and with widths kept between
  visits. Reset layout returns to the defaults.
- Save and approval stay in view while the centre panel scrolls.
- A conflict (another window changed the line) refuses the save, keeps everything typed, and offers
  *Reload and keep my edits*.
- Unsaved typing survives a reload for the same stored version; leaving a line with unsaved changes asks first.
- The URL keeps the selected line and every filter.
- Each approval and rework is a confirmed button press, and an unavailable button says why.
- A Halo-inspired dark theme, with every colour defined in one place and tested for contrast.

## Left to do

- Silences, the validation footer, level status, and several recordings for one subtitle still need the
  classic page. They are the only reasons to open it during matching.
- The Studio's time to complete the task (8.6 s against 6.2 s) needs profiling before it is called
  faster or slower in practice.
