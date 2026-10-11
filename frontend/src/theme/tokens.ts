// Theme tokens: the one place where colours, spacing and radii of the Studio are defined.
//
// Inspired by the interfaces of Halo: Combat Evolved (2001): dark navy and charcoal surfaces, olive
// armour-green accents, and a restrained cyan for focus and holographic highlights. The values are
// original; no Halo artwork, fonts or logos are used.
//
// Status is never shown by colour alone: every status badge also carries its word ("approved",
// "draft", "needs rework"). tokens.test.ts checks that every text colour meets WCAG AA contrast on the
// surfaces it is used on, so a change here cannot make text hard to read without a failing test.

export const COLOURS = {
  // Surfaces, darkest first.
  background: "#0e1319",
  panel: "#18212b",
  panelRaised: "#202b37",
  border: "#34444f",
  borderStrong: "#50626f",

  // Text.
  text: "#e4eaee",
  textMuted: "#9fb0bb",

  // Accents.
  olive: "#9aac6a", // armour green: primary buttons, selection, emphasis
  oliveText: "#0e1319", // text on olive buttons
  cyan: "#6fd6e8", // holographic: focus rings, links, the active divider

  // Status (always paired with a word).
  approved: "#8fd19e",
  draft: "#e6bd66",
  rework: "#f19a8c",
  unmatched: "#9fb0bb",
  radio: "#c7a6f0",

  // Feedback banners.
  danger: "#f19a8c",
  success: "#8fd19e",
} as const;

export const SHAPE = {
  radius: "4px",
  borderWidth: "1px",
  focusWidth: "2px",
  gap: "0.75rem",
} as const;

export const FONTS = {
  ui: 'system-ui, "Segoe UI", Roboto, sans-serif',
  mono: '"Cascadia Mono", Consolas, ui-monospace, monospace',
} as const;

/** The CSS custom properties the stylesheet uses. Set on the document root at start-up (see main.ts). */
export function cssVariables(): Record<string, string> {
  return {
    "--bg": COLOURS.background,
    "--panel": COLOURS.panel,
    "--panel-raised": COLOURS.panelRaised,
    "--line": COLOURS.border,
    "--line-strong": COLOURS.borderStrong,
    "--text": COLOURS.text,
    "--muted": COLOURS.textMuted,
    "--accent": COLOURS.olive,
    "--accent-text": COLOURS.oliveText,
    "--focus": COLOURS.cyan,
    "--ok": COLOURS.approved,
    "--warn": COLOURS.draft,
    "--bad": COLOURS.rework,
    "--unmatched": COLOURS.unmatched,
    "--radio": COLOURS.radio,
    "--radius": SHAPE.radius,
    "--focus-width": SHAPE.focusWidth,
    "--font-ui": FONTS.ui,
    "--font-mono": FONTS.mono,
  };
}

export function applyTheme(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(cssVariables())) root.style.setProperty(name, value);
}
