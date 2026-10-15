# Using the Studio on a phone or tablet

The Studio is one application for every screen. A phone or tablet opens the Studio running on the host
computer, through the same remote listener, sign-in and roles as a second computer
([remote-access.md](remote-access.md)). Nothing is installed on the phone, and no game file, recording or
tool is copied to it. Recordings, waveforms and edited previews stream from the host. Every decision is
written to the host's database (`mappings/manual_mappings.db`), the same one the desktop uses.

- [1. Connect](#1-connect)
- [2. The layouts](#2-the-layouts)
- [3. Matching on a phone](#3-matching-on-a-phone)
- [4. Editing audio with a finger](#4-editing-audio-with-a-finger)
- [5. Listen and compare](#5-listen-and-compare)
- [6. Subtitles, saving and approvals](#6-subtitles-saving-and-approvals)
- [7. Limits](#7-limits)
- [8. For developers](#8-for-developers)
- [9. Install it as an app](#9-install-it-as-an-app)

## 1. Connect

1. On the host, start the Studio with remote access: `npm run host` (from `frontend/`). See
   [remote-access.md §2](remote-access.md#2-start-the-host).
2. On the phone, open the address shown on the host's **Network** page:
   - at home, on the same Wi-Fi: the LAN address, such as `http://192.168.1.10:8766/` (§4 there);
   - from anywhere: the Tailscale address, such as `https://studio-pc.tail1234.ts.net/`, with the Tailscale app
     signed in on the phone (§5 there).
3. Sign in with your Studio account.

The remote listener always asks for a sign-in, and it can never install into the game or restore it. Build &
Test installs stay on the host's own `127.0.0.1` page. Use the Tailscale route away from home: the LAN address
is not encrypted.

## 2. The layouts

The layout follows the screen. Turning the phone or resizing a window only changes the layout: nothing reloads,
and the open line, unsaved edits, searches and players stay as they were.

| Screen | Layout |
|---|---|
| Phone (narrower than 700 px), or a phone held sideways | One pane at a time: **MCC**, **Matching**, **Campaign Evolved**, switched by the bottom navigation. |
| Tablet upright (700–999 px wide) | A list (MCC or Campaign Evolved, switched above it) beside the Matching panel. |
| 1000 px and wider (desktop, tablet held sideways) | The three resizable panels, as before. |

On touch screens, buttons, fields and choices are at least 44 px tall, and fields use 16 px text, so the phone
does not zoom in when you type. Keyboard hints are hidden on touch screens. The app menu is behind the button at
the top right.

## 3. Matching on a phone

1. **MCC**: choose the level, filter and search as on the desktop. **ES** / **EN** play a line without opening
   it. Tap a line to open it: the Matching pane opens at its top.
2. The bar at the top always shows the open line: **ES** plays Spain's original, then the MCC key, then
   **M / A / S** for the match, audio and subtitle state (✓ approved, • draft, ! needs rework, – none), and
   **unsaved** when there is something to save. It stays on screen while you scroll, and also on the
   candidates pane, so you can replay the original while comparing candidates. On the Matching pane its chips
   jump to **Audio, Flags, Edit, Compare, Subtitles, Save**.
3. **Campaign Evolved**: search and listen (**es-MX** / **EN**), then **Use this recording**. A strip above the
   navigation confirms it and offers **Review**, which opens the Matching pane. The tab shows how many
   recordings are matched to the line.
4. Each pane keeps its own search and scroll position. Tapping the current tab again returns to its top.

**The save strip.** When the open line has unsaved changes, **Save** and **Next** (save, then open the next
unmatched line) stay above the navigation on every pane. The strip steps aside while the save bar at the end of
the Matching pane is on screen. Both strips and the navigation also hide while the keyboard is up.

Nothing is matched or approved automatically. **Use this recording** proposes the recording's LATAM subtitle
as an unsaved choice, exactly as on the desktop.

## 4. Editing audio with a finger

The audio editor is the same as on the desktop (§4.1 of the [user guide](m4-user-guide.md)), adapted for touch:

- **Tap** the waveform to move the playhead.
- **Drag sideways** to select. Swipe **up or down** to scroll the page: the waveform takes only sideways drags.
- The trim handles (cyan) are a finger wide. Drag them to trim. Drag the selection's edges or body to adjust it.
- **Selection start / end (s)**: type a selection to the hundredth of a second, then **Trim to selection** or
  **Cut selection**.
- **Zoom in / Fit / Zoom out** as on the desktop. When zoomed in, **Select / Pan** chooses what a sideways drag
  does: select, or scroll along the recording.
- **Insert silence**, **fades**, **radio filter**, **echo**, **Undo** and **Reset edits** work as on the desktop.
  Every value can also be typed in.
- **Full screen** gives the editor the whole screen, with **Original** and **Edited result** to listen without
  leaving it. **Done** returns to the page, with nothing reloaded and the undo history intact.

Edits are a recipe saved with the audio decision. The original recording is never changed, and the edited
result is rendered on the host exactly as the build renders it.

## 5. Listen and compare

**Original (A)** and **Replacement (B)** play each recording from the start. **A then B** plays the original and
then the replacement. **A / B** switches between them at the same position, and **Stop** stops both. Only one
recording plays at a time, and nothing plays until you tap. B is the edited recording, rendered again
automatically after each change ("Rendering the latest edits…" while it renders). The durations of A, B and
their difference are shown below. While a recording loads on a slow connection, its button shows a spinner.

## 6. Subtitles, saving and approvals

- The subtitle choices are whole-row buttons. The preview shows the text the game will show, in large type.
- **Write my own** opens a large text box. It starts from the chosen recording's LATAM subtitle, or MCC's when no
  recording is chosen.
- Unsaved changes survive switching panes, turning the phone and reloading the page (in the same browser
  session).
- **Save draft** saves the audio, its editing, the subtitle, the flags and the notes together, and approves
  nothing.
- **Approve audio** and **Approve subtitle** are separate buttons, each with a confirmation. **Approve both**
  does both in one save.
- **Needs rework** unlocks an approved decision, again with a confirmation. Approved decisions cannot be edited
  until then, from a phone as from the desktop.

## 7. Limits

- Keyboard shortcuts need a keyboard. With a tablet keyboard they work as on the desktop.
- Dividers cannot be resized on a phone or an upright tablet: the panes fill the screen.
- Build & Test installs and restores only on the host's own page, never from a phone.
- Some phones (Safari on iOS) allow audio only after a tap. Every player starts from a tap, and **A then B**
  unlocks B during the same tap.

## 8. For developers

- The layout mode is computed once in `frontend/src/layout/useLayoutMode.ts` (rules and breakpoints in
  `layoutMode.ts`, unit-tested) and written to `<html data-layout="phone|tablet|desktop">`. The styles in
  `frontend/src/styles/mobile.css` key on that attribute, and on `(pointer: coarse)` for touch sizing.
  Media queries are used to measure, not `window.innerWidth`, because a phone's layout viewport can briefly be
  wider than the screen.
- `MatchView.vue` keeps all three panels mounted. Panes are shown or hidden by CSS only, and the pane is in the
  URL (`pane=mcc|match|ce`). New pieces: `WorkspaceTabs.vue`, `MatchContextBar.vue`, `MobileActionStrip.vue`.
- Touch on the waveform (`WaveformView.vue`): `touch-action: pan-y` on WaveSurfer's scroll part, finger-wide
  handles, Select / Pan when zoomed in, `select(span)` for typed selections, and `prime()` to unlock B for
  **A then B**.
- No server change was needed: audio is already served with byte ranges, ETags and immutable caching, and
  waveforms use server peaks, so a phone downloads only what it plays.
- Test: `npm run test:mobile` drives an emulated phone with real touch events (Chrome DevTools Protocol) on
  disposable data, then the same page sideways, as a tablet and as a desktop, and checks for sideways overflow
  at 360, 390, 430, 768 and 1024 px. It needs Microsoft Edge.
- `npm run test:layout` checks every page at 360–1920 px for text that escapes its box, sideways scroll and
  small touch targets, with real data ([ui-design-system.md §6](ui-design-system.md#long-values-and-narrow-screens)).
- Build & Test shows compact cards on phones and upright tablets (two columns on a tablet), newest first and
  grouped by day, with the same search and filters as the desktop. Each card has:
  - the time, type, folders and lines;
  - the status badges;
  - **Details** (level, files, validation, subtitles);
  - **Install to MCC**, which still works only on the host's own page.

## 9. Install it as an app

The Studio can be installed on a phone or tablet as **Halo Studio**. It then opens from its own icon, full
screen, without the browser's address bar, and keeps you signed in.

**Install**

1. Open the Studio's **https** address: the Tailscale address (`https://studio-pc.tail1234.ts.net/`,
   [remote-access.md §5](remote-access.md#5-secure-internet-access-tailscale-recommended)). Browsers only install
   apps from secure addresses, so the plain-http LAN address works in the browser but cannot be installed.
   Tailscale keeps the Studio private: it is reachable only from your own devices, never from the public internet.
   Or the owner's Cloudflare address, `https://studio.andresgustavo.com`, where Cloudflare Access signs you in
   ([deploy-cloudflare.md](deploy-cloudflare.md)).
2. Sign in (with Cloudflare Access on the Cloudflare address).
3. Install:
   - **Android (Chrome, Edge):** **Install app** in the Studio's menu, or the browser's *Install app* /
     *Add to Home screen*.
   - **iPhone, iPad (Safari):** Share → **Add to Home Screen**.

The **Network** page shows the right steps for the device you are on.

**What it keeps on the phone.** Only the Studio's own built files (its screens, styles, fonts and icons), so it
can open and explain when the host cannot be reached. Recordings, waveforms, previews, decisions, subtitles and
API answers are never stored by the app: they always come from the host while it is connected. Your session is
the same HttpOnly cookie as in the browser (it expires as configured on the host,
`session.max_days`); no token is kept in the page's storage. There is no offline matching.

**When the host is unreachable.** The app still opens and says whether the phone is offline or the host cannot
be reached, with what to check (host on and awake, `npm run host` running, Wi-Fi or Tailscale connected). It
reconnects by itself when the connection returns, or press **Try again**. Unsaved edits are kept for the session.

**Updates.** After the host is updated and rebuilt (`npm run host` builds every time), the app shows *A new
version of the Studio is available* with **Reload**. It never reloads by itself in the middle of an edit, and
the next launch uses the new version anyway. Unsaved edits survive the reload.

**For developers.** `vite-plugin-pwa` (generateSW) in `frontend/vite.config.ts`: the manifest, and a service
worker that precaches the built files only, with no run-time caching. Its navigation fallback excludes `/api`,
`/audio` and `/classic`. Registration, the update prompt and the install offer are in `frontend/src/pwa.ts`
(`PwaBanner.vue`, `InstallApp.vue`); the unreachable screen is `HostUnreachable.vue`. The server serves
`sw.js`, `index.html` and the manifest with `Cache-Control: no-cache` (ETag revalidation), so a rebuild is seen at
once; hashed assets stay immutable. The icons are drawn by `npm run icons` (`frontend/scripts/make-icons.mjs`,
renders with Edge) into `frontend/public/`. The worker is not active under `npm run dev`. The Studio is expected
at the root of its address (`/`), as `npm run host` and Tailscale Serve provide. `npm run test:pwa` checks it all
against the production server.
