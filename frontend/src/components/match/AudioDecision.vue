<script setup lang="ts">
// Audio choice for one MCC line: keep Spain's recording, use one of the matched Campaign Evolved lines, or mute
// the line in game (Mute / No replacement: silence of the original length; the reason is required).
// Choosing a recording goes through the parent (useMatch.chooseRecording), which also offers its subtitle.
// Approved audio is shown read-only. Durations are compared under "Listen and compare".

import { X } from "lucide-vue-next";
import { nextTick, ref, watch } from "vue";
import type { CeLanguage } from "../../api/types";
import type { Draft } from "../../matching/draft";

// readOnly: the public read-only view (docs/public-access.md): shown as stored, with no editing advice.
const props = defineProps<{ draft: Draft; locked: boolean; readOnly?: boolean }>();
const emit = defineEmits<{ choose: [ref: string]; remove: [ref: string]; mute: [] }>();

// Choosing Mute puts the cursor in the reason box: Save stays disabled until the reason is written.
const reasonBox = ref<HTMLTextAreaElement | null>(null);
watch(
  () => props.draft.audioSource,
  (now, before) => {
    if (now === "mute" && before !== "mute" && !props.locked) void nextTick(() => reasonBox.value?.focus());
  },
);

const LANGUAGES: { value: CeLanguage; label: string }[] = [
  { value: "Spanish(Mexico)", label: "LATAM Spanish (es-MX)" },
  { value: "English(US)", label: "English" },
  { value: "Spanish(Spain)", label: "Spain Spanish (es-ES)" },
];
</script>

<template>
  <div class="audio-decision">
    <p v-if="locked && !readOnly" class="note">Approved. Mark it Needs rework to change the audio.</p>

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
      <label class="opt">
        <input type="radio" :checked="draft.audioSource === 'mute'" data-testid="mute-line" @change="emit('mute')" />
        Mute in game (no replacement)
      </label>
    </fieldset>

    <div v-if="draft.audioSource === 'mute'" class="mute-reason">
      <p class="small muted">
        The line is omitted: the game plays silence of the same length, so the scene's timing does not change.
        Choose Keep Spain's audio to undo.
      </p>
      <label class="block-label">
        Why is it muted? (required)
        <textarea
          ref="reasonBox"
          v-model="draft.muteReason"
          rows="2"
          maxlength="500"
          required
          :aria-invalid="!draft.muteReason.trim()"
          placeholder="Required: Save stays disabled until you say why"
          :disabled="locked"
          data-testid="mute-reason"
        ></textarea>
      </label>
    </div>

    <div v-if="draft.ceRefs.length && draft.audioSource !== 'mute'" class="matched">
      <p class="small muted">{{ readOnly ? "Matched recordings:" : "Matched recordings (choose one to use as the replacement):" }}</p>
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
          <button v-if="!readOnly" type="button" class="link icon-label" :disabled="locked" @click="emit('remove', ref)">
            <X :size="13" aria-hidden="true" /> remove
          </button>
        </li>
      </ul>
    </div>
    <p v-else-if="draft.audioSource !== 'mute'" class="small muted">No Campaign Evolved recording is matched to this line yet.<template v-if="!readOnly"> Use one from the right-hand list.</template></p>

    <label class="inline">
      Language of the replacement
      <select v-model="draft.audioLanguage" :disabled="locked || draft.audioSource !== 'ce'">
        <option v-for="lang in LANGUAGES" :key="lang.value" :value="lang.value">{{ lang.label }}</option>
      </select>
    </label>
  </div>
</template>
