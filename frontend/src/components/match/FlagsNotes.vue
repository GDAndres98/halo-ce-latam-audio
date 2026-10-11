<script setup lang="ts">
// The owner's flags and notes for the line. They are metadata, independent of the audio and subtitle
// approvals: they can change while both are approved, and they never change an approved decision.

import { Flag } from "lucide-vue-next";
import type { Draft } from "../../matching/draft";
import { FLAGS, FLAG_ORDER } from "./flags";

defineProps<{ draft: Draft }>();
</script>

<template>
  <section class="block" aria-label="Flags and notes" data-section="flags">
    <h3><Flag :size="15" aria-hidden="true" /> Flags &amp; notes</h3>
    <div class="flag-list">
      <label v-for="name in FLAG_ORDER" :key="name" class="opt" :title="FLAGS[name].hint" :data-testid="`flag-${name}`">
        <input v-model="draft[name]" type="checkbox" />
        <component :is="FLAGS[name].icon" :size="16" :class="`flag-${name}`" aria-hidden="true" />
        {{ FLAGS[name].label }}
      </label>
    </div>
    <p class="small muted">{{ FLAGS.radio.hint }}</p>
    <label class="block-label">Notes
      <textarea v-model="draft.notes" rows="2" maxlength="2000"></textarea>
    </label>
  </section>
</template>
