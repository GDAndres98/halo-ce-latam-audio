<script setup lang="ts">
// The matching workspace: MCC lines (left), the decision for the selected line (centre), and Campaign
// Evolved candidates (right). The selected line and every filter are kept in the URL, so reloading or
// going back returns to the same place.

import { Keyboard, LayoutTemplate } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import { api, audioUrl } from "../api/client";
import type { LevelProgress, SlotRow } from "../api/types";
import { stop, togglePlay } from "../audio/player";
import { stopCurrent } from "../audio/transport";
import CeColumn from "../components/match/CeColumn.vue";
import MccColumn from "../components/match/MccColumn.vue";
import MatchPanel from "../components/match/MatchPanel.vue";
import { confirmAction } from "../composables/useConfirm";
import { useMatch } from "../composables/useMatch";
import { useShortcuts } from "../composables/useShortcuts";
import SplitHandle from "../layout/SplitHandle.vue";
import { useWorkspaceLayout } from "../layout/useWorkspaceLayout";

interface ColumnHandle {
  move: (delta: number) => void;
  focusSearch: () => void;
}

interface MccHandle extends ColumnHandle {
  updateRow: (row: SlotRow, progress?: LevelProgress) => void;
  nextUnmatched: () => string | null;
}

interface CandidateHandle extends ColumnHandle {
  playNth: (index: number) => void;
}

const route = useRoute();
const router = useRouter();
const match = useMatch();

const levels = ref<string[]>([]);
const missions = ref<string[]>([]);
const focusedRef = ref<string | null>(null);
const mccColumn = ref<MccHandle | null>(null);
const workspaceEl = ref<HTMLElement | null>(null);
const layout = useWorkspaceLayout(workspaceEl);
const ceColumn = ref<CandidateHandle | null>(null);

// ---- URL state: everything the user can change is reflected in the address.
const param = (name: string, fallback: string) => String(route.query[name] ?? fallback);
const selectedSlot = computed(() => (route.query.slot ? String(route.query.slot) : null));

function setQuery(changes: Record<string, string | undefined>) {
  const query: LocationQueryRaw = { ...route.query };
  for (const [key, value] of Object.entries(changes)) {
    if (value === undefined || value === "" || value === "all" && key === "cm") delete query[key];
    else query[key] = value;
  }
  void router.replace({ query });
}

const mccLevel = computed({ get: () => param("level", "a10"), set: (v: string) => setQuery({ level: v }) });
const mccStatus = computed({ get: () => param("status", ""), set: (v: string) => setQuery({ status: v }) });
const mccQuery = computed({ get: () => param("q", ""), set: (v: string) => setQuery({ q: v }) });
const ceMission = computed({ get: () => param("cm", "all"), set: (v: string) => setQuery({ cm: v }) });
const ceQuery = computed({ get: () => param("cq", ""), set: (v: string) => setQuery({ cq: v }) });
const ceSubtitles = computed({ get: () => param("cs", ""), set: (v: string) => setQuery({ cs: v }) });
const ceHideUsed = computed({ get: () => route.query.ch === "1", set: (v: boolean) => setQuery({ ch: v ? "1" : undefined }) });

// ---- Selecting a line. Leaving a line with unsaved changes asks first. The draft is also kept for this
// stored version in the browser session, so answering "leave" does not lose it entirely.
async function selectSlot(slotId: string) {
  if (slotId === selectedSlot.value) return;
  if (match.dirty()) {
    const leave = await confirmAction({
      title: "Unsaved changes",
      message:
        "This line has unsaved changes. Leave it without saving?\n\n" +
        "The draft is kept in this browser session for this version of the line.",
      confirmLabel: "Leave without saving",
      cancelLabel: "Stay on this line",
      tone: "warning",
    });
    if (!leave) return;
  }
  setQuery({ slot: slotId });
}

watch(
  selectedSlot,
  (slotId) => {
    if (slotId) void match.load(slotId);
  },
  { immediate: false },
);

// ---- After a save: only the saved row and the level's counters change in the list (server values).
match.onSaved((response) => {
  if (response.row) mccColumn.value?.updateRow(response.row, response.progress);
});

/** Save the draft (no approval), then open the next unmatched line of the list. */
async function saveAndNext() {
  if (match.saving.value) return;
  if (match.dirty() && !(await match.save())) return; // a refused save keeps the draft and the line
  if (!mccColumn.value?.nextUnmatched()) match.message.value = "Saved. No unmatched line left in this list.";
}

// ---- Candidates. Choosing one is always an explicit action (the "Use" button or the s key). Its LATAM
// subtitle is then offered as an unsaved subtitle, unless the subtitle was already decided.
async function useCandidate(ref: string) {
  focusedRef.value = ref;
  if (!(await match.chooseRecording(ref))) return;
  match.message.value =
    match.proposal.value === "proposed"
      ? "Recording chosen; its LATAM subtitle is proposed. Save the draft to keep both."
      : match.proposal.value === "missing"
        ? "Recording chosen. It has no LATAM subtitle: choose the subtitle manually, then save."
        : "Recording chosen. Save the draft to keep it.";
}

const mccUrl = computed(() =>
  match.detail.value ? audioUrl.mcc(match.detail.value.level, "spanish", match.detail.value.spanish.index) : null,
);

