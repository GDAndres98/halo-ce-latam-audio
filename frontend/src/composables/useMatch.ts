// State of the line being matched: the server's decision, the user's draft, and the actions that save it.
//
// Two copies are kept: `baseline` (what the server holds) and `draft` (what the user is editing).
// An unsaved draft also survives a page reload, for the same stored version of the decision only
// (sessionStorage, per viewer). The server copy is the only one that counts; the session copy only
// protects typing against accidents.

import { reactive, ref, watch } from "vue";
import { api, ApiError } from "../api/client";
import type { ApprovalField, SaveAction, SlotDetail } from "../api/types";
import { buildReworkBody, buildSaveBody, draftFrom, draftKey, isDirty, type Draft } from "../matching/draft";

const sessionKey = (slotId: string) => `studio.draft.${slotId}`;

export function useMatch() {
  const detail = ref<SlotDetail | null>(null);
  const baseline = ref<Draft | null>(null);
  const draft = reactive({} as Draft);
  const loading = ref(false);
  const saving = ref(false);
  const message = ref("");
  const error = ref("");

  /** Takes the server's copy. `keepTyping` leaves the user's draft as it is (after a rework, or when they
   * typed while a request was in flight); otherwise the draft becomes the stored decision. */
  function adopt(next: SlotDetail, keepTyping: boolean) {
    const fresh = draftFrom(next);
    detail.value = next;
    baseline.value = fresh;
    if (!keepTyping) Object.assign(draft, restoreSession(next) ?? fresh);
  }

  async function load(slotId: string) {
    loading.value = true;
    error.value = "";
    message.value = "";
    try {
      adopt(await api.slot(slotId), false);
    } catch (e) {
      error.value = describe(e);
    } finally {
      loading.value = false;
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

  watch(
    () => draftKey(draft),
    () => {
      if (detail.value && dirty()) writeSession(detail.value.slot_id, detail.value.sha256.mappings, draft);
    },
  );

  return { detail, baseline, draft, loading, saving, message, error, load, save, rework, reloadKeepingDraft, dirty };
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

function restoreSession(next: SlotDetail): Draft | null {
  try {
    const raw = sessionStorage.getItem(sessionKey(next.slot_id));
    if (!raw) return null;
    const stored = JSON.parse(raw) as { sha: string; draft: Draft };
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
