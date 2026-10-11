<script setup lang="ts">
// Data: how mappings/manual_mappings.json relates to mappings/manual_mappings.db.
//
// The database is the source of truth; the JSON file is the export every save writes. When the file was
// changed outside the Studio (an editor, a git checkout or restore), the Studio refuses to read it and this
// page offers the two explicit ways out:
//   Import  the file's decisions replace the database's. A preview lists every slot and approval that would
//           change; importing needs a confirmation and uses the previewed hashes, so a file or database that
//           changed in between is refused. The database is backed up to mappings/.history/ first.
//   Export  the database is written over the file. The file it replaces is kept in mappings/.history/.
// Nothing here happens on its own, and nothing is imported at start-up.

import { computed, onMounted, ref } from "vue";
import { Database, Download, FileInput, RefreshCw, ScanSearch } from "lucide-vue-next";
import { api, ApiError } from "../api/client";
import type { DataStatus, ImportPreview, SlotSummary } from "../api/types";
import StatusBadge from "../components/StatusBadge.vue";

const status = ref<DataStatus | null>(null);
const preview = ref<ImportPreview | null>(null);
const busy = ref(false);
const error = ref("");
const message = ref("");

const STATE_TEXT: Record<DataStatus["state"], { label: string; tone: "ok" | "warn" | "bad" | "muted"; help: string }> = {
  in_sync: { label: "in sync", tone: "ok", help: "The file is exactly the database's export." },
  line_endings: {
    label: "line endings only",
    tone: "ok",
    help: "Same content with Windows line endings (for example after a git checkout). It is read as in sync; the next save writes LF again.",
  },
  external_edit: {
    label: "changed outside the Studio",
    tone: "bad",
    help: "The file's content differs from the database. The Studio will not read it until you import it or export the database over it.",
  },
  missing: { label: "file missing", tone: "warn", help: "Export the database to write the file again." },
  pending: { label: "save in progress", tone: "warn", help: "A save's JSON write did not finish; the next read finishes it." },
  not_imported: { label: "no database yet", tone: "muted", help: "The database is created from the file on first use." },
};
const stateText = computed(() => (status.value ? STATE_TEXT[status.value.state] : null));
const canImport = computed(() => status.value?.state === "external_edit" || status.value?.state === "line_endings");
const canExport = computed(() => status.value && ["external_edit", "missing", "line_endings"].includes(status.value.state));

const describe = (e: unknown) =>
  e instanceof ApiError ? `${e.message}${e.details.length ? ` (${e.details.join("; ")})` : ""}` : e instanceof Error ? e.message : String(e);

async function refresh() {
  error.value = "";
  try {
    status.value = await api.dataStatus();
  } catch (e) {
    error.value = describe(e);
  }
}

