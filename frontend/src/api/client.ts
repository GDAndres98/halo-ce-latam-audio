import type { AudioEdit, BuildDetail, BuildJob, BuildKind, BuildPreview, BuildScope, DeployEvent, DeployStatus, InstallPlan, ExportSettings, LevelMode, BuildsResponse, CeLine, CeResponse, DataStatus, ImportPreview, EditPreviewResponse, SaveBody, SaveResponse, SlotDetail, SlotsResponse, StateResponse, SessionInfo, NetworkInfo, InterferenceReference, TakeResponse, ConversionPreview, ConversionInventory, ConversionResponse, ApprovableTakes, RevertPreview, CombineEdit, SetSubtitleChoice } from "./types";

/** An error the API reported, with the HTTP status (409 = stale or conflicting, 400 = refused). */
export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly details: string[] = []) {
    super(message);
    this.name = "ApiError";
  }
}

// The CSRF token of the signed-in session (remote access, docs/remote-access.md). Every POST carries it;
// the host's own address needs none and ignores it. Set by the session store (auth/session.ts).
let csrfToken: string | null = null;
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

// Told when the server answers 401: the session ended (signed out, expired, password changed). `access` is
// true when Cloudflare Access (docs/deploy-cloudflare.md) answered instead of the Studio: its sign-in expired.
const unauthorizedListeners: ((access: boolean) => void)[] = [];
export function onUnauthorized(listener: (access: boolean) => void): void {
  unauthorizedListeners.push(listener);
}

/** The message of an expired Cloudflare Access sign-in (the request was redirected to its login page). */
export const ACCESS_EXPIRED = "Your Cloudflare Access sign-in has expired.";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.method === "POST" && csrfToken) headers.set("X-Studio-CSRF", csrfToken);
  let res: Response;
  try {
    // The Studio's API never redirects. A redirect means Cloudflare Access is sending the browser to its login
    // page (expired sign-in); "manual" makes it visible here instead of a cross-site fetch that fails.
    res = await fetch(path, { ...init, headers, credentials: "same-origin", redirect: "manual" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "The Studio server cannot be reached. Check the connection to the host computer.");
  }
  if (res.type === "opaqueredirect" || (res.status >= 300 && res.status < 400 && res.status !== 304)) {
    unauthorizedListeners.forEach((listener) => listener(true));
    throw new ApiError(401, ACCESS_EXPIRED);
  }
  const body = (await res.json().catch(() => ({}))) as { error?: string; details?: string[] };
  if (res.status === 401 && path !== "/api/login") unauthorizedListeners.forEach((listener) => listener(false));
  if (!res.ok) throw new ApiError(res.status, body.error ?? res.statusText, body.details ?? []);
  return body as T;
}

const postJson = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const query = (params: Record<string, string | number | undefined | null>): string => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

