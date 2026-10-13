import { describe, expect, it } from "vitest";
import type { AudioEdit } from "../api/types";
import {
  EditHistory,
  addCut,
  addSilence,
  editedSeconds,
  fadeSpans,
  keepSpan,
  moveSilence,
  removeCut,
  removeSilence,
  replaceWithSilence,
  resetEdits,
  setFade,
  setKeep,
  setSilenceLength,
  ECHO_PRESETS,
  RADIO_PRESETS,
  radioProblem,
  setEchoPreset,
  setEchoValue,
  setInterference,
  setRegionValue,
  setRadioPreset,
  setRadioValue,
} from "./editRecipe";

const DURATION = 4;

function edit(overrides: Partial<AudioEdit> = {}): AudioEdit {
  return {
    trim_start_s: 0,
    trim_end_s: 0,
    gap_s: 0,
    cuts: [],
    silences: [],
    fade_in_ms: 0,
    fade_out_ms: 0,
    crossfade_ms: 20,
    ...overrides,
  };
}

describe("keeping part of the recording", () => {
  it("sets trims from a kept span and reports the duration", () => {
    const next = setKeep(edit(), { start: 0.5, end: 3 }, DURATION);
    expect(next.trim_start_s).toBe(0.5);
    expect(next.trim_end_s).toBe(1);
    expect(editedSeconds(next, DURATION)).toBe(2.5);
    expect(keepSpan(next, DURATION)).toEqual({ start: 0.5, end: 3 });
  });

  it("drops cuts that a new trim leaves outside the kept part", () => {
    const cut = addCut(edit(), { start: 0.2, end: 0.4 }, DURATION);
    const next = setKeep(cut, { start: 1, end: 3 }, DURATION);
    expect(next.cuts).toEqual([]);
  });

  it("refuses a kept span shorter than the minimum", () => {
    expect(() => setKeep(edit(), { start: 1, end: 1.01 }, DURATION)).toThrow(/at least/);
  });
});

describe("cutting", () => {
  it("removes an interior section", () => {
    const next = addCut(edit(), { start: 1, end: 1.5 }, DURATION);
    expect(next.cuts).toEqual([{ start_s: 1, end_s: 1.5 }]);
    expect(editedSeconds(next, DURATION)).toBe(3.5);
  });

  it("merges overlapping cuts into one", () => {
    const first = addCut(edit(), { start: 1, end: 1.5 }, DURATION);
    const second = addCut(first, { start: 1.4, end: 2 }, DURATION);
    expect(second.cuts).toEqual([{ start_s: 1, end_s: 2 }]);
  });

  it("keeps several separate cuts", () => {
    const first = addCut(edit(), { start: 0.5, end: 0.8 }, DURATION);
    const second = addCut(first, { start: 2, end: 2.5 }, DURATION);
    expect(second.cuts).toHaveLength(2);
    expect(removeCut(second, 0).cuts).toEqual([{ start_s: 2, end_s: 2.5 }]);
  });

  it("clips a cut to the kept part", () => {
    const trimmed = setKeep(edit(), { start: 1, end: 3 }, DURATION);
    const next = addCut(trimmed, { start: 0.2, end: 1.5 }, DURATION);
    expect(next.cuts).toEqual([{ start_s: 1, end_s: 1.5 }]);
  });

  it("refuses a cut that would remove the whole recording", () => {
    expect(() => addCut(edit(), { start: 0, end: DURATION }, DURATION)).toThrow(/whole recording/);
  });

  it("refuses an empty cut", () => {
    expect(() => addCut(edit(), { start: 1, end: 1.01 }, DURATION)).toThrow(/at least/);
  });
});

describe("fades", () => {
  it("sets a fade within the limit and places it on the kept part", () => {
    const next = setFade(setKeep(edit(), { start: 1, end: 3 }, DURATION), "in", 200);
    expect(next.fade_in_ms).toBe(200);
    expect(fadeSpans(next, DURATION).fadeIn).toEqual({ start: 1, end: 1.2 });
    expect(fadeSpans(next, DURATION).fadeOut).toBeNull();
  });

  it("keeps a fade inside the limit", () => {
    expect(setFade(edit(), "out", 99999).fade_out_ms).toBe(500);
    expect(setFade(edit(), "out", -5).fade_out_ms).toBe(0);
  });
});

