import { describe, expect, it } from "vitest";
import { foldKeepingLength, highlightSegments } from "./text";

describe("highlighting search terms", () => {
  it("ignores case and accents, and keeps the original text", () => {
    const segments = highlightSegments("¡Qué pasó, JEFE!", ["que", "jefe"]);
    expect(segments.filter((s) => s.hit).map((s) => s.text)).toEqual(["Qué", "JEFE"]);
    expect(segments.map((s) => s.text).join("")).toBe("¡Qué pasó, JEFE!");
  });

  it("keeps the length of the folded text, so ranges line up with the original", () => {
    expect(foldKeepingLength("Ñandú ßtraße")).toHaveLength("Ñandú ßtraße".length);
  });

  it("returns one unhighlighted run when nothing matches", () => {
    expect(highlightSegments("Nave de abordaje", ["nothing"])).toEqual([{ text: "Nave de abordaje", hit: false }]);
  });
});
