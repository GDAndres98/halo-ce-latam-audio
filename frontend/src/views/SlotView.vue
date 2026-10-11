<script setup lang="ts">
import { ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { api, audioUrl } from "../api/client";
import AudioButton from "../components/AudioButton.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { SlotDetail } from "../api/types";

const props = defineProps<{ id: string }>();

const slot = ref<SlotDetail | null>(null);
const error = ref("");

async function load(id: string) {
  slot.value = null;
  error.value = "";
  try {
    slot.value = await api.slot(id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

watch(() => props.id, load, { immediate: true });

// Approved decisions are green, drafts amber, rework red; undecided stays grey.
const tone = (s: string) => (s === "approved" ? "ok" : s === "draft" ? "warn" : s === "needs_rework" ? "bad" : "muted");
</script>

<template>
  <section v-if="slot">
    <p><RouterLink :to="{ name: 'dialogues', query: { level: slot.level } }">← Dialogues</RouterLink></p>
    <h1>{{ slot.tag_name }}</h1>
    <p class="muted small mono">{{ slot.slot_id }} · {{ slot.mcc_tag }} · speaker: {{ slot.speaker_from_name || "—" }}</p>

    <h2>Recordings</h2>
    <div class="row">
      <AudioButton :url="audioUrl.mcc(slot.level, 'spanish', slot.spanish.index)"
                   :label="`Spain ${slot.spanish.duration_s.toFixed(2)} s`" />
      <AudioButton v-for="(en, i) in slot.english" :key="en.index"
                   :url="audioUrl.mcc(slot.level, 'english', en.index)"
                   :label="`English${slot.english.length > 1 ? ' #' + (i + 1) : ''} ${en.duration_s.toFixed(2)} s`" />
    </div>

    <h2>Campaign Evolved candidates</h2>
    <p v-if="!slot.mapping || !slot.mapping.match.ce_line_refs.length" class="muted">
      No CE line is matched to this line yet.
    </p>
    <div v-else class="row">
      <AudioButton v-for="ref in slot.mapping.match.ce_line_refs" :key="ref"
                   :url="audioUrl.ce(ref, 'Spanish(Mexico)')" :label="`es-MX · ${ref}`" />
    </div>

    <h2>Decision</h2>
    <div class="row">
      <StatusBadge :label="`match: ${slot.mapping?.match.status ?? 'unreviewed'}`"
                   :tone="slot.mapping?.match.status === 'matched' ? 'ok' : 'muted'" />
      <StatusBadge :label="`audio: ${slot.mapping?.audio.status ?? 'none'}`" :tone="tone(slot.mapping?.audio.status ?? 'none')" />
      <StatusBadge :label="`subtitle: ${slot.mapping?.subtitle.status ?? 'none'}`" :tone="tone(slot.mapping?.subtitle.status ?? 'none')" />
      <StatusBadge v-if="slot.mapping?.radio_effect.needed" label="needs radio effect" tone="warn" />
    </div>
    <p v-if="slot.mapping?.notes" class="notes">{{ slot.mapping.notes }}</p>

    <h2>Subtitles in the game</h2>
    <dl class="subs">
      <template v-for="(text, key) in slot.mcc_subtitles" :key="key">
        <dt>{{ key }}</dt>
        <dd>{{ text ?? "—" }}</dd>
      </template>
    </dl>

    <p class="note">
      This page is read-only. Matching, approvals and edits are still on the
      <a href="http://127.0.0.1:8765/" target="_blank" rel="noopener">classic page</a> until this screen covers them.
    </p>
  </section>
  <p v-else-if="error" class="error">{{ error }}</p>
  <p v-else class="muted">Loading…</p>
</template>
