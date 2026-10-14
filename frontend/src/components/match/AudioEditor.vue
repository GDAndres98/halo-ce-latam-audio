<script setup lang="ts">
// Non-destructive editing of the replacement recording, on its waveform.
//
// What the user can do: drag across the waveform to select, drag the two handles of the kept part (trims),
// keep or cut the selection (several cuts are allowed), remove cuts, insert silences (at the playhead or the
// start of the selection, or in place of the selection), set fades and a radio filter (presets fitted from the
// MCC radio lines, docs/radio-filter.md). There is no level control here: the
// global export gain (Build & Test) is the only level setting. Every change goes through editRecipe.ts and can be undone. The result is rendered automatically
// as the build renders it and heard as B under "Listen and compare" (composables/useEditPreview.ts). The original WAV is never changed; the recipe is saved with the audio decision (Save draft), and
// approved audio must be marked Needs rework first (the server refuses the change otherwise).
//
// Speed and per-line gain do not exist here (removed 2026-10-09); volume is the global export gain.
//
// On a phone or tablet the editor can fill the screen ("Full screen"): the same component, only restyled, so
// nothing reloads and the undo history stays. There the selection can also be typed in (start and end, in
// seconds) and the original and the edited result can be played without leaving the editor.

import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  Crop,
  Maximize2,
  Minimize2,
  Hourglass,
  Play,
  Radio,
  Waves,
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
import AudioButton from "../AudioButton.vue";
import type { AudioEdit, CurvePoint, EchoPreset, InterferenceDefaults, RadioFilter, RadioPreset } from "../../api/types";
import { formatSeconds } from "../../audio/format";
import { useShortcuts } from "../../composables/useShortcuts";
import {
  EditHistory,
  MAX_FADE_MS,
  MAX_SILENCE_MS,
  MIN_SILENCE_MS,
  DEFAULT_HISS_DBFS,
  ECHO_DEFAULTS,
  ECHO_LIMITS,
  RADIO_LIMITS,
  RADIO_SLOPES,
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
  setRadioPreset,
  setRadioValue,
  setEchoPreset,
  setEchoValue,
  setCurvePoints,
  setFlutter,
  setTexture,
  setInterferenceCurve,
  setSilenceLength,
  type Span,
} from "../../matching/editRecipe";
import type { Draft } from "../../matching/draft";
import WaveformView from "../waveform/WaveformView.vue";
import InterferenceLane from "./InterferenceLane.vue";

const props = defineProps<{
  draft: Draft;
  locked: boolean;
  interference?: InterferenceDefaults | null;
  slotId?: string;
  /** Spain's original and the edited result (null while it renders), playable from the full-screen editor. */
  originalUrl?: string | null;
  previewUrl?: string | null;
}>();

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

// ---- Radio filter: a preset, or its values one by one (any change makes it "custom"). Undoable like the rest.
function onRadioPreset(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  attempt(() => setRadioPreset(props.draft.edit, value === "off" ? null : (value as RadioPreset)));
}

function onRadioSlope(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value) as RadioFilter["slope_db_oct"];
  attempt(() => setRadioValue(props.draft.edit, "slope_db_oct", value));
}

// ---- Echo: a preset, or its values one by one (any change makes it "custom").
function onEchoPreset(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  attempt(() => setEchoPreset(props.draft.edit, value === "off" ? null : (value as EchoPreset)));
}

/** The optional echo values (repeats, damping, slap): a checkbox switches them on at a default, or off (null). */
function onEchoOptional(event: Event, key: "feedback_db" | "damping_hz" | "slap_db") {
  const on = (event.target as HTMLInputElement).checked;
  attempt(() => setEchoValue(props.draft.edit, key, on ? ECHO_DEFAULTS[key] : null));
}

/** Victor 933 only: the curve generated from the phrase guides (added, or restored by Reset curve). */
function applyDefaultCurve() {
  const info = props.interference;
  if (!info?.points) return;
  const current = props.draft.edit.interference;
  attempt(() =>
    setInterferenceCurve(props.draft.edit, {
      guides: current?.guides ?? info.guides,
      points: info.points as CurvePoint[],
      flutter_db: current?.flutter_db ?? 2.5,
      texture: current?.texture ?? "synthetic",
    }),
  );
}

function onClicksToggle(event: Event) {
  const on = (event.target as HTMLInputElement).checked;
  attempt(() => setRadioValue(props.draft.edit, "clicks", on));
}

function onHissToggle(event: Event) {
  const on = (event.target as HTMLInputElement).checked;
  attempt(() => setRadioValue(props.draft.edit, "noise_dbfs", on ? DEFAULT_HISS_DBFS : null));
}