describe("reset and undo", () => {
  it("resets the audio edits and keeps the gap", () => {
    const changed = setFade(addCut(setKeep(edit({ gap_s: 0.3 }), { start: 0.5, end: 3.5 }, DURATION), { start: 1, end: 1.5 }, DURATION), "in", 50);
    const reset = resetEdits(changed);
    expect(reset).toMatchObject({ trim_start_s: 0, trim_end_s: 0, cuts: [], silences: [], fade_in_ms: 0, gap_s: 0.3 });
  });

  it("undoes changes one at a time, back to the start", () => {
    const history = new EditHistory();
    const original = edit();
    history.push(original);
    const cut = addCut(original, { start: 1, end: 1.5 }, DURATION);
    history.push(cut);
    const trimmed = setKeep(cut, { start: 0.5, end: 3.5 }, DURATION);
    expect(history.undo()).toEqual(cut);
    expect(history.undo()).toEqual(original);
    expect(history.undo()).toBeNull();
    expect(history.canUndo).toBe(false);
    expect(trimmed.cuts).toEqual([{ start_s: 1, end_s: 1.5 }]);
  });

  it("saves a copy, so later edits cannot change the history", () => {
    const history = new EditHistory();
    const before = edit();
    history.push(before);
    before.trim_start_s = 9;
    expect(history.undo()?.trim_start_s).toBe(0);
  });
});

describe("inserting silence", () => {
  it("inserts silences in milliseconds, kept in order, and adds them to the duration", () => {
    let next = addSilence(edit(), 2, 300, DURATION);
    next = addSilence(next, 1, 250, DURATION);
    expect(next.silences).toEqual([{ at_s: 1, dur_s: 0.25 }, { at_s: 2, dur_s: 0.3 }]);
    expect(editedSeconds(next, DURATION)).toBe(4.55);
  });

  it("lengthens a silence inserted again at the same position, up to 5 s", () => {
    let next = addSilence(edit(), 1, 300, DURATION);
    next = addSilence(next, 1, 200, DURATION);
    expect(next.silences).toEqual([{ at_s: 1, dur_s: 0.5 }]);
    next = addSilence(next, 1, 5000, DURATION);
    expect(next.silences[0].dur_s).toBe(5);
  });

  it("refuses a bad length, a trimmed position and a position inside a cut", () => {
    expect(() => addSilence(edit(), 1, 5, DURATION)).toThrow(/10–5000 ms/);
    expect(() => addSilence(edit(), 1, 6000, DURATION)).toThrow(/10–5000 ms/);
    expect(() => addSilence(edit({ trim_start_s: 1 }), 0.5, 300, DURATION)).toThrow(/trimmed/);
    expect(() => addSilence(edit({ cuts: [{ start_s: 1, end_s: 2 }] }), 1.5, 300, DURATION)).toThrow(/inside a cut/);
    // At a cut's edge is allowed (the renderer places it at the join).
    expect(addSilence(edit({ cuts: [{ start_s: 1, end_s: 2 }] }), 1, 300, DURATION).silences).toHaveLength(1);
  });

  it("edits, moves and removes an existing silence", () => {
    const base = addSilence(addSilence(edit(), 1, 300, DURATION), 2, 300, DURATION);
    expect(setSilenceLength(base, 1, 800).silences[1]).toEqual({ at_s: 2, dur_s: 0.8 });
    expect(moveSilence(base, 1, 0.5, DURATION).silences).toEqual([{ at_s: 0.5, dur_s: 0.3 }, { at_s: 1, dur_s: 0.3 }]);
    expect(() => moveSilence(base, 1, 1, DURATION)).toThrow(/already/);
    expect(removeSilence(base, 0).silences).toEqual([{ at_s: 2, dur_s: 0.3 }]);
    expect(resetEdits(base).silences).toEqual([]);
  });

  it("drops a silence that a new cut swallows, and replaces a selection with an exact pause", () => {
    const withSilence = addSilence(edit(), 1.5, 300, DURATION);
    expect(addCut(withSilence, { start: 1, end: 2 }, DURATION).silences).toEqual([]);
    const pause = replaceWithSilence(edit(), { start: 1, end: 2 }, 400, DURATION);
    expect(pause.cuts).toEqual([{ start_s: 1, end_s: 2 }]);
    expect(pause.silences).toEqual([{ at_s: 1, dur_s: 0.4 }]);
    expect(editedSeconds(pause, DURATION)).toBe(3.4);
  });
});

