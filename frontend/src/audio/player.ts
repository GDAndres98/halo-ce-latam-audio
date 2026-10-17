// One clip plays at a time across the whole Studio. Buttons and keyboard shortcuts both use this module,
// so starting a clip anywhere stops the previous one, and every button shows the same state.

import { reactive, readonly } from "vue";
import { canListen } from "../auth/session";
import { endPlayback, startPlayback, type Playback } from "./transport";

// `loading`: asked to play, waiting for the first audio (a slow connection, a recording decoded on demand).
const state = reactive({ url: null as string | null, playing: false, loading: false, error: "" });
let audio: HTMLAudioElement | null = null;

export const playerState = readonly(state);

// The one-click clips are one player among the others (see transport.ts).
const clipPlayer: Playback = { pause: () => pause() };

/** Starts the clip at `url`, or pauses it if it is the one playing. */
export function togglePlay(url: string): void {
  if (!canListen.value) return; // the public read-only view never streams recordings (the server refuses them)
  if (audio && state.url === url) {
    if (audio.paused) void play(audio);
    else pause();
    return;
  }
  stop();
  audio = new Audio(url);
  audio.onended = () => {
    state.playing = false;
    endPlayback(clipPlayer);
  };
  audio.onplaying = () => (state.loading = false);
  state.url = url;
  state.error = "";
  void play(audio);
}

async function play(clip: HTMLAudioElement): Promise<void> {
  try {
    startPlayback(clipPlayer);
    state.loading = clip.readyState < HTMLMediaElement.HAVE_FUTURE_DATA;
    await clip.play();
    if (clip !== audio) return; // another clip was started meanwhile
    state.playing = true;
    state.loading = false;
  } catch {
    if (clip !== audio) return; // this clip was replaced before it could play: not an error
    // Browsers refuse playback on some failed loads; the message says what to check.
    state.playing = false;
    state.loading = false;
    state.error = "This recording could not be played. Check that the game files and extracted audio are present.";
  }
}

export function pause(): void {
  audio?.pause();
  state.playing = false;
  state.loading = false;
  endPlayback(clipPlayer);
}

export function stop(): void {
  if (audio) {
    audio.pause();
    audio.src = "";
  }
  audio = null;
  state.url = null;
  state.playing = false;
  state.loading = false;
  endPlayback(clipPlayer);
}

/** Whether the clip at `url` was asked to play and its audio has not arrived yet. */
export function isLoading(url: string): boolean {
  return state.url === url && state.loading;
}

/** Whether the clip at `url` is the one currently playing. */
export function isPlaying(url: string): boolean {
  return state.url === url && state.playing;
}
