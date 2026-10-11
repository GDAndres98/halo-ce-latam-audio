<script setup lang="ts">
// A panel's title band: icon, name in the display face, an optional short identifier code, and actions on the
// right (slot). It spans the whole panel and ends in a rule (styles/panels.css, .panel-head).
import type { Component } from "vue";

withDefaults(defineProps<{ title: string; icon?: Component; code?: string; level?: 2 | 3; titleId?: string }>(), { level: 2 });
</script>

<template>
  <header class="panel-head">
    <component :is="`h${level}`" :id="titleId">
      <component :is="icon" v-if="icon" :size="16" aria-hidden="true" />
      {{ title }}
    </component>
    <span v-if="code" class="code" aria-hidden="true">{{ code }}</span>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </header>
</template>
