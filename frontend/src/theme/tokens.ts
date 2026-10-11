// Theme tokens: the one place where the colours, fonts and shapes of the Studio are defined.
//
// The look reinterprets the menu system of the original Xbox Halo: Combat Evolved (2001): deep space-navy
// backgrounds, translucent navy panels outlined by a bright menu-blue frame with soft rounded corners,
// wide uppercase blue headings over a thin full-width rule, and selection shown as a framed outline with the
// selected words turning near-white. See docs/ui-design-system.md for the references and the reasoning.
// The values are original; no Halo artwork, logos or fonts are used (the fonts are OFL, see styles/fonts.css).
//
// Status is never shown by colour alone: every status badge also carries an icon or glyph and a word.
// tokens.test.ts checks that every text colour meets WCAG AA contrast on the surfaces it is used on, so a
// change here cannot make text hard to read without a failing test.

export const COLOURS = {
  // Surfaces, darkest first. Panels are drawn slightly translucent over the background (see panelGlass);
  // these are their opaque equivalents, used for contrast checks and for controls.
  space: "#01040c", // the deepest background, behind the starfield
  background: "#03091a",
  panel: "#061230",
  panelRaised: "#0b1d45",
  well: "#020818", // recessed areas: waveforms, logs, input fields

  // The menu frame: the bright blue outline of the original panels, and its dimmer resting state.
  frame: "#2f8cff",
  frameDim: "#1d4e8f",
  border: "#17345f", // hairlines inside panels
  borderStrong: "#2a5590",

  // Text.
  text: "#dce9f8", // body text and selected menu items (the original's near-white)
  textMuted: "#8fa9cc",
  menu: "#4da3ff", // headings, labels and unselected menu items: the original's menu blue

  // Accents.
  cyan: "#7fe3ff", // keyboard focus and the playhead: brighter and greener than the frame, never confused with it
  green: "#8ecb5b", // muted armour green: approval and "go" actions
  greenText: "#03091a", // text on green buttons

  // Status (always paired with a word and a glyph).
  approved: "#97d468",
  draft: "#f2c25c",
  rework: "#ff8f80",
  unmatched: "#8fa9cc",
  radio: "#c9a8f5",

  // Feedback banners.
  danger: "#ff8f80",
  success: "#97d468",
} as const;

export const SHAPE = {
  radius: "10px", // panels: the original's soft, rounded menu frames
  radiusControl: "8px", // buttons and fields
  borderWidth: "2px",
  focusWidth: "2px",
  gap: "0.75rem",
} as const;

export const FONTS = {
  // Michroma: a wide, geometric display face in the spirit of the original menu titles (OFL).
  display: '"Michroma", "Saira Variable", system-ui, sans-serif',
  // Saira: squared, technical and very readable at small sizes; used for everything else (OFL).
  ui: '"Saira Variable", "Segoe UI", system-ui, sans-serif',
  mono: '"Cascadia Mono", Consolas, ui-monospace, monospace',
} as const;

/** Translucent panel fill: the panel colour over the background at this opacity. */
export const PANEL_ALPHA = 0.9;

function rgba(hex: string, alpha: number): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** The CSS custom properties the stylesheets use. Set on the document root at start-up (see main.ts). */
export function cssVariables(): Record<string, string> {
  return {
    "--space": COLOURS.space,
    "--bg": COLOURS.background,
    "--panel": COLOURS.panel,
    "--panel-glass": rgba(COLOURS.panel, PANEL_ALPHA),
    "--panel-raised": COLOURS.panelRaised,
    "--well": COLOURS.well,
    "--frame": COLOURS.frame,
    "--frame-dim": COLOURS.frameDim,
    "--frame-glow": rgba(COLOURS.frame, 0.45),
    "--line": COLOURS.border,
    "--line-strong": COLOURS.borderStrong,
    "--text": COLOURS.text,
    "--muted": COLOURS.textMuted,
    "--menu": COLOURS.menu,
    "--accent": COLOURS.menu,
    "--focus": COLOURS.cyan,
    "--green": COLOURS.green,
    "--green-text": COLOURS.greenText,
    "--ok": COLOURS.approved,
    "--warn": COLOURS.draft,
    "--bad": COLOURS.rework,
    "--unmatched": COLOURS.unmatched,
    "--radio": COLOURS.radio,
    "--radius": SHAPE.radius,
    "--radius-control": SHAPE.radiusControl,
    "--frame-width": SHAPE.borderWidth,
    "--focus-width": SHAPE.focusWidth,
    "--font-display": FONTS.display,
    "--font-ui": FONTS.ui,
    "--font-mono": FONTS.mono,
  };
}

export function applyTheme(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(cssVariables())) root.style.setProperty(name, value);
}
