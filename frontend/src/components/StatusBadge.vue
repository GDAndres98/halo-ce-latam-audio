<script setup lang="ts">
// A status: an icon and a word, in the tone's colour. The icon and the word carry the meaning; the colour
// only repeats it.
import { CircleCheck, CircleDashed, CircleDot, Info, OctagonAlert } from "lucide-vue-next";

defineProps<{ label: string; tone?: "ok" | "warn" | "bad" | "muted" | "info" }>();
</script>

<template>
  <span class="badge" :class="tone ?? 'muted'">
    <CircleCheck v-if="tone === 'ok'" :size="12" aria-hidden="true" />
    <CircleDot v-else-if="tone === 'warn'" :size="12" aria-hidden="true" />
    <OctagonAlert v-else-if="tone === 'bad'" :size="12" aria-hidden="true" />
    <Info v-else-if="tone === 'info'" :size="12" aria-hidden="true" />
    <CircleDashed v-else :size="12" aria-hidden="true" />{{ label }}
  </span>
</template>
