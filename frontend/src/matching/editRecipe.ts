// Editing rules for an audio recipe, as the waveform editor applies them. Pure functions: the screens call
// these and show the result; nothing here plays audio or touches the files.
//
// The recipe is non-destructive. It lists what to keep, cut, fade and silence on the ORIGINAL recording's
// timeline (seconds). The original WAV is never changed. The server renders the recipe the same way for
// previews and for the build (scripts/common/audio_edit.py), so these rules only decide what the recipe
// contains; the server decides what it sounds like.

import type { AudioEdit, CurvePoint, EchoEffect, EchoPreset, InterferenceCurve, RadioFilter, RadioPreset } from "../api/types";

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

// ---- Radio filter (2026-10-13). Same presets and limits as the server (audio_edit.RADIO_PRESETS /
// RADIO_LIMITS); the server checks again and renders it.
export const RADIO_PRESETS: Record<Exclude<RadioPreset, "custom">, Omit<RadioFilter, "preset">> = {
  spain: { low_hz: 700, high_hz: 3300, slope_db_oct: 36, presence_db: 0, drive_db: 0, noise_dbfs: null, clicks: true },
  english: { low_hz: 1000, high_hz: 5000, slope_db_oct: 12, presence_db: 6, drive_db: 6, noise_dbfs: -50, clicks: false },
  spain_eco: { low_hz: 350, high_hz: 8000, slope_db_oct: 36, presence_db: 8, presence_hz: 2500, drive_db: 0, noise_dbfs: null, clicks: false },
  english_eco: { low_hz: 150, high_hz: 2250, slope_db_oct: 12, presence_db: 8, presence_hz: 400, drive_db: 0, noise_dbfs: null, clicks: false },
  soldier: { low_hz: 1000, high_hz: 5000, slope_db_oct: 24, presence_db: 0, drive_db: 1, noise_dbfs: -70, clicks: true },
  pilot: { low_hz: 700, high_hz: 3300, slope_db_oct: 24, presence_db: 0, drive_db: 0, noise_dbfs: -60, clicks: true },
};
export const RADIO_LIMITS = {
  low_hz: [100, 2000],
  high_hz: [1000, 10000],
  presence_db: [-6, 12],
  drive_db: [0, 24],
  noise_dbfs: [-80, -30],
} as const;
export const RADIO_SLOPES = [12, 24, 36] as const;
const RADIO_MIN_RATIO = 1.5;
/** Hiss level a field starts at when hiss is switched on. */
export const DEFAULT_HISS_DBFS = -55;

/** Turns the radio filter off (null) or sets it to a preset's values. */
export function setRadioPreset(edit: AudioEdit, preset: RadioPreset | null): AudioEdit {
  if (preset === null) return { ...edit, radio: null };
  const base = preset === "custom" ? (edit.radio ?? { ...RADIO_PRESETS.spain, preset: "custom" }) : RADIO_PRESETS[preset];
  return { ...edit, radio: { ...base, preset } as RadioFilter };
}

/** Changes one value of the radio filter; the filter becomes "custom" (no longer a preset's values). */
export function setRadioValue<K extends keyof Omit<RadioFilter, "preset">>(edit: AudioEdit, key: K, value: RadioFilter[K]): AudioEdit {
  if (!edit.radio) throw new Error("turn the radio filter on first");
  const next = { ...edit.radio, [key]: value, preset: "custom" as RadioPreset };
  const problem = radioProblem(next);
  if (problem) throw new Error(problem);
  return { ...edit, radio: next };
}

/** Why a radio filter would be refused by the server, or null. */
export function radioProblem(r: RadioFilter): string | null {
  for (const [key, [lo, hi]] of Object.entries(RADIO_LIMITS) as [keyof typeof RADIO_LIMITS, readonly [number, number]][]) {
    const v = r[key];
    if (v !== null && (!Number.isFinite(v) || v < lo || v > hi)) return `${key.replace(/_/g, " ")} must be ${lo}–${hi}`;
  }
  if (!(RADIO_SLOPES as readonly number[]).includes(r.slope_db_oct)) return `slope must be ${RADIO_SLOPES.join(", ")} dB/oct`;
  if (r.high_hz < r.low_hz * RADIO_MIN_RATIO) return `the band is too narrow: high must be at least ${RADIO_MIN_RATIO} × low`;
  return null;
}

