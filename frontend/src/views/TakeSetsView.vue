<script setup lang="ts">
// Take sets: every multi-take sound at a glance, and replacement sets in bulk (docs/replacement-set-conversion.md).
//
// The list is a read-only preview of turning each sound's per-take selections into one set of replacement takes
// ("3 original MCC takes -> 2 replacement takes"), so existing work can be reviewed without opening every Spain take.
// Two bulk actions, each confirmed by the owner and refused as a whole if any listed sound changed since the list
// was loaded:
//   Stage    only sounds whose preview needs no review ("ready"); review cases are staged one by one from the line
//            panel, where each point is ticked. Staging changes no build: the line decisions stay in force.
//   Switch   only staged sounds whose takes are all approved.
// Nothing here approves a take or pairs a line.

import { computed, onMounted, ref } from "vue";
import { ExternalLink, Layers, RefreshCw, Shuffle } from "lucide-vue-next";
import { api, ApiError } from "../api/client";
import type { ConversionInventory, ConversionPreview } from "../api/types";
import { readOnly, visitor } from "../auth/session";
import StatusBadge from "../components/StatusBadge.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import PanelHeader from "../components/ui/PanelHeader.vue";
import StateMessage from "../components/ui/StateMessage.vue";
import { confirmAction } from "../composables/useConfirm";

const inv = ref<ConversionInventory | null>(null);
const busy = ref(false);
const error = ref("");
const message = ref("");
const filter = ref<string>("ready");
const picked = ref<string[]>([]);

const STATUS: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "muted"; help: string }> = {
  ready: { label: "ready", tone: "ok", help: "Every Spain take selects Campaign Evolved audio; nothing needs review." },
  review: { label: "needs review", tone: "warn", help: "Stage it from the line panel, ticking each point." },
  blocked: { label: "blocked", tone: "bad", help: "Something cannot become a take (unsupported source, missing media, a bad recipe)." },
  staged: { label: "staged", tone: "warn", help: "Prepared; the line decisions still apply until you switch." },
  active: { label: "replacement set", tone: "ok", help: "In force: the sound plays only its takes." },
  ineligible: { label: "per take only", tone: "muted", help: "Stereo (stereo replacement is deferred)." },
  nothing_to_convert: { label: "nothing selected", tone: "muted", help: "No audio selected yet." },
  single_take: { label: "sets on single-take sounds", tone: "ok", help: "Own sets on sounds that have one Spain take (counted apart from the multi-take sounds)." },
};
const ORDER = ["ready", "review", "blocked", "staged", "active", "ineligible", "nothing_to_convert", "single_take"];
const countOf = (k: string) => (k === "single_take" ? inv.value?.counts.own_sets_single_take : inv.value?.counts[k]) ?? 0;
const canWrite = computed(() => !readOnly.value && !visitor.value);

const shown = computed(() => (inv.value?.sounds ?? []).filter((s) =>
  !filter.value || (filter.value === "single_take" ? s.single_take : s.status === filter.value && !s.single_take)));
const pickable = (s: ConversionPreview) =>
  s.status === "ready" || (s.status === "staged" && (s.takes_total ?? 0) > 0 && s.takes_approved === s.takes_total);
const pickedReady = computed(() => (inv.value?.sounds ?? []).filter((s) => picked.value.includes(s.mcc_tag) && s.status === "ready"));
const pickedSwitch = computed(() => (inv.value?.sounds ?? []).filter((s) => picked.value.includes(s.mcc_tag) && s.status === "staged"));
const allShownPicked = computed(() => {
  const ids = shown.value.filter(pickable);
  return ids.length > 0 && ids.every((s) => picked.value.includes(s.mcc_tag));
});

const describe = (e: unknown) =>
  e instanceof ApiError ? `${e.message}${e.details.length ? `: ${e.details.join("; ")}` : ""}` : String(e);
const name = (tag: string) => tag.replace(/^sound\\dialog\\/, "");

