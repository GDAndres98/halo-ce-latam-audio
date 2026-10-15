// The build history's order and how its times read. The server already lists builds newest first
// (build_api.newest_first); the page sorts again with the same rules so the order never depends on the
// server's version, on folder names or on how a date is displayed.

/** A build's `built_at` as milliseconds since the epoch, or null when missing or not a valid ISO 8601 time.
 *  m6_build.py writes the host's local time without an offset, which JavaScript also reads as local time; a
 *  time with an offset or Z is honoured. */
export function builtAtMs(value: string | null | undefined): number | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$/.test(value.trim())) return null;
  const v = value.trim().replace(" ", "T");
  // A date alone is UTC to Date.parse; read it as local midnight like a local date-time.
  const ms = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(v) ? `${v}T00:00:00` : v);
  return Number.isNaN(ms) ? null : ms;
}

/** Newest first; equal times by name; builds without a valid time last, by name. Returns a new array. */
export function newestFirst<T extends { name: string; built_at: string | null }>(builds: readonly T[]): T[] {
  return builds
    .map((b) => ({ b, t: builtAtMs(b.built_at) }))
    .sort((x, y) => {
      if (x.t === null || y.t === null) return x.t === y.t ? cmp(x.b.name, y.b.name) : x.t === null ? 1 : -1;
      return y.t - x.t || cmp(x.b.name, y.b.name);
    })
    .map(({ b }) => b);
}

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

const pad = (n: number) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "15 Oct 2026" and "01:52" in the viewer's time zone, or null for a missing or invalid time. */
export function builtAtParts(value: string | null | undefined): { date: string; time: string; iso: string } | null {
  const ms = builtAtMs(value);
  if (ms === null) return null;
  const d = new Date(ms);
  return {
    date: `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
    iso: d.toISOString(),
  };
}

/** "3 folders: a10, x10, x20", for a title that shows them all. */
export function foldersTitle(levels: readonly string[]): string {
  return `${levels.length} folder${levels.length === 1 ? "" : "s"}: ${levels.join(", ")}`;
}

/** The local calendar day of a time, "2026-10-15" (groups builds by the day they were made). */
export function dayKey(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "Today", "Yesterday", or "Mon 13 Oct 2026", for a day group's heading. */
export function dayLabel(ms: number, now: number = Date.now()): string {
  const key = dayKey(ms);
  if (key === dayKey(now)) return "Today";
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  if (key === dayKey(y.getTime())) return "Yesterday";
  const d = new Date(ms);
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** Consecutive builds of the same day, in the order given; builds without a valid time form one last group. */
export function groupByDay<T extends { built_at: string | null }>(
  builds: readonly T[],
  now: number = Date.now(),
): { key: string; label: string; builds: T[] }[] {
  const groups: { key: string; label: string; builds: T[] }[] = [];
  for (const b of builds) {
    const ms = builtAtMs(b.built_at);
    const key = ms === null ? "undated" : dayKey(ms);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.builds.push(b);
    else groups.push({ key, label: ms === null ? "No date" : dayLabel(ms, now), builds: [b] });
  }
  return groups;
}

export type KindFilter = "all" | "audio" | "subtitles" | "both";
export type StatusFilter = "all" | "current" | "stale" | "failed" | "installed";

export interface BuildFilter {
  text: string;
  kind: KindFilter;
  status: StatusFilter;
}

/** Whether a build passes the list's filters. Text matches the name or a folder, ignoring case. */
export function matchesFilter(
  b: { name: string; kind: string; levels: string[]; stale: boolean; validation_ok: boolean | null },
  f: BuildFilter,
  installed: readonly string[] = [],
): boolean {
  const text = f.text.trim().toLowerCase();
  if (text && !b.name.toLowerCase().includes(text) && !b.levels.some((l) => l.toLowerCase().includes(text))) return false;
  if (f.kind !== "all" && b.kind !== f.kind) return false;
  switch (f.status) {
    case "current":
      return !b.stale;
    case "stale":
      return b.stale;
    case "failed":
      return b.validation_ok !== true;
    case "installed":
      return installed.includes(b.name);
    default:
      return true;
  }
}
