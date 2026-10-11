<script setup lang="ts">
// A small icon button that copies a text (an identifier) to the clipboard and says so for a moment.

import { Check, Copy } from "lucide-vue-next";
import { onBeforeUnmount, ref } from "vue";

const props = defineProps<{ text: string; label: string }>();

const state = ref<"idle" | "copied" | "failed">("idle");
let timer: ReturnType<typeof setTimeout> | undefined;

async function copy() {
  try {
    await navigator.clipboard.writeText(props.text);
    state.value = "copied";
  } catch {
    state.value = "failed"; // clipboard blocked by the browser: the text stays selectable on the page
  }
  clearTimeout(timer);
  timer = setTimeout(() => (state.value = "idle"), 1600);
}

onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <button
    type="button"
    class="icon-only copy-button"
    :class="state"
    :aria-label="label"
    :title="state === 'copied' ? 'Copied' : state === 'failed' ? 'Could not copy: select the text instead' : label"
    @click="copy"
  >
    <Check v-if="state === 'copied'" :size="14" aria-hidden="true" />
    <Copy v-else :size="14" aria-hidden="true" />
    <span class="sr-only" role="status">{{ state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "" }}</span>
  </button>
</template>
