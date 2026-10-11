<script setup lang="ts">
defineProps<{ label: string; tone?: "ok" | "warn" | "bad" | "muted" }>();
</script>

<template>
  <span class="badge" :class="tone ?? 'muted'">{{ label }}</span>
</template>
