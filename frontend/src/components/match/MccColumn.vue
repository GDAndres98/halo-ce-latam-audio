<script setup lang="ts">
// Left column: the MCC dialogue lines of one level, with filters and search.
// Filters and the search live in the URL (through the parent's v-model), so a reload keeps the list.
// Changing a filter never changes the selected line: the line stays open even when it is filtered out.

import { ChevronsDown, Layers, ListMusic, VolumeX } from "lucide-vue-next";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import { onChange, onReconnect } from "../../live/changes";
import { useDebounced } from "../../composables/useDebounced";
import type { LevelProgress, SlotRow, SlotsResponse } from "../../api/types";
import AudioButton from "../AudioButton.vue";
import { markFor } from "../../matching/status";
import StatusBadge from "../StatusBadge.vue";
import StateMessage from "../ui/StateMessage.vue";
import { FLAGS, FLAG_ORDER, type FlagName } from "./flags";

const props = defineProps<{ levels: string[]; selectedId: string | null }>();
const emit = defineEmits<{ select: [slotId: string] }>();

const level = defineModel<string>("level", { required: true });
const status = defineModel<string>("status", { default: "" });
const query = defineModel<string>("query", { default: "" });
const debouncedQuery = useDebounced(query, 250);

const PAGE = 300;
const limit = ref(PAGE);
const data = ref<SlotsResponse | null>(null);
const error = ref("");
const searchBox = ref<HTMLInputElement | null>(null);
let latest = 0; // ignore responses to older requests

const STATUS_OPTIONS: [string, string][] = [
  ["", "All lines"],
  ["undecided", "Unmatched"],
  ["draft", "Draft"],
  ["approved", "Approved (both)"],
  ["needs_rework", "Needs rework"],
  ["keep_original", "Keep Spain audio"],
  ["muted", "Muted in game"],
  ["takes", "Has added takes"],
  ["radio", FLAGS.radio.label],
  ["recording", FLAGS.recording.label],
  ["fits", FLAGS.fits.label],
  ["stereo", "Stereo"],
];

async function load() {
  const request = ++latest;
  error.value = "";
  try {
    const res = await api.slots({ level: level.value, status: status.value, q: debouncedQuery.value, limit: limit.value });
    if (request === latest) data.value = res;
  } catch (e) {
    if (request === latest) error.value = e instanceof ApiError ? e.message : String(e);
  }
}

watch([level, status, debouncedQuery], () => {
  limit.value = PAGE;
  load();
});
onMounted(load);

// Decisions changed on another computer (or by a tool on the host): reload the list in place, at most once
// per burst of changes. The selection, the filters and the scroll position stay.
let liveTimer: ReturnType<typeof setTimeout> | undefined;
const reloadSoon = () => {
  clearTimeout(liveTimer);
  liveTimer = setTimeout(load, 400);
};
const stopChanges = onChange(reloadSoon);
const stopReconnect = onReconnect(reloadSoon);
onBeforeUnmount(() => {
  clearTimeout(liveTimer);
  stopChanges();
  stopReconnect();
});

function showMore() {
  limit.value += PAGE;
  load();
}

/** Moves the selection through the visible list (keyboard: [ and ]). */
function move(delta: number) {
  const rows = data.value?.slots ?? [];
  if (!rows.length) return;
  const index = rows.findIndex((r) => r.slot_id === props.selectedId);
  const next = index === -1 ? rows[0] : rows[Math.min(Math.max(index + delta, 0), rows.length - 1)];
  if (next.slot_id !== props.selectedId) emit("select", next.slot_id);
  document.getElementById(`mcc-${next.slot_id}`)?.scrollIntoView({ block: "nearest" });
}

function focusSearch() {
  searchBox.value?.focus();
}

/** After a save: the server's version of that row and of the level's counters replace the old ones, so the
 * list stays right without being reloaded (the selection, the scroll position and the filters stay). */
function updateRow(row: SlotRow, progress?: LevelProgress) {
  if (!data.value) return;
  const i = data.value.slots.findIndex((r) => r.slot_id === row.slot_id);
  if (i !== -1) data.value.slots[i] = row;
  if (progress && row.level === data.value.level) data.value.progress = progress;
}

