<script setup lang="ts">
// Save and approval controls for the line. Approval and rework are deliberate: each is a button press
// with a confirmation, and each explains why it is unavailable. Nothing is approved by a shortcut.

import { BadgeCheck, Save, SkipForward, Wrench } from "lucide-vue-next";
import { computed } from "vue";
import type { ApprovalField } from "../../api/types";
import { canApprove, canRework, draftProblems } from "../../matching/draft";
import { confirmAction } from "../../composables/useConfirm";
import type { MatchState } from "../../composables/useMatch";
import StateMessage from "../ui/StateMessage.vue";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{ match: MatchState }>();
// "Save & next unmatched": saves the draft (never approves), then the parent opens the next unmatched line.
const emit = defineEmits<{ saveNext: [] }>();

const stored = computed(() => props.match.detail.value?.mapping ?? null);
const baseline = computed(() => props.match.baseline.value);
const problems = computed(() => draftProblems(props.match.draft));
const dirty = computed(() => props.match.dirty());
const approval = computed(() => ({
  audio: canApprove("audio", stored.value, props.match.draft, baseline.value ?? props.match.draft),
  subtitle: canApprove("subtitle", stored.value, props.match.draft, baseline.value ?? props.match.draft),
}));
const rework = computed(() => ({ audio: canRework("audio", stored.value), subtitle: canRework("subtitle", stored.value) }));
const conflict = computed(() => /changed/.test(props.match.error.value));

const FIELD_NAME: Record<ApprovalField, string> = { audio: "audio", subtitle: "subtitle" };

function saveDraft() {
  void props.match.save();
}

async function approve(field: ApprovalField) {
  const ok = await confirmAction({
    title: `Approve ${FIELD_NAME[field]}`,
    message:
      `Approve the ${FIELD_NAME[field]} decision for this line?\n\n` +
      "Approved decisions are read-only. To change one later, mark it Needs rework first.",
    confirmLabel: "Yes, approve",
  });
  if (ok) await props.match.save([{ action: "approve", field }]);
}

async function markRework(field: ApprovalField) {
  const ok = await confirmAction({
    title: `Needs rework: ${FIELD_NAME[field]}`,
    message:
      `Mark the ${FIELD_NAME[field]} decision as Needs rework?\n\n` +
      "It becomes editable again and must be approved again before it counts.",
    confirmLabel: "Mark Needs rework",
    tone: "warning",
  });
  if (ok) await props.match.rework(field);
}
</script>

<template>
  <section class="block approvals action-band">
    <h3><BadgeCheck :size="15" aria-hidden="true" /> Save and approve</h3>

    <ul v-if="problems.length" class="problems">
      <li v-for="p in problems" :key="p">{{ p }}</li>
    </ul>

    <div class="row">
      <button type="button" class="primary icon-label" :disabled="!dirty || match.saving.value || problems.length > 0" @click="saveDraft">
        <Save :size="16" aria-hidden="true" /> Save draft (Ctrl+S)
      </button>
      <button
        type="button"
        class="icon-label"
        :disabled="!dirty || match.saving.value || problems.length > 0"
        title="Save the draft, then open the next unmatched line (Ctrl+Enter). Approves nothing."
        @click="emit('saveNext')"
      >
        <SkipForward :size="16" aria-hidden="true" /> Save &amp; next unmatched
      </button>
      <StatusBadge v-if="dirty" label="Unsaved changes." tone="warn" />
      <span v-else class="small muted">No unsaved changes.</span>
    </div>

    <div class="approval-grid">
      <div>
        <button type="button" :disabled="!approval.audio.allowed || match.saving.value" class="approve icon-label" :title="approval.audio.reason" @click="approve('audio')">
          <BadgeCheck :size="16" aria-hidden="true" /> Approve audio
        </button>
        <p v-if="!approval.audio.allowed" class="small muted">{{ approval.audio.reason }}</p>
        <button v-if="rework.audio.allowed" type="button" class="link icon-label" :disabled="match.saving.value" @click="markRework('audio')">
          <Wrench :size="14" aria-hidden="true" /> Needs rework (audio)
        </button>
      </div>
      <div>
        <button type="button" :disabled="!approval.subtitle.allowed || match.saving.value" class="approve icon-label" :title="approval.subtitle.reason" @click="approve('subtitle')">
          <BadgeCheck :size="16" aria-hidden="true" /> Approve subtitle
        </button>
        <p v-if="!approval.subtitle.allowed" class="small muted">{{ approval.subtitle.reason }}</p>
        <button v-if="rework.subtitle.allowed" type="button" class="link icon-label" :disabled="match.saving.value" @click="markRework('subtitle')">
          <Wrench :size="14" aria-hidden="true" /> Needs rework (subtitle)
        </button>
      </div>
    </div>

    <StateMessage v-if="match.message.value" kind="success" class="feedback small">{{ match.message.value }}</StateMessage>
    <StateMessage v-if="match.error.value" kind="error" class="feedback small">
      {{ match.error.value }}
      <button v-if="conflict" type="button" class="link" @click="match.reloadKeepingDraft()">Reload and keep my edits</button>
    </StateMessage>
  </section>
</template>
