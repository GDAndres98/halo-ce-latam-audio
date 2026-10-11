// One clip plays at a time across the Studio: the waveform players and the one-click buttons. Whichever
// starts playing pauses the one that was playing. Playing two recordings at once is never a side effect;
// it only happens when the user starts both.

export interface Playback {
  pause(): void;
}

let playing: Playback | null = null;

/** Called by a player when it starts. Pauses the previous player, if it is a different one. */
export function startPlayback(player: Playback): void {
  if (playing && playing !== player) playing.pause();
  playing = player;
}

/** Called by a player when it stops or finishes, so it is not paused for nothing later. */
export function endPlayback(player: Playback): void {
  if (playing === player) playing = null;
}

/** Pauses whichever player is playing (Escape). */
export function stopCurrent(): void {
  const current = playing;
  playing = null;
  current?.pause();
}
