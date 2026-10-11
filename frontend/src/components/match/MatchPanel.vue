<script setup lang="ts">
// Centre column: the decision for the selected MCC line. The two recordings first (listen and compare),
// then the audio choice, the audio editing, the subtitle, the flags and the approval controls.

import { Flag, ListChecks, RadioTower, Puzzle } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { audioUrl } from "../../api/client";
import StatusBadge from "../StatusBadge.vue";
import StateMessage from "../ui/StateMessage.vue";
import AudioCompare from "../waveform/AudioCompare.vue";
import AudioDecision from "./AudioDecision.vue";
import AudioEditor, { type EditPreview } from "./AudioEditor.vue";
import ApprovalBar from "./ApprovalBar.vue";
import SubtitleDecision from "./SubtitleDecision.vue";
import type { MatchState } from "../../composables/useMatch";

const props = defineProps<{ match: MatchState }>();
const emit = defineEmits<{ saveNext: [] }>();

const detail = computed(() => props.match.detail.value);
const draft = computed(() => props.match.draft);
const stored = computed(() => detail.value?.mapping ?? null);
const audioLocked = computed(() => stored.value?.audio.status === "approved");
const subtitleLocked = computed(() => stored.value?.subtitle.status === "approved");

const mccUrl = computed(() => (detail.value ? audioUrl.mcc(detail.value.level, "spanish", detail.value.spanish.index) : null));
const mccSeconds = computed(() => detail.value?.spanish.duration_s ?? null);

// The latest edited preview (rendered by the editor), heard as B in the comparison.
const preview = ref<EditPreview | null>(null);
watch(() => detail.value?.slot_id, () => (preview.value = null));
const replacement = computed(() => {
  const d = draft.value;
  const unedited = d && d.audioSource === "ce" && d.audioRef ? audioUrl.ce(d.audioRef, d.audioLanguage) : null;
  return { unedited, edited: unedited ? preview.value?.edited ?? null : null, encoded: unedited ? preview.value?.encoded ?? null : null };
});
const statusTone = (status: string | undefined) =>
  status === "approved" ? "ok" : status === "needs_rework" ? "bad" : status ? "warn" : "muted";
const previewStale = computed(() => preview.value !== null && preview.value.recipe !== JSON.stringify(draft.value.edit));
</script>

<template>
  <section class="column center sections">
    <template v-if="detail && draft">
      <header class="line-title">
        <h2>{{ detail.tag_name }}</h2>
        <p class="ident">
          <span class="muted small mono">{{ detail.slot_id }} · speaker {{ detail.speaker_from_name || "—" }}</span>
          <StatusBadge v-if="match.dirty()" label="unsaved changes" tone="warn" />
        </p>
      </header>

      <div class="status-row">
        <StatusBadge :label="`match: ${draft.matchStatus}`" :tone="draft.matchStatus === 'matched' ? 'ok' : 'muted'" />
        <StatusBadge :label="`audio: ${stored?.audio.status ?? 'not decided'}`" :tone="statusTone(stored?.audio.status)" />
        <StatusBadge :label="`subtitle: ${stored?.subtitle.status ?? 'not decided'}`" :tone="statusTone(stored?.subtitle.status)" />
        <StatusBadge v-if="draft.radio" label="radio effect" tone="info" />
      </div>

      <AudioCompare :key="detail.slot_id" :mcc-url="mccUrl" :replacement="replacement" :preview-stale="previewStale" />
      <AudioDecision :draft="draft" :locked="audioLocked" :mcc-duration="mccSeconds" />
      <AudioEditor
        :key="detail.slot_id"
        :draft="draft"
        :locked="audioLocked"
        :slot-id="detail.slot_id"
        @preview="(p) => (preview = p)"
      />
      <SubtitleDecision :draft="draft" :locked="subtitleLocked" :detail="detail" />

      <section class="block">
        <h3><Flag :size="15" aria-hidden="true" /> Flags and notes</h3>
        <div class="flag-list">
          <label class="opt">
            <input v-model="draft.radio" type="checkbox" />
            <RadioTower :size="16" class="muted" aria-hidden="true" />
            Needs radio effect (flag only: no processing is applied yet)
          </label>
          <label class="opt">
            <input v-model="draft.fits" type="checkbox" />
            <Puzzle :size="16" class="muted" aria-hidden="true" />
            Different but fits
          </label>
        </div>
        <label class="block-label">Notes
          <textarea v-model="draft.notes" rows="2" maxlength="2000"></textarea>
        </label>
      </section>

      <ApprovalBar :match="match" @save-next="emit('saveNext')" />
    </template>

    <StateMessage v-else-if="match.loading.value" kind="loading">Loading line…</StateMessage>
    <StateMessage v-else-if="match.error.value" kind="error">{{ match.error.value }}</StateMessage>
    <div v-else class="center-empty">
      <ListChecks :size="56" aria-hidden="true" />
      <p>Choose an MCC line on the left to start matching.</p>
      <p class="small"><kbd>J</kbd> / <kbd>K</kbd> step through the lines · <kbd>U</kbd> next unmatched</p>
    </div>
  </section>
</template>
