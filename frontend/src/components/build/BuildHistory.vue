<script setup lang="ts">
// The builds in work/m6/, newest first and grouped by day (src/build/history.ts). A search and two filters
// narrow the list; without a filter only the newest builds are shown, the rest one click away. Rows stay short:
// time, name, type, folders, lines, status and Install. Everything else (level, why a build is stale, files,
// validation, subtitles, log) is in the details, opened by clicking the row. A table on the desktop, compact
// cards on phones and upright tablets. Install is the only action; BuildsView confirms it and runs it.

import { Captions, ChevronDown, ChevronRight, FileAudio, HardDriveDownload, Search, X } from "lucide-vue-next";
import { computed, reactive, ref } from "vue";
import type { BuildSummary } from "../../api/types";
import { builtAtParts, foldersTitle, groupByDay, matchesFilter, newestFirst, type BuildFilter, type KindFilter, type StatusFilter } from "../../build/history";
import { layoutMode } from "../../layout/useLayoutMode";
import StatusBadge from "../StatusBadge.vue";
import CopyButton from "../ui/CopyButton.vue";
import StateMessage from "../ui/StateMessage.vue";
import BuildDetails from "./BuildDetails.vue";

const props = defineProps<{
  builds: BuildSummary[];
  installed: string[];
  /** Installing is possible at all here (host page, valid game folder, MCC closed, no job running). */
  canDeploy: boolean;
  /** A build is installed now: restore first. */
  modInstalled: boolean;
  /** The public read-only view (docs/public-access.md): no Install action at all. */
  readOnly?: boolean;
}>();
const emit = defineEmits<{ install: [name: string] }>();

/** Builds shown before "Show older builds", when no filter is on. */
const LIMIT = 8;
const KIND_TEXT = { audio: "Audio", subtitles: "Subtitles", both: "Audio + subtitles", experiment: "Experiment" } as const;
const KINDS: { value: KindFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "audio", label: "Audio" },
  { value: "subtitles", label: "Subtitles" },
  { value: "both", label: "Both" },
];
const STATUSES: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "Any status" },
  { value: "current", label: "Current" },
  { value: "stale", label: "Stale" },
  { value: "failed", label: "Failed or not validated" },
  { value: "installed", label: "Installed" },
];

const filter = reactive<BuildFilter>({ text: "", kind: "all", status: "all" });
const showAll = ref(false);
const open = ref<string | null>(null);
const cards = computed(() => layoutMode.value !== "desktop");
const filtering = computed(() => Boolean(filter.text.trim()) || filter.kind !== "all" || filter.status !== "all");

// Sort the whole list first, then filter, then shorten: the newest always come first.
const all = computed(() => newestFirst(props.builds));
const newest = computed(() => all.value[0]?.name ?? null);
const matching = computed(() => all.value.filter((b) => matchesFilter(b, filter, props.installed)));
const visible = computed(() => (filtering.value || showAll.value ? matching.value : matching.value.slice(0, LIMIT)));
const hidden = computed(() => matching.value.length - visible.value.length);
const groups = computed(() =>
  groupByDay(visible.value).map((g) => ({
    ...g,
    builds: g.builds.map((b) => ({ ...b, when: builtAtParts(b.built_at), files: b.install_files.map((f) => f.install_rel.split("/").pop()).join(", ") })),
  })),
);

const toggle = (name: string) => (open.value = open.value === name ? null : name);
/** A click anywhere on a row opens it, except on its own buttons and links. */
function rowClick(event: MouseEvent, name: string) {
  if ((event.target as HTMLElement).closest("button, a, input, select")) return;
  if (window.getSelection()?.toString()) return; // selecting a name to copy it
  toggle(name);
}
function clearFilters() {
  filter.text = "";
  filter.kind = "all";
  filter.status = "all";
}

const isInstalled = (name: string) => props.installed.includes(name);
const n = (v: number | undefined) => (v ?? 0).toLocaleString("en-US");
const installBlocked = (b: BuildSummary) => !props.canDeploy || b.validation_ok !== true || !b.install_files.length || props.modInstalled;
const installTitle = (b: BuildSummary) =>
  props.modInstalled ? "Restore the originals first" : b.validation_ok !== true ? "Only validated builds can be installed" : "Install this build into MCC";
const staleTitle = (b: BuildSummary) => (b.stale ? `Stale: ${b.stale_reasons.join("; ")}` : "Made from the current decisions and settings");
</script>

