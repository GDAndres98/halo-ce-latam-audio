import type {
  AudioEdit,
  BuildJob,
  BuildsResponse,
  CeResponse,
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

  startDryRun: (levels: string[], name?: string) =>
    request<BuildJob>("/api/builds/dry-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ levels, name }),
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
