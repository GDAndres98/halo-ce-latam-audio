<script setup lang="ts">
// Non-destructive editing of the replacement recording, on its waveform.
//
// What the user can do: drag across the waveform to select, drag the two handles of the kept part (trims),
// keep or cut the selection (several cuts are allowed), remove cuts, insert silences (at the playhead or the
// start of the selection, or in place of the selection), set fades and match the loudness of Spain's
// recording. Every change goes through editRecipe.ts and can be undone. The result is rendered automatically
// as the build renders it and heard as B under "Listen and compare" (composables/useEditPreview.ts). The original WAV is never changed; the recipe is saved with the audio decision (Save draft), and
// approved audio must be marked Needs rework first (the server refuses the change otherwise).
//
// Speed and per-line gain do not exist here (removed 2026-10-09); volume is the global export gain.

import { computed, ref, watch } from "vue";
import {
  Crop,
  Hourglass,
  Replace,
  RotateCcw,
  Scissors,
  SlidersHorizontal,
  Trash2,
  TrendingDown,
  TrendingUp,
  Undo2,
} from "lucide-vue-next";
import { audioUrl } from "../../api/client";
import type { AudioEdit } from "../../api/types";
import { formatSeconds } from "../../audio/format";
import { useShortcuts } from "../../composables/useShortcuts";
import {
  EditHistory,
  MAX_FADE_MS,
  MAX_SILENCE_MS,
  MIN_SILENCE_MS,
  addCut,
  addSilence,
  editedSeconds,
  fadeSpans,
  keepSpan,
  moveSilence,
  removeCut,
  removeSilence,
  replaceWithSilence,
  resetEdits,
  setFade,
  setKeep,
  setSilenceLength,
  type Span,
} from "../../matching/editRecipe";
import type { Draft } from "../../matching/draft";
import WaveformView from "../waveform/WaveformView.vue";

const props = defineProps<{ draft: Draft; locked: boolean }>();

const replacement = ref<InstanceType<typeof WaveformView> | null>(null);
const duration = ref(0);
const selection = ref<Span | null>(null);
const history = new EditHistory();
const undoDepth = ref(0); // EditHistory is not reactive; this mirrors its depth for the Undo button
const editError = ref("");

const usesCe = computed(() => props.draft.audioSource === "ce" && Boolean(props.draft.audioRef));
const replacementUrl = computed(() =>
  usesCe.value ? audioUrl.ce(props.draft.audioRef as string, props.draft.audioLanguage) : null,
);
const editable = computed(() => usesCe.value && !props.locked);
const canEdit = computed(() => editable.value && duration.value > 0);
const keep = computed<Span | null>(() => (duration.value ? keepSpan(props.draft.edit, duration.value) : null));
const cuts = computed<Span[]>(() => props.draft.edit.cuts.map((c) => ({ start: c.start_s, end: c.end_s })));
const fades = computed(() => fadeSpans(props.draft.edit, duration.value));
const afterEdits = computed(() => (duration.value ? editedSeconds(props.draft.edit, duration.value) : null));
const recipeKey = computed(() => JSON.stringify(props.draft.edit));

// A new recording starts with an empty history.
watch(replacementUrl, () => {
  history.clear();
  undoDepth.value = 0;
  duration.value = 0;
  selection.value = null;
  editError.value = "";
});

/** Applies a recipe change: the current recipe is saved first, so Undo can return to it. */
function applyEdit(next: AudioEdit) {
  if (JSON.stringify(next) === recipeKey.value) return;
  history.push(props.draft.edit);
  undoDepth.value += 1;
  props.draft.edit = next;
  editError.value = "";
}

/** Runs a change; a refused change is explained and leaves the recipe as it was. */
function attempt(change: () => AudioEdit): boolean {
  if (!editable.value) return false;
  try {
    applyEdit(change());
    return true;
  } catch (e) {
    editError.value = e instanceof Error ? e.message : String(e);
    return false;
  }
}

