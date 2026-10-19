import { describe, expect, it } from "vitest";
import { effectiveVolume, parseStoredVolume, setVolume, toggleMute, volumeState } from "./volume";

describe("parseStoredVolume", () => {
  it("defaults to full volume, not muted", () => {
    expect(parseStoredVolume(null)).toEqual({ level: 1, muted: false });
    expect(parseStoredVolume("not json")).toEqual({ level: 1, muted: false });
    expect(parseStoredVolume('{"level":"loud"}')).toEqual({ level: 1, muted: false });
  });

  it("keeps a stored setting and clamps the level", () => {
    expect(parseStoredVolume('{"level":0.3,"muted":true}')).toEqual({ level: 0.3, muted: true });
    expect(parseStoredVolume('{"level":4}')).toEqual({ level: 1, muted: false });
    expect(parseStoredVolume('{"level":-1}')).toEqual({ level: 0, muted: false });
  });
});

describe("volume", () => {
  it("mutes and unmutes without losing the level", () => {
    setVolume(0.4);
    toggleMute();
    expect(effectiveVolume.value).toBe(0);
    toggleMute();
    expect(effectiveVolume.value).toBe(0.4);
  });

  it("moving the slider up unmutes; unmuting at 0 brings back a usable level", () => {
    toggleMute();
    setVolume(0.7);
    expect(volumeState.muted).toBe(false);
    setVolume(0);
    toggleMute();
    expect(effectiveVolume.value).toBe(0.5);
  });
});
