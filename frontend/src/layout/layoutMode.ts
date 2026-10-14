// Which layout the Studio uses for the current window: the three resizable panels on a desktop, two panes on
// a tablet, and one pane at a time on a phone. Pure arithmetic here (unit-tested); useLayoutMode.ts keeps the
// reactive value and the `data-layout` attribute of the page in step with the window.
//
//   desktop  width >= 1000 px                  MCC | Matching | Campaign Evolved, resizable (unchanged)
//   tablet   700–999 px wide, >= 500 px tall   a list (MCC or Campaign Evolved) beside the Matching panel
//   phone    narrower, or a landscape phone     one pane at a time, bottom navigation
//
// 1000 px is where the three panels stop fitting at their minimum widths (workspaceLayout.ts: 240 + 420 +
// 260 + the dividers). A phone held sideways is wide but short: it keeps the one-pane layout, where the page
// scrolls, instead of two short panes.

export type LayoutMode = "phone" | "tablet" | "desktop";

export const DESKTOP_MIN_WIDTH = 1000;
export const TABLET_MIN_WIDTH = 700;
export const TABLET_MIN_HEIGHT = 500;

export function layoutModeFor(width: number, height: number): LayoutMode {
  if (width >= DESKTOP_MIN_WIDTH) return "desktop";
  if (width >= TABLET_MIN_WIDTH && height >= TABLET_MIN_HEIGHT) return "tablet";
  return "phone";
}

/** The panes of the matching workspace, as named in the URL (`pane=`) and the navigation. */
export type Pane = "mcc" | "match" | "ce";
export const PANES: Pane[] = ["mcc", "match", "ce"];

export function paneFrom(value: unknown, fallback: Pane): Pane {
  return PANES.includes(value as Pane) ? (value as Pane) : fallback;
}