function onKeepChange(span: Span) {
  // A refused drag (it would keep almost nothing) snaps the handles back to the recipe.
  if (!attempt(() => setKeep(props.draft.edit, span, duration.value))) props.draft.edit = { ...props.draft.edit };
}

function keepSelection() {
  const s = selection.value;
  if (!s || !canEdit.value) return;
  if (attempt(() => setKeep(props.draft.edit, s, duration.value))) replacement.value?.clearSelection();
}

function cutSelection() {
  const s = selection.value;
  if (!s || !canEdit.value) return;
  if (attempt(() => addCut(props.draft.edit, s, duration.value))) replacement.value?.clearSelection();
}

function undo() {
  if (!editable.value) return;
  const previous = history.undo();
  if (!previous) return;
  undoDepth.value -= 1;
  props.draft.edit = previous;
  editError.value = "";
}

function reset() {
  attempt(() => resetEdits(props.draft.edit));
}

/** A number field: applies the change, or puts the field back to the recipe's value if it is refused. */
function onNumber(event: Event, change: (value: number) => AudioEdit, current: () => number) {
  const field = event.target as HTMLInputElement;
  const value = Number(field.value);
  if (field.value.trim() === "" || !Number.isFinite(value) || !attempt(() => change(value))) {
    if (field.value.trim() === "" || !Number.isFinite(value)) editError.value = "Enter a number.";
    field.value = String(current());
  }
}

const trimStart = (seconds: number) => setKeep(props.draft.edit, { start: seconds, end: (keep.value as Span).end }, duration.value);
const trimEnd = (seconds: number) =>
  setKeep(props.draft.edit, { start: (keep.value as Span).start, end: duration.value - seconds }, duration.value);

function setLoudnessMode(mode: string) {
  attempt(() => ({ ...props.draft.edit, loudness: { ...props.draft.edit.loudness, mode } }));
}

function setLoudnessOffset(offset: number) {
  if (offset < -12 || offset > 12) throw new Error("the offset must be between −12 and +12 dB");
  return { ...props.draft.edit, loudness: { ...props.draft.edit.loudness, offset_db: Math.round(offset * 10) / 10 } };
}

function setLimiter(on: boolean) {
  attempt(() => ({ ...props.draft.edit, limiter: on }));
}

// ---- Inserted silences. The length is typed in milliseconds; the recipe stores seconds (audio_edit.py).
const silenceMs = ref(300);
const silenceMarkers = computed(() => props.draft.edit.silences.map((s) => ({ at: s.at_s, dur: s.dur_s })));
/** Where Insert silence puts it: the start of the selection, else the playhead. */
const silenceAt = computed(() => selection.value?.start ?? replacement.value?.position ?? 0);

function insertSilence() {
  if (!canEdit.value) return;
  attempt(() => addSilence(props.draft.edit, silenceAt.value, silenceMs.value, duration.value));
}

function replaceSelectionWithSilence() {
  const s = selection.value;
  if (!s || !canEdit.value) return;
  if (attempt(() => replaceWithSilence(props.draft.edit, s, silenceMs.value, duration.value))) {
    replacement.value?.clearSelection();
  }
}

// Editing keys; they only act on an editable recording and never fire while typing in a field.
useShortcuts({
  w: () => replacement.value?.togglePlay(),
  x: cutSelection,
  t: keepSelection,
  "ctrl+z": undo,
});
</script>

