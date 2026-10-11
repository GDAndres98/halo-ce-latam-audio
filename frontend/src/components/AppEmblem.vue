<script setup lang="ts">
// The Studio's emblem: a tilted ring around a small sphere, in menu blue. Original artwork (not the Halo logo).
// The ring's far half is drawn behind the sphere and its near half in front of it.
defineProps<{ size?: number }>();
</script>

<template>
  <svg class="emblem" :width="size ?? 30" :height="size ?? 30" viewBox="0 0 32 32" aria-hidden="true">
    <g transform="rotate(-24 16 16)" fill="none" stroke-linecap="round">
      <path d="M2 16 A14 5 0 0 1 30 16" stroke="#2f8cff" stroke-width="2" />
      <circle cx="16" cy="16" r="5.5" fill="#0b2552" stroke="#4da3ff" stroke-width="1.6" />
      <path d="M2 16 A14 5 0 0 0 30 16" stroke="#9fd0ff" stroke-width="2.4" />
    </g>
  </svg>
</template>
