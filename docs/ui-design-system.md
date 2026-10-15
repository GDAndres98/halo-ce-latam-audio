# Studio design system: the original Xbox *Halo: Combat Evolved* menus

The Studio (`frontend/`) reinterprets the menu system of *Halo: Combat Evolved* (Xbox, 2001) as a
localization workstation. This note records the references, the patterns taken from them, how each pattern
maps onto code, and the rules for extending the theme. It covers looks only. Mapping logic, approvals and
audio processing are unchanged by the theme.

## 1. References

These were studied on 2026-10-11:

| Reference | What it shows | Source |
|---|---|---|
| *Halo Demo* "CONTROLLER CONFIGURATION" pop-up, captured in the Xbox emulator Xemu | The original Xbox pop-up box: navy panel, bright blue rounded frame with glow, title band over a rule, light-blue labels, white prompt line | [Halopedia file](https://www.halopedia.org/File:HCE_Demo_ControlSchemes_Screenshot.png) |
| "EDIT MULTIPLAYER GAMETYPE" (custom games menu) | The menu screen: huge wide blue uppercase title over a full-width rule; a list of blue uppercase items; the selected item framed, its words near-white, the frame joining the description panel; a darker bottom band with rounded OK and CANCEL buttons | [Halopedia, HCE menu screenshots](https://www.halopedia.org/Category:Halo:_Combat_Evolved_menu_screenshots) |
| Main menu (Custom Edition capture) | Centred blue menu items, the selected one white and glowing; a ring in orbit over space; a holographic reticle and horizontal lines behind the title | same category |
| Halopedia, "Main menu" | The original menu is set in orbit of Installation 04, with the camera moving around the ring | [Halopedia, Main menu](https://www.halopedia.org/Main_menu) |
| Halopedia, Beta 1749 | The pre-release menu kept the same panel language, with a still camera on the ring | [Halopedia, Beta 1749](https://halopedia.org/Halo:_Combat_Evolved_Beta_1749) |

**Caveat.** Clean captures of the original Xbox main menu and difficulty screens are rare online. The Xemu
demo capture is a genuine Xbox build. The custom games and main-menu captures come from the PC versions,
which reuse the Xbox menu system. MCC's Classic mode and the later Anniversary menus were deliberately not
used as references.

## 2. Patterns taken from the references

1. **Space backdrop.** Near-black navy, stars, a ring seen nearly edge-on, a planet's lit limb, and faint
   reticle circles and lines behind the titles.
2. **The panel frame.** Translucent dark navy, a bright blue outline (about 2 px) with soft rounded corners
   and a soft blue glow.
3. **Title band.** The panel name in wide uppercase blue, with a rule across the whole panel under it.
4. **Screen title.** Very large, wide, uppercase, menu-blue, over a full-width lit rule.
5. **Menu items.** Blue uppercase words. The **selected** item gets a rounded outline frame and its words
   turn near-white. On the custom games screen that frame **merges into the description panel** beside it.
6. **Bottom action band.** A darker strip under a lit rule, with rounded, framed buttons in light words
   (OK / CANCEL).
7. **Prompts.** Controller-button glyphs inline with text ("PRESS START OR (A) TO CONTINUE").
8. **HUD meters.** Segmented, slanted bars (the shield meter in the same capture's HUD).
9. **Colour.** One dominant saturated blue for frames, titles and unselected items; near-white for the
   selection and for values; the dark-green Xbox accent sparingly.

## 3. How each pattern maps to the Studio

| Pattern | Where in the Studio | Code |
|---|---|---|
| Space backdrop | Behind every screen; static SVG, painted once | `components/AppBackdrop.vue`, `styles/shell.css` `.backdrop` |
| Panel frame | Matching columns, cards, dashboard detail, dialog | `.panel`, `.column`, `.card` in `styles/panels.css` |
| Title band | Column titles, card titles, dialog title | `components/ui/PanelHeader.vue` (`.panel-head`); a plain `h2` in a `.column`/`.card` gets the same look |
| Screen title | Dashboard, Build & Test, Data | `components/ui/PageHeader.vue` (`.page-head`) |
| Menu items, selection | Top navigation; dashboard level list; MCC and candidate lists | `.top nav a.router-link-active`, `.menu-item.highlighted`, `.row-item.selected` |
| Selection merging into its panel | Dashboard: the highlighted level opens into the description panel. Matching: a lit connector runs from the selected MCC line towards the decision panel | `styles/pages.css` `.menu-item.highlighted`; `styles/workspace.css` `.column.mcc .row-item.selected::after` |
| Bottom action band | "Save and approve" (sticky), dialog buttons, dashboard detail actions | `.action-band`, `.approvals`, `.detail-actions` |
| Prompts | Keyboard legend and hints | `kbd` in `styles/controls.css` |
| HUD meters | Level progress, campaign totals | `components/ui/HudMeter.vue`, `.progressbar` |
| Numbered identifiers | Centre-panel sections show "01 LISTEN AND COMPARE" … "06 SAVE AND APPROVE" | CSS counter on `.sections .block h3` (no template numbers) |

Original items with no direct game equivalent use the same language. Examples are the waveform display (a
recessed "well" with a faint measuring grid and A / B channel tags), the confirmation dialog (the Halo Demo
pop-up), and the status badges.

## 4. Tokens

All colours, fonts and shapes are in `frontend/src/theme/tokens.ts`. They are set as CSS variables at
start-up. Stylesheets use only the variables.

| Token | Value | Use |
|---|---|---|
| `--frame` | `#2f8cff` | Panel outlines, selection frames, rules |
| `--frame-dim` | `#1d4e8f` | Resting outlines of fields and buttons, inner rules |
| `--menu` | `#4da3ff` | Titles, labels, unselected menu items |
| `--text` | `#dce9f8` | Reading text, selected items |
| `--muted` | `#8fa9cc` | Secondary text |
| `--panel` / `--panel-glass` | `#061230` / 90 % | Panel fill |
| `--well` | `#020818` | Recessed areas: fields, waveforms, logs |
| `--focus` | `#7fe3ff` | Keyboard focus ring, playhead (cyan, never confused with the frame) |
| `--green` / `--ok` | `#8ecb5b` / `#97d468` | Approval and "approved" |
| `--warn`, `--bad`, `--radio` | amber, coral, violet | Draft, needs rework, radio-effect flag |

`tokens.test.ts` checks WCAG AA contrast for every text colour on every surface, including a translucent
panel over the backdrop's brightest spot. A token change that hurts readability fails the unit tests.

## 5. Typography

| Role | Face | Licence | Notes |
|---|---|---|---|
| Titles, navigation, panel bands, dialog titles | **Michroma** (`@fontsource/michroma`) | SIL OFL 1.1 | Wide geometric face in the spirit of the original menu titles. Used only for short uppercase titles, never for data. |
| Everything else | **Saira** variable (`@fontsource-variable/saira`) | SIL OFL 1.1 | Squared, technical, readable at small sizes; buttons use it in uppercase with modest tracking. |
| IDs, times, hashes | Cascadia Mono / Consolas (system) | not bundled | Tabular figures for times and durations. |

The fonts are bundled with the app (no network requests). No game font is used. Dense data such as tags,
subtitles and tables is never letter-spaced. Only short labels are tracked.

## 6. Components

All live in `frontend/src/components/`:

- `ui/PageHeader.vue` is a screen title, with an optional icon, lead line and actions.
- `ui/PanelHeader.vue` is a panel's title band, with an icon, a title, an optional short code (`M6`,
  `EXPORT`) and actions.
- `ui/HudMeter.vue` is a labelled segmented meter with its numbers in words (`role="progressbar"`).
- `ui/StateMessage.vue` shows loading, empty, error, warning and success states, each with an icon and
  words.
- `ui/ConfirmDialog.vue` with `composables/useConfirm.ts` is the Studio's only confirmation. Usage:
  `await confirmAction({ title, message, confirmLabel, tone })`.
  - It is a modal `<dialog>`. Focus starts on **Cancel**, so Enter alone never confirms.
  - Esc cancels.
  - Keyboard shortcuts pause while it is open.
  - The browser's `window.confirm` is no longer used anywhere.
- `StatusBadge.vue` shows an icon plus a word. The tone colour only repeats the meaning.
- `build/BuildHistory.vue` is the Build & Test build list. On the desktop it is a table, and below 1000 px
  (`data-layout` phone or tablet) it is one card per build. Builds are listed newest first by their real
  `built_at` time (`src/build/history.ts`), with a copy button on each name and the details opening in place.
- `AppBackdrop.vue` and `AppEmblem.vue` are original SVG art: a ring around a sphere. They are not the
  Halo logo.

Native controls (buttons, fields, selects, checkboxes, radio buttons, scrollbars) are themed globally in
`styles/controls.css`, so no screen falls back to the browser's look.

**Button roles:**

| Class | Look | Use |
|---|---|---|
| (none) | Navy fill, dim frame | Ordinary actions |
| `.primary` | Bright menu-blue fill | The main action of a screen: save, build, import |
| `.approve` | Green frame | Approval; always paired with a check icon and the word "Approve" |
| `.caution` | Amber frame | Restore and other recoverable changes to the install |
| `.primary-soft` | Bright frame | Secondary emphasis: preview, use this recording |
| `.link` | Text | Actions inside sentences |

Important actions carry an icon (lucide) and a word. Icon-only buttons (zoom, clear selection) have an
accessible name and a tooltip.

### Long values and narrow screens

Identifiers (slot IDs, Campaign Evolved line refs, build names, file paths) have no spaces. The rules below
keep them, and long generated text, inside their boxes. They do not hide overflow:

- `.tag`, build names and the paths in build details wrap anywhere (`overflow-wrap: anywhere`). They are
  never cut, because the end of an ID (`#0`, a timestamp) is often the part that tells two apart. They are
  also never upper-cased.
- A shortened value (`text-overflow: ellipsis`) always has its full text in a `title` and somewhere else on the
  page, such as the build details.
- A `fieldset` may shrink (`min-width: 0`), and a `select` never grows past its box because of a long option.
- Grid and flex children that hold text get `min-width: 0` (`minmax(0, 1fr)` columns).
- Groups of controls wrap (`flex-wrap: wrap`).
- On touch screens, controls are at least 40–44 px tall, including text links (`button.link`), section
  chips and `<summary>` toggles.
- Bars that run edge to edge on purpose use negative side margins or `position: fixed`.

`npm run test:layout` (`frontend/e2e/layout.mjs`) checks this on the rendered pages. It opens every page at
360, 390, 430, 768, 1024, 1440 and 1920 px, with the real decisions and builds on a disposable copy. It
reports:

- sideways page scroll;
- text drawn outside its box;
- elements outside the window;
- touch targets under 40 px.

It also checks the build list's order and layout. With `-- --shots`, it saves screenshots to
`frontend/e2e/out/layout/`.

## 7. Interaction and motion

- **Hover** lights a control's frame and adds a soft glow.
- **Selection** frames the item, turns its words near-white, and, where there is a panel beside it, joins
  them.
- **Focus** is a 2 px cyan ring on every control, never removed.
- Transitions are 120 ms (colour, border, glow). The dialog fades in over 140 ms. The loading mark steps
  through three segments. Nothing else moves.
- `prefers-reduced-motion: reduce` turns all transitions and animations off.
- No sounds are played by the interface.

## 8. Performance rules

- The backdrop is one static SVG on a fixed layer, painted once. It has no animation and no filters.
- No `backdrop-filter` or blur is used. Glows are plain `box-shadow` on a handful of elements.
- Long lists keep their paging ("Show more"). `content-visibility` is deliberately not used on rows: skipped
  rows report empty text to find-in-page, assistive tools and tests.
- Waveform loading, caching and playback code is unchanged. Only its colours come from the theme.

- Transitions run only on hover-in (the frame lights up). State changes made by the app, such as a control
  becoming enabled or a row becoming selected, are instant. Loading a line therefore starts no animations.
- No `:has()` selectors (the wide matching layout is a route class on `main`).

These were measured on 2026-10-11 with `npm run perf`, A/B against the previous theme on the same machine
and data, 10 iterations, Edge:

| Step | Previous theme | This theme |
|---|---|---|
| Select a line (median) | 126–135 ms | 90–100 ms |
| Next line, keyboard | 59–63 ms | 64–65 ms |
| Open the workspace (cold, includes fonts) | about 1.5 s | about 1.6 s |
| Save (median) | 305 ms | 380–390 ms |

The save difference is server time. In the page, "Draft saved." appears about 20 ms after the server
answers in both versions. `npm run test:theme` also checks a median J/K line change under 400 ms and no long
tasks while idle.

## 9. Extending the theme

1. Put a new colour in `COLOURS` and `cssVariables()` in `tokens.ts`, with a contrast case in
   `tokens.test.ts` if it is used for text.
2. Put styles in the stylesheet for their area (`styles/index.css` lists them). Avoid styles in components.
3. A new screen starts with `PageHeader`. Its sections are `.panel` with a `PanelHeader`. Loading and
   empty states use `StateMessage`. Confirmations use `confirmAction`.
4. Status is always an icon or glyph plus a word.
5. Run `npm test`, `npm run typecheck` and `npm run test:theme`. The theme test screenshots every screen into
   `frontend/e2e/out/theme-*.png` and checks fonts, contrast, the dialog, keyboard menus, reduced motion,
   overflow at 390–1440 px and responsiveness. Run `npm run test:layout` for long content at 360–1920 px.