// ---- Echo (2026-10-13, the "eco" lines). Same presets and limits as the server (audio_edit.ECHO_PRESETS /
// ECHO_LIMITS).
export const ECHO_PRESETS: Record<Exclude<EchoPreset, "custom">, Omit<EchoEffect, "preset">> = {
  spain: { slap_ms: 30, slap_db: null, delay_ms: 140, echo_db: -11, feedback_db: -15, diffusion: 1, damping_hz: 4000 },
  english: { slap_ms: 30, slap_db: -12, delay_ms: 150, echo_db: -12, feedback_db: null, diffusion: 0, damping_hz: null },
};
export const ECHO_LIMITS = {
  slap_ms: [5, 80],
  slap_db: [-40, -3],
  delay_ms: [50, 600],
  echo_db: [-40, -3],
  feedback_db: [-40, -3],
  diffusion: [0, 1],
  damping_hz: [1000, 16000],
} as const;
/** Values a switched-on optional echo field starts at. */
export const ECHO_DEFAULTS = { slap_db: -12, feedback_db: -9, damping_hz: 4000 } as const;

export function setEchoPreset(edit: AudioEdit, preset: EchoPreset | null): AudioEdit {
  if (preset === null) return { ...edit, echo: null };
  const base = preset === "custom" ? (edit.echo ?? { ...ECHO_PRESETS.spain, preset: "custom" }) : ECHO_PRESETS[preset];
  return { ...edit, echo: { ...base, preset } as EchoEffect };
}

export function setEchoValue<K extends keyof Omit<EchoEffect, "preset">>(edit: AudioEdit, key: K, value: EchoEffect[K]): AudioEdit {
  if (!edit.echo) throw new Error("turn the echo on first");
  const next = { ...edit.echo, [key]: value, preset: "custom" as EchoPreset };
  const problem = echoProblem(next);
  if (problem) throw new Error(problem);
  return { ...edit, echo: next };
}

export function echoProblem(e: EchoEffect): string | null {
  for (const [key, [lo, hi]] of Object.entries(ECHO_LIMITS) as [keyof typeof ECHO_LIMITS, readonly [number, number]][]) {
    const v = e[key];
    if (v !== null && (!Number.isFinite(v) || v < lo || v > hi)) return `${key.replace(/_/g, " ")} must be ${lo}–${hi}`;
  }
  return null;
}

// ---- Transmission interference (Victor 933 only): the intensity curve. Same rules and mapping as
// scripts/common/interference.py; the server checks again and renders it.
export const CURVE = { minSpacing: 0.002, maxPoints: 3000, speechFull: 0.35, partial: 0.6, mask: 0.95, bed: 0.35 } as const;

/** Speech level (dB) under the interference at intensity i; null = removed. Mirrors interference.speech_gain. */
export function speechDb(i: number): number | null {
  if (i <= CURVE.speechFull) return 0;
  if (i >= CURVE.mask) return null;
  let g = Math.pow(10, -(5 * ((i - CURVE.speechFull) / (CURVE.partial - CURVE.speechFull)) ** 2) / 20);
  if (i > 0.85) {
    const u = (i - 0.85) / (CURVE.mask - 0.85);
    g *= 1 - u * u * (3 - 2 * u);
  }
  return g > 0 ? 20 * Math.log10(g) : null;
}

/** The curve's value at time t (linear between points; flat before the first and after the last). */
export function curveAt(points: CurvePoint[], t: number): number {
  if (!points.length) return 0;
  if (t <= points[0].t) return points[0].v;
  for (let k = 1; k < points.length; k++) {
    const p = points[k - 1];
    const q = points[k];
    if (t <= q.t) return p.v + ((q.v - p.v) * (t - p.t)) / (q.t - p.t || 1);
  }
  return points[points.length - 1].v;
}

