<script setup lang="ts">
// Build & Test: build the audio bank, install it into MCC, restore the originals.
//
// Builds run scripts/build/m6_build.py and write only under work/m6/. Install and restore run
// scripts/build/m6_install.py (MCC must be closed; originals are hash-checked and backed up outside the
// game; any failure restores them) and only after you confirm the exact files. Nothing launches MCC.

import { FileAudio, Folder, Hammer, HardDriveDownload, Lock, RefreshCw, Undo2 } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api/client";
import GainSetting from "../components/build/GainSetting.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { BuildJob, BuildScope, BuildsResponse, DeployStatus } from "../api/types";

const builds = ref<BuildsResponse | null>(null);
const deploy = ref<DeployStatus | null>(null);
const levels = ref<string[]>([]);
const scope = ref<BuildScope>("mission");
const mission = ref("a10");
const chosen = ref<string[]>(["a10"]);
const name = ref("");
const job = ref<BuildJob | null>(null);
const error = ref("");
const folderInput = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const running = computed(() => job.value?.state === "running");
const gameRunning = computed(() => Boolean(deploy.value?.game_running.length));
const canDeploy = computed(() => Boolean(deploy.value?.valid) && !gameRunning.value && !running.value);
const scopeReady = computed(() => (scope.value === "levels" ? chosen.value.length > 0 : scope.value === "mission" ? Boolean(mission.value) : true));

async function refresh() {
  [builds.value, deploy.value] = await Promise.all([api.builds(), api.deployStatus()]);
  if (deploy.value && !folderInput.value) folderInput.value = deploy.value.mcc_folder ?? "";
}

onMounted(async () => {
  try {
    levels.value = (await api.state()).levels.map((l) => l.level);
    await refresh();
    if (builds.value?.missions.length && !builds.value.missions.includes(mission.value)) mission.value = builds.value.missions[0];
  } catch (e) {
    error.value = message(e);
  }
});

onBeforeUnmount(() => clearTimeout(timer));

function toggleLevel(level: string) {
  chosen.value = chosen.value.includes(level) ? chosen.value.filter((l) => l !== level) : [...chosen.value, level];
}

async function run(start: () => Promise<BuildJob>) {
  error.value = "";
  try {
    job.value = await start();
    poll();
  } catch (e) {
    error.value = message(e);
  }
}

function buildAudio() {
  void run(() =>
    api.startBuild({
      scope: scope.value,
      mission: scope.value === "mission" ? mission.value : undefined,
      levels: scope.value === "levels" ? chosen.value : undefined,
      name: name.value.trim() || undefined,
    }),
  );
}

const mb = (bytes: number | null) => (bytes === null ? "?" : `${(bytes / 1048576).toFixed(1)} MB`);

async function install(build: string) {
  error.value = "";
  try {
    const plan = await api.installPlan(build);
    const lines = plan.files.map(
      (f) => `• ${f.install_rel} (${mb(f.candidate_bytes)})\n   original ${f.original_sha256.slice(0, 12)}… → build ${f.candidate_sha256.slice(0, 12)}…`,
    );
    const warnings = [
      plan.validation_ok ? "" : "⚠ The build's validation report is not OK; the installer will refuse it.",
      plan.stale ? `⚠ Stale: ${plan.stale_reasons.join("; ")}. Lines no longer approved make the installer refuse; newer approvals are simply not included.` : "",
    ].filter(Boolean);
    const ok = window.confirm(
      `Install build "${build}" into MCC?\n\nGame folder: ${plan.mcc_folder}\n\nFiles replaced:\n${lines.join("\n")}\n\n` +
        `Subtitles: ${plan.subtitles}.\nOriginals are verified and backed up to ${plan.files[0]?.backup_folder} first; ` +
        `any failure restores them. MCC must stay closed until it finishes.${warnings.length ? `\n\n${warnings.join("\n")}` : ""}`,
    );
    if (ok) await run(() => api.install(build));
  } catch (e) {
    error.value = message(e);
  }
}

async function restore() {
  const active = deploy.value?.active_builds.join(", ") || "the installed build";
  const ok = window.confirm(
    `Restore the original game files?\n\nInstalled: ${active}\nEach replaced file is copied back from its verified backup ` +
      "and checked. Backups are kept. MCC must be closed.",
  );
  if (ok) await run(() => api.restore());
}

async function saveFolder() {
  error.value = "";
  try {
    deploy.value = await api.setMccFolder(folderInput.value.trim());
  } catch (e) {
    error.value = message(e);
  }
}

// Builds and installs run in the background on the server; poll the job until it finishes.
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

const JOB_TEXT = { build: "Building", install: "Installing", restore: "Restoring" } as const;
const isInstalled = (build: string) => Boolean(deploy.value?.active_builds.includes(build));
</script>

