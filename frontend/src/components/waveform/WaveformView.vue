<script setup lang="ts">
// A waveform with playback. It shows and reports; it does not decide edits.
//
// Clicking anywhere seeks. In an editable waveform the user can also drag across the audio to make a
// selection (its edges and body can then be dragged), and drag the two handles of the kept part (the trims).
// Each change is reported (keepChange, selectionChange) and the parent applies it to the recipe through
// editRecipe.ts. Cuts, fades and trimmed-away parts are drawn from the props and never take the pointer, so
// clicks and drags over them reach the waveform underneath.
//
// WaveSurfer.js draws the waveform and owns the audio element; regions, the time ruler and the hover time
// come from its plugins.

import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import WaveSurfer from "wavesurfer.js";
import HoverPlugin from "wavesurfer.js/dist/plugins/hover.esm.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import TimelinePlugin from "wavesurfer.js/dist/plugins/timeline.esm.js";
import { AudioWaveform, Crosshair, Maximize, Pause, Play, RotateCcw, Square, X, ZoomIn, ZoomOut } from "lucide-vue-next";
import { endPlayback, startPlayback, type Playback } from "../../audio/transport";
import { formatPosition } from "../../audio/format";
import { loadPeaks } from "../../audio/peaks";
import type { Span } from "../../matching/editRecipe";
import { COLOURS } from "../../theme/tokens";

export interface Fades {
  fadeIn: Span | null;
  fadeOut: Span | null;
}

const props = withDefaults(
  defineProps<{
    url: string | null;
    label: string;
    /** "A" or "B" in the comparison: shown as a tag before the label. */
    channel?: string;
    editable?: boolean;
    keep?: Span | null;
    cuts?: Span[];
    fades?: Fades;
    /** Inserted silences: a marker at each position (original timeline), labelled with its length. */
    silences?: { at: number; dur: number }[];
    height?: number;
    /** Shown when there is no URL (for example while a preview renders). */
    emptyText?: string;
  }>(),
  {
    editable: false,
    keep: null,
    cuts: () => [],
    fades: () => ({ fadeIn: null, fadeOut: null }),
    silences: () => [],
    height: 96,
    emptyText: "No recording.",
  },
);

const emit = defineEmits<{
  duration: [seconds: number];
  keepChange: [span: Span];
  selectionChange: [span: Span | null];
  failed: [message: string];
  finish: [];
}>();

// Region ids: ours start with "studio-"; a region the plugin creates from a drag gets a random id, which is
// how a new drag selection is told apart from the regions drawn here.
const KEEP = "studio-keep";
const SELECTION = "studio-selection";
// Region colours: trimmed-away parts dimmed to the well, cuts in the rework red, fades in the focus cyan, and
// the selection in the menu blue (see theme/tokens.ts).
const DIM = "rgba(1, 4, 12, 0.8)";
const CUT = "rgba(255, 143, 128, 0.36)";
const FADE = "rgba(127, 227, 255, 0.18)";
const SELECTED = "rgba(77, 163, 255, 0.32)";
const SILENCE = "rgba(126, 231, 135, 0.95)"; // inserted silence markers, in the approved green
const WAVE = "#3f6fae"; // unplayed part: a dim menu blue
const PLAYED = "#9fd0ff"; // played part: the lit menu blue
const ZOOM_LEVELS = [1, 2, 4, 8, 16, 32]; // multiples of the width that fits the whole recording
const MIN_SELECTION_S = 0.01;

/** The label with its A / B tag, for screen readers and toolbars. */
const fullLabel = computed(() => (props.channel ? `${props.channel} · ${props.label}` : props.label));

const host = ref<HTMLElement | null>(null);
const duration = ref(0);
const position = ref(0);
const playing = ref(false);
const loading = ref(false);
const selection = ref<Span | null>(null);
const zoomIndex = ref(0);
const error = ref("");

let wave: WaveSurfer | null = null;
let regions: ReturnType<typeof RegionsPlugin.create> | null = null;
let stopDragSelection: (() => void) | null = null;
let lastPlayed: Span | null = null;

const owner: Playback = { pause: () => wave?.pause() };