/** The lowest curve value over [a, b] (the points inside and both ends). */
export function curveMin(points: CurvePoint[], a: number, b: number): number {
  let m = Math.min(curveAt(points, a), curveAt(points, b));
  for (const p of points) if (p.t > a && p.t < b) m = Math.min(m, p.v);
  return m;
}

/** Why a curve would be refused, or null. */
export function curveProblem(points: CurvePoint[], duration: number): string | null {
  if (points.length < 2) return "the curve needs at least 2 points";
  if (points.length > CURVE.maxPoints) return `at most ${CURVE.maxPoints} points`;
  for (let k = 0; k < points.length; k++) {
    const p = points[k];
    if (!Number.isFinite(p.t) || !Number.isFinite(p.v)) return "enter numbers";
    if (p.v < 0 || p.v > 1) return "intensity is 0–1";
    if (p.t < 0 || (duration > 0 && p.t > duration + 0.001)) return "a point is outside the recording";
    if (k && p.t - points[k - 1].t < CURVE.minSpacing - 1e-9) return "two points are too close together";
  }
  return null;
}

/** Sets the curve's points (sorted, rounded like the server), refusing an invalid curve. */
export function setCurvePoints(edit: AudioEdit, points: CurvePoint[], duration: number): AudioEdit {
  if (!edit.interference) throw new Error("no interference curve on this recording");
  const next = [...points]
    .map((p) => ({ t: round3(p.t), v: round3(Math.min(1, Math.max(0, p.v))) }))
    .sort((a, b) => a.t - b.t);
  const problem = curveProblem(next, duration);
  if (problem) throw new Error(problem);
  return { ...edit, interference: { ...edit.interference, points: next } };
}

/** Sets the whole interference (Reset to the generated curve), or removes it (null). */
export function setInterferenceCurve(edit: AudioEdit, value: InterferenceCurve | null): AudioEdit {
  if (value === null) return { ...edit, interference: null };
  return { ...edit, interference: { engine: value.engine, guides: value.guides.map((g) => ({ ...g })),
                                    points: value.points.map((p) => ({ ...p })), flutter_db: value.flutter_db,
                                    texture: value.texture ?? "synthetic" } };
}

/** The static's source: made from scratch ("synthetic") or MCC Spain's sample ("mcc"). */
export function setTexture(edit: AudioEdit, texture: "synthetic" | "mcc"): AudioEdit {
  if (!edit.interference) throw new Error("no interference curve on this recording");
  return { ...edit, interference: { ...edit.interference, texture } };
}

export function setFlutter(edit: AudioEdit, db: number): AudioEdit {
  if (!edit.interference) throw new Error("no interference curve on this recording");
  if (!Number.isFinite(db) || db < 0 || db > 6) throw new Error("flutter is 0–6 dB");
  return { ...edit, interference: { ...edit.interference, flutter_db: Math.round(db * 10) / 10 } };
}

/** Where source time t lands in the edited recording (trims, cuts, inserted silences), as the server splices. */
export function editedTime(edit: AudioEdit, t: number): number {
  let pos = t - edit.trim_start_s;
  for (const c of edit.cuts) {
    if (t >= c.end_s) pos -= c.end_s - c.start_s;
    else if (t > c.start_s) pos -= t - c.start_s;
  }
  for (const s of edit.silences) if (s.at_s <= t) pos += s.dur_s;
  return Math.max(0, pos);
}

/** The source time of a position in the edited recording (inverse of editedTime, for the playhead). */
export function sourceTime(edit: AudioEdit, e: number, duration: number): number {
  let lo = 0;
  let hi = duration;
  for (let k = 0; k < 40; k++) {
    const mid = (lo + hi) / 2;
    if (editedTime(edit, mid) < e) lo = mid;
    else hi = mid;
  }
  return hi;
}

/** Back to an unedited recording. The gap is kept: it is not an edit to the audio itself. */
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
