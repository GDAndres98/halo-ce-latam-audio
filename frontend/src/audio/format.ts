// Times shown to the user: "1.234 s" for durations, "0:01.234" for positions on a recording.

/** A duration in seconds with three decimals, as the matching screens show durations. */
export function formatSeconds(seconds: number | null): string {
  return seconds === null || !Number.isFinite(seconds) ? "—" : `${seconds.toFixed(3)} s`;
}

/** A position on a recording: minutes, seconds and milliseconds, for example 0:01.234. */
export function formatPosition(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(3).padStart(6, "0")}`;
}
