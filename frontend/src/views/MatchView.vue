<script setup lang="ts">
// The matching workspace: MCC lines (left), the decision for the selected line (centre), and Campaign
// Evolved candidates (right). The selected line and every filter are kept in the URL, so reloading or
// going back returns to the same place.
//
// The same three panels serve every screen size (layout/layoutMode.ts). On a desktop they sit side by side
// and can be resized. On a tablet one list sits beside the Matching panel; on a phone one pane is shown at a
// time, with a bottom navigation (WorkspaceTabs), the open line kept in view (MatchContextBar) and Save in reach
// (MobileActionStrip). Only CSS changes between layouts: nothing is mounted again, so the draft, the players,
// the searches and the lists survive switching panes or turning the phone. The pane is in the URL (`pane=`).

import { LayoutTemplate } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import { api, audioUrl } from "../api/client";
import { readOnly } from "../auth/session";
import type { LevelProgress, SlotRow } from "../api/types";
import { stop, togglePlay } from "../audio/player";
import { stopCurrent } from "../audio/transport";
import CeColumn from "../components/match/CeColumn.vue";
import MccColumn from "../components/match/MccColumn.vue";
import MatchContextBar from "../components/match/MatchContextBar.vue";
import MatchPanel from "../components/match/MatchPanel.vue";
import MobileActionStrip from "../components/match/MobileActionStrip.vue";
import WorkspaceTabs from "../components/match/WorkspaceTabs.vue";
import ShortcutsButton from "../components/match/ShortcutsButton.vue";
import { confirmAction } from "../composables/useConfirm";
import { useMatch } from "../composables/useMatch";
import { useShortcuts } from "../composables/useShortcuts";
import SplitHandle from "../layout/SplitHandle.vue";
import { paneFrom, type Pane } from "../layout/layoutMode";
import { layoutMode } from "../layout/useLayoutMode";
import { useWorkspaceLayout } from "../layout/useWorkspaceLayout";
import { onChange, onReconnect } from "../live/changes";

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
  return router.replace({ query });
}

const mccLevel = computed({ get: () => param("level", "a10"), set: (v: string) => setQuery({ level: v }) });
const mccStatus = computed({ get: () => param("status", ""), set: (v: string) => setQuery({ status: v }) });
const mccQuery = computed({ get: () => param("q", ""), set: (v: string) => setQuery({ q: v }) });
const ceMission = computed({ get: () => param("cm", "all"), set: (v: string) => setQuery({ cm: v }) });
const ceQuery = computed({ get: () => param("cq", ""), set: (v: string) => setQuery({ cq: v }) });
const ceSubtitles = computed({ get: () => param("cs", ""), set: (v: string) => setQuery({ cs: v }) });
const ceHideUsed = computed({ get: () => route.query.ch === "1", set: (v: boolean) => setQuery({ ch: v ? "1" : undefined }) });

// ---- Panes (phone and tablet). `pane` is what a phone shows; a tablet shows the Matching panel beside the
// last list chosen (`list`). A desktop shows everything and ignores both.
const pane = computed<Pane>(() => paneFrom(route.query.pane, selectedSlot.value ? "match" : "mcc"));
const list = ref<"mcc" | "ce">(route.query.pane === "ce" ? "ce" : "mcc");
const tabPane = computed<Pane>(() => (layoutMode.value === "tablet" ? list.value : pane.value));

/** Where each pane was scrolled: the page on a phone, the list's own scroll on a tablet. */
const scrolled = new Map<Pane, { page: number; column: number }>();
const columnOf = (p: Pane) => workspaceEl.value?.querySelector<HTMLElement>(`#pane-${p}`) ?? null;

async function setPane(next: Pane, options: { top?: boolean } = {}) {
  const shown = tabPane.value;
  if (next === shown && !options.top) {
    // Pressing the current tab again goes back to the top of it, as in most phone apps.
    if (layoutMode.value === "phone") window.scrollTo({ top: 0 });
    else columnOf(next)?.scrollTo({ top: 0 });
    return;
  }
  scrolled.set(shown, { page: window.scrollY, column: columnOf(shown)?.scrollTop ?? 0 });
  if (options.top) scrolled.delete(next);
  if (next !== "match") list.value = next;
  await setQuery({ pane: next });
  await nextTick();
  const saved = scrolled.get(next) ?? { page: 0, column: 0 };
  if (layoutMode.value === "phone") window.scrollTo({ top: saved.page });
  else if (layoutMode.value === "tablet") {
    const column = columnOf(next);
    if (column) column.scrollTop = saved.column;
  }
}

/** Phone: brings a section of the decision into view (the context bar's chips). */
function jumpTo(section: string) {
  workspaceEl.value?.querySelector(`#pane-match [data-section="${section}"]`)?.scrollIntoView({ block: "start" });
}

// Phone: the bottom bars step aside while the on-screen keyboard is up (a field is being typed in), so they
// never cover the field or the text.
const typing = ref(false);
const TEXT_ENTRY =
  'input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="button"]), textarea';
const onFocusIn = (e: FocusEvent) => (typing.value = e.target instanceof Element && e.target.matches(TEXT_ENTRY));
const onFocusOut = () => (typing.value = false);