describe("radio filter", () => {
  it("turns a preset on and off", () => {
    const on = setRadioPreset(edit(), "spain");
    expect(on.radio).toEqual({ ...RADIO_PRESETS.spain, preset: "spain" });
    expect(setRadioPreset(on, null).radio).toBeNull();
    expect(setRadioPreset(on, "english").radio?.noise_dbfs).toBe(-50);
  });

  it("becomes custom when a value changes, and keeps the values when Custom is chosen", () => {
    const custom = setRadioValue(setRadioPreset(edit(), "spain"), "low_hz", 600);
    expect(custom.radio).toMatchObject({ preset: "custom", low_hz: 600, high_hz: 3300 });
    expect(setRadioPreset(custom, "custom").radio?.low_hz).toBe(600);
  });

  it("refuses what the server would refuse", () => {
    const on = setRadioPreset(edit(), "spain");
    expect(() => setRadioValue(on, "low_hz", 50)).toThrow();
    expect(() => setRadioValue(on, "high_hz", 1000)).toThrow(/narrow/);
    expect(() => setRadioValue(on, "noise_dbfs", -10)).toThrow();
    expect(() => setRadioValue(edit(), "low_hz", 600)).toThrow(/on first/);
    expect(radioProblem({ ...RADIO_PRESETS.english, preset: "english" })).toBeNull();
  });

  it("is kept by Reset edits (it has its own Off)", () => {
    const on = setRadioPreset(edit({ trim_start_s: 0.2 }), "spain");
    expect(resetEdits(on).radio?.preset).toBe("spain");
  });
});

describe("echo", () => {
  it("turns a preset on and off, and becomes custom when a value changes", () => {
    const on = setEchoPreset(edit(), "spain");
    expect(on.echo).toEqual({ ...ECHO_PRESETS.spain, preset: "spain" });
    expect(setEchoPreset(on, null).echo).toBeNull();
    const custom = setEchoValue(on, "delay_ms", 200);
    expect(custom.echo).toMatchObject({ preset: "custom", delay_ms: 200, echo_db: ECHO_PRESETS.spain.echo_db });
    expect(setEchoValue(custom, "feedback_db", null).echo?.feedback_db).toBeNull();
  });

  it("refuses what the server would refuse", () => {
    const on = setEchoPreset(edit(), "english");
    expect(() => setEchoValue(on, "delay_ms", 10)).toThrow();
    expect(() => setEchoValue(on, "diffusion", 2)).toThrow();
    expect(() => setEchoValue(edit(), "delay_ms", 100)).toThrow(/on first/);
  });

  it("the intercom radio presets carry their presence frequency", () => {
    expect(setRadioPreset(edit(), "spain_eco").radio).toMatchObject({ presence_hz: 2500, clicks: false });
  });
});

describe("transmission interference (Victor 933)", () => {
  const regions = [
    { label: "Aquí", kind: "partial" as const, start_s: 0.12, end_s: 0.4, intensity_db: 0 },
    { label: "33", kind: "masked" as const, start_s: 1.93, end_s: 2.51, intensity_db: 0 },
  ];
  it("adds, edits and removes regions", () => {
    const on = setInterference(edit(), regions);
    expect(on.interference?.regions).toHaveLength(2);
    expect(setRegionValue(on, 1, "end_s", 2.6, 29).interference?.regions[1].end_s).toBe(2.6);
    expect(setRegionValue(on, 0, "kind", "masked", 29).interference?.regions[0].kind).toBe("masked");
    expect(setInterference(on, null).interference).toBeNull();
  });
  it("refuses reversed, overlapping, too long or too strong regions", () => {
    const on = setInterference(edit(), regions);
    expect(() => setRegionValue(on, 0, "end_s", 0.1, 29)).toThrow(/before it ends/);
    expect(() => setRegionValue(on, 0, "end_s", 2.0, 29)).toThrow(/overlap/);
    expect(() => setRegionValue(on, 1, "end_s", 40, 29)).toThrow(/after the recording/);
    expect(() => setRegionValue(on, 1, "intensity_db", 20, 29)).toThrow(/intensity/);
  });
});
