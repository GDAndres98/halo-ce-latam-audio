<script setup lang="ts">
// Takes of this sound (docs/added-takes-design.md): the sound's Spain takes (each one is an MCC line, decided on
// its own) and its added takes, extra Campaign Evolved recordings the game picks among (in game: v-000020/21).
// Each added take is its own decision: approve, Needs rework, reorder, remove. Saving happens right away, through
// /api/takes/*; every request names the sound's version it was made from, so a change on another computer is
// refused instead of overwritten. The page never adds or approves a take on its own.
// Two ways to add: "Add as extra take" adds the recording focused on the right; "Add several takes" opens a picker
// where the user ticks any number of recordings and adds them in one save (/api/takes/add_many). Nothing is
// pre-ticked: the search only fills the list.
// Own take set (docs/custom-take-set-design.md): turned on and off from the line's audio choices ("Replace every
// take of this sound", WholeSoundReplace.vue). Here it only changes how the list reads: Spain's takes show removed.
// Replacement set from the owner's selections (docs/replacement-set-conversion.md): ReplacementSet.vue, at the end.
// The header says which way the sound is handled and sums it up ("3 original MCC takes -> 2 replacement takes").
// Sounds with a SU/SP subtitle entry (owner, 2026-10-19): allowed too. Every take shows the same text: without an own
// set the line subtitle decisions decide it (a warning says so); with one, "Subtitle of this sound" (SetSubtitle.vue).

import { ArrowDown, ArrowUp, Layers, ListPlus, Plus, Trash2 } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import type { AddedTake, SoundTakes } from "../../api/types";
import { confirmAction } from "../../composables/useConfirm";
import AudioButton from "../AudioButton.vue";
import StatusBadge from "../StatusBadge.vue";
import ReplacementSet from "./ReplacementSet.vue";
import SetSubtitle from "./SetSubtitle.vue";
import TakePicker from "./TakePicker.vue";

const props = defineProps<{
  sound: SoundTakes | null;
  /** The recording focused in the Campaign Evolved column (what "Add" adds). */
  focusedRef: string | null;
  readOnly?: boolean;
  /** Whether recordings can be played here (the public view may not allow it). */
  canListen?: boolean;
  /** The line open in the panel: its Spain take is marked "this line". */
  slotId?: string | null;
}>();
const emit = defineEmits<{ changed: [sound: SoundTakes] }>();

const current = ref<SoundTakes | null>(props.sound);
watch(() => props.sound, (s) => (current.value = s));
const busy = ref(false);
const error = ref("");
const note = ref("");
const LANGUAGE = "Spanish(Mexico)";

const tone = (status: string) => (status === "approved" ? "ok" : status === "needs_rework" ? "bad" : "warn");
const word = (status: string) => (status === "needs_rework" ? "needs rework" : status);
const refOf = (t: AddedTake) => t.audio.sources[0]?.ce_line_ref ?? "";
const langOf = (t: AddedTake) => t.audio.sources[0]?.language ?? LANGUAGE;
const canAdd = computed(() => Boolean(current.value?.allowed && props.focusedRef && !busy.value && !props.readOnly));
const alreadyAdded = computed(() => current.value?.added_takes.some((t) => refOf(t) === props.focusedRef) ?? false);

