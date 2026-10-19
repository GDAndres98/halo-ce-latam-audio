<script setup lang="ts">
// The Studio's listening volume (audio/volume.ts), in the top band: a mute button and a slider. On a phone it
// folds into the menu with the account area (App.vue, mobile.css).
import { Volume1, Volume2, VolumeX } from "lucide-vue-next";
import { computed } from "vue";
import { effectiveVolume, setVolume, toggleMute, volumeState } from "../audio/volume";

const percent = computed(() => Math.round(effectiveVolume.value * 100));
const silent = computed(() => effectiveVolume.value === 0);

function onInput(event: Event) {
  setVolume(Number((event.target as HTMLInputElement).value) / 100);
}
</script>

<template>
  <div class="volume" data-testid="volume-control">
    <button
      type="button" class="volume-mute icon-only" :aria-pressed="volumeState.muted"
      :aria-label="silent ? 'Unmute' : 'Mute'" :title="silent ? 'Unmute' : 'Mute'" data-testid="volume-mute"
      @click="toggleMute"
    >
      <VolumeX v-if="silent" :size="16" aria-hidden="true" />
      <Volume1 v-else-if="percent < 50" :size="16" aria-hidden="true" />
      <Volume2 v-else :size="16" aria-hidden="true" />
    </button>
    <input
      type="range" min="0" max="100" step="1" :value="percent" aria-label="Volume" :aria-valuetext="`${percent}%`" :title="`Volume ${percent}%`"
      :style="{ '--fill': `${percent}%` }" data-testid="volume-slider" @input="onInput"
    />
  </div>
</template>
