<script setup lang="ts">
// Centre column: the decision for the selected MCC line, in working order:
//   1. Replacement audio: which MCC line this is (its key, always visible), the chosen replacement, and the
//      audio decision with its approval.
//   2. Flags & notes.
//   3. Audio editing of the chosen recording.
//   4. Listen & compare: the original (A) against the edited replacement (B), rendered automatically.
//   5. Subtitles, with their own approval.
// The save bar stays in view at the bottom: one Save draft writes audio, subtitle, flags and notes together.

import { FileAudio, ListChecks, Unlink } from "lucide-vue-next";
import { computed } from "vue";
import { audioUrl } from "../../api/client";
import AudioButton from "../AudioButton.vue";
import type { CeLine } from "../../api/types";
import { useEditPreview } from "../../composables/useEditPreview";
import type { MatchState } from "../../composables/useMatch";
import StatusBadge from "../StatusBadge.vue";
import CopyButton from "../ui/CopyButton.vue";
import DownloadLink from "../ui/DownloadLink.vue";
import StateMessage from "../ui/StateMessage.vue";
import AudioCompare from "../waveform/AudioCompare.vue";
import AudioDecision from "./AudioDecision.vue";
import AudioEditor from "./AudioEditor.vue";
import FlagsNotes from "./FlagsNotes.vue";
import { FLAGS, FLAG_ORDER } from "./flags";
import { canUnmatch } from "../../matching/draft";
import SaveBar from "./SaveBar.vue";
import SubtitleDecision from "./SubtitleDecision.vue";

const props = defineProps<{
  match: MatchState;
  /** The MCC line selected in the list (from the URL): shown at once, even while its decision loads. */
  slotId: string | null;
}>();
const emit = defineEmits<{ saveNext: []; browse: [] }>();

const detail = computed(() => props.match.detail.value);
const shownKey = computed(() => props.slotId ?? detail.value?.slot_id ?? "");
// Busy until the latest load has answered: an older answer may already show the same line, and the newer
// one would replace anything changed meanwhile.
const switching = computed(
  () => Boolean(detail.value && ((props.slotId && props.slotId !== detail.value.slot_id) || props.match.loading.value)),
);
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

/** Short language code for file names and the download button ("es-MX"). */
const LANGUAGE_CODES: Record<string, string> = { "Spanish(Mexico)": "es-MX", "English(US)": "en-US", "Spanish(Spain)": "es-ES" };
const languageCode = computed(() => LANGUAGE_CODES[draft.value.audioLanguage] ?? draft.value.audioLanguage);
/** The CE line ref as a file name part: vo_scr_m06_00740_victor933#0 -> vo_scr_m06_00740_victor933_0. */
const ceFileBase = computed(() => (draft.value.audioRef ?? "").replace("#", "_"));

/** The draft's Campaign Evolved lines with their subtitles (saved matches and recordings chosen since). */
const draftLines = computed<CeLine[]>(() =>
  draft.value.ceRefs.map((ref) => props.match.lines.get(ref)).filter((line): line is CeLine => Boolean(line)),
);
const activeFlags = computed(() => FLAG_ORDER.filter((name) => draft.value[name]).map((name) => FLAGS[name]));
const matchTone = computed(() => (draft.value.matchStatus === "matched" ? "ok" : "muted"));
const unmatchable = computed(() => canUnmatch(stored.value, draft.value));
const unmatchTitle = computed(() =>
  unmatchable.value.allowed
    ? "Remove every Campaign Evolved line and keep Spain's audio (save the draft to keep it)"
    : unmatchable.value.reason,
);

/** MCC's three subtitle tables for this line, in the order they matter for the LATAM build. */
const MCC_TABLES: { key: string; label: string }[] = [
  { key: "SU", label: "MCC LATAM (SU)" },
  { key: "SP", label: "MCC Spain (SP)" },
  { key: "EN", label: "MCC English (EN)" },
];
const englishName = (sample: { name_in_bank: string; ordinal_in_tag: number }) =>
  `${sample.name_in_bank} #${sample.ordinal_in_tag}`;

