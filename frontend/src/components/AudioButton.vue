<script setup lang="ts">
// One-click play/stop for a clip (lists and candidates). The state is shared: see audio/player.ts.
import { computed } from "vue";
import { Play, Square } from "lucide-vue-next";
import { isPlaying, togglePlay } from "../audio/player";

const props = defineProps<{ url: string; label: string; disabled?: boolean; title?: string }>();
const active = computed(() => isPlaying(props.url));
const name = computed(() => `${active.value ? "Stop" : "Play"} ${props.title ?? props.label}`.trim());
</script>

<template>
  <button
    class="play icon-label"
    :class="{ active }"
    :disabled="disabled"
    type="button"
    :aria-pressed="active"
    :aria-label="label ? undefined : name"
    :title="name"
    @click="togglePlay(url)"
  >
    <Square v-if="active" :size="13" aria-hidden="true" />
    <Play v-else :size="13" aria-hidden="true" />
    <template v-if="label">{{ label }}</template>
  </button>
</template>
