<script lang="ts">
import { reactive } from "vue";
// The last result per sound, kept outside the component: switching reloads the line, which rebuilds this panel.
const lastNotes = reactive(new Map<string, string>());
</script>

<script setup lang="ts">
// The line's 4th audio option: "Replace every take of this sound" (own take set, docs/custom-take-set-design.md).
// Lists every Spain take of the sound that would be replaced, each playable with its current decision, and lets the
// owner tick several Campaign Evolved recordings to play instead. Applying is the owner's explicit, confirmed action:
// it clears the sound's line decisions (approved ones are marked Needs rework first, by the server) and adds the ticked
// recordings as draft takes, in one request. The takes are then approved one by one under "Takes of this sound".
// A sound with a SU/SP subtitle entry (owner, 2026-10-19) has ONE subtitle per set: its line subtitle decisions are
// cleared too, so the set's subtitle can be chosen here (saved as a draft with the set) or later under "Takes of this
// sound" (SetSubtitle.vue), where it is approved.

import { Undo2 } from "lucide-vue-next";
import { computed, ref } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import type { SetSubtitleChoice, SoundTakes, TakeResponse } from "../../api/types";
import { confirmAction } from "../../composables/useConfirm";
import AudioButton from "../AudioButton.vue";
import StatusBadge from "../StatusBadge.vue";
import TakePicker from "./TakePicker.vue";

const props = defineProps<{
  sound: SoundTakes;
  /** The line open in the panel (marked "this line"). */
  slotId: string;
  focusedRef: string | null;
  canListen?: boolean;
  readOnly?: boolean;
}>();
const emit = defineEmits<{ changed: [sound: SoundTakes] }>();
const picker = ref<InstanceType<typeof TakePicker> | null>(null);

const LANGUAGE = "Spanish(Mexico)";
const busy = ref(false);
const error = ref("");
const note = computed({
  get: () => lastNotes.get(props.sound.mcc_tag) ?? "",
  set: (v: string) => void lastNotes.set(props.sound.mcc_tag, v),
});
const ticked = ref<string[]>([]);
/** Subtitled sounds: the set's one subtitle, chosen with the replacement (a draft) or later. */
const subSource = ref<"later" | "keep_original" | "none" | "custom">("later");
const subText = ref(props.sound.mcc_text?.SU ?? "");
const subChoice = computed<SetSubtitleChoice | undefined>(() => {
  if (!props.sound.has_subtitle_entry || subSource.value === "later") return undefined;
  if (subSource.value === "custom") return subText.value.trim() ? { source: "custom", custom_text: subText.value.trim() } : undefined;
  return { source: subSource.value };
});
const SUB_WORD = { later: "decide later", keep_original: "keep MCC's text", none: "no subtitle", custom: "my own text" } as const;

