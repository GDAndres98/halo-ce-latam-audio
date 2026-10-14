<script setup lang="ts">
// The pane switcher of the matching workspace on phones and tablets (hidden on a desktop, where the three
// panels are side by side). On a phone it is the bottom navigation: MCC | Matching | Campaign Evolved. On a
// tablet the Matching panel is always shown, so only the two lists are offered, as a segmented control above
// them. Switching panes never reloads anything: every pane stays mounted with its search, its scroll position
// and the unsaved draft.

import { AudioLines, Library, ListMusic } from "lucide-vue-next";
import type { Pane } from "../../layout/layoutMode";

defineProps<{
  /** The pane shown (phone), or the list shown beside the Matching panel (tablet). */
  pane: Pane;
  /** Unsaved changes on the open line: a dot on Matching. */
  dirty: boolean;
  /** Campaign Evolved recordings matched to the open line (saved or not). */
  chosen: number;
}>();
const emit = defineEmits<{ select: [pane: Pane] }>();
</script>

<template>
  <nav class="workspace-tabs" aria-label="Workspace panels">
    <div class="tabs-inner" role="tablist">
      <button
        type="button" role="tab" class="tab tab-mcc" aria-controls="pane-mcc"
        :aria-selected="pane === 'mcc'" data-testid="tab-mcc"
        @click="emit('select', 'mcc')"
      >
        <ListMusic :size="20" aria-hidden="true" />
        <span class="tab-label">MCC</span>
      </button>
      <button
        type="button" role="tab" class="tab tab-match" aria-controls="pane-match"
        :aria-selected="pane === 'match'" data-testid="tab-match"
        @click="emit('select', 'match')"
      >
        <AudioLines :size="20" aria-hidden="true" />
        <span class="tab-label">Matching</span>
        <span v-if="dirty" class="tab-dot" title="Unsaved changes"><span class="sr-only">(unsaved changes)</span></span>
      </button>
      <button
        type="button" role="tab" class="tab tab-ce" aria-controls="pane-ce"
        :aria-selected="pane === 'ce'" data-testid="tab-ce"
        @click="emit('select', 'ce')"
      >
        <Library :size="20" aria-hidden="true" />
        <span class="tab-label">Campaign Evolved</span>
        <span v-if="chosen" class="tab-count" :title="`${chosen} matched to this line`">{{ chosen }}</span>
      </button>
    </div>
  </nav>
</template>
