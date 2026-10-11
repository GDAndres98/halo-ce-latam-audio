<script setup lang="ts">
// A segmented, slanted meter (the original's shield meter), with its label and numbers in words beside it.
import { computed } from "vue";

const props = defineProps<{ label: string; value: number; max: number; tone?: "ok" | "info" }>();
const percent = computed(() => (props.max ? Math.round((100 * props.value) / props.max) : 0));
</script>

<template>
  <div class="hud-meter">
    <div class="hud-meter-text">
      <span class="hud-meter-label">{{ label }}</span>
      <span class="hud-meter-value mono">{{ value }} / {{ max }} <span class="muted">({{ percent }}%)</span></span>
    </div>
    <div
      class="progressbar"
      :class="tone"
      role="progressbar"
      :aria-label="label"
      :aria-valuenow="value"
      aria-valuemin="0"
      :aria-valuemax="max"
    >
      <span :style="{ width: `${percent}%` }"></span>
    </div>
  </div>
</template>
