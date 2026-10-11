<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { api, ApiError } from "../api/client";
import { useDebounced } from "../composables/useDebounced";
import StatusBadge from "../components/StatusBadge.vue";
import type { SlotsResponse } from "../api/types";

// Filter values the API understands (scripts/ui/m4_app.py, _slot_filter).
const STATUS_OPTIONS: [string, string][] = [
  ["", "All lines"],
  ["undecided", "Undecided"],
  ["matched", "Matched"],
  ["no_equivalent", "No equivalent"],
  ["deferred", "Deferred"],
  ["needs_rework", "Needs rework"],
  ["audio_pending", "Audio not approved"],
  ["subtitle_pending", "Subtitle not approved"],
  ["radio", "Needs radio effect"],
  ["fits", "Different but fits"],
  ["edited", "Edited"],
  ["stereo", "Stereo"],
];
const PAGE_SIZE = 500;

const route = useRoute();
const router = useRouter();

// The view lives in the URL, so Back and reloads keep the level, filter and search.
const levels = ref<string[]>([]);
const level = ref(String(route.query.level ?? "a10"));
const status = ref(String(route.query.status ?? ""));
const search = ref(String(route.query.q ?? ""));
const debouncedSearch = useDebounced(search);

const data = ref<SlotsResponse | null>(null);
const error = ref("");
let latest = 0; // a slower response for an older query must not overwrite a newer one

async function load() {
  const request = ++latest;
  error.value = "";
  try {
    const res = await api.slots({
      level: level.value,
      status: status.value,
      q: debouncedSearch.value,
      limit: PAGE_SIZE,
    });
    if (request === latest) data.value = res;
  } catch (e) {
    if (request === latest) error.value = e instanceof ApiError ? e.message : String(e);
  }
}

watch([level, status, debouncedSearch], () => {
  router.replace({
    query: { level: level.value, status: status.value || undefined, q: debouncedSearch.value || undefined },
  });
  load();
});

onMounted(async () => {
  try {
    levels.value = (await api.state()).levels.map((l) => l.level);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
  await load();
});

const tone = (s: string) => (s === "approved" ? "ok" : s === "draft" ? "warn" : s === "needs_rework" ? "bad" : "muted");
</script>

<template>
  <section>
    <h1>Dialogues</h1>
    <form class="filters" @submit.prevent>
      <label>Level
        <select v-model="level">
          <option v-for="l in levels" :key="l" :value="l">{{ l }}</option>
        </select>
      </label>
      <label>Show
        <select v-model="status">
          <option v-for="[value, label] in STATUS_OPTIONS" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label class="grow">Search
        <input v-model="search" type="search" placeholder="Tag, id, text, speaker (accents ignored)" />
      </label>
    </form>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="data">
      <p class="muted small">
        {{ data.slots.length }} of {{ data.total }} lines
        <span v-if="data.truncated">· showing the first {{ PAGE_SIZE }}; narrow the search to see the rest</span>
        · decided {{ data.progress.decided }} / {{ data.progress.slots }}
      </p>
      <table class="lines">
        <thead>
          <tr>
            <th>Line</th>
            <th>Speaker</th>
            <th>Match</th>
            <th>Audio</th>
            <th>Subtitle</th>
            <th>Flags</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in data.slots" :key="row.slot_id">
            <td>
              <RouterLink :to="{ name: 'slot', params: { id: row.slot_id } }">{{ row.tag_name }}</RouterLink>
              <div class="muted small mono">{{ row.slot_id }}</div>
            </td>
            <td>{{ row.speaker_from_name || "—" }}</td>
            <td><StatusBadge :label="row.decision.match" :tone="row.decision.match === 'matched' ? 'ok' : 'muted'" /></td>
            <td><StatusBadge :label="row.decision.audio" :tone="tone(row.decision.audio)" /></td>
            <td><StatusBadge :label="row.decision.subtitle" :tone="tone(row.decision.subtitle)" /></td>
            <td>
              <StatusBadge v-if="row.radio_effect" label="radio" tone="warn" />
              <StatusBadge v-if="row.different_but_fits" label="fits" tone="muted" />
              <StatusBadge v-if="row.channels > 1" label="stereo" tone="muted" />
            </td>
          </tr>
          <tr v-if="!data.slots.length"><td colspan="6" class="muted">No lines match.</td></tr>
        </tbody>
      </table>
    </template>
    <p v-else-if="!error" class="muted">Loading…</p>
  </section>
</template>
