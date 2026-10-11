<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";

// One clip plays at a time across the page: starting a new one stops the previous.
let playing: HTMLAudioElement | null = null;

const props = defineProps<{ url: string; label: string; disabled?: boolean }>();
const active = ref(false);
let audio: HTMLAudioElement | null = null;

function toggle() {
  if (audio && !audio.paused) {
    audio.pause();
    active.value = false;
    return;
  }
  playing?.pause();
  // Created on first use: decoding only the clips someone listens to keeps the page light.
  audio = new Audio(props.url);
  audio.onended = () => (active.value = false);
  playing = audio;
  active.value = true;
  audio.play().catch(() => (active.value = false));
}

onBeforeUnmount(() => {
  audio?.pause();
  if (playing === audio) playing = null;
});
</script>

<template>
  <button class="play" :class="{ active }" :disabled="disabled" type="button" @click="toggle">
    {{ active ? "■" : "▶" }} {{ label }}
  </button>
</template>