<template>
  <section class="block editor" aria-label="Audio editing">
    <header class="block-head">
      <h3><SlidersHorizontal :size="15" aria-hidden="true" /> Audio editing</h3>
      <span v-if="usesCe" class="small muted">Edits are a recipe; the original recording is never changed.</span>
    </header>
    <p v-if="!usesCe" class="note">Editing applies to a Campaign Evolved recording. Choose one to edit it.</p>

    <template v-else>
      <p v-if="locked" class="note">Approved: read-only. Mark the audio Needs rework to change its editing.</p>

      <div class="toolbar" role="toolbar" aria-label="Editing tools">
        <button type="button" class="icon-label" :disabled="!canEdit || !selection" title="Keep only the selection; trim the rest (T)" @click="keepSelection">
          <Crop :size="16" aria-hidden="true" /> Trim to selection
        </button>
        <button type="button" class="icon-label" :disabled="!canEdit || !selection" title="Remove the selection, crossfaded (X)" @click="cutSelection">
          <Scissors :size="16" aria-hidden="true" /> Cut selection
        </button>
        <span class="sep" aria-hidden="true"></span>
        <span class="silence-tools">
          <label class="inline small">Silence (ms)
            <input
              v-model.number="silenceMs"
              type="number" :min="MIN_SILENCE_MS" :max="MAX_SILENCE_MS" step="10"
              :disabled="!canEdit" aria-label="Silence length (ms)"
            />
          </label>
          <button
            type="button" class="icon-label" :disabled="!canEdit"
            :title="`Insert the silence at ${selection ? 'the start of the selection' : 'the playhead'} (${silenceAt.toFixed(3)} s)`"
            data-testid="insert-silence"
            @click="insertSilence"
          >
            <Hourglass :size="16" aria-hidden="true" /> Insert silence
          </button>
          <button
            type="button" class="icon-label" :disabled="!canEdit || !selection"
            title="Remove the selection and put exactly this much silence in its place (set a pause length)"
            @click="replaceSelectionWithSilence"
          >
            <Replace :size="16" aria-hidden="true" /> Replace selection with silence
          </button>
        </span>
        <span class="sep" aria-hidden="true"></span>
        <button type="button" class="icon-label" :disabled="!editable || undoDepth === 0" title="Undo the last change (Ctrl+Z)" @click="undo">
          <Undo2 :size="16" aria-hidden="true" /> Undo
        </button>
        <button type="button" class="icon-label" :disabled="!editable" title="Remove all trims, cuts, silences and fades" @click="reset">
          <RotateCcw :size="16" aria-hidden="true" /> Reset edits
        </button>
      </div>

      <p v-if="editError" class="error small" role="alert">{{ editError }}</p>

      <WaveformView
        ref="replacement"
        :url="replacementUrl"
        label="Replacement — Campaign Evolved LATAM (original timeline)"
        :editable="editable"
        :keep="keep"
        :cuts="cuts"
        :fades="fades"
        :silences="silenceMarkers"
        @duration="(s) => (duration = s)"
        @keep-change="onKeepChange"
        @selection-change="(s) => (selection = s)"
      />
      <p v-if="editable" class="small muted hint">
        Click to move the playhead. Drag across the waveform to select, then trim to it or cut it. Drag the cyan
        handles at the ends to trim. Insert silence places it at the playhead (or the selection's start); green
        markers show the inserted silences. <kbd>W</kbd> play · <kbd>T</kbd> trim · <kbd>X</kbd> cut · <kbd>Ctrl</kbd>+<kbd>Z</kbd> undo.
        The edited result is rendered automatically and heard as B under “Listen and compare”.
      </p>

      <dl class="durations compact">
        <dt>Original</dt><dd class="mono">{{ formatSeconds(duration || null) }}</dd>
        <dt>After edits</dt><dd class="mono" data-testid="after-edits">{{ formatSeconds(afterEdits) }}</dd>
      </dl>

      <fieldset :disabled="locked" class="edit-grid">
        <label>Trim start (s)
          <input
            :value="draft.edit.trim_start_s"
            type="number" min="0" step="0.01" :disabled="!canEdit"
            @change="onNumber($event, trimStart, () => draft.edit.trim_start_s)"
          />
        </label>
        <label>Trim end (s)
          <input
            :value="draft.edit.trim_end_s"
            type="number" min="0" step="0.01" :disabled="!canEdit"
            @change="onNumber($event, trimEnd, () => draft.edit.trim_end_s)"
          />
        </label>
        <label>
          <span><TrendingUp :size="14" aria-hidden="true" /> Fade in (ms)</span>
          <input
            :value="draft.edit.fade_in_ms"
            type="number" min="0" :max="MAX_FADE_MS" step="10" aria-label="Fade in (ms)"
            @change="onNumber($event, (v) => setFade(draft.edit, 'in', v), () => draft.edit.fade_in_ms)"
          />
        </label>
        <label>
          <span><TrendingDown :size="14" aria-hidden="true" /> Fade out (ms)</span>
          <input
            :value="draft.edit.fade_out_ms"
            type="number" min="0" :max="MAX_FADE_MS" step="10" aria-label="Fade out (ms)"
            @change="onNumber($event, (v) => setFade(draft.edit, 'out', v), () => draft.edit.fade_out_ms)"
          />
        </label>
      </fieldset>

      <fieldset :disabled="locked" class="loudness">
        <label class="inline">Loudness
          <select :value="draft.edit.loudness.mode" @change="setLoudnessMode(($event.target as HTMLSelectElement).value)">
            <option value="off">Keep the source level</option>
            <option value="match_mcc">Match Spain's recording</option>
          </select>
        </label>
        <template v-if="draft.edit.loudness.mode === 'match_mcc'">
          <label class="inline">Offset (dB)
            <input
              :value="draft.edit.loudness.offset_db"
              type="number" min="-12" max="12" step="0.5"
              @change="onNumber($event, setLoudnessOffset, () => draft.edit.loudness.offset_db)"
            />
          </label>
          <label class="opt">
            <input :checked="draft.edit.limiter" type="checkbox" @change="setLimiter(($event.target as HTMLInputElement).checked)" />
            Limit peaks (look-ahead limiter at −1 dBFS)
          </label>
        </template>
      </fieldset>

      <div v-if="draft.edit.cuts.length" class="cut-list">
        <p class="small muted">Cuts (times on the original recording)</p>
        <ul>
          <li v-for="(cut, i) in draft.edit.cuts" :key="`${cut.start_s}-${cut.end_s}`" data-testid="cut">
            <Scissors :size="14" aria-hidden="true" />
            <span class="mono small">{{ cut.start_s.toFixed(3) }} – {{ cut.end_s.toFixed(3) }} s</span>
            <span class="small muted">({{ (cut.end_s - cut.start_s).toFixed(3) }} s)</span>
            <button type="button" class="icon-label small-button" :disabled="!editable" :aria-label="`Remove cut ${i + 1}`" @click="attempt(() => removeCut(draft.edit, i))">
              <Trash2 :size="14" aria-hidden="true" /> Remove
            </button>
          </li>
        </ul>
      </div>
      <div v-if="draft.edit.silences.length" class="cut-list silence-list">
        <p class="small muted">Inserted silences (times on the original recording)</p>
        <ul>
          <li v-for="(s, i) in draft.edit.silences" :key="`${s.at_s}-${i}`" data-testid="silence">
            <Hourglass :size="14" aria-hidden="true" />
            <label class="inline small">at (s)
              <input
                :value="s.at_s" type="number" min="0" step="0.01" :disabled="!canEdit" :aria-label="`Position of silence ${i + 1} (s)`"
                @change="onNumber($event, (v) => moveSilence(draft.edit, i, v, duration), () => s.at_s)"
              />
            </label>
            <label class="inline small">length (ms)
              <input
                :value="Math.round(s.dur_s * 1000)" type="number" :min="MIN_SILENCE_MS" :max="MAX_SILENCE_MS" step="10"
                :disabled="!canEdit" :aria-label="`Length of silence ${i + 1} (ms)`"
                @change="onNumber($event, (v) => setSilenceLength(draft.edit, i, v), () => Math.round(s.dur_s * 1000))"
              />
            </label>
            <button type="button" class="icon-label small-button" :disabled="!editable" :aria-label="`Remove silence ${i + 1}`" @click="attempt(() => removeSilence(draft.edit, i))">
              <Trash2 :size="14" aria-hidden="true" /> Remove
            </button>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>
