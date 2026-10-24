<script setup lang="ts">
// Build & Test: build the audio bank, the subtitle tables or both, install a build into MCC, restore the
// originals.
//
// Builds run scripts/build/m6_build.py --kind audio|subtitles|both and write only under work/m6/. Only approved
// decisions are used; the scope preview shows, before building, what each kind would contain and what is
// excluded. Install and restore run scripts/build/m6_install.py (MCC must be closed; originals are
// hash-checked and backed up outside the game; any failure restores every file of the build) and only after
// you confirm the exact files. Nothing launches MCC.

import { Captions, FileAudio, Folder, Hammer, HardDriveDownload, Layers, RefreshCw, TriangleAlert, Undo2 } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "../api/client";
import { permissions, visitor } from "../auth/session";
import BuildHistory from "../components/build/BuildHistory.vue";
import DeployHistory from "../components/build/DeployHistory.vue";
import GainSetting from "../components/build/GainSetting.vue";
import ScopePreview from "../components/build/ScopePreview.vue";
import StatusBadge from "../components/StatusBadge.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import PanelHeader from "../components/ui/PanelHeader.vue";
import StateMessage from "../components/ui/StateMessage.vue";
import { buildJob } from "../composables/useBuildJob";
import { confirmAction } from "../composables/useConfirm";
import type { BuildJob, BuildKind, BuildLevel, BuildPreview, BuildScope, BuildsResponse, DeployEvent, DeployStatus } from "../api/types";

const builds = ref<BuildsResponse | null>(null);
const deploy = ref<DeployStatus | null>(null);
const history = ref<DeployEvent[]>([]);
const levels = ref<string[]>([]);
const scope = ref<BuildScope>("mission");
const mission = ref("a10");
const chosen = ref<string[]>(["a10"]);
const name = ref("");
const job = buildJob;
const error = ref("");
const folderInput = ref("");
const preview = ref<BuildPreview | null>(null);
const previewError = ref("");
const previewLoading = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let previewTimer: ReturnType<typeof setTimeout> | undefined;
let previewSeq = 0;

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const running = computed(() => job.value?.state === "running");
const gameRunning = computed(() => Boolean(deploy.value?.game_running.length));
// Installing and restoring touch the game folder: only the host computer's own Studio may do it (the server
// refuses it elsewhere, whatever the account). Builds and the level setting need an admin account.
const canDeploy = computed(
  () => permissions.value.install && Boolean(deploy.value?.valid) && !gameRunning.value && !running.value,
);
const scopeReady = computed(() => (scope.value === "levels" ? chosen.value.length > 0 : scope.value === "mission" ? Boolean(mission.value) : true));
const scopeBody = () => ({
  scope: scope.value,
  mission: scope.value === "mission" ? mission.value : undefined,
  levels: scope.value === "levels" ? chosen.value : undefined,
});
// What each kind needs from the scope; a kind with nothing approved to build says so instead of failing later.
const nothing = computed(() => ({
  audio: preview.value ? preview.value.audio.replace === 0 : false,
  subtitles: preview.value ? preview.value.subtitles.keys_to_write === 0 : false,
}));
const blocked = (kind: BuildKind) =>
  !permissions.value.admin ||
  running.value || !scopeReady.value || (kind !== "subtitles" && nothing.value.audio) || (kind !== "audio" && nothing.value.subtitles);
const blockedReason = (kind: BuildKind) =>
  !permissions.value.admin
    ? "Building needs an admin account"
    : kind !== "subtitles" && nothing.value.audio
    ? "No approved Campaign Evolved audio in this scope"
    : kind !== "audio" && nothing.value.subtitles
      ? "No approved subtitle text in this scope"
      : "";

async function refresh() {
  // The public read-only view sees the builds and the install history only (docs/public-access.md): the game
  // folder, the level setting and the scope preview are the owner's.
  if (visitor.value) {
    const [b, h] = await Promise.all([api.builds(), api.deployHistory()]);
    builds.value = b;
    history.value = h.events;
    return;
  }
  const [b, d, h] = await Promise.all([api.builds(), api.deployStatus(), api.deployHistory()]);
  builds.value = b;
  deploy.value = d;
  history.value = h.events;
  if (deploy.value && !folderInput.value) folderInput.value = deploy.value.mcc_folder ?? "";
}

