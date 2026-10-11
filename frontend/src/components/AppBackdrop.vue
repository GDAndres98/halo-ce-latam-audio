<script setup lang="ts">
// The atmosphere behind every screen, after the original's menu backdrop (a ring in orbit, a planet's rim, a
// field of stars and the holographic reticle behind the title). Original geometry only, no game artwork.
// One static SVG on a fixed layer: it is painted once and never takes the pointer.

// A fixed pseudo-random starfield, the same on every load (no flicker between screens).
function stars(count: number): { x: number; y: number; r: number; o: number }[] {
  let seed = 117;
  const next = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  return Array.from({ length: count }, () => ({
    x: Math.round(next() * 1600),
    y: Math.round(next() * 1000),
    r: next() < 0.9 ? 0.8 : 1.5,
    o: Math.round((0.25 + next() * 0.6) * 100) / 100,
  }));
}
const STARS = stars(110);
</script>

<template>
  <div class="backdrop" aria-hidden="true">
    <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="bd-ring" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#7fc0ff" stop-opacity="0" />
          <stop offset="0.45" stop-color="#7fc0ff" stop-opacity="0.32" />
          <stop offset="1" stop-color="#2f8cff" stop-opacity="0" />
        </linearGradient>
        <radialGradient id="bd-planet" cx="0.35" cy="0.25" r="0.8">
          <stop offset="0" stop-color="#0b2552" />
          <stop offset="1" stop-color="#01040c" />
        </radialGradient>
      </defs>

      <g fill="#cfe4ff">
        <circle v-for="(s, i) in STARS" :key="i" :cx="s.x" :cy="s.y" :r="s.r" :opacity="s.o" />
      </g>

      <!-- The ring, seen nearly edge-on. -->
      <g transform="rotate(16 1270 430)" fill="none">
        <ellipse cx="1270" cy="430" rx="95" ry="660" stroke="url(#bd-ring)" stroke-width="10" />
        <ellipse cx="1270" cy="430" rx="85" ry="645" stroke="url(#bd-ring)" stroke-width="1.5" />
      </g>

      <!-- A planet's limb, lit from behind. -->
      <circle cx="1480" cy="1420" r="640" fill="url(#bd-planet)" stroke="#4da3ff" stroke-opacity="0.35" stroke-width="2" />

      <!-- Holographic reticle behind the screen titles. -->
      <g fill="none" stroke="#4da3ff">
        <circle cx="300" cy="150" r="70" stroke-opacity="0.1" />
        <circle cx="300" cy="150" r="125" stroke-opacity="0.08" stroke-dasharray="4 10" />
        <circle cx="300" cy="150" r="190" stroke-opacity="0.06" />
        <line x1="0" y1="150" x2="1600" y2="150" stroke-opacity="0.07" />
        <line x1="300" y1="0" x2="300" y2="420" stroke-opacity="0.06" />
      </g>
    </svg>
  </div>
</template>
