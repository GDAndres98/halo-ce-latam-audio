// Confirmations, shown in the Studio's own dialog (components/ui/ConfirmDialog.vue) instead of the browser's.
//
//   if (await confirmAction({ title: "Approve audio", message: "…", confirmLabel: "Approve audio" })) { … }
//
// One dialog at a time: opening another answers the previous one with "cancel". Cancel, Esc and closing the
// dialog all answer false; only the confirm button answers true. Nothing is ever confirmed by a shortcut.

import { shallowRef } from "vue";

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** "warning" for actions that change the game install or approvals in bulk. */
  tone?: "default" | "warning";
}

export interface PendingConfirm {
  options: ConfirmOptions;
  answer: (ok: boolean) => void;
}

export const pendingConfirm = shallowRef<PendingConfirm | null>(null);

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  pendingConfirm.value?.answer(false);
  return new Promise((resolve) => {
    const entry: PendingConfirm = {
      options,
      answer: (ok) => {
        if (pendingConfirm.value === entry) pendingConfirm.value = null;
        resolve(ok);
      },
    };
    pendingConfirm.value = entry;
  });
}
