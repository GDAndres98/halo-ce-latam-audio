// Keyboard shortcuts for the matching workflow.
//
// Shortcuts are single keys ("m", "j", "[") or a modifier plus key ("ctrl+s"). They never fire while
// the user is typing in a field, so typing a subtitle cannot play audio or change the selection.
// Shortcuts never approve anything: approval is always a button press with a confirmation.

import { onBeforeUnmount, onMounted } from "vue";

export type ShortcutMap = Record<string, () => void>;

export function useShortcuts(shortcuts: ShortcutMap) {
  const onKeyDown = (event: KeyboardEvent) => {
    const name = shortcutName(event);
    const action = shortcuts[name];
    if (!action) return;
    if (isTyping(event.target) && !name.startsWith("ctrl+")) return;
    event.preventDefault();
    action();
  };
  onMounted(() => window.addEventListener("keydown", onKeyDown));
  onBeforeUnmount(() => window.removeEventListener("keydown", onKeyDown));
}

/** "ctrl+s", "j", "[". Modifier keys on their own are not shortcuts. */
export function shortcutName(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.ctrlKey || event.metaKey) parts.push("ctrl");
  if (event.altKey) parts.push("alt");
  const key = event.key.toLowerCase();
  if (!["control", "shift", "alt", "meta"].includes(key)) parts.push(key);
  return parts.join("+");
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}
