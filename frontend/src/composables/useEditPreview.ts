// The edited replacement, rendered automatically for "Listen and compare".
//
// Whenever the chosen recording or its recipe changes, the recording is rendered again through the same
// endpoint as before (/api/edit/preview, which renders exactly as the build does). Recipe changes wait for
// the editing to pause; choosing a recording renders at once. A newer change cancels the request in flight,
// and an answer that arrives late is ignored.
//
// Only a preview whose key matches the current choice and recipe is offered (`current`): an outdated
// preview is never played as if it reflected the current edits. Nothing here plays audio.

import { computed, onScopeDispose, ref, watch } from "vue";
import { api, ApiError } from "../api/client";
import type { AudioEdit, CeLanguage } from "../api/types";
import type { MatchState } from "./useMatch";

export interface RenderedPreview {
  /** What the preview was rendered from (slot, recording, language and recipe). */
  key: string;
  edited: string;
  encoded: string;
  stats: Record<string, number>;
}

interface PreviewRequest {
  slot_id: string;
  ce_line_ref: string;
  language: CeLanguage;
  edit: AudioEdit;
}

/** How long the recipe must stay unchanged before it is rendered (dragging a handle changes it often). */
export const PREVIEW_DELAY_MS = 450;

export function useEditPreview(match: MatchState, delayMs = PREVIEW_DELAY_MS) {
  const rendered = ref<RenderedPreview | null>(null);
  const rendering = ref(false);
  const errors = ref<string[]>([]);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | null = null;
  let sequence = 0;

  /** What should be rendered now, or null when there is nothing to render. */
  const request = computed<PreviewRequest | null>(() => {
    const detail = match.detail.value;
    const draft = match.draft;
    if (!detail || detail.edit?.available === false) return null;
    if (draft.audioSource !== "ce" || !draft.audioRef) return null;
    return { slot_id: detail.slot_id, ce_line_ref: draft.audioRef, language: draft.audioLanguage, edit: draft.edit };
  });
  const key = computed(() => (request.value ? JSON.stringify(request.value) : null));
  /** The preview of the current choice and recipe; null while it is being rendered or after an error. */
  const current = computed(() => (rendered.value && rendered.value.key === key.value ? rendered.value : null));

  function cancel() {
    clearTimeout(timer);
    controller?.abort();
    controller = null;
  }

  async function render(body: PreviewRequest, bodyKey: string, mine: number) {
    controller = new AbortController();
    try {
      const result = await api.editPreview(body, controller.signal);
      if (mine !== sequence) return;
      rendered.value = { key: bodyKey, edited: result.urls.edited, encoded: result.urls.encoded, stats: result.stats };
    } catch (e) {
      if (mine !== sequence || (e instanceof DOMException && e.name === "AbortError")) return;
      errors.value = e instanceof ApiError && e.details.length ? e.details : [e instanceof Error ? e.message : String(e)];
    } finally {
      if (mine === sequence) rendering.value = false;
    }
  }

  watch(
    key,
    (next, previous) => {
      cancel();
      const mine = ++sequence;
      errors.value = [];
      if (!next || !request.value) {
        rendering.value = false;
        return;
      }
      if (rendered.value?.key === next) {
        rendering.value = false; // back to a recipe already rendered (Undo, for example)
        return;
      }
      rendering.value = true;
      const body = JSON.parse(next) as PreviewRequest;
      // Only a recipe change waits: a new line or recording is rendered at once.
      const sameRecording =
        previous !== null && previous !== undefined && sourceOf(JSON.parse(previous)) === sourceOf(body);
      timer = setTimeout(() => void render(body, next, mine), sameRecording ? delayMs : 0);
    },
    { immediate: true },
  );

  onScopeDispose(cancel);

  return { current, rendering, errors, key };
}

const sourceOf = (r: PreviewRequest) => `${r.slot_id}|${r.ce_line_ref}|${r.language}`;

export type EditPreviewState = ReturnType<typeof useEditPreview>;
