// Draws the Studio's app icons (favicon, PWA icons, Apple touch icon) from one design and writes them to
// public/. Original artwork: the Studio's tilted ring (components/AppEmblem.vue) around an audio waveform, in
// the menu blues, on deep navy, inside a thin holographic frame. No Halo logo or game artwork.
//
//   npm run icons      (needs Microsoft Edge: the PNGs are rendered by the browser from the SVG)
//
// The outputs are committed, so a normal build does not need this script; run it after changing the design.

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), "..", "public");

/**
 * The icon as SVG (512 units).
 *   shape "rounded": a rounded tile with transparent corners (browser tabs, Android's "any" icon)
 *   shape "square":  full bleed, no transparency (maskable icons, iOS, which round the corners itself)
 *   scale: the artwork's size inside the tile (maskable icons keep it inside the central safe circle)
 *   frame: the thin frame inside the edge (left out where the platform crops the edge)
 */
function iconSvg({ shape = "rounded", scale = 1, frame = true } = {}) {
  const tile =
    shape === "rounded"
      ? `<rect x="8" y="8" width="496" height="496" rx="104" fill="url(#bg)"/>`
      : `<rect width="512" height="512" fill="url(#bg)"/>`;
  const frameRect = frame
    ? `<rect x="30" y="30" width="452" height="452" rx="84" fill="none" stroke="#2f8cff" stroke-opacity="0.55" stroke-width="5"/>`
    : "";
  // The waveform: nine bars, tallest in the middle, in the lit menu blue.
  const heights = [70, 120, 176, 236, 290, 236, 176, 120, 70];
  const barWidth = 26;
  const gap = 14;
  const total = heights.length * barWidth + (heights.length - 1) * gap;
  const bars = heights
    .map((h, i) => {
      const x = 256 - total / 2 + i * (barWidth + gap);
      return `<rect x="${x}" y="${256 - h / 2}" width="${barWidth}" height="${h}" rx="${barWidth / 2}" fill="url(#bar)"/>`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <radialGradient id="bg" cx="0.3" cy="0.2" r="1">
      <stop offset="0" stop-color="#0d2c66"/>
      <stop offset="0.55" stop-color="#05122e"/>
      <stop offset="1" stop-color="#01040c"/>
    </radialGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#d6f6ff"/>
      <stop offset="0.5" stop-color="#7fe3ff"/>
      <stop offset="1" stop-color="#2f8cff"/>
    </linearGradient>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="7" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  ${tile}
  ${frameRect}
  <g transform="translate(256 256) scale(${scale}) translate(-256 -256)" filter="url(#glow)">
    <g transform="rotate(-24 256 256)" fill="none" stroke-linecap="round">
      <path d="M48 256 A208 76 0 0 1 464 256" stroke="#2f8cff" stroke-width="22"/>
    </g>
    ${bars}
    <g transform="rotate(-24 256 256)" fill="none" stroke-linecap="round">
      <path d="M48 256 A208 76 0 0 0 464 256" stroke="#9fd0ff" stroke-width="26"/>
    </g>
  </g>
</svg>
`;
}

const OUTPUTS = [
  { file: "favicon.svg", svg: iconSvg({ shape: "rounded", frame: false }) },
  { file: "icons/favicon-32.png", size: 32, svg: iconSvg({ shape: "rounded", frame: false }), transparent: true },
  { file: "icons/pwa-192.png", size: 192, svg: iconSvg({ shape: "rounded" }), transparent: true },
  { file: "icons/pwa-512.png", size: 512, svg: iconSvg({ shape: "rounded" }), transparent: true },
  // Maskable: the platform crops to its own shape; the art stays inside the central 80 % circle.
  { file: "icons/maskable-192.png", size: 192, svg: iconSvg({ shape: "square", scale: 0.78, frame: false }) },
  { file: "icons/maskable-512.png", size: 512, svg: iconSvg({ shape: "square", scale: 0.78, frame: false }) },
  { file: "icons/apple-touch-icon-180.png", size: 180, svg: iconSvg({ shape: "square", scale: 0.86, frame: false }) },
];

async function main() {
  await mkdir(join(PUBLIC, "icons"), { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const out of OUTPUTS) {
      const target = join(PUBLIC, out.file);
      if (!out.size) {
        await writeFile(target, out.svg);
        console.log(`wrote ${out.file}`);
        continue;
      }
      const page = await browser.newPage({ viewport: { width: out.size, height: out.size }, deviceScaleFactor: 1 });
      const svg = out.svg.replace('width="512" height="512"', `width="${out.size}" height="${out.size}"`);
      await page.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
      await page.screenshot({ path: target, omitBackground: Boolean(out.transparent), clip: { x: 0, y: 0, width: out.size, height: out.size } });
      await page.close();
      console.log(`wrote ${out.file} (${out.size} px)`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
