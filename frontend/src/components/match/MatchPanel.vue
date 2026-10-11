<script setup lang="ts">
// Centre column: the decision for the selected MCC line, in working order:
//   1. Replacement audio: which MCC line this is (its key, always visible), the chosen replacement, and the
//      audio decision with its approval.
//   2. Flags & notes.
//   3. Audio editing of the chosen recording.
//   4. Listen & compare: the original (A) against the edited replacement (B), rendered automatically.
//   5. Subtitles, with their own approval.
// The save bar stays in view at the bottom: one Save draft writes audio, subtitle, flags and notes together.

import { FileAudio, ListChecks } from "lucide-vue-next";
import { computed } from "vue";
import { audioUrl } from "../../api/client";
import type { CeLine } from "../../api/types";
import { useEditPreview } from "../../composables/useEditPreview";
import type { MatchState } from "../../composables/useMatch";
import StatusBadge from "../StatusBadge.vue";
import CopyButton from "../ui/CopyButton.vue";
import StateMessage from "../ui/StateMessage.vue";
import AudioCompare from "../waveform/AudioCompare.vue";
import ApprovalControls from "./ApprovalControls.vue";
import AudioDecision from "./AudioDecision.vue";
import AudioEditor from "./AudioEditor.vue";
import FlagsNotes from "./FlagsNotes.vue";
import { FLAGS, FLAG_ORDER } from "./flags";
import SaveBar from "./SaveBar.vue";
import SubtitleDecision from "./SubtitleDecision.vue";

const props = defineProps<{
  match: MatchState;
  /** The MCC line selected in the list (from the URL): shown at once, even while its decision loads. */
  slotId: string | null;
}>();
const emit = defineEmits<{ saveNext: [] }>();

const detail = computed(() => props.match.detail.value);
const shownKey = computed(() => props.slotId ?? detail.value?.slot_id ?? "");
const switching = computed(() => Boolean(detail.value && props.slotId && props.slotId !== detail.value.slot_id));
const draft = computed(() => props.match.draft);
const stored = computed(() => detail.value?.mapping ?? null);
const audioLocked = computed(() => stored.value?.audio.status === "approved");
const subtitleLocked = computed(() => stored.value?.subtitle.status === "approved");

const mccUrl = computed(() => (detail.value ? audioUrl.mcc(detail.value.level, "spanish", detail.value.spanish.index) : null));

// The edited replacement is rendered automatically; only a preview of the current recipe is offered.
const preview = useEditPreview(props.match);
const canRender = computed(() => detail.value?.edit?.available !== false);
const replacement = computed(() => {
  const d = draft.value;
  const unedited = d.audioSource === "ce" && d.audioRef ? audioUrl.ce(d.audioRef, d.audioLanguage) : null;
  const current = unedited ? preview.current.value : null;
  return { unedited, edited: current?.edited ?? null, encoded: current?.encoded ?? null };
});

/** The draft's Campaign Evolved lines with their subtitles (saved matches and recordings chosen since). */
const draftLines = computed<CeLine[]>(() =>
  draft.value.ceRefs.map((ref) => props.match.lines.get(ref)).filter((line): line is CeLine => Boolean(line)),
);
const activeFlags = computed(() => FLAG_ORDER.filter((name) => draft.value[name]).map((name) => FLAGS[name]));
const matchTone = computed(() => (draft.value.matchStatus === "matched" ? "ok" : "muted"));

async function choose(ref: string) {
  await props.match.chooseRecording(ref);
}
</script>

<template>
  <!-- While another line loads, only its key is current: the rest is dimmed and cannot be changed. -->
  <section class="column center sections" :class="{ switching }" :aria-busy="switching">
    <template v-if="detail && draft">
      <!-- 1. Replacement audio -->
      <section class="block replacement" aria-label="Replacement audio" data-section="replacement">
        <h3><FileAudio :size="15" aria-hidden="true" /> Replacement audio</h3>

        <div class="source-card mcc-source" data-testid="mcc-original">
          <span class="source-tag">MCC original</span>
          <code class="source-key" data-testid="mcc-key" :title="shownKey">{{ shownKey }}</code>
          <CopyButton :text="shownKey" label="Copy the MCC key" data-testid="copy-mcc-key" />
          <p v-if="switching" class="source-meta small muted">Loading this line…</p>
          <div v-else class="source-meta line-title">
            <h2>{{ detail.tag_name }}</h2>
            <p class="small muted">{{ detail.slot_id }} · speaker {{ detail.speaker_from_name || "—" }} · {{ detail.spanish.duration_s.toFixed(2) }} s (Spain)</p>
          </div>
        </div>

        <div class="source-card ce-source" :class="{ empty: draft.audioSource !== 'ce' }" data-testid="ce-replacement">
          <span class="source-tag">Campaign Evolved replacement</span>
          <template v-if="draft.audioSource === 'ce' && draft.audioRef">
            <code class="source-key" data-testid="ce-key" :title="draft.audioRef">{{ draft.audioRef }}</code>
            <CopyButton :text="draft.audioRef" label="Copy the Campaign Evolved key" />
          </template>
          <span v-else class="source-key muted">None: Spain's audio stays</span>
        </div>

        <div class="status-row">
          <StatusBadge :label="`match: ${draft.matchStatus}`" :tone="matchTone" />
          <StatusBadge v-if="match.dirty()" label="unsaved changes" tone="warn" />
          <span v-for="flag in activeFlags" :key="flag.name" class="badge flag-badge" :class="`flag-${flag.name}`" :title="flag.label">
            <component :is="flag.icon" :size="13" aria-hidden="true" /> {{ flag.label }}
          </span>
        </div>

        <AudioDecision :draft="draft" :locked="audioLocked" @choose="choose" @remove="match.removeMatch" />
        <ApprovalControls :match="match" field="audio" />
      </section>

      <!-- 2. Flags & notes -->
      <FlagsNotes :draft="draft" />

      <!-- 3. Audio editing -->
      <AudioEditor :key="detail.slot_id" :draft="draft" :locked="audioLocked" />

      <!-- 4. Listen & compare -->
      <AudioCompare
        :key="detail.slot_id"
        :mcc-url="mccUrl"
        :replacement="replacement"
        :can-render="canRender"
        :rendering="preview.rendering.value"
        :errors="preview.errors.value"
        :stats="preview.current.value?.stats ?? null"
      />

      <!-- 5. Subtitles -->
      <SubtitleDecision
        :draft="draft"
        :baseline="match.baseline.value"
        :locked="subtitleLocked"
        :detail="detail"
        :lines="draftLines"
        :proposed-ref="match.proposedSubtitle.value"
      >
        <ApprovalControls :match="match" field="subtitle" />
      </SubtitleDecision>

      <SaveBar :match="match" @save-next="emit('saveNext')" />
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
