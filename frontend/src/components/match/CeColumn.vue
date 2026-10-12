<script setup lang="ts">
// Right column: Campaign Evolved candidate recordings.
//
// Results stay in catalog order. Searching never selects, ranks or matches anything: the highlighted row
// (j / k) is only a cursor, and a recording becomes the replacement only when the user presses "Use this
// recording" (s).

import { ChevronsDown, CircleCheck, Library } from "lucide-vue-next";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api, ApiError, audioUrl } from "../../api/client";
import { onChange } from "../../live/changes";
import { togglePlay } from "../../audio/player";
import { useDebounced } from "../../composables/useDebounced";
import { highlightSegments } from "../../matching/text";
import type { CeLine, CeResponse } from "../../api/types";
import AudioButton from "../AudioButton.vue";
import ClipSeconds from "../ClipSeconds.vue";
import StatusBadge from "../StatusBadge.vue";
import StateMessage from "../ui/StateMessage.vue";

const props = defineProps<{ missions: string[]; slotId: string | null; focusedRef: string | null; chosenRefs: string[] }>();
const emit = defineEmits<{ focus: [ref: string]; use: [ref: string] }>();

const mission = defineModel<string>("mission", { default: "all" });
const query = defineModel<string>("query", { default: "" });
const hideUsed = defineModel<boolean>("hideUsed", { default: false });
/** "" = any, "missing" = no es-MX source subtitle, "present" = has one (the server's own values). */
const subtitles = defineModel<string>("subtitles", { default: "" });
const debouncedQuery = useDebounced(query, 250);

const PAGE = 100;
const limit = ref(PAGE);
const data = ref<CeResponse | null>(null);
const error = ref("");
const searchBox = ref<HTMLInputElement | null>(null);
let latest = 0;

async function load() {
  const request = ++latest;
  error.value = "";
  try {
    const res = await api.ce({
      mission: mission.value,
      q: debouncedQuery.value,
      limit: limit.value,
      hide_used: hideUsed.value,
      subs: subtitles.value || undefined,
      keep_slot: props.slotId ?? undefined,
    });
    if (request === latest) data.value = res;
  } catch (e) {
    if (request === latest) error.value = e instanceof ApiError ? e.message : String(e);
  }
}

watch([mission, debouncedQuery, hideUsed, subtitles], () => {
  limit.value = PAGE;
  load();
});
// The hidden set depends on the selected MCC line (its own matches are never hidden from it).
// The list depends on the selected line only through "hide recordings already used" (keep_slot); otherwise
// switching lines keeps the same candidates and search, with no request.
watch(() => props.slotId, () => {
  if (hideUsed.value) load();
});
onMounted(load);

// "Hide recordings already used" depends on every line's decision: reload it when another computer saves.
let liveTimer: ReturnType<typeof setTimeout> | undefined;
const stopChanges = onChange(() => {
  if (!hideUsed.value) return;
  clearTimeout(liveTimer);
  liveTimer = setTimeout(load, 400);
});
onBeforeUnmount(() => {
  clearTimeout(liveTimer);
  stopChanges();
});

function showMore() {
  limit.value += PAGE;
  load();
}

/** Moves the highlighted row (j / k). It does not select anything. */
function move(delta: number) {
  const lines = data.value?.lines ?? [];
  if (!lines.length) return;
  const index = lines.findIndex((l) => l.ce_line_ref === props.focusedRef);
  const next = index === -1 ? lines[0] : lines[Math.min(Math.max(index + delta, 0), lines.length - 1)];
  emit("focus", next.ce_line_ref);
  document.getElementById(`ce-${next.ce_line_ref}`)?.scrollIntoView({ block: "nearest" });
}

function focusSearch() {
  searchBox.value?.focus();
}

/** Plays the es-MX recording of the n-th visible candidate (keys 1 to 9). Plays only; selects nothing. */
function playNth(index: number) {
  const line = data.value?.lines[index];
  if (line && line.media["Spanish(Mexico)"]?.count) togglePlay(audioUrl.ce(line.ce_line_ref, "Spanish(Mexico)"));
}

defineExpose({ move, focusSearch, playNth });

const terms = (): string[] => data.value?.terms ?? [];
const hasText = (line: CeLine, culture: string) => Boolean(line.subtitles[culture]?.text);
const spanish = (line: CeLine) => line.subtitles["es-MX"]?.text ?? null;
const english = (line: CeLine) => line.subtitles["en"]?.text ?? null;
</script>

