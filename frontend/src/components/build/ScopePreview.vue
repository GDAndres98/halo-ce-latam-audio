<script setup lang="ts">
// What a build of the selected scope would contain, from the current approved decisions (read-only; nothing
// is built). Subtitle counts come from the same planner the build uses, so a draft, a decision marked Needs
// rework, a conflict between takes or a line without a subtitle entry is shown here as excluded before you
// build.

import { Captions, FileAudio } from "lucide-vue-next";
import type { BuildPreview } from "../../api/types";
import StatusBadge from "../StatusBadge.vue";

defineProps<{ preview: BuildPreview | null; loading: boolean; error: string }>();

const CATEGORY = { excluded: "not applied", conflict: "conflict", missing_key: "no subtitle entry" } as const;
</script>

<template>
  <div class="scope-preview" data-testid="scope-preview" :aria-busy="loading">
    <p v-if="error" class="small error">{{ error }}</p>
    <template v-else-if="preview">
      <p class="small">
        <strong>{{ preview.scope }}</strong>: <span class="mono">{{ preview.levels.join(", ") }}</span>
      </p>
      <dl class="preview-counts">
        <dt><FileAudio :size="14" aria-hidden="true" /> Audio</dt>
        <dd data-testid="preview-audio">
          {{ preview.audio.replace }} approved replacement(s)
          <span class="muted">· {{ preview.audio.mute ?? 0 }} muted · {{ preview.audio.insert ?? 0 }} added takes · {{ preview.audio.keep_original }} keep Spain · {{ preview.audio.not_eligible }} not eligible</span>
        </dd>
        <dt><Captions :size="14" aria-hidden="true" /> Subtitles</dt>
        <dd data-testid="preview-subtitles">
          <span data-testid="preview-approved">{{ preview.subtitles.approved_subtitles }}</span> approved decision(s) →
          <strong data-testid="preview-entries">{{ preview.subtitles.keys_to_write }}</strong> entr{{ preview.subtitles.keys_to_write === 1 ? "y" : "ies" }}
          in SU and SP
          <span class="muted">({{ preview.subtitles.variable_length.SU ?? 0 }} SU / {{ preview.subtitles.variable_length.SP ?? 0 }} SP change length)</span>
          <span class="badges">
            <StatusBadge
              :label="`${preview.subtitles.excluded} excluded`"
              :tone="preview.subtitles.excluded ? 'warn' : 'ok'"
            />
            <StatusBadge
              :label="`${preview.subtitles.conflicts} conflict${preview.subtitles.conflicts === 1 ? '' : 's'}`"
              :tone="preview.subtitles.conflicts ? 'bad' : 'ok'"
            />
          </span>
        </dd>
      </dl>
      <details v-if="preview.subtitles.excluded_rows.length" class="excluded">
        <summary>Excluded subtitle decisions ({{ preview.subtitles.excluded_rows.length }}): these lines keep MCC's text</summary>
        <ul class="small plain">
          <li v-for="r in preview.subtitles.excluded_rows" :key="r.slot_id">
            <code>{{ r.slot_id }}</code> · {{ CATEGORY[r.category] }}: {{ r.result }}
          </li>
        </ul>
      </details>
    </template>
    <p v-else-if="loading" class="small muted">Counting approved decisions…</p>
  </div>
</template>
