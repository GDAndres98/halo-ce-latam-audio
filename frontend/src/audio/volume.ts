// One listening volume for the whole Studio, set from the top band. Every player (the one-click clips, the
// waveforms, the interference lane) registers its media element here, so a change applies to whatever is
// playing and to everything played later. It only changes what this browser plays: recordings, previews and
// builds are untouched. Remembered per browser; storage can be blocked, and the default is then used.

import { computed, reactive, readonly, watch } from "vue";

export const VOLUME_STORAGE_KEY = "studio.volume";
const DEFAULT = { level: 1, muted: false };

const state = reactive(load());
const elements = new Set<HTMLMediaElement>();

export const volumeState = readonly(state);
/** The volume the media elements get: 0 when muted. */
export const effectiveVolume = computed(() => (state.muted ? 0 : state.level));

/** Reads a stored setting; anything unexpected falls back to full volume, not muted. */
export function parseStoredVolume(raw: string | null): { level: number; muted: boolean } {
  if (!raw) return { ...DEFAULT };
  try {
    const value = JSON.parse(raw) as { level?: unknown; muted?: unknown };
    const level = typeof value.level === "number" && Number.isFinite(value.level) ? clamp(value.level) : DEFAULT.level;
    return { level, muted: value.muted === true };
  } catch {
    return { ...DEFAULT };
  }
}

function load() {
  try {
    return parseStoredVolume(localStorage.getItem(VOLUME_STORAGE_KEY));
  } catch {
    return { ...DEFAULT };
  }
}

function clamp(level: number): number {
  return Math.min(1, Math.max(0, level));
}

/** Sets the volume (0 to 1). Moving it above 0 unmutes, as a media player's slider does. */
export function setVolume(level: number): void {
  state.level = clamp(level);
  if (state.level > 0) state.muted = false;
}

export function toggleMute(): void {
  // Unmuting a volume left at 0 would still be silent: bring it back to a usable level.
  if (state.muted || state.level === 0) {
    state.muted = false;
    if (state.level === 0) state.level = 0.5;
  } else {
    state.muted = true;
  }
}

/** Keeps `el` at the Studio volume until the returned function is called. */
export function attachVolume(el: HTMLMediaElement): () => void {
  el.volume = effectiveVolume.value;
  elements.add(el);
  return () => elements.delete(el);
}

watch(effectiveVolume, (volume) => {
  for (const el of elements) el.volume = volume;
});

watch(
  () => ({ level: state.level, muted: state.muted }),
  (value) => {
    try {
      localStorage.setItem(VOLUME_STORAGE_KEY, JSON.stringify(value));
    } catch {
      // Not saved: the volume still applies for this visit.
    }
  },
);