<template>
  <div class="build-history" data-testid="build-list" :data-view="cards ? 'cards' : 'table'">
    <div v-if="builds.length" class="build-toolbar" role="search" aria-label="Find a build">
      <label class="build-search">
        <Search :size="15" aria-hidden="true" />
        <input v-model="filter.text" type="search" placeholder="Name or folder" aria-label="Search builds by name or folder" />
      </label>
      <div class="segmented" role="group" aria-label="Type">
        <button
          v-for="k in KINDS"
          :key="k.value"
          type="button"
          :class="{ active: filter.kind === k.value }"
          :aria-pressed="filter.kind === k.value"
          @click="filter.kind = k.value"
        >
          {{ k.label }}
        </button>
      </div>
      <select v-model="filter.status" aria-label="Status">
        <option v-for="s in STATUSES" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
      <p class="small muted build-count" aria-live="polite" data-testid="build-count">
        <template v-if="filtering">{{ matching.length }} of {{ all.length }} match</template>
        <template v-else>{{ visible.length }} of {{ all.length }}, newest first</template>
        <button v-if="filtering" type="button" class="link icon-label" @click="clearFilters"><X :size="13" aria-hidden="true" /> Clear</button>
      </p>
    </div>

    <StateMessage v-if="!builds.length" kind="empty">No builds yet.</StateMessage>
    <StateMessage v-else-if="!matching.length" kind="empty">No build matches these filters.</StateMessage>

    <!-- Desktop: one short row per build under its day; details below the row. -->
    <div v-else-if="!cards" class="table-frame build-table">
      <table>
        <colgroup>
          <col class="c-time" /><col class="c-name" /><col class="c-type" /><col class="c-folders" /><col class="c-lines" /><col class="c-status" /><col class="c-action" />
        </colgroup>
        <thead>
          <tr><th scope="col">Time</th><th scope="col">Build</th><th scope="col">Type</th><th scope="col">Folders</th><th scope="col">Lines</th><th scope="col">Status</th><th scope="col"><span class="sr-only">Install</span></th></tr>
        </thead>
        <tbody v-for="g in groups" :key="g.key">
          <tr class="day-row">
            <th colspan="7" scope="colgroup">{{ g.label }} <span class="muted">· {{ g.builds.length }} {{ g.builds.length === 1 ? "build" : "builds" }}</span></th>
          </tr>
          <template v-for="b in g.builds" :key="b.name">
            <tr
              :data-build="b.name"
              :data-kind="b.kind"
              :data-built-at="b.built_at ?? ''"
              :data-files="b.files"
              class="build-row"
              :class="{ open: open === b.name, latest: b.name === newest }"
              @click="rowClick($event, b.name)"
            >
              <td class="when">
                <time v-if="b.when" :datetime="b.when.iso" :title="`${b.when.date} ${b.built_at}`">{{ b.when.time }}</time>
                <span v-else class="muted">—</span>
              </td>
              <td class="name-cell">
                <div class="name-line">
                  <button type="button" class="link-button build-toggle" :aria-expanded="open === b.name" :aria-label="`Details of ${b.name}`" @click="toggle(b.name)">
                    <ChevronDown v-if="open === b.name" :size="15" aria-hidden="true" />
                    <ChevronRight v-else :size="15" aria-hidden="true" />
                    <span class="build-name">{{ b.name }}</span>
                  </button>
                  <StatusBadge v-if="b.name === newest" label="latest" tone="info" />
                  <CopyButton :text="b.name" :label="`Copy the name ${b.name}`" />
                </div>
              </td>
              <td class="type small">
                <span class="icon-label kind">
                  <FileAudio v-if="b.kind !== 'subtitles'" :size="13" aria-hidden="true" />
                  <Captions v-if="b.kind === 'subtitles' || b.kind === 'both'" :size="13" aria-hidden="true" />
                  {{ KIND_TEXT[b.kind] }}
                </span>
              </td>
              <td class="folders small" :title="foldersTitle(b.levels)">
                <div class="folders-line">
                  <strong>{{ b.levels.length }}</strong>
                  <span class="folder-list mono">{{ b.levels.join(", ") }}</span>
                </div>
              </td>
              <td class="lines small">
                <div v-if="b.kind === 'experiment'">+{{ n(b.counts.extra_takes) }} <span class="muted">takes (test)</span></div>
                <div v-else-if="b.kind !== 'subtitles'">{{ n(b.counts.replace) }} <span class="muted">audio</span></div>
                <div v-if="b.subtitles.enabled && b.subtitles.summary">{{ n(b.subtitles.summary.keys_to_write) }} <span class="muted">subtitles</span></div>
              </td>
              <td class="status">
                <div class="badges">
                  <StatusBadge v-if="b.validation_ok === true" label="passed" tone="ok" />
                  <StatusBadge v-else-if="b.validation_ok === false" :label="`failed (${b.failed_checks.length})`" tone="bad" />
                  <StatusBadge v-else label="not validated" tone="muted" />
                  <StatusBadge :label="b.stale ? 'stale' : 'current'" :tone="b.stale ? 'warn' : 'ok'" :title="staleTitle(b)" />
                  <StatusBadge v-if="isInstalled(b.name)" label="installed" tone="warn" />
                </div>
              </td>
              <td class="action">
                <button
                  v-if="!readOnly && !isInstalled(b.name)"
                  type="button"
                  class="icon-label small-button"
                  aria-label="Install to MCC"
                  :disabled="installBlocked(b)"
                  :title="installTitle(b)"
                  @click="emit('install', b.name)"
                >
                  <HardDriveDownload :size="14" aria-hidden="true" /> Install
                </button>
              </td>
            </tr>
            <tr v-if="open === b.name" class="detail-row">
              <td colspan="7"><BuildDetails :name="b.name" :has-log="b.has_log" :build="b" /></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Phone and upright tablet: compact cards under day headings. -->
    <div v-else class="build-days">
      <section v-for="g in groups" :key="g.key" class="build-day" :aria-label="g.label">
        <h3 class="day-heading">{{ g.label }} <span class="muted">· {{ g.builds.length }}</span></h3>
        <ol class="build-cards plain">
          <li v-for="b in g.builds" :key="b.name" :class="{ open: open === b.name }">
            <article class="build-card" :data-build="b.name" :data-kind="b.kind" :data-built-at="b.built_at ?? ''" :data-files="b.files" :aria-label="`Build ${b.name}`">
              <div class="name-line">
                <h4 class="build-name mono">{{ b.name }}</h4>
                <CopyButton :text="b.name" :label="`Copy the name ${b.name}`" />
              </div>
              <p class="card-meta small">
                <time v-if="b.when" :datetime="b.when.iso">{{ b.when.time }}</time>
                <span class="icon-label">
                  <FileAudio v-if="b.kind !== 'subtitles'" :size="13" aria-hidden="true" />
                  <Captions v-if="b.kind === 'subtitles' || b.kind === 'both'" :size="13" aria-hidden="true" />{{ KIND_TEXT[b.kind] }}
                </span>
                <span :title="foldersTitle(b.levels)">{{ b.levels.length }} {{ b.levels.length === 1 ? "folder" : "folders" }}</span>
                <span v-if="b.kind === 'experiment'">+{{ n(b.counts.extra_takes) }} takes (test)</span>
                <span v-else-if="b.kind !== 'subtitles'">{{ n(b.counts.replace) }} audio</span>
                <span v-if="b.subtitles.enabled && b.subtitles.summary">{{ n(b.subtitles.summary.keys_to_write) }} subtitles</span>
              </p>
              <div class="badges">
                <StatusBadge v-if="b.name === newest" label="latest" tone="info" />
                <StatusBadge v-if="b.validation_ok === true" label="passed" tone="ok" />
                <StatusBadge v-else-if="b.validation_ok === false" :label="`failed (${b.failed_checks.length})`" tone="bad" />
                <StatusBadge v-else label="not validated" tone="muted" />
                <StatusBadge :label="b.stale ? 'stale' : 'current'" :tone="b.stale ? 'warn' : 'ok'" />
                <StatusBadge v-if="isInstalled(b.name)" label="installed" tone="warn" />
              </div>
              <div class="card-actions">
                <button type="button" class="icon-label" :aria-expanded="open === b.name" :aria-label="`Details of ${b.name}`" @click="toggle(b.name)">
                  <ChevronDown v-if="open === b.name" :size="15" aria-hidden="true" />
                  <ChevronRight v-else :size="15" aria-hidden="true" /> Details
                </button>
                <button v-if="!readOnly && !isInstalled(b.name)" type="button" class="icon-label" :disabled="installBlocked(b)" :title="installTitle(b)" @click="emit('install', b.name)">
                  <HardDriveDownload :size="15" aria-hidden="true" /> Install to MCC
                </button>
              </div>
              <BuildDetails v-if="open === b.name" :name="b.name" :has-log="b.has_log" :build="b" />
            </article>
          </li>
        </ol>
      </section>
    </div>

    <div v-if="hidden > 0 || (showAll && !filtering && all.length > LIMIT)" class="more-builds">
      <button v-if="hidden > 0" type="button" class="icon-label" data-testid="show-older" @click="showAll = true">
        <ChevronDown :size="15" aria-hidden="true" /> Show {{ hidden }} older {{ hidden === 1 ? "build" : "builds" }}
      </button>
      <button v-else type="button" class="icon-label" @click="showAll = false">Show only the {{ LIMIT }} newest</button>
    </div>
  </div>
</template>
