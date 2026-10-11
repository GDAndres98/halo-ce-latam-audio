<script setup lang="ts">
// A vertical divider between two panels. Drag it with the mouse or a finger; or focus it and use the
// arrow keys (Shift for bigger steps). It is announced as a separator with its current width.

import { PANEL_LIMITS, type PanelWidths } from "./workspaceLayout";

const props = defineProps<{ side: keyof PanelWidths; width: number; dragging: boolean }>();
const emit = defineEmits<{
  dragStart: [event: PointerEvent];
  step: [direction: -1 | 1, coarse: boolean];
}>();

const limits = PANEL_LIMITS[props.side];
const label = props.side === "left" ? "Resize the MCC lines panel" : "Resize the candidates panel";

function onKey(event: KeyboardEvent) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  emit("step", event.key === "ArrowLeft" ? -1 : 1, event.shiftKey);
}
</script>

<template>
  <div
    class="split-handle"
    :class="[`side-${side}`, { dragging }]"
    role="separator"
    aria-orientation="vertical"
    :aria-label="label"
    :aria-valuenow="Math.round(width)"
    :aria-valuemin="limits.min"
    :aria-valuemax="limits.max"
    tabindex="0"
    :title="`${label} (drag, or use the arrow keys)`"
    @pointerdown="emit('dragStart', $event)"
    @keydown="onKey"
  >
    <span class="grip" aria-hidden="true"></span>
  </div>
</template>
