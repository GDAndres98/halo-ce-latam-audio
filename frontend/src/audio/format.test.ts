import { describe, expect, it } from "vitest";
import { formatPosition, formatSeconds } from "./format";

describe("time formatting", () => {
  it("shows durations with three decimals", () => {
    expect(formatSeconds(3.5)).toBe("3.500 s");
    expect(formatSeconds(null)).toBe("—");
  });

  it("shows positions as minutes, seconds and milliseconds", () => {
    expect(formatPosition(0)).toBe("0:00.000");
    expect(formatPosition(1.2346)).toBe("0:01.235");
    expect(formatPosition(65.5)).toBe("1:05.500");
    expect(formatPosition(-1)).toBe("0:00.000");
  });
});
