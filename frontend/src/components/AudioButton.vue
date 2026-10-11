<script setup lang="ts">
import { computed } from "vue";
import { isPlaying, togglePlay } from "../audio/player";

const props = defineProps<{ url: string; label: string; disabled?: boolean }>();
const active = computed(() => isPlaying(props.url));
</script>

<template>
  <button class="play" :class="{ active }" :disabled="disabled" type="button" @click="togglePlay(url)">
    {{ active ? "■" : "▶" }} {{ label }}
  </button>
</template>
