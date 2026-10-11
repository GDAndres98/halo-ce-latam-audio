import type {
  AudioEdit,
  BuildJob,
  BuildScope,
  DeployStatus,
  InstallPlan,
  ExportSettings,
  BuildsResponse,
  CeResponse,
  DataStatus,
  ImportPreview,
  EditPreviewResponse,
  SaveBody,
  SaveResponse,
  SlotDetail,
  SlotsResponse,
  StateResponse,
} from "./types";

/** An error the API reported, with the HTTP status (409 = stale or conflicting, 400 = refused). */
export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly details: string[] = []) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const body = (await res.json().catch(() => ({}))) as { error?: string; details?: string[] };
  if (!res.ok) throw new ApiError(res.status, body.error ?? res.statusText, body.details ?? []);
  return body as T;
}

const query = (params: Record<string, string | number | undefined | null>): string => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

export const api = {
  state: () => request<StateResponse>("/api/state"),

  slots: (params: { level: string; status?: string; q?: string; limit?: number }) =>
    request<SlotsResponse>(`/api/slots${query(params)}`),

  slot: (id: string) => request<SlotDetail>(`/api/slot${query({ id })}`),

  builds: () => request<BuildsResponse>("/api/builds"),

  /** Starts an audio build (m6_build.py) in the background; poll job(). */
  startBuild: (body: { scope: BuildScope; mission?: string; levels?: string[]; name?: string }) =>
    request<BuildJob>("/api/builds/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "audio", ...body }),
    }),

  deployStatus: () => request<DeployStatus>("/api/deploy/status"),
  installPlan: (build: string) => request<InstallPlan>(`/api/deploy/plan${query({ build })}`),

  /** Installs a build into MCC (preflight, then install). Only after the owner confirmed the plan. */
  install: (build: string) =>
    request<BuildJob>("/api/deploy/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ build, confirm: true }),
    }),

  /** Restores the original game files from the verified backups. */
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

  exportSettings: () => request<ExportSettings>("/api/settings/export"),

  /** Saves the global gain. `loadedSha256` must be the hash the settings were read with (optimistic lock). */
  saveExportSettings: (globalGainDb: number, loadedSha256: string | null) =>
    request<ExportSettings>("/api/settings/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ global_gain_db: globalGainDb, loaded_sha256: loadedSha256 }),
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

  /** Renders an edit as M6 would, for listening only. Writes nothing to the mappings. */
  editPreview: (body: { slot_id: string; ce_line_ref: string; language: string; edit: AudioEdit }) =>
    request<EditPreviewResponse>("/api/edit/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

/** Audio is streamed by the API; these are the URLs the players use (same ones as the classic page). */
export const audioUrl = {
  mcc: (level: string, lang: "spanish" | "english", index: number) =>
    `/audio/mcc${query({ level, lang, index })}`,
  ce: (ref: string, lang: string) => `/audio/ce${query({ ref, lang })}`,
};
