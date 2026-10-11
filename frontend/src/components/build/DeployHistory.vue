<script setup lang="ts">
// The installer's history (work/m6/deploy_history.jsonl, append-only): every install, failed install and
// restore, newest first.

import { History } from "lucide-vue-next";
import type { DeployEvent } from "../../api/types";
import StatusBadge from "../StatusBadge.vue";

defineProps<{ events: DeployEvent[] }>();

const ACTION = { install: "Install", rollback: "Restore" } as const;
</script>

<template>
  <details class="deploy-history" data-testid="deploy-history" :open="events.length > 0 && events[0].result === 'failed'">
    <summary><History :size="14" aria-hidden="true" /> Install history ({{ events.length }})</summary>
    <ul v-if="events.length" class="small plain">
      <li v-for="(e, i) in events" :key="`${e.at}-${i}`" :data-action="e.action" :data-result="e.result">
        <span class="mono">{{ e.at.replace("T", " ") }}</span>
        {{ ACTION[e.action] }} <strong>{{ e.build }}</strong>
        <StatusBadge :label="e.result === 'ok' ? 'done' : 'failed'" :tone="e.result === 'ok' ? 'ok' : 'bad'" />
        <span class="muted">{{ e.files.map((f) => f.install_rel.split("/").pop()).join(", ") }}</span>
        <div v-if="e.result !== 'ok'" class="error">{{ e.message }}</div>
      </li>
    </ul>
    <p v-else class="small muted">Nothing installed from here yet.</p>
  </details>
</template>