<template>
  <section class="builds-view">
    <h1>Build &amp; Test</h1>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <GainSetting @saved="refresh" />

    <h2><FileAudio :size="18" aria-hidden="true" /> Build</h2>
    <p class="muted small">
      Builds the Spanish dialogue bank from your <strong>approved</strong> audio decisions, their edit recipes and the
      global gain, into <code>work/m6/NAME</code>. Nothing in the game changes until you install a build.
    </p>
    <fieldset class="scope" :disabled="running">
      <legend class="small muted">Scope</legend>
      <label class="check"><input v-model="scope" type="radio" value="mission" /> Mission (its folder and the cinematics only it uses)</label>
      <select v-if="scope === 'mission'" v-model="mission" aria-label="Mission">
        <option v-for="m in builds?.missions ?? []" :key="m" :value="m">{{ m }}</option>
      </select>
      <label class="check"><input v-model="scope" type="radio" value="levels" /> Chosen folders</label>
      <div v-if="scope === 'levels'" class="row level-picks">
        <label v-for="l in levels" :key="l" class="check">
          <input type="checkbox" :checked="chosen.includes(l)" @change="toggleLevel(l)" /> {{ l }}
        </label>
      </div>
      <label class="check"><input v-model="scope" type="radio" value="all_mapped" /> Every folder with a mapping</label>
    </fieldset>
    <div class="row">
      <input v-model="name" placeholder="Build name (optional)" aria-label="Build name" />
      <button type="button" class="primary icon-label" :disabled="running || !scopeReady" @click="buildAudio">
        <Hammer :size="16" aria-hidden="true" /> Build audio
      </button>
      <button type="button" class="icon-label" disabled :title="builds?.subtitles_disabled">
        <Lock :size="14" aria-hidden="true" /> Build subtitles
      </button>
      <button type="button" class="icon-label" disabled :title="builds?.subtitles_disabled">
        <Lock :size="14" aria-hidden="true" /> Build both
      </button>
    </div>
    <p class="small muted">{{ builds?.subtitles_disabled }}</p>

    <div v-if="job" class="job" data-testid="job" :data-state="job.state" :data-kind="job.kind" :data-id="job.id">
      <p class="small">
        {{ JOB_TEXT[job.kind] }} <strong>{{ job.name }}</strong>:
        <StatusBadge :label="job.state" :tone="job.state === 'done' ? 'ok' : job.state === 'failed' ? 'bad' : 'warn'" />
        <span v-if="job.state === 'running'" class="muted"> (started {{ job.started }}; this page keeps checking)</span>
      </p>
      <pre v-if="job.log_tail" class="log">{{ job.log_tail }}</pre>
    </div>

    <h2><HardDriveDownload :size="18" aria-hidden="true" /> Install to MCC</h2>
    <div v-if="deploy" class="sync-card" data-testid="deploy-status">
      <p class="small">
        <Folder :size="14" aria-hidden="true" /> Game folder:
        <code>{{ deploy.mcc_folder ?? "not found" }}</code> <span class="muted">({{ deploy.source }})</span>
        <StatusBadge v-if="!deploy.valid" label="not an MCC install" tone="bad" />
      </p>
      <div v-if="!deploy.fixed" class="row">
        <input v-model="folderInput" class="grow-input" aria-label="MCC folder" placeholder="…\steamapps\common\Halo The Master Chief Collection" />
        <button type="button" class="icon-label" @click="saveFolder"><Folder :size="15" aria-hidden="true" /> Use this folder</button>
      </div>
      <p class="small">
        Installed now:
        <StatusBadge v-if="!deploy.valid" label="unknown" tone="muted" />
        <StatusBadge v-else-if="!deploy.mod_installed" label="original game files" tone="ok" />
        <StatusBadge v-else-if="deploy.active_builds.length" :label="`build ${deploy.active_builds.join(', ')}`" tone="warn" />
        <StatusBadge v-else label="modified files that match no build" tone="bad" />
      </p>
      <ul class="small plain">
        <li v-for="f in deploy.files" :key="f.install_rel">
          <code>{{ f.install_rel }}</code>: {{ f.state === "original" ? "original" : f.state === "build" ? `build ${f.builds.join(", ")}` : "unknown content" }}
        </li>
      </ul>
      <p v-if="gameRunning" class="warn small">MCC appears to be running ({{ deploy.game_running.join(", ") }}). Close it to install or restore.</p>
      <div class="row">
        <button type="button" class="icon-label" :disabled="!canDeploy || !deploy.mod_installed" @click="restore">
          <Undo2 :size="16" aria-hidden="true" /> Restore originals
        </button>
        <button type="button" class="icon-label" :disabled="running" @click="refresh">
          <RefreshCw :size="15" aria-hidden="true" /> Check again
        </button>
      </div>
      <p class="small muted">The Studio never starts MCC. After installing, launch it yourself (anti-cheat off), test, close it, then restore here.</p>
    </div>

    <h2>Builds</h2>
    <table v-if="builds">
      <thead>
        <tr><th>Build</th><th>Folders</th><th>Built</th><th>Counts</th><th>Validation</th><th>Decisions</th><th>Game</th></tr>
      </thead>
      <tbody>
        <tr v-for="b in builds.builds" :key="b.name" :data-build="b.name">
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
          <td>
            <StatusBadge v-if="isInstalled(b.name)" label="installed" tone="warn" />
            <button
              v-else
              type="button"
              class="icon-label small-button"
              :disabled="!canDeploy || b.validation_ok !== true || !b.install_files.length || deploy?.mod_installed"
              :title="deploy?.mod_installed ? 'Restore the originals first' : 'Install this build into MCC'"
              @click="install(b.name)"
            >
              <HardDriveDownload :size="14" aria-hidden="true" /> Install to MCC
            </button>
          </td>
        </tr>
        <tr v-if="!builds.builds.length"><td colspan="7" class="muted">No builds yet.</td></tr>
      </tbody>
    </table>
  </section>
</template>