type TakeResult = {
  sound: SoundTakes; saved: boolean; message?: string; added?: string[]; skipped?: string[]; cleared?: string[];
};
async function run(label: string | ((r: TakeResult) => string), op: () => Promise<TakeResult>) {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    const r = await op();
    current.value = r.sound;
    emit("changed", r.sound);
    note.value = r.saved ? (typeof label === "function" ? label(r) : label) : (r.message ?? "Nothing changed.");
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.message}${e.status === 409 ? " Reload the line to see the current takes." : ""}` : String(e);
  } finally {
    busy.value = false;
  }
}

function add() {
  const s = current.value;
  if (!s || !props.focusedRef) return;
  const ref_ = props.focusedRef;
  return run(`Added ${ref_} as a take (draft).`, () =>
    api.takeSave({ mcc_tag: s.mcc_tag, loaded_takes_sha256: s.version, audio: { ce_line_ref: ref_, language: LANGUAGE } }));
}

function replaceWithFocused(t: AddedTake) {
  const s = current.value;
  if (!s || !props.focusedRef) return;
  const ref_ = props.focusedRef;
  return run(`Take ${t.take_id} now uses ${ref_}.`, () =>
    api.takeSave({ mcc_tag: s.mcc_tag, take_id: t.take_id, loaded_takes_sha256: s.version,
                   audio: { ce_line_ref: ref_, language: langOf(t) } }));
}

async function approve(t: AddedTake) {
  const s = current.value;
  if (!s) return;
  const ok = await confirmAction({
    title: "Approve the added take",
    message: `Approve ${t.take_id} (${refOf(t)}) as an extra take of ${s.tag_name}?\n\nApproved takes are read-only. ` +
      "To change one later, mark it Needs rework first.",
    confirmLabel: "Yes, approve",
  });
  if (ok) {
    await run(`Approved ${t.take_id}.`, () =>
      api.takeSave({ mcc_tag: s.mcc_tag, take_id: t.take_id, loaded_takes_sha256: s.version,
                     actions: [{ action: "approve", field: "audio" }] }));
  }
}

async function rework(t: AddedTake) {
  const s = current.value;
  if (!s) return;
  const ok = await confirmAction({
    title: "Needs rework",
    message: `Mark ${t.take_id} Needs rework? Its revision goes up by one; it is not inserted until approved again.`,
    confirmLabel: "Mark Needs rework",
    tone: "warning",
  });
  if (ok) {
    await run(`${t.take_id} marked Needs rework.`, () =>
      api.takeSave({ mcc_tag: s.mcc_tag, take_id: t.take_id, loaded_takes_sha256: s.version,
                     actions: [{ action: "needs_rework", field: "audio" }] }));
  }
}

function move(t: AddedTake, direction: -1 | 1) {
  const s = current.value;
  if (!s) return;
  return run("Order saved.", () =>
    api.takeMove({ mcc_tag: s.mcc_tag, take_id: t.take_id, direction, loaded_takes_sha256: s.version }));
}

async function remove(t: AddedTake) {
  const s = current.value;
  if (!s) return;
  const ok = await confirmAction({
    title: "Remove the added take",
    message: `Remove ${t.take_id} (${refOf(t)}) from ${s.tag_name}? Its ID is not reused.`,
    confirmLabel: "Remove",
    tone: "warning",
  });
  if (ok) {
    await run(`Removed ${t.take_id}.`, () =>
      api.takeRemove({ mcc_tag: s.mcc_tag, take_id: t.take_id, loaded_takes_sha256: s.version }));
  }
}

// ---- Add several takes: the shared picker; the ticked recordings are added in one save.
const picking = ref(false);
const takenRefs = computed(() => (current.value?.added_takes ?? []).map(refOf));
const pickerQuery = computed(() => (props.focusedRef ? props.focusedRef.replace(/#\d+$/, "") : ""));

async function addPicked(refs: string[]) {
  const s = current.value;
  if (!s || !refs.length) return;
  const plural = (n: number) => `${n} take${n === 1 ? "" : "s"}`;
  await run(
    (r) => `Added ${plural(r.added?.length ?? 0)} as drafts.${r.skipped?.length ? ` Skipped ${r.skipped.length}: already a take.` : ""}`,
    () => api.takeAddMany({
      mcc_tag: s.mcc_tag,
      loaded_takes_sha256: s.version,
      audio_list: refs.map((ce_line_ref) => ({ ce_line_ref, language: LANGUAGE })),
    }),
  );
  if (!error.value) picking.value = false;
}

// ---- How the sound is handled
const MODE_LABEL: Record<string, string> = {
  per_take: "per take", spain_plus_added: "Spain + added takes", replacement_set: "replacement set",
  replacement_set_staged: "replacement set staged",
};
const modeLabel = computed(() => MODE_LABEL[current.value?.mode ?? "per_take"] ?? "per take");
const summary = computed(() => {
  const s = current.value;
  if (!s) return "";
  const spain = s.spain_takes.length;
  const n = s.added_takes.length;
  const plural = (k: number, w: string) => `${k} ${w}${k === 1 ? "" : "s"}`;
  if (s.mode === "replacement_set") return `${plural(spain, "original MCC take")} → ${plural(n, "replacement take")}`;
  if (s.mode === "replacement_set_staged")
    return `${plural(spain, "original MCC take")} → ${plural(n, "replacement take")} once switched (staged; Spain's takes and their decisions still apply)`;
  if (s.mode === "spain_plus_added") return `${plural(spain, "original MCC take")} + ${plural(n, "added take")}`;
  return `${plural(spain, "original MCC take")}, each decided on its own`;
});

// ---- Own take set
const own = computed(() => Boolean(current.value?.own_set));
const ownApproved = computed(() => current.value?.added_takes.some((t) => t.audio.status === "approved") ?? false);
const shownTotal = computed(() => (own.value ? current.value?.added_takes.length ?? 0 : current.value?.total_takes ?? 0));

function spainUses(take: SoundTakes["spain_takes"][number]) {
  const d = take.decision;
  if (!d || d.audio_source === "keep_original" || !d.audio_source) return "Spain's recording";
  if (d.audio_source === "mute") return "muted";
  return take.audio_ref ? `${take.audio_ref} (${word(d.audio)})` : word(d.audio);
}
</script>

