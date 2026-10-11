// How a decision state is shown: a glyph and a word, never colour alone. Used by the MCC list.

// Status symbols: the letter says what it is, the glyph says the state, and the title says it in words.
// Colour is an extra, never the only signal.
export interface StatusMark {
  glyph: string;
  word: string;
  tone: "ok" | "warn" | "bad" | "muted";
}
export function markFor(state: string): StatusMark {
  switch (state) {
    case "approved":
    case "matched":
      return { glyph: "✓", word: state, tone: "ok" };
    case "draft":
      return { glyph: "•", word: "draft", tone: "warn" };
    case "needs_rework":
      return { glyph: "!", word: "needs rework", tone: "bad" };
    case "no_equivalent":
      return { glyph: "⊘", word: "no equivalent", tone: "muted" };
    case "deferred":
      return { glyph: "…", word: "deferred", tone: "muted" };
    default:
      return { glyph: "–", word: "unmatched", tone: "muted" };
  }
}
