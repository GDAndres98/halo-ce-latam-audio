// One clip plays at a time across the whole Studio. Buttons and keyboard shortcuts both use this module,
// so starting a clip anywhere stops the previous one, and every button shows the same state.

import { reactive, readonly } from "vue";

const state = reactive({ url: null as string | null, playing: false, error: "" });
let audio: HTMLAudioElement | null = null;

export const playerState = readonly(state);

/** Starts the clip at `url`, or pauses it if it is the one playing. */
export function togglePlay(url: string): void {
  if (audio && state.url === url) {
    if (audio.paused) void play(audio);
    else pause();
    return;
  }
  stop();
  audio = new Audio(url);
  audio.onended = () => {
    state.playing = false;
  };
  state.url = url;
  state.error = "";
  void play(audio);
}

async function play(clip: HTMLAudioElement): Promise<void> {
  try {
    await clip.play();
    state.playing = true;
  } catch {
    // Browsers refuse playback on some failed loads; the message says what to check.
    state.playing = false;
    state.error = "This recording could not be played. Check that the game files and extracted audio are present.";
  }
}

export function pause(): void {
  audio?.pause();
  state.playing = false;
}

export function stop(): void {
  if (audio) {
    audio.pause();
    audio.src = "";
  }
  audio = null;
  state.url = null;
  state.playing = false;
}

/** Whether the clip at `url` is the one currently playing. */
export function isPlaying(url: string): boolean {
  return state.url === url && state.playing;
}
