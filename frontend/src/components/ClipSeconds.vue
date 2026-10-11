<script setup lang="ts">
// The length of a clip in seconds. Uses the duration the API already knows; otherwise reads it from the
// clip's header once the row scrolls into view (the API decodes a recording the first time it is asked for
// it, so only visible rows are measured).

import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { clipDuration } from "../audio/clipInfo";

const props = defineProps<{ url: string; known?: number | null; disabled?: boolean }>();

const seconds = ref<number | null>(props.known ?? null);
const el = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

async function measure() {
  if (seconds.value !== null || props.disabled) return;
  seconds.value = await clipDuration(props.url);
}

function observe() {
  observer?.disconnect();
  if (seconds.value !== null || props.disabled || !el.value) return;
  observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      observer?.disconnect();
      void measure();
    }
  });
  observer.observe(el.value);
}

watch(
  () => [props.url, props.known],
  () => {
    seconds.value = props.known ?? null;
    observe();
  },
);
onMounted(observe);
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <span ref="el" class="mono small clip-seconds" data-testid="clip-seconds">{{
    disabled ? "—" : seconds === null ? "… s" : `${seconds.toFixed(2)} s`
  }}</span>
</template>
