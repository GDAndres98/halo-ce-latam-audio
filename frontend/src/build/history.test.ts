import { describe, expect, it } from "vitest";
import { builtAtMs, builtAtParts, newestFirst } from "./history";

const b = (name: string, built_at: string | null) => ({ name, built_at });

describe("newestFirst", () => {
  it("orders by the real time, not by name or by text", () => {
    const list = [
      b("101212343", "2026-10-12T23:54:50"),
      b("a10", "2026-10-08T23:24:55"),
      b("all_mapped_both_20261015013840", "2026-10-15T01:52:22"),
      b("test_3", "2026-10-11T03:53:13"),
    ];
    expect(newestFirst(list).map((x) => x.name)).toEqual(["all_mapped_both_20261015013840", "101212343", "test_3", "a10"]);
  });

  it("compares times with offsets on the same instant", () => {
    // 10:00+02:00 is 08:00Z, earlier than 09:00Z.
    const list = [b("plus_two", "2026-10-10T10:00:00+02:00"), b("utc", "2026-10-10T09:00:00Z")];
    expect(newestFirst(list).map((x) => x.name)).toEqual(["utc", "plus_two"]);
  });

  it("breaks ties by name and puts missing or invalid times last", () => {
    const list = [b("z_none", null), b("tie_b", "2026-10-10T10:00:00"), b("bad", "yesterday"), b("tie_a", "2026-10-10T10:00:00"), b("a_none", "")];
    expect(newestFirst(list).map((x) => x.name)).toEqual(["tie_a", "tie_b", "a_none", "bad", "z_none"]);
  });

  it("does not change the list it is given", () => {
    const list = [b("old", "2026-01-01T00:00:00"), b("new", "2026-02-01T00:00:00")];
    newestFirst(list);
    expect(list[0].name).toBe("old");
  });
});

describe("built times", () => {
  it("reads local, offset and date-only times and refuses the rest", () => {
    expect(builtAtMs("2026-10-15T01:52:22")).toBe(new Date(2026, 9, 15, 1, 52, 22).getTime());
    expect(builtAtMs("2026-10-15T01:52:22Z")).toBe(Date.UTC(2026, 9, 15, 1, 52, 22));
    expect(builtAtMs("2026-10-15")).toBe(new Date(2026, 9, 15).getTime());
    for (const bad of [null, undefined, "", "yesterday", "15/10/2026", "2026-13-40T99:99:99"]) expect(builtAtMs(bad)).toBeNull();
  });

  it("formats a date and a time for the list", () => {
    expect(builtAtParts("2026-10-15T01:52:22")).toMatchObject({ date: "15 Oct 2026", time: "01:52" });
    expect(builtAtParts("nope")).toBeNull();
  });
});