async function loadPreview() {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    preview.value = await api.dataPreviewImport();
  } catch (e) {
    preview.value = null;
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

async function runImport() {
  const p = preview.value;
  if (!p) return;
  const approvals =
    (p.approvals_added.length ? `\nApprovals added: ${p.approvals_added.join(", ")}` : "") +
    (p.approvals_removed.length ? `\nApprovals REMOVED: ${p.approvals_removed.join(", ")}` : "");
  const ok = window.confirm(
    `Import manual_mappings.json into the database?\n\n${p.changes.length} slot(s) change.${approvals}\n\n` +
      "The database's current decisions for those slots are replaced (a backup is kept in mappings/.history/).",
  );
  if (!ok) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await api.dataImport(p.file_sha256, p.db_export_sha256);
    status.value = result.status;
    preview.value = null;
    message.value = `Imported: ${result.changed_slots} slot(s) changed. Database backup: ${result.database_backup}`;
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

async function runExport() {
  if (!status.value) return;
  const ok = window.confirm(
    "Write the database's decisions over manual_mappings.json?\n\n" +
      "Changes made to the file outside the Studio are discarded from the file (it is kept in mappings/.history/).",
  );
  if (!ok) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await api.dataExport(status.value.file_sha256);
    status.value = result.status;
    preview.value = null;
    message.value = "Exported: the file is the database's export again.";
  } catch (e) {
    error.value = describe(e);
  } finally {
    busy.value = false;
  }
}

function summary(s: SlotSummary | null): string {
  if (!s) return "—";
  return `match ${s.match}${s.ce_line_refs.length ? ` (${s.ce_line_refs.join(", ")})` : ""} · audio ${s.audio} (${s.audio_source}, rev ${s.audio_revision}) · subtitle ${s.subtitle} (${s.subtitle_source}, rev ${s.subtitle_revision})${s.radio ? " · radio" : ""}`;
}

onMounted(refresh);
</script>

<template>
  <section class="data-view">
    <h1><Database :size="22" aria-hidden="true" /> Data</h1>
    <p class="note">
      Decisions live in <code>mappings/manual_mappings.db</code>. Every save also writes
      <code>mappings/manual_mappings.json</code>, the export the build tools and git see. If that file is changed
      outside the Studio, nothing is read from it until you choose what to keep.
    </p>

    <div class="row">
      <button type="button" class="icon-label" :disabled="busy" @click="refresh">
        <RefreshCw :size="15" aria-hidden="true" /> Check again
      </button>
    </div>

    <div v-if="status && stateText" class="sync-card" data-testid="sync-status">
      <p>
        <strong>manual_mappings.json:</strong>
        <StatusBadge :label="stateText.label" :tone="stateText.tone" />
      </p>
      <p class="small">{{ stateText.help }}</p>
      <dl class="texts small">
        <dt>File SHA-256</dt><dd class="mono">{{ status.file_sha256 ?? "—" }}</dd>
        <dt>Database export</dt><dd class="mono">{{ status.db_export_sha256 ?? "—" }}</dd>
        <template v-if="status.last_import">
          <dt>Last import</dt>
          <dd>{{ status.last_import.at }} · {{ status.last_import.changed_slots }} slot(s) · backup {{ status.last_import.database_backup }}</dd>
        </template>
      </dl>
      <div class="row">
        <button type="button" class="icon-label" :disabled="busy || !canImport" @click="loadPreview">
          <ScanSearch :size="16" aria-hidden="true" /> Preview import from JSON
        </button>
        <button type="button" class="icon-label" :disabled="busy || !canExport" @click="runExport">
          <Download :size="16" aria-hidden="true" /> Export database to JSON
        </button>
      </div>
    </div>

    <p v-if="message" class="ok small" role="status">{{ message }}</p>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>

    <section v-if="preview" class="block" aria-label="Import preview" data-testid="import-preview">
      <h2>Import preview</h2>
      <p class="small">
        {{ preview.changes.length }} slot(s) would change · file {{ preview.slots_in_file }} slots, database
        {{ preview.slots_in_database }} · line endings {{ preview.line_endings }}
        <span v-if="preview.pins_change" class="warn"> · the build pins change</span>
      </p>
      <p v-if="preview.approvals_added.length" class="small warn">Approvals added: {{ preview.approvals_added.join(", ") }}</p>
      <p v-if="preview.approvals_removed.length" class="small bad">Approvals removed: {{ preview.approvals_removed.join(", ") }}</p>
      <table v-if="preview.changes.length">
        <thead><tr><th>Slot</th><th>Change</th><th>Database now</th><th>File (would become)</th></tr></thead>
        <tbody>
          <tr v-for="c in preview.changes" :key="c.mapping_id">
            <td class="mono small">{{ c.slot_id }}<br /><span class="muted">{{ c.mapping_id }}</span></td>
            <td class="small">{{ c.kind }}: {{ c.fields.join(", ") }}</td>
            <td class="small">{{ summary(c.database) }}</td>
            <td class="small">{{ summary(c.file) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="small muted">No decision changes: only the file's bytes differ.</p>
      <div class="row">
        <button type="button" class="primary icon-label" :disabled="busy" @click="runImport">
          <FileInput :size="16" aria-hidden="true" /> Import these changes
        </button>
        <button type="button" :disabled="busy" @click="preview = null">Cancel</button>
      </div>
    </section>
  </section>
</template>
