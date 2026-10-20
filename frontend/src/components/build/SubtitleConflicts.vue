<script setup lang="ts">
// Subtitle conflicts, line by line: the takes of one MCC tag share one subtitle entry (key), and their approved
// subtitles disagree, so the build leaves that entry with MCC's text. Each take shows what it would write and
// links to it in Matching, where the owner decides. Read-only (the outcomes come from the build planner).

import { RouterLink } from "vue-router";
import type { SubtitleConflict, SubtitleConflictTake } from "../../api/types";

defineProps<{ conflicts: SubtitleConflict[] }>();

const EXPLAIN: Record<string, string> = {
  different_texts_for_one_subtitle_key:
    "These takes share one subtitle entry, but their approved subtitles have different texts.",
  keep_and_change_for_one_subtitle_key:
    "These takes share one subtitle entry: one keeps MCC's text and another changes it.",
  empty_subtitle_not_agreed_by_every_take:
    "\"No subtitle\" hides this line for every take, but not every take has an approved \"no subtitle\".",
};
const explain = (code: string) => EXPLAIN[code] ?? code.replace(/_/g, " ");
const shortTag = (tag: string) => tag.split("\\").pop() ?? tag;
const SOURCE: Record<string, string> = { ce_locres: "CE text", custom: "custom text" };

function outcome(t: SubtitleConflictTake): string {
  switch (t.outcome) {
    case "keep":
      return "keep MCC text";
    case "empty":
      return "no subtitle";
    case "not_approved":
      return t.status ? `no approved "no subtitle" (subtitle ${t.status})` : `no approved "no subtitle" (no decision)`;
    case "unknown":
      return "not recorded";
    default:
      return SOURCE[t.source ?? ""] ?? "text";
  }
}
/** The take's line in Matching (the URL Matching itself uses: ?level=<folder>&slot=<slot_id>). */
function matchLink(c: SubtitleConflict, t: SubtitleConflictTake) {
  const level = t.level ?? c.level;
  return { path: "/match", query: level ? { level, slot: t.slot_id } : { slot: t.slot_id } };
}
const takes = (c: SubtitleConflict): SubtitleConflictTake[] =>
  c.takes ?? c.slots.map((slot_id) => ({ slot_id, level: c.level ?? null, outcome: "unknown", text: null,
                                         source: null, status: null, result: null }));
</script>

<template>
  <ul class="subtitle-conflicts plain" data-testid="subtitle-conflicts">
    <li v-for="c in conflicts" :key="c.key_hex" class="conflict-group" data-testid="conflict-group" :data-key="c.key_hex">
      <p class="conflict-head">
        <strong class="mono">{{ shortTag(c.mcc_tag) }}</strong> <code class="muted">{{ c.key_hex }}</code>
      </p>
      <p class="small">{{ explain(c.code) }} MCC's text stays until they agree.</p>
      <ul class="plain conflict-takes">
        <li v-for="t in takes(c)" :key="t.slot_id" data-testid="conflict-take" :data-slot="t.slot_id" :data-outcome="t.outcome">
          <RouterLink
            :to="matchLink(c, t)"
            class="mono"
            title="Open this take in Matching"
          >{{ t.slot_id }}</RouterLink>
          <span class="muted"> · {{ outcome(t) }}</span>
          <q v-if="t.outcome === 'text'" class="conflict-text">{{ t.text }}</q>
        </li>
      </ul>
    </li>
  </ul>
</template>
