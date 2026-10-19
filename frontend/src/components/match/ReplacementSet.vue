<script setup lang="ts">
// Replacement set from the owner's own selections (docs/replacement-set-conversion.md). Lives under "Takes of this
// sound". Three states:
//   per take / Spain + added  "Preview a replacement set": a read-only preview of turning the selections already made
//                             for the sound's Spain takes into one set of takes (equal selections become one take),
//                             then "Stage" (owner-confirmed; review points must be ticked one by one).
//   staged                    the line decisions stay in force; the new takes are drafts. "Approve unchanged converted
//                             takes" lists which takes carry an approved, unchanged, drift-free selection and which
//                             are left out and why; the owner confirms that list (a new approval of each take). Then
//                             "Switch" once every take is approved and buildable (the server checks it again), or
//                             "Cancel".
//   active, with a record     what the next build does with the set's takes, the archived decisions' reminders, and
//                             "Undo": a preview first (what comes back, conflicts), then the undo exactly as previewed.
// Nothing here pairs lines, picks recordings or approves anything; every request names what the page showed and is
// refused when it changed.

import { CheckCheck, Layers, RotateCcw, Shuffle, X } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import type { ApprovableTakes, BuildView, ConversionPreview, ConversionResponse, RevertPreview, SoundTakes } from "../../api/types";
import { confirmAction } from "../../composables/useConfirm";
import AudioButton from "../AudioButton.vue";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{ sound: SoundTakes; readOnly?: boolean; canListen?: boolean }>();
const emit = defineEmits<{ changed: [sound: SoundTakes] }>();

const preview = ref<ConversionPreview | null>(null);
const acked = ref<string[]>([]);
const busy = ref(false);
const error = ref("");
const note = ref("");
const approvable = ref<ApprovableTakes | null>(null);
const undoPlan = ref<RevertPreview | null>(null);
watch(() => props.sound.mcc_tag, () => {
  preview.value = null; acked.value = []; error.value = ""; note.value = ""; approvable.value = null; undoPlan.value = null;
});
watch(() => props.sound.sound_version, () => { approvable.value = null; undoPlan.value = null; });
watch(() => props.sound.sound_version, () => { if (preview.value && preview.value.token !== props.sound.sound_version) preview.value = null; });

const mode = computed(() => props.sound.mode);
const conv = computed(() => props.sound.conversion);
const staged = computed(() => mode.value === "replacement_set_staged");
const canConvert = computed(() => props.sound.allowed && (mode.value === "per_take" || mode.value === "spain_plus_added")
  && props.sound.spain_takes.some((t) => t.mapping_id));
const approved = computed(() => props.sound.added_takes.filter((t) => t.audio.status === "approved").length);
const allApproved = computed(() => props.sound.added_takes.length > 0 && approved.value === props.sound.added_takes.length);
/** Active set: takes the next build would leave out (not approved, or changed since approval). */
const notBuilt = computed(() => props.sound.added_takes.filter((t) => t.audio.status !== "approved" || t.drift));
const DRIFT_ONLY = ["approval_drift"];
const onlyDrift = computed(() => (undoPlan.value?.conflicts ?? []).every((c) => DRIFT_ONLY.includes(c.code)));
const reviewCodes = computed(() => preview.value?.review_codes ?? []);
const issuesBy = (sev: string) => (preview.value?.issues ?? []).filter((i) => i.severity === sev);
const canStage = computed(() => {
  const p = preview.value;
  if (!p || busy.value || props.readOnly) return false;
  if (p.status === "ready") return true;
  return p.status === "review" && reviewCodes.value.every((c) => acked.value.includes(c));
});
const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "muted"> = {
  ready: "ok", review: "warn", blocked: "bad", ineligible: "muted", nothing_to_convert: "muted", staged: "warn", active: "ok",
};
const STATUS_LABEL: Record<string, string> = {
  ready: "ready to stage", review: "needs your review", blocked: "cannot be converted", ineligible: "not eligible",
  nothing_to_convert: "nothing to convert", staged: "staged", active: "replacement set on",
};

