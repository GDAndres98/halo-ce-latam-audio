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
  /** /api/slot only: the stored version of that one line (its decision and custom text). Saves send it back, so
   * saves of other lines (another computer) never make this line stale. */
  slot?: string;
}

/** GET /api/session: the address this page came from and who is signed in (docs/remote-access.md). */
export interface SessionInfo {
  listener: "local" | "remote";
  auth_required: boolean;
  authenticated: boolean;
  user: string | null;
  role: "editor" | "admin" | null;
  csrf: string | null;
  /** The host computer's own address (no sign-in; the only place game files can be installed or restored). */
  local_admin: boolean;
  https: boolean;
  /** "cloudflare_access": the address is behind Cloudflare Access, which signs people in (no password form). */
  sso?: "cloudflare_access" | null;
  /** Where signing out goes in that mode (Cloudflare's own logout page). */
  logout_url?: string | null;
  permissions: { edit: boolean; admin: boolean; install: boolean; settings_mcc: boolean };
}

export interface NetworkInfo {
  local_url: string;
  remote: { enabled: boolean; running: boolean; host: string; port: number; tls: boolean };
  urls: { url: string; kind: string; encrypted: boolean }[];
  addresses: { address: string; kind: string }[];
  hostname: string;
  allowed_hosts: string[];
  allowed_origins: string[];
  public_url: string | null;
  config_file: string | null;
  session: { idle_hours: number; max_days: number };
  this_listener: "local" | "remote";
  https: boolean;
  remote_users: string[] | null;
  signed_in: { user: string; from: string | null; last_seen: number }[] | null;
}

/** One message of GET /api/events: lines and files that changed (any computer, any tool). */
export interface ChangeEvent {
  type: "change";
  seq: number;
  slots: string[];
  documents: string[];
  /** Who saved each line, when it was saved through the Studio. */
  by: Record<string, string>;
}

export type MatchStatus = "unreviewed" | "matched" | "no_equivalent" | "deferred";
export type CeLanguage = "Spanish(Mexico)" | "English(US)" | "Spanish(Spain)";
export type AudioSource = "keep_original" | "ce";
export type SubtitleSource = "keep_original" | "ce_locres" | "custom" | "none";
export type ApprovalField = "audio" | "subtitle";
export type ObjectStatus = "draft" | "approved" | "needs_rework";

/** An audio recipe. Speed and per-line gain were removed on 2026-10-09, loudness matching and its limiter
 * on 2026-10-11: the global export gain is the only level setting. None of them must come back. */
export interface AudioEdit {
  trim_start_s: number;
  trim_end_s: number;
  gap_s: number;
  cuts: { start_s: number; end_s: number }[];
  silences: { at_s: number; dur_s: number }[];
  fade_in_ms: number;
  fade_out_ms: number;
  crossfade_ms: number;
  /** Optional radio filter (2026-10-13); null or absent = off. Rendered by scripts/common/audio_edit.py. */
  radio?: RadioFilter | null;
  /** Optional echo (2026-10-13, the "eco" lines); null or absent = off. */
  echo?: EchoEffect | null;
  /** One-off transmission interference (Victor 933's damaged transmission only); null or absent = off. */
  interference?: InterferenceCurve | null;
}

export type InterferenceKind = "partial" | "masked";

/** A point of the interference curve: intensity 0..1 at a time of the original recording (seconds). */
export interface CurvePoint {
  t: number;
  v: number;
}

/** One of the owner's phrase decisions, drawn on the curve's timeline (it never changes the audio by itself). */
export interface InterferenceGuide {
  label: string;
  kind: InterferenceKind;
  start_s: number;
  end_s: number;
}

/** The recipe's interference (scripts/common/interference.py, engine interference/2). */
export interface InterferenceCurve {
  engine?: string;
  points: CurvePoint[];
  guides: InterferenceGuide[];
  flutter_db: number;
  /** The static: made from scratch, or MCC Spain's sample (absent = "mcc"). */
  texture?: "synthetic" | "mcc";
}

/** What the server gives for a line with the one-off treatment (only Victor 933's). */
export interface InterferenceDefaults {
  guides: InterferenceGuide[];
  /** The curve generated from the guides (Reset curve). */
  points: CurvePoint[] | null;
  duration_s: number | null;
  kinds?: Record<InterferenceKind, string>;
  alignment?: { method: string; uncertain: string[] };
  scale: { speech_full: number; partial: number; mask: number; bed: number };
  mcc?: { level: string; spanish: number; english: number | null };
}

/** The MCC original's interference estimate (a visual reference only). */
export interface InterferenceReference {
  frame_s: number;
  values: number[];
  duration_s: number;
  language: "spanish" | "english";
}

export type EchoPreset = "spain" | "english" | "custom";

/** The recipe's echo: a short slap tap and a main echo with feedback, diffusion and damping. */
export interface EchoEffect {
  preset: EchoPreset;
  slap_ms: number;
  /** null = no slap. */
  slap_db: number | null;
  delay_ms: number;
  echo_db: number;
  /** null = a single repeat. */
  feedback_db: number | null;
  diffusion: number;
  /** null = no damping. */
  damping_hz: number | null;
}

export type RadioPreset = "spain" | "english" | "spain_eco" | "english_eco" | "soldier" | "pilot" | "custom";

