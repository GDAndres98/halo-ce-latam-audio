import { describe, expect, it } from "vitest";
import { layoutModeFor, paneFrom } from "./layoutMode";

describe("layoutModeFor", () => {
  it("keeps the three panels from 1000 px", () => {
    expect(layoutModeFor(1000, 700)).toBe("desktop");
    expect(layoutModeFor(1920, 1080)).toBe("desktop");
    expect(layoutModeFor(1024, 768)).toBe("desktop"); // a tablet held sideways
  });

  it("uses two panes on tablets in portrait", () => {
    expect(layoutModeFor(768, 1024)).toBe("tablet");
    expect(layoutModeFor(820, 1180)).toBe("tablet");
    expect(layoutModeFor(999, 600)).toBe("tablet");
  });

  it("uses one pane on phones, upright or sideways", () => {
    expect(layoutModeFor(360, 740)).toBe("phone");
    expect(layoutModeFor(390, 844)).toBe("phone");
    expect(layoutModeFor(430, 932)).toBe("phone");
    expect(layoutModeFor(844, 390)).toBe("phone");
    expect(layoutModeFor(932, 430)).toBe("phone");
  });
});

describe("paneFrom", () => {
  it("accepts the three pane names only", () => {
    expect(paneFrom("ce", "mcc")).toBe("ce");
    expect(paneFrom("match", "mcc")).toBe("match");
    expect(paneFrom("other", "mcc")).toBe("mcc");
    expect(paneFrom(undefined, "match")).toBe("match");
  });
});
