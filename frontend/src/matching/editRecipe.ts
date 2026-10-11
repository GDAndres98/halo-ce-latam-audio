// Editing rules for an audio recipe, as the waveform editor applies them. Pure functions: the screens call
// these and show the result; nothing here plays audio or touches the files.
//
// The recipe is non-destructive. It lists what to keep, cut, fade and silence on the ORIGINAL recording's
// timeline (seconds). The original WAV is never changed. The server renders the recipe the same way for
// previews and for the build (scripts/common/audio_edit.py), so these rules only decide what the recipe
// contains; the server decides what it sounds like.

import type { AudioEdit } from "../api/types";

/** A span of the original recording, in seconds. */
export interface Span {
  start: number;
  end: number;
}

/** Shortest span the editor will create. Shorter selections are almost always mis-drags. */
export const MIN_SPAN_S = 0.05;
// Same limit as the server (scripts/common/audio_edit.py LIMITS); a longer fade would be refused there.
export const MAX_FADE_MS = 500;
// One inserted silence, as the server accepts it (audio_edit.SILENCE_S = 0.01..5 s).
export const MIN_SILENCE_MS = 10;
export const MAX_SILENCE_MS = 5000;

const round3 = (value: number) => Math.round(value * 1000) / 1000;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** The part of the original that is kept: from the start trim to the end trim. */
export function keepSpan(edit: AudioEdit, duration: number): Span {
  return { start: round3(edit.trim_start_s), end: round3(duration - edit.trim_end_s) };
}

/** Sets the kept part from a span (a trim drag, or "keep only the selection"). Cuts and silences that now
 * fall outside the kept part are dropped, as the classic editor did. */
export function setKeep(edit: AudioEdit, span: Span, duration: number): AudioEdit {
  const start = clamp(round3(span.start), 0, duration);
  const end = clamp(round3(span.end), 0, duration);
  if (end - start < MIN_SPAN_S) throw new Error(`keep at least ${MIN_SPAN_S} s`);
  const next: AudioEdit = { ...edit, trim_start_s: start, trim_end_s: round3(duration - end) };
  next.cuts = edit.cuts.filter((c) => c.start_s >= start && c.end_s <= end);
  next.silences = edit.silences.filter((s) => s.at_s >= start && s.at_s <= end);
  return next;
}

/** Removes a span from the kept part. Overlapping cuts merge into one. A cut outside the kept part is
 * clipped to it; a cut that would leave nothing is refused. */
export function addCut(edit: AudioEdit, span: Span, duration: number): AudioEdit {
  const keep = keepSpan(edit, duration);
  const start = clamp(round3(span.start), keep.start, keep.end);
  const end = clamp(round3(span.end), keep.start, keep.end);
  if (end - start < MIN_SPAN_S) throw new Error(`a cut must be at least ${MIN_SPAN_S} s`);
  const merged: { start_s: number; end_s: number }[] = [];
  const all = [...edit.cuts, { start_s: start, end_s: end }].sort((a, b) => a.start_s - b.start_s);
  for (const cut of all) {
    const last = merged[merged.length - 1];
    if (last && cut.start_s <= last.end_s) last.end_s = round3(Math.max(last.end_s, cut.end_s));
    else merged.push({ start_s: cut.start_s, end_s: cut.end_s });
  }
  if (keep.end - keep.start - merged.reduce((sum, c) => sum + (c.end_s - c.start_s), 0) < MIN_SPAN_S) {
    throw new Error("the cuts would remove the whole recording");
  }
  // Silences strictly inside a cut have nothing left to sit in (the classic editor dropped them too).
  const silences = edit.silences.filter((s) => !merged.some((c) => c.start_s < s.at_s && s.at_s < c.end_s));
  return { ...edit, cuts: merged, silences };
}

export function removeCut(edit: AudioEdit, index: number): AudioEdit {
  return { ...edit, cuts: edit.cuts.filter((_, i) => i !== index) };
}

/** A silence length from the editor's millisecond field, checked against the server's limits. */
function silenceSeconds(ms: number): number {
  if (!Number.isFinite(ms) || ms < MIN_SILENCE_MS || ms > MAX_SILENCE_MS) {
    throw new Error(`a silence must be ${MIN_SILENCE_MS}–${MAX_SILENCE_MS} ms long`);
  }
  return round3(ms / 1000);
}

/** Why a silence cannot sit at `at` (a source time), or null. Same rules as audio_edit.problems. */
function silencePositionProblem(edit: AudioEdit, at: number, duration: number): string | null {
  const keep = keepSpan(edit, duration);
  if (at < keep.start || at > keep.end) return "the position is in a trimmed part";
  if (edit.cuts.some((c) => c.start_s < at && at < c.end_s)) return "the position is inside a cut";
  return null;
}

const sortSilences = (silences: AudioEdit["silences"]) => [...silences].sort((a, b) => a.at_s - b.at_s);

