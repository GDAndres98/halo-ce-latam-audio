import { describe, expect, it } from "vitest";
import { COLOURS, PANEL_ALPHA, cssVariables } from "./tokens";

// WCAG 2.x relative luminance and contrast ratio.
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The colour a translucent panel actually shows over the brightest part of the background. */
function over(top: string, alpha: number, bottom: string): string {
  const mix = [1, 3, 5].map((i) => {
    const t = parseInt(top.slice(i, i + 2), 16);
    const b = parseInt(bottom.slice(i, i + 2), 16);
    return Math.round(t * alpha + b * (1 - alpha)).toString(16).padStart(2, "0");
  });
  return `#${mix.join("")}`;
}

describe("theme contrast (WCAG AA: 4.5:1 for text, 3:1 for focus and frames)", () => {
  type Colour = keyof typeof COLOURS;
  const SURFACES: Colour[] = ["background", "panel", "panelRaised", "well"];
  const TEXTS: Colour[] = ["text", "textMuted", "menu", "approved", "draft", "rework", "radio", "cyan"];
  const pairs: [Colour, Colour][] = SURFACES.flatMap((s) => TEXTS.map((t) => [s, t] as [Colour, Colour]));

  it.each(pairs)("%s surface with %s text", (surface, text) => {
    expect(contrast(COLOURS[surface], COLOURS[text])).toBeGreaterThanOrEqual(4.5);
  });

  it("text on a translucent panel over the planet glow stays readable", () => {
    // The brightest spot of the background (the planet's rim light) is about the frame-dim colour.
    const glass = over(COLOURS.panel, PANEL_ALPHA, COLOURS.frameDim);
    for (const text of ["text", "textMuted", "menu"] as const) expect(contrast(glass, COLOURS[text])).toBeGreaterThanOrEqual(4.5);
  });

  it("button text on the green accent", () => {
    expect(contrast(COLOURS.green, COLOURS.greenText)).toBeGreaterThanOrEqual(4.5);
  });

  it("the focus ring and the menu frame are visible against every surface", () => {
    for (const surface of SURFACES) {
      expect(contrast(COLOURS[surface], COLOURS.cyan)).toBeGreaterThanOrEqual(3);
      expect(contrast(COLOURS[surface], COLOURS.frame)).toBeGreaterThanOrEqual(3);
    }
  });

  it("hairlines are visible against the panel", () => {
    expect(contrast(COLOURS.panel, COLOURS.border)).toBeGreaterThanOrEqual(1.3);
    expect(contrast(COLOURS.panel, COLOURS.borderStrong)).toBeGreaterThanOrEqual(2);
  });

  it("exposes every token the stylesheets use", () => {
    const vars = cssVariables();
    for (const name of ["--frame", "--menu", "--panel-glass", "--font-display", "--ok", "--focus"]) expect(vars[name]).toBeTruthy();
  });
});
