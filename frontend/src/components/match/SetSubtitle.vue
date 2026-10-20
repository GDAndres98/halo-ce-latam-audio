<script setup lang="ts">
// "Subtitle of this sound" (owner, 2026-10-19; docs/custom-take-set-design.md §2.1). A sound with a SU/SP subtitle
// entry shows ONE text for every take, so a sound that plays its own take set (staged or in force) has ONE subtitle:
// own_sets[].subtitle. Same choices and rules as a line's subtitle: saved as a draft right away (/api/takes/
// set_subtitle), approved only by the owner's confirmed click, read-only once approved until "Needs rework"
// (revision + 1). A custom text is kept in the git-ignored local file. The build writes it only while the set is in
// force and the subtitle is approved; otherwise MCC's text stays. Nothing here picks a text on its own.

import { Captions } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { api, ApiError } from "../../api/client";
import type { SetSubtitleChoice, SoundTakes, SubtitleSource, TakeResponse } from "../../api/types";
import { confirmAction } from "../../composables/useConfirm";
import { LATAM_CULTURE } from "../../matching/draft";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{ sound: SoundTakes; readOnly?: boolean }>();
const emit = defineEmits<{ changed: [sound: SoundTakes] }>();

const SOURCES: { value: SubtitleSource; label: string }[] = [
  { value: "keep_original", label: "Keep MCC's LATAM text (SU)" },
  { value: "ce_locres", label: "Use a Campaign Evolved subtitle (of a take of this set)" },
  { value: "custom", label: "Write my own LATAM Spanish text" },
  { value: "none", label: "No subtitle (intentionally omitted)" },
];
const CULTURES = [LATAM_CULTURE, "en", "es-ES"];

const view = computed(() => props.sound.set_subtitle ?? null);
const decision = computed(() => view.value?.decision ?? null);
const locked = computed(() => props.readOnly || decision.value?.status === "approved");
const busy = ref(false);
const error = ref("");
const note = ref("");

// The form: starts from the stored decision (or keep MCC's text), changes nothing until "Save".
const source = ref<SubtitleSource>("keep_original");
const ceRef = ref<string | null>(null);
const culture = ref(LATAM_CULTURE);
const customText = ref("");
function reset() {
  const d = decision.value;
  source.value = d?.source ?? "keep_original";
  ceRef.value = d?.ce_locres?.ce_line_ref ?? null;
  culture.value = d?.ce_locres?.culture ?? LATAM_CULTURE;
  customText.value = view.value?.custom_text ?? props.sound.mcc_text?.SU ?? "";
}
watch(() => props.sound.version, reset, { immediate: true });

/** The CE lines the set's takes play, with their subtitles (the choices for "a Campaign Evolved subtitle"). */
const lines = computed(() => {
  const seen = new Set<string>();
  return props.sound.added_takes.map((t) => t.line).filter((l): l is NonNullable<typeof l> => {
    if (!l || seen.has(l.ce_line_ref)) return false;
    seen.add(l.ce_line_ref);
    return true;
  });
});

const choice = computed<SetSubtitleChoice | null>(() => {
  if (source.value === "ce_locres") return ceRef.value ? { source: "ce_locres", ce_locres: { ce_line_ref: ceRef.value, culture: culture.value } } : null;
  if (source.value === "custom") return customText.value.trim() ? { source: "custom", custom_text: customText.value.trim() } : null;
  return { source: source.value };
});
const dirty = computed(() => {
  const d = decision.value;
  const c = choice.value;
  if (!c) return false;
  if (!d) return true;
  if (c.source !== d.source) return true;
  if (c.source === "ce_locres") return c.ce_locres?.ce_line_ref !== d.ce_locres?.ce_line_ref || c.ce_locres?.culture !== d.ce_locres?.culture;
  if (c.source === "custom") return c.custom_text !== (view.value?.custom_text ?? "");
  return false;
});

/** What the game shows with the current form (saved or not). */
const preview = computed(() => {
  switch (source.value) {
    case "keep_original": return props.sound.mcc_text?.SU ?? null;
    case "ce_locres": return lines.value.find((l) => l.ce_line_ref === ceRef.value)?.subtitles[culture.value]?.text ?? null;
    case "custom": return customText.value.trim() || null;
    default: return "";
  }
});
const statusTone = computed(() => {
  const st = decision.value?.status;
  return st === "approved" ? "ok" : st === "needs_rework" ? "bad" : st ? "warn" : "muted";
});
const statusLabel = computed(() => (decision.value ? decision.value.status.replace("_", " ") : "undecided"));