// ---- Full screen (phones and tablets). The page behind it does not scroll while it is open.
const expanded = ref(false);
function setExpanded(on: boolean) {
  expanded.value = on;
  document.documentElement.classList.toggle("editor-expanded", on);
}
onBeforeUnmount(() => document.documentElement.classList.remove("editor-expanded"));

/** A selection edge typed in (seconds). The other edge stays; a refused value puts the field back. */
function onSelectionField(event: Event, edge: "start" | "end") {
  const field = event.target as HTMLInputElement;
  const value = Number(field.value);
  const current = selection.value ?? { start: replacement.value?.position ?? 0, end: duration.value };
  if (field.value.trim() !== "" && Number.isFinite(value)) {
    replacement.value?.select(
      edge === "start"
        ? { start: value, end: Math.max(current.end, value + 0.05) }
        : { start: Math.min(current.start, value - 0.05), end: value },
    );
  }
  field.value = selection.value ? String(selection.value[edge]) : "";
}

// Editing keys; they only act on an editable recording and never fire while typing in a field.
useShortcuts({
  w: () => replacement.value?.togglePlay(),
  x: cutSelection,
  t: keepSelection,
  "ctrl+z": undo,
  escape: () => expanded.value && setExpanded(false),
});
</script>

<template>
  <section class="block editor" :class="{ expanded }" aria-label="Audio editing" data-section="editor">
    <header class="block-head">
      <h3><SlidersHorizontal :size="15" aria-hidden="true" /> Audio editing</h3>
      <span v-if="usesCe" class="small muted editor-note">Edits are a recipe; the original recording is never changed.</span>
      <button
        v-if="usesCe"
        type="button" class="icon-label touch-only expand-editor" :aria-pressed="expanded" data-testid="expand-editor"
        @click="setExpanded(!expanded)"
      >
        <Minimize2 v-if="expanded" :size="16" aria-hidden="true" />
        <Maximize2 v-else :size="16" aria-hidden="true" />
        {{ expanded ? "Done" : "Full screen" }}
      </button>
    </header>
    <div v-if="expanded" class="expanded-listen" role="group" aria-label="Listen while editing">
      <AudioButton v-if="originalUrl" :url="originalUrl" label="Original" title="Spain's original recording" />
      <AudioButton v-if="previewUrl" :url="previewUrl" label="Edited result" title="The edited replacement, as the build renders it" />
      <span v-else class="small muted">Rendering the edited result…</span>
    </div>
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
      <div v-if="editable" class="selection-fields" :class="{ shown: expanded }" data-testid="selection-fields">
        <label>Selection start (s)
          <input
            :value="selection?.start ?? ''" type="number" inputmode="decimal" min="0" step="0.01" :disabled="!canEdit"
            aria-label="Selection start (s)" @change="onSelectionField($event, 'start')"
          />
        </label>
        <label>Selection end (s)
          <input
            :value="selection?.end ?? ''" type="number" inputmode="decimal" min="0" step="0.01" :disabled="!canEdit"
            aria-label="Selection end (s)" @change="onSelectionField($event, 'end')"
          />
        </label>
      </div>
      <p v-if="editable" class="small muted hint touch-only">
        Tap to move the playhead. Drag sideways to select (swipe up or down to scroll the page), then trim to it or
        cut it; the selection can also be typed in above. Drag the wide cyan handles to trim. Zoomed in, switch
        Select / Pan to scroll along the recording.
      </p>
      <p v-if="editable" class="small muted hint pointer-only">
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

      <section class="radio-filter" aria-label="Radio filter" data-testid="radio-filter">
        <header class="radio-head">
          <h4><Radio :size="14" aria-hidden="true" /> Radio filter</h4>
          <span v-if="draft.radio && !draft.edit.radio" class="small warn">This line is flagged “Needs radio effect”.</span>
          <span v-else class="small muted">Heard in the automatic preview (B). Applied after the edits, before the level.</span>
        </header>
        <fieldset :disabled="locked" class="edit-grid">
          <label>Preset
            <select :value="draft.edit.radio?.preset ?? 'off'" :disabled="!canEdit" aria-label="Radio filter preset" @change="onRadioPreset">
              <option value="off">Off</option>
              <option value="spain">Spain radio (MCC Spain lines)</option>
              <option value="english">English radio (MCC English lines)</option>
              <option value="spain_eco">Spain intercom (eco lines)</option>
              <option value="english_eco">English intercom (eco lines)</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <template v-if="draft.edit.radio">
            <label>Low cut (Hz)
              <input
                :value="draft.edit.radio.low_hz" type="number" :min="RADIO_LIMITS.low_hz[0]" :max="RADIO_LIMITS.low_hz[1]" step="50"
                :disabled="!canEdit" aria-label="Radio low cut (Hz)"
                @change="onNumber($event, (v) => setRadioValue(draft.edit, 'low_hz', v), () => draft.edit.radio?.low_hz ?? 0)"
              />
            </label>
            <label>High cut (Hz)
              <input
                :value="draft.edit.radio.high_hz" type="number" :min="RADIO_LIMITS.high_hz[0]" :max="RADIO_LIMITS.high_hz[1]" step="100"
                :disabled="!canEdit" aria-label="Radio high cut (Hz)"
                @change="onNumber($event, (v) => setRadioValue(draft.edit, 'high_hz', v), () => draft.edit.radio?.high_hz ?? 0)"
              />
            </label>
            <label>Slope (dB/oct)
              <select :value="draft.edit.radio.slope_db_oct" :disabled="!canEdit" aria-label="Radio slope (dB per octave)" @change="onRadioSlope">
                <option v-for="s in RADIO_SLOPES" :key="s" :value="s">{{ s }}{{ s === 12 ? " (gentle)" : s === 36 ? " (steep)" : "" }}</option>
              </select>
            </label>
            <label>Presence (dB)
              <input
                :value="draft.edit.radio.presence_db" type="number" :min="RADIO_LIMITS.presence_db[0]" :max="RADIO_LIMITS.presence_db[1]" step="1"
                :disabled="!canEdit" aria-label="Radio presence (dB)"
                @change="onNumber($event, (v) => setRadioValue(draft.edit, 'presence_db', v), () => draft.edit.radio?.presence_db ?? 0)"
              />
            </label>
            <label>Drive (dB)
              <input
                :value="draft.edit.radio.drive_db" type="number" :min="RADIO_LIMITS.drive_db[0]" :max="RADIO_LIMITS.drive_db[1]" step="1"
                :disabled="!canEdit" aria-label="Radio drive (dB)"
                @change="onNumber($event, (v) => setRadioValue(draft.edit, 'drive_db', v), () => draft.edit.radio?.drive_db ?? 0)"
              />
            </label>
            <label>
              <span><input type="checkbox" :checked="draft.edit.radio.noise_dbfs !== null" :disabled="!canEdit" aria-label="Add hiss" @change="onHissToggle" /> Hiss (dBFS)</span>
              <input
                :value="draft.edit.radio.noise_dbfs ?? ''" type="number" :min="RADIO_LIMITS.noise_dbfs[0]" :max="RADIO_LIMITS.noise_dbfs[1]" step="1"
                :disabled="!canEdit || draft.edit.radio.noise_dbfs === null" aria-label="Radio hiss level (dBFS)"
                @change="onNumber($event, (v) => setRadioValue(draft.edit, 'noise_dbfs', v), () => draft.edit.radio?.noise_dbfs ?? DEFAULT_HISS_DBFS)"
              />
            </label>
            <label>
              <span><input type="checkbox" :checked="Boolean(draft.edit.radio.clicks)" :disabled="!canEdit" aria-label="Add MCC radio clicks" @change="onClicksToggle" /> MCC clicks</span>
              <span class="small muted">Key-up click before the line, release and squelch after it (from MCC's Spain lines).</span>
            </label>
          </template>
        </fieldset>
      </section>

      <section class="radio-filter" aria-label="Echo" data-testid="echo-effect">
        <header class="radio-head">
          <h4><Waves :size="14" aria-hidden="true" /> Echo</h4>
          <span class="small muted">The cryo assistant's intercom ("eco"). The line gets longer by the echo's ring-out.</span>
        </header>
        <fieldset :disabled="locked" class="edit-grid">
          <label>Preset
            <select :value="draft.edit.echo?.preset ?? 'off'" :disabled="!canEdit" aria-label="Echo preset" @change="onEchoPreset">
              <option value="off">Off</option>
              <option value="spain">Spain echo (MCC Spain eco lines)</option>
              <option value="english">English echo (MCC English eco lines)</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <template v-if="draft.edit.echo">
            <label>Delay (ms)
              <input
                :value="draft.edit.echo.delay_ms" type="number" :min="ECHO_LIMITS.delay_ms[0]" :max="ECHO_LIMITS.delay_ms[1]" step="5"
                :disabled="!canEdit" aria-label="Echo delay (ms)"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'delay_ms', v), () => draft.edit.echo?.delay_ms ?? 0)"
              />
            </label>
            <label>Echo level (dB)
              <input
                :value="draft.edit.echo.echo_db" type="number" :min="ECHO_LIMITS.echo_db[0]" :max="ECHO_LIMITS.echo_db[1]" step="1"
                :disabled="!canEdit" aria-label="Echo level (dB)"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'echo_db', v), () => draft.edit.echo?.echo_db ?? 0)"
              />
            </label>
            <label>
              <span><input type="checkbox" :checked="draft.edit.echo.feedback_db !== null" :disabled="!canEdit" aria-label="Echo repeats" @change="onEchoOptional($event, 'feedback_db')" /> Repeats (dB)</span>
              <input
                :value="draft.edit.echo.feedback_db ?? ''" type="number" :min="ECHO_LIMITS.feedback_db[0]" :max="ECHO_LIMITS.feedback_db[1]" step="1"
                :disabled="!canEdit || draft.edit.echo.feedback_db === null" aria-label="Echo feedback (dB)"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'feedback_db', v), () => draft.edit.echo?.feedback_db ?? ECHO_DEFAULTS.feedback_db)"
              />
            </label>
            <label>Diffusion (0–1)
              <input
                :value="draft.edit.echo.diffusion" type="number" min="0" max="1" step="0.1"
                :disabled="!canEdit" aria-label="Echo diffusion"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'diffusion', v), () => draft.edit.echo?.diffusion ?? 0)"
              />
            </label>
            <label>
              <span><input type="checkbox" :checked="draft.edit.echo.damping_hz !== null" :disabled="!canEdit" aria-label="Echo damping" @change="onEchoOptional($event, 'damping_hz')" /> Damping (Hz)</span>
              <input
                :value="draft.edit.echo.damping_hz ?? ''" type="number" :min="ECHO_LIMITS.damping_hz[0]" :max="ECHO_LIMITS.damping_hz[1]" step="250"
                :disabled="!canEdit || draft.edit.echo.damping_hz === null" aria-label="Echo damping (Hz)"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'damping_hz', v), () => draft.edit.echo?.damping_hz ?? ECHO_DEFAULTS.damping_hz)"
              />
            </label>
            <label>
              <span><input type="checkbox" :checked="draft.edit.echo.slap_db !== null" :disabled="!canEdit" aria-label="Echo slap" @change="onEchoOptional($event, 'slap_db')" /> Slap (dB)</span>
              <input
                :value="draft.edit.echo.slap_db ?? ''" type="number" :min="ECHO_LIMITS.slap_db[0]" :max="ECHO_LIMITS.slap_db[1]" step="1"
                :disabled="!canEdit || draft.edit.echo.slap_db === null" aria-label="Echo slap level (dB)"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'slap_db', v), () => draft.edit.echo?.slap_db ?? ECHO_DEFAULTS.slap_db)"
              />
            </label>
            <label>Slap delay (ms)
              <input
                :value="draft.edit.echo.slap_ms" type="number" :min="ECHO_LIMITS.slap_ms[0]" :max="ECHO_LIMITS.slap_ms[1]" step="1"
                :disabled="!canEdit || draft.edit.echo.slap_db === null" aria-label="Echo slap delay (ms)"
                @change="onNumber($event, (v) => setEchoValue(draft.edit, 'slap_ms', v), () => draft.edit.echo?.slap_ms ?? 30)"
              />
            </label>
          </template>
        </fieldset>
      </section>

      <template v-if="interference && usesCe">
        <InterferenceLane
          v-if="draft.edit.interference"
          :edit="draft.edit" :info="interference" :slot-id="slotId ?? ''" :ce-ref="draft.audioRef ?? ''"
          :language="draft.audioLanguage" :source-url="replacementUrl ?? ''" :duration="duration" :can-edit="canEdit"
          @points="(p) => attempt(() => setCurvePoints(draft.edit, p, duration))"
          @flutter="(v) => attempt(() => setFlutter(draft.edit, v))"
          @texture="(t) => attempt(() => setTexture(draft.edit, t))"
          @reset="applyDefaultCurve"
        />
        <section v-else class="radio-filter interference" aria-label="Transmission interference" data-testid="interference">
          <header class="radio-head"><h4>Transmission interference</h4></header>
          <p class="small">
            <button type="button" class="icon-label small-button" :disabled="!canEdit || !interference.points" @click="applyDefaultCurve">
              Add the interference curve (from the {{ interference.guides.length }} phrase guides)
            </button>
          </p>
        </section>
      </template>



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
