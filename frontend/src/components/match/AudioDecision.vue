<script setup lang="ts">
// Audio choice for one MCC line: keep Spain's recording, or use one of the matched Campaign Evolved lines.
// Choosing a recording goes through the parent (useMatch.chooseRecording), which also offers its subtitle.
// Approved audio is shown read-only. Durations are compared under "Listen and compare".

import { X } from "lucide-vue-next";
import type { CeLanguage } from "../../api/types";
import type { Draft } from "../../matching/draft";

defineProps<{ draft: Draft; locked: boolean }>();
const emit = defineEmits<{ choose: [ref: string]; remove: [ref: string] }>();

const LANGUAGES: { value: CeLanguage; label: string }[] = [
  { value: "Spanish(Mexico)", label: "LATAM Spanish (es-MX)" },
  { value: "English(US)", label: "English" },
  { value: "Spanish(Spain)", label: "Spain Spanish (es-ES)" },
];
</script>

<template>
  <div class="audio-decision">
    <p v-if="locked" class="note">Approved. Mark it Needs rework to change the audio.</p>

    <fieldset :disabled="locked" class="choice">
      <label class="opt">
        <input type="radio" :checked="draft.audioSource === 'keep_original'" data-testid="keep-spain" @change="draft.audioSource = 'keep_original'" />
        Keep Spain's audio (no suitable replacement)
      </label>
      <label class="opt">
        <input
          type="radio"
          :checked="draft.audioSource === 'ce'"
          :disabled="!draft.ceRefs.length"
          @change="emit('choose', draft.audioRef && draft.ceRefs.includes(draft.audioRef) ? draft.audioRef : draft.ceRefs[0])"
        />
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
              @change="emit('choose', ref)"
            />
            <span class="mono small">{{ ref }}</span>
          </label>
          <button type="button" class="link icon-label" :disabled="locked" @click="emit('remove', ref)">
            <X :size="13" aria-hidden="true" /> remove
          </button>
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
  </div>
</template>
