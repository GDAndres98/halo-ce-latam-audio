<script setup lang="ts">
// Picks several Campaign Evolved recordings at once (es-MX), with its own search: used by "Add several takes" and by
// the line's "Replace every take of this sound" option. Nothing is ticked for the user: the search only fills the
// list. Recordings already a take of the sound are shown but cannot be ticked. Emits the ticked refs on submit.

import { ListPlus, X } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import type { CeLine } from "../../api/types";
import { useDebounced } from "../../composables/useDebounced";
import AudioButton from "../AudioButton.vue";

const props = defineProps<{
  /** Recordings that are already a take of the sound (shown, not tickable). */
  takenRefs: string[];
  /** The search the list starts from (e.g. the focused recording without its "#n"). */
  initialQuery?: string;
  canListen?: boolean;
  busy?: boolean;
  /** The submit button's text for n ticked recordings. */
  submitLabel: (n: number) => string;
  /** Show a close button (emits close). */
  closable?: boolean;
}>();
const emit = defineEmits<{ submit: [refs: string[]]; close: []; change: [refs: string[]] }>();

const LANGUAGE = "Spanish(Mexico)";
const query = ref(props.initialQuery ?? "");
const debounced = useDebounced(query, 250);
const lines = ref<CeLine[]>([]);
const total = ref(0);
const error = ref("");
const loading = ref(false);
const picked = ref<string[]>([]);
let latest = 0;

const taken = computed(() => new Set(props.takenRefs));
const hasMx = (l: CeLine) => Boolean(l.media[LANGUAGE]?.count);
const pickable = (l: CeLine) => hasMx(l) && !taken.value.has(l.ce_line_ref);
const pickableShown = computed(() => lines.value.filter(pickable));
const allShownPicked = computed(
  () => pickableShown.value.length > 0 && pickableShown.value.every((l) => picked.value.includes(l.ce_line_ref)),
);
const lineText = (l: CeLine) => l.subtitles["es-MX"]?.text ?? l.subtitles["en"]?.text ?? "";
const lineSeconds = (l: CeLine) => l.media[LANGUAGE]?.duration_s ?? null;

async function load() {
  const request = ++latest;
  error.value = "";
  loading.value = true;
  try {
    const res = await api.ce({ mission: "all", q: debounced.value, limit: 200 });
    if (request !== latest) return;
    lines.value = res.lines;
    total.value = res.total;
  } catch (e) {
    if (request === latest) error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    if (request === latest) loading.value = false;
  }
}
watch(debounced, load);
onMounted(load);
watch(picked, (p) => emit("change", [...p]));

function togglePickAll() {
  const shown = pickableShown.value.map((l) => l.ce_line_ref);
  picked.value = allShownPicked.value
    ? picked.value.filter((r) => !shown.includes(r))
    : [...picked.value, ...shown.filter((r) => !picked.value.includes(r))];
}

/** Clears the ticks (the parent calls it after a successful save). */
function clear() {
  picked.value = [];
}
defineExpose({ clear });
</script>

<template>
  <div class="picker" data-testid="take-picker">
    <div class="picker-head">
      <label>Search Campaign Evolved recordings (ID, English or LATAM Spanish text)
        <input v-model="query" type="search" placeholder="e.g. die_ass_grunt" data-testid="take-picker-search" />
      </label>
      <button v-if="closable" type="button" class="icon-only" aria-label="Close" title="Close" @click="emit('close')">
        <X :size="15" aria-hidden="true" />
      </button>
    </div>
    <p v-if="error" class="small error" role="alert">{{ error }}</p>
    <p v-else class="small muted">
      {{ loading ? "Loading…" : `${lines.length} of ${total} shown` }}<template v-if="total > lines.length">; refine the search to see the rest</template>.
      Tick the recordings to use; nothing is ticked for you.
    </p>
    <label v-if="pickableShown.length" class="check small">
      <input type="checkbox" :checked="allShownPicked" data-testid="take-picker-all" @change="togglePickAll" />
      Tick every recording shown ({{ pickableShown.length }})
    </label>
    <ul class="pick-list">
      <li v-for="l in lines" :key="l.ce_line_ref" :class="{ off: !pickable(l) }">
        <label>
          <input v-model="picked" type="checkbox" :value="l.ce_line_ref" :disabled="!pickable(l)" data-testid="take-pick" />
          <span class="take-main">
            <span class="mono small">{{ l.ce_line_ref }}</span>
            <span class="small muted">
              <template v-if="taken.has(l.ce_line_ref)">already a take · </template>
              <template v-else-if="!hasMx(l)">no es-MX recording · </template>
              <template v-if="lineSeconds(l) !== null">{{ lineSeconds(l)?.toFixed(2) }} s</template>
              <template v-if="lineText(l)"> · {{ lineText(l) }}</template>
            </span>
          </span>
        </label>
        <AudioButton v-if="canListen !== false && hasMx(l)" :url="audioUrl.ce(l.ce_line_ref, LANGUAGE)" label="es-MX" title="Listen" />
      </li>
    </ul>
    <div class="row">
      <button type="button" class="icon-label" :disabled="busy || !picked.length" data-testid="take-picker-add"
              @click="emit('submit', [...picked])">
        <ListPlus :size="15" aria-hidden="true" /> {{ submitLabel(picked.length) }}
      </button>
      <button v-if="picked.length" type="button" class="small-button" :disabled="busy" @click="clear">Clear</button>
    </div>
  </div>
</template>

<style scoped>
.picker {
  margin-top: 0.5rem;
  padding: 0.5rem;
  border: 1px solid var(--line, rgba(127, 127, 127, 0.25));
  border-radius: 6px;
  display: grid;
  gap: 0.4rem;
}
.picker-head {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
}
.picker-head label {
  flex: 1;
  display: grid;
  gap: 0.2rem;
}
.pick-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 22rem;
  overflow-y: auto;
  display: grid;
  gap: 0.2rem;
}
.pick-list li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.2rem 0.35rem;
}
.pick-list li label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.pick-list li.off {
  opacity: 0.55;
}
.pick-list li.off label {
  cursor: default;
}
.take-main {
  display: grid;
  flex: 1 1 14rem;
  min-width: 0;
}
.take-main .mono {
  overflow-wrap: anywhere;
}
</style>
