// Waveform peaks from the server (GET /audio/peaks): a few kilobytes that let a waveform be drawn at once,
// while the browser streams the audio itself with range requests. Without them the whole WAV had to be
// downloaded and decoded before anything was drawn, which is slow from another computer.

import { audioUrl } from "../api/client";

export interface Peaks {
  duration: number;
  peaks: number[];
}

const cache = new Map<string, Promise<Peaks | null>>();

/** The peaks of one of the Studio's audio URLs, or null when they cannot be read (the caller then lets the
 * player decode the file itself). Cached per URL for the page's lifetime; failures are not cached. */
export function loadPeaks(url: string): Promise<Peaks | null> {
  let known = cache.get(url);
  if (!known) {
    known = fetch(audioUrl.peaks(url), { credentials: "same-origin" })
      .then(async (res) => {
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as Peaks;
        return Array.isArray(body.peaks) && body.duration > 0 ? body : null;
      })
      .catch(() => {
        cache.delete(url);
        return null;
      });
    cache.set(url, known);
    if (cache.size > 300) cache.delete(cache.keys().next().value as string);
  }
  return known;
}
