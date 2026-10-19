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
  /** Lines muted in game (Mute / No replacement): a subset of no_equivalent, never counted as matched. */
  muted: number;
  muted_approved: number;
  /** Added takes of the level's sounds (docs/added-takes-design.md); never counted as lines or matches. */
  added_takes?: number;
  added_takes_approved?: number;
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
  listener: "local" | "remote" | "public";
  /** The public read-only view (docs/public-access.md): anonymous, no edits, no audio, no downloads. */
  visitor?: boolean;
  /** Where a visitor signs in to edit (the owner's Cloudflare Access protected address). */
  sign_in_url?: string | null;
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
  /** audio: play recordings, waveforms and editor previews; download: save them as files. Older servers send
   * neither (then edit stands for both). */
  permissions: { edit: boolean; admin: boolean; install: boolean; settings_mcc: boolean; audio?: boolean; download?: boolean;
    /** The public view plays the published edited previews of approved lines (docs/public-access.md §2.1). */
    previews?: boolean };
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
/** mute: the line is omitted from gameplay (silence of the original length). */
export type AudioSource = "keep_original" | "ce" | "ce_concat" | "ce_mix" | "mute";
/** Two Campaign Evolved recordings in one replacement (docs/combine-recordings.md). */
export const COMBINED_SOURCES = ["ce_concat", "ce_mix"] as const;
export type CombinedSource = (typeof COMBINED_SOURCES)[number];

/** The recipe of a join (ce_concat: part 1 then part 2, each with its own edits, gap_s between them; negative =
 * they overlap) or an overlay (ce_mix: both at once, the second starting offset_s later). radio / echo apply to
 * the combined result. Rendered by scripts/common/audio_combine.py. */
export interface CombineEdit {
  engine?: "audio-combine/1";
  mode: "concat" | "mix";
  parts?: [AudioEdit, AudioEdit];
  gap_s?: number;
  offset_s?: number;
  radio?: RadioFilter | null;
  echo?: EchoEffect | null;
}
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
    /** Why the owner muted the line (only when source is "mute"). */
    mute_reason?: string;
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
  /** Added takes of this line's sound (all its takes share them). */
  added_takes?: number;
  /** The line's sound plays its own take set (this Spain take is removed in the build): its takes' state. */
  own_set?: { takes: number; approved: number; needs_rework: number } | null;
  /** The line's decision is archived in its sound's replacement-set record; its reminders are shown (radio_effect /
   * needs_recording above come from it). */
  archived_reminders?: boolean;
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

/** The public view only: whether this line's published edited preview can be played, and why not. */
export interface PublicPreview {
  available: boolean;
  url: string | null;
  reason: string | null;
}

export interface SlotDetail {
  public_preview?: PublicPreview;
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
  /** The line's sound: its Spain takes and its added takes. */
  sound?: SoundTakes;
  sha256: Hashes;
}

/** One added take of a sound (manual_mappings.json added_takes). */
export interface AddedTake {
  take_id: string;
  mcc_tag: string;
  position: number;
  audio: StoredDecision["audio"];
  radio_effect: { needed: boolean; set_at: string | null; revision: number };
  notes?: string;
  /** Approved, but the recording or the sound's Spain takes changed since. */
  drift: boolean;
  edit_summary: string;
  edited: boolean;
  line: CeLine | null;
  /** Created by a staged conversion: not built until the sound is switched to its replacement set. */
  staged?: boolean;
}

/** How a sound is handled (docs/replacement-set-conversion.md). */
export type SoundMode = "per_take" | "spain_plus_added" | "replacement_set" | "replacement_set_staged";

/** The record a replacement set keeps of the decisions it replaced (own_sets[].provenance, summarised). */
export interface SetConversion {
  state: "staged" | "active";
  /** conversion: made from the sound's line decisions; replace: the 4th audio option (new recordings). */
  kind: "conversion" | "replace";
  record_id: string;
  created_at: string;
  activated_at: string | null;
  replaced_decisions: number;
  takes: { take_id: string; origin: "created" | "existing"; from_mapping_ids: string[] }[];
  acknowledged: string[];
  decisions: { mapping_id: string; slot_id: string; audio: string; audio_source: string; audio_ref: string | null;
               subtitle: string; notes: string }[];
}

export type IssueSeverity = "blocked" | "review" | "info";
export interface ConversionIssue { code: string; severity: IssueSeverity; message: string; slot_id?: string; detail?: string }

export interface BuildView {
  spain: { slot_id: string; action: string; reason: string; ce_line_ref: string | null }[];
  inserts?: { take_id: string; action: string; reason: string; ce_line_ref: string | null }[];
  takes_in_game: number;
  replaced?: number;
  muted?: number;
  spain_kept?: number;
  dropped: number;
  inserted: number;
  note?: string;
}

export type ConversionStatus = "ready" | "review" | "blocked" | "ineligible" | "active" | "staged" | "nothing_to_convert";

