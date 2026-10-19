<script setup lang="ts">
// The audio editing recipe of a line, as read-only text: shown instead of the waveform editor and "Listen and
// compare" where recordings cannot be played (the public read-only view, docs/public-access.md). The summary
// is the server's own (common/audio_edit.py summary), so it reads exactly as the build applies the recipe.

import { SlidersHorizontal } from "lucide-vue-next";
import type { SlotDetail } from "../../api/types";
import type { Draft } from "../../matching/draft";

defineProps<{ detail: SlotDetail; draft: Draft }>();
</script>

<template>
  <section class="block" aria-label="Audio editing" data-section="editor" data-testid="recipe-summary">
    <h3><SlidersHorizontal :size="15" aria-hidden="true" /> Audio editing</h3>
    <p v-if="(draft.audioSource === 'ce_concat' || draft.audioSource === 'ce_mix') && draft.audioRef">
      {{ draft.audioSource === "ce_concat" ? "Joined" : "Played together" }}: <span class="mono">{{ draft.audioRef }}</span>
      {{ draft.audioSource === "ce_concat" ? "then" : "with" }} <span class="mono">{{ draft.audioRefB }}</span>.
      Recipe: <strong data-testid="recipe-summary-text">{{ detail.edit?.summary || "no edits" }}</strong>
    </p>
    <p v-else-if="draft.audioSource === 'ce' && draft.audioRef">
      Recipe: <strong data-testid="recipe-summary-text">{{ detail.edit?.summary || "no edits" }}</strong>
    </p>
    <p v-else class="muted">No Campaign Evolved recording replaces this line, so there is no editing recipe.</p>
    <p class="small muted">The waveform editor is available to the project owner only.</p>
  </section>
</template>
