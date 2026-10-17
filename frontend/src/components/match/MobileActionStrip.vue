<script setup lang="ts">
// Phone only: Save draft and Save & next, kept in reach of the thumb above the bottom navigation whenever the
// open line has something to save or to say, on any pane. It saves exactly what the save bar saves (one
// request, never an approval); approvals and Needs rework stay in the save bar, behind their confirmations.
// It steps aside while the save bar itself is on screen, so there is never a second set of buttons in view.

import { ChevronRight, Save, SkipForward, X } from "lucide-vue-next";
import { computed } from "vue";
import type { MatchState } from "../../composables/useMatch";
import type { Pane } from "../../layout/layoutMode";
import { draftProblems } from "../../matching/draft";
import { readOnly } from "../../auth/session";

const props = defineProps<{ match: MatchState; pane: Pane; saveBarVisible: boolean }>();
const emit = defineEmits<{ saveNext: []; review: [] }>();

const dirty = computed(() => Boolean(props.match.detail.value) && props.match.dirty());
const problems = computed(() => (props.match.detail.value ? draftProblems(props.match.draft) : []));
const blocked = computed(
  () => !dirty.value || props.match.saving.value || props.match.loading.value || problems.value.length > 0,
);
const note = computed(() => props.match.error.value || props.match.message.value);
const shown = computed(
  () => !readOnly.value && !(props.pane === "match" && props.saveBarVisible) && (dirty.value || props.match.saving.value || Boolean(note.value)),
);

function dismiss() {
  props.match.message.value = "";
}
</script>

<template>
  <section v-if="shown" class="action-strip" aria-label="Save this line" data-testid="action-strip">
    <p v-if="note" class="strip-note small" :class="match.error.value ? 'error' : 'ok'" role="status">
      <span>{{ note }}</span>
      <button v-if="pane !== 'match'" type="button" class="link icon-label" data-testid="strip-review" @click="emit('review')">
        Review <ChevronRight :size="14" aria-hidden="true" />
      </button>
      <button v-if="!match.error.value" type="button" class="icon-only" aria-label="Dismiss the message" @click="dismiss">
        <X :size="16" aria-hidden="true" />
      </button>
    </p>
    <div v-if="dirty || match.saving.value" class="strip-actions">
      <span class="small" :class="problems.length ? 'warn' : 'muted'">
        {{ match.saving.value ? "Saving…" : problems.length ? problems[0] : "Unsaved changes" }}
      </span>
      <button type="button" class="primary icon-label" :disabled="blocked" data-testid="strip-save" @click="match.save()">
        <Save :size="16" aria-hidden="true" /> Save
      </button>
      <button type="button" class="icon-label" :disabled="blocked" title="Save the draft, then open the next unmatched line" @click="emit('saveNext')">
        <SkipForward :size="16" aria-hidden="true" /> Next
      </button>
    </div>
  </section>
</template>
