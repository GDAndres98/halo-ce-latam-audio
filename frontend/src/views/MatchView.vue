<script setup lang="ts">
// The matching workspace: MCC lines (left), the decision for the selected line (centre), and Campaign
// Evolved candidates (right). The selected line and every filter are kept in the URL, so reloading or
// going back returns to the same place.

import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import { api, audioUrl } from "../api/client";
import { stop, togglePlay } from "../audio/player";
import CeColumn from "../components/match/CeColumn.vue";
import MccColumn from "../components/match/MccColumn.vue";
import MatchPanel from "../components/match/MatchPanel.vue";
import { useMatch } from "../composables/useMatch";
import { useShortcuts } from "../composables/useShortcuts";
import SplitHandle from "../layout/SplitHandle.vue";
import { useWorkspaceLayout } from "../layout/useWorkspaceLayout";

interface ColumnHandle {
  move: (delta: number) => void;
  focusSearch: () => void;
}

const route = useRoute();
const router = useRouter();
const match = useMatch();

const levels = ref<string[]>([]);
const missions = ref<string[]>([]);
const focusedRef = ref<string | null>(null);
const mccColumn = ref<ColumnHandle | null>(null);
const workspaceEl = ref<HTMLElement | null>(null);
const layout = useWorkspaceLayout(workspaceEl);
const ceColumn = ref<ColumnHandle | null>(null);

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
const ceHideUsed = computed({ get: () => route.query.ch === "1", set: (v: boolean) => setQuery({ ch: v ? "1" : undefined }) });

// ---- Selecting a line. Leaving a line with unsaved changes asks first. The draft is also kept for this
// stored version in the browser session, so answering "leave" does not lose it entirely.
function selectSlot(slotId: string) {
  if (slotId === selectedSlot.value) return;
  if (match.dirty() && !window.confirm("This line has unsaved changes. Leave it without saving?")) return;
  setQuery({ slot: slotId });
}

watch(
  selectedSlot,
  (slotId) => {
    if (slotId) void match.load(slotId);
  },
  { immediate: false },
);

// ---- Candidates. Choosing one is always an explicit action (the "Use" button or the s key).
function useCandidate(ref: string) {
  const current = match.detail.value?.mapping;
  if (current?.audio.status === "approved") {
    match.error.value = "The audio decision is approved. Mark it Needs rework before choosing another recording.";
    return;
  }
  const draft = match.draft;
  draft.audioSource = "ce";
  draft.audioRef = ref;
  if (!draft.ceRefs.includes(ref)) draft.ceRefs.push(ref);
  draft.matchStatus = "matched";
  focusedRef.value = ref;
  match.message.value = "Recording chosen. Save the draft to keep it.";
}

const mccUrl = computed(() =>
  match.detail.value ? audioUrl.mcc(match.detail.value.level, "spanish", match.detail.value.spanish.index) : null,
);

/** Which candidate the sound keys refer to: the highlighted row, else the one already chosen. */
const candidateRef = computed(() => focusedRef.value ?? match.draft.audioRef ?? null);

// ---- Keyboard. Single keys; none of them fire while typing (see useShortcuts).
useShortcuts({
  m: () => mccUrl.value && togglePlay(mccUrl.value),
  e: () => candidateRef.value && togglePlay(audioUrl.ce(candidateRef.value, "Spanish(Mexico)")),
  n: () => candidateRef.value && togglePlay(audioUrl.ce(candidateRef.value, "English(US)")),
  j: () => ceColumn.value?.move(1),
  k: () => ceColumn.value?.move(-1),
  s: () => focusedRef.value && useCandidate(focusedRef.value),
  "[": () => mccColumn.value?.move(-1),
  "]": () => mccColumn.value?.move(1),
  "/": () => mccColumn.value?.focusSearch(),
  "\\": () => ceColumn.value?.focusSearch(),
  "ctrl+s": () => void match.save(),
  escape: () => stop(),
});

onMounted(async () => {
  try {
    const state = await api.state();
    levels.value = state.levels.map((l) => l.level);
    missions.value = state.missions.map((m) => m.mission);
  } catch (e) {
    match.error.value = e instanceof Error ? e.message : String(e);
  }
  if (selectedSlot.value) void match.load(selectedSlot.value);
});
</script>

<template>
  <div class="layout-bar">
    <span class="muted small">Drag the dividers to resize the panels. Widths are kept on this computer.</span>
    <button type="button" :disabled="layout.isDefault.value" @click="layout.reset()">Reset layout</button>
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
    <MatchPanel :match="match" />
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
      :missions="missions"
      :slot-id="selectedSlot"
      :focused-ref="focusedRef"
      :chosen-refs="match.detail.value ? match.draft.ceRefs : []"
      @focus="focusedRef = $event"
      @use="useCandidate"
    />
  </div>
</template>
