<script setup lang="ts">
// A "Keyboard shortcuts" button that opens the list of the matching keys in a dialog. While the dialog is
// open the shortcuts themselves are paused (see useShortcuts); Esc, the Close button or a click outside
// closes it.

import { Keyboard, X } from "lucide-vue-next";
import { ref } from "vue";

const dialog = ref<HTMLDialogElement | null>(null);

/** Each row: the keys (alternatives, each a combination of key caps), what they do, and how the
 * alternatives are joined ("/" by default, "–" for a range). */
const GROUPS: { title: string; rows: { keys: string[][]; action: string; range?: boolean }[] }[] = [
  {
    title: "Lines and recordings",
    rows: [
      { keys: [["J"], ["K"]], action: "Next / previous MCC line" },
      { keys: [["U"]], action: "Next unmatched line" },
      { keys: [["Space"], ["M"]], action: "Play Spain's recording" },
      { keys: [["1"], ["9"]], action: "Play candidates 1 to 9 (plays only, selects nothing)", range: true },
      { keys: [["↑"], ["↓"]], action: "Move the candidate highlight" },
      { keys: [["S"]], action: "Use the highlighted recording" },
      { keys: [["E"], ["N"]], action: "Play the highlighted (or chosen) recording in es-MX / English" },
      { keys: [["/"], ["\\"]], action: "Search MCC lines / candidates" },
    ],
  },
  {
    title: "Compare and edit",
    rows: [
      { keys: [["A"]], action: "A / B: switch between original and replacement" },
      { keys: [["B"]], action: "Play A, then B" },
      { keys: [["W"]], action: "Play or pause the editing waveform" },
      { keys: [["T"], ["X"]], action: "Trim to the selection / cut the selection" },
      { keys: [["Ctrl", "Z"]], action: "Undo the last edit" },
      { keys: [["Esc"]], action: "Stop playback" },
    ],
  },
  {
    title: "Save",
    rows: [
      { keys: [["Ctrl", "S"]], action: "Save the draft" },
      { keys: [["Ctrl", "Enter"]], action: "Save and open the next unmatched line" },
    ],
  },
];

function open() {
  dialog.value?.showModal();
}

function close() {
  dialog.value?.close();
}

/** A click on the backdrop (outside the dialog's box) closes it. */
function onClick(event: MouseEvent) {
  if (event.target === dialog.value) close();
}
</script>

<template>
  <button type="button" class="icon-label" aria-haspopup="dialog" data-testid="shortcuts-button" @click="open">
    <Keyboard :size="15" aria-hidden="true" /> Keyboard shortcuts
  </button>
  <dialog
    ref="dialog"
    class="confirm-dialog shortcuts-dialog"
    aria-labelledby="shortcuts-title"
    data-testid="shortcuts-dialog"
    @click="onClick"
  >
    <header class="panel-head">
      <h2 id="shortcuts-title"><Keyboard :size="16" aria-hidden="true" /> Keyboard shortcuts</h2>
    </header>
    <div class="body">
      <p class="small muted">Not while typing in a field (except the Save keys). Approval has no shortcut.</p>
      <section v-for="group in GROUPS" :key="group.title">
        <h3>{{ group.title }}</h3>
        <dl class="shortcut-list">
          <template v-for="row in group.rows" :key="row.action">
            <dt>
              <template v-for="(combo, i) in row.keys" :key="i">
                <span v-if="i > 0" class="muted">{{ row.range ? "–" : " / " }}</span>
                <template v-for="(key, j) in combo" :key="key">
                  <span v-if="j > 0">+</span><kbd>{{ key }}</kbd>
                </template>
              </template>
            </dt>
            <dd>{{ row.action }}</dd>
          </template>
        </dl>
      </section>
    </div>
    <footer class="action-band">
      <button type="button" class="primary icon-label" autofocus @click="close">
        <X :size="15" aria-hidden="true" /> Close
      </button>
    </footer>
  </dialog>
</template>
