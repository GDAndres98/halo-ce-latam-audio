<script setup lang="ts">
// Non-destructive audio editing for the replacement recording: trims and cuts, previewed as M6 would
// render them. The original WAV is never changed; the recipe is stored with the audio decision.
//
// Speed and per-line gain are not offered: they were removed on 2026-10-09 (see CLAUDE.md).

import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import { togglePlay } from "../../audio/player";
import { defaultEdit, type Draft } from "../../matching/draft";

const props = defineProps<{ draft: Draft; locked: boolean; slotId: string }>();

const canvas = ref<HTMLCanvasElement | null>(null);
const duration = ref<number | null>(null);
const peaks = ref<number[]>([]);
const waveError = ref("");
const previewError = ref<string[]>([]);
const previewing = ref(false);

const waveUrl = computed(() =>
  props.draft.audioSource === "ce" && props.draft.audioRef
    ? audioUrl.ce(props.draft.audioRef, props.draft.audioLanguage)
    : null,
);

/** Downloads the original WAV and decodes it once, to draw the waveform and know the exact length. */
async function loadWaveform(url: string | null) {
  duration.value = null;
  peaks.value = [];
  waveError.value = "";
  if (!url) return;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`the recording is not available (${response.status})`);
    const context = new AudioContext();
    try {
      const decoded = await context.decodeAudioData(await response.arrayBuffer());
      duration.value = decoded.duration;
      peaks.value = bucketPeaks(decoded.getChannelData(0), 600);
    } finally {
      await context.close();
    }
  } catch (e) {
    waveError.value = e instanceof Error ? e.message : String(e);
  }
}

watch(waveUrl, loadWaveform, { immediate: true });

/** Maximum absolute sample per bucket: one bar per pixel column. */
function bucketPeaks(samples: Float32Array, buckets: number): number[] {
  const size = Math.max(1, Math.floor(samples.length / buckets));
  const out: number[] = [];
  for (let b = 0; b < buckets; b++) {
    let max = 0;
    const end = Math.min(samples.length, (b + 1) * size);
    for (let i = b * size; i < end; i++) max = Math.max(max, Math.abs(samples[i]));
    out.push(max);
  }
  return out;
}

const cutSeconds = computed(() => props.draft.edit.cuts.reduce((sum, c) => sum + Math.max(0, c.end_s - c.start_s), 0));
const editedDuration = computed(() =>
  duration.value === null
    ? null
    : Math.max(0, duration.value - props.draft.edit.trim_start_s - props.draft.edit.trim_end_s - cutSeconds.value),
);

/** The problems the user can see at once. The server checks the same rules again when previewing or saving. */
const localProblems = computed(() => {
  const e = props.draft.edit;
  const problems: string[] = [];
  if (e.trim_start_s < 0 || e.trim_end_s < 0) problems.push("Trims cannot be negative.");
  if (duration.value !== null && editedDuration.value !== null && editedDuration.value <= 0.05) {
    problems.push("The trims and cuts leave nothing to play.");
  }
  e.cuts.forEach((c, i) => {
    if (c.end_s <= c.start_s) problems.push(`Cut ${i + 1} ends before it starts.`);
  });
  return problems;
});

function addCut() {
  props.draft.edit.cuts.push({ start_s: 0, end_s: 0 });
}

function removeCut(index: number) {
  props.draft.edit.cuts.splice(index, 1);
}

function resetEdits() {
  props.draft.edit = defaultEdit(props.draft.edit.gap_s);
  previewError.value = [];
}

async function preview() {
  if (!props.draft.audioRef) return;
  previewing.value = true;
  previewError.value = [];
  try {
    const result = await api.editPreview({
      slot_id: props.slotId,
      ce_line_ref: props.draft.audioRef,
      language: props.draft.audioLanguage,
      edit: props.draft.edit,
    });
    togglePlay(result.urls.edited);
  } catch (e) {
    previewError.value = e instanceof ApiError && e.details.length ? e.details : [e instanceof Error ? e.message : String(e)];
  } finally {
    previewing.value = false;
  }
}