onMounted(() => {
  regions = RegionsPlugin.create();
  wave = WaveSurfer.create({
    container: host.value as HTMLElement,
    height: props.height,
    waveColor: WAVE,
    progressColor: PLAYED,
    cursorColor: COLOURS.cyan,
    cursorWidth: 2,
    barWidth: 2,
    barGap: 1,
    normalize: true,
    interact: true,
    dragToSeek: false,
    plugins: [
      regions,
      TimelinePlugin.create({ height: 16, style: { color: COLOURS.textMuted, fontSize: "10px" } }),
      HoverPlugin.create({
        lineColor: COLOURS.cyan,
        lineWidth: 1,
        labelColor: COLOURS.space,
        labelBackground: COLOURS.cyan,
        labelSize: "10px",
        formatTimeCallback: formatPosition,
      }),
    ],
  });
  wave.on("ready", (seconds) => {
    loading.value = false;
    if (!props.url) return; // the blank left by empty(): nothing to play
    duration.value = seconds;
    emit("duration", seconds);
    drawRegions();
    applyZoom();
  });
  wave.on("timeupdate", (time) => (position.value = time));
  wave.on("interaction", (time) => (position.value = time));
  wave.on("play", () => {
    playing.value = true;
    startPlayback(owner);
  });
  wave.on("pause", () => {
    playing.value = false;
    endPlayback(owner);
  });
  wave.on("finish", () => {
    playing.value = false;
    endPlayback(owner);
    emit("finish");
  });
  wave.on("error", () => {
    loading.value = false;
    error.value = "This recording could not be loaded.";
  });

  regions.on("region-created", (region) => {
    if (region.id.startsWith("studio-")) return;
    // A drag across the waveform: it becomes the selection, replacing the previous one.
    for (const other of regions?.getRegions() ?? []) if (other !== region && other.id === SELECTION) other.remove();
    region.setOptions({ id: SELECTION, color: SELECTED });
    styleHandles(region);
    setSelection({ start: region.start, end: region.end });
  });
  regions.on("region-updated", (region) => {
    if (region.id === KEEP) emit("keepChange", { start: round(region.start), end: round(region.end) });
    if (region.id === SELECTION) setSelection({ start: region.start, end: region.end });
  });

  setDragSelection(props.editable);
  void load(props.url);
});

onBeforeUnmount(() => {
  endPlayback(owner);
  stopDragSelection?.();
  wave?.destroy();
  wave = null;
  regions = null;
});

watch(
  () => props.url,
  (url) => void load(url),
);
watch(
  () => props.editable,
  (editable) => {
    setDragSelection(editable);
    if (!editable) clearSelection();
    drawRegions();
  },
);
watch(
  () => [props.keep, props.cuts, props.fades, props.silences],
  () => drawRegions(),
  { deep: true },
);

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** Drag selection exists only while the waveform is editable (an approved recording cannot be edited). */
function setDragSelection(on: boolean) {
  stopDragSelection?.();
  stopDragSelection = null;
  if (on && regions) stopDragSelection = regions.enableDragSelection({ color: SELECTED, drag: true, resize: true });
}

function setSelection(span: Span | null) {
  const next = span && span.end - span.start >= MIN_SELECTION_S ? { start: round(span.start), end: round(span.end) } : null;
  if (JSON.stringify(next) === JSON.stringify(selection.value)) return;
  selection.value = next;
  emit("selectionChange", selection.value);
}

// Loads in quick succession (choosing recordings, a new preview): only the latest one is shown.
let loadSequence = 0;

async function load(url: string | null) {
  const mine = ++loadSequence;
  wave?.pause();
  duration.value = 0;
  position.value = 0;
  playing.value = false;
  error.value = "";
  lastPlayed = null;
  setSelection(null);
  regions?.clearRegions();
  if (!url || !wave) {
    wave?.empty(); // nothing outdated stays drawn (or playable)
    return;
  }
  loading.value = true;
  // Server peaks first: the waveform is drawn at once and the audio streams (and seeks) with range requests.
  // Without peaks the player downloads and decodes the whole recording, as before.
  const peaks = await loadPeaks(url);
  if (mine !== loadSequence || !wave) return;
  try {
    if (peaks) await wave.load(url, [peaks.peaks], peaks.duration);
    else await wave.load(url);
  } catch {
    if (mine !== loadSequence) return;
    loading.value = false;
    error.value = "This recording could not be loaded.";
    emit("failed", error.value);
  }
}

