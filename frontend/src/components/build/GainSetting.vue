<script setup lang="ts">
// How every Campaign Evolved replacement's level is set at export. Two build-level modes, never per line:
//   global gain  one number for every replacement, applied once, linear, never limited (default, +4 dB);
//   match Spain  each line brought to the loudness of the Spain recording it replaces, with a look-ahead
//                limiter capped at 6 dB (owner, 2026-10-11, after measuring the installed bank).
// Changing either does not rebuild anything: builds made with other settings are marked stale.

import { RotateCcw, Save, Volume2 } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api, ApiError } from "../../api/client";
import { permissions } from "../../auth/session";
import type { ExportSettings, LevelMode } from "../../api/types";
import PanelHeader from "../ui/PanelHeader.vue";
import StateMessage from "../ui/StateMessage.vue";

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

const MODE_TEXT: Record<LevelMode, string> = { global_gain: "global gain", match_spain: "match Spain's loudness" };

async function save(value: number | null, mode?: LevelMode) {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    settings.value = await api.saveExportSettings(value, settings.value?.sha256 ?? null, mode);
    input.value = settings.value.global_gain_db;
    message.value = mode
      ? `Level set to ${MODE_TEXT[settings.value.level_mode]}. Audio builds made in the other mode are now marked stale.`
      : `Global gain set to ${signed(settings.value.global_gain_db)}. Builds made with another gain are now marked stale.`;
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
const mode = computed(() => settings.value?.level_mode ?? "global_gain");
const setMode = (m: LevelMode) => m !== mode.value && save(null, m);

onMounted(load);
</script>

<template>
  <section class="panel gain" aria-labelledby="gain-title">
    <PanelHeader title="Global audio gain" title-id="gain-title" :icon="Volume2" code="EXPORT" />
    <fieldset class="scope level-mode" :disabled="busy || !settings || !permissions.admin" data-testid="level-mode">
      <legend>Level</legend>
      <label class="check">
        <input type="radio" name="level-mode" :checked="mode === 'global_gain'" @change="setMode('global_gain')" />
        Global gain: the same gain for every line, never limited
      </label>
      <label class="check">
        <input type="radio" name="level-mode" :checked="mode === 'match_spain'" @change="setMode('match_spain')" />
        Match Spain's loudness: each line as loud as the Spain recording it replaces
      </label>
    </fieldset>
    <p v-if="mode === 'global_gain'" class="muted small">
      The gain below is applied once to every Campaign Evolved replacement when a build is exported. Lines are never
      limited: a line that would peak above −1 dBFS gets less gain, and the build reports it.
    </p>
    <p v-else class="muted small">
      Each replacement gets the gain that brings it to the loudness of the Spain recording it replaces, so quiet lines
      stay quiet and shouts stay loud. A look-ahead limiter keeps peaks at −1 dBFS and takes at most 6 dB off any peak;
      a line that would need more gets less gain, and the build reports it. The global gain below is kept but not used.
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
          :disabled="busy || !settings || !permissions.admin"
          :aria-invalid="!valid"
          aria-describedby="gain-help"
        />
      </label>
      <button type="button" class="primary icon-label" :disabled="busy || !settings || !permissions.admin || unchanged || !valid" @click="apply">
        <Save :size="16" aria-hidden="true" /> Save gain
      </button>
      <button type="button" class="icon-label" :disabled="busy || !settings || !permissions.admin || current === DEFAULT_GAIN_DB" @click="resetToDefault">
        <RotateCcw :size="15" aria-hidden="true" /> Reset to default (+4 dB)
      </button>
    </div>

    <p id="gain-help" class="small">
      Current: <strong class="gain-value">{{ settings ? signed(settings.global_gain_db) : "…" }}</strong>
      <span class="muted">({{ settings?.source === "default" ? "default, no saved setting" : "saved on this computer" }})</span>
      · allowed {{ RANGE_DB.min }} to +{{ RANGE_DB.max }} dB
    </p>
    <p v-if="!valid" class="error small">Enter a value between {{ RANGE_DB.min }} and +{{ RANGE_DB.max }} dB.</p>
    <StateMessage v-if="message" kind="success" class="small">{{ message }}</StateMessage>
    <StateMessage v-if="error" kind="error" class="small">{{ error }}</StateMessage>

    <details class="order">
      <summary>How the audio is processed, in order</summary>
      <ol class="small">
        <li>Sources are converted to 44.1 kHz mono.</li>
        <li>The edit recipe: trims, cuts, fades and inserted silences.</li>
        <li>
          <strong>Level</strong>, by the mode above: the global gain (once, linear, never limited), or matching each
          Spain recording (limiting capped at 6 dB).
        </li>
        <li>Rounding to 16-bit, then encoding for the game (CELT).</li>
      </ol>
      <p class="small muted">
        Previews in the editor use the same steps, so what you hear is what the build writes. Speed and
        per-line gain do not exist any more.
      </p>
    </details>
  </section>
</template>