// Drawing: the bars, the trimmed ends and the cuts shaded over them.
function draw() {
  const el = canvas.value;
  if (!el) return;
  const ctx = el.getContext("2d");
  if (!ctx) return;
  const { width, height } = el;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#8a94a6";
  const bars = peaks.value;
  bars.forEach((p, i) => {
    const h = Math.max(1, p * height);
    ctx.fillRect((i / bars.length) * width, (height - h) / 2, Math.max(1, width / bars.length), h);
  });
  if (duration.value === null) return;
  const x = (s: number) => (s / (duration.value as number)) * width;
  ctx.fillStyle = "rgba(180, 35, 24, 0.25)";
  ctx.fillRect(0, 0, x(props.draft.edit.trim_start_s), height);
  ctx.fillRect(width - x(props.draft.edit.trim_end_s), 0, x(props.draft.edit.trim_end_s), height);
  ctx.fillStyle = "rgba(36, 86, 199, 0.25)";
  for (const c of props.draft.edit.cuts) ctx.fillRect(x(c.start_s), 0, Math.max(1, x(c.end_s) - x(c.start_s)), height);
}

watch([peaks, duration, () => JSON.stringify(props.draft.edit)], () => draw(), { deep: false });
onBeforeUnmount(() => {
  // Nothing to release: the waveform context is closed after decoding.
});

const seconds = (s: number | null) => (s === null ? "—" : `${s.toFixed(2)} s`);
</script>

<template>
  <section class="block">
    <h3>Audio editing</h3>
    <p v-if="draft.audioSource !== 'ce' || !draft.audioRef" class="note">
      Editing applies to a Campaign Evolved recording. Choose one to edit it.
    </p>

    <template v-else>
      <p v-if="waveError" class="error small">{{ waveError }}</p>
      <canvas ref="canvas" class="wave" width="600" height="80" aria-label="Waveform of the replacement recording"></canvas>

      <dl class="durations">
        <dt>Original</dt><dd>{{ seconds(duration) }}</dd>
        <dt>After edits</dt><dd>{{ seconds(editedDuration) }}</dd>
      </dl>

      <fieldset :disabled="locked" class="edit-grid">
        <label>Trim start (s)
          <input v-model.number="draft.edit.trim_start_s" type="number" min="0" step="0.01" />
        </label>
        <label>Trim end (s)
          <input v-model.number="draft.edit.trim_end_s" type="number" min="0" step="0.01" />
        </label>
      </fieldset>

      <fieldset :disabled="locked" class="edit-grid">
        <label>Fade in (ms)
          <input v-model.number="draft.edit.fade_in_ms" type="number" min="0" max="5000" step="10" />
        </label>
        <label>Fade out (ms)
          <input v-model.number="draft.edit.fade_out_ms" type="number" min="0" max="5000" step="10" />
        </label>
      </fieldset>

      <fieldset :disabled="locked" class="loudness">
        <label class="inline">Loudness
          <select v-model="draft.edit.loudness.mode">
            <option value="off">Keep the source level</option>
            <option value="match_mcc">Match Spain's recording</option>
          </select>
        </label>
        <template v-if="draft.edit.loudness.mode === 'match_mcc'">
          <label class="inline">Offset (dB)
            <input v-model.number="draft.edit.loudness.offset_db" type="number" min="-12" max="12" step="0.5" />
          </label>
          <label class="opt">
            <input v-model="draft.edit.limiter" type="checkbox" />
            Limit peaks (look-ahead limiter at -1 dBFS)
          </label>
        </template>
      </fieldset>
      <p v-if="draft.edit.loudness.mode === 'match_mcc'" class="small muted">
        The gain to Spain's loudness is applied before the global gain (see Build &amp; Test). Previews show the result.
      </p>

      <div class="cuts">
        <p class="small muted">Cuts remove a part of the recording (times are from the original start):</p>
        <div v-for="(cut, i) in draft.edit.cuts" :key="i" class="row">
          <label>From (s) <input v-model.number="cut.start_s" type="number" min="0" step="0.01" :disabled="locked" /></label>
          <label>To (s) <input v-model.number="cut.end_s" type="number" min="0" step="0.01" :disabled="locked" /></label>
          <button type="button" class="link" :disabled="locked" @click="removeCut(i)">remove</button>
        </div>
        <button type="button" :disabled="locked" @click="addCut">Add cut</button>
      </div>

      <ul v-if="localProblems.length" class="problems">
        <li v-for="p in localProblems" :key="p">{{ p }}</li>
      </ul>
      <ul v-if="previewError.length" class="problems">
        <li v-for="p in previewError" :key="p">{{ p }}</li>
      </ul>

      <div class="row">
        <button type="button" :disabled="previewing || localProblems.length > 0" @click="preview">
          {{ previewing ? "Rendering…" : "Preview edited recording" }}
        </button>
        <button type="button" :disabled="locked" @click="resetEdits">Reset edits to the original</button>
      </div>
      <p class="small muted">The preview is rendered as the build would render it. Nothing is saved until you save the draft.</p>
    </template>
  </section>
</template>
