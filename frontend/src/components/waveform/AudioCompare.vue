<script setup lang="ts">
// The two recordings of the line, one above the other, both read-only:
//   A: the original MCC recording (Spain), never changed.
//   B: the Campaign Evolved replacement: unedited, the edited preview, or the preview as encoded for the game.
// A / B switches between them at the same position; "A then B" plays the original and then the replacement.
// Only one recording ever plays (see audio/transport.ts).

import { computed, ref, watch } from "vue";
import { ArrowRightLeft, Headphones, ListVideo, Square } from "lucide-vue-next";
import WaveformView from "./WaveformView.vue";
import { formatSeconds } from "../../audio/format";
import { useShortcuts } from "../../composables/useShortcuts";

export type ReplacementKind = "unedited" | "edited" | "encoded";

const props = defineProps<{
  mccUrl: string | null;
  replacement: Record<ReplacementKind, string | null>;
  /** The edited preview no longer matches the recipe (the recipe changed after it was rendered). */
  previewStale: boolean;
}>();

const original = ref<InstanceType<typeof WaveformView> | null>(null);
const other = ref<InstanceType<typeof WaveformView> | null>(null);
const originalSeconds = ref<number | null>(null);
const otherSeconds = ref<number | null>(null);
const kind = ref<ReplacementKind>("unedited");
let thenB = false;

const KIND_LABEL: Record<ReplacementKind, string> = {
  unedited: "Campaign Evolved LATAM (unedited)",
  edited: "Campaign Evolved LATAM (edited preview)",
  encoded: "Campaign Evolved LATAM (encoded for the game)",
};

const otherUrl = computed(() => props.replacement[kind.value]);
const otherLabel = computed(() => `${KIND_LABEL[kind.value]}${kind.value !== "unedited" && props.previewStale ? " — out of date" : ""}`);
const difference = computed(() =>
  originalSeconds.value !== null && otherSeconds.value !== null ? otherSeconds.value - originalSeconds.value : null,
);

// A new preview is what the user wants to hear: B switches to it. If the replacement goes away, B falls back.
watch(
  () => props.replacement.edited,
  (url) => {
    if (url) kind.value = "edited";
    else if (kind.value !== "unedited") kind.value = "unedited";
  },
);
watch(
  () => props.replacement.unedited,
  () => {
    if (!props.replacement.edited) kind.value = "unedited";
  },
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
  original.value.playFromStart();
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
  <section class="block compare" aria-label="Compare the original and the replacement">
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
          <option value="unedited" :disabled="!replacement.unedited">Unedited recording</option>
          <option value="edited" :disabled="!replacement.edited">Edited preview</option>
          <option value="encoded" :disabled="!replacement.encoded">Encoded for the game (CELT)</option>
        </select>
      </label>
      <span v-if="!replacement.unedited" class="small muted">No Campaign Evolved recording chosen.</span>
      <span v-else-if="!replacement.edited" class="small muted">Preview the edit to hear it here.</span>
      <span v-else-if="previewStale" class="small warn">The recipe changed since this preview. Preview again.</span>
    </div>

    <WaveformView
      ref="other"
      :url="otherUrl"
      :height="64"
      channel="B"
      :label="otherLabel"
      @duration="(s) => (otherSeconds = s)"
    />

    <dl class="durations compact">
      <dt>A · Original</dt><dd class="mono" data-testid="duration-a">{{ formatSeconds(originalSeconds) }}</dd>
      <dt>B · Replacement</dt><dd class="mono" data-testid="duration-b">{{ otherUrl ? formatSeconds(otherSeconds) : "—" }}</dd>
      <dt>Difference</dt>
      <dd class="mono" data-testid="duration-diff">{{ difference === null ? "—" : `${difference >= 0 ? "+" : ""}${difference.toFixed(3)} s` }}</dd>
    </dl>
  </section>
</template>
