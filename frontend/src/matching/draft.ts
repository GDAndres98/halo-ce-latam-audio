// The matching rules the screens follow. Pure functions, no Vue, so they can be unit-tested directly.
//
// The Studio never decides a match. Every field in a Draft is set by the user. These functions only
// translate between the stored decision (mappings/manual_mappings.json, shown by /api/slot) and the
// request body /api/save expects. The server still enforces every protection (approved objects are
// read-only, Needs Rework bumps the revision, the hashes must match), so these checks are for usability.

import type {
  AudioEdit,
  CeLanguage,
  MatchStatus,
  SaveAction,
  SaveBody,
  SlotDetail,
  StoredDecision,
  SubtitleSource,
  AudioSource,
  ApprovalField,
} from "../api/types";

/** The editable decision for one MCC line. */
export interface Draft {
  matchStatus: MatchStatus;
  /** Campaign Evolved lines the user associated with this MCC line. */
  ceRefs: string[];
  audioSource: AudioSource;
  /** The CE line used as the replacement. Must be one of ceRefs when audioSource is "ce". */
  audioRef: string | null;
  audioLanguage: CeLanguage;
  edit: AudioEdit;
  subtitleSource: SubtitleSource;
  subtitleRef: string | null;
  subtitleCulture: string;
  customText: string;
  radio: boolean;
  fits: boolean;
  notes: string;
}

export const DEFAULT_LANGUAGE: CeLanguage = "Spanish(Mexico)";

/** An empty recipe. Speed and per-line gain no longer exist (removed 2026-10-09). */
export function defaultEdit(gapS = 0): AudioEdit {
  return {
    trim_start_s: 0,
    trim_end_s: 0,
    gap_s: gapS,
    cuts: [],
    silences: [],
    fade_in_ms: 0,
    fade_out_ms: 0,
    crossfade_ms: 20,
    limiter: true,
    loudness: { mode: "off", offset_db: 0 },
  };
}

/** A stored recipe with every field present: missing fields get the defaults, and a partial loudness
 * setting keeps its mode and gets the default offset. */
function completeEdit(stored: AudioEdit): AudioEdit {
  const edit = editWithoutBinding(stored);
  const defaults = defaultEdit(stored.gap_s ?? 0);
  return { ...defaults, ...edit, loudness: { ...defaults.loudness, ...(edit.loudness ?? {}) } };
}

/** The recipe as the editor works on it. `for_source` records which recording the recipe was made for; the
 * server recomputes it from the audio choice, so it is never sent back. */
function editWithoutBinding(edit: AudioEdit): AudioEdit {
  const copy = JSON.parse(JSON.stringify(edit)) as AudioEdit & { for_source?: unknown };
  delete copy.for_source;
  return copy;
}

/** The draft a page starts from: the stored decision, or an empty one for a line not yet decided. */
export function draftFrom(detail: SlotDetail): Draft {
  const m: StoredDecision | null = detail.mapping;
  const firstSource = m?.audio.sources[0];
  return {
    matchStatus: m?.match.status ?? "unreviewed",
    ceRefs: [...(m?.match.ce_line_refs ?? [])],
    audioSource: m?.audio.source ?? "keep_original",
    audioRef: firstSource?.ce_line_ref ?? null,
    audioLanguage: firstSource?.language ?? DEFAULT_LANGUAGE,
    // The server stores only the fields that were set (a new line has just the trims and gap), so the
    // missing ones are filled with the defaults, as the classic page does.
    edit: m ? completeEdit(m.audio.edit) : defaultEdit(),
    subtitleSource: m?.subtitle.source ?? "keep_original",
    subtitleRef: m?.subtitle.ce_locres?.ce_line_ref ?? null,
    subtitleCulture: m?.subtitle.ce_locres?.culture ?? "es-MX",
    customText: detail.custom_text ?? "",
    radio: m?.radio_effect.needed ?? false,
    fits: m?.different_but_fits?.marked ?? false,
    notes: m?.notes ?? "",
  };
}

/** A stable text form of a draft, used for "has anything changed?" comparisons. */
export function draftKey(draft: Draft): string {
  return JSON.stringify(draft);
}

export function isDirty(draft: Draft, baseline: Draft): boolean {
  return draftKey(draft) !== draftKey(baseline);
}