const on = computed(() => Boolean(props.sound.own_set));
const word = (status: string) => (status === "needs_rework" ? "needs rework" : status);
const refOf = (t: SoundTakes["added_takes"][number]) => t.audio.sources[0]?.ce_line_ref ?? "";
const takenRefs = computed(() => props.sound.added_takes.map(refOf));
const pickerQuery = computed(() => (props.focusedRef ? props.focusedRef.replace(/#\d+$/, "") : ""));
const decided = computed(() => props.sound.spain_takes.filter((t) => t.mapping_id));
const approvedTakes = computed(() => props.sound.added_takes.filter((t) => t.audio.status === "approved").length);
/** Lines that already select Campaign Evolved audio: converting them keeps that work (ReplacementSet.vue). */
const selected = computed(() => decided.value.filter((t) => t.decision?.audio_source === "ce").length);
/** How many takes the sound would play after applying (its added takes, plus the ticked recordings). */
const resulting = computed(() => props.sound.added_takes.length + ticked.value.length);

function decisionText(t: SoundTakes["spain_takes"][number]) {
  const d = t.decision;
  if (!d) return "no decision (plays Spain's recording)";
  const audio = d.audio_source === "mute" ? "muted" : d.audio_source === "ce" ? (t.audio_ref ?? "Campaign Evolved") : "Spain's recording";
  return `${audio} · audio ${word(d.audio)} · subtitle ${word(d.subtitle)}`;
}

async function run(label: (r: TakeResponse) => string, op: () => Promise<TakeResponse>) {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    const r = await op();
    note.value = r.saved ? label(r) : (r.message ?? "Nothing changed.");
    if (r.saved) picker.value?.clear();
    emit("changed", r.sound);
    return r;
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.message}${e.status === 409 ? " Reload the line to see the current state." : ""}` : String(e);
    return null;
  } finally {
    busy.value = false;
  }
}

async function apply(refs: string[]) {
  const s = props.sound;
  const n = s.added_takes.length + refs.length;
  if (!n) return;
  const lines = decided.value.map((t) => `  • ${t.slot_id}: ${decisionText(t)}`);
  const approved = decided.value.filter((t) => t.decision && (t.decision.audio === "approved" || t.decision.subtitle === "approved"));
  const ok = await confirmAction({
    title: "Replace every take of this sound",
    message:
      `${s.tag_name} will play ${n} Campaign Evolved take(s) instead of Spain's ${s.spain_takes.length}` +
      (s.added_takes.length ? ` (${refs.length} new, ${s.added_takes.length} already added)` : "") +
      ". New takes are drafts: approve them under \"Takes of this sound\"; the build removes Spain's takes once one is approved." +
      (lines.length
        ? `\n\nThese line decisions will be cleared (kept in the set's record; "Undo the replacement set" under ` +
          `"Takes of this sound" brings them back as Needs rework):\n${lines.join("\n")}` +
          (approved.length ? `\n\n${approved.length} of them are approved: they are marked Needs rework first, then removed, in one save.` : "") +
          (selected.value ? `\n\n${selected.value} of them already select Campaign Evolved audio: "Preview a replacement set from my ` +
            `selections" under "Takes of this sound" keeps that work instead.` : "")
        : "") +
      (s.has_subtitle_entry ? `\n\nSubtitle of this sound (one for every take): ${SUB_WORD[subSource.value]}` +
        (subSource.value === "later" ? "; until it is approved the build keeps MCC's text." : " (saved as a draft; approve it under \"Takes of this sound\").") : ""),
    confirmLabel: lines.length ? `Clear ${lines.length} and replace` : "Replace",
    tone: lines.length ? "warning" : "default",
  });
  if (!ok) return;
  const r = await run(
    (x) => `Every take replaced: ${x.added?.length ?? 0} recording(s) added as drafts` +
      (x.cleared?.length ? `, ${x.cleared.length} line decision(s) cleared` : "") + ".",
    () => api.ownSetOn({
      mcc_tag: s.mcc_tag, loaded_takes_sha256: s.version, loaded_sound_sha256: s.sound_version,
      clear_mapping_ids: decided.value.map((t) => t.mapping_id as string),
      audio_list: refs.map((ce_line_ref) => ({ ce_line_ref, language: LANGUAGE })),
      ...(subChoice.value ? { subtitle: subChoice.value } : {}),
    }),
  );
  if (r?.saved) ticked.value = [];
}

async function addMore(refs: string[]) {
  const s = props.sound;
  const r = await run(
    (x) => `Added ${x.added?.length ?? 0} take(s) as drafts.${x.skipped?.length ? ` Skipped ${x.skipped.length}: already a take.` : ""}`,
    () => api.takeAddMany({ mcc_tag: s.mcc_tag, loaded_takes_sha256: s.version,
                            audio_list: refs.map((ce_line_ref) => ({ ce_line_ref, language: LANGUAGE })) }),
  );
  if (r?.saved) ticked.value = [];
}

async function turnOff() {
  const s = props.sound;
  const ok = await confirmAction({
    title: "Back to Spain's takes",
    message: `${s.tag_name} will play Spain's ${s.spain_takes.length} take(s) plus its added takes again. ` +
      "Its lines start undecided. To bring back the recorded line decisions instead, use \"Undo the replacement set\" " +
      "under \"Takes of this sound\".",
    confirmLabel: "Back to Spain's takes",
  });
  if (ok) await run(() => "Back to Spain's takes.", () => api.ownSetOff({ mcc_tag: s.mcc_tag, loaded_takes_sha256: s.version }));
}
</script>

