// Drag and keyboard resizing of the matching panels, with the widths saved for the next visit.
//
// While the mouse moves, only two CSS variables on the workspace element change: nothing re-renders and
// no audio is interrupted. The widths are committed (and saved) once, when the drag ends.

import { computed, onBeforeUnmount, onMounted, ref, type Ref } from "vue";
import {
  DEFAULT_WIDTHS,
  KEY_STEP_PX,
  STORAGE_KEY,
  fitWidths,
  nudge,
  readStoredWidths,
  type PanelWidths,
} from "./workspaceLayout";

function loadSaved(): PanelWidths {
  try {
    return readStoredWidths(localStorage.getItem(STORAGE_KEY)) ?? DEFAULT_WIDTHS;
  } catch {
    return DEFAULT_WIDTHS; // storage can be blocked (private windows); the layout still works
  }
}

function save(widths: PanelWidths) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(widths));
  } catch {
    // Not saved: the layout still works for this visit.
  }
}

export function useWorkspaceLayout(workspace: Ref<HTMLElement | null>) {
  const widths = ref<PanelWidths>(loadSaved());
  const dragging = ref<keyof PanelWidths | null>(null);

  const available = () => workspace.value?.clientWidth ?? window.innerWidth;

  /** Shows widths on the element as CSS variables: the stylesheet lays the grid out from them. */
  function show(next: PanelWidths) {
    const el = workspace.value;
    if (!el) return;
    el.style.setProperty("--left-w", `${next.left}px`);
    el.style.setProperty("--right-w", `${next.right}px`);
  }

  function commit(next: PanelWidths) {
    widths.value = fitWidths(next, available());
    show(widths.value);
    save(widths.value);
  }

  /** Mouse or touch drag on the divider next to `side`. */
  function startDrag(side: keyof PanelWidths, event: PointerEvent) {
    event.preventDefault();
    const handle = event.currentTarget as HTMLElement;
    handle.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = widths.value[side];
    let live = widths.value;
    dragging.value = side;

    const onMove = (e: PointerEvent) => {
      const delta = e.clientX - startX;
      const wanted = side === "left" ? startWidth + delta : startWidth - delta;
      live = fitWidths({ ...widths.value, [side]: wanted }, available());
      show(live);
    };
    const onEnd = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onEnd);
      handle.removeEventListener("pointercancel", onEnd);
      dragging.value = null;
      commit(live);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onEnd);
    handle.addEventListener("pointercancel", onEnd);
  }

  /** Keyboard step on a divider. `direction` is the way the divider moves: +1 is to the right. */
  function step(side: keyof PanelWidths, direction: -1 | 1, coarse: boolean) {
    commit(nudge(widths.value, side, direction * KEY_STEP_PX * (coarse ? 4 : 1)));
  }

  function reset() {
    commit(DEFAULT_WIDTHS);
  }

  // Each render uses the current width; the grid adapts when the browser window changes size.
  const onResize = () => {
    widths.value = fitWidths(widths.value, available());
    show(widths.value);
  };
  onMounted(() => {
    widths.value = fitWidths(widths.value, available());
    show(widths.value);
    window.addEventListener("resize", onResize);
  });
  onBeforeUnmount(() => window.removeEventListener("resize", onResize));

  const isDefault = computed(() => widths.value.left === DEFAULT_WIDTHS.left && widths.value.right === DEFAULT_WIDTHS.right);

  return { widths, dragging, isDefault, startDrag, step, reset };
}