function buildLine(b: BuildView | undefined) {
  if (!b) return "";
  const parts = [];
  if (b.replaced) parts.push(`${b.replaced} replaced`);
  if (b.muted) parts.push(`${b.muted} muted`);
  if (b.spain_kept) parts.push(`${b.spain_kept} Spain's recording`);
  if (b.dropped) parts.push(`${b.dropped} Spain take(s) removed`);
  if (b.inserted) parts.push(`${b.inserted} take(s) inserted`);
  return `${b.takes_in_game} take(s) in game: ${parts.join(", ") || "nothing changes"}`;
}

const describe = (e: unknown) =>
  e instanceof ApiError ? `${e.message}${e.details.length ? ` (${e.details.join("; ")})` : ""}` : String(e);

async function run(label: (r: ConversionResponse) => string, op: () => Promise<ConversionResponse>) {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    const r = await op();
    note.value = r.saved ? label(r) : (r.message ?? "Nothing changed.");
    if (r.sound) emit("changed", r.sound);
    preview.value = null;
    acked.value = [];
    approvable.value = null;
    undoPlan.value = null;
    return r;
  } catch (e) {
    error.value = describe(e);
    return null;
  } finally {
    busy.value = false;
  }
}

async function loadPreview() {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    preview.value = await api.convertPreview(props.sound.mcc_tag);
    acked.value = [];
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

async function stage() {
  const p = preview.value;
  if (!p) return;
  const created = (p.proposed ?? []).filter((t) => t.origin === "new").length;
  const ok = await confirmAction({
    title: "Stage the replacement set",
    message:
      `${p.summary}.\n\n${created} new take(s) are added as drafts${(p.proposed ?? []).length > created ? ", and the sound's existing takes join the set unchanged" : ""}. ` +
      "Nothing is approved for you, and nothing changes in a build yet: the line decisions stay in force until you approve every take and switch the sound." +
      (reviewCodes.value.length ? `\n\nYou confirmed: ${reviewCodes.value.join(", ")}.` : ""),
    confirmLabel: "Stage",
  });
  if (!ok) return;
  await run((r) => `Staged ${r.staged?.[0]?.record_id ?? ""}: ${r.staged?.[0]?.created.length ?? 0} draft take(s). Approve each one above, then switch.`,
            () => api.convertStage({ confirm: true, items: [{ mcc_tag: p.mcc_tag, token: p.token, acknowledged: acked.value }] }));
}

async function loadApprovable() {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    approvable.value = await api.convertApprovable(props.sound.mcc_tag);
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

async function approveUnchanged() {
  const a = approvable.value;
  if (!a || !a.included.length) return;
  const lines = a.included.map((t) => `  • ${t.take_id} ${t.ce_line_ref}${t.edit_summary ? ` (${t.edit_summary})` : ""} ← ` +
    t.sources.map((x) => `${x.slot_id} (approved ${x.approved_at})`).join(", "));
  const ok = await confirmAction({
    title: "Approve unchanged converted takes",
    message:
      `Approve these ${a.included.length} take(s) now? Each one carries exactly the audio you approved for the lines listed, ` +
      "unchanged and still valid.\n\n" + lines.join("\n") +
      "\n\nThis is a new approval of each take (its own fingerprint, today's date); the lines' approvals are not copied. " +
      (a.excluded.length ? `${a.excluded.length} other take(s) are left out (see the list) and need approving one by one. ` : "") +
      "If anything changed since this list was shown, nothing is approved.",
    confirmLabel: `Approve ${a.included.length}`,
  });
  if (!ok) return;
  await run((r) => `Approved ${r.approved?.join(", ") ?? ""}.`,
            () => api.convertApproveUnchanged({ confirm: true, mcc_tag: a.mcc_tag, loaded_sound_sha256: a.sound_version,
                                                take_ids: a.included.map((t) => t.take_id) }));
}

async function activate() {
  const s = props.sound;
  const decisions = conv.value?.replaced_decisions ?? 0;
  const ok = await confirmAction({
    title: "Switch to the replacement set",
    message:
      `${s.tag_name} will play its ${s.added_takes.length} replacement take(s) instead of Spain's ${s.spain_takes.length}.\n\n` +
      `Its ${decisions} line decision(s) stop applying: approved ones are marked Needs rework, then removed, in one save. ` +
      "They stay in the set's record exactly as they were; Undo can bring them back with their approvals.\n\n" +
      "This changes your decisions and what the next build produces; it does not touch the installed game.",
    confirmLabel: "Switch",
    tone: "warning",
  });
  if (ok) await run((r) => `Switched (${r.switched?.[0]?.record_id ?? ""}).`,
                    () => api.convertActivate({ confirm: true, items: [{ mcc_tag: s.mcc_tag, loaded_sound_sha256: s.sound_version }] }));
}

async function cancel() {
  const s = props.sound;
  const created = conv.value?.takes.filter((t) => t.origin === "created").length ?? 0;
  const ok = await confirmAction({
    title: "Cancel the conversion",
    message: `The ${created} take(s) the conversion created are removed (approved ones are marked Needs rework first). ` +
      "The line decisions were never changed and stay as they are. Take IDs are not reused.",
    confirmLabel: "Cancel the conversion",
    tone: "warning",
  });
  if (ok) await run(() => "Conversion cancelled.", () => api.convertCancel({ mcc_tag: s.mcc_tag, loaded_sound_sha256: s.sound_version }));
}

async function loadUndo(reworkDrifted = false) {
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    undoPlan.value = await api.convertRevertPreview(props.sound.mcc_tag, reworkDrifted);
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

async function revert() {
  const u = undoPlan.value;
  if (!u || u.conflicts.length) return;
  const back = u.restore.filter((r) => r.audio === "approval restored" || r.subtitle === "approval restored").length;
  const ok = await confirmAction({
    title: "Undo the replacement set",
    message:
      `${u.restore.length} line decision(s) come back exactly as recorded (${back} with their approvals)` +
      (u.drifted.length ? `; ${u.drifted.length} approval(s) that no longer match the catalogs come back as Needs rework` : "") +
      `.\n\nThe ${u.remove_takes.length} take(s) the set created leave the sound (approved ones are marked Needs rework first; ` +
      `their IDs are never reused). ${u.keep_takes.length ? `Takes it had before stay: ${u.keep_takes.join(", ")}.` : ""}` +
      (Object.keys(u.local_restore.custom_subtitles).length ? `\n\nMissing custom subtitle text is put back: ${Object.keys(u.local_restore.custom_subtitles).join(", ")}.` : ""),
    confirmLabel: "Undo",
    tone: "warning",
  });
  if (ok) await run((r) => `Undone: ${r.restored?.length ?? 0} decision(s) restored` +
                      (r.local_restored?.length ? `, local text put back (${r.local_restored.join(", ")})` : "") + ".",
                    () => api.convertRevert({ confirm: true, mcc_tag: u.mcc_tag, token: u.token, rework_drifted: u.rework_drifted }));
}
</script>

<template>
  <div class="replacement-set" data-testid="replacement-set">
    <!-- staged: the switch -->
    <template v-if="staged && conv">
      <p class="small" data-testid="set-staged">
        <StatusBadge label="staged" tone="warn" />
        Replacement set staged on {{ conv.created_at }} ({{ conv.record_id }}): the line decisions still apply.
        {{ approved }} of {{ sound.added_takes.length }} take(s) approved.
        <template v-if="!allApproved"> Approve every take above, then switch.</template>
      </p>
      <div v-if="!readOnly && !allApproved" class="row">
        <button type="button" class="icon-label" :disabled="busy" data-testid="set-approvable" @click="loadApprovable">
          <CheckCheck :size="15" aria-hidden="true" /> Approve unchanged converted takes…
        </button>
      </div>
      <div v-if="approvable" class="preview" data-testid="set-approvable-panel">
        <h4 class="small">Would be approved ({{ approvable.included.length }})</h4>
        <ul class="plain" data-testid="approvable-included">
          <li v-for="t in approvable.included" :key="t.take_id">
            <span class="mono small">{{ t.take_id }}</span> <span class="mono small">{{ t.ce_line_ref }}</span>
            <span class="small muted"><template v-if="t.edit_summary">{{ t.edit_summary }} · </template>from
              {{ t.sources.map((x) => `${x.slot_id} (approved ${x.approved_at})`).join(", ") }}</span>
          </li>
          <li v-if="!approvable.included.length" class="small muted">None: approve the takes one by one above.</li>
        </ul>
        <template v-if="approvable.excluded.length">
          <h4 class="small">Left out ({{ approvable.excluded.length }})</h4>
          <ul class="plain" data-testid="approvable-excluded">
            <li v-for="t in approvable.excluded" :key="t.take_id">
              <span class="mono small">{{ t.take_id }}</span> <span class="mono small">{{ t.ce_line_ref }}</span>
              <span class="small warn">{{ t.reasons.join("; ") }}</span>
            </li>
          </ul>
        </template>
        <div class="row">
          <button type="button" class="icon-label" :disabled="busy || !approvable.included.length" data-testid="approve-unchanged"
                  @click="approveUnchanged">
            <CheckCheck :size="15" aria-hidden="true" /> Approve these {{ approvable.included.length }}
          </button>
          <button type="button" class="icon-label" :disabled="busy" @click="approvable = null">Close</button>
        </div>
      </div>
      <div v-if="!readOnly" class="row">
        <button type="button" class="icon-label" :disabled="busy || !allApproved" data-testid="set-activate" @click="activate">
          <Shuffle :size="15" aria-hidden="true" /> Switch to the replacement set
        </button>
        <button type="button" class="icon-label" :disabled="busy" data-testid="set-cancel" @click="cancel">
          <X :size="15" aria-hidden="true" /> Cancel the conversion
        </button>
      </div>
    </template>

    <!-- active, with a record: undo -->
    <template v-else-if="mode === 'replacement_set' && conv">
      <details class="small">
        <summary data-testid="set-record">
          Record {{ conv.record_id }} ({{ conv.kind === "conversion" ? "from your selections" : "replace every take" }}):
          {{ conv.replaced_decisions }} line decision(s) replaced on {{ conv.activated_at ?? conv.created_at }}
        </summary>
        <ul class="plain">
          <li v-for="d in conv.decisions" :key="d.mapping_id">
            <span class="mono">{{ d.slot_id }}</span> · {{ d.audio_source === "ce" ? d.audio_ref : d.audio_source }} · audio {{ d.audio }} · subtitle {{ d.subtitle }}<template v-if="d.notes"> · “{{ d.notes }}”</template>
          </li>
        </ul>
      </details>
      <p v-if="notBuilt.length" class="small warn" data-testid="set-not-built">
        The next build leaves out {{ notBuilt.length }} of {{ sound.added_takes.length }} take(s)
        ({{ notBuilt.map((t) => `${t.take_id}: ${t.drift ? "changed since approval" : t.audio.status.replace("_", " ")}`).join(", ") }}).
        <template v-if="notBuilt.length === sound.added_takes.length">With none left, the build keeps Spain's own recordings for this sound.</template>
        <template v-else>The sound plays the other takes only.</template>
      </p>
      <div v-if="!readOnly && !undoPlan" class="row">
        <button type="button" class="icon-label" :disabled="busy" data-testid="set-revert-preview" @click="loadUndo()">
          <RotateCcw :size="15" aria-hidden="true" /> Undo the replacement set…
        </button>
      </div>
      <div v-if="undoPlan" class="preview" data-testid="set-undo-panel">
        <h4 class="small">Comes back ({{ undoPlan.restore.length }})</h4>
        <ul class="plain">
          <li v-for="r in undoPlan.restore" :key="r.mapping_id" class="small">
            <span class="mono">{{ r.slot_id }}</span> · audio {{ r.audio }} · subtitle {{ r.subtitle }}
          </li>
        </ul>
        <p class="small">Takes removed: {{ undoPlan.remove_takes.join(", ") || "none" }} · takes kept: {{ undoPlan.keep_takes.join(", ") || "none" }}</p>
        <p v-for="(n, k) in undoPlan.notes" :key="k" class="small muted">{{ n }}</p>
        <p v-if="Object.keys(undoPlan.local_restore.custom_subtitles).length" class="small">
          Missing custom subtitle text put back from the recovery snapshot: {{ Object.keys(undoPlan.local_restore.custom_subtitles).join(", ") }}
        </p>
        <div v-if="undoPlan.conflicts.length" class="issues bad" data-testid="set-undo-conflicts">
          <p class="small"><strong>Nothing can be undone yet:</strong></p>
          <p v-for="(c, k) in undoPlan.conflicts" :key="k" class="small">{{ c.code }}: {{ c.detail }}</p>
          <label v-if="onlyDrift" class="small ack">
            <input type="checkbox" data-testid="undo-rework-drifted" @change="loadUndo(($event.target as HTMLInputElement).checked)" />
            <span>Bring the drifted decisions back as Needs rework instead (to approve again)</span>
          </label>
        </div>
        <label v-else-if="undoPlan.rework_drifted" class="small ack">
          <input type="checkbox" checked @change="loadUndo(($event.target as HTMLInputElement).checked)" />
          <span>Drifted decisions come back as Needs rework: {{ undoPlan.drifted.join(", ") }}</span>
        </label>
        <div class="row">
          <button type="button" class="icon-label" :disabled="busy || undoPlan.conflicts.length > 0" data-testid="set-revert" @click="revert">
            <RotateCcw :size="15" aria-hidden="true" /> Undo
          </button>
          <button type="button" class="icon-label" :disabled="busy" @click="undoPlan = null">Close</button>
        </div>
      </div>
    </template>

    <!-- per take: preview, then stage -->
    <template v-else-if="canConvert && !readOnly">
      <div v-if="!preview" class="row">
        <button type="button" class="icon-label" :disabled="busy" data-testid="set-preview" @click="loadPreview">
          <Layers :size="15" aria-hidden="true" /> Preview a replacement set from my selections
        </button>
        <span class="small muted">Read-only: shows what your per-take selections would become. Nothing is saved.</span>
      </div>
      <div v-else class="preview" data-testid="set-preview-panel">
        <p class="summary">
          <strong data-testid="set-summary">{{ preview.summary }}</strong>
          <StatusBadge :label="STATUS_LABEL[preview.status] ?? preview.status" :tone="STATUS_TONE[preview.status] ?? 'muted'" />
        </p>
        <h4 class="small">Replacement takes</h4>
        <ol class="plain" data-testid="set-proposed">
          <li v-for="t in preview.proposed ?? []" :key="t.take_id ?? `new-${t.position}`">
            <AudioButton v-if="canListen !== false" :url="audioUrl.ce(t.ce_line_ref, t.language)" label="es-MX" title="Listen" />
            <span class="mono small">{{ t.ce_line_ref }}</span>
            <span class="small muted">
              {{ t.origin === "existing" ? `existing ${t.take_id} (${t.status})` : "new draft" }}<template v-if="t.edit_summary"> · {{ t.edit_summary }}</template><template v-if="t.radio_effect"> · needs radio effect</template>
              <template v-if="t.from_slots.length"> · from {{ t.from_slots.join(", ") }}</template>
            </span>
          </li>
        </ol>
        <h4 class="small">Original MCC takes</h4>
        <ul class="plain" data-testid="set-sources">
          <li v-for="s in preview.sources ?? []" :key="s.slot_id">
            <AudioButton v-if="canListen !== false" :url="audioUrl.mcc(preview.level, 'spanish', s.spanish_index)" label="ES" title="Spain's recording" />
            <span class="mono small">{{ s.slot_id }}</span>
            <span class="small muted">
              <template v-if="!s.decision">no decision</template>
              <template v-else>{{ s.decision.audio_source === "ce" ? s.decision.audio_refs.join(", ") : s.decision.audio_source }} · audio {{ s.decision.audio }}</template>
              → {{ s.take ?? "no replacement take" }}
            </span>
          </li>
        </ul>
        <div v-if="issuesBy('blocked').length" class="issues bad" data-testid="set-blocked">
          <p v-for="(i, k) in issuesBy('blocked')" :key="k" class="small"><span v-if="i.slot_id" class="mono">{{ i.slot_id }}: </span>{{ i.message }}<template v-if="i.detail"> ({{ i.detail }})</template></p>
        </div>
        <fieldset v-if="reviewCodes.length" class="issues" data-testid="set-review">
          <legend class="small">Needs your review: tick each point to stage anyway</legend>
          <label v-for="c in reviewCodes" :key="c" class="small ack">
            <input v-model="acked" type="checkbox" :value="c" :data-testid="`ack-${c}`" />
            <span>
              {{ issuesBy("review").find((i) => i.code === c)?.message }}
              <span class="muted">({{ issuesBy("review").filter((i) => i.code === c).map((i) => i.slot_id).filter(Boolean).join(", ") }})</span>
            </span>
          </label>
        </fieldset>
        <details class="small">
          <summary>What the build does</summary>
          <p>Now: {{ buildLine(preview.build_now) }}.</p>
          <p v-if="preview.build_staged">While staged: {{ buildLine(preview.build_staged) }} (unchanged).</p>
          <p v-if="preview.build_after">After the switch: {{ buildLine(preview.build_after) }}; {{ preview.build_after.note }}.</p>
          <p class="muted">The game picks a take at random: fewer takes change how often each one plays.</p>
        </details>
        <details v-if="issuesBy('info').length" class="small">
          <summary>Details ({{ issuesBy("info").length }})</summary>
          <p v-for="(i, k) in issuesBy('info')" :key="k"><span v-if="i.slot_id" class="mono">{{ i.slot_id }}: </span>{{ i.message }}<template v-if="i.detail"> ({{ i.detail }})</template></p>
        </details>
        <div class="row">
          <button type="button" class="icon-label" :disabled="!canStage" data-testid="set-stage" @click="stage">
            <Layers :size="15" aria-hidden="true" /> Stage the replacement set
          </button>
          <button type="button" class="icon-label" :disabled="busy" @click="preview = null">Close</button>
        </div>
      </div>
    </template>

    <p v-if="error" class="small error" role="alert">{{ error }}</p>
    <p v-else-if="note" class="small ok" role="status" data-testid="set-note">{{ note }}</p>
  </div>
</template>

<style scoped>
.replacement-set {
  display: grid;
  gap: 0.4rem;
  margin-top: 0.5rem;
}
.preview {
  display: grid;
  gap: 0.35rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--frame, rgba(127, 127, 127, 0.4));
  border-radius: 6px;
}
.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
}
h4 {
  margin: 0.3rem 0 0;
}
.plain {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.25rem;
}
.plain li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  overflow-wrap: anywhere;
}
.issues {
  display: grid;
  gap: 0.25rem;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--line, rgba(127, 127, 127, 0.3));
  border-radius: 6px;
}
.issues p {
  margin: 0;
}
.ack {
  display: flex;
  gap: 0.4rem;
  align-items: flex-start;
}
</style>