/** Problems that would make the server refuse the draft. Shown next to the controls, before any request. */
export function draftProblems(draft: Draft): string[] {
  const problems: string[] = [];
  if (draft.audioSource === "ce") {
    if (!draft.audioRef) problems.push("Choose the Campaign Evolved recording to use, or keep Spain's audio.");
    else if (!draft.ceRefs.includes(draft.audioRef)) problems.push("The replacement must be one of the matched lines.");
  }
  if (draft.subtitleSource === "ce_locres" && !draft.subtitleRef) {
    problems.push("Choose a Campaign Evolved subtitle.");
  }
  if (draft.subtitleSource === "custom" && !draft.customText.trim()) {
    problems.push("Write the subtitle text, or choose another subtitle source.");
  }
  return problems;
}

/** Problems for one field only, so the approval button for audio is not blocked by a subtitle issue. */
export function fieldProblems(draft: Draft, field: ApprovalField): string[] {
  return draftProblems(draft).filter((p) =>
    field === "audio" ? /recording|matched lines/.test(p) : /subtitle/i.test(p),
  );
}

export interface ApprovalCheck {
  allowed: boolean;
  reason: string;
}

/** Whether the audio or subtitle decision can be approved right now. Approval is always an explicit
 * action on a saved draft: the user must save first, so what is approved is what they saw. */
export function canApprove(field: ApprovalField, stored: StoredDecision | null, draft: Draft, baseline: Draft): ApprovalCheck {
  const status = stored ? stored[field].status : "draft";
  if (status === "approved") return { allowed: false, reason: "Already approved. Use Needs rework to change it." };
  if (isDirty(draft, baseline)) return { allowed: false, reason: "Save the draft first." };
  const problems = fieldProblems(draft, field);
  if (problems.length) return { allowed: false, reason: problems[0] };
  return { allowed: true, reason: "" };
}

export function canRework(field: ApprovalField, stored: StoredDecision | null): ApprovalCheck {
  if (stored?.[field].status !== "approved") return { allowed: false, reason: "Only an approved decision needs rework." };
  return { allowed: true, reason: "" };
}

/** The body for "Needs rework": only the action, so no other part of the decision is touched. */
export function buildReworkBody(detail: SlotDetail, field: ApprovalField): SaveBody {
  return {
    slot_id: detail.slot_id,
    loaded_sha256: detail.sha256.mappings,
    local_sha256: detail.sha256.local,
    actions: [{ action: "needs_rework", field }],
  };
}

/**
 * The body for a normal save.
 *
 * Rules, each one protecting data the user already has:
 * - An approved object is not sent: approved decisions are read-only until Needs rework.
 * - The audio recipe is sent only when it changed. The server treats a missing recipe as "keep the
 *   stored one", and an identity recipe as "reset", so sending a default would erase a saved trim.
 * - Radio and "different but fits" flags are always sent: they are independent of approvals.
 */
export function buildSaveBody(detail: SlotDetail, draft: Draft, baseline: Draft, actions: SaveAction[] = []): SaveBody {
  const stored = detail.mapping;
  const body: SaveBody = {
    slot_id: detail.slot_id,
    loaded_sha256: detail.sha256.mappings,
    local_sha256: detail.sha256.local,
    match: { status: draft.matchStatus, ce_line_refs: [...draft.ceRefs] },
    radio_effect: { needed: draft.radio },
    different_but_fits: { marked: draft.fits },
    notes: draft.notes,
  };
  if (stored?.audio.status !== "approved") body.audio = audioSection(draft, baseline);
  if (stored?.subtitle.status !== "approved") body.subtitle = subtitleSection(draft);
  if (actions.length) body.actions = actions;
  return body;
}

function audioSection(draft: Draft, baseline: Draft): NonNullable<SaveBody["audio"]> {
  const usesCe = draft.audioSource === "ce" && draft.audioRef !== null;
  const section: NonNullable<SaveBody["audio"]> = {
    source: draft.audioSource,
    sources: usesCe ? [{ ce_line_ref: draft.audioRef as string, language: draft.audioLanguage }] : [],
  };
  if (usesCe && JSON.stringify(draft.edit) !== JSON.stringify(baseline.edit)) {
    section.edit = draft.edit;
  }
  return section;
}

function subtitleSection(draft: Draft): NonNullable<SaveBody["subtitle"]> {
  switch (draft.subtitleSource) {
    case "ce_locres":
      return {
        source: "ce_locres",
        ce_locres: { ce_line_ref: draft.subtitleRef as string, culture: draft.subtitleCulture },
      };
    case "custom":
      return { source: "custom", custom_text: draft.customText.trim() };
    default:
      // keep_original (MCC's own text) and none (intentionally no subtitle) carry no other fields.
      return { source: draft.subtitleSource };
  }
}
