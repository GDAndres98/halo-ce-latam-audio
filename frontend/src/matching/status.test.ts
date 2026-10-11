import { describe, expect, it } from "vitest";
import { markFor } from "./status";

describe("status marks", () => {
  it("says every state in words as well as with a glyph", () => {
    expect(markFor("approved")).toMatchObject({ glyph: "✓", word: "approved" });
    expect(markFor("draft")).toMatchObject({ glyph: "•", word: "draft" });
    expect(markFor("needs_rework")).toMatchObject({ glyph: "!", word: "needs rework" });
    expect(markFor("unreviewed")).toMatchObject({ word: "unmatched" });
  });

  it("gives different states different glyphs", () => {
    const glyphs = ["approved", "draft", "needs_rework", "no_equivalent", "deferred", "unreviewed"].map((s) => markFor(s).glyph);
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });
});