function statusOf(field: "audio" | "subtitle") {
  const status = stored.value?.[field].status;
  return {
    label: `${field}: ${status ? status.replace("_", " ") : "not saved"}`,
    tone: (status === "approved" ? "ok" : status === "needs_rework" ? "bad" : status ? "warn" : "muted") as
      | "ok"
      | "bad"
      | "warn"
      | "muted",
  };
}

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
          <DownloadLink
            v-if="mccUrl && !switching"
            :url="mccUrl"
            :file-name="`${detail.level}_${detail.slot_id.replace(/^es:/, '')}_spain.wav`"
            label="Download the MCC Spain recording (WAV)"
            data-testid="download-mcc-spain"
          />
          <p v-if="switching" class="source-meta small muted">Loading this line…</p>
          <div v-else class="source-meta line-title">
            <h2>{{ detail.tag_name }}</h2>
            <p class="small muted">speaker {{ detail.speaker_from_name || "—" }} · {{ detail.spanish.duration_s.toFixed(2) }} s (Spain)</p>
          </div>
        </div>

        <div v-if="detail.english.length" class="english-takes" data-testid="english-takes">
          <span class="source-tag">MCC English recordings</span>
          <ul>
            <li v-for="sample in detail.english" :key="sample.index">
              <AudioButton
                :url="audioUrl.mcc(detail.level, 'english', sample.index)"
                label=""
                :title="`English ${englishName(sample)}`"
              />
              <span class="mono small">{{ englishName(sample) }}</span>
              <DownloadLink
                :url="audioUrl.mcc(detail.level, 'english', sample.index)"
                :file-name="`${detail.level}_${sample.name_in_bank}_${sample.ordinal_in_tag}_english.wav`"
                :label="`Download English ${englishName(sample)} (WAV)`"
                data-testid="download-mcc-english"
              />
            </li>
          </ul>
        </div>

        <dl class="texts mcc-texts" data-testid="mcc-subtitles">
          <template v-for="t in MCC_TABLES" :key="t.key">
            <dt>{{ t.label }}</dt>
            <dd>
              <span v-if="detail.mcc_subtitles[t.key]?.text">{{ detail.mcc_subtitles[t.key]?.text }}</span>
              <span v-else class="missing">No text.</span>
            </dd>
          </template>
        </dl>

        <div class="source-card ce-source" :class="{ empty: draft.audioSource !== 'ce' }" data-testid="ce-replacement">
          <span class="source-tag">Campaign Evolved replacement</span>
          <template v-if="draft.audioSource === 'ce' && draft.audioRef">
            <code class="source-key" data-testid="ce-key" :title="draft.audioRef">{{ draft.audioRef }}</code>
            <CopyButton :text="draft.audioRef" label="Copy the Campaign Evolved key" />
            <span class="ce-downloads">
              <DownloadLink
                v-if="replacement.unedited"
                :url="replacement.unedited"
                :file-name="`${ceFileBase}_${languageCode}.wav`"
                :text="languageCode"
                :label="`Download the Campaign Evolved ${languageCode} recording (WAV)`"
                data-testid="download-ce"
              />
              <DownloadLink
                v-if="replacement.edited"
                :url="replacement.edited"
                :file-name="`${detail.level}_${detail.slot_id.replace(/^es:/, '')}_${ceFileBase}_${languageCode}_draft.wav`"
                text="Draft"
                label="Download the edited draft (WAV): the current edits as the build renders them, before encoding"
                data-testid="download-ce-draft"
              />
              <span v-else-if="preview.rendering.value" class="small muted" data-testid="draft-rendering">rendering the draft…</span>
            </span>
          </template>
          <span v-else class="source-key muted">None: Spain's audio stays</span>
        </div>

        <div class="status-row">
          <StatusBadge :label="`match: ${draft.matchStatus}`" :tone="matchTone" />
          <StatusBadge v-if="match.dirty()" label="unsaved changes" tone="warn" />
          <button
            type="button"
            class="icon-label small-button"
            :disabled="!unmatchable.allowed || switching"
            :title="unmatchTitle"
            data-testid="unmatch"
            @click="match.unmatch()"
          >
            <Unlink :size="14" aria-hidden="true" /> Unmatch
          </button>
          <span v-for="flag in activeFlags" :key="flag.name" class="badge flag-badge" :class="`flag-${flag.name}`" :title="flag.label">
            <component :is="flag.icon" :size="13" aria-hidden="true" /> {{ flag.label }}
          </span>
        </div>

        <AudioDecision :draft="draft" :locked="audioLocked" @choose="choose" @remove="match.removeMatch" />
        <p class="decision-status"><StatusBadge v-bind="statusOf('audio')" /></p>
      </section>

      <!-- 2. Flags & notes -->
      <FlagsNotes :draft="draft" />

      <!-- 3. Audio editing -->
      <AudioEditor
        :key="detail.slot_id" :draft="draft" :locked="audioLocked"
        :interference="detail.interference?.[draft.audioRef ?? ''] ?? null" :slot-id="detail.slot_id"
        :original-url="mccUrl" :preview-url="replacement.edited"
      />

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
        <p class="decision-status"><StatusBadge v-bind="statusOf('subtitle')" /></p>
      </SubtitleDecision>

      <SaveBar :match="match" @save-next="emit('saveNext')" />
    </template>

    <StateMessage v-else-if="match.loading.value" kind="loading">Loading line…</StateMessage>
    <StateMessage v-else-if="match.error.value" kind="error">{{ match.error.value }}</StateMessage>
    <div v-else class="center-empty">
      <ListChecks :size="56" aria-hidden="true" />
      <p class="pointer-only">Choose an MCC line on the left to start matching.</p>
      <p class="small pointer-only"><kbd>J</kbd> / <kbd>K</kbd> step through the lines · <kbd>U</kbd> next unmatched</p>
      <p class="touch-only">Choose an MCC line to start matching.</p>
      <button type="button" class="primary icon-label touch-only" data-testid="browse-mcc" @click="emit('browse')">Browse MCC lines</button>
    </div>
  </section>
</template>
