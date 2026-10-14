<script setup lang="ts">
// A small icon link that saves a recording served by the Studio (a WAV) under a readable file name.
// The file comes from the host through the same URL the players use; nothing is converted.

import { Download } from "lucide-vue-next";
import { computed } from "vue";

const props = defineProps<{ url: string; fileName: string; label: string; text?: string }>();

/** Characters that are unsafe in file names on Windows, macOS or Linux become "_". */
const safeName = computed(() => props.fileName.replace(/[^\w.-]+/g, "_"));
</script>

<template>
  <a class="button download-link" :class="text ? 'icon-label small-button' : 'icon-only'" :href="url" :download="safeName" :aria-label="label" :title="label">
    <Download :size="14" aria-hidden="true" /><span v-if="text">{{ text }}</span>
  </a>
</template>