/** The recipe's radio filter: a band-pass with presence, drive and hiss. `preset` is a label; the numbers render. */
export interface RadioFilter {
  preset: RadioPreset;
  low_hz: number;
  high_hz: number;
  slope_db_oct: 12 | 24 | 36;
  presence_db: number;
  /** Optional presence centre (Hz); absent = the band's geometric centre. */
  presence_hz?: number;
  drive_db: number;
  /** Channel hiss level; null = none. */
  noise_dbfs: number | null;
  /** MCC's Spain radio key-up click before the line and release/squelch after it. Absent = off. */
  clicks?: boolean;
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
  /** Lines with the one-off interference treatment, by CE line ref (only Victor 933's). */
  interference?: Record<string, InterferenceDefaults>;
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
  /** The line's version as loaded (Hashes.slot). When sent, only this line must be unchanged. */
  loaded_slot_sha256?: string;
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
/** How every replacement's level is set at export (a build setting, never part of a mapping). */
export type LevelMode = "global_gain" | "match_spain";

export interface ExportSettings {
  global_gain_db: number;
  level_mode: LevelMode;
  source: string;
  sha256: string | null;
}

/** What a build contains: the Spanish dialogue bank, the SU/SP subtitle tables, or all three. */
export type BuildKind = "audio" | "subtitles" | "both";

/** Counts of a subtitle plan (common/m6_build.subtitle_plan "summary"). */
export interface SubtitleSummary {
  approved_subtitles: number;
  approved_text_changes: number;
  rows: Record<string, number>;
  keys_to_write: number;
  keys_written: Record<string, number>;
  missing_keys: Record<string, number>;
  variable_length: Record<string, number>;
  same_length: Record<string, number>;
  empty_entries: number;
  conflicts: number;
  excluded: number;
}

export interface SubtitleTableInfo {
  candidate: string;
  candidate_sha256: string;
  original_sha256: string;
  entries: number;
  entries_written: number;
  entries_identical_to_before: number;
  size_before: number;
  size_after: number;
}

export interface SubtitleConflict {
  code: string;
  key_hex: string;
  mcc_tag: string;
  slots: string[];
}

export interface ExcludedSubtitle {
  slot_id: string;
  status: string;
  category: "excluded" | "conflict" | "missing_key";
  result: string;
  mcc_tag?: string;
  source?: string;
}

type Dist = { min: number; median: number; max: number; p10?: number; p90?: number } | null;

/** The level settings a build used and what they did (build_manifest.json `level`). */
export interface BuildLevel {
  mode: LevelMode;
  global_gain_db: number | null;
  lines: number;
  /** The gain each replacement actually got (dB). */
  effective_gain_db: Dist;
  /** Lines that got less than asked: the peak rule (global gain) or the 6 dB limiting cap (match Spain). */
  constrained: number;
  fallback: number;
  limiter_max_reduction_db: Dist;
  /** Replacement loudness minus the Spain recording's (dB); negative = quieter than the original game. */
  loudness_vs_spain_db: Dist;
  source: string | null;
}

export interface BuildSummary {
  name: string;
  kind: BuildKind;
  levels: string[];
  built_at: string | null;
  counts: Record<string, number>;
  subtitles: {
    enabled: boolean;
    summary: SubtitleSummary | null;
    tables: Record<string, SubtitleTableInfo> | null;
    warnings: string[];
    conflicts: number;
  };
  failed_checks: string[];
  has_log: boolean;
  validation_ok: boolean | null;
  stale: boolean;
  stale_reasons: string[];
  built_gain_db: number | null;
  level: BuildLevel | null;
  built_from_sha256: string | null;
  candidate_sha256: string | null;
  install_files: { install_rel: string; candidate: string | null; candidate_sha256: string; size: number | null }[];
}

export interface BuildsResponse {
  builds: BuildSummary[];
  decisions_sha256: string | null;
  kinds: BuildKind[];
  /** What is still unverified in the game about rewritten subtitle tables. */
  runtime_note: string;
  /** Playable maps a mission build can target (its folder plus its cinematics). */
  missions: string[];
}

export type BuildScope = "mission" | "levels" | "all_mapped";

/** What a build of a scope would contain (POST /api/builds/preview). Read-only. */
export interface BuildPreview {
  levels: string[];
  scope: string;
  audio: { replace: number; keep_original: number; not_eligible: number; conflicts: number };
  subtitles: SubtitleSummary & { excluded_rows: ExcludedSubtitle[]; conflict_list: SubtitleConflict[] };
}

/** One build in detail (GET /api/builds/detail). */
export interface BuildDetail {
  name: string;
  kind: BuildKind;
  levels: string[];
  subtitles_enabled: boolean;
  summary: SubtitleSummary | null;
  tables: Record<string, SubtitleTableInfo> | null;
  written: { key_hex: string; mcc_tag: string; level: string; slots: string[]; text: string; before: Record<string, string | null> }[];
  excluded: ExcludedSubtitle[];
  conflicts: SubtitleConflict[];
  warnings: string[];
  checks: Record<string, boolean>;
  ok: boolean | null;
  install_files: { install_rel: string; candidate: string; candidate_sha256: string; original_sha256: string; size: number; growth_bytes: number }[];
  not_written: string[];
}

/** One install / restore event from the installer's append-only history. */
export interface DeployEvent {
  at: string;
  action: "install" | "rollback";
  result: "ok" | "failed";
  build: string;
  kind: BuildKind;
  message: string;
  files: { install_rel: string; installed_sha256: string | null; original_sha256: string; candidate_sha256: string }[];
}

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
  /** What the Studio is set to now, and the level settings inside the installed audio build(s). */
  current_level?: { mode: LevelMode; global_gain_db: number };
  installed_level?: (BuildLevel & { build: string; built_at: string | null; matches_current: boolean })[];
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
  kind: BuildKind;
  subtitles: string;
  audio: string;
}

export interface BuildJob {
  id: string;
  kind: "build" | "install" | "restore";
  /** For builds: the scope, the kind and the builder arguments. */
  detail?: Record<string, unknown>;
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
