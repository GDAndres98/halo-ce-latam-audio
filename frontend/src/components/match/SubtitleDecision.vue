<script setup lang="ts">
// Subtitle choice for one MCC line: the LATAM text that the build will write (SU), with the other texts
// shown for comparison. Independent of the audio decision: no audio match is needed to choose a subtitle.
//
// "Missing" (MCC has no text for this line) and "omitted" (the user chose no subtitle) are shown
// differently on purpose: a missing text is a problem to look at, an omitted one is a decision.

import { computed } from "vue";
import type { CeLine, SlotDetail, SubtitleSource } from "../../api/types";
import type { Draft } from "../../matching/draft";

const props = defineProps<{ draft: Draft; locked: boolean; detail: SlotDetail }>();

const SOURCES: { value: SubtitleSource; label: string }[] = [
  { value: "keep_original", label: "Keep MCC's LATAM text (SU)" },
  { value: "ce_locres", label: "Use a Campaign Evolved subtitle" },
  { value: "custom", label: "Write my own LATAM Spanish text" },
  { value: "none", label: "No subtitle (intentionally omitted)" },
];

const CULTURES = ["es-MX", "en", "es-ES"];

const mccText = (key: string): { text: string | null; missing: boolean } => {
  const entry = props.detail.mcc_subtitles[key];
  return { text: entry?.text ?? null, missing: !entry?.text };
};
const su = computed(() => mccText("SU"));
const sp = computed(() => mccText("SP"));
const en = computed(() => mccText("EN"));

/** Campaign Evolved lines matched to this MCC line that have a subtitle in the chosen language. */
const ceOptions = computed<{ line: CeLine; ref: string }[]>(() =>
  props.detail.matched_lines
    .filter((line) => Boolean(line.subtitles[props.draft.subtitleCulture]?.text))
    .map((line) => ({ line, ref: line.ce_line_ref })),
);

const noSubtitleAtAll = (line: CeLine) => !Object.values(line.subtitles).some((s) => s?.text);
</script>

<template>
  <section class="block">
    <h3>Subtitle</h3>
    <p v-if="locked" class="note">Approved. Mark it Needs rework to change the subtitle.</p>

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

    <div v-if="draft.subtitleSource === 'ce_locres'" class="ce-subtitle">
      <label class="inline">Language
        <select v-model="draft.subtitleCulture" :disabled="locked">
          <option v-for="c in CULTURES" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <ul v-if="detail.matched_lines.length">
        <li v-for="line in detail.matched_lines" :key="line.ce_line_ref">
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
      <p v-else class="small muted">Match a recording first; its subtitle can then be used.</p>
    </div>

    <div v-if="draft.subtitleSource === 'custom'" class="custom-subtitle">
      <label class="block-label">Subtitle text (LATAM Spanish)
        <textarea v-model="draft.customText" rows="3" :disabled="locked" placeholder="Write the subtitle the game should show"></textarea>
      </label>
      <p class="small muted">{{ draft.customText.length }} characters</p>
    </div>

    <p v-if="draft.subtitleSource === 'none'" class="small muted">
      The line is shown without subtitles. This is a decision, not a missing value.
    </p>
  </section>
</template>
