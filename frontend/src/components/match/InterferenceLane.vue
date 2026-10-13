<script setup lang="ts">
// Victor 933's damaged transmission: an automation lane for the interference curve (owner prompt 45).
//
// Exclusive to the one recording the server offers it for (scripts/common/interference.py LINES); there is no
// generic automation editor. The lane draws the Campaign Evolved waveform (original timeline), the owner's 11
// phrase guides, the intensity curve and, optionally, the MCC original's interference as a dashed reference.
//
// Editing (every finished gesture is one undoable recipe change, rendered as B under "Listen and compare"):
//   Points mode  click empty space to add a point and drag it; drag a point; double-click it (or Delete) to
//                remove it; arrow keys nudge the selected point (10 ms / 0.02).
//   Draw mode    drag across the lane to paint that stretch of the curve.
//   Zoom 1-16x, scroll sideways; the selected point's time and intensity can be typed exactly.
// The transport plays the CE processed transmission, the CE original or the MCC Spain / English original from
// the cursor (click the time ruler); switching source while playing keeps the position.

import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Pause, Pencil, Play, RotateCcw, Spline, Trash2, ZoomIn, ZoomOut } from "lucide-vue-next";
import { api, audioUrl } from "../../api/client";
import type { AudioEdit, CurvePoint, InterferenceDefaults, InterferenceReference } from "../../api/types";
import { loadPeaks, type Peaks } from "../../audio/peaks";
import { CURVE, curveAt, curveMin, editedTime, sourceTime, speechDb } from "../../matching/editRecipe";

const props = defineProps<{
  edit: AudioEdit;
  info: InterferenceDefaults;
  slotId: string;
  ceRef: string;
  language: string;
  sourceUrl: string;
  duration: number;
  canEdit: boolean;
}>();
const emit = defineEmits<{
  points: [points: CurvePoint[]];
  reset: [];
  flutter: [db: number];
}>();

const HEIGHT = 220;
const RULER = 18;
const TOP = 16; // guide labels
const ZOOMS = [1, 2, 4, 8, 16];
const zoom = ref(1);
const mode = ref<"points" | "draw">("points");
const scroller = ref<HTMLDivElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const width = ref(800);
const peaks = ref<Peaks | null>(null);
const reference = ref<InterferenceReference | null>(null);
const referenceLang = ref<"off" | "spanish" | "english">("off");
const referenceError = ref("");
const selected = ref<number | null>(null);
const live = ref<CurvePoint[] | null>(null); // the points during a gesture (committed on release)
const cursor = ref(0);
const playhead = ref<number | null>(null);
const playing = ref<"processed" | "original" | "spanish" | "english" | null>(null);
const playError = ref("");

const points = computed<CurvePoint[]>(() => live.value ?? props.edit.interference?.points ?? []);
const guides = computed(() => props.edit.interference?.guides ?? props.info.guides);
const total = computed(() => props.duration || props.info.duration_s || 1);
const plotH = HEIGHT - RULER - TOP;
const xOf = (t: number) => (t / total.value) * width.value * zoom.value;
const tOf = (x: number) => Math.min(total.value, Math.max(0, (x / (width.value * zoom.value)) * total.value));
const yOf = (v: number) => TOP + (1 - v) * plotH;
const vOf = (y: number) => Math.min(1, Math.max(0, 1 - (y - TOP) / plotH));

// ---- guide status (client-side, same mapping as the server)
const guideStatus = computed(() =>
  guides.value.map((g) => {
    const min = curveMin(points.value, g.start_s, g.end_s);
    const db = speechDb(min);
    const ok = g.kind === "masked" ? db === null : db !== null && db > -12;
    return { ...g, min, db, ok };
  }),
);

// ---- data
onMounted(async () => {
  const resize = () => {
    if (scroller.value) width.value = Math.max(300, scroller.value.clientWidth);
  };
  resize();
  window.addEventListener("resize", resize);
  onBeforeUnmount(() => window.removeEventListener("resize", resize));
  peaks.value = await loadPeaks(props.sourceUrl);
  draw();
});