/** A drawn region that only shows something: the pointer goes through it to the waveform. */
function passive(region: Region) {
  if (region.element) region.element.style.pointerEvents = "none";
}

/** The resize handles of the kept part and the selection, visible on the dark theme and easy to grab. */
function styleHandles(region: Region) {
  region.element?.querySelectorAll<HTMLElement>('[part*="region-handle"]').forEach((handle) => {
    handle.style.pointerEvents = "all";
    handle.style.width = "8px";
    handle.style.background = "rgba(127, 227, 255, 0.25)";
    handle.style.borderColor = COLOURS.cyan;
  });
}

/** Draws the kept part, the trimmed-away parts, the cuts, the fades and the selection. */
function drawRegions() {
  if (!regions || !duration.value) return;
  const total = duration.value;
  const keep = props.keep ?? { start: 0, end: total };
  regions.clearRegions();
  const shade = (id: string, span: Span, color: string) =>
    span.end > span.start && passive(regions!.addRegion({ id, ...span, color, drag: false, resize: false }));
  shade("studio-trim-start", { start: 0, end: keep.start }, DIM);
  shade("studio-trim-end", { start: keep.end, end: total }, DIM);
  props.cuts.forEach((cut, i) => shade(`studio-cut-${i}`, cut, CUT));
  if (props.fades.fadeIn) shade("studio-fade-in", props.fades.fadeIn, FADE);
  if (props.fades.fadeOut) shade("studio-fade-out", props.fades.fadeOut, FADE);
  props.silences.forEach((s, i) => {
    // A region without an end is a marker; its label says how much silence is inserted there.
    const label = document.createElement("span");
    label.className = "silence-marker";
    // Regions live in WaveSurfer's shadow root, out of reach of the page's stylesheets: styled inline.
    label.style.cssText =
      "display:inline-block;margin:2px 0 0 3px;padding:0 3px;font:600 10px/1.4 monospace;" +
      "color:#04120a;background:rgba(126,231,135,0.95);border-radius:2px;white-space:nowrap";
    label.textContent = `+${(s.dur * 1000).toFixed(0)} ms`;
    passive(regions!.addRegion({ id: `studio-silence-${i}`, start: s.at, color: SILENCE, content: label, drag: false, resize: false }));
  });
  if (props.editable) {
    // Only the two handles of the kept part take the pointer; its body lets drags make selections.
    const kept = regions.addRegion({ id: KEEP, start: keep.start, end: keep.end, color: "rgba(0, 0, 0, 0)", drag: false, resize: true });
    passive(kept);
    styleHandles(kept);
    if (selection.value) {
      styleHandles(regions.addRegion({ id: SELECTION, ...selection.value, color: SELECTED, drag: true, resize: true }));
    }
  }
}

function applyZoom() {
  if (!wave || !duration.value) return;
  const width = host.value?.clientWidth ?? 600;
  wave.zoom((width / duration.value) * ZOOM_LEVELS[zoomIndex.value]);
}

function zoom(step: number) {
  zoomIndex.value = Math.min(ZOOM_LEVELS.length - 1, Math.max(0, zoomIndex.value + step));
  applyZoom();
}

function fit() {
  zoomIndex.value = 0;
  applyZoom();
}

/** Play or pause. With a selection, playing plays the selection; otherwise it plays from the playhead. */
function togglePlay() {
  if (!wave || !duration.value) return;
  if (wave.isPlaying()) {
    wave.pause();
    return;
  }
  lastPlayed = selection.value;
  if (selection.value) void wave.play(selection.value.start, selection.value.end);
  else void wave.play();
}

/** Plays from the start, whatever the playhead and the selection (used by A/B and sequential play). */
function playFromStart() {
  if (!wave || !duration.value) return;
  lastPlayed = null;
  wave.setTime(0);
  void wave.play();
}

function playSelection() {
  if (!wave || !selection.value) return;
  lastPlayed = selection.value;
  void wave.play(selection.value.start, selection.value.end);
}

function stop() {
  wave?.pause();
  wave?.setTime(0);
  position.value = 0;
}

/** Plays again what was played last: the selection, or the whole recording. */
function replay() {
  if (!wave || !duration.value) return;
  if (lastPlayed) void wave.play(lastPlayed.start, lastPlayed.end);
  else playFromStart();
}