<template>
  <div class="whole-sound" data-testid="whole-sound">
    <p class="small muted">
      <template v-if="!on">
        Replaces every take of <span class="mono">{{ sound.tag_name }}</span> at once: the game then plays only the
        Campaign Evolved recordings you choose below, picked at random each time.
        <strong v-if="selected" data-testid="whole-sound-has-selections">
          {{ selected }} take(s) already select Campaign Evolved audio: to keep that work, use "Preview a replacement set
          from my selections" under "Takes of this sound" instead.
        </strong>
      </template>
      <template v-else>
        <span class="mono">{{ sound.tag_name }}</span> plays its own {{ sound.added_takes.length }} take(s).
        <template v-if="approvedTakes">The build removes Spain's takes.</template>
        <strong v-else>No take is approved yet: approve them under "Takes of this sound" (until then the build keeps Spain's takes).</strong>
      </template>
    </p>

    <h4 class="small">{{ on ? "Spain takes replaced" : "Spain takes that would be replaced" }} ({{ sound.spain_takes.length }})</h4>
    <ul class="replaced" data-testid="whole-sound-replaced">
      <li v-for="t in sound.spain_takes" :key="t.slot_id" :class="{ here: t.slot_id === slotId }">
        <AudioButton v-if="canListen !== false" :url="audioUrl.mcc(sound.level, 'spanish', t.spanish_index)" label="ES"
                     title="Listen to Spain's recording" />
        <span class="take-main">
          <span class="mono small">{{ t.slot_id }}</span>
          <span class="small muted">{{ t.duration_s.toFixed(2) }} s · <template v-if="on">replaced</template><template v-else>{{ decisionText(t) }}</template></span>
        </span>
        <StatusBadge v-if="t.slot_id === slotId" label="this line" tone="ok" />
        <StatusBadge v-if="!on && t.mapping_id" label="decision cleared" tone="warn" />
      </li>
    </ul>

    <template v-if="sound.added_takes.length">
      <h4 class="small">{{ on ? "Takes it plays" : "Already added (kept as takes)" }} ({{ sound.added_takes.length }})</h4>
      <ul class="replaced" data-testid="whole-sound-takes">
        <li v-for="t in sound.added_takes" :key="t.take_id">
          <AudioButton v-if="canListen !== false && refOf(t)" :url="audioUrl.ce(refOf(t), LANGUAGE)" label="es-MX" title="Listen" />
          <span class="take-main"><span class="mono small">{{ refOf(t) }}</span><span class="small muted">{{ t.take_id }}</span></span>
          <StatusBadge :label="word(t.audio.status)" :tone="t.audio.status === 'approved' ? 'ok' : t.audio.status === 'needs_rework' ? 'bad' : 'warn'" />
        </li>
      </ul>
    </template>

    <fieldset v-if="sound.has_subtitle_entry && !on && !readOnly" class="choice small" data-testid="whole-sound-subtitle">
      <legend>Subtitle of this sound (one for every take; its line subtitle decisions are cleared too)</legend>
      <label v-for="(w, k) in SUB_WORD" :key="k" class="opt">
        <input v-model="subSource" type="radio" :value="k" :data-testid="`whole-sound-subtitle-${k}`" /> {{ w }}
      </label>
      <textarea v-if="subSource === 'custom'" v-model="subText" rows="2" data-testid="whole-sound-subtitle-text"></textarea>
      <span class="muted">MCC LATAM (SU): {{ sound.mcc_text?.SU ? `“${sound.mcc_text.SU}”` : "an empty entry (no text shown today)" }}. A Campaign Evolved subtitle can be chosen after, under “Takes of this sound”.</span>
    </fieldset>
    <p v-else-if="sound.has_subtitle_entry && on" class="small" data-testid="whole-sound-subtitle-on">
      Subtitle of this sound: {{ sound.set_subtitle?.decision?.status?.replace("_", " ") ?? "undecided" }}
      (choose and approve it under “Takes of this sound”).
    </p>

    <template v-if="!readOnly">
      <h4 class="small">{{ on ? "Add more recordings" : "Recordings to play instead" }}</h4>
      <TakePicker
        ref="picker"
        :taken-refs="takenRefs" :initial-query="pickerQuery" :can-listen="canListen" :busy="busy"
        :submit-label="(n) => on ? `Add ${n} take${n === 1 ? '' : 's'}` : `Replace all ${sound.spain_takes.length} Spain take(s) with ${n + sound.added_takes.length}`"
        @change="(r) => (ticked = r)" @submit="on ? addMore($event) : apply($event)"
      />
      <p v-if="!on && !resulting" class="small muted">Tick at least one recording.</p>
      <div v-if="!on && sound.added_takes.length && !ticked.length" class="row">
        <button type="button" class="icon-label" :disabled="busy" data-testid="whole-sound-apply-added" @click="apply([])">
          Replace all {{ sound.spain_takes.length }} Spain take(s) with the {{ sound.added_takes.length }} added
        </button>
      </div>
      <div v-if="on" class="row">
        <button type="button" class="icon-label" :disabled="busy" data-testid="own-set-off" @click="turnOff">
          <Undo2 :size="15" aria-hidden="true" /> Back to Spain's takes
        </button>
      </div>
    </template>
    <p v-if="error" class="small error" role="alert">{{ error }}</p>
    <p v-else-if="note" class="small ok" role="status">{{ note }}</p>
  </div>
</template>

<style scoped>
.whole-sound {
  display: grid;
  gap: 0.4rem;
  margin-top: 0.5rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--frame, rgba(127, 127, 127, 0.4));
  border-radius: 6px;
}
h4 {
  margin: 0.3rem 0 0;
}
.replaced {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.25rem;
}
.replaced li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.4rem;
  border: 1px solid var(--line, rgba(127, 127, 127, 0.25));
  border-radius: 6px;
}
.replaced li.here {
  border-color: var(--frame, currentColor);
}
.take-main {
  display: grid;
  flex: 1 1 12rem;
  min-width: 0;
}
.take-main .mono {
  overflow-wrap: anywhere;
}
</style>
