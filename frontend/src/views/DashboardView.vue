<script setup lang="ts">
// Dashboard: progress of every MCC dialogue folder, laid out like the original's campaign menu. A list of
// levels on the left; the highlighted one (hover, keyboard focus or arrow keys) is described in the connected
// panel on the right; choosing it opens it in Matching.

import { ArrowRight, Clapperboard, Gauge, ListFilter, Map as MapIcon, ShieldCheck, Users } from "lucide-vue-next";
import { computed, nextTick, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api, ApiError } from "../api/client";
import type { LevelSummary, StateResponse } from "../api/types";
import StatusBadge from "../components/StatusBadge.vue";
import HudMeter from "../components/ui/HudMeter.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import PanelHeader from "../components/ui/PanelHeader.vue";
import StateMessage from "../components/ui/StateMessage.vue";
import { levelTitle } from "../matching/levelNames";

const state = ref<StateResponse | null>(null);
const error = ref("");
const highlighted = ref<string | null>(null);
const list = ref<HTMLElement | null>(null);

onMounted(async () => {
  try {
    state.value = await api.state();
    highlighted.value = state.value.levels[0]?.level ?? null;
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

const GROUP_TITLE: Record<string, string> = { campaign: "Campaign", cutscene: "Cinematics", generic: "Shared voices" };
const groups = computed(() => {
  const byGroup = new Map<string, LevelSummary[]>();
  for (const level of state.value?.levels ?? []) {
    const list = byGroup.get(level.group) ?? [];
    list.push(level);
    byGroup.set(level.group, list);
  }
  return [...byGroup.entries()].map(([group, levels]) => ({ group, title: GROUP_TITLE[group] ?? group, levels }));
});

const totals = computed(() => {
  const sum = { slots: 0, decided: 0, audio: 0, subtitle: 0 };
  for (const l of state.value?.levels ?? []) {
    if (l.group !== "campaign") continue;
    sum.slots += l.progress.slots;
    sum.decided += l.progress.decided;
    sum.audio += l.progress.audio_approved;
    sum.subtitle += l.progress.subtitle_approved;
  }
  return sum;
});

const current = computed(() => state.value?.levels.find((l) => l.level === highlighted.value) ?? null);
/** The mission title, or the folder's own name for shared voices (marines, grunt, …). */
const nameOf = (level: string) => levelTitle(level) || level.charAt(0).toUpperCase() + level.slice(1);
const pct = (n: number, total: number) => (total ? Math.round((100 * n) / total) : 0);

/** Arrow keys move through the menu, as on the original; the highlight follows the focus. */
async function onListKey(event: KeyboardEvent) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  event.preventDefault();
  const items = Array.from(list.value?.querySelectorAll<HTMLAnchorElement>("a.menu-item") ?? []);
  const index = items.findIndex((a) => a === document.activeElement);
  const next = items[Math.min(items.length - 1, Math.max(0, index + (event.key === "ArrowDown" ? 1 : -1)))];
  await nextTick();
  next?.focus();
}
</script>

<template>
  <section class="dashboard">
    <PageHeader title="Campaign progress" :icon="Gauge" lead="Choose a level to open it in Matching. Approved decisions are what a build uses.">
      <StatusBadge v-if="state" :label="pinsMatch ? 'pins match the installed game' : 'pins differ from the installed game'"
                   :tone="pinsMatch ? 'ok' : 'bad'" />
    </PageHeader>

    <StateMessage v-if="error" kind="error">Could not reach the API: {{ error }}. Start it with <code>npm run dev</code>.</StateMessage>
    <StateMessage v-else-if="!state" kind="loading">Loading progress…</StateMessage>

    <template v-else>
      <div class="totals panel quiet" aria-label="Campaign totals">
        <HudMeter label="Campaign lines decided" :value="totals.decided" :max="totals.slots" />
        <HudMeter label="Audio approved" :value="totals.audio" :max="totals.slots" tone="ok" />
        <HudMeter label="Subtitles approved" :value="totals.subtitle" :max="totals.slots" tone="ok" />
      </div>

      <div class="menu-screen">
        <nav ref="list" class="menu-list" aria-label="Levels" @keydown="onListKey">
          <template v-for="g in groups" :key="g.group">
            <p class="menu-group">{{ g.title }}</p>
            <RouterLink
              v-for="l in g.levels"
              :key="l.level"
              :to="{ name: 'match', query: { level: l.level } }"
              class="menu-item"
              :class="{ highlighted: l.level === highlighted }"
              :aria-current="l.level === highlighted ? 'true' : undefined"
              @mouseenter="highlighted = l.level"
              @focus="highlighted = l.level"
            >
              <span v-if="levelTitle(l.level)" class="code">{{ l.level }}</span>
              <Users v-else :size="15" class="code" aria-hidden="true" />
              <span class="name">{{ nameOf(l.level) }}</span>
              <span class="figure mono">{{ pct(l.progress.decided, l.progress.slots) }}%</span>
            </RouterLink>
          </template>
        </nav>

        <article v-if="current" class="menu-detail" aria-live="polite">
          <header class="detail-head">
            <Clapperboard v-if="current.group === 'cutscene'" :size="34" aria-hidden="true" />
            <MapIcon v-else :size="34" aria-hidden="true" />
            <div>
              <h2>{{ nameOf(current.level) }}</h2>
              <p class="muted small mono">{{ current.level }} · {{ current.group }} · {{ current.progress.slots }} lines<span v-if="current.ce_missions?.length"> · Campaign Evolved {{ current.ce_missions.join(", ") }}</span></p>
            </div>
          </header>

          <HudMeter label="Decided" :value="current.progress.decided" :max="current.progress.slots" />
          <HudMeter label="Audio approved" :value="current.progress.audio_approved" :max="current.progress.slots" tone="ok" />
          <HudMeter label="Subtitles approved" :value="current.progress.subtitle_approved" :max="current.progress.slots" tone="ok" />

          <dl class="texts figures">
            <dt>Matched</dt><dd>{{ current.progress.matched }}</dd>
            <dt>No equivalent</dt><dd>{{ current.progress.no_equivalent }}</dd>
            <dt>Deferred</dt><dd>{{ current.progress.deferred }}</dd>
            <dt>Needs rework</dt><dd :class="{ bad: current.progress.needs_rework > 0 }">{{ current.progress.needs_rework }}</dd>
            <dt>Radio effect</dt><dd>{{ current.progress.radio_effect }}</dd>
            <dt>Different but fits</dt><dd>{{ current.progress.different_but_fits }}</dd>
          </dl>

          <p>
            <StatusBadge v-if="current.progress.ready_for_build" label="ready to build" tone="ok" />
            <StatusBadge v-else label="not ready to build" tone="muted" />
          </p>

          <footer class="detail-actions">
            <RouterLink class="button primary" :to="{ name: 'match', query: { level: current.level } }">
              <ArrowRight :size="16" aria-hidden="true" /> Open in Matching
            </RouterLink>
            <RouterLink class="button" :to="{ name: 'match', query: { level: current.level, status: 'undecided' } }">
              <ListFilter :size="15" aria-hidden="true" /> Unmatched lines
            </RouterLink>
          </footer>
        </article>
      </div>

      <section class="panel quiet missions">
        <PanelHeader title="Campaign Evolved missions" :icon="ShieldCheck" />
        <div class="table-frame">
          <table>
            <thead>
              <tr><th>Mission</th><th>Records</th><th>Lines</th><th>Lines with es-MX audio</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in state.missions" :key="m.mission">
                <td class="mono">{{ m.mission }}</td>
                <td>{{ m.records }}</td>
                <td>{{ m.lines }}</td>
                <td>{{ m.lines_with_es_mx_audio }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </section>
</template>
