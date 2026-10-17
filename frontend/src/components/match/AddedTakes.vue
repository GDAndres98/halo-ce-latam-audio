<script setup lang="ts">
// Takes of this sound (docs/added-takes-design.md): the sound's Spain takes (each one is an MCC line, decided on
// its own) and its added takes, extra Campaign Evolved recordings the game picks among (in game: v-000020/21).
// Each added take is its own decision: approve, Needs rework, reorder, remove. Saving happens right away, through
// /api/takes/*; every request names the sound's version it was made from, so a change on another computer is
// refused instead of overwritten. The page never adds or approves a take on its own.

import { ArrowDown, ArrowUp, Layers, Plus, Trash2 } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import type { AddedTake, SoundTakes } from "../../api/types";
import { confirmAction } from "../../composables/useConfirm";
import AudioButton from "../AudioButton.vue";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{
  sound: SoundTakes | null;
  /** The recording focused in the Campaign Evolved column (what "Add" adds). */
  focusedRef: string | null;
  readOnly?: boolean;
  /** Whether recordings can be played here (the public view may not allow it). */
  canListen?: boolean;
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

async function run(label: string, op: () => Promise<{ sound: SoundTakes; saved: boolean; message?: string }>) {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    const r = await op();
    current.value = r.sound;
    emit("changed", r.sound);
    note.value = r.saved ? label : (r.message ?? "Nothing changed.");
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
      <span class="count">{{ current.total_takes }}</span>
    </h3>
    <p class="small muted">
      The game picks one of these takes at random each time <span class="mono">{{ current.tag_name }}</span> plays.
      Spain's takes are the lines of this sound; added takes are extra Campaign Evolved recordings.
    </p>

    <ol class="take-list">
      <li v-for="t in current.spain_takes" :key="t.slot_id" class="take spain" :data-slot="t.slot_id">
        <span class="take-no">{{ t.ordinal + 1 }}</span>
        <span class="mono small">{{ t.slot_id }}</span>
        <span class="small muted">Spain · {{ t.duration_s.toFixed(2) }} s · plays {{ spainUses(t) }}</span>
      </li>
      <li v-for="(t, i) in current.added_takes" :key="t.take_id" class="take added" :data-take="t.take_id" data-testid="added-take">
        <span class="take-no">{{ current.spain_takes.length + i + 1 }}</span>
        <span class="take-main">
          <span class="mono small">{{ refOf(t) }}</span>
          <span class="small muted">{{ t.take_id }} · added<template v-if="t.edited"> · {{ t.edit_summary }}</template></span>
        </span>
        <AudioButton v-if="canListen !== false && refOf(t)" :url="audioUrl.ce(refOf(t), langOf(t))" label="es-MX" title="Listen to this take" />
        <StatusBadge :label="word(t.audio.status)" :tone="tone(t.audio.status)" />
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

    <p v-if="current.total_takes > current.warn_above" class="small warn">
      {{ current.total_takes }} takes: above {{ current.warn_above }}. It works, but each take adds to the bank.
    </p>
    <template v-if="!readOnly">
      <p v-if="!current.allowed" class="small muted" data-testid="takes-not-allowed">Added takes are not available here: {{ current.reason }}.</p>
      <div v-else class="row">
        <button type="button" class="icon-label" :disabled="!canAdd || alreadyAdded" data-testid="take-add" @click="add">
          <Plus :size="15" aria-hidden="true" /> Add as extra take
        </button>
        <span class="small muted">
          <template v-if="!focusedRef">Select a Campaign Evolved recording on the right first.</template>
          <template v-else-if="alreadyAdded"><span class="mono">{{ focusedRef }}</span> is already a take of this sound.</template>
          <template v-else>Adds <span class="mono">{{ focusedRef }}</span> (es-MX) as a draft.</template>
        </span>
      </div>
    </template>
    <p v-if="error" class="small error" role="alert">{{ error }}</p>
    <p v-else-if="note" class="small ok" role="status">{{ note }}</p>
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
.count {
  margin-left: 0.4rem;
  font-size: 0.85em;
  opacity: 0.75;
}
</style>
