// Shapes of the JSON the M4 API returns (scripts/ui/m4_app.py). Keep in step with that module.

export interface LevelProgress {
  slots: number;
  decided: number;
  matched: number;
  no_equivalent: number;
  deferred: number;
  audio_approved: number;
  subtitle_approved: number;
  needs_rework: number;
  radio_effect: number;
  different_but_fits: number;
  ready_for_build: boolean;
}

export interface LevelSummary {
  level: string;
  group: string;
  tags: number;
  slots: number;
  progress: LevelProgress;
  status: { status: string; updated_at: string; note: string } | null;
  ce_missions: string[];
}

export interface MissionSummary {
  mission: string;
  records: number;
  lines: number;
  lines_with_es_mx_audio: number;
}

export interface StateResponse {
  levels: LevelSummary[];
  missions: MissionSummary[];
  pins: Record<string, string | null>;
  current_pins: Record<string, string | null>;
  sha256: Hashes;
}

/** Hashes of the files a page was loaded from. Every save must send them back (optimistic locking). */
export interface Hashes {
  mappings: string;
  local: string;
  progress: string;
}

export type MatchStatus = "unreviewed" | "matched" | "no_equivalent" | "deferred";
export type CeLanguage = "Spanish(Mexico)" | "English(US)" | "Spanish(Spain)";
export type AudioSource = "keep_original" | "ce";
export type SubtitleSource = "keep_original" | "ce_locres" | "custom" | "none";
export type ApprovalField = "audio" | "subtitle";
export type ObjectStatus = "draft" | "approved" | "needs_rework";

/** An audio recipe. Speed and per-line gain were removed on 2026-10-09 and must not come back. */
export interface AudioEdit {
  trim_start_s: number;
  trim_end_s: number;
  gap_s: number;
  cuts: { start_s: number; end_s: number }[];
  silences: { at_s: number; dur_s: number }[];
  fade_in_ms: number;
  fade_out_ms: number;
  crossfade_ms: number;
  limiter: boolean;
  loudness: { mode: string; offset_db: number };
}

/** The decision as stored in mappings/manual_mappings.json (returned inside /api/slot). */
export interface StoredDecision {
  mapping_id: string;
  match: { status: MatchStatus; ce_line_refs: string[]; decided_at: string | null; revision: number };
  audio: {
    status: ObjectStatus;
    source: AudioSource;
    sources: { kind: "ce"; ce_line_ref: string; language: CeLanguage }[];
    edit: AudioEdit;
    approved_at: string | null;
    revision: number;
  };
  subtitle: {
    status: ObjectStatus;
    source: SubtitleSource;
    ce_locres: { ce_line_ref: string; culture: string } | null;
    custom_ref: string | null;
    approved_at: string | null;
    revision: number;
  };
  radio_effect: { needed: boolean; set_at: string | null; revision: number };
  different_but_fits?: { marked: boolean; set_at: string | null; revision: number };
  notes: string;
}

export interface SlotRow {
  slot_id: string;
  level: string;
  mcc_tag: string;
  tag_name: string;
  kind: string;
  speaker_from_name: string;
  ordinal: number;
  duration_s: number;
  en_duration_s: number | null;
  channels: number;
  flags: string[];
  /** Null for a line with no saved decision. */
  decision: { match: string; audio: string; subtitle: string; audio_source: string | null; subtitle_source: string | null } | null;
  radio_effect: boolean;
  different_but_fits: boolean;
  edited: boolean;
  preview: string;
  /** Bank index of the Spain sample: what /audio/mcc plays. */
  spanish_index: number;
}

export interface SlotsResponse {
  level: string;
  slots: SlotRow[];
  total: number;
  truncated: boolean;
  progress: LevelProgress;
  sha256: Hashes;
}

export interface SpanishSample {
  index: number;
  subsong: number;
  name_in_bank: string;
  duration_s: number;
  channels: number;
}

export interface EnglishSample {
  index: number;
  name_in_bank: string;
  duration_s: number;
}

export interface MccSubtitle {
  text: string | null;
  speaker_label: string | null;
  table_loaded: boolean;
}

export interface SlotDetail {
  slot_id: string;
  level: string;
  mcc_tag: string;
  tag_name: string;
  kind: string;
  speaker_from_name: string;
  spanish: SpanishSample;
  english: EnglishSample[];
  /** Keys: SU (LATAM, the replacement text), SP (Spain), EN. */
  mcc_subtitles: Record<string, MccSubtitle>;
  mapping: StoredDecision | null;
  custom_text: string | null;
  matched_lines: CeLine[];
  ce_missions: string[];
  sha256: Hashes;
}

export interface CeLine {
  ce_line_ref: string;
  mission: string;
  display_key: string;
  family: string;
  folder: string;
  has_source_subtitle: Record<string, boolean>;
  subtitles: Record<string, { text: string | null } | undefined>;
  media: Record<CeLanguage, { count: number; evidence: string; duration_s: number | null }>;
  used_by: string[];
}

export interface CeResponse {
  scope: string;
  total: number;
  offset: number;
  limit: number;
  lines: CeLine[];
  terms: string[];
  hidden_used: number;
}

export interface SaveAction {
  action: "approve" | "needs_rework";
  field: ApprovalField;
}

/** Body of POST /api/save. Omitted sections are left unchanged by the server. */
export interface SaveBody {
  slot_id: string;
  loaded_sha256: string;
  local_sha256: string;
  actions?: SaveAction[];
  match?: { status: MatchStatus; ce_line_refs: string[] };
  audio?: {
    source: AudioSource;
    sources: { ce_line_ref: string; language: CeLanguage }[];
    /** Sent only when the recipe changed. Omitting it keeps the stored recipe. */
    edit?: AudioEdit;
  };
  subtitle?: {
    source: SubtitleSource;
    ce_locres?: { ce_line_ref: string; culture: string };
    custom_text?: string;
  };
  radio_effect?: { needed: boolean };
  different_but_fits?: { marked: boolean };
  notes?: string;
}

export interface SaveResponse {
  saved: boolean;
  message?: string;
  sha256?: string;
  slot: SlotDetail;
}

export interface EditPreviewResponse {
  key: string;
  urls: { edited: string; encoded: string };
  stats: Record<string, number>;
}

/** The global export gain (config/audio_export.json). `source` is "default" when no file has been saved. */
export interface ExportSettings {
  global_gain_db: number;
  source: string;
  sha256: string | null;
}

export interface BuildSummary {
  name: string;
  levels: string[];
  built_at: string | null;
  counts: Record<string, number>;
  subtitles: Record<string, unknown>;
  validation_ok: boolean | null;
  stale: boolean;
  stale_reasons: string[];
  built_gain_db: number | null;
  built_from_sha256: string | null;
  candidate_sha256: string | null;
}

export interface BuildsResponse {
  builds: BuildSummary[];
  decisions_sha256: string | null;
}

export interface BuildJob {
  id: string;
  name: string;
  levels: string[];
  state: "running" | "done" | "failed";
  started: string;
  returncode: number | null;
  log_tail: string;
}