/** Moves the playhead without starting playback. */
function seek(seconds: number) {
  if (!wave || !duration.value) return;
  wave.setTime(Math.min(duration.value, Math.max(0, seconds)));
  position.value = wave.getCurrentTime();
}

/** Plays one span of the recording (an interference region). */
function playRange(start: number, end: number) {
  if (!wave || !duration.value) return;
  lastPlayed = null;
  void wave.play(Math.max(0, start), Math.min(duration.value, end));
}

/** Plays from a position (A/B switching keeps the position). */
function playFrom(seconds: number) {
  if (!wave || !duration.value) return;
  lastPlayed = null;
  seek(seconds);
  void wave.play();
}

function currentTime(): number {
  return wave?.getCurrentTime() ?? 0;
}

function isPlaying(): boolean {
  return playing.value;
}

function clearSelection() {
  regions?.getRegions().forEach((r) => {
    if (r.id === SELECTION) r.remove();
  });
  setSelection(null);
}

defineExpose({
  togglePlay,
  playFromStart,
  playFrom,
  playSelection,
  playRange,
  stop,
  replay,
  clearSelection,
  seek,
  currentTime,
  isPlaying,
  selection,
  duration,
  playing,
  position,
});
</script>

<template>
  <figure class="wave-view" :class="{ editable }" :data-playing="playing ? 'true' : 'false'">
    <figcaption class="wave-head">
      <span class="wave-label">
        <span v-if="channel" class="channel" aria-hidden="true">{{ channel }}</span>
        <AudioWaveform v-else :size="15" aria-hidden="true" />
        <span v-if="channel" class="sr-only">{{ channel }} ·</span>
        {{ label }}
      </span>
      <span class="wave-times mono" data-testid="wave-time">{{ formatPosition(position) }} / {{ formatPosition(duration) }}</span>
    </figcaption>

    <div
      ref="host"
      class="wave-host"
      role="img"
      :aria-label="`${fullLabel} waveform`"
      :data-duration="duration"
      :data-zoom="ZOOM_LEVELS[zoomIndex]"
      data-testid="wave-host"
    ></div>
    <p v-if="loading" class="small muted wave-status">Loading the recording…</p>
    <p v-else-if="!url" class="small muted wave-status">{{ emptyText }}</p>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>

    <div class="wave-transport" role="toolbar" :aria-label="`${fullLabel}: playback`">
      <button type="button" class="icon-label" :disabled="!duration" :aria-pressed="playing" @click="togglePlay">
        <Pause v-if="playing" :size="16" aria-hidden="true" />
        <Play v-else :size="16" aria-hidden="true" />
        {{ playing ? "Pause" : selection ? "Play selection" : "Play" }}
      </button>
      <button type="button" class="icon-label" :disabled="!duration" @click="stop">
        <Square :size="14" aria-hidden="true" /> Stop
      </button>
      <button type="button" class="icon-label" :disabled="!duration" @click="replay">
        <RotateCcw :size="15" aria-hidden="true" /> Replay
      </button>
      <span v-if="selection" class="wave-selection small" data-testid="wave-selection">
        <Crosshair :size="14" aria-hidden="true" />
        {{ formatPosition(selection.start) }} – {{ formatPosition(selection.end) }}
        ({{ (selection.end - selection.start).toFixed(3) }} s)
        <button type="button" class="icon-only" title="Clear the selection" aria-label="Clear the selection" @click="clearSelection">
          <X :size="14" aria-hidden="true" />
        </button>
      </span>
      <span class="zoom" role="group" aria-label="Zoom">
        <button type="button" class="icon-only" :disabled="!duration || zoomIndex === 0" title="Zoom out" aria-label="Zoom out" @click="zoom(-1)">
          <ZoomOut :size="16" aria-hidden="true" />
        </button>
        <button type="button" class="icon-only" :disabled="!duration || zoomIndex === 0" title="Fit the whole recording" aria-label="Fit the whole recording" @click="fit">
          <Maximize :size="16" aria-hidden="true" />
        </button>
        <button type="button" class="icon-only" :disabled="!duration || zoomIndex === ZOOM_LEVELS.length - 1" title="Zoom in" aria-label="Zoom in" @click="zoom(1)">
          <ZoomIn :size="16" aria-hidden="true" />
        </button>
      </span>
    </div>
  </figure>
</template>
