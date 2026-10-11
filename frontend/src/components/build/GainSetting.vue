<script setup lang="ts">
// The global audio gain: one number for every Campaign Evolved replacement, applied once at export.
// It is a global export setting, not a per-line control (per-line gain was removed on 2026-10-09).
// Changing it does not rebuild anything: builds made with the old value are marked stale.

import { computed, onMounted, ref } from "vue";
import { api, ApiError } from "../../api/client";
import type { ExportSettings } from "../../api/types";

const DEFAULT_GAIN_DB = 4;
const RANGE_DB = { min: -12, max: 12 };

const emit = defineEmits<{ saved: [] }>();

const settings = ref<ExportSettings | null>(null);
const input = ref<number>(DEFAULT_GAIN_DB);
const message = ref("");
const error = ref("");
const busy = ref(false);

const current = computed(() => settings.value?.global_gain_db ?? DEFAULT_GAIN_DB);
const unchanged = computed(() => Number(input.value) === current.value);
const valid = computed(() => Number.isFinite(Number(input.value)) && Number(input.value) >= RANGE_DB.min && Number(input.value) <= RANGE_DB.max);
const signed = (db: number) => `${db >= 0 ? "+" : ""}${db.toFixed(1)} dB`;

async function load() {
  try {
    settings.value = await api.exportSettings();
    input.value = settings.value.global_gain_db;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function save(value: number) {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    settings.value = await api.saveExportSettings(value, settings.value?.sha256 ?? null);
    input.value = settings.value.global_gain_db;
    message.value = `Global gain set to ${signed(settings.value.global_gain_db)}. Builds made with another gain are now marked stale.`;
    emit("saved");
  } catch (e) {
    error.value = e instanceof ApiError && e.status === 409
      ? `${e.message} Nothing was saved; the page has been refreshed.`
      : e instanceof Error ? e.message : String(e);
    if (e instanceof ApiError && e.status === 409) await load();
  } finally {
    busy.value = false;
  }
}

const apply = () => valid.value && save(Number(input.value));
const resetToDefault = () => save(DEFAULT_GAIN_DB);

onMounted(load);
</script>

<template>
  <section class="card gain" aria-labelledby="gain-title">
    <h2 id="gain-title">Global audio gain</h2>
    <p class="muted small">
      Applied once to every Campaign Evolved replacement when a build is exported. Lines are never limited:
      a line that would peak above −1 dBFS gets less gain, and the build reports it.
    </p>

    <div class="gain-row">
      <label>
        Gain (dB)
        <input
          v-model.number="input"
          type="number"
          :min="RANGE_DB.min"
          :max="RANGE_DB.max"
          step="0.5"
          :disabled="busy || !settings"
          :aria-invalid="!valid"
          aria-describedby="gain-help"
        />
      </label>
      <button type="button" class="primary" :disabled="busy || !settings || unchanged || !valid" @click="apply">
        Save gain
      </button>
      <button type="button" :disabled="busy || !settings || current === DEFAULT_GAIN_DB" @click="resetToDefault">
        Reset to default (+4 dB)
      </button>
    </div>

    <p id="gain-help" class="small">
      Current: <strong>{{ settings ? signed(settings.global_gain_db) : "…" }}</strong>
      <span class="muted">({{ settings?.source === "default" ? "default, no saved setting" : "saved on this computer" }})</span>
      · allowed {{ RANGE_DB.min }} to +{{ RANGE_DB.max }} dB
    </p>
    <p v-if="!valid" class="error small">Enter a value between {{ RANGE_DB.min }} and +{{ RANGE_DB.max }} dB.</p>
    <p v-if="message" class="ok small" role="status">{{ message }}</p>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>

    <details class="order">
      <summary>How the audio is processed, in order</summary>
      <ol class="small">
        <li>Sources are converted to 44.1 kHz mono.</li>
        <li>The edit recipe: trims, cuts, fades and inserted silences.</li>
        <li>Optional loudness match to Spain's recording (only where chosen on the line).</li>
        <li><strong>Global gain</strong>: applied exactly once, linearly, never limited (see above).</li>
        <li>Rounding to 16-bit, then encoding for the game (CELT).</li>
      </ol>
      <p class="small muted">
        Previews in the editor use the same steps, so what you hear is what the build writes. Speed and
        per-line gain do not exist any more.
      </p>
    </details>
  </section>
</template>
