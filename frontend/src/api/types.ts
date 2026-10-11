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
  sha256: { mappings: string; local: string; progress: string };
}

export interface SlotDecision {
  match: string;
  audio: string;
  subtitle: string;
  audio_source: string | null;
  subtitle_source: string | null;
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
  en_duration_s: number;
  channels: number;
  flags: string[];
  decision: SlotDecision;
  radio_effect: boolean;
  different_but_fits: boolean;
  edited: boolean;
}

export interface SlotsResponse {
  level: string;
  slots: SlotRow[];
  total: number;
  truncated: boolean;
  progress: LevelProgress;
  sha256: { mappings: string; local: string; progress: string };
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

export interface SlotDetail {
  slot_id: string;
  level: string;
  mcc_tag: string;
  tag_name: string;
  kind: string;
  speaker_from_name: string;
  spanish: SpanishSample;
  english: EnglishSample[];
  mcc_subtitles: Record<string, string | null>;
  mapping: {
    mapping_id: string;
    match: { status: string; ce_line_refs: string[] };
    audio: { status: string; source: string };
    subtitle: { status: string; source: string };
    radio_effect: { needed: boolean };
    notes: string;
  } | null;
  ce_missions: string[];
}

export interface BuildSummary {
  name: string;
  levels: string[];
  built_at: string | null;
  counts: Record<string, number>;
  subtitles: Record<string, unknown>;
  validation_ok: boolean | null;
  stale: boolean;
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