<template>
  <section class="column ce">
    <h2>
      <Library :size="16" aria-hidden="true" /> Campaign Evolved candidates
      <span v-if="data" class="count">{{ data.lines.length }}/{{ data.total }}</span>
    </h2>
    <div class="controls">
      <label>Mission
        <select v-model="mission">
          <option value="all">All missions</option>
          <option v-for="m in missions" :key="m" :value="m">{{ m }}</option>
        </select>
      </label>
      <label class="wide">Search ID, English or LATAM Spanish text
        <input ref="searchBox" v-model="query" type="search" placeholder="Partial words and &quot;phrases&quot; work (\)" />
      </label>
      <label>es-MX subtitle
        <select v-model="subtitles">
          <option value="">Any</option>
          <option value="present">Has one</option>
          <option value="missing">None (no source subtitle)</option>
        </select>
      </label>
      <label class="check"><input v-model="hideUsed" type="checkbox" /> Hide recordings already used elsewhere</label>
    </div>

    <StateMessage v-if="error" kind="error">{{ error }}</StateMessage>
    <StateMessage v-else-if="!data" kind="loading">Loading recordings…</StateMessage>
    <p v-if="data" class="muted small list-meta">
      {{ data.lines.length }} of {{ data.total }} recordings
      <span v-if="data.hidden_used"> · {{ data.hidden_used }} hidden as already used</span>
    </p>

    <ul v-if="data" class="rows" role="listbox" aria-label="Campaign Evolved recordings">
      <li
        v-for="line in data.lines"
        :id="`ce-${line.ce_line_ref}`"
        :key="line.ce_line_ref"
        class="row-item"
        :class="{ focused: line.ce_line_ref === focusedRef, chosen: chosenRefs.includes(line.ce_line_ref) }"
        role="option"
        :aria-selected="line.ce_line_ref === focusedRef"
        @click="emit('focus', line.ce_line_ref)"
      >
        <div class="line-head">
          <strong class="tag mono small">{{ line.ce_line_ref }}</strong>
          <span class="play-group">
            <ClipSeconds
              :url="audioUrl.ce(line.ce_line_ref, 'Spanish(Mexico)')"
              :known="line.media['Spanish(Mexico)']?.duration_s"
              :disabled="!line.media['Spanish(Mexico)']?.count"
              :title="'Length of the es-MX recording'"
            />
            <AudioButton :url="audioUrl.ce(line.ce_line_ref, 'Spanish(Mexico)')" label="es-MX" :disabled="!line.media['Spanish(Mexico)']?.count" @click.stop />
            <AudioButton :url="audioUrl.ce(line.ce_line_ref, 'English(US)')" label="EN" :disabled="!line.media['English(US)']?.count" @click.stop />
          </span>
        </div>
        <div class="subtitles small">
          <p v-if="spanish(line)" class="es">
            <span class="culture">es-MX</span>
            <template v-for="(part, i) in highlightSegments(spanish(line) as string, terms())" :key="i">
              <mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template>
            </template>
          </p>
          <p v-else class="muted"><span class="culture">es-MX</span> No source subtitle for this recording.</p>
          <p v-if="english(line)" class="en">
            <span class="culture">EN</span>
            <template v-for="(part, i) in highlightSegments(english(line) as string, terms())" :key="i">
              <mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template>
            </template>
          </p>
        </div>
        <div class="badges">
          <StatusBadge :label="hasText(line, 'es-MX') ? 'es-MX subtitle' : 'no es-MX subtitle'" :tone="hasText(line, 'es-MX') ? 'ok' : 'warn'" />
          <StatusBadge :label="hasText(line, 'en') ? 'EN subtitle' : 'no EN subtitle'" :tone="hasText(line, 'en') ? 'ok' : 'muted'" />
          <StatusBadge v-if="line.used_by?.length" :label="`used by ${line.used_by.length}`" tone="muted" />
          <StatusBadge v-if="chosenRefs.includes(line.ce_line_ref)" label="matched here" tone="ok" />
          <button type="button" class="use icon-label primary-soft" @click.stop="emit('use', line.ce_line_ref)"><CircleCheck :size="15" aria-hidden="true" /> Use this recording (s)</button>
        </div>
      </li>
      <li v-if="!data.lines.length" class="empty-list"><StateMessage kind="empty">No recordings match.</StateMessage></li>
    </ul>

    <button v-if="data && data.lines.length < data.total" type="button" class="more icon-label" @click="showMore"><ChevronsDown :size="15" aria-hidden="true" /> Show more recordings</button>
  </section>
</template>
