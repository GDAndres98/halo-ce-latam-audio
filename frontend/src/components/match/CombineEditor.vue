<script setup lang="ts">
// Editing two recordings in one replacement (docs/combine-recordings.md).
//   Join (ce_concat): each recording keeps its own edits on its own waveform (the usual editor, without the effects),
//   and the gap between them is set here: positive = silence, negative = the second starts before the first ends
//   and both play during the overlap.
//   Play together (ce_mix): both play unedited; the second can start later (or earlier, negative).
// The radio filter and the echo apply to the combined result. Both recordings keep their own level: there is no
// volume control (where they add up past the peak ceiling the result is lowered just enough, and that is reported).
// The result is rendered as the build renders it and heard as B under "Listen and compare".

import { Combine } from "lucide-vue-next";
import { computed, reactive } from "vue";
import type { AudioEdit, EchoPreset, RadioPreset } from "../../api/types";
import AudioButton from "../AudioButton.vue";
import { setEchoPreset, setRadioPreset } from "../../matching/editRecipe";
import type { Draft } from "../../matching/draft";
import AudioEditor from "./AudioEditor.vue";

const props = defineProps<{
  draft: Draft;
  locked: boolean;
  slotId: string;
  originalUrl?: string | null;
  previewUrl?: string | null;
  stats?: Record<string, number | unknown> | null;
  rendering?: boolean;
  errors?: string[];
}>();

const join = computed(() => props.draft.audioSource === "ce_concat");
const combine = computed(() => props.draft.combine);

/** A draft-shaped view of one part, so the usual editor edits `combine.parts[i]` and nothing else. */
function partDraft(i: 0 | 1): Draft {
  return reactive({
    get audioSource() { return "ce" as const; },
    get audioRef() { return i === 0 ? props.draft.audioRef : props.draft.audioRefB; },
    get audioLanguage() { return props.draft.audioLanguage; },
    get radio() { return false; },
    get edit() { return (props.draft.combine?.parts?.[i] ?? null) as AudioEdit; },
    set edit(v: AudioEdit) {
      const c = props.draft.combine;
      if (c?.parts) c.parts = (i === 0 ? [v, c.parts[1]] : [c.parts[0], v]) as [AudioEdit, AudioEdit];
    },
  }) as unknown as Draft;
}
const parts = [partDraft(0), partDraft(1)];

function setNumber(key: "gap_s" | "offset_s", event: Event, lo: number, hi: number) {
  const c = props.draft.combine;
  const v = Number((event.target as HTMLInputElement).value);
  if (!c || !Number.isFinite(v)) return;
  c[key] = Math.round(Math.min(hi, Math.max(lo, v)) * 1000) / 1000;
}

function onRadio(event: Event) {
  const c = props.draft.combine;
  const value = (event.target as HTMLSelectElement).value;
  if (!c) return;
  const next = setRadioPreset({ radio: c.radio ?? null } as AudioEdit, value === "off" ? null : (value as RadioPreset));
  c.radio = next.radio ?? null;
}
function onEcho(event: Event) {
  const c = props.draft.combine;
  const value = (event.target as HTMLSelectElement).value;
  if (!c) return;
  const next = setEchoPreset({ echo: c.echo ?? null } as AudioEdit, value === "off" ? null : (value as EchoPreset));
  c.echo = next.echo ?? null;
}

const num = (k: string) => (typeof props.stats?.[k] === "number" ? (props.stats[k] as number) : null);
const warnings = computed(() => ((props.stats?.warnings as unknown) as string[] | undefined) ?? []);
</script>

<template>
  <section v-if="combine" class="block combine-editor" aria-label="Two recordings" data-section="editor" data-testid="combine-editor">
    <header class="block-head">
      <h3><Combine :size="15" aria-hidden="true" /> {{ join ? "Join two recordings" : "Play two recordings at the same time" }}</h3>
      <span class="small muted">A recipe, like any edit: the original recordings are never changed.</span>
    </header>

    <template v-if="join">
      <AudioEditor :key="`p0-${draft.audioRef}`" :draft="parts[0]" :locked="locked" part-only title="Part 1" :slot-id="slotId"
                   :original-url="originalUrl" :preview-url="previewUrl" />
      <label class="inline gap" data-testid="combine-gap">
        Gap between the parts (s)
        <input :value="combine.gap_s ?? 0" type="number" min="-5" max="5" step="0.05" :disabled="locked"
               aria-label="Gap between the parts (seconds)" @change="setNumber('gap_s', $event, -5, 5)" />
        <span class="small muted">0 = right after; positive = silence; negative = part 2 starts before part 1 ends (both play).</span>
      </label>
      <AudioEditor :key="`p1-${draft.audioRefB}`" :draft="parts[1]" :locked="locked" part-only title="Part 2" :slot-id="slotId"
                   :original-url="originalUrl" :preview-url="previewUrl" />
    </template>
    <label v-else class="inline gap" data-testid="combine-offset">
      The second recording starts (s)
      <input :value="combine.offset_s ?? 0" type="number" min="-10" max="10" step="0.05" :disabled="locked"
             aria-label="Start offset of the second recording (seconds)" @change="setNumber('offset_s', $event, -10, 10)" />
      <span class="small muted">after the first; 0 = together; negative = the first starts later. Both play unedited.</span>
    </label>

    <fieldset class="effects" :disabled="locked">
      <legend class="small">On the combined result</legend>
      <label class="inline">Radio filter
        <select :value="combine.radio?.preset ?? 'off'" aria-label="Radio filter on the combined result" data-testid="combine-radio" @change="onRadio">
          <option value="off">Off</option>
          <option value="spain">Spain radio</option>
          <option value="english">English radio</option>
          <option value="spain_eco">Spain intercom (eco)</option>
          <option value="english_eco">English intercom (eco)</option>
          <option value="soldier">Soldier radio</option>
          <option value="pilot">Pilot radio</option>
        </select>
      </label>
      <label class="inline">Echo
        <select :value="combine.echo?.preset ?? 'off'" aria-label="Echo on the combined result" @change="onEcho">
          <option value="off">Off</option>
          <option value="spain">Spain echo</option>
          <option value="english">English echo</option>
        </select>
      </label>
    </fieldset>

    <p class="small" data-testid="combine-result">
      <template v-if="rendering">Rendering the result…</template>
      <template v-else-if="errors?.length"><span class="error">{{ errors.join("; ") }}</span></template>
      <template v-else-if="num('output_s') !== null">
        Result: {{ num("output_s")?.toFixed(2) }} s<template v-if="num('overlap_s')"> · {{ num("overlap_s")?.toFixed(2) }} s overlap</template>.
        <AudioButton v-if="previewUrl" :url="previewUrl" label="Result" title="The combined result, as the build renders it" />
        <span v-for="(w, k) in warnings" :key="k" class="warn"> {{ w }}</span>
      </template>
    </p>
  </section>
</template>

<style scoped>
.combine-editor {
  display: grid;
  gap: 0.5rem;
}
.gap {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}
.gap input {
  width: 6rem;
}
.effects {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  border: 1px solid var(--line, rgba(127, 127, 127, 0.25));
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
}
</style>
