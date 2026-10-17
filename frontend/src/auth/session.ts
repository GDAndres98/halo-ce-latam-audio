// Who is using this Studio page (docs/remote-access.md).
//
// The host computer's own address (127.0.0.1) needs no sign-in and is the only place game files can be
// installed or restored. Other computers reach the Studio through the remote address, sign in, and get the
// permissions of their account's role. The server decides every permission; this store only mirrors it
// so the screens can hide what would be refused.

import { computed, reactive, readonly } from "vue";
import { api, ApiError, onUnauthorized, setCsrfToken } from "../api/client";
import type { SessionInfo } from "../api/types";

const state = reactive({
  loaded: false,
  info: null as SessionInfo | null,
  /** Why the page is showing the sign-in form (expired session, signed out, unreachable server). */
  reason: "",
  /** Cloudflare Access must sign the visitor in again (its sign-in expired): show its button, not the form. */
  accessSignIn: false,
});

export const session = readonly(state);

export const signedIn = computed(() => !!state.info && (!state.info.auth_required || state.info.authenticated));
export const permissions = computed(
  () => state.info?.permissions ?? { edit: false, admin: false, install: false, settings_mcc: false },
);

/** The public read-only view (docs/public-access.md): anyone may browse; nothing can be changed. */
export const visitor = computed(() => Boolean(state.info?.visitor));
/** Nothing on this page may be changed: no saving, approving, choosing recordings or editing. */
export const readOnly = computed(() => !permissions.value.edit);
/** Recordings, waveforms and editor previews may be played (never for a visitor). */
export const canListen = computed(() => permissions.value.audio ?? permissions.value.edit);
/** Recordings may be saved as files (never for a visitor). */
export const canDownload = computed(() => permissions.value.download ?? permissions.value.edit);

function adopt(info: SessionInfo) {
  state.info = info;
  setCsrfToken(info.csrf);
}

export async function loadSession(): Promise<void> {
  try {
    adopt(await api.session());
    state.reason = "";
    state.accessSignIn = false;
  } catch (e) {
    state.reason = e instanceof Error ? e.message : String(e);
  } finally {
    state.loaded = true;
  }
}

export async function signIn(username: string, password: string): Promise<void> {
  const info = await api.login(username, password);
  adopt(info);
  state.reason = "";
}

/** Cloudflare Access mode: the browser goes through Access's login page and comes back to the Studio. A
 * server route, so the installed app's service worker never answers it from its cache. */
export function signInWithAccess(): void {
  window.location.assign("/api/sso/continue");
}

export async function signOut(): Promise<void> {
  if (state.info?.sso === "cloudflare_access") {
    window.location.assign(state.info.logout_url || "/cdn-cgi/access/logout"); // Cloudflare's own session
    return;
  }
  try {
    await api.logout();
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  }
  await loadSession();
  state.reason = "Signed out.";
}

// A 401 anywhere means the session ended: show the sign-in form. Unsaved typing stays in the browser session
// (see useMatch), so signing in again returns to it.
onUnauthorized((access) => {
  if (access) {
    state.accessSignIn = true;
    if (state.info) state.info = { ...state.info, authenticated: false, user: null, role: null, csrf: null };
    setCsrfToken(null);
    state.reason = "Your Cloudflare Access sign-in has expired. Sign in again; unsaved edits on this device are kept.";
    return;
  }
  if (state.info?.auth_required && state.info.authenticated) {
    state.info = { ...state.info, authenticated: false, user: null, role: null, csrf: null };
    setCsrfToken(null);
    state.reason = "Your session ended. Sign in again; unsaved edits on this computer are kept.";
  }
});