/** Which candidate the sound keys refer to: the highlighted row, else the one already chosen. */
const candidateRef = computed(() => focusedRef.value ?? match.draft.audioRef ?? null);

// ---- Keyboard. Single keys; none of them fire while typing (see useShortcuts).
// The keys follow the classic M4 page where it had them: j and k step through the MCC lines, Space plays
// Spain's recording, and 1 to 9 play the candidates. Arrow keys move the candidate highlight.
const playMcc = () => mccUrl.value && togglePlay(mccUrl.value);
useShortcuts({
  " ": playMcc,
  m: playMcc,
  j: () => mccColumn.value?.move(1),
  k: () => mccColumn.value?.move(-1),
  ArrowDown: () => ceColumn.value?.move(1),
  ArrowUp: () => ceColumn.value?.move(-1),
  e: () => candidateRef.value && togglePlay(audioUrl.ce(candidateRef.value, "Spanish(Mexico)")),
  n: () => candidateRef.value && togglePlay(audioUrl.ce(candidateRef.value, "English(US)")),
  s: () => focusedRef.value && void useCandidate(focusedRef.value),
  "1": () => ceColumn.value?.playNth(0),
  "2": () => ceColumn.value?.playNth(1),
  "3": () => ceColumn.value?.playNth(2),
  "4": () => ceColumn.value?.playNth(3),
  "5": () => ceColumn.value?.playNth(4),
  "6": () => ceColumn.value?.playNth(5),
  "7": () => ceColumn.value?.playNth(6),
  "8": () => ceColumn.value?.playNth(7),
  "9": () => ceColumn.value?.playNth(8),
  "/": () => mccColumn.value?.focusSearch(),
  "\\": () => ceColumn.value?.focusSearch(),
  "ctrl+s": () => void match.save(),
  "ctrl+enter": () => void saveAndNext(),
  u: () => mccColumn.value?.nextUnmatched(),
  escape: () => {
    stop();
    stopCurrent();
  },
});

onMounted(async () => {
  // The line first: /api/state can be slow, and a line loaded after it would replace whatever the user
  // already started on that line.
  if (selectedSlot.value) void match.load(selectedSlot.value);
  try {
    const state = await api.state();
    levels.value = state.levels.map((l) => l.level);
    missions.value = state.missions.map((m) => m.mission);
  } catch (e) {
    match.error.value = e instanceof Error ? e.message : String(e);
  }
});
</script>

<template>
  <div class="layout-bar">
    <Keyboard :size="16" class="muted" aria-hidden="true" />
    <ul class="keys" aria-label="Keyboard shortcuts">
      <li><kbd>J</kbd>/<kbd>K</kbd> line</li>
      <li><kbd>Space</kbd> Spain</li>
      <li><kbd>1</kbd>–<kbd>9</kbd> candidate</li>
      <li><kbd>↑</kbd>/<kbd>↓</kbd> highlight</li>
      <li><kbd>S</kbd> use</li>
      <li><kbd>E</kbd> es-MX · <kbd>N</kbd> EN</li>
      <li><kbd>A</kbd> A/B · <kbd>B</kbd> A then B</li>
      <li><kbd>W</kbd> play edit · <kbd>T</kbd> trim · <kbd>X</kbd> cut</li>
      <li><kbd>Ctrl</kbd>+<kbd>Z</kbd> undo edit</li>
      <li><kbd>Esc</kbd> stop</li>
      <li><kbd>Ctrl</kbd>+<kbd>S</kbd> save</li>
      <li><kbd>Ctrl</kbd>+<kbd>Enter</kbd> save &amp; next · <kbd>U</kbd> next unmatched</li>
    </ul>
    <button type="button" class="icon-label" :disabled="layout.isDefault.value" @click="layout.reset()">
      <LayoutTemplate :size="15" aria-hidden="true" /> Reset layout
    </button>
  </div>
  <div ref="workspaceEl" class="workspace" :class="{ resizing: layout.dragging.value !== null }">
    <MccColumn
      ref="mccColumn"
      v-model:level="mccLevel"
      v-model:status="mccStatus"
      v-model:query="mccQuery"
      :levels="levels"
      :selected-id="selectedSlot"
      @select="selectSlot"
    />
    <SplitHandle
      side="left"
      :width="layout.widths.value.left"
      :dragging="layout.dragging.value === 'left'"
      @drag-start="layout.startDrag('left', $event)"
      @step="(direction, coarse) => layout.step('left', direction, coarse)"
    />
    <MatchPanel :match="match" :slot-id="selectedSlot" @save-next="saveAndNext" />
    <SplitHandle
      side="right"
      :width="layout.widths.value.right"
      :dragging="layout.dragging.value === 'right'"
      @drag-start="layout.startDrag('right', $event)"
      @step="(direction, coarse) => layout.step('right', direction, coarse)"
    />
    <CeColumn
      ref="ceColumn"
      v-model:mission="ceMission"
      v-model:query="ceQuery"
      v-model:hide-used="ceHideUsed"
      v-model:subtitles="ceSubtitles"
      :missions="missions"
      :slot-id="selectedSlot"
      :focused-ref="focusedRef"
      :chosen-refs="match.detail.value ? match.draft.ceRefs : []"
      @focus="focusedRef = $event"
      @use="useCandidate"
    />
  </div>
</template>