export const api = {
  /** Who is signed in on this address, the role and what it may do. Never needs a session. */
  session: () => request<SessionInfo>("/api/session"),
  login: (username: string, password: string) => request<SessionInfo>("/api/login", postJson({ username, password })),
  logout: () => request<{ signed_out: boolean; logout_url?: string }>("/api/logout", postJson({})),
  /** Listeners and the addresses to open from another computer. */
  network: () => request<NetworkInfo>("/api/network"),

  state: () => request<StateResponse>("/api/state"),

  slots: (params: { level: string; status?: string; q?: string; limit?: number }) =>
    request<SlotsResponse>(`/api/slots${query(params)}`),

  slot: (id: string) => request<SlotDetail>(`/api/slot${query({ id })}`),

  /** One Campaign Evolved line with its subtitles (for a recording chosen but not saved yet). */
  ceLine: (ref: string) => request<CeLine>(`/api/ce_line${query({ ref })}`),

  builds: () => request<BuildsResponse>("/api/builds"),

  /** Starts a build (m6_build.py --kind) in the background; poll job(). */
  startBuild: (body: { kind?: BuildKind; scope: BuildScope; mission?: string; levels?: string[]; name?: string }) =>
    request<BuildJob>("/api/builds/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "audio", ...body }),
    }),

  /** What a build of this scope would contain, from the current approved decisions. Builds nothing. */
  buildPreview: (body: { scope: BuildScope; mission?: string; levels?: string[] }) =>
    request<BuildPreview>("/api/builds/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  buildDetail: (name: string) => request<BuildDetail>(`/api/builds/detail${query({ name })}`),
  buildLog: (name: string) => request<{ name: string; log: string }>(`/api/builds/log${query({ name })}`),
  deployHistory: () => request<{ events: DeployEvent[] }>("/api/deploy/history"),

  deployStatus: () => request<DeployStatus>("/api/deploy/status"),
  installPlan: (build: string) => request<InstallPlan>(`/api/deploy/plan${query({ build })}`),

  /** Installs a build into MCC (preflight, then install). Only after the owner confirmed the plan. */
  install: (build: string) =>
    request<BuildJob>("/api/deploy/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ build, confirm: true }),
    }),

  /** Restores the original game files from the verified backups (every installed build when none is named). */
  restore: (build?: string) =>
    request<BuildJob>("/api/deploy/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ build, confirm: true }),
    }),

  setMccFolder: (mccFolder: string) =>
    request<DeployStatus>("/api/settings/mcc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mcc_folder: mccFolder }),
    }),

  job: (id: string) => request<BuildJob>(`/api/job${query({ id })}`),

  ce: (params: { mission?: string; q?: string; offset?: number; limit?: number; subs?: string; hide_used?: boolean; level?: string; keep_slot?: string }) =>
    request<CeResponse>(`/api/ce${query({ ...params, hide_used: params.hide_used ? "1" : undefined })}`),

  /** Saves a decision. The server checks the hashes and the approval rules; a 409 means the page is stale
   * or the decision is protected, and nothing was written. */
  save: (body: SaveBody) =>
    request<SaveResponse>("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  /** Added takes of one sound: add / change / approve / rework (save), reorder (move), remove. Each request names
   * the sound's version it was made from (409 when another computer changed the sound's takes). */
  takeSave: (body: TakeSaveBody) => request<TakeResponse>("/api/takes/save", postJson(body)),
  takeMove: (body: { mcc_tag: string; take_id: string; direction: -1 | 1; loaded_takes_sha256: string }) =>
    request<TakeResponse>("/api/takes/move", postJson(body)),
  takeRemove: (body: { mcc_tag: string; take_id: string; loaded_takes_sha256: string }) =>
    request<TakeResponse>("/api/takes/remove", postJson(body)),
  /** Adds several recordings as new draft takes in one save; recordings already a take are skipped. */
  takeAddMany: (body: { mcc_tag: string; loaded_takes_sha256: string; audio_list: { ce_line_ref: string; language: string }[] }) =>
    request<TakeResponse>("/api/takes/add_many", postJson(body)),
  /** Turns a sound's own take set on (clearing the listed line decisions) or off. */
  ownSetOn: (body: { mcc_tag: string; loaded_takes_sha256: string; loaded_sound_sha256: string;
                     clear_mapping_ids: string[]; audio_list?: { ce_line_ref: string; language: string }[];
                     /** Subtitled sounds: the set's one subtitle, saved as a draft. */
                     subtitle?: SetSubtitleChoice }) =>
    request<TakeResponse>("/api/takes/own_set_on", postJson(body)),
  ownSetOff: (body: { mcc_tag: string; loaded_takes_sha256: string }) =>
    request<TakeResponse>("/api/takes/own_set_off", postJson(body)),
  /** The ONE subtitle of a subtitled sound's own set (owner 2026-10-19): save (draft), approve, Needs rework; null
   * clears an unapproved one. Never approves without the owner's explicit action. */
  setSubtitle: (body: { mcc_tag: string; loaded_takes_sha256: string; subtitle?: SetSubtitleChoice | null;
                        actions?: { action: "approve" | "needs_rework" }[] }) =>
    request<TakeResponse>("/api/takes/set_subtitle", postJson(body)),

  /** Replacement sets (docs/replacement-set-conversion.md). Previews are read-only; every action names what the
   * page showed (the preview token or the sound's version) and is refused when it changed. */
  convertPreview: (mccTag: string) =>
    request<ConversionPreview>(`/api/takes/convert/preview${query({ mcc_tag: mccTag })}`),
  convertInventory: (level: string) =>
    request<ConversionInventory>(`/api/takes/convert/inventory${query({ level })}`),
  convertStage: (body: { items: { mcc_tag: string; token: string; acknowledged?: string[] }[]; bulk?: boolean;
                         confirm: true }) =>
    request<ConversionResponse>("/api/takes/convert/stage", postJson(body)),
  convertActivate: (body: { items: { mcc_tag: string; loaded_sound_sha256: string }[]; confirm: true }) =>
    request<ConversionResponse>("/api/takes/convert/activate", postJson(body)),
  convertCancel: (body: { mcc_tag: string; loaded_sound_sha256: string }) =>
    request<ConversionResponse>("/api/takes/convert/cancel", postJson(body)),
  convertApprovable: (mccTag: string) =>
    request<ApprovableTakes>(`/api/takes/convert/approvable${query({ mcc_tag: mccTag })}`),
  /** The owner's explicit approval of exactly the takes listed as unchanged (nothing is approved if the list moved). */
  convertApproveUnchanged: (body: { mcc_tag: string; loaded_sound_sha256: string; take_ids: string[]; confirm: true }) =>
    request<ConversionResponse>("/api/takes/convert/approve_unchanged", postJson(body)),
  convertRevertPreview: (mccTag: string, reworkDrifted = false) =>
    request<RevertPreview>(`/api/takes/convert/revert_preview${query({ mcc_tag: mccTag, rework_drifted: reworkDrifted ? "1" : undefined })}`),
  /** Undo exactly as previewed (token); refused while a conflict remains or if anything changed. */
  convertRevert: (body: { mcc_tag: string; token: string; rework_drifted?: boolean; confirm: true }) =>
    request<ConversionResponse>("/api/takes/convert/revert", postJson(body)),

  exportSettings: () => request<ExportSettings>("/api/settings/export"),

  /** Saves the global gain and/or the level mode (null keeps the saved value). `loadedSha256` must be the hash
   * the settings were read with (optimistic lock). */
  saveExportSettings: (globalGainDb: number | null, loadedSha256: string | null, levelMode?: LevelMode) =>
    request<ExportSettings>("/api/settings/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ global_gain_db: globalGainDb, loaded_sha256: loadedSha256, level_mode: levelMode }),
    }),

  /** How manual_mappings.json relates to the database (the source of truth). Read-only. */
  dataStatus: () => request<DataStatus>("/api/data/status"),

  /** What importing manual_mappings.json would change in the database. Read-only. */
  dataPreviewImport: () => request<ImportPreview>("/api/data/import/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),

  /** The file's decisions replace the database's. The hashes come from the preview the owner confirmed. */
  dataImport: (fileSha256: string, dbExportSha256: string) =>
    request<{ changed_slots: number; database_backup: string; status: DataStatus }>("/api/data/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_sha256: fileSha256, db_export_sha256: dbExportSha256, confirm: true }),
    }),

  /** The database is written over the file (a differing file is kept in mappings/.history/ first). */
  dataExport: (fileSha256: string | null) =>
    request<{ exported_sha256: string; status: DataStatus }>("/api/data/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_sha256: fileSha256, confirm: true }),
    }),

  /** The MCC original's interference estimate for the Victor 933 lane (a reference only; read-only). */
  interferenceReference: (slot: string, lang: "spanish" | "english") =>
    request<InterferenceReference>(`/api/interference/reference${query({ slot, lang })}`),

  /** Renders an edit as M6 would, for listening only. Writes nothing to the mappings. */
  /** A join or an overlay of two recordings, rendered as the build would (never saved). */
  editPreviewCombined: (body: { slot_id: string; source: string; sources: { ce_line_ref: string; language: string }[];
                                edit: CombineEdit }, signal?: AbortSignal) =>
    request<EditPreviewResponse>("/api/edit/preview_combined", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  editPreview: (body: { slot_id: string; ce_line_ref: string; language: string; edit: AudioEdit }, signal?: AbortSignal) =>
    request<EditPreviewResponse>("/api/edit/preview", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

/** Audio is streamed by the API; these are the URLs the players use (same ones as the classic page). */
export interface TakeSaveBody {
  mcc_tag: string;
  loaded_takes_sha256: string;
  take_id?: string;
  audio?: { ce_line_ref: string; language: string };
  actions?: { action: "approve" | "needs_rework"; field: "audio" }[];
}

export const audioUrl = {
  mcc: (level: string, lang: "spanish" | "english", index: number) =>
    `/audio/mcc${query({ level, lang, index })}`,
  ce: (ref: string, lang: string) => `/audio/ce${query({ ref, lang })}`,
  /** Waveform peaks of one of the URLs above (drawn before the audio itself is downloaded). */
  peaks: (url: string) => `/audio/peaks${query({ src: url })}`,
};