async function run(label: string, op: () => Promise<TakeResponse>) {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    const r = await op();
    emit("changed", r.sound);
    note.value = r.saved ? label : (r.message ?? "Nothing changed.");
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.message}${e.details.length ? ` (${e.details.join("; ")})` : ""}` : String(e);
  } finally {
    busy.value = false;
  }
}

const base = () => ({ mcc_tag: props.sound.mcc_tag, loaded_takes_sha256: props.sound.version });
function save() {
  const c = choice.value;
  if (c) return run("Subtitle saved as a draft.", () => api.setSubtitle({ ...base(), subtitle: c }));
}
async function approve() {
  const text = view.value?.text;
  const ok = await confirmAction({
    title: "Approve the subtitle of this sound",
    message: `Every take of ${props.sound.tag_name} shows this subtitle:\n\n` +
      (text === "" ? "(no subtitle: the entry is written empty)" : text ?? "(MCC's text)") +
      "\n\nApproved subtitles are read-only. The build writes it in SU and SP while the replacement set is in force.",
    confirmLabel: "Yes, approve",
  });
  if (ok) await run("Subtitle approved.", () => api.setSubtitle({ ...base(), actions: [{ action: "approve" }] }));
}
async function rework() {
  const ok = await confirmAction({
    title: "Needs rework",
    message: "Mark the subtitle of this sound Needs rework? Its revision goes up by one; the build keeps MCC's text until it is approved again.",
    confirmLabel: "Mark Needs rework",
    tone: "warning",
  });
  if (ok) await run("Subtitle marked Needs rework.", () => api.setSubtitle({ ...base(), actions: [{ action: "needs_rework" }] }));
}
function clear() {
  return run("Subtitle cleared: undecided again.", () => api.setSubtitle({ ...base(), subtitle: null }));
}
</script>

<template>
  <div class="set-subtitle" data-testid="set-subtitle">
    <h4 class="small">
      <Captions :size="14" aria-hidden="true" /> Subtitle of this sound <span class="muted">(one for every take)</span>
      <StatusBadge :label="statusLabel" :tone="statusTone" data-testid="set-subtitle-status" />
      <StatusBadge v-if="view?.drift" label="changed since approval" tone="bad" />
    </h4>
    <p class="small muted">
      <span class="mono">{{ sound.tag_name }}</span> has one subtitle entry, shared by every take. MCC LATAM (SU):
      <template v-if="sound.mcc_text?.SU">“{{ sound.mcc_text.SU }}”</template><template v-else>(an empty entry: no text is shown today)</template><template v-if="sound.mcc_text?.SP && sound.mcc_text.SP !== sound.mcc_text.SU"> · Spain (SP): “{{ sound.mcc_text.SP }}”</template>.
      <template v-if="!decision || decision.status !== 'approved'">Until it is approved, the build keeps MCC's text.</template>
    </p>
    <p v-if="decision" class="small" data-testid="set-subtitle-current">
      Saved: {{ SOURCES.find((s) => s.value === decision!.source)?.label }}
      <template v-if="view?.text"> · “{{ view.text }}”</template><template v-else-if="view?.text === ''"> · (empty entry)</template>
    </p>

    <template v-if="!readOnly">
      <fieldset :disabled="locked || busy" class="choice">
        <label v-for="s in SOURCES" :key="s.value" class="opt">
          <input v-model="source" type="radio" :value="s.value" :data-testid="`set-subtitle-${s.value}`" />
          {{ s.label }}
        </label>
      </fieldset>
      <div v-if="source === 'ce_locres'" class="ce-subtitle">
        <label class="inline">Language
          <select v-model="culture" :disabled="locked">
            <option v-for="c in CULTURES" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <ul v-if="lines.length" class="plain">
          <li v-for="line in lines" :key="line.ce_line_ref">
            <label class="opt">
              <input v-model="ceRef" type="radio" :value="line.ce_line_ref" :disabled="locked || !line.subtitles[culture]?.text" />
              <span class="mono small">{{ line.ce_line_ref }}</span>
              <span class="small">{{ line.subtitles[culture]?.text ?? `no ${culture} subtitle` }}</span>
            </label>
          </li>
        </ul>
        <p v-else class="small muted">Add takes to the set first; their subtitles can then be chosen here.</p>
      </div>
      <label v-if="source === 'custom'" class="block-label small">Subtitle text (LATAM Spanish)
        <textarea v-model="customText" rows="2" :disabled="locked" data-testid="set-subtitle-text"></textarea>
      </label>
      <p class="small">Preview: <span v-if="preview" class="subtitle-text">{{ preview }}</span><span v-else class="muted">(no text)</span></p>
      <div class="row">
        <button v-if="!locked" type="button" class="small-button" :disabled="busy || !dirty" data-testid="set-subtitle-save" @click="save">Save subtitle</button>
        <button v-if="decision && decision.status !== 'approved'" type="button" class="small-button" :disabled="busy || dirty"
                :title="dirty ? 'Save the change first' : 'Approve this subtitle'" data-testid="set-subtitle-approve" @click="approve">Approve subtitle</button>
        <button v-if="decision?.status === 'approved'" type="button" class="small-button" :disabled="busy" data-testid="set-subtitle-rework" @click="rework">Needs rework</button>
        <button v-if="decision && decision.status !== 'approved'" type="button" class="small-button" :disabled="busy" @click="clear">Clear</button>
      </div>
      <p v-if="locked" class="small muted">Approved. Mark it Needs rework to change the subtitle.</p>
    </template>
    <p v-if="error" class="small error" role="alert">{{ error }}</p>
    <p v-else-if="note" class="small ok" role="status">{{ note }}</p>
  </div>
</template>

<style scoped>
.set-subtitle {
  display: grid;
  gap: 0.35rem;
  margin-top: 0.5rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--frame, rgba(127, 127, 127, 0.4));
  border-radius: 6px;
}
h4 {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}
.plain {
  list-style: none;
  margin: 0;
  padding: 0;
}
textarea {
  width: 100%;
}
</style>