const unmatched = (r: SlotRow) => !r.decision || r.decision.match === "unreviewed";

/** The next line after the selected one (wrapping) that has no match decision yet, among the listed lines. */
function nextUnmatched(): string | null {
  const rows = data.value?.slots ?? [];
  const start = rows.findIndex((r) => r.slot_id === props.selectedId);
  for (let step = 1; step <= rows.length; step++) {
    const row = rows[(start + step + rows.length) % rows.length];
    if (row && row.slot_id !== props.selectedId && unmatched(row)) {
      emit("select", row.slot_id);
      document.getElementById(`mcc-${row.slot_id}`)?.scrollIntoView({ block: "nearest" });
      return row.slot_id;
    }
  }
  return null;
}

defineExpose({ move, focusSearch, updateRow, nextUnmatched });

const tone = (state: string) => (state === "approved" ? "ok" : state === "draft" ? "warn" : state === "needs_rework" ? "bad" : "muted");
const matchTone = (state: string) => (state === "matched" ? "ok" : state === "no_equivalent" ? "bad" : "muted");

/** A line with no saved decision is listed as undecided (the server sends no summary for it). */
const UNDECIDED = { match: "unreviewed", audio: "draft", subtitle: "draft" };
function decisionOf(row: SlotRow) {
  return row.decision ?? UNDECIDED;
}

/** The owner flags set on a row, in the usual order. */
function rowFlags(row: SlotRow) {
  const set: Record<FlagName, boolean> = {
    radio: row.radio_effect,
    recording: Boolean(row.needs_recording),
    fits: row.different_but_fits,
  };
  return FLAG_ORDER.filter((name) => set[name]).map((name) => FLAGS[name]);
}

/** A flag button of the filter row: shows only the lines with that flag, or all lines again. */
function toggleFlagFilter(name: FlagName) {
  status.value = status.value === FLAGS[name].filter ? "" : FLAGS[name].filter;
}

function mccAudio(row: SlotRow) {
  return audioUrl.mcc(row.level, "spanish", row.spanish_index);
}

/** The line's name as the classic page shows it: the tag, and "#n" when the tag has several takes. */
function rowLabel(row: SlotRow) {
  return row.permutations > 1 ? `${row.tag_name} #${row.ordinal}` : row.tag_name;
}
</script>