<template>
  <section v-if="current" class="block added-takes" aria-label="Takes of this sound" data-section="takes" data-testid="added-takes">
    <h3>
      <Layers :size="15" aria-hidden="true" /> Takes of this sound
      <span class="count">{{ shownTotal }}</span>
      <StatusBadge v-if="own" label="own take set" tone="ok" data-testid="own-set-badge" />
      <StatusBadge v-else :label="modeLabel" :tone="current.mode === 'replacement_set_staged' ? 'warn' : 'muted'" data-testid="sound-mode" />
    </h3>
    <p class="small" data-testid="sound-summary"><strong>{{ summary }}</strong></p>
    <p v-if="!own" class="small muted">
      The game picks one of these takes at random each time <span class="mono">{{ current.tag_name }}</span> plays.
      Spain's takes are the lines of this sound; added takes are extra Campaign Evolved recordings.
    </p>
    <p v-else class="small muted" data-testid="own-set-note">
      Own take set: <span class="mono">{{ current.tag_name }}</span> plays only the takes added below.
      <template v-if="ownApproved">The build removes Spain's {{ current.spain_takes.length }} take(s).</template>
      <strong v-else>No take is approved yet, so the build still keeps Spain's takes.</strong>
    </p>

    <div v-if="current.reminders?.length" class="small reminders" data-testid="set-reminders">
      <strong>Reminders from the replaced line decisions:</strong>
      <ul>
        <li v-for="r in current.reminders" :key="r.mapping_id">
          <span class="mono">{{ r.slot_id }}</span>
          <template v-if="r.needs_recording"> · needs a new recording</template>
          <template v-if="r.radio_effect"> · needs radio effect</template>
          <template v-if="r.notes"> · “{{ r.notes }}”</template>
        </li>
      </ul>
    </div>
    <h4 class="small list-head">Original MCC takes <span class="muted">(Spain; for reference and playback)</span></h4>
    <ol class="take-list">
      <li v-for="t in current.spain_takes" :key="t.slot_id" class="take spain" :class="{ here: t.slot_id === slotId, removed: own }" :data-slot="t.slot_id">
        <span class="take-no">{{ own ? "–" : t.ordinal + 1 }}</span>
        <AudioButton v-if="canListen !== false" :url="audioUrl.mcc(current.level, 'spanish', t.spanish_index)" label="ES" title="Listen to Spain's recording" />
        <span class="mono small">{{ t.slot_id }}</span>
        <StatusBadge v-if="t.slot_id === slotId" label="this line" tone="ok" />
        <span v-if="own" class="small muted">Spain · {{ t.duration_s.toFixed(2) }} s · {{ ownApproved ? "removed" : "kept until a take is approved" }} (own take set)</span>
        <span v-else class="small muted">Spain · {{ t.duration_s.toFixed(2) }} s · plays {{ spainUses(t) }}</span>
      </li>
    </ol>
    <h4 v-if="current.added_takes.length" class="small list-head">
      {{ own || current.mode === "replacement_set_staged" ? "Replacement takes" : "Added takes" }}
      <span class="muted">(Campaign Evolved; each approved on its own)</span>
    </h4>
    <ol class="take-list">
      <li v-for="(t, i) in current.added_takes" :key="t.take_id" class="take added" :data-take="t.take_id" data-testid="added-take">
        <span class="take-no">{{ own || current.mode === "replacement_set_staged" ? i + 1 : current.spain_takes.length + i + 1 }}</span>
        <span class="take-main">
          <span class="mono small">{{ refOf(t) }}</span>
          <span class="small muted">{{ t.take_id }} · added<template v-if="t.edited"> · {{ t.edit_summary }}</template></span>
        </span>
        <AudioButton v-if="canListen !== false && refOf(t)" :url="audioUrl.ce(refOf(t), langOf(t))" label="es-MX" title="Listen to this take" />
        <StatusBadge :label="word(t.audio.status)" :tone="tone(t.audio.status)" />
        <StatusBadge v-if="t.staged" label="staged: built after the switch" tone="warn" data-testid="take-staged" />
        <StatusBadge v-if="t.drift" label="changed since approval" tone="bad" />
        <span v-if="!readOnly" class="take-actions">
          <button type="button" class="icon-only" :disabled="busy || i === 0" aria-label="Move up" title="Move up" @click="move(t, -1)">
            <ArrowUp :size="15" aria-hidden="true" />
          </button>
          <button type="button" class="icon-only" :disabled="busy || i === current.added_takes.length - 1" aria-label="Move down" title="Move down" @click="move(t, 1)">
            <ArrowDown :size="15" aria-hidden="true" />
          </button>
          <button v-if="t.audio.status !== 'approved'" type="button" class="small-button" :disabled="busy" data-testid="take-approve" @click="approve(t)">Approve</button>
          <button v-else type="button" class="small-button" :disabled="busy" data-testid="take-rework" @click="rework(t)">Needs rework</button>
          <button v-if="t.audio.status !== 'approved' && focusedRef && focusedRef !== refOf(t)" type="button" class="small-button"
                  :disabled="busy" :title="`Use ${focusedRef} for this take instead`" @click="replaceWithFocused(t)">Use selected</button>
          <button type="button" class="icon-only" :disabled="busy || t.audio.status === 'approved'"
                  :title="t.audio.status === 'approved' ? 'Approved: mark it Needs rework first' : 'Remove this take'"
                  aria-label="Remove this take" data-testid="take-remove" @click="remove(t)">
            <Trash2 :size="15" aria-hidden="true" />
          </button>
        </span>
      </li>
    </ol>

    <p v-if="current.has_subtitle_entry && current.added_takes.length && !current.set_subtitle" class="small warn"
       data-testid="takes-shared-subtitle">
      This sound has a subtitle entry: every take, added ones included, shows the same text, the one its lines'
      subtitle decisions give (takes that disagree leave MCC's text). Added takes on scripted story lines are not yet
      proven in game.
    </p>
    <SetSubtitle v-if="current.set_subtitle" :sound="current" :read-only="readOnly"
                 @changed="(s) => { current = s; emit('changed', s); }" />
    <p v-if="shownTotal > current.warn_above" class="small warn">
      {{ shownTotal }} takes: above {{ current.warn_above }}. It works, but each take adds to the bank.
    </p>
    <template v-if="!readOnly">
      <p v-if="!current.allowed" class="small muted" data-testid="takes-not-allowed">Added takes are not available here: {{ current.reason }}.</p>
      <div v-else class="row">
        <button type="button" class="icon-label" :disabled="!canAdd || alreadyAdded" data-testid="take-add" @click="add">
          <Plus :size="15" aria-hidden="true" /> Add as extra take
        </button>
        <button type="button" class="icon-label" :disabled="busy" :aria-expanded="picking" data-testid="take-add-several"
                @click="picking = !picking">
          <ListPlus :size="15" aria-hidden="true" /> Add several takes…
        </button>
        <span class="small muted">
          <template v-if="current.has_subtitle_entry && !current.added_takes.length">Every take shares this sound's one subtitle. </template>
          <template v-if="!focusedRef">Select a Campaign Evolved recording on the right first.</template>
          <template v-else-if="alreadyAdded"><span class="mono">{{ focusedRef }}</span> is already a take of this sound.</template>
          <template v-else>Adds <span class="mono">{{ focusedRef }}</span> (es-MX) as a draft.</template>
        </span>
      </div>
    </template>
    <TakePicker
      v-if="picking && !readOnly && current.allowed"
      :taken-refs="takenRefs" :initial-query="pickerQuery" :can-listen="canListen" :busy="busy" closable
      :submit-label="(n) => `Add ${n} as extra take${n === 1 ? '' : 's'}`"
      @submit="addPicked" @close="picking = false"
    />
    <p v-if="error" class="small error" role="alert">{{ error }}</p>
    <p v-else-if="note" class="small ok" role="status">{{ note }}</p>
    <ReplacementSet :sound="current" :read-only="readOnly" :can-listen="canListen"
                    @changed="(s) => { current = s; emit('changed', s); }" />
  </section>
</template>

<style scoped>
.take-list {
  list-style: none;
  margin: 0.5rem 0;
  padding: 0;
  display: grid;
  gap: 0.35rem;
}
.take {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--line, rgba(127, 127, 127, 0.25));
  border-radius: 6px;
}
.take.here {
  border-color: var(--frame, currentColor);
}
.take.removed {
  opacity: 0.55;
  text-decoration: line-through;
  text-decoration-color: rgba(127, 127, 127, 0.6);
}
.take.added {
  border-style: dashed;
}
.take-no {
  min-width: 1.6rem;
  font-weight: 600;
  text-align: center;
}
.take-main {
  display: grid;
  flex: 1 1 14rem;
  min-width: 0;
}
.take-main .mono {
  overflow-wrap: anywhere;
}
.take-actions {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-left: auto;
}
.list-head {
  margin: 0.5rem 0 0;
}
.reminders ul {
  margin: 0.2rem 0 0;
  padding-left: 1.1rem;
}
.count {
  margin-left: 0.4rem;
  font-size: 0.85em;
  opacity: 0.75;
}
</style>
