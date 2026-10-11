// State of the line being matched: the server's decision, the user's draft, and the actions that save it.
//
// Two copies are kept: `baseline` (what the server holds) and `draft` (what the user is editing).
// An unsaved draft also survives a page reload, for the same stored version of the decision only
// (sessionStorage, per viewer). The server copy is the only one that counts; the session copy only
// protects typing against accidents.
//
// The audio and subtitle decisions are edited together and saved by one request (the server writes both
// atomically), so a subtitle can be chosen for a recording that is not saved yet. `lines` holds the
// Campaign Evolved lines of the draft, saved or not, so their subtitles can be shown and chosen.

import { reactive, ref, watch } from "vue";
import { api, ApiError } from "../api/client";
import type { ApprovalField, CeLine, SaveAction, SaveResponse, SlotDetail } from "../api/types";
import {
  buildReworkBody,
  buildSaveBody,
  completeDraft,
  draftFrom,
  draftKey,
  isDirty,
  proposeSubtitle,
  type Draft,
  type SubtitleProposal,
} from "../matching/draft";

const sessionKey = (slotId: string) => `studio.draft.${slotId}`;

export function useMatch() {
  const detail = ref<SlotDetail | null>(null);
  const baseline = ref<Draft | null>(null);
  const draft = reactive({} as Draft);
  const loading = ref(false);
  const saving = ref(false);
  const message = ref("");
  const error = ref("");
  /** Campaign Evolved lines by ref: the saved matches (from /api/slot) and recordings chosen since. */
  const lines = reactive(new Map<string, CeLine>());
  const pendingLines = new Map<string, Promise<CeLine | null>>();
  /** The CE line whose subtitle was offered when its recording was chosen (unsaved), and the outcome. */
  const proposedSubtitle = ref<string | null>(null);
  const proposal = ref<SubtitleProposal | null>(null);
  // Called with the server's answer after every successful save or rework (the list updates that row).
  const savedListeners: ((response: SaveResponse) => void)[] = [];
  const onSaved = (listener: (response: SaveResponse) => void) => savedListeners.push(listener);

  /** Takes the server's copy. `keepTyping` leaves the user's draft as it is (after a rework, or when they
   * typed while a request was in flight); otherwise the draft becomes the stored decision. */
  function adopt(next: SlotDetail, keepTyping: boolean) {
    const fresh = draftFrom(next);
    detail.value = next;
    baseline.value = fresh;
    next.matched_lines.forEach((line) => lines.set(line.ce_line_ref, line));
    if (!keepTyping) {
      const restored = restoreSession(next);
      Object.assign(draft, restored ? completeDraft(restored, fresh) : fresh);
      // What is shown now is saved (or the user's own restored draft): nothing is a proposal any more.
      proposedSubtitle.value = null;
      proposal.value = null;
    }
  }

  /** The CE line with its subtitles, from the cache or /api/ce_line. Null when it cannot be read. */
  function ensureLine(ref: string): Promise<CeLine | null> {
    const known = lines.get(ref);
    if (known) return Promise.resolve(known);
    let pending = pendingLines.get(ref);
    if (!pending) {
      pending = api
        .ceLine(ref)
        .then((line) => {
          lines.set(ref, line);
          return line;
        })
        .catch(() => null)
        .finally(() => pendingLines.delete(ref));
      pendingLines.set(ref, pending);
    }
    return pending;
  }

  /**
   * The user chose a Campaign Evolved recording as the replacement (always an explicit action). The
   * recording's LATAM subtitle is then offered as the subtitle, unsaved, unless the user already decided
   * the subtitle (see proposeSubtitle). Returns false when the audio is approved and cannot change.
   */
  async function chooseRecording(ref: string): Promise<boolean> {
    if (!detail.value || !baseline.value) return false;
    if (detail.value.mapping?.audio.status === "approved") {
      error.value = "The audio decision is approved. Mark it Needs rework before choosing another recording.";
      return false;
    }
    draft.audioSource = "ce";
    draft.audioRef = ref;
    if (!draft.ceRefs.includes(ref)) draft.ceRefs.push(ref);
    draft.matchStatus = "matched";
    const slotId = detail.value.slot_id;
    const line = await ensureLine(ref);
    // The user may have moved on while the line was read: propose only for the choice still on screen.
    if (detail.value?.slot_id !== slotId || draft.audioRef !== ref || !baseline.value) return true;
    const outcome = proposeSubtitle(draft, baseline.value, detail.value.mapping, line, proposedSubtitle.value);
    if (outcome === "proposed") proposedSubtitle.value = ref;
    else if (outcome === "missing") proposedSubtitle.value = null;
    proposal.value = outcome;
    return true;
  }

  /** Removes a CE line from the match. A replacement or subtitle that used it goes back to the default. */
  function removeMatch(ref: string) {
    draft.ceRefs = draft.ceRefs.filter((r) => r !== ref);
    if (draft.audioRef === ref) {
      draft.audioRef = null;
      draft.audioSource = "keep_original";
    }
    if (draft.subtitleSource === "ce_locres" && draft.subtitleRef === ref && detail.value?.mapping?.subtitle.status !== "approved") {
      draft.subtitleSource = "keep_original";
      draft.subtitleRef = null;
    }
    if (proposedSubtitle.value === ref) proposedSubtitle.value = null;
  }

  // Lines selected in quick succession: only the answer for the latest selection is shown (an older answer
  // arriving late would otherwise put another line's decision under the selected key).
  let latestLoad = 0;

  async function load(slotId: string) {
    const request = ++latestLoad;
    loading.value = true;
    error.value = "";
    message.value = "";
    try {
      const next = await api.slot(slotId);
      if (request === latestLoad) adopt(next, false);
    } catch (e) {
      if (request === latestLoad) error.value = describe(e);
    } finally {
      if (request === latestLoad) loading.value = false;
    }
  }

  const dirty = () => (baseline.value ? isDirty(draft, baseline.value) : false);

  /** Saves the draft and any approval actions in one request. On failure nothing is lost: the draft
   * stays exactly as the user left it. */
  async function save(actions: SaveAction[] = []): Promise<boolean> {
    if (!detail.value || !baseline.value) return false;
    const slotId = detail.value.slot_id;
    const sentKey = draftKey(draft);
    saving.value = true;
    error.value = "";
    try {
      const response = await api.save(buildSaveBody(detail.value, draft, baseline.value, actions));
      message.value = response.saved ? savedMessage(actions) : (response.message ?? "Nothing changed.");
      adopt(response.slot, draftKey(draft) !== sentKey);
      forgetSession(slotId);
      savedListeners.forEach((listener) => listener(response));
      return true;
    } catch (e) {
      error.value = describe(e);
      return false;
    } finally {
      saving.value = false;
    }
  }

  /** Sends an approved decision back to rework. Only that field is touched; the draft is kept. */
  async function rework(field: ApprovalField): Promise<boolean> {
    if (!detail.value) return false;
    saving.value = true;
    error.value = "";
    try {
      const response = await api.save(buildReworkBody(detail.value, field));
      message.value = `${field === "audio" ? "Audio" : "Subtitle"} marked Needs rework. Change it, then save and approve again.`;
      adopt(response.slot, true);
      savedListeners.forEach((listener) => listener(response));
      return true;
    } catch (e) {
      error.value = describe(e);
      return false;
    } finally {
      saving.value = false;
    }
  }

  /** After a conflict (409): fetch the newer decision, keep the user's draft, and ask them to check it. */
  async function reloadKeepingDraft(): Promise<void> {
    if (!detail.value) return;
    try {
      adopt(await api.slot(detail.value.slot_id), true);
      error.value = "The line changed elsewhere. Your edits are kept: check them, then save again.";
    } catch (e) {
      error.value = describe(e);
    }
  }

  // Recordings restored from a session draft also need their subtitles.
  watch(
    () => [...(draft.ceRefs ?? [])],
    (refs) => refs.forEach((ref) => void ensureLine(ref)),
  );

  watch(
    () => draftKey(draft),
    () => {
      if (detail.value && dirty()) writeSession(detail.value.slot_id, detail.value.sha256.mappings, draft);
    },
  );

  return {
    detail,
    baseline,
    draft,
    lines,
    proposedSubtitle,
    proposal,
    loading,
    saving,
    message,
    error,
    load,
    save,
    rework,
    reloadKeepingDraft,
    dirty,
    onSaved,
    chooseRecording,
    removeMatch,
  };
}

