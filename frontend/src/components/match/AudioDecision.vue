<script setup lang="ts">
// Audio choice for one MCC line: keep Spain's recording, or use one of the matched Campaign Evolved lines.
// The draft is edited in place (it is the parent's reactive copy). Approved audio is shown read-only.

import { X } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { audioUrl } from "../../api/client";
import { clipDuration } from "../../audio/clipInfo";
import type { CeLanguage } from "../../api/types";
import type { Draft } from "../../matching/draft";

const props = defineProps<{ draft: Draft; locked: boolean; mccDuration: number | null }>();

const LANGUAGES: { value: CeLanguage; label: string }[] = [
  { value: "Spanish(Mexico)", label: "LATAM Spanish (es-MX)" },
  { value: "English(US)", label: "English" },
  { value: "Spanish(Spain)", label: "Spain Spanish (es-ES)" },
];

const replacementUrl = computed(() =>
  props.draft.audioSource === "ce" && props.draft.audioRef
    ? audioUrl.ce(props.draft.audioRef, props.draft.audioLanguage)
    : null,
);
const replacementDuration = ref<number | null>(null);
watch(
  replacementUrl,
  async (url) => {
    replacementDuration.value = url ? await clipDuration(url) : null;
  },
  { immediate: true },
);

const difference = computed(() =>
  replacementDuration.value !== null && props.mccDuration !== null
    ? replacementDuration.value - props.mccDuration
    : null,
);

const seconds = (s: number | null) => (s === null ? "—" : `${s.toFixed(2)} s`);

function keepSpainAudio() {
  props.draft.audioSource = "keep_original";
}

function useRecording(line: string) {
  props.draft.audioSource = "ce";
  props.draft.audioRef = line;
  if (!props.draft.ceRefs.includes(line)) props.draft.ceRefs.push(line);
  if (props.draft.matchStatus !== "matched") props.draft.matchStatus = "matched";
}

function removeMatch(line: string) {
  props.draft.ceRefs = props.draft.ceRefs.filter((r) => r !== line);
  if (props.draft.audioRef === line) {
    props.draft.audioRef = null;
    props.draft.audioSource = "keep_original";
  }
}
</script>

<template>
  <section class="block">
    <h3>Replacement audio</h3>
    <p v-if="locked" class="note">Approved. Mark it Needs rework to change the audio.</p>

    <fieldset :disabled="locked" class="choice">
      <label class="opt">
        <input type="radio" :checked="draft.audioSource === 'keep_original'" @change="keepSpainAudio" />
        Keep Spain's audio (no suitable replacement)
      </label>
      <label class="opt">
        <input type="radio" :checked="draft.audioSource === 'ce'" :disabled="!draft.ceRefs.length" @change="draft.audioSource = 'ce'" />
        Use a matched Campaign Evolved recording
      </label>
    </fieldset>

    <div v-if="draft.ceRefs.length" class="matched">
      <p class="small muted">Matched recordings (choose one to use as the replacement):</p>
      <ul>
        <li v-for="ref in draft.ceRefs" :key="ref">
          <label class="opt">
            <input
              type="radio"
              name="replacement"
              :checked="draft.audioRef === ref && draft.audioSource === 'ce'"
              :disabled="locked"
              @change="useRecording(ref)"
            />
            <span class="mono small">{{ ref }}</span>
          </label>
          <button type="button" class="link icon-label" :disabled="locked" @click="removeMatch(ref)"><X :size="13" aria-hidden="true" /> remove</button>
        </li>
      </ul>
    </div>
    <p v-else class="small muted">No Campaign Evolved recording is matched to this line yet. Use one from the right-hand list.</p>

    <label class="inline">
      Language of the replacement
      <select v-model="draft.audioLanguage" :disabled="locked || draft.audioSource !== 'ce'">
        <option v-for="lang in LANGUAGES" :key="lang.value" :value="lang.value">{{ lang.label }}</option>
      </select>
    </label>

    <dl class="durations">
      <dt>Spain (MCC)</dt><dd>{{ seconds(mccDuration) }}</dd>
      <dt>Replacement</dt><dd>{{ draft.audioSource === "ce" ? seconds(replacementDuration) : "—" }}</dd>
      <dt>Difference</dt>
      <dd>{{ difference === null ? "—" : `${difference >= 0 ? "+" : ""}${difference.toFixed(2)} s` }}</dd>
    </dl>
  </section>
</template>