/** GET /api/takes/convert/preview: what converting one sound would do. Read-only. */
export interface ConversionPreview {
  mcc_tag: string;
  level: string;
  tag_name: string;
  original_takes: number;
  /** The sound's first Spain take (to open it in Matching). */
  first_slot_id: string;
  /** An own set on a sound with one Spain take (listed, counted apart from the multi-take sounds). */
  single_take?: boolean;
  /** How many takes the set has (proposed, staged or in force). */
  replacement_takes?: number;
  mode: SoundMode;
  status: ConversionStatus;
  eligible: boolean;
  reason: string;
  /** Names the exact inputs it was made from; staging refuses a stale one. */
  token: string;
  sound_version?: string;
  summary: string;
  review_codes?: string[];
  issues: ConversionIssue[];
  sources?: { slot_id: string; ordinal: number; spanish_index: number; duration_s: number; take: string | null;
              codes: string[];
              decision: { mapping_id: string; match: string; match_refs: string[]; audio: string; audio_source: string;
                          audio_refs: string[]; edit_summary: string | null; subtitle: string; subtitle_source: string;
                          radio_effect: boolean; different_but_fits: boolean; needs_recording: boolean;
                          notes: string } | null }[];
  existing_takes?: { take_id: string; position: number; status: string; ce_line_ref: string | null }[];
  proposed?: { origin: "existing" | "new"; take_id: string | null; position: number; ce_line_ref: string;
               language: string; edit_summary: string | null; status: string; radio_effect: boolean; notes: string;
               from_mapping_ids: string[]; from_slots: string[] }[];
  build_now?: BuildView;
  build_staged?: BuildView;
  build_after?: BuildView;
  takes_total?: number;
  takes_approved?: number;
}

export interface ConversionInventory {
  sounds: ConversionPreview[];
  counts: Record<string, number>;
  sha256: string;
}

export interface ConversionResponse {
  saved: boolean;
  message?: string;
  sha256?: string;
  sound?: SoundTakes;
  staged?: { mcc_tag: string; record_id: string; created: string[] }[];
  already?: string[];
  switched?: { mcc_tag: string; record_id: string; reworked: string[] }[];
  restored?: string[];
  renamed?: Record<string, string>;
  reworked?: string[];
  removed_takes?: string[];
  kept_takes?: string[];
  custom_text_changed?: string[];
  record_id?: string;
  /** approve_unchanged: the takes approved. revert: what came back. */
  approved?: string[];
  restore?: { mapping_id: string; slot_id: string; audio: string; subtitle: string }[];
  local_restored?: string[];
  notes?: string[];
}

/** A sound (tag) as the takes section shows it (GET /api/slot -> sound, and every takes request). */
export interface SoundTakes {
  mcc_tag: string;
  level: string;
  tag_name: string;
  /** Owner rule 2026-10-17: only mono sounds without a subtitle entry may get added takes. */
  allowed: boolean;
  reason: string;
  spain_takes: { slot_id: string; ordinal: number; duration_s: number; spanish_index: number;
                 decision: { match: string; audio: string; subtitle: string; audio_source: string | null } | null;
                 audio_ref: string | null; mapping_id: string | null }[];
  added_takes: AddedTake[];
  total_takes: number;
  warn_above: number;
  /** The version the next takes request must name (loaded_takes_sha256). */
  version: string;
  /** Every line decision, take and set of the sound: conversions and the 4th audio option name it. */
  sound_version: string;
  mode: SoundMode;
  /** Own take set (docs/custom-take-set-design.md): when on, the sound plays only its added takes. Null while a
   * conversion is only staged. */
  own_set: { mcc_tag: string; set_at: string } | null;
  /** The record of what the set replaced (a staged or active conversion, or the 4th option). */
  conversion: SetConversion | null;
  /** Reminders of the archived line decisions of a set in force (needs a new recording, needs radio effect, notes). */
  reminders: { slot_id: string; mapping_id: string; needs_recording: boolean; radio_effect: boolean; notes: string }[];
}

/** GET /api/takes/convert/approvable: the staged takes "Approve unchanged converted takes" would approve. */
export interface ApprovableTakes {
  mcc_tag: string;
  record_id: string;
  sound_version: string;
  included: ApprovableTake[];
  excluded: (ApprovableTake & { reasons: string[] })[];
}
export interface ApprovableTake {
  take_id: string;
  ce_line_ref: string | null;
  language: string | null;
  edit_summary: string | null;
  sources: { mapping_id: string; slot_id: string | null; audio: string | null; approved_at: string | null;
             ce_line_ref: string | null }[];
}

/** GET /api/takes/convert/revert_preview: what Undo would do, and what stops it. */
export interface RevertPreview {
  mcc_tag: string;
  record_id: string;
  kind: "conversion" | "replace";
  restore: { mapping_id: string; slot_id: string; audio: string; subtitle: string }[];
  drifted: string[];
  remove_takes: string[];
  keep_takes: string[];
  notes: string[];
  local_restore: { custom_subtitles: Record<string, unknown>; user_recordings: Record<string, unknown> };
  conflicts: { code: string; detail: string }[];
  rework_drifted: boolean;
  sound_version: string;
  token: string;
}

export interface TakeResponse {
  saved: boolean;
  message?: string;
  sound: SoundTakes;
  take_id?: string | null;
  /** own_set_on only: the decisions removed, and the approved ones marked Needs rework first. */
  cleared?: string[];
  reworked?: string[];
  /** add_many only: the new take IDs and the recordings skipped (already a take, or listed twice). */
  added?: string[];
  skipped?: string[];
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
    /** Required when source is "mute". */
    mute_reason?: string;
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
/** "experiment": a prepared test (e.g. the permutation experiment), installed and restored like a build but never
 * started from the page and not made from the mappings. */
export type BuildKind = "audio" | "subtitles" | "both" | "experiment";

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
  audio: { replace: number; keep_original: number; mute: number; insert?: number; insert_not_eligible?: number;
           not_eligible: number; conflicts: number };
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
  /** Builds with only some of their files installed (an interrupted install); Restore covers them too. */
  partial_builds?: string[];
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
