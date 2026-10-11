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
  needs_recording: number;
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

/** An audio recipe. Speed and per-line gain were removed on 2026-10-09, and the limiter setting on
 * 2026-10-11; none of them must come back. */
export interface AudioEdit {
  trim_start_s: number;
  trim_end_s: number;
  gap_s: number;
  cuts: { start_s: number; end_s: number }[];
  silences: { at_s: number; dur_s: number }[];
  fade_in_ms: number;
  fade_out_ms: number;
  crossfade_ms: number;
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
  /** Optional: written only once first marked (added 2026-10-11). */
  needs_recording?: { marked: boolean; set_at: string | null; revision: number };
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
  /** How many Spain samples the tag has (several = takes, shown as "#n"). */
  permutations: number;
  duration_s: number;
  en_duration_s: number | null;
  /** Bank index of the English sample of the same take (what /audio/mcc plays in English), if any. */
  english_index: number | null;
  channels: number;
  flags: string[];
  /** Null for a line with no saved decision. */
  decision: { match: string; audio: string; subtitle: string; audio_source: string | null; subtitle_source: string | null } | null;
  radio_effect: boolean;
  different_but_fits: boolean;
  needs_recording: boolean;
  edited: boolean;
  preview: string;
  /** The first words of MCC's English subtitle. */
  english_preview: string;
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
  ordinal_in_tag: number;
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
  /** The stored recipe in short, and whether the server can render previews (ffmpeg and the encoder). */
  edit?: { identity: boolean; summary: string; available: boolean; engine: string };
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
  used_by?: string[];
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
  needs_recording?: { marked: boolean };
  notes?: string;
}

export interface SaveResponse {
  saved: boolean;
  message?: string;
  sha256?: string;
  slot: SlotDetail;
  /** The saved line as the MCC list shows it, and its level's progress (absent when nothing changed). */
  row?: SlotRow;
  progress?: LevelProgress;
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
  install_files: { install_rel: string; candidate_sha256: string }[];
}

export interface BuildsResponse {
  builds: BuildSummary[];
  decisions_sha256: string | null;
  /** Why subtitle builds are not offered yet. */
  subtitles_disabled: string;
  /** Playable maps a mission build can target (its folder plus its cinematics). */
  missions: string[];
}

export type BuildScope = "mission" | "levels" | "all_mapped";

/** The MCC folder and what it holds now (GET /api/deploy/status). */
export interface DeployStatus {
  mcc_folder: string | null;
  source: string;
  valid: boolean;
  /** The folder is fixed by the server (test mode) and cannot be changed from the page. */
  fixed: boolean;
  game_running: string[];
  files: { install_rel: string; sha256: string | null; state: "original" | "build" | "unknown"; builds: string[] }[];
  active_builds: string[];
  mod_installed: boolean;
}

/** What installing a build would change (GET /api/deploy/plan). */
export interface InstallPlan {
  build: string;
  mcc_folder: string | null;
  validation_ok: boolean | null;
  stale: boolean;
  stale_reasons: string[];
  counts: Record<string, number>;
  levels: string[];
  files: {
    install_rel: string;
    installed_path: string;
    candidate_bytes: number | null;
    original_sha256: string;
    candidate_sha256: string;
    backup_folder: string;
  }[];
  subtitles: string;
}

export interface BuildJob {
  id: string;
  kind: "build" | "install" | "restore";
  name: string;
  state: "running" | "done" | "failed";
  started: string;
  returncode: number | null;
  log_tail: string;
}

/** manual_mappings.json against the database (GET /api/data/status). */
export interface DataStatus {
  file: string;
  database: string;
  state: "in_sync" | "line_endings" | "external_edit" | "missing" | "pending" | "not_imported";
  file_sha256: string | null;
  db_export_sha256: string | null;
  last_import: { at: string; file_sha256: string; changed_slots: number; database_backup: string } | null;
}

export interface SlotSummary {
  match: string;
  ce_line_refs: string[];
  audio: string;
  audio_source: string;
  audio_revision: number;
  subtitle: string;
  subtitle_source: string;
  subtitle_revision: number;
  radio: boolean;
  notes: string;
}

/** What importing manual_mappings.json would change (POST /api/data/import/preview). */
export interface ImportPreview {
  file_sha256: string;
  db_export_sha256: string;
  line_endings: "CRLF" | "LF";
  slots_in_file: number;
  slots_in_database: number;
  pins_change: boolean;
  changes: {
    mapping_id: string;
    slot_id: string;
    kind: "added" | "removed" | "changed";
    fields: string[];
    database: SlotSummary | null;
    file: SlotSummary | null;
  }[];
  approvals_added: string[];
  approvals_removed: string[];
}