watch(referenceLang, async (lang) => {
  referenceError.value = "";
  reference.value = null;
  if (lang === "off") return draw();
  try {
    reference.value = await api.interferenceReference(props.slotId, lang);
  } catch (e) {
    referenceError.value = e instanceof Error ? e.message : String(e);
  }
  draw();
});
watch([points, zoom, width, guides, cursor, playhead, selected], () => draw(), { deep: true });

// ---- drawing
function css(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function draw() {
  const c = canvas.value;
  if (!c) return;
  const W = Math.round(width.value * zoom.value);
  const dpr = window.devicePixelRatio || 1;
  c.width = W * dpr;
  c.height = HEIGHT * dpr;
  c.style.width = `${W}px`;
  c.style.height = `${HEIGHT}px`;
  const g = c.getContext("2d");
  if (!g) return;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, HEIGHT);
  // bands: speech removed / ducked / bed
  g.fillStyle = "rgba(255, 90, 90, 0.10)";
  g.fillRect(0, yOf(1), W, yOf(CURVE.mask) - yOf(1));
  g.fillStyle = "rgba(255, 180, 60, 0.06)";
  g.fillRect(0, yOf(CURVE.mask), W, yOf(CURVE.speechFull) - yOf(CURVE.mask));
  g.strokeStyle = "rgba(255,255,255,0.12)";
  g.setLineDash([3, 4]);
  for (const v of [CURVE.mask, CURVE.partial, CURVE.speechFull]) {
    g.beginPath();
    g.moveTo(0, yOf(v));
    g.lineTo(W, yOf(v));
    g.stroke();
  }
  g.setLineDash([]);
  // guides
  g.font = "11px system-ui, sans-serif";
  guides.value.forEach((gd, k) => {
    const a = xOf(gd.start_s);
    const b = xOf(gd.end_s);
    g.fillStyle = gd.kind === "masked" ? "rgba(255, 80, 80, 0.16)" : "rgba(255, 190, 70, 0.14)";
    g.fillRect(a, TOP, b - a, plotH);
    g.fillStyle = gd.kind === "masked" ? "#ff8a80" : "#ffc76b";
    g.fillText(`${k + 1}`, a + 2, 12);
  });
  // waveform (mirrored around the middle of the plot)
  const pk = peaks.value;
  if (pk && pk.peaks.length) {
    g.fillStyle = "rgba(180, 210, 255, 0.35)";
    const mid = TOP + plotH / 2;
    const n = pk.peaks.length;
    for (let x = 0; x < W; x++) {
      const i0 = Math.floor((x / W) * n);
      const i1 = Math.max(i0 + 1, Math.floor(((x + 1) / W) * n));
      let m = 0;
      for (let i = i0; i < i1 && i < n; i++) m = Math.max(m, pk.peaks[i]);
      const h = (m * plotH) / 2;
      g.fillRect(x, mid - h, 1, Math.max(1, 2 * h));
    }
  }
  // MCC reference (dashed)
  const ref = reference.value;
  if (ref) {
    g.strokeStyle = css("--accent-2", "#7fe3ff");
    g.setLineDash([5, 4]);
    g.lineWidth = 1.5;
    g.beginPath();
    ref.values.forEach((v, k) => {
      const x = xOf(k * ref.frame_s);
      if (k) g.lineTo(x, yOf(v));
      else g.moveTo(x, yOf(v));
    });
    g.stroke();
    g.setLineDash([]);
  }
  // the curve: filled, coloured by what it does to the speech
  const pts = points.value;
  if (pts.length) {
    const grad = g.createLinearGradient(0, yOf(1), 0, yOf(0));
    grad.addColorStop(0, "rgba(255, 90, 90, 0.45)");
    grad.addColorStop(1 - CURVE.mask, "rgba(255, 90, 90, 0.40)");
    grad.addColorStop(1 - CURVE.partial, "rgba(255, 180, 60, 0.30)");
    grad.addColorStop(1 - CURVE.speechFull, "rgba(120, 200, 255, 0.18)");
    grad.addColorStop(1, "rgba(120, 200, 255, 0.05)");
    g.fillStyle = grad;
    g.beginPath();
    g.moveTo(0, yOf(0));
    g.lineTo(0, yOf(pts[0].v));
    for (const p of pts) g.lineTo(xOf(p.t), yOf(p.v));
    g.lineTo(W, yOf(pts[pts.length - 1].v));
    g.lineTo(W, yOf(0));
    g.closePath();
    g.fill();
    g.lineWidth = 2;
    g.strokeStyle = "#ffd28a";
    g.beginPath();
    g.moveTo(0, yOf(pts[0].v));
    for (const p of pts) g.lineTo(xOf(p.t), yOf(p.v));
    g.lineTo(W, yOf(pts[pts.length - 1].v));
    g.stroke();
    pts.forEach((p, k) => {
      g.beginPath();
      g.arc(xOf(p.t), yOf(p.v), k === selected.value ? 5.5 : 3.5, 0, Math.PI * 2);
      g.fillStyle = k === selected.value ? "#ffffff" : p.v >= CURVE.mask ? "#ff8a80" : "#ffd28a";
      g.fill();
    });
  }
  // ruler
  g.fillStyle = "rgba(0,0,0,0.35)";
  g.fillRect(0, HEIGHT - RULER, W, RULER);
  const pxPerS = W / total.value;
  const step = pxPerS > 400 ? 0.1 : pxPerS > 120 ? 0.5 : pxPerS > 40 ? 1 : 2;
  g.fillStyle = "rgba(255,255,255,0.7)";
  for (let t = 0; t <= total.value + 1e-9; t += step) {
    const x = xOf(t);
    g.fillRect(x, HEIGHT - RULER, 1, 5);
    if (Math.abs(t / (step * 2) - Math.round(t / (step * 2))) < 1e-6) g.fillText(`${+t.toFixed(1)}`, x + 2, HEIGHT - 5);
  }
  // cursor and playhead
  g.fillStyle = "#7fe3ff";
  g.fillRect(xOf(cursor.value), TOP, 1, plotH + RULER);
  if (playhead.value !== null) {
    g.fillStyle = "#ffffff";
    g.fillRect(xOf(playhead.value), 0, 2, HEIGHT);
  }
}

