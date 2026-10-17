<script setup lang="ts">
// Subtitle choice for one MCC line: the LATAM text that the build will write (SU), with the other texts
// shown for comparison. Independent of the audio decision: no audio match is needed to choose a subtitle,
// and a recording chosen but not saved yet can already give its subtitle (both are saved together).
//
// "Missing" (MCC has no text for this line) and "omitted" (the user chose no subtitle) are shown
// differently on purpose: a missing text is a problem to look at, an omitted one is a decision.

import { Captions, Sparkles } from "lucide-vue-next";
import { computed, watch } from "vue";
import type { CeLine, SlotDetail, SubtitleSource } from "../../api/types";
import { LATAM_CULTURE, subtitleDirty, type Draft } from "../../matching/draft";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{
  draft: Draft;
  /** What is saved, to tell an unsaved choice apart. */
  baseline: Draft | null;
  locked: boolean;
  /** The public read-only view: shown as stored, with no editing advice. */
  readOnly?: boolean;
  detail: SlotDetail;
  /** The Campaign Evolved lines of the draft's match, saved or not (in match order). */
  lines: CeLine[];
  /** The CE line whose subtitle was proposed when its recording was chosen (unsaved). */
  proposedRef: string | null;
}>();

const SOURCES: { value: SubtitleSource; label: string }[] = [
  { value: "keep_original", label: "Keep MCC's LATAM text (SU)" },
  { value: "ce_locres", label: "Use a Campaign Evolved subtitle" },
  { value: "custom", label: "Write my own LATAM Spanish text" },
  { value: "none", label: "No subtitle (intentionally omitted)" },
];

const CULTURES = [LATAM_CULTURE, "en", "es-ES"];

const mccText = (key: string): { text: string | null; missing: boolean } => {
  const entry = props.detail.mcc_subtitles[key];
  return { text: entry?.text ?? null, missing: !entry?.text };
};
const su = computed(() => mccText("SU"));
const sp = computed(() => mccText("SP"));
const en = computed(() => mccText("EN"));

const noSubtitleAtAll = (line: CeLine) => !Object.values(line.subtitles).some((s) => s?.text);

const unsaved = computed(() => (props.baseline ? subtitleDirty(props.draft, props.baseline) : false));
/** The shown subtitle is the proposal made when the recording was chosen, and is not saved yet. */
const isProposal = computed(
  () =>
    unsaved.value &&
    props.proposedRef !== null &&
    props.draft.subtitleSource === "ce_locres" &&
    props.draft.subtitleRef === props.proposedRef,
);
/** The chosen replacement recording has no LATAM subtitle: the subtitle has to be chosen by hand. */
const chosenWithoutLatam = computed(() => {
  if (props.draft.audioSource !== "ce" || !props.draft.audioRef) return false;
  const line = props.lines.find((l) => l.ce_line_ref === props.draft.audioRef);
  return Boolean(line) && !line?.subtitles[LATAM_CULTURE]?.text;
});

/**
 * Choosing "Write my own" with an empty text box starts it from a text to adapt: the chosen Campaign
 * Evolved recording's LATAM subtitle, or MCC's LATAM text (SU) when no recording is chosen. Text the user
 * already wrote is never replaced.
 */
watch(
  () => props.draft.subtitleSource,
  (source) => {
    if (source !== "custom" || props.locked || props.draft.customText.trim()) return;
    const d = props.draft;
    const chosen = d.audioSource === "ce" && d.audioRef ? props.lines.find((l) => l.ce_line_ref === d.audioRef) : undefined;
    const start = chosen ? chosen.subtitles[LATAM_CULTURE]?.text : su.value.text;
    if (start) d.customText = start;
  },
);

