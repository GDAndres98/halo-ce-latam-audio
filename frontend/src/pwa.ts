// The installable app (docs/mobile.md §9): the service worker's registration, its "new version" prompt, and
// the install offer.
//
// The service worker only keeps the Studio's built files (see vite.config.ts); it never stores decisions,
// recordings or API answers. A new version waits until the user chooses Reload (or the app is next opened),
// so an update never reloads the page in the middle of an edit. Unsaved edits are in the browser session
// anyway (useMatch), and survive the reload.
//
// Browsers register service workers only on secure addresses (https, or this computer). On a plain-http LAN
// address nothing here happens and the Studio works as a normal web page.

import { reactive, readonly } from "vue";
import { registerSW } from "virtual:pwa-register";

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const standaloneQuery = typeof window !== "undefined" ? window.matchMedia?.("(display-mode: standalone)") : undefined;
const ios =
  typeof navigator !== "undefined" &&
  (/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));

const state = reactive({
  /** A new version of the Studio is ready; it is used after Reload. */
  needRefresh: false,
  /** The browser offers installing (Chrome, Edge, Android): the Install button can show its dialog. */
  canInstall: false,
  /** Running as the installed app (no address bar). */
  standalone: Boolean(standaloneQuery?.matches || (navigator as Navigator & { standalone?: boolean }).standalone),
  /** iPhone or iPad: installing is Share → Add to Home Screen (Safari has no install dialog). */
  ios,
  /** The page is on a secure address, which installing needs. */
  secure: typeof window !== "undefined" && window.isSecureContext,
});

export const pwa = readonly(state);

let deferredPrompt: InstallPromptEvent | null = null;
let updateServiceWorker: ((reload?: boolean) => Promise<void>) | null = null;

export function startPwa(): void {
  if (typeof window === "undefined") return;
  standaloneQuery?.addEventListener?.("change", (e) => (state.standalone = e.matches));
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // offered by the Studio's own Install button instead of the browser's banner
    deferredPrompt = event as InstallPromptEvent;
    state.canInstall = true;
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    state.canInstall = false;
  });
  if (!("serviceWorker" in navigator)) return;
  updateServiceWorker = registerSW({
    onNeedRefresh: () => (state.needRefresh = true),
    // Check for a new version when the app comes back to the foreground, and every hour while open.
    onRegisteredSW: (_url, registration) => {
      if (!registration) return;
      const check = () => void registration.update().catch(() => {});
      setInterval(check, 60 * 60 * 1000);
      document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && check());
    },
  });
}

/** Shows the browser's install dialog. Returns whether the user installed. */
export async function installApp(): Promise<boolean> {
  if (!deferredPrompt) return false;
  const prompt = deferredPrompt;
  deferredPrompt = null;
  state.canInstall = false;
  await prompt.prompt();
  return (await prompt.userChoice).outcome === "accepted";
}

/** Uses the new version: the waiting service worker takes over and the page reloads. */
export function applyUpdate(): void {
  if (updateServiceWorker) void updateServiceWorker(true);
  else window.location.reload();
}