<template>
  <section class="column mcc">
    <h2>
      <ListMusic :size="16" aria-hidden="true" /> MCC dialogue
      <span v-if="data" class="count">{{ data.slots.length }}/{{ data.total }}</span>
    </h2>
    <div class="controls">
      <label>Level
        <select v-model="level">
          <option v-for="l in levels" :key="l" :value="l">{{ l }}</option>
          <option value="all">All levels (search)</option>
        </select>
      </label>
      <label>Show
        <select v-model="status">
          <option v-for="[value, label] in STATUS_OPTIONS" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <div class="flag-filters wide" role="group" aria-label="Show only lines with a flag">
        <button
          v-for="name in FLAG_ORDER"
          :key="name"
          type="button"
          class="icon-label small-button flag-filter"
          :class="`flag-${name}`"
          :aria-pressed="status === FLAGS[name].filter"
          :title="`Show only: ${FLAGS[name].label}`"
          :data-testid="`flag-filter-${name}`"
          @click="toggleFlagFilter(name)"
        >
          <component :is="FLAGS[name].icon" :size="14" aria-hidden="true" /> {{ FLAGS[name].label }}
        </button>
      </div>
      <label class="wide">Search ID, speaker or subtitle
        <input ref="searchBox" v-model="query" type="search" placeholder="Accents and case ignored (/)" />
      </label>
    </div>

    <div v-if="data?.progress" class="progressbar" role="progressbar" aria-label="Level progress"
         :aria-valuenow="data.progress.decided" aria-valuemin="0" :aria-valuemax="data.progress.slots">
      <span :style="{ width: `${data.progress.slots ? (100 * data.progress.decided) / data.progress.slots : 0}%` }"></span>
    </div>
    <p v-if="data?.progress" class="progress small">
      Decided {{ data.progress.decided }} / {{ data.progress.slots }} ·
      audio approved {{ data.progress.audio_approved }} ·
      subtitles approved {{ data.progress.subtitle_approved }}<template v-if="data.progress.muted"> ·
      muted {{ data.progress.muted }}</template>
      <StatusBadge v-if="data.progress.ready_for_build" label="ready to build" tone="ok" />
    </p>
    <StateMessage v-if="error" kind="error">{{ error }}</StateMessage>
    <StateMessage v-else-if="!data" kind="loading">Loading lines…</StateMessage>
    <p v-if="data" class="muted small list-meta">
      {{ data.slots.length }} of {{ data.total }} lines<span v-if="data.truncated"> · more below</span>
    </p>

    <ul v-if="data" class="rows" role="listbox" aria-label="MCC dialogue lines">
      <li
        v-for="row in data.slots"
        :id="`mcc-${row.slot_id}`"
        :key="row.slot_id"
        class="row-item"
        :class="{ selected: row.slot_id === selectedId }"
        role="option"
        :aria-selected="row.slot_id === selectedId"
        @click="emit('select', row.slot_id)"
      >
        <div class="line-head">
          <strong class="tag">{{ rowLabel(row) }}</strong>
          <span class="muted small">{{ row.speaker_from_name || "—" }} · {{ row.duration_s.toFixed(2) }} s</span>
          <span class="play-group">
            <AudioButton :url="mccAudio(row)" label="ES" title="Spain Spanish recording" @click.stop />
            <AudioButton
              v-if="row.english_index !== null"
              :url="audioUrl.mcc(row.level, 'english', row.english_index)"
              label="EN"
              title="English recording"
              @click.stop
            />
          </span>
        </div>
        <div class="preview small" :title="row.english_preview">{{ row.english_preview || "(no English subtitle)" }}</div>
        <div class="badges">
          <span class="pill" :class="markFor(decisionOf(row).match).tone" :title="`match: ${markFor(decisionOf(row).match).word}`"
                :aria-label="`match: ${markFor(decisionOf(row).match).word}`">M{{ markFor(decisionOf(row).match).glyph }}</span>
          <span class="pill" :class="markFor(decisionOf(row).audio).tone" :title="`audio: ${markFor(decisionOf(row).audio).word}`"
                :aria-label="`audio: ${markFor(decisionOf(row).audio).word}`">A{{ markFor(decisionOf(row).audio).glyph }}</span>
          <span class="pill" :class="markFor(decisionOf(row).subtitle).tone" :title="`subtitle: ${markFor(decisionOf(row).subtitle).word}`"
                :aria-label="`subtitle: ${markFor(decisionOf(row).subtitle).word}`">S{{ markFor(decisionOf(row).subtitle).glyph }}</span>
          <span
            v-if="row.decision?.audio_source === 'mute'"
            class="pill muted-pill"
            title="Muted in game (no replacement)"
            aria-label="Muted in game"
            data-testid="muted-pill"
          ><VolumeX :size="12" aria-hidden="true" /> muted</span>
          <span
            v-if="row.added_takes"
            class="pill takes-pill"
            :title="`${row.added_takes} added take(s) for this sound`"
            :aria-label="`${row.added_takes} added takes`"
            data-testid="takes-pill"
          ><Layers :size="12" aria-hidden="true" /> +{{ row.added_takes }}</span>
          <span
            v-for="flag in rowFlags(row)"
            :key="flag.name"
            class="pill flag-pill"
            :class="`flag-${flag.name}`"
            :title="flag.label"
            :aria-label="flag.label"
            :data-flag="flag.name"
          ><component :is="flag.icon" :size="12" aria-hidden="true" /></span>
        </div>
      </li>
      <li v-if="!data.slots.length" class="empty-list"><StateMessage kind="empty">No lines match these filters.</StateMessage></li>
    </ul>

    <button v-if="data?.truncated" type="button" class="more icon-label" @click="showMore"><ChevronsDown :size="15" aria-hidden="true" /> Show more lines</button>
  </section>
</template>
