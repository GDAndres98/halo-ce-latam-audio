<script setup lang="ts">
// Loading, empty, error, warning and success messages: always an icon and words, never colour alone.
import { CircleAlert, CircleCheck, Inbox, TriangleAlert } from "lucide-vue-next";

defineProps<{ kind: "loading" | "empty" | "error" | "warning" | "success" }>();
</script>

<template>
  <div class="state" :class="kind" :role="kind === 'error' ? 'alert' : kind === 'loading' ? undefined : 'status'">
    <span v-if="kind === 'loading'" class="loader" aria-hidden="true"><i></i><i></i><i></i></span>
    <CircleAlert v-else-if="kind === 'error'" :size="18" aria-hidden="true" />
    <TriangleAlert v-else-if="kind === 'warning'" :size="18" aria-hidden="true" />
    <CircleCheck v-else-if="kind === 'success'" :size="18" aria-hidden="true" />
    <Inbox v-else :size="18" aria-hidden="true" />
    <p><slot /></p>
  </div>
</template>
