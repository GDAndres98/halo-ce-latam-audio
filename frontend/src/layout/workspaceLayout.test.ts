import { describe, expect, it } from "vitest";
import {
  DEFAULT_WIDTHS,
  HANDLE_PX,
  MIN_CENTRE_PX,
  PANEL_LIMITS,
  fitWidths,
  nudge,
  readStoredWidths,
} from "./workspaceLayout";

describe("panel widths", () => {
  it("keeps the defaults on a comfortable window", () => {
    expect(fitWidths(DEFAULT_WIDTHS, 1440)).toEqual(DEFAULT_WIDTHS);
  });

  it("never lets a side panel leave its limits", () => {
    expect(fitWidths({ left: 10, right: 5000 }, 1440)).toEqual({
      left: PANEL_LIMITS.left.min,
      right: PANEL_LIMITS.right.max,
    });
  });

  it("keeps the centre panel at least at its minimum width", () => {
    const fitted = fitWidths({ left: 520, right: 620 }, 1000);
    expect(1000 - fitted.left - fitted.right - 2 * HANDLE_PX).toBeGreaterThanOrEqual(MIN_CENTRE_PX);
  });

  it("takes width from the wider side panel first when the window narrows", () => {
    const fitted = fitWidths({ left: 300, right: 400 }, 1000);
    expect(400 - fitted.right).toBeGreaterThan(300 - fitted.left);
    expect(fitted.left + fitted.right).toBeLessThanOrEqual(1000 - 2 * HANDLE_PX - MIN_CENTRE_PX);
  });

  it("reads only a valid stored layout", () => {
    expect(readStoredWidths(JSON.stringify({ left: 320, right: 340 }))).toEqual({ left: 320, right: 340 });
    expect(readStoredWidths("not json")).toBeNull();
    expect(readStoredWidths(JSON.stringify({ left: "wide", right: 1 }))).toBeNull();
    expect(readStoredWidths(null)).toBeNull();
  });

  it("moves a divider: the left one widens the left panel, the right one narrows the right panel", () => {
    expect(nudge(DEFAULT_WIDTHS, "left", 16)).toEqual({ left: 316, right: 360 });
    expect(nudge(DEFAULT_WIDTHS, "right", 16)).toEqual({ left: 300, right: 344 });
  });
});
