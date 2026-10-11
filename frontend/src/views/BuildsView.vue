<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api/client";
import GainSetting from "../components/build/GainSetting.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { BuildJob, BuildsResponse } from "../api/types";

// Dry runs only: they write under work/m6/ and never touch the MCC install. Deploying and restoring
// need your approval for each build, so they are shown here but not wired to any action.
const DEPLOY_ACTIONS = [
  { label: "Audio only", reason: "Needs your approval for this build. Run it with scripts/build/m6_install.py." },
  { label: "Subtitles only", reason: "Disabled: the variable-length subtitle writer is not validated in-game (docs/m6-build.md §4)." },
  { label: "Audio + subtitles", reason: "Disabled until the subtitle writer is validated in-game." },
  { label: "Restore originals", reason: "Needs your approval. Run it with scripts/build/m6_install.py --build <name> rollback." },
];

const builds = ref<BuildsResponse | null>(null);
const levels = ref<string[]>([]);
const chosen = ref<string[]>([]);
const name = ref("");
const job = ref<BuildJob | null>(null);
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

async function refresh() {
  builds.value = await api.builds();
}

onMounted(async () => {
  try {
    levels.value = (await api.state()).levels.map((l) => l.level);
    chosen.value = levels.value.includes("a10") ? ["a10"] : levels.value.slice(0, 1);
    await refresh();
  } catch (e) {
    error.value = message(e);
  }
});

onBeforeUnmount(() => clearTimeout(timer));

function toggleLevel(level: string) {
  chosen.value = chosen.value.includes(level)
    ? chosen.value.filter((l) => l !== level)
    : [...chosen.value, level];
}

async function dryRun() {
  error.value = "";
  try {
    job.value = await api.startDryRun(chosen.value, name.value.trim() || undefined);
    poll();
  } catch (e) {
    error.value = message(e);
  }
}

// The build runs in the background on the server; poll its state until it finishes.
function poll() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if (!job.value) return;
    try {
      job.value = await api.job(job.value.id);
      if (job.value.state === "running") poll();
      else await refresh();
    } catch (e) {
      error.value = message(e);
    }
  }, 1000);
}
</script>

<template>
  <section>
    <h1>Build &amp; Test</h1>
    <p v-if="error" class="error">{{ error }}</p>

    <GainSetting @saved="refresh" />

    <h2>Dry run</h2>
    <p class="muted small">
      Builds the candidate audio into <code>work/m6/NAME</code>. Nothing is installed.
      Only approved decisions are used.
    </p>
    <div class="row">
      <label v-for="l in levels" :key="l" class="check">
        <input type="checkbox" :checked="chosen.includes(l)" @change="toggleLevel(l)" /> {{ l }}
      </label>
    </div>
    <div class="row">
      <input v-model="name" placeholder="Name (optional)" />
      <button type="button" :disabled="!chosen.length || job?.state === 'running'" @click="dryRun">
        Dry run build
      </button>
    </div>
    <p v-if="job" class="muted small">
      {{ job.name }}:
      <StatusBadge :label="job.state" :tone="job.state === 'done' ? 'ok' : job.state === 'failed' ? 'bad' : 'warn'" />
    </p>
    <pre v-if="job?.log_tail" class="log">{{ job.log_tail }}</pre>

    <h2>Builds</h2>
    <table v-if="builds">
      <thead>
        <tr><th>Build</th><th>Levels</th><th>Built</th><th>Counts</th><th>Validation</th><th>Decisions</th></tr>
      </thead>
      <tbody>
        <tr v-for="b in builds.builds" :key="b.name">
          <td class="mono">{{ b.name }}</td>
          <td>{{ b.levels.join(", ") }}</td>
          <td class="small">{{ b.built_at ?? "—" }}</td>
          <td class="small">{{ Object.entries(b.counts).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—" }}</td>
          <td>
            <StatusBadge v-if="b.validation_ok === true" label="passed" tone="ok" />
            <StatusBadge v-else-if="b.validation_ok === false" label="failed" tone="bad" />
            <StatusBadge v-else label="not validated" tone="muted" />
          </td>
          <td>
            <StatusBadge v-if="b.stale" :label="`stale: ${b.stale_reasons.join('; ')}`" tone="bad" />
            <StatusBadge v-else label="current" tone="ok" />
          </td>
        </tr>
        <tr v-if="!builds.builds.length"><td colspan="6" class="muted">No builds yet.</td></tr>
      </tbody>
    </table>

    <h2>Install to the game</h2>
    <p class="note">
      Each install needs your explicit approval for that build. This dashboard does not install, deploy or
      restore anything, and MCC must be closed.
    </p>
    <div class="deploy">
      <div v-for="action in DEPLOY_ACTIONS" :key="action.label" class="deploy-item">
        <button type="button" disabled>{{ action.label }}</button>
        <span class="muted small">{{ action.reason }}</span>
      </div>
    </div>
  </section>
</template>
