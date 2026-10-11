<script setup lang="ts">
// The save and approval controls, kept in view at the bottom of the centre column. One Save draft writes the
// whole decision of the line in one request: audio (with its editing), subtitle, flags and notes. Saving
// never approves. The audio and the subtitle are approved separately, or both in one save; every approval
// is a button press with a confirmation.

import { CheckCheck, Save, SkipForward } from "lucide-vue-next";
import { computed } from "vue";
import { canApprove, draftProblems } from "../../matching/draft";
import { confirmAction } from "../../composables/useConfirm";
import ApprovalControls from "./ApprovalControls.vue";
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

const both = computed(() => {
  const stored = props.match.detail.value?.mapping ?? null;
  const baseline = props.match.baseline.value ?? props.match.draft;
  const audio = canApprove("audio", stored, props.match.draft, baseline);
  const subtitle = canApprove("subtitle", stored, props.match.draft, baseline);
  return { allowed: audio.allowed && subtitle.allowed, reason: audio.allowed ? subtitle.reason : audio.reason };
});

async function approveBoth() {
  const ok = await confirmAction({
    title: "Approve audio and subtitle",
    message:
      "Approve both the audio and the subtitle decisions for this line?\n\n" +
      "Approved decisions are read-only. To change one later, mark it Needs rework first.",
    confirmLabel: "Yes, approve both",
  });
  if (ok) {
    await props.match.save([
      { action: "approve", field: "audio" },
      { action: "approve", field: "subtitle" },
    ]);
  }
}
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

    <div class="approval-row" aria-label="Approve">
      <ApprovalControls :match="match" field="audio" />
      <ApprovalControls :match="match" field="subtitle" />
      <button
        type="button"
        class="approve icon-label"
        :disabled="!both.allowed || match.saving.value"
        :title="both.allowed ? 'Approve the audio and the subtitle in one save' : both.reason"
        data-testid="approve-both"
        @click="approveBoth"
      >
        <CheckCheck :size="16" aria-hidden="true" /> Approve both
      </button>
    </div>

    <StateMessage v-if="match.message.value" kind="success" class="feedback small">{{ match.message.value }}</StateMessage>
    <StateMessage v-if="match.error.value" kind="error" class="feedback small">
      {{ match.error.value }}
      <button v-if="conflict" type="button" class="link" @click="match.reloadKeepingDraft()">Reload and keep my edits</button>
    </StateMessage>
  </section>
</template>
