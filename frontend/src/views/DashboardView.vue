<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api, ApiError } from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import type { StateResponse } from "../api/types";

const state = ref<StateResponse | null>(null);
const error = ref("");

onMounted(async () => {
  try {
    state.value = await api.state();
  } catch (e) {
    error.value = e instanceof ApiError || e instanceof Error ? e.message : String(e);
  }
});

// The build pins must match the installed game and the reference copies, or decisions were made
// against something else.
const pinsMatch = computed(() => {
  if (!state.value) return true;
  const { pins, current_pins } = state.value;
  return Object.keys(pins).every((k) => pins[k] === current_pins[k]);
});

const pct = (n: number, total: number) => (total ? Math.round((100 * n) / total) : 0);
</script>

<template>
  <section>
    <h1>Progress</h1>
    <p v-if="error" class="error">Could not reach the API: {{ error }}. Start it with <code>npm run dev</code>.</p>
    <p v-else-if="!state" class="muted">Loading…</p>

    <template v-else>
      <p>
        <StatusBadge :label="pinsMatch ? 'pins match the installed game' : 'pins differ from the installed game'"
                     :tone="pinsMatch ? 'ok' : 'bad'" />
      </p>

      <table>
        <thead>
          <tr>
            <th>Level</th>
            <th>Decided</th>
            <th>Audio approved</th>
            <th>Subtitles approved</th>
            <th>Radio effect</th>
            <th>Build</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in state.levels" :key="l.level">
            <td>
              <RouterLink :to="{ name: 'match', query: { level: l.level } }">{{ l.level }}</RouterLink>
              <span class="muted small"> {{ l.group }}</span>
            </td>
            <td>{{ l.progress.decided }} / {{ l.progress.slots }} ({{ pct(l.progress.decided, l.progress.slots) }}%)</td>
            <td>{{ l.progress.audio_approved }}</td>
            <td>{{ l.progress.subtitle_approved }}</td>
            <td>{{ l.progress.radio_effect }}</td>
            <td>
              <StatusBadge v-if="l.progress.ready_for_build" label="ready" tone="ok" />
              <StatusBadge v-else label="not ready" tone="muted" />
            </td>
          </tr>
        </tbody>
      </table>

      <h2>Campaign Evolved missions</h2>
      <table>
        <thead>
          <tr><th>Mission</th><th>Records</th><th>Lines</th><th>Lines with es-MX audio</th></tr>
        </thead>
        <tbody>
          <tr v-for="m in state.missions" :key="m.mission">
            <td>{{ m.mission }}</td>
            <td>{{ m.records }}</td>
            <td>{{ m.lines }}</td>
            <td>{{ m.lines_with_es_mx_audio }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </section>
</template>