// Phone: the save strip hides while the save bar itself is on screen.
const saveBarVisible = ref(false);
let saveBarObserver: IntersectionObserver | null = null;
function observeSaveBar() {
  saveBarObserver?.disconnect();
  saveBarVisible.value = false;
  const bar = workspaceEl.value?.querySelector("#pane-match .save-bar");
  if (!bar || typeof IntersectionObserver === "undefined") return;
  saveBarObserver = new IntersectionObserver((entries) => (saveBarVisible.value = entries.some((e) => e.isIntersecting)));
  saveBarObserver.observe(bar);
}
watch(
  () => Boolean(match.detail.value),
  () => void nextTick(observeSaveBar),
);

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
  // On a phone, choosing a line opens it: the Matching pane, from its top.
  if (layoutMode.value === "phone") {
    // Remember where the list was first: with a line in the URL the default pane becomes Matching.
    scrolled.set(tabPane.value, { page: window.scrollY, column: 0 });
    await setQuery({ slot: slotId, pane: tabPane.value });
    await setPane("match", { top: true });
  } else void setQuery({ slot: slotId });
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

// ---- Live updates: another computer (or a tool on the host) changed decisions. The lists reload themselves
// (MccColumn, CeColumn); the open line is refreshed here, never over unsaved edits.
const stopChanges = onChange((event) => {
  const open = match.detail.value?.slot_id;
  if (open && (event.slots.includes(open) || event.documents.some((d) => d.endsWith(".local.json")))) {
    void match.lineChangedElsewhere(event.by[open] ?? null);
  }
});
const stopReconnect = onReconnect(() => {
  if (match.detail.value) void match.lineChangedElsewhere(null);
});
onBeforeUnmount(() => {
  stopChanges();
  stopReconnect();
  saveBarObserver?.disconnect();
  document.removeEventListener("focusin", onFocusIn);
  document.removeEventListener("focusout", onFocusOut);
});

/** Save the draft (no approval), then open the next unmatched line of the list. */
async function saveAndNext() {
  if (match.saving.value || readOnly.value) return;
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
  s: () => !readOnly.value && focusedRef.value && void useCandidate(focusedRef.value),
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
  "ctrl+s": () => !readOnly.value && void match.save(),
  "ctrl+enter": () => !readOnly.value && void saveAndNext(),
  u: () => mccColumn.value?.nextUnmatched(),
  escape: () => {
    stop();
    stopCurrent();
  },
});

onMounted(async () => {
  document.addEventListener("focusin", onFocusIn);
  document.addEventListener("focusout", onFocusOut);
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
  <div class="match-view" :class="{ typing }">
    <div class="layout-bar">
      <ShortcutsButton />
      <button type="button" class="icon-label" :disabled="layout.isDefault.value" @click="layout.reset()">
        <LayoutTemplate :size="15" aria-hidden="true" /> Reset layout
      </button>
    </div>
    <!-- Phone and tablet only (hidden on a desktop by the stylesheet). -->
    <MatchContextBar
      :match="match" :slot-id="selectedSlot" :mcc-url="mccUrl" :pane="pane"
      @jump="jumpTo" @browse="setPane('mcc')"
    />
    <WorkspaceTabs
      :pane="tabPane" :dirty="Boolean(match.detail.value) && match.dirty()"
      :chosen="match.detail.value ? match.draft.ceRefs.length : 0"
      @select="setPane"
    />
    <div ref="workspaceEl" class="workspace" :class="{ resizing: layout.dragging.value !== null }">
      <MccColumn
        id="pane-mcc"
        ref="mccColumn"
        v-model:level="mccLevel"
        v-model:status="mccStatus"
        v-model:query="mccQuery"
        :class="{ 'pane-active': pane === 'mcc', 'list-active': list === 'mcc' }"
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
      <MatchPanel
        id="pane-match"
        :class="{ 'pane-active': pane === 'match' }"
        :match="match"
        :slot-id="selectedSlot"
        @save-next="saveAndNext"
        @browse="setPane('mcc')"
      />
      <SplitHandle
        side="right"
        :width="layout.widths.value.right"
        :dragging="layout.dragging.value === 'right'"
        @drag-start="layout.startDrag('right', $event)"
        @step="(direction, coarse) => layout.step('right', direction, coarse)"
      />
      <CeColumn
        id="pane-ce"
        ref="ceColumn"
        v-model:mission="ceMission"
        v-model:query="ceQuery"
        v-model:hide-used="ceHideUsed"
        v-model:subtitles="ceSubtitles"
        :class="{ 'pane-active': pane === 'ce', 'list-active': list === 'ce' }"
        :missions="missions"
        :slot-id="selectedSlot"
        :focused-ref="focusedRef"
        :chosen-refs="match.detail.value ? match.draft.ceRefs : []"
        @focus="focusedRef = $event"
        @use="useCandidate"
      />
    </div>
    <MobileActionStrip
      :match="match" :pane="pane" :save-bar-visible="saveBarVisible"
      @save-next="saveAndNext" @review="setPane('match')"
    />
  </div>
</template>