// ---- editing
const HIT = 8;
let gesture: { kind: "drag" | "draw"; index?: number; stroke?: CurvePoint[] } | null = null;

function local(ev: PointerEvent) {
  const r = (canvas.value as HTMLCanvasElement).getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

function hit(x: number, y: number): number | null {
  let best: number | null = null;
  let bd = HIT;
  points.value.forEach((p, k) => {
    const d = Math.hypot(xOf(p.t) - x, yOf(p.v) - y);
    if (d <= bd) {
      bd = d;
      best = k;
    }
  });
  return best;
}

function onDown(ev: PointerEvent) {
  const { x, y } = local(ev);
  (canvas.value as HTMLCanvasElement).focus();
  if (y >= HEIGHT - RULER) {
    cursor.value = tOf(x);
    if (playing.value) void play(playing.value);
    return;
  }
  if (!props.canEdit) return;
  (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
  if (mode.value === "draw") {
    gesture = { kind: "draw", stroke: [{ t: tOf(x), v: vOf(y) }] };
    return;
  }
  const k = hit(x, y);
  const pts = points.value.map((p) => ({ ...p }));
  if (k !== null) {
    selected.value = k;
    live.value = pts;
    gesture = { kind: "drag", index: k };
    return;
  }
  const t = tOf(x);
  const at = pts.findIndex((p) => p.t > t);
  const index = at < 0 ? pts.length : at;
  if ((index > 0 && t - pts[index - 1].t < CURVE.minSpacing) || (index < pts.length && pts[index].t - t < CURVE.minSpacing)) return;
  pts.splice(index, 0, { t, v: vOf(y) });
  live.value = pts;
  selected.value = index;
  gesture = { kind: "drag", index };
}

function onMove(ev: PointerEvent) {
  if (!gesture) return;
  const { x, y } = local(ev);
  if (gesture.kind === "draw") {
    gesture.stroke?.push({ t: tOf(x), v: vOf(y) });
    const s = [...(gesture.stroke ?? [])].sort((a, b) => a.t - b.t);
    live.value = painted(props.edit.interference?.points ?? [], s);
    return;
  }
  const pts = (live.value ?? []).map((p) => ({ ...p }));
  const k = gesture.index as number;
  const lo = k > 0 ? pts[k - 1].t + CURVE.minSpacing : 0;
  const hi = k < pts.length - 1 ? pts[k + 1].t - CURVE.minSpacing : total.value;
  pts[k] = { t: Math.min(hi, Math.max(lo, tOf(x))), v: vOf(y) };
  live.value = pts;
}

/** The curve with the painted stretch replacing whatever was under it (samples kept >= 20 ms apart). */
function painted(base: CurvePoint[], stroke: CurvePoint[]): CurvePoint[] {
  if (!stroke.length) return base;
  const a = stroke[0].t;
  const b = stroke[stroke.length - 1].t;
  const kept: CurvePoint[] = [];
  for (const p of stroke) if (!kept.length || p.t - kept[kept.length - 1].t >= 0.02) kept.push(p);
  return [...base.filter((p) => p.t < a - CURVE.minSpacing || p.t > b + CURVE.minSpacing), ...kept].sort((p, q) => p.t - q.t);
}

function onUp() {
  if (!gesture) return;
  gesture = null;
  if (live.value) emit("points", live.value);
  live.value = null;
}

function removeAt(k: number) {
  if (!props.canEdit || points.value.length <= 2) return;
  emit("points", points.value.filter((_, i) => i !== k));
  selected.value = null;
}

function onDouble(ev: MouseEvent) {
  const r = (canvas.value as HTMLCanvasElement).getBoundingClientRect();
  const k = hit(ev.clientX - r.left, ev.clientY - r.top);
  if (k !== null) removeAt(k);
}

function onKey(ev: KeyboardEvent) {
  const k = selected.value;
  if (k === null || !props.canEdit) return;
  const p = points.value[k];
  if (!p) return;
  const move = (dt: number, dv: number) => {
    ev.preventDefault();
    ev.stopPropagation();
    const pts = points.value.map((q) => ({ ...q }));
    const lo = k > 0 ? pts[k - 1].t + CURVE.minSpacing : 0;
    const hi = k < pts.length - 1 ? pts[k + 1].t - CURVE.minSpacing : total.value;
    pts[k] = { t: Math.min(hi, Math.max(lo, p.t + dt)), v: Math.min(1, Math.max(0, p.v + dv)) };
    emit("points", pts);
  };
  if (ev.key === "Delete" || ev.key === "Backspace") {
    ev.preventDefault();
    ev.stopPropagation();
    removeAt(k);
  } else if (ev.key === "ArrowLeft") move(-0.01, 0);
  else if (ev.key === "ArrowRight") move(0.01, 0);
  else if (ev.key === "ArrowUp") move(0, 0.02);
  else if (ev.key === "ArrowDown") move(0, -0.02);
}

function setSelected(field: "t" | "v", event: Event) {
  const k = selected.value;
  const input = event.target as HTMLInputElement;
  const value = Number(input.value);
  if (k === null || !Number.isFinite(value)) return;
  emit("points", points.value.map((p, i) => (i === k ? { ...p, [field]: value } : p)));
}

function setZoom(z: number) {
  const el = scroller.value;
  const centre = el ? (el.scrollLeft + el.clientWidth / 2) / (width.value * zoom.value) : 0;
  zoom.value = z;
  requestAnimationFrame(() => {
    if (el) el.scrollLeft = centre * width.value * z - el.clientWidth / 2;
  });
}

// ---- transport
const player = new Audio();
let raf = 0;
let playingEdit: AudioEdit | null = null;

function tick() {
  if (!playing.value) return;
  const t = player.currentTime;
  playhead.value = playing.value === "processed" && playingEdit ? sourceTime(playingEdit, t, total.value) : t;
  raf = requestAnimationFrame(tick);
}

async function play(source: NonNullable<typeof playing.value>) {
  playError.value = "";
  const from = playhead.value ?? cursor.value;
  let url: string;
  let start = from;
  try {
    if (source === "processed") {
      const r = await api.editPreview({ slot_id: props.slotId, ce_line_ref: props.ceRef, language: props.language, edit: props.edit });
      url = r.urls.encoded;
      playingEdit = JSON.parse(JSON.stringify(props.edit)) as AudioEdit;
      start = editedTime(playingEdit, from);
    } else if (source === "original") {
      url = props.sourceUrl;
    } else {
      const mcc = props.info.mcc;
      const index = mcc ? (source === "spanish" ? mcc.spanish : mcc.english) : null;
      if (!mcc || index === null || index === undefined) throw new Error(`no MCC ${source} recording`);
      url = audioUrl.mcc(mcc.level, source, index);
    }
  } catch (e) {
    playError.value = e instanceof Error ? e.message : String(e);
    return;
  }
  cancelAnimationFrame(raf);
  if (player.src !== new URL(url, location.href).href) player.src = url;
  player.currentTime = Math.max(0, start);
  playing.value = source;
  try {
    await player.play();
  } catch (e) {
    playing.value = null;
    playError.value = e instanceof Error ? e.message : String(e);
    return;
  }
  raf = requestAnimationFrame(tick);
}

function stop() {
  player.pause();
  cancelAnimationFrame(raf);
  if (playhead.value !== null) cursor.value = playhead.value;
  playing.value = null;
  playhead.value = null;
}
player.addEventListener("ended", stop);
onBeforeUnmount(stop);

const sources = [
  { id: "processed", label: "CE processed" },
  { id: "original", label: "CE original" },
  { id: "spanish", label: "MCC Spain" },
  { id: "english", label: "MCC English" },
] as const;
</script>

<template>
  <section class="radio-filter interference" aria-label="Transmission interference" data-testid="interference">
    <header class="radio-head">
      <h4><Spline :size="14" aria-hidden="true" /> Transmission interference</h4>
      <span class="small muted">Victor 933 only. Shape the interference like an automation envelope; times are on the original recording.</span>
    </header>

    <div class="lane-toolbar" role="toolbar" aria-label="Interference curve">
      <span class="segmented" role="group" aria-label="Editing mode">
        <button type="button" class="icon-label small-button" :aria-pressed="mode === 'points'" :disabled="!canEdit" @click="mode = 'points'">
          <Spline :size="14" aria-hidden="true" /> Points
        </button>
        <button type="button" class="icon-label small-button" :aria-pressed="mode === 'draw'" :disabled="!canEdit" @click="mode = 'draw'">
          <Pencil :size="14" aria-hidden="true" /> Draw
        </button>
      </span>
      <span class="segmented" role="group" aria-label="Zoom">
        <button type="button" class="icon-label small-button" aria-label="Zoom out" :disabled="zoom === ZOOMS[0]" @click="setZoom(ZOOMS[ZOOMS.indexOf(zoom) - 1])">
          <ZoomOut :size="14" aria-hidden="true" />
        </button>
        <span class="small mono" data-testid="lane-zoom">{{ zoom }}×</span>
        <button type="button" class="icon-label small-button" aria-label="Zoom in" :disabled="zoom === ZOOMS[ZOOMS.length - 1]" @click="setZoom(ZOOMS[ZOOMS.indexOf(zoom) + 1])">
          <ZoomIn :size="14" aria-hidden="true" />
        </button>
      </span>
      <label class="inline small">MCC reference
        <select v-model="referenceLang" aria-label="MCC reference overlay">
          <option value="off">Off</option>
          <option value="spanish">Spain (dashed)</option>
          <option value="english">English (dashed)</option>
        </select>
      </label>
      <label class="inline small">Flutter (dB)
        <input
          :value="edit.interference?.flutter_db ?? 0" type="number" min="0" max="6" step="0.5" :disabled="!canEdit"
          aria-label="Static flutter (dB)" @change="emit('flutter', Number(($event.target as HTMLInputElement).value))"
        />
      </label>
      <button type="button" class="icon-label small-button" :disabled="!canEdit" title="Regenerate the curve from the 11 phrase guides" @click="emit('reset')">
        <RotateCcw :size="14" aria-hidden="true" /> Reset curve
      </button>
    </div>

    <div ref="scroller" class="lane-scroller">
      <canvas
        ref="canvas" class="lane-canvas" :class="{ drawing: mode === 'draw' }" tabindex="0" data-testid="interference-lane"
        aria-label="Interference curve: click to add a point, drag to move, double-click or Delete to remove"
        @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp" @dblclick="onDouble" @keydown="onKey"
      ></canvas>
    </div>
    <p v-if="referenceError" class="error small">{{ referenceError }}</p>

    <div class="lane-row">
      <span class="segmented" role="group" aria-label="Play from the cursor">
        <button
          v-for="s in sources" :key="s.id" type="button" class="icon-label small-button" :aria-pressed="playing === s.id"
          :data-testid="`lane-play-${s.id}`" @click="play(s.id)"
        >
          <Play :size="13" aria-hidden="true" /> {{ s.label }}
        </button>
        <button type="button" class="icon-label small-button" :disabled="!playing" aria-label="Stop" @click="stop">
          <Pause :size="13" aria-hidden="true" />
        </button>
      </span>
      <span class="small muted">Cursor {{ cursor.toFixed(2) }} s (click the time ruler). MCC is on its own timeline.</span>
      <template v-if="selected !== null && points[selected]">
        <label class="inline small">Point time (s)
          <input :value="points[selected].t" type="number" step="0.01" :disabled="!canEdit" aria-label="Selected point time (s)" @change="setSelected('t', $event)" />
        </label>
        <label class="inline small">Intensity
          <input :value="points[selected].v" type="number" min="0" max="1" step="0.01" :disabled="!canEdit" aria-label="Selected point intensity" @change="setSelected('v', $event)" />
        </label>
        <button type="button" class="icon-label small-button" :disabled="!canEdit || points.length <= 2" @click="removeAt(selected)">
          <Trash2 :size="13" aria-hidden="true" /> Remove point
        </button>
      </template>
    </div>
    <p v-if="playError" class="error small">{{ playError }}</p>

    <ul class="guide-list small" aria-label="Phrase guides">
      <li v-for="(g, i) in guideStatus" :key="i" :data-kind="g.kind" :data-ok="g.ok" data-testid="interference-guide">
        <span class="mono">{{ i + 1 }}</span>
        <span>{{ g.label }}</span>
        <span class="muted">{{ g.start_s.toFixed(2) }}–{{ g.end_s.toFixed(2) }} s</span>
        <span :class="g.ok ? 'muted' : 'warn'">
          {{ g.kind === "masked"
            ? g.db === null ? "hidden" : `audible! (${g.db.toFixed(1)} dB)`
            : g.db === null ? "hidden — meant to stay understandable" : `speech ${g.db.toFixed(1)} dB` }}
        </span>
      </li>
    </ul>
    <p class="small muted">
      Bands: red = speech removed (≥ {{ CURVE.mask }}), amber = ducked under static, blue = the quiet hiss bed (≤ {{ CURVE.speechFull }}).
      Guides: red = not understandable, amber = low but understandable. Undo with Ctrl+Z; B under “Listen and compare” plays the result.
    </p>
  </section>
</template>
