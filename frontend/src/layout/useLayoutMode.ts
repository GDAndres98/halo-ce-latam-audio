// The current layout mode (layoutMode.ts), shared by the whole Studio, and whether the main pointer is a finger.
//
// One value for the page: it is also written to <html data-layout="…"> so the stylesheets and the scripts
// always agree on the layout (no media query can disagree with the script at a breakpoint). Turning a phone
// or resizing a window only changes this value and the attribute: no component is created again, so the
// open line, the drafts, the players and the lists stay as they are.
//
// The sizes are read through media queries, not window.innerWidth: on a phone innerWidth follows the layout
// viewport, which briefly grows when the content is wider than the screen (for example while the desktop
// panels are still laid out after turning the phone). Media queries use the screen's own width.

import { readonly, ref } from "vue";
import { DESKTOP_MIN_WIDTH, TABLET_MIN_HEIGHT, TABLET_MIN_WIDTH, type LayoutMode } from "./layoutMode";

const mode = ref<LayoutMode>("desktop");
const coarse = ref(false);

if (typeof window !== "undefined" && window.matchMedia) {
  const desktop = window.matchMedia(`(min-width: ${DESKTOP_MIN_WIDTH}px)`);
  const tablet = window.matchMedia(`(min-width: ${TABLET_MIN_WIDTH}px) and (min-height: ${TABLET_MIN_HEIGHT}px)`);
  const pointer = window.matchMedia("(pointer: coarse)");
  // The same rules as layoutModeFor(), evaluated by the browser.
  const measure = () => {
    mode.value = desktop.matches ? "desktop" : tablet.matches ? "tablet" : "phone";
    document.documentElement.dataset.layout = mode.value;
    coarse.value = pointer.matches;
  };
  measure();
  for (const query of [desktop, tablet, pointer]) query.addEventListener?.("change", measure);
}

export const layoutMode = readonly(mode);
/** The main pointer is a finger (phone, tablet): bigger handles, the pan/select choice on zoomed waveforms. */
export const coarsePointer = readonly(coarse);
