<script setup lang="ts">
// One build in detail: the files it would install, the validation checks, and for a subtitle build what each
// table gets (entries written, before and after), what was excluded and why, and conflicts. Read-only.

import { Captions, FileCheck2, ScrollText, TriangleAlert } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api } from "../../api/client";
import type { BuildDetail } from "../../api/types";
import StatusBadge from "../StatusBadge.vue";

const props = defineProps<{ name: string; hasLog: boolean; levels?: string[] }>();

const detail = ref<BuildDetail | null>(null);
const error = ref("");
const log = ref<string | null>(null);
const showAll = ref(false);

const LIMIT = 40;
const written = computed(() => (showAll.value ? detail.value?.written : detail.value?.written.slice(0, LIMIT)) ?? []);
const failed = computed(() => Object.entries(detail.value?.checks ?? {}).filter(([, ok]) => !ok).map(([k]) => k));
const passed = computed(() => Object.values(detail.value?.checks ?? {}).filter(Boolean).length);
const kb = (n: number) => `${(n / 1024).toFixed(1)} KB`;
const size = (n: number) => (n > 4 * 1048576 ? `${(n / 1048576).toFixed(1)} MB` : kb(n));
const CATEGORY = { excluded: "not applied", conflict: "conflict", missing_key: "no subtitle entry" } as const;

onMounted(async () => {
  try {
    detail.value = await api.buildDetail(props.name);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
});

async function loadLog() {
  try {
    log.value = (await api.buildLog(props.name)).log;
  } catch (e) {
    log.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <div class="build-detail" data-testid="build-detail" :data-build="name">
    <p v-if="error" class="small error">{{ error }}</p>
    <template v-else-if="detail">
      <section>
        <h4><FileCheck2 :size="14" aria-hidden="true" /> Files and validation</h4>
        <p v-if="levels?.length" class="small detail-folders" data-testid="detail-folders">
          <span class="muted">Folders ({{ levels.length }}):</span> <span class="mono">{{ levels.join(", ") }}</span>
        </p>
        <ul class="small plain" data-testid="detail-files">
          <li v-for="f in detail.install_files" :key="f.install_rel">
            <code>{{ f.install_rel }}</code> ← <code>{{ f.candidate }}</code>
            <span class="muted">({{ size(f.size) }}, {{ f.growth_bytes >= 0 ? "+" : "" }}{{ f.growth_bytes.toLocaleString() }} B; {{ f.candidate_sha256.slice(0, 12) }}…)</span>
          </li>
        </ul>
        <p class="small">
          <StatusBadge :label="`${passed}/${Object.keys(detail.checks).length} checks passed`" :tone="failed.length ? 'bad' : 'ok'" />
          <span v-if="detail.not_written.length" class="muted"> Not changed: {{ detail.not_written.join(", ") }}</span>
        </p>
        <ul v-if="failed.length" class="problems small">
          <li v-for="k in failed" :key="k">{{ k }}</li>
        </ul>
      </section>

      <section v-if="detail.subtitles_enabled && detail.summary">
        <h4><Captions :size="14" aria-hidden="true" /> Subtitles</h4>
        <table class="compact" data-testid="detail-tables">
          <thead><tr><th>Table</th><th>Entries</th><th>Written</th><th>Size</th></tr></thead>
          <tbody>
            <tr v-for="(t, key) in detail.tables ?? {}" :key="key">
              <td class="mono">{{ key }}_Halo1.bin</td>
              <td>{{ t.entries }}</td>
              <td>{{ t.entries_written }}</td>
              <td class="small">{{ t.size_before.toLocaleString() }} → {{ t.size_after.toLocaleString() }} B</td>
            </tr>
          </tbody>
        </table>
        <p v-for="w in detail.warnings" :key="w" class="small warn"><TriangleAlert :size="12" aria-hidden="true" /> {{ w }}</p>
        <details data-testid="detail-written">
          <summary>Entries written ({{ detail.written.length }})</summary>
          <table class="compact">
            <thead><tr><th>Line</th><th>Before (SU)</th><th>After (SU and SP)</th></tr></thead>
            <tbody>
              <tr v-for="w in written" :key="w.key_hex">
                <td class="mono small">{{ w.mcc_tag.split("\\").pop() }}</td>
                <td class="small muted">{{ w.before.SU }}</td>
                <td class="small"><span v-if="w.text">{{ w.text }}</span><em v-else class="muted">(no subtitle)</em></td>
              </tr>
            </tbody>
          </table>
          <button v-if="!showAll && detail.written.length > LIMIT" type="button" class="small-button" @click="showAll = true">
            Show all {{ detail.written.length }}
          </button>
        </details>
        <details data-testid="detail-excluded" :open="detail.conflicts.length > 0">
          <summary>Excluded ({{ detail.excluded.length }}) and conflicts ({{ detail.conflicts.length }}): these lines keep MCC's text</summary>
          <ul class="small plain">
            <li v-for="c in detail.conflicts" :key="c.key_hex" class="error">
              Conflict <code>{{ c.key_hex }}</code> {{ c.mcc_tag.split("\\").pop() }}: {{ c.code.replace(/_/g, " ") }} ({{ c.slots.join(", ") }})
            </li>
            <li v-for="r in detail.excluded" :key="r.slot_id"><code>{{ r.slot_id }}</code> · {{ CATEGORY[r.category] }}: {{ r.result }}</li>
            <li v-if="!detail.excluded.length && !detail.conflicts.length" class="muted">none</li>
          </ul>
        </details>
      </section>

      <section>
        <button v-if="hasLog" type="button" class="icon-label small-button" @click="loadLog">
          <ScrollText :size="14" aria-hidden="true" /> Build log
        </button>
        <pre v-if="log !== null" class="log" data-testid="detail-log">{{ log }}</pre>
      </section>
    </template>
    <p v-else class="small muted">Loading…</p>
  </div>
</template>
