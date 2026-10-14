<script setup lang="ts">
// One-click play/stop for a clip (lists and candidates). The state is shared: see audio/player.ts.
import { computed } from "vue";
import { LoaderCircle, Play, Square } from "lucide-vue-next";
import { isLoading, isPlaying, togglePlay } from "../audio/player";

const props = defineProps<{ url: string; label: string; disabled?: boolean; title?: string }>();
const active = computed(() => isPlaying(props.url));
const loading = computed(() => isLoading(props.url));
const name = computed(() => `${active.value ? "Stop" : "Play"} ${props.title ?? props.label}`.trim());
</script>

<template>
  <button
    class="play icon-label"
    :class="{ active, loading }"
    :aria-busy="loading"
    :disabled="disabled"
    type="button"
    :aria-pressed="active"
    :aria-label="label ? undefined : name"
    :title="name"
    @click="togglePlay(url)"
  >
    <LoaderCircle v-if="loading" :size="13" class="spin" aria-hidden="true" />
    <Square v-else-if="active" :size="13" aria-hidden="true" />
    <Play v-else :size="13" aria-hidden="true" />
    <template v-if="label">{{ label }}</template>
  </button>
</template>
