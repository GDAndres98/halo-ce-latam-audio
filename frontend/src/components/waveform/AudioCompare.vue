<script setup lang="ts">
// The two recordings of the line, one above the other, both read-only:
//   A: the original MCC recording (Spain), never changed.
//   B: the Campaign Evolved replacement. By default the edited recording, rendered automatically after every
//      change (see composables/useEditPreview.ts); also the unedited recording or the edit as encoded.
// A / B switches between them at the same position; "A then B" plays the original and then the replacement.
// Only one recording ever plays (see audio/transport.ts), and nothing plays by itself.
// On touch screens two more buttons play A or B from the start, so the comparison works with one thumb.
//
// While the edited recording is being rendered, B has no URL: an outdated preview is never offered.

import { computed, ref, watch } from "vue";
import { ArrowRightLeft, Headphones, ListVideo, LoaderCircle, Play, Square, TriangleAlert } from "lucide-vue-next";
import WaveformView from "./WaveformView.vue";
import { formatSeconds } from "../../audio/format";
import { useShortcuts } from "../../composables/useShortcuts";

export type ReplacementKind = "unedited" | "edited" | "encoded";

const props = defineProps<{
  mccUrl: string | null;
  /** `edited` and `encoded` are set only for a preview of the current recipe. */
  replacement: Record<ReplacementKind, string | null>;
  /** The server can render the edited recording (false: B can only play the unedited one). */
  canRender: boolean;
  /** The edited recording is being rendered for the latest change. */
  rendering: boolean;
  /** Why the last render failed. */
  errors: string[];
  /** Render statistics of the current preview (global gain report). */
  stats: Record<string, number> | null;
}>();

const original = ref<InstanceType<typeof WaveformView> | null>(null);
const other = ref<InstanceType<typeof WaveformView> | null>(null);
const originalSeconds = ref<number | null>(null);
const otherSeconds = ref<number | null>(null);
const defaultKind = (): ReplacementKind => (props.canRender ? "edited" : "unedited");
const kind = ref<ReplacementKind>(defaultKind());
let thenB = false;

const KIND_LABEL: Record<ReplacementKind, string> = {
  unedited: "Campaign Evolved LATAM (unedited)",
  edited: "Campaign Evolved LATAM (edited)",
  encoded: "Campaign Evolved LATAM (encoded for the game)",
};

const otherUrl = computed(() => props.replacement[kind.value]);
const otherLabel = computed(() => KIND_LABEL[kind.value]);
const otherEmptyText = computed(() =>
  !props.replacement.unedited
    ? "No Campaign Evolved recording chosen."
    : props.rendering
      ? "Rendering the latest edits…"
      : props.errors.length
        ? "The edited recording could not be rendered."
        : "No recording.",
);
/** One word for the tests and the status line: none, rendering, ready or error. */
const previewState = computed(() =>
  !props.replacement.unedited || !props.canRender
    ? "none"
    : props.rendering
      ? "rendering"
      : props.errors.length
        ? "error"
        : props.replacement.edited
          ? "ready"
          : "none",
);

/** The gain report: the global gain is applied in full unless the peak would pass −1 dBFS (then it is
 * reduced and the shortfall reported). */
const gainReport = computed(() => {
  const s = props.stats;
  if (!s) return null;
  const shortfall = Number(s.global_gain_shortfall_db ?? 0);
  return {
    applied: Number(s.global_gain_applied_db ?? 0),
    shortfall,
    peak: Number(s.output_peak_dbfs ?? 0),
    reduced: shortfall > 0.05,
  };
});
const difference = computed(() =>
  originalSeconds.value !== null && otherSeconds.value !== null ? otherSeconds.value - originalSeconds.value : null,
);

// A newly chosen recording starts on the default B (the edited recording). Otherwise the user's choice of B
// stays while they edit.
watch(
  () => props.replacement.unedited,
  () => (kind.value = defaultKind()),
);
watch(otherUrl, () => (otherSeconds.value = null));

/** Switches between A and B at the same position. If neither plays, A starts from the beginning. */
function switchAB() {
  const a = original.value;
  const b = other.value;
  if (!a || !b) return;
  thenB = false;
  if (a.isPlaying()) b.playFrom(a.currentTime());
  else if (b.isPlaying()) a.playFrom(b.currentTime());
  else a.playFromStart();
}

/** Plays A from the start, then B from the start. */
function playSequence() {
  if (!original.value || !other.value?.duration) return;
  thenB = true;
  other.value.prime(); // B starts without a tap of its own when A ends (phone browsers need this)
  original.value.playFromStart();
}

function playOnly(player: InstanceType<typeof WaveformView> | null) {
  thenB = false;
  player?.playFromStart();
}

