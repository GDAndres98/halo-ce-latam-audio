<script setup lang="ts">
// Centre column: the decision for the selected MCC line. Both recordings side by side, then the audio
// choice, the audio editing, the subtitle, the flags and the approval controls.

import { computed, ref, watch } from "vue";
import { audioUrl } from "../../api/client";
import { clipDuration } from "../../audio/clipInfo";
import AudioButton from "../AudioButton.vue";
import StatusBadge from "../StatusBadge.vue";
import AudioDecision from "./AudioDecision.vue";
import AudioEditor from "./AudioEditor.vue";
import ApprovalBar from "./ApprovalBar.vue";
import SubtitleDecision from "./SubtitleDecision.vue";
import type { MatchState } from "../../composables/useMatch";

const props = defineProps<{ match: MatchState }>();

const detail = computed(() => props.match.detail.value);
const draft = computed(() => props.match.draft);
const stored = computed(() => detail.value?.mapping ?? null);
const audioLocked = computed(() => stored.value?.audio.status === "approved");
const subtitleLocked = computed(() => stored.value?.subtitle.status === "approved");

const mccUrl = computed(() => (detail.value ? audioUrl.mcc(detail.value.level, "spanish", detail.value.spanish.index) : null));
const mccSeconds = computed(() => detail.value?.spanish.duration_s ?? null);

const replacementUrl = computed(() =>
  draft.value && draft.value.audioSource === "ce" && draft.value.audioRef
    ? audioUrl.ce(draft.value.audioRef, draft.value.audioLanguage)
    : null,
);
const replacementSeconds = ref<number | null>(null);
watch(
  replacementUrl,
  async (url) => {
    replacementSeconds.value = url ? await clipDuration(url) : null;
  },
  { immediate: true },
);
</script>

<template>
  <section class="column center">
    <template v-if="detail && draft">
      <header class="line-title">
        <h2>{{ detail.tag_name }}</h2>
        <p class="muted small mono">{{ detail.slot_id }} · speaker {{ detail.speaker_from_name || "—" }}</p>
        <StatusBadge v-if="match.dirty()" label="unsaved changes" tone="warn" />
      </header>

      <div class="side-by-side">
        <div class="recording">
          <h3>MCC (Spain)</h3>
          <AudioButton v-if="mccUrl" :url="mccUrl" label="Play (m)" />
          <p class="small">{{ mccSeconds === null ? "—" : `${mccSeconds.toFixed(2)} s` }}</p>
        </div>
        <div class="recording">
          <h3>Replacement (CE)</h3>
          <AudioButton v-if="replacementUrl" :url="replacementUrl" label="Play (e)" />
          <p v-else class="small muted">None chosen</p>
          <p class="small">
            {{ replacementSeconds === null ? "—" : `${replacementSeconds.toFixed(2)} s` }}
            <span v-if="mccSeconds !== null && replacementSeconds !== null" class="muted">
              ({{ replacementSeconds - mccSeconds >= 0 ? "+" : "" }}{{ (replacementSeconds - mccSeconds).toFixed(2) }} s)
            </span>
          </p>
        </div>
      </div>

      <div class="status-row">
        <StatusBadge :label="`match: ${draft.matchStatus}`" :tone="draft.matchStatus === 'matched' ? 'ok' : 'muted'" />
        <StatusBadge :label="`audio: ${stored?.audio.status ?? 'not decided'}`" :tone="stored?.audio.status === 'approved' ? 'ok' : 'warn'" />
        <StatusBadge :label="`subtitle: ${stored?.subtitle.status ?? 'not decided'}`" :tone="stored?.subtitle.status === 'approved' ? 'ok' : 'warn'" />
      </div>

      <AudioDecision :draft="draft" :locked="audioLocked" :mcc-duration="mccSeconds" />
      <AudioEditor :draft="draft" :locked="audioLocked" :slot-id="detail.slot_id" />
      <SubtitleDecision :draft="draft" :locked="subtitleLocked" :detail="detail" />

      <section class="block">
        <h3>Flags and notes</h3>
        <label class="opt">
          <input v-model="draft.radio" type="checkbox" />
          Needs radio effect (flag only: no processing is applied yet)
        </label>
        <label class="opt">
          <input v-model="draft.fits" type="checkbox" />
          Different but fits
        </label>
        <label class="block-label">Notes
          <textarea v-model="draft.notes" rows="2" maxlength="2000"></textarea>
        </label>
      </section>

      <ApprovalBar :match="match" />
    </template>

    <p v-else-if="match.loading.value" class="muted">Loading line…</p>
    <p v-else-if="match.error.value" class="error">{{ match.error.value }}</p>
    <p v-else class="muted">Choose an MCC line on the left to start matching.</p>
  </section>
</template>