async function loadPreview() {
  if (!scopeReady.value || visitor.value) {
    preview.value = null;
    return;
  }
  const seq = ++previewSeq;
  previewLoading.value = true;
  previewError.value = "";
  try {
    const p = await api.buildPreview(scopeBody());
    if (seq === previewSeq) preview.value = p;
  } catch (e) {
    if (seq === previewSeq) {
      preview.value = null;
      previewError.value = message(e);
    }
  } finally {
    if (seq === previewSeq) previewLoading.value = false;
  }
}

watch([scope, mission, chosen], () => {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(loadPreview, 200);
});

// A job started before leaving the page, or from another tab or device: show the server's latest job and keep
// checking it while it runs.
async function resumeJob() {
  if (visitor.value) return;
  try {
    const current = await api.currentJob();
    const wasRunning = running.value;
    job.value = current;
    if (current?.state === "running") poll();
    else if (wasRunning) await Promise.all([refresh(), loadPreview()]);
  } catch {
    // keep what is shown; the next check tries again
  }
}

function onVisible() {
  if (document.visibilityState === "visible") void resumeJob();
}

onMounted(async () => {
  void resumeJob();
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("focus", onVisible);
  try {
    levels.value = (await api.state()).levels.map((l) => l.level);
    await refresh();
    if (builds.value?.missions.length && !builds.value.missions.includes(mission.value)) mission.value = builds.value.missions[0];
    await loadPreview();
  } catch (e) {
    error.value = message(e);
  }
});

onBeforeUnmount(() => {
  clearTimeout(timer);
  clearTimeout(previewTimer);
  document.removeEventListener("visibilitychange", onVisible);
  window.removeEventListener("focus", onVisible);
});

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

function startBuild(kind: BuildKind) {
  void run(() => api.startBuild({ kind, ...scopeBody(), name: name.value.trim() || undefined }));
}

const mb = (bytes: number | null) => (bytes === null ? "?" : bytes > 4 * 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`);

async function install(build: string) {
  error.value = "";
  try {
    const plan = await api.installPlan(build);
    const lines = plan.files.map(
      (f) => `• ${f.install_rel} (${mb(f.candidate_bytes)})\n   original ${f.original_sha256.slice(0, 12)}… → build ${f.candidate_sha256.slice(0, 12)}…`,
    );
    const warnings = [
      plan.validation_ok ? "" : "⚠ The build's validation report is not OK; it cannot be installed.",
      plan.stale ? `⚠ Stale: ${plan.stale_reasons.join("; ")}. Lines no longer approved make the installer refuse; newer approvals are simply not included.` : "",
    ].filter(Boolean);
    const ok = await confirmAction({
      title: `Install build ${build}`,
      message:
        `Install build "${build}" into MCC?\n\nGame folder: ${plan.mcc_folder}\n\nFiles replaced, as one operation:\n${lines.join("\n")}\n\n` +
        `Audio: ${plan.audio}.\nSubtitles: ${plan.subtitles}\n\nOriginals are verified and backed up to ${plan.files[0]?.backup_folder} first; ` +
        `any failure restores every one of them. MCC must stay closed until it finishes.${warnings.length ? `\n\n${warnings.join("\n")}` : ""}`,
      confirmLabel: "Install build",
      tone: "warning",
    });
    if (ok) await run(() => api.install(build));
  } catch (e) {
    error.value = message(e);
  }
}

async function restore() {
  const active = deploy.value?.active_builds.join(", ") || "the installed build";
  const files = deploy.value?.files.filter((f) => f.state !== "original").map((f) => `• ${f.install_rel}`) ?? [];
  const ok = await confirmAction({
    title: "Restore original game files",
    message:
      `Restore the original game files?\n\nInstalled: ${active}\n${files.join("\n")}\n\nEach replaced file is copied back from its ` +
      "verified backup and checked; audio and subtitle files are restored together. Backups are kept. MCC must be closed.",
    confirmLabel: "Restore now",
    tone: "warning",
  });
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
      else await Promise.all([refresh(), loadPreview()]);
    } catch (e) {
      error.value = message(e);
    }
  }, 1000);
}

const JOB_TEXT = { build: "Building", install: "Installing", restore: "Restoring" } as const;
const KIND_TEXT = { audio: "Audio", subtitles: "Subtitles", both: "Audio + subtitles", experiment: "Experiment" } as const;
const jobKind = computed(() => (job.value?.detail as { kind?: BuildKind } | undefined)?.kind);
const db = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)} dB`);
const levelName = (l: BuildLevel | { mode: string; global_gain_db: number | null }) =>
  l.mode === "match_spain" ? "match Spain" : `global gain ${db(l.global_gain_db)}`;