/** The object returned by useMatch(), passed to the components of the matching workspace. */
export type MatchState = ReturnType<typeof useMatch>;

function savedMessage(actions: SaveAction[]): string {
  if (!actions.length) return "Draft saved.";
  const names = actions.map((a) => `${a.action === "approve" ? "approved" : "marked for rework"} ${a.field}`);
  return `Saved; ${names.join(", ")}.`;
}

function describe(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return `${e.message} Nothing was written.`;
  return e instanceof Error ? e.message : String(e);
}

function writeSession(slotId: string, sha: string, draft: Draft) {
  try {
    sessionStorage.setItem(sessionKey(slotId), JSON.stringify({ sha, draft }));
  } catch {
    // Private windows and full storage: the draft is simply not remembered across reloads.
  }
}

function restoreSession(next: SlotDetail): Partial<Draft> | null {
  try {
    const raw = sessionStorage.getItem(sessionKey(next.slot_id));
    if (!raw) return null;
    const stored = JSON.parse(raw) as { sha: string; draft: Partial<Draft> };
    return stored.sha === next.sha256.mappings ? stored.draft : null;
  } catch {
    return null;
  }
}

function forgetSession(slotId: string) {
  try {
    sessionStorage.removeItem(sessionKey(slotId));
  } catch {
    // Nothing to forget when storage is unavailable.
  }
}