function onOriginalFinished() {
  if (!thenB || !other.value) return;
  thenB = false;
  other.value.playFromStart();
}

function stopAll() {
  thenB = false;
  original.value?.stop();
  other.value?.stop();
}

useShortcuts({ a: switchAB, b: playSequence });
</script>

<template>
  <section class="block compare" aria-label="Compare the original and the replacement" data-section="compare">
    <header class="compare-head">
      <h3><Headphones :size="15" aria-hidden="true" /> Listen and compare</h3>
      <div class="toolbar" role="toolbar" aria-label="Comparison">
        <button
          type="button"
          class="icon-label"
          :disabled="!original?.duration || !other?.duration"
          title="Switch between A and B at the same position (A)"
          @click="switchAB"
        >
          <ArrowRightLeft :size="16" aria-hidden="true" /> A / B
        </button>
        <button
          type="button"
          class="icon-label"
          :disabled="!original?.duration || !other?.duration"
          title="Play the original, then the replacement (B)"
          @click="playSequence"
        >
          <ListVideo :size="16" aria-hidden="true" /> A then B
        </button>
        <button
          type="button" class="icon-label touch-only" :disabled="!original?.duration"
          data-testid="play-a" @click="playOnly(original)"
        >
          <Play :size="16" aria-hidden="true" /> Original (A)
        </button>
        <button
          type="button" class="icon-label touch-only" :disabled="!other?.duration"
          data-testid="play-b" @click="playOnly(other)"
        >
          <Play :size="16" aria-hidden="true" /> Replacement (B)
        </button>
        <button type="button" class="icon-label" title="Stop both (Esc)" @click="stopAll">
          <Square :size="14" aria-hidden="true" /> Stop
        </button>
      </div>
    </header>

    <WaveformView
      ref="original"
      :url="mccUrl"
      :height="64"
      channel="A"
      label="Original MCC (Spain, read-only)"
      @duration="(s) => (originalSeconds = s)"
      @finish="onOriginalFinished"
    />

    <div class="compare-source">
      <label class="inline small">B plays
        <select v-model="kind" aria-label="Which replacement B plays">
          <option value="edited" :disabled="!canRender">Edited recording (latest edits)</option>
          <option value="unedited">Unedited recording</option>
          <option value="encoded" :disabled="!canRender">Encoded for the game (CELT)</option>
        </select>
      </label>
      <span class="preview-status small" role="status" data-testid="preview-status" :data-state="previewState">
        <span v-if="!replacement.unedited" class="muted">No Campaign Evolved recording chosen.</span>
        <span v-else-if="!canRender" class="muted">Previews are unavailable on this server: B plays the unedited recording.</span>
        <template v-else-if="rendering">
          <LoaderCircle :size="14" class="spin" aria-hidden="true" />
          <span class="muted">Rendering the latest edits…</span>
        </template>
        <template v-else-if="errors.length">
          <TriangleAlert :size="14" class="warn" aria-hidden="true" />
          <span class="warn">Could not render the edits: {{ errors.join(" · ") }}</span>
        </template>
        <span v-else-if="replacement.edited" class="muted">Edited recording is up to date.</span>
      </span>
    </div>

    <WaveformView
      ref="other"
      :url="otherUrl"
      :height="64"
      channel="B"
      :label="otherLabel"
      :empty-text="otherEmptyText"
      @duration="(s) => (otherSeconds = s)"
    />

    <dl class="durations compact">
      <dt>A · Original</dt><dd class="mono" data-testid="duration-a">{{ formatSeconds(originalSeconds) }}</dd>
      <dt>B · {{ kind === "unedited" ? "Unedited" : "Edited" }}</dt><dd class="mono" data-testid="duration-b">{{ otherUrl ? formatSeconds(otherSeconds) : "—" }}</dd>
      <dt>Difference</dt>
      <dd class="mono" data-testid="duration-diff">{{ difference === null ? "—" : `${difference >= 0 ? "+" : ""}${difference.toFixed(3)} s` }}</dd>
    </dl>
    <p v-if="gainReport && replacement.edited" class="small" :class="gainReport.reduced ? 'warn' : 'muted'" data-testid="gain-report">
      Global gain {{ gainReport.applied >= 0 ? "+" : "" }}{{ gainReport.applied.toFixed(1) }} dB applied once (build setting)
      <span v-if="gainReport.reduced">· reduced by {{ gainReport.shortfall.toFixed(1) }} dB so the peak stays at or below −1 dBFS</span>
      · output peak {{ gainReport.peak.toFixed(1) }} dBFS.
    </p>
  </section>
</template>
