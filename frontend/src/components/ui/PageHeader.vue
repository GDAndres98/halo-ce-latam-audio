<script setup lang="ts">
// The title of a screen: big menu-blue words over a full-width lit rule, as on the original's menu screens.
// Optional icon, a one-line lead, and actions on the right (slot).
import type { Component } from "vue";

defineProps<{ title: string; lead?: string; icon?: Component }>();
</script>

<template>
  <header class="page-head">
    <div>
      <div class="titles">
        <component :is="icon" v-if="icon" :size="26" aria-hidden="true" />
        <h1>{{ title }}</h1>
      </div>
      <p v-if="lead" class="lead">{{ lead }}</p>
    </div>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </header>
</template>
