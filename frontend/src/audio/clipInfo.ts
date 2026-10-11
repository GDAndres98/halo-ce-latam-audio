// Durations of audio clips, read from the file header (no decoding), cached per URL.
// Used for the duration comparison and the candidate list, where decoding every clip would be slow.

const cache = new Map<string, Promise<number | null>>();

export function clipDuration(url: string): Promise<number | null> {
  let known = cache.get(url);
  if (!known) {
    known = new Promise((resolve) => {
      const clip = new Audio();
      clip.preload = "metadata";
      clip.onloadedmetadata = () => resolve(Number.isFinite(clip.duration) ? clip.duration : null);
      clip.onerror = () => {
        cache.delete(url); // a later attempt may succeed (for example once the API has started)
        resolve(null);
      };
      clip.src = url;
    });
    cache.set(url, known);
  }
  return known;
}