/**
 * Inserts `ms` of silence at a time of the original recording (the playhead, or the start of the selection).
 * A second silence at the same position lengthens the first one, up to the limit, as the classic editor did:
 * the server refuses two silences at one position.
 */
export function addSilence(edit: AudioEdit, at: number, ms: number, duration: number): AudioEdit {
  const position = round3(at);
  const length = silenceSeconds(ms);
  const problem = silencePositionProblem(edit, position, duration);
  if (problem) throw new Error(problem);
  const same = edit.silences.find((s) => s.at_s === position);
  const silences = same
    ? edit.silences.map((s) => (s === same ? { ...s, dur_s: round3(Math.min(MAX_SILENCE_MS / 1000, s.dur_s + length)) } : s))
    : [...edit.silences, { at_s: position, dur_s: length }];
  return { ...edit, silences: sortSilences(silences) };
}

/** Changes the length of an inserted silence (the field next to it in the list). */
export function setSilenceLength(edit: AudioEdit, index: number, ms: number): AudioEdit {
  const length = silenceSeconds(ms);
  return { ...edit, silences: edit.silences.map((s, i) => (i === index ? { ...s, dur_s: length } : s)) };
}

/** Moves an inserted silence to another time of the original recording. */
export function moveSilence(edit: AudioEdit, index: number, at: number, duration: number): AudioEdit {
  const position = round3(at);
  const problem = silencePositionProblem(edit, position, duration);
  if (problem) throw new Error(problem);
  if (edit.silences.some((s, i) => i !== index && s.at_s === position)) throw new Error("another silence is already there");
  return { ...edit, silences: sortSilences(edit.silences.map((s, i) => (i === index ? { ...s, at_s: position } : s))) };
}

export function removeSilence(edit: AudioEdit, index: number): AudioEdit {
  return { ...edit, silences: edit.silences.filter((_, i) => i !== index) };
}

/** Removes the selection and puts exactly `ms` of silence in its place: sets the length of a pause. */
export function replaceWithSilence(edit: AudioEdit, span: Span, ms: number, duration: number): AudioEdit {
  silenceSeconds(ms); // refuse a bad length before changing anything
  const cut = addCut(edit, span, duration);
  const keep = keepSpan(edit, duration);
  const start = clamp(round3(span.start), keep.start, keep.end);
  // The silence goes where the merged cut that holds the selection starts.
  const at = cut.cuts.find((c) => c.start_s <= start && start <= c.end_s)?.start_s ?? start;
  return addSilence({ ...cut, silences: cut.silences.filter((s) => s.at_s !== at) }, at, ms, duration);
}

export function setFade(edit: AudioEdit, which: "in" | "out", ms: number): AudioEdit {
  const value = clamp(Math.round(ms), 0, MAX_FADE_MS);
  return which === "in" ? { ...edit, fade_in_ms: value } : { ...edit, fade_out_ms: value };
}

/** Back to an unedited recording. The gap and loudness settings are kept: they are not edits to the audio
 * itself. */
export function resetEdits(edit: AudioEdit): AudioEdit {
  return {
    ...edit,
    trim_start_s: 0,
    trim_end_s: 0,
    cuts: [],
    silences: [],
    fade_in_ms: 0,
    fade_out_ms: 0,
  };
}

/** The length the recording will have after the trims, the cuts and the inserted silences (before the
 * global gain and encoding). Crossfades make the render a few milliseconds shorter per cut. */
export function editedSeconds(edit: AudioEdit, duration: number): number {
  const keep = keepSpan(edit, duration);
  const cut = edit.cuts.reduce((sum, c) => sum + Math.max(0, c.end_s - c.start_s), 0);
  const silence = edit.silences.reduce((sum, s) => sum + s.dur_s, 0);
  return Math.max(0, round3(keep.end - keep.start - cut + silence));
}

/** Where the fades sit on the original timeline, for drawing them. */
export function fadeSpans(edit: AudioEdit, duration: number): { fadeIn: Span | null; fadeOut: Span | null } {
  const keep = keepSpan(edit, duration);
  return {
    fadeIn: edit.fade_in_ms > 0 ? { start: keep.start, end: round3(Math.min(keep.end, keep.start + edit.fade_in_ms / 1000)) } : null,
    fadeOut: edit.fade_out_ms > 0 ? { start: round3(Math.max(keep.start, keep.end - edit.fade_out_ms / 1000)), end: keep.end } : null,
  };
}

/**
 * Undo for the editor. Each change first saves the recipe before it. Undo returns the previous recipe.
 * Reset is itself a change, so it can be undone too.
 */
export class EditHistory {
  private past: AudioEdit[] = [];

  push(before: AudioEdit): void {
    this.past.push(JSON.parse(JSON.stringify(before)) as AudioEdit);
    if (this.past.length > 100) this.past.shift();
  }

  undo(): AudioEdit | null {
    return this.past.pop() ?? null;
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  clear(): void {
    this.past = [];
  }
}
