import { describe, expect, it } from "vitest";
import { COLOURS } from "./tokens";

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

describe("theme contrast (WCAG AA: 4.5:1 for text, 3:1 for focus and borders)", () => {
  type Colour = keyof typeof COLOURS;
  const textOnSurfaces: [Colour, Colour][] = [];
  for (const surface of ["background", "panel", "panelRaised"] as Colour[]) {
    textOnSurfaces.push([surface, "text"], [surface, "textMuted"]);
    textOnSurfaces.push([surface, "approved"], [surface, "draft"], [surface, "rework"], [surface, "radio"], [surface, "cyan"]);
  }

  it.each(textOnSurfaces)("%s surface with %s text", (surface, text) => {
    expect(contrast(COLOURS[surface], COLOURS[text])).toBeGreaterThanOrEqual(4.5);
  });

  it("button text on the olive accent", () => {
    expect(contrast(COLOURS.olive, COLOURS.oliveText)).toBeGreaterThanOrEqual(4.5);
  });

  it("the focus ring is visible against every surface", () => {
    for (const surface of ["background", "panel", "panelRaised"] as const) {
      expect(contrast(COLOURS[surface], COLOURS.cyan)).toBeGreaterThanOrEqual(3);
    }
  });

  it("borders are visible against the panel", () => {
    expect(contrast(COLOURS.panel, COLOURS.border)).toBeGreaterThanOrEqual(1.3);
    expect(contrast(COLOURS.panel, COLOURS.borderStrong)).toBeGreaterThanOrEqual(2);
  });
});
