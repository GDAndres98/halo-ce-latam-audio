<script setup lang="ts">
// Audio choice for one MCC line: keep Spain's recording, use one of the matched Campaign Evolved lines, or mute
// the line in game (Mute / No replacement: silence of the original length; the reason is required).
// Choosing a recording goes through the parent (useMatch.chooseRecording), which also offers its subtitle.
// The 4th option, "Replace every take of this sound", is not a decision of this line: it opens the sound-level panel
// (WholeSoundReplace.vue, own take set) through `whole`. It stays available on an approved line, because the panel's
// own confirmed action takes care of the approvals; it is checked (and the rest locked) while the set is on.
// Approved audio is shown read-only. Durations are compared under "Listen and compare".

import { X } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";
import type { CeLanguage } from "../../api/types";
import { chooseCombined, isCombined, setCombinedRef, type Draft } from "../../matching/draft";

// Two recordings in one replacement (docs/combine-recordings.md): join them (one after the other, each with its own
// edits and a gap) or play them at the same time (the second can start later). Both must be matched lines.
const combined = computed(() => isCombined(props.draft.audioSource));
const twoMatched = computed(() => props.draft.ceRefs.length >= 2);

// readOnly: the public read-only view (docs/public-access.md): shown as stored, with no editing advice.
const props = defineProps<{
  draft: Draft; locked: boolean; readOnly?: boolean;
  /** The 4th option is chosen (the panel is open) or the sound's own take set is on. */
  whole?: boolean;
  /** Whether the sound allows it (mono, no subtitle entry) and why not. */
  wholeAllowed?: boolean; wholeReason?: string; wholeOn?: boolean;
}>();
const emit = defineEmits<{ choose: [ref: string]; remove: [ref: string]; mute: []; whole: [on: boolean] }>();

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
    <p v-if="locked && !readOnly && !wholeOn" class="note">Approved. Mark it Needs rework to change the audio.</p>

    <fieldset :disabled="locked" class="choice">
      <label class="opt">
        <input type="radio" :checked="!whole && draft.audioSource === 'keep_original'" data-testid="keep-spain"
               @change="emit('whole', false); draft.audioSource = 'keep_original'" />
        Keep Spain's audio (no suitable replacement)
      </label>
      <label class="opt">
        <input
          type="radio"
          :checked="!whole && draft.audioSource === 'ce'"
          :disabled="!draft.ceRefs.length"
          @change="emit('whole', false); emit('choose', draft.audioRef && draft.ceRefs.includes(draft.audioRef) ? draft.audioRef : draft.ceRefs[0])"
        />
        Use a matched Campaign Evolved recording
      </label>
      <label class="opt" :title="twoMatched ? '' : 'Match a second Campaign Evolved line first'">
        <input type="radio" :checked="!whole && draft.audioSource === 'ce_concat'" :disabled="!twoMatched" data-testid="join-two"
               @change="emit('whole', false); chooseCombined(draft, 'ce_concat')" />
        Join two matched recordings (one after the other)
      </label>
      <label class="opt" :title="twoMatched ? '' : 'Match a second Campaign Evolved line first'">
        <input type="radio" :checked="!whole && draft.audioSource === 'ce_mix'" :disabled="!twoMatched" data-testid="mix-two"
               @change="emit('whole', false); chooseCombined(draft, 'ce_mix')" />
        Play two matched recordings at the same time
      </label>
      <label class="opt">
        <input type="radio" :checked="!whole && draft.audioSource === 'mute'" data-testid="mute-line"
               @change="emit('whole', false); emit('mute')" />
        Mute in game (no replacement)
      </label>
    </fieldset>
    <!-- Outside the fieldset: not locked by this line's approval (the panel's confirmation handles that). -->
    <label class="opt whole-opt" :title="wholeAllowed === false ? `Not available: ${wholeReason}` : ''">
      <input type="radio" :checked="whole" :disabled="readOnly || wholeOn || wholeAllowed === false"
             data-testid="whole-sound-option" @change="emit('whole', true)" />
      Replace every take of this sound (choose several recordings)
    </label>
    <p v-if="wholeAllowed === false && !readOnly" class="small muted">
      Replacing every take is not available here: {{ wholeReason }}.
    </p>

    <div v-if="!whole && draft.audioSource === 'mute'" class="mute-reason">
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

    <template v-if="!whole">
    <div v-if="combined" class="matched combined-refs" data-testid="combined-refs">
      <label v-for="(label, which) in ['First recording', draft.audioSource === 'ce_mix' ? 'Second recording (plays with it)' : 'Then']"
             :key="which" class="inline">
        {{ label }}
        <select :value="which === 0 ? draft.audioRef : draft.audioRefB" :disabled="locked" :data-testid="`combined-ref-${which}`"
                @change="setCombinedRef(draft, which as 0 | 1, ($event.target as HTMLSelectElement).value)">
          <option v-for="ref in draft.ceRefs" :key="ref" :value="ref">{{ ref }}</option>
        </select>
      </label>
    </div>
    <div v-if="draft.ceRefs.length && draft.audioSource !== 'mute' && !combined" class="matched">
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
      <select v-model="draft.audioLanguage" :disabled="locked || (draft.audioSource !== 'ce' && !combined)">
        <option v-for="lang in LANGUAGES" :key="lang.value" :value="lang.value">{{ lang.label }}</option>
      </select>
    </label>
    </template>
  </div>
</template>
