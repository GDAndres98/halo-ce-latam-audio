<script setup lang="ts">
// Approval and rework of one decision (audio or subtitle), shown in that decision's section. Approval and
// rework are deliberate: each is a button press with a confirmation, and each explains why it is
// unavailable. Nothing is approved by a shortcut, and the two decisions are approved independently.

import { BadgeCheck, Wrench } from "lucide-vue-next";
import { computed } from "vue";
import type { ApprovalField } from "../../api/types";
import { canApprove, canRework } from "../../matching/draft";
import { confirmAction } from "../../composables/useConfirm";
import type { MatchState } from "../../composables/useMatch";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{ match: MatchState; field: ApprovalField }>();

const stored = computed(() => props.match.detail.value?.mapping ?? null);
const status = computed(() => stored.value?.[props.field].status ?? null);
const approval = computed(() =>
  canApprove(props.field, stored.value, props.match.draft, props.match.baseline.value ?? props.match.draft),
);
const rework = computed(() => canRework(props.field, stored.value));
const name = computed(() => (props.field === "audio" ? "audio" : "subtitle"));
const tone = computed(() =>
  status.value === "approved" ? "ok" : status.value === "needs_rework" ? "bad" : status.value ? "warn" : "muted",
);

async function approve() {
  const ok = await confirmAction({
    title: `Approve ${name.value}`,
    message:
      `Approve the ${name.value} decision for this line?\n\n` +
      "Approved decisions are read-only. To change one later, mark it Needs rework first.",
    confirmLabel: "Yes, approve",
  });
  if (ok) await props.match.save([{ action: "approve", field: props.field }]);
}

async function markRework() {
  const ok = await confirmAction({
    title: `Needs rework: ${name.value}`,
    message:
      `Mark the ${name.value} decision as Needs rework?\n\n` +
      "It becomes editable again and must be approved again before it counts.",
    confirmLabel: "Mark Needs rework",
    tone: "warning",
  });
  if (ok) await props.match.rework(props.field);
}
</script>

<template>
  <div class="approval-controls" :data-testid="`approval-${field}`">
    <StatusBadge :label="`${name}: ${status ? status.replace('_', ' ') : 'not saved'}`" :tone="tone" />
    <button
      type="button"
      class="approve icon-label"
      :disabled="!approval.allowed || match.saving.value"
      :title="approval.reason"
      @click="approve"
    >
      <BadgeCheck :size="16" aria-hidden="true" /> Approve {{ name }}
    </button>
    <button v-if="rework.allowed" type="button" class="link icon-label" :disabled="match.saving.value" @click="markRework">
      <Wrench :size="14" aria-hidden="true" /> Needs rework ({{ name }})
    </button>
    <span v-else-if="!approval.allowed" class="small muted">{{ approval.reason }}</span>
  </div>
</template>