/** The text the game will show, as chosen now (saved or not). */
const preview = computed<{ text: string | null; note: string }>(() => {
  const d = props.draft;
  switch (d.subtitleSource) {
    case "keep_original":
      return { text: su.value.text, note: su.value.missing ? "MCC has no LATAM text for this line." : "MCC's LATAM text (unchanged)" };
    case "ce_locres": {
      const line = props.lines.find((l) => l.ce_line_ref === d.subtitleRef);
      const text = line?.subtitles[d.subtitleCulture]?.text ?? null;
      return { text, note: d.subtitleRef ? `Campaign Evolved ${d.subtitleCulture} · ${d.subtitleRef}` : "Choose a Campaign Evolved subtitle." };
    }
    case "custom":
      return { text: d.customText.trim() || null, note: "Your own LATAM Spanish text" };
    default:
      return { text: null, note: "No subtitle: shown without text (a decision, not a missing value)." };
  }
});
</script>

<template>
  <section class="block" aria-label="Subtitles" data-section="subtitles">
    <h3><Captions :size="15" aria-hidden="true" /> Subtitles</h3>
    <p v-if="locked && !readOnly" class="note">Approved. Mark it Needs rework to change the subtitle.</p>

    <dl class="texts">
      <dt>MCC LATAM (SU)</dt>
      <dd>
        <span v-if="su.missing" class="missing">MCC has no LATAM text for this line.</span>
        <span v-else>{{ su.text }}</span>
      </dd>
      <dt>MCC Spain (SP)</dt>
      <dd>
        <span v-if="sp.missing" class="missing">No Spain text.</span>
        <span v-else>{{ sp.text }}</span>
      </dd>
      <dt>English (MCC)</dt>
      <dd>
        <span v-if="en.missing" class="missing">No English text.</span>
        <span v-else>{{ en.text }}</span>
      </dd>
    </dl>

    <fieldset :disabled="locked" class="choice">
      <label v-for="s in SOURCES" :key="s.value" class="opt">
        <input v-model="draft.subtitleSource" type="radio" :value="s.value" />
        {{ s.label }}
      </label>
    </fieldset>

    <p v-if="chosenWithoutLatam && !locked" class="note small" data-testid="subtitle-manual-needed">
      The chosen recording has no LATAM Spanish subtitle. Choose the subtitle manually.
    </p>

    <div v-if="draft.subtitleSource === 'ce_locres'" class="ce-subtitle">
      <label class="inline">Language
        <select v-model="draft.subtitleCulture" :disabled="locked">
          <option v-for="c in CULTURES" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <ul v-if="lines.length">
        <li v-for="line in lines" :key="line.ce_line_ref">
          <label class="opt">
            <input v-model="draft.subtitleRef" type="radio" name="subtitle-ref" :value="line.ce_line_ref"
                   :disabled="locked || !line.subtitles[draft.subtitleCulture]?.text" />
            <span class="mono small">{{ line.ce_line_ref }}</span>
            <span class="small">
              {{ line.subtitles[draft.subtitleCulture]?.text ?? (noSubtitleAtAll(line) ? "no source subtitle for this recording" : `no ${draft.subtitleCulture} subtitle`) }}
            </span>
          </label>
        </li>
      </ul>
      <p v-else-if="!readOnly" class="small muted">Use a recording from the right-hand list; its subtitle can then be chosen here.</p>
    </div>

    <div v-if="draft.subtitleSource === 'custom'" class="custom-subtitle">
      <label class="block-label">Subtitle text (LATAM Spanish)
        <textarea v-model="draft.customText" rows="3" :disabled="locked" placeholder="Write the subtitle the game should show"></textarea>
      </label>
      <p class="small muted">{{ draft.customText.length }} characters</p>
    </div>

    <figure class="subtitle-preview" data-testid="subtitle-preview">
      <figcaption class="small">
        <span>Subtitle preview</span>
        <StatusBadge v-if="isProposal" label="proposed from the chosen recording · unsaved" tone="info" />
        <StatusBadge v-else-if="unsaved" label="unsaved" tone="warn" />
        <Sparkles v-if="isProposal" :size="13" class="muted" aria-hidden="true" />
      </figcaption>
      <p v-if="preview.text" class="subtitle-text" data-testid="subtitle-preview-text">{{ preview.text }}</p>
      <p v-else class="subtitle-text missing">(no text)</p>
      <p class="small muted">{{ preview.note }}</p>
    </figure>

    <slot />
  </section>
</template>