async function refresh() {
  busy.value = true;
  error.value = "";
  try {
    inv.value = await api.convertInventory("all");
    picked.value = picked.value.filter((t) => inv.value?.sounds.some((s) => s.mcc_tag === t && pickable(s)));
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

function toggleAll() {
  const ids = shown.value.filter(pickable).map((s) => s.mcc_tag);
  picked.value = allShownPicked.value ? picked.value.filter((t) => !ids.includes(t)) : [...new Set([...picked.value, ...ids])];
}

async function stage() {
  const items = pickedReady.value;
  if (!items.length) return;
  const takes = items.reduce((n, s) => n + (s.replacement_takes ?? 0), 0);
  const ok = await confirmAction({
    title: `Stage ${items.length} replacement set(s)`,
    message:
      `${items.length} sound(s) get a staged replacement set (${takes} replacement take(s) in all, existing takes included). ` +
      "New takes are drafts: nothing is approved for you. No build changes until you approve every take of a sound and " +
      "switch it; until then its line decisions stay in force.\n\nIf any of these sounds changed since this list was " +
      "loaded, nothing is staged.",
    confirmLabel: `Stage ${items.length}`,
  });
  if (!ok) return;
  await act(async () => {
    const r = await api.convertStage({ confirm: true, bulk: true, items: items.map((s) => ({ mcc_tag: s.mcc_tag, token: s.token })) });
    return `Staged ${r.staged?.length ?? 0} sound(s)${r.already?.length ? `; ${r.already.length} were already staged` : ""}. ` +
      "Approve each sound's takes in the line panel, then switch.";
  });
}

async function activate() {
  const items = pickedSwitch.value;
  if (!items.length) return;
  const ok = await confirmAction({
    title: `Switch ${items.length} sound(s) to their replacement sets`,
    message:
      `Each sound then plays only its approved replacement takes; the build removes its Spain takes. Its line decisions ` +
      "stop applying: approved ones are marked Needs rework, then removed, all in one save. They stay in each set's " +
      "record, and Undo (in the line panel) brings them back as Needs rework.\n\nIf any of these sounds changed since " +
      "this list was loaded, or a take is not approved, nothing is switched.",
    confirmLabel: `Switch ${items.length}`,
    tone: "warning",
  });
  if (!ok) return;
  await act(async () => {
    const r = await api.convertActivate({ confirm: true, items: items.map((s) => ({ mcc_tag: s.mcc_tag, loaded_sound_sha256: s.token })) });
    return `Switched ${r.switched?.length ?? 0} sound(s).`;
  });
}

async function act(op: () => Promise<string>) {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    message.value = await op();
    picked.value = [];
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <section class="take-sets-view">
    <PageHeader title="Take sets" :icon="Layers">
      <button type="button" class="icon-label" :disabled="busy" @click="refresh">
        <RefreshCw :size="15" aria-hidden="true" /> Check again
      </button>
    </PageHeader>
    <p class="note">
      Sounds with several Spain takes. For mono sounds, the takes you already matched can become
      one <strong>replacement set</strong>: the sound plays the set's takes instead of Spain's, and equal selections
      (same recording, language and recipe) become one take. A sound with a subtitle entry gets one subtitle for the
      whole set, approved on its own before the switch. This list is a preview: nothing changes until you stage,
      approve and switch.
    </p>

    <StateMessage v-if="!inv && !error" kind="loading">Previewing every multi-take sound…</StateMessage>
    <StateMessage v-if="message" kind="success" class="small">{{ message }}</StateMessage>
    <StateMessage v-if="error" kind="error" class="small">{{ error }}</StateMessage>

    <section v-if="inv" class="panel" data-testid="take-sets">
      <PanelHeader :title="`${inv.counts.multi_take_sounds ?? 0} multi-take sounds · ${inv.counts.own_sets_single_take ?? 0} own sets on single-take sounds`" :icon="Layers" />
      <div class="row filters" role="group" aria-label="Filter by status">
        <button v-for="k in ORDER" :key="k" type="button" class="small-button" :class="{ on: filter === k }"
                :data-testid="`filter-${k}`" :title="STATUS[k].help" @click="filter = filter === k ? '' : k">
          {{ STATUS[k].label }} <span class="count">{{ countOf(k) }}</span>
        </button>
        <span class="small muted">{{ inv.counts.untouched ?? 0 }} untouched (no decision yet)</span>
      </div>

      <div v-if="canWrite" class="row">
        <button type="button" class="icon-label" :disabled="busy || !pickedReady.length" data-testid="bulk-stage" @click="stage">
          <Layers :size="15" aria-hidden="true" /> Stage {{ pickedReady.length }} ready
        </button>
        <button type="button" class="icon-label" :disabled="busy || !pickedSwitch.length" data-testid="bulk-activate" @click="activate">
          <Shuffle :size="15" aria-hidden="true" /> Switch {{ pickedSwitch.length }} staged
        </button>
        <span class="small muted">Only ready sounds can be staged here, and only staged sounds whose takes are all approved can be switched.</span>
      </div>

      <div v-if="shown.length" class="table-frame"><table>
        <thead>
          <tr>
            <th v-if="canWrite"><input type="checkbox" :checked="allShownPicked" aria-label="Pick every listed sound" data-testid="pick-all" @change="toggleAll" /></th>
            <th>Sound</th><th>Status</th><th>Summary</th><th>Needs review</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in shown" :key="s.mcc_tag" :data-sound="s.mcc_tag">
            <td v-if="canWrite"><input v-if="pickable(s)" v-model="picked" type="checkbox" :value="s.mcc_tag" :aria-label="`Pick ${s.tag_name}`" /></td>
            <td class="mono small">{{ name(s.mcc_tag) }}<br /><span class="muted">{{ s.level }}</span></td>
            <td>
              <StatusBadge :label="STATUS[s.status]?.label ?? s.status" :tone="STATUS[s.status]?.tone ?? 'muted'" />
              <span v-if="s.single_take" class="small muted"> single take</span>
            </td>
            <td class="small">
              {{ s.summary }}
              <template v-if="s.status === 'staged'"> · {{ s.takes_approved }}/{{ s.takes_total }} approved</template>
              <template v-if="s.reason"> · {{ s.reason }}</template>
            </td>
            <td class="small">
              <span v-for="i in s.issues" :key="`${i.code}-${i.slot_id}`" class="issue" :class="i.severity">{{ i.code }}<template v-if="i.slot_id"> ({{ i.slot_id }})</template></span>
            </td>
            <td>
              <RouterLink :to="{ path: '/match', query: { level: s.level, slot: s.first_slot_id } }" class="icon-label small" title="Open the sound's first take in Matching">
                <ExternalLink :size="14" aria-hidden="true" /> Open
              </RouterLink>
            </td>
          </tr>
        </tbody>
      </table></div>
      <StateMessage v-else kind="empty">No sound with this status.</StateMessage>
    </section>
  </section>
</template>

<style scoped>
.filters .on {
  border-color: var(--frame, currentColor);
  font-weight: 600;
}
.count {
  opacity: 0.75;
  margin-left: 0.25rem;
}
.issue {
  display: inline-block;
  margin: 0 0.35rem 0.15rem 0;
}
.issue.blocked {
  color: var(--bad, #c0392b);
}
.issue.review {
  color: var(--warn, #b7791f);
}
</style>
