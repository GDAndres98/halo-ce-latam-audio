<script setup lang="ts">
// The confirmation dialog (see composables/useConfirm.ts). A modal <dialog>: the rest of the page is inert
// while it is open, Esc cancels, and the Cancel button has the focus first, so Enter alone never confirms.
import { CircleHelp, TriangleAlert, X, Check } from "lucide-vue-next";
import { nextTick, ref, watch } from "vue";
import { pendingConfirm } from "../../composables/useConfirm";

const dialog = ref<HTMLDialogElement | null>(null);
const cancelButton = ref<HTMLButtonElement | null>(null);

watch(pendingConfirm, async (pending) => {
  const el = dialog.value;
  if (!el) return;
  if (pending && !el.open) {
    el.showModal();
    await nextTick();
    cancelButton.value?.focus();
  } else if (!pending && el.open) {
    el.close();
  }
});

function answer(ok: boolean) {
  pendingConfirm.value?.answer(ok);
}
</script>

<template>
  <dialog
    ref="dialog"
    class="confirm-dialog"
    :class="`tone-${pendingConfirm?.options.tone ?? 'default'}`"
    aria-labelledby="confirm-title"
    aria-describedby="confirm-body"
    @cancel.prevent="answer(false)"
  >
    <template v-if="pendingConfirm">
      <header class="panel-head">
        <h2 id="confirm-title">
          <TriangleAlert v-if="pendingConfirm.options.tone === 'warning'" :size="16" aria-hidden="true" />
          <CircleHelp v-else :size="16" aria-hidden="true" />
          {{ pendingConfirm.options.title }}
        </h2>
      </header>
      <div id="confirm-body" class="body">{{ pendingConfirm.options.message }}</div>
      <footer class="action-band">
        <button ref="cancelButton" type="button" class="icon-label" data-confirm="no" @click="answer(false)">
          <X :size="15" aria-hidden="true" /> {{ pendingConfirm.options.cancelLabel ?? "Cancel" }}
        </button>
        <button type="button" class="primary icon-label" data-confirm="yes" @click="answer(true)">
          <Check :size="15" aria-hidden="true" /> {{ pendingConfirm.options.confirmLabel }}
        </button>
      </footer>
    </template>
  </dialog>
</template>
