// Keyboard shortcuts for the matching workflow.
//
// Shortcuts are single keys ("m", "j", "[") or a modifier plus key ("ctrl+s"). They never fire while
// the user is typing in a field, so typing a subtitle cannot play audio or change the selection. The one
// exceptions are Ctrl+S (save) and Ctrl+Enter (save and next); Ctrl+Z in a field stays the field's own undo.
// Shortcuts never approve anything: approval is always a button press with a confirmation.

import { onBeforeUnmount, onMounted } from "vue";

export type ShortcutMap = Record<string, () => void>;

const WHILE_TYPING = new Set(["ctrl+s", "ctrl+enter"]);

export function useShortcuts(shortcuts: ShortcutMap) {
  // Names are compared in lower case, so "ArrowDown" and "arrowdown" are the same binding.
  const actions = Object.fromEntries(Object.entries(shortcuts).map(([name, action]) => [name.toLowerCase(), action]));
  const onKeyDown = (event: KeyboardEvent) => {
    const name = shortcutName(event);
    const action = actions[name];
    if (!action) return;
    // A confirmation dialog owns the keyboard while it is open (Space and Enter press its buttons).
    if (document.querySelector("dialog[open]")) return;
    if (isTyping(event.target) && !WHILE_TYPING.has(name)) return;
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
