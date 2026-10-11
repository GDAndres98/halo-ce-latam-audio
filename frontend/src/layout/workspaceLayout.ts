// Widths of the three matching panels, in pixels. Pure functions: the drag handling lives in
// useWorkspaceLayout.ts, the arithmetic and the rules live here so they can be unit-tested.
//
// Rules: each side panel has its own minimum and maximum; the centre panel never goes below its minimum,
// so when the window is narrow the side panels give way first. The saved widths are checked on load:
// anything unexpected falls back to the defaults.

export interface PanelWidths {
  left: number;
  right: number;
}

export const DEFAULT_WIDTHS: PanelWidths = { left: 300, right: 360 };
export const HANDLE_PX = 8;
export const MIN_CENTRE_PX = 420;
export const PANEL_LIMITS: Record<keyof PanelWidths, { min: number; max: number }> = {
  left: { min: 240, max: 520 },
  right: { min: 260, max: 620 },
};
export const STORAGE_KEY = "studio.layout.workspace.v1";
/** Keyboard step for the dividers; Shift multiplies it. */
export const KEY_STEP_PX = 16;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/**
 * Returns widths that respect each panel's limits and leave the centre panel its minimum width in
 * `available` pixels (the whole workspace). If the centre would be too narrow, the wider side panel gives
 * up width first, down to its minimum.
 */
export function fitWidths(widths: PanelWidths, available: number): PanelWidths {
  let left = clamp(widths.left, PANEL_LIMITS.left.min, PANEL_LIMITS.left.max);
  let right = clamp(widths.right, PANEL_LIMITS.right.min, PANEL_LIMITS.right.max);
  const room = () => available - 2 * HANDLE_PX - MIN_CENTRE_PX;
  while (left + right > room()) {
    const canShrinkLeft = left > PANEL_LIMITS.left.min;
    const canShrinkRight = right > PANEL_LIMITS.right.min;
    if (!canShrinkLeft && !canShrinkRight) break; // the window is too narrow: the grid scrolls instead
    if (canShrinkLeft && (left >= right || !canShrinkRight)) left -= 1;
    else right -= 1;
  }
  return { left: Math.round(left), right: Math.round(right) };
}

/** Parses a saved layout. Returns null for anything that is not two finite numbers. */
export function readStoredWidths(raw: string | null): PanelWidths | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<PanelWidths>;
    if (typeof value.left !== "number" || typeof value.right !== "number") return null;
    if (!Number.isFinite(value.left) || !Number.isFinite(value.right)) return null;
    return { left: value.left, right: value.right };
  } catch {
    return null;
  }
}

/** The width a divider step produces. `side` is the panel the divider sits next to. */
export function nudge(widths: PanelWidths, side: keyof PanelWidths, deltaPx: number): PanelWidths {
  return side === "left"
    ? { ...widths, left: widths.left + deltaPx }
    : { ...widths, right: widths.right - deltaPx };
}
