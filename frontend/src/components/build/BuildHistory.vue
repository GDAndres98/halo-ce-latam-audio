<script setup lang="ts">
// The builds in work/m6/, newest first (src/build/history.ts): a table on the desktop, one card per build on
// phones and upright tablets. Each build opens its details (BuildDetails) in place. Install is the only action;
// BuildsView confirms it and runs it. Read-only otherwise.

import { Captions, ChevronDown, ChevronRight, FileAudio, HardDriveDownload } from "lucide-vue-next";
import { computed, ref } from "vue";
import type { BuildLevel, BuildSummary } from "../../api/types";
import { builtAtParts, foldersTitle, newestFirst } from "../../build/history";
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
}>();
const emit = defineEmits<{ install: [name: string] }>();

const KIND_TEXT = { audio: "Audio", subtitles: "Subtitles", both: "Audio + subtitles" } as const;
const open = ref<string | null>(null);
const sorted = computed(() =>
  newestFirst(props.builds).map((b) => ({
    ...b,
    when: builtAtParts(b.built_at),
    files: b.install_files.map((f) => f.install_rel.split("/").pop()).join(", "),
  })),
);
const cards = computed(() => layoutMode.value !== "desktop");

const toggle = (name: string) => (open.value = open.value === name ? null : name);
const isInstalled = (name: string) => props.installed.includes(name);
const n = (v: number | undefined) => (v ?? 0).toLocaleString("en-US");
const db = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)} dB`);
const levelName = (l: BuildLevel) => (l.mode === "match_spain" ? "Match Spain" : `Global gain ${db(l.global_gain_db)}`);
/** "Decisions changed since the build; custom subtitle text changed since the build." */
const sentence = (reasons: string[]) => {
  const text = reasons.join("; ");
  return text ? `${text[0].toUpperCase()}${text.slice(1)}.` : "";
};
const installBlocked = (b: BuildSummary) => !props.canDeploy || b.validation_ok !== true || !b.install_files.length || props.modInstalled;
const installTitle = (b: BuildSummary) =>
  props.modInstalled ? "Restore the originals first" : b.validation_ok !== true ? "Only validated builds can be installed" : "Install this build into MCC";
</script>

<template>
  <div class="build-history" data-testid="build-list" :data-view="cards ? 'cards' : 'table'">
    <StateMessage v-if="!sorted.length" kind="empty">No builds yet.</StateMessage>

    <!-- Desktop: one row per build, details below it. -->
    <div v-else-if="!cards" class="table-frame build-table">
      <table>
        <colgroup>
          <col class="c-when" /><col class="c-name" /><col class="c-folders" /><col class="c-result" /><col class="c-level" /><col class="c-status" /><col class="c-action" />
        </colgroup>
        <thead>
          <tr><th scope="col">Built <span class="sort-mark" aria-label="newest first">↓</span></th><th scope="col">Build</th><th scope="col">Folders</th><th scope="col">Result</th><th scope="col">Level</th><th scope="col">Status</th><th scope="col"><span class="sr-only">Action</span></th></tr>
        </thead>
        <tbody>
          <template v-for="(b, i) in sorted" :key="b.name">
            <tr :data-build="b.name" :data-kind="b.kind" :data-built-at="b.built_at ?? ''" :class="{ open: open === b.name }">
              <td class="when">
                <time v-if="b.when" :datetime="b.when.iso" :title="b.built_at ?? ''"><span class="date">{{ b.when.date }}</span> <span class="time">{{ b.when.time }}</span></time>
                <span v-else class="muted">no date</span>
                <StatusBadge v-if="i === 0 && b.when" label="latest" tone="info" class="latest" />
              </td>
              <td class="name-cell">
                <div class="name-line">
                  <button type="button" class="link-button build-toggle" :aria-expanded="open === b.name" :aria-label="`Details of ${b.name}`" :title="b.name" @click="toggle(b.name)">
                    <ChevronDown v-if="open === b.name" :size="14" aria-hidden="true" />
                    <ChevronRight v-else :size="14" aria-hidden="true" />
                    <span class="build-name">{{ b.name }}</span>
                  </button>
                  <CopyButton :text="b.name" :label="`Copy the name ${b.name}`" />
                </div>
                <span class="icon-label kind muted">
                  <FileAudio v-if="b.kind !== 'subtitles'" :size="13" aria-hidden="true" />
                  <Captions v-if="b.kind !== 'audio'" :size="13" aria-hidden="true" />
                  {{ KIND_TEXT[b.kind] }}
                </span>
                <div class="files mono" :title="b.files">{{ b.files }}</div>
              </td>
              <td class="folders" :title="foldersTitle(b.levels)">
                <strong>{{ b.levels.length }}</strong> <span class="muted">{{ b.levels.length === 1 ? "folder" : "folders" }}</span>
                <div class="folder-list mono">{{ b.levels.join(", ") }}</div>
              </td>
              <td class="result small">
                <div v-if="b.kind !== 'subtitles'"><FileAudio :size="12" aria-hidden="true" /> {{ n(b.counts.replace) }} replaced <span class="muted">· {{ n(b.counts.keep_original) }} kept</span></div>
                <div v-if="b.subtitles.enabled && b.subtitles.summary">
                  <Captions :size="12" aria-hidden="true" /> {{ n(b.subtitles.summary.keys_to_write) }} written
                  <span :class="b.subtitles.summary.excluded ? 'warn' : 'muted'">· {{ n(b.subtitles.summary.excluded) }} excluded</span>
                  <span :class="b.subtitles.conflicts ? 'error' : 'muted'">· {{ b.subtitles.conflicts }} conflicts</span>
                </div>
              </td>
              <td class="level-cell small" data-testid="build-level">
                <template v-if="b.level">
                  <strong>{{ levelName(b.level) }}</strong>
                  <div title="Median gain applied to the replaced lines">{{ db(b.level.effective_gain_db?.median) }} <span class="muted">applied</span></div>
                  <div :class="{ warn: b.level.constrained }" title="Lines that got less gain than asked">{{ b.level.constrained }}/{{ b.level.lines }} <span :class="{ muted: !b.level.constrained }">constrained</span></div>
                  <div v-if="b.level.loudness_vs_spain_db" title="Median loudness against the Spain recordings">{{ db(b.level.loudness_vs_spain_db.median) }} <span class="muted">vs Spain</span></div>
                </template>
                <span v-else class="muted">—</span>
              </td>
              <td class="status">
                <div class="badges">
                  <StatusBadge v-if="b.validation_ok === true" label="passed" tone="ok" />
                  <StatusBadge v-else-if="b.validation_ok === false" :label="`failed (${b.failed_checks.length})`" tone="bad" />
                  <StatusBadge v-else label="not validated" tone="muted" />
                  <StatusBadge v-if="b.stale" label="stale" tone="bad" />
                  <StatusBadge v-else label="current" tone="ok" />
                </div>
                <p v-if="b.stale" class="stale-reasons small muted">{{ sentence(b.stale_reasons) }}</p>
              </td>
              <td class="action">
                <StatusBadge v-if="isInstalled(b.name)" label="installed" tone="warn" />
                <button v-else type="button" class="icon-label small-button" aria-label="Install to MCC" :disabled="installBlocked(b)" :title="installTitle(b)" @click="emit('install', b.name)">
                  <HardDriveDownload :size="14" aria-hidden="true" /> Install
                </button>
              </td>
            </tr>
            <tr v-if="open === b.name" class="detail-row">
              <td colspan="7"><BuildDetails :name="b.name" :has-log="b.has_log" :levels="b.levels" /></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Phone and upright tablet: one card per build. -->
    <ol v-else class="build-cards plain">
      <li v-for="(b, i) in sorted" :key="b.name">
        <article class="build-card" :data-build="b.name" :data-kind="b.kind" :data-built-at="b.built_at ?? ''" :aria-label="`Build ${b.name}`">
          <header>
            <div class="name-line">
              <h3 class="build-name mono">{{ b.name }}</h3>
              <CopyButton :text="b.name" :label="`Copy the name ${b.name}`" />
            </div>
            <p class="when small">
              <time v-if="b.when" :datetime="b.when.iso" :title="b.built_at ?? ''">{{ b.when.date }} · {{ b.when.time }}</time>
              <span v-else class="muted">no date</span>
              <StatusBadge v-if="i === 0 && b.when" label="latest" tone="info" />
            </p>
          </header>
          <div class="badges">
            <span class="badge info kind">
              <FileAudio v-if="b.kind !== 'subtitles'" :size="12" aria-hidden="true" />
              <Captions v-if="b.kind !== 'audio'" :size="12" aria-hidden="true" />{{ KIND_TEXT[b.kind] }}
            </span>
            <StatusBadge v-if="b.validation_ok === true" label="passed" tone="ok" />
            <StatusBadge v-else-if="b.validation_ok === false" :label="`failed (${b.failed_checks.length})`" tone="bad" />
            <StatusBadge v-else label="not validated" tone="muted" />
            <StatusBadge v-if="b.stale" label="stale" tone="bad" />
            <StatusBadge v-else label="current" tone="ok" />
            <StatusBadge v-if="isInstalled(b.name)" label="installed" tone="warn" />
          </div>
          <dl class="card-facts small">
            <dt>Folders</dt>
            <dd :title="foldersTitle(b.levels)"><strong>{{ b.levels.length }}</strong> · <span class="mono folder-list">{{ b.levels.join(", ") }}</span></dd>
            <dt>Files</dt>
            <dd class="mono">{{ b.files }}</dd>
            <template v-if="b.kind !== 'subtitles'">
              <dt>Audio</dt>
              <dd>{{ n(b.counts.replace) }} replaced <span class="muted">· {{ n(b.counts.keep_original) }} kept</span></dd>
            </template>
            <template v-if="b.subtitles.enabled && b.subtitles.summary">
              <dt>Subtitles</dt>
              <dd>
                {{ n(b.subtitles.summary.keys_to_write) }} written
                <span :class="b.subtitles.summary.excluded ? 'warn' : 'muted'">· {{ n(b.subtitles.summary.excluded) }} excluded</span>
                <span :class="b.subtitles.conflicts ? 'error' : 'muted'">· {{ b.subtitles.conflicts }} conflicts</span>
              </dd>
            </template>
            <template v-if="b.level">
              <dt>Level</dt>
              <dd data-testid="build-level">
                {{ levelName(b.level) }} · applied {{ db(b.level.effective_gain_db?.median) }} median ·
                <span :class="{ warn: b.level.constrained }">{{ b.level.constrained }}/{{ b.level.lines }} constrained</span>
                <template v-if="b.level.loudness_vs_spain_db"> · vs Spain {{ db(b.level.loudness_vs_spain_db.median) }}</template>
              </dd>
            </template>
            <template v-if="b.stale">
              <dt>Stale</dt>
              <dd class="muted">{{ sentence(b.stale_reasons) }}</dd>
            </template>
          </dl>
          <div class="card-actions">
            <button type="button" class="icon-label" :aria-expanded="open === b.name" :aria-label="`Details of ${b.name}`" @click="toggle(b.name)">
              <ChevronDown v-if="open === b.name" :size="15" aria-hidden="true" />
              <ChevronRight v-else :size="15" aria-hidden="true" /> Details
            </button>
            <button v-if="!isInstalled(b.name)" type="button" class="icon-label" :disabled="installBlocked(b)" :title="installTitle(b)" @click="emit('install', b.name)">
              <HardDriveDownload :size="15" aria-hidden="true" /> Install to MCC
            </button>
          </div>
          <BuildDetails v-if="open === b.name" :name="b.name" :has-log="b.has_log" :levels="b.levels" />
        </article>
      </li>
    </ol>
  </div>
</template>