</script>

<template>
  <section class="builds-view">
    <PageHeader
      title="Build & Test"
      :icon="Hammer"
      :lead="visitor
        ? 'The builds made from approved decisions and the history of test installs. Read-only: building, installing and downloads are limited to the project owner.'
        : 'Build the Spanish dialogue bank and the LATAM subtitle tables from approved decisions, install them to try them in MCC, then restore the originals.'"
    />
    <StateMessage v-if="error" kind="error">{{ error }}</StateMessage>

    <section v-if="visitor" class="panel" aria-labelledby="installs-title" data-testid="public-install-history">
      <PanelHeader title="Test installs" title-id="installs-title" :icon="HardDriveDownload" />
      <DeployHistory :events="history" />
    </section>

    <div v-if="!visitor" class="builds-grid">
      <GainSetting @saved="refresh" />

      <section class="panel build-panel" aria-labelledby="build-title">
        <PanelHeader title="Build" title-id="build-title" :icon="FileAudio" code="M6" />
        <p class="muted small">
          Builds from your <strong>approved</strong> decisions only, into <code>work/m6/NAME</code>: the Spanish dialogue
          bank (audio, with edit recipes and the global gain), <code>SU_Halo1.bin</code> + <code>SP_Halo1.bin</code>
          (subtitles), or all three. Nothing in the game changes until you install a build.
        </p>
        <fieldset class="scope" :disabled="running">
          <legend>Scope</legend>
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
        <ScopePreview :preview="preview" :loading="previewLoading" :error="previewError" />
        <div class="row">
          <input v-model="name" class="grow-input" placeholder="Build name (optional)" aria-label="Build name" />
        </div>
        <div class="row build-actions">
          <button type="button" class="primary icon-label" :disabled="blocked('audio')" :title="blockedReason('audio')" @click="startBuild('audio')">
            <FileAudio :size="16" aria-hidden="true" /> Build audio
          </button>
          <button type="button" class="primary icon-label" :disabled="blocked('subtitles')" :title="blockedReason('subtitles')" @click="startBuild('subtitles')">
            <Captions :size="16" aria-hidden="true" /> Build subtitles
          </button>
          <button type="button" class="primary icon-label" :disabled="blocked('both')" :title="blockedReason('both')" @click="startBuild('both')">
            <Layers :size="16" aria-hidden="true" /> Build audio + subtitles
          </button>
        </div>
        <p class="small muted runtime-note"><TriangleAlert :size="12" aria-hidden="true" /> {{ builds?.runtime_note }}</p>

        <div v-if="job" class="job" data-testid="job" :data-state="job.state" :data-kind="job.kind" :data-id="job.id">
          <p class="small job-line">
            <span v-if="job.state === 'running'" class="loader" aria-hidden="true"><i></i><i></i><i></i></span>
            {{ JOB_TEXT[job.kind] }}<template v-if="job.kind === 'build' && jobKind"> ({{ KIND_TEXT[jobKind].toLowerCase() }})</template>
            <strong>{{ job.name }}</strong>:
            <StatusBadge :label="job.state" :tone="job.state === 'done' ? 'ok' : job.state === 'failed' ? 'bad' : 'warn'" />
            <span v-if="job.state === 'running'" class="muted"> (started {{ job.started }}; this page keeps checking)</span>
          </p>
          <pre v-if="job.log_tail" class="log">{{ job.log_tail }}</pre>
        </div>
      </section>
    </div>

    <section v-if="!visitor" class="panel" aria-labelledby="install-title">
      <PanelHeader title="Install to MCC" title-id="install-title" :icon="HardDriveDownload">
        <button type="button" class="icon-label small-button" :disabled="running" @click="refresh">
          <RefreshCw :size="14" aria-hidden="true" /> Check again
        </button>
      </PanelHeader>
      <div v-if="deploy" class="deploy-status" data-testid="deploy-status">
        <p class="small">
          <Folder :size="14" aria-hidden="true" /> Game folder:
          <code>{{ deploy.mcc_folder ?? "not found" }}</code> <span class="muted">({{ deploy.source }})</span>
          <StatusBadge v-if="!deploy.valid" label="not an MCC install" tone="bad" />
        </p>
        <StateMessage v-if="!permissions.install" kind="warning" data-testid="install-host-only">
          Installing into and restoring the game are only possible on the host computer's own Studio address
          (http://127.0.0.1:8765/), never from another computer.
        </StateMessage>
        <div v-if="!deploy.fixed && permissions.settings_mcc" class="row">
          <input v-model="folderInput" class="grow-input" aria-label="MCC folder" placeholder="…\steamapps\common\Halo The Master Chief Collection" />
          <button type="button" class="icon-label" @click="saveFolder"><Folder :size="15" aria-hidden="true" /> Use this folder</button>
        </div>
        <p class="small installed">
          Installed now:
          <StatusBadge v-if="!deploy.valid" label="unknown" tone="muted" />
          <StatusBadge v-else-if="!deploy.mod_installed" label="original game files" tone="ok" />
          <StatusBadge v-else-if="deploy.active_builds.length" :label="`build ${deploy.active_builds.join(', ')}`" tone="warn" />
          <StatusBadge v-else label="modified files that match no build" tone="bad" />
        </p>
        <ul class="small plain file-states">
          <li v-for="f in deploy.files" :key="f.install_rel" :data-file="f.install_rel" :data-state="f.state">
            <code>{{ f.install_rel }}</code>: {{ f.state === "original" ? "original" : f.state === "build" ? `build ${f.builds.join(", ")}` : "unknown content" }}
          </li>
        </ul>
        <div v-for="l in deploy.installed_level ?? []" :key="l.build" class="installed-level small" data-testid="installed-level">
          <p>
            Installed audio level (<strong>{{ l.build }}</strong>, built {{ l.built_at ?? "?" }}): {{ levelName(l) }} ·
            gain applied median {{ db(l.effective_gain_db?.median) }}
            <template v-if="l.loudness_vs_spain_db"> · vs Spain median {{ db(l.loudness_vs_spain_db.median) }}</template>
            · {{ l.constrained }} of {{ l.lines }} line(s) constrained
          </p>
          <StateMessage v-if="!l.matches_current && deploy.current_level" kind="warning">
            The installed build was made with {{ levelName(l) }}, but the Studio is now set to
            {{ levelName(deploy.current_level) }}. Restore, rebuild and install to hear the current setting.
          </StateMessage>
        </div>
        <StateMessage v-if="gameRunning" kind="warning">MCC appears to be running ({{ deploy.game_running.join(", ") }}). Close it to install or restore.</StateMessage>
        <div class="row">
          <button type="button" class="caution icon-label" :disabled="!canDeploy || !deploy.mod_installed" @click="restore">
            <Undo2 :size="16" aria-hidden="true" /> Restore originals
          </button>
        </div>
        <DeployHistory :events="history" />
        <p class="small muted"><TriangleAlert :size="12" aria-hidden="true" /> The Studio never starts MCC. After installing, launch it yourself (anti-cheat off), test, close it, then restore here.</p>
      </div>
      <StateMessage v-else-if="!error" kind="loading">Checking the game folder…</StateMessage>
    </section>

    <section class="panel quiet" aria-labelledby="builds-title">
      <PanelHeader title="Builds" title-id="builds-title" :icon="Layers" />
      <BuildHistory
        v-if="builds"
        :builds="builds.builds"
        :installed="deploy?.active_builds ?? []"
        :can-deploy="canDeploy"
        :mod-installed="Boolean(deploy?.mod_installed)"
        :read-only="visitor"
        @install="install"
      />
      <StateMessage v-else-if="!error" kind="loading">Loading builds…</StateMessage>
    </section>
  </section>
</template>
