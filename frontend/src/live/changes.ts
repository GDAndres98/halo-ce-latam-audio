// Live updates: the server tells every open Studio when decisions change (GET /api/events, Server-Sent
// Events), whichever computer or tool made the change. The screens then reload what they show.
//
// One connection per page. EventSource reconnects by itself; after a reconnection the screens reload once,
// because changes made while disconnected were not announced.

import { reactive, readonly } from "vue";
import type { ChangeEvent } from "../api/types";

type Listener = (event: ChangeEvent) => void;

const state = reactive({ status: "off" as "off" | "connecting" | "live" | "reconnecting" });
export const liveStatus = readonly(state);

const listeners = new Set<Listener>();
const reconnectListeners = new Set<() => void>();
let source: EventSource | null = null;
let everConnected = false;
let wanted = false;
let retry: ReturnType<typeof setTimeout> | undefined;

export function startLiveUpdates(): void {
  wanted = true;
  if (source || typeof EventSource === "undefined") return;
  state.status = "connecting";
  source = new EventSource("/api/events");
  source.addEventListener("hello", () => {
    const again = everConnected;
    everConnected = true;
    state.status = "live";
    if (again) reconnectListeners.forEach((listener) => listener());
  });
  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as ChangeEvent;
      if (event.type === "change") listeners.forEach((listener) => listener(event));
    } catch {
      // not a change message
    }
  };
  source.onerror = () => {
    // The browser retries on its own (retry: 3000 from the server) unless the answer was an error status.
    state.status = source?.readyState === EventSource.CLOSED ? "off" : "reconnecting";
    if (source?.readyState === EventSource.CLOSED) {
      source = null;
      clearTimeout(retry);
      retry = setTimeout(() => wanted && startLiveUpdates(), 5000);
    }
  };
}

export function stopLiveUpdates(): void {
  wanted = false;
  clearTimeout(retry);
  source?.close();
  source = null;
  state.status = "off";
}

/** Called with every change; returns the function that stops listening. */
export function onChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Called after the connection came back (changes may have been missed). */
export function onReconnect(listener: () => void): () => void {
  reconnectListeners.add(listener);
  return () => reconnectListeners.delete(listener);
}
