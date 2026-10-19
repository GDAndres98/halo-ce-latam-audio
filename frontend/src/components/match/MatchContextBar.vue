<script setup lang="ts">
// The open line, kept in view at the top of every pane on a phone: its MCC key, its match / audio / subtitle
// state, whether it has unsaved changes, and a button to hear Spain's original again while browsing the
// candidates. On the Matching pane it also jumps to the sections of the (long) decision panel.

import { ChevronRight, ListMusic } from "lucide-vue-next";
import { computed } from "vue";
import type { MatchState } from "../../composables/useMatch";
import type { Pane } from "../../layout/layoutMode";
import { canListen, readOnly } from "../../auth/session";
import { markFor } from "../../matching/status";
import AudioButton from "../AudioButton.vue";

const props = defineProps<{ match: MatchState; slotId: string | null; mccUrl: string | null; pane: Pane }>();
const emit = defineEmits<{ jump: [section: string]; browse: [] }>();

const SECTIONS: { id: string; label: string }[] = [
  { id: "replacement", label: "Audio" },
  { id: "flags", label: "Flags" },
  { id: "editor", label: "Edit" },
  { id: "compare", label: "Compare" },
  { id: "subtitles", label: "Subtitles" },
  { id: "save", label: "Save" },
];

const sections = computed(() =>
  SECTIONS.filter((s) => (s.id !== "compare" || canListen.value) && (s.id !== "save" || !readOnly.value)),
);
const detail = computed(() => props.match.detail.value);
/** The key is shown at once from the URL, even while the line loads. */
const key = computed(() => props.slotId ?? "");
const loaded = computed(() => Boolean(detail.value && detail.value.slot_id === props.slotId));
const marks = computed(() => {
  const stored = detail.value?.mapping ?? null;
  return [
    { letter: "M", name: "match", mark: markFor(props.match.draft.matchStatus ?? "unreviewed") },
    { letter: "A", name: "audio", mark: markFor(stored?.audio.status ?? "unreviewed") },
    { letter: "S", name: "subtitle", mark: markFor(stored?.subtitle.status ?? "unreviewed") },
  ];
});
</script>

<template>
  <div class="match-context" data-testid="match-context">
    <template v-if="slotId">
      <div class="context-line">
        <AudioButton v-if="mccUrl && loaded" :url="mccUrl" label="ES" title="Spain's original recording" />
        <code class="context-key" :title="key" data-testid="context-key">{{ key }}</code>
        <span v-if="loaded" class="context-marks">
          <span
            v-for="m in marks" :key="m.letter" class="pill" :class="m.mark.tone"
            :title="`${m.name}: ${m.mark.word}`" :aria-label="`${m.name}: ${m.mark.word}`"
          >{{ m.letter }}{{ m.mark.glyph }}</span>
          <span v-if="match.dirty()" class="pill warn unsaved-pill" data-testid="context-unsaved">unsaved</span>
        </span>
        <span v-else class="small muted">loading…</span>
      </div>
      <nav v-if="pane === 'match' && loaded" class="section-chips" aria-label="Sections of the decision">
        <button v-for="s in sections" :key="s.id" type="button" class="chip" @click="emit('jump', s.id)">{{ s.label }}</button>
      </nav>
    </template>
    <div v-else class="context-line">
      <span class="small muted">No MCC line open.</span>
      <button type="button" class="link icon-label" @click="emit('browse')">
        <ListMusic :size="15" aria-hidden="true" /> Choose a line <ChevronRight :size="14" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
