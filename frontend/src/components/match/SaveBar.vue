<script setup lang="ts">
// The save controls, kept in view at the bottom of the centre column. One Save draft writes the whole
// decision of the line in one request: audio (with its editing), subtitle, flags and notes. Saving never
// approves anything; approvals are in the audio and subtitle sections.

import { Save, SkipForward } from "lucide-vue-next";
import { computed } from "vue";
import { draftProblems } from "../../matching/draft";
import type { MatchState } from "../../composables/useMatch";
import StateMessage from "../ui/StateMessage.vue";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{ match: MatchState }>();
// "Save & next unmatched": saves the draft (never approves), then the parent opens the next unmatched line.
const emit = defineEmits<{ saveNext: [] }>();

const problems = computed(() => draftProblems(props.match.draft));
const dirty = computed(() => props.match.dirty());
const conflict = computed(() => /changed/.test(props.match.error.value));
const blocked = computed(() => !dirty.value || props.match.saving.value || problems.value.length > 0);
</script>

<template>
  <section class="save-bar action-band" aria-label="Save the decision">
    <ul v-if="problems.length" class="problems">
      <li v-for="p in problems" :key="p">{{ p }}</li>
    </ul>

    <div class="row">
      <button
        type="button"
        class="primary icon-label"
        :disabled="blocked"
        title="Save the audio, subtitle, flags and notes together (Ctrl+S). Approves nothing."
        data-testid="save-draft"
        @click="match.save()"
      >
        <Save :size="16" aria-hidden="true" /> Save draft (Ctrl+S)
      </button>
      <button
        type="button"
        class="icon-label"
        :disabled="blocked"
        title="Save the draft, then open the next unmatched line (Ctrl+Enter). Approves nothing."
        @click="emit('saveNext')"
      >
        <SkipForward :size="16" aria-hidden="true" /> Save &amp; next unmatched
      </button>
      <StatusBadge v-if="match.saving.value" label="Saving…" tone="info" />
      <StatusBadge v-else-if="dirty" label="Unsaved changes" tone="warn" />
      <span v-else class="small muted">No unsaved changes.</span>
    </div>

    <StateMessage v-if="match.message.value" kind="success" class="feedback small">{{ match.message.value }}</StateMessage>
    <StateMessage v-if="match.error.value" kind="error" class="feedback small">
      {{ match.error.value }}
      <button v-if="conflict" type="button" class="link" @click="match.reloadKeepingDraft()">Reload and keep my edits</button>
    </StateMessage>
  </section>
</template>
