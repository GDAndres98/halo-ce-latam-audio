// Screenshots of the Studio for the README, written to docs/images/.
//
//   npm run docs:screenshots        (from frontend/; needs Microsoft Edge)
//
// Works on a disposable copy of the mapping data, like the browser tests. Unlike e2e/out/, these images are
// committed, so every element that shows dialogue text (MCC and Campaign Evolved subtitles, custom text,
// notes) and the local game folder are painted over before the capture. Nothing here clicks a save, approve,
// build or install button.

import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture } from "./harness.mjs";

const OUT = resolve(HERE, "..", "..", "docs", "images");
const SLOT = "es:A10_690_captkeyes#0";
const LINE = "a10_690_captkeyes";
const BASE = `http://localhost:${WEB_PORT}/#`;
const VIEWPORT = { width: 1600, height: 1000 };
const REDACTED_FILL = "repeating-linear-gradient(135deg, #17345c 0 8px, #1d3f6e 8px 16px)";

// Elements that show game dialogue or local paths.
const REDACT = [
  ".preview",                       // MCC list: English subtitle of each line
  ".subtitles",                     // candidates: es-MX and EN subtitles
  ".column dl.texts dd",            // MCC subtitles (SU, SP, EN) in the replacement and subtitle sections
  ".ce-subtitle",                   // the chosen Campaign Evolved subtitle
  ".custom-subtitle textarea",      // the owner's own text
  ".subtitle-text",                 // the subtitle preview
  "[data-section='flags'] textarea", // notes
  "[data-testid='deploy-status'] > p:first-child code", // game folder
  "[data-testid='deploy-status'] input",                // game folder override box
];

async function ready(page) {
  await page.locator("h1:visible, h2:visible").first().waitFor({ timeout: 60000 });
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(600);
}

// Text is made transparent and its box filled, so the page keeps its layout and its sticky bars stay on top.
async function redact(page) {
  const css = `${REDACT.join(", ")} {
    color: transparent !important; -webkit-text-fill-color: transparent !important; text-shadow: none !important;
    background: ${REDACTED_FILL} !important; border-radius: 3px;
  }
  ${REDACT.map((s) => `${s} *`).join(", ")} { color: transparent !important; -webkit-text-fill-color: transparent !important; }`;
  await page.addStyleTag({ content: css });
}

async function shot(page, name, options = {}) {
  await redact(page);
  await page.screenshot({ path: join(OUT, `${name}.png`), ...options });
  console.log(`wrote docs/images/${name}.png`);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-shots-"));
  const fixture = await runFixture(join(tmp, "root"));
  const services = new Services(fixture.root);
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const context = await browser.newContext({ viewport: VIEWPORT, reducedMotion: "reduce" });
    const page = await context.newPage();

    await page.goto(`${BASE}/`);
    await ready(page);
    await shot(page, "dashboard");

    await page.goto(`${BASE}/match?level=a10&slot=${encodeURIComponent(SLOT)}`);
    await ready(page);
    await page.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 60000 });
    await page.waitForTimeout(1500); // waveforms
    await shot(page, "matching");

    await page.locator("[data-testid='after-edits']").evaluate((el) => el.closest("section")?.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(800);
    await shot(page, "matching-editor");

    await page.goto(`${BASE}/builds`);
    await ready(page);
    await page.locator("[data-testid='deploy-status']").waitFor({ timeout: 60000 });
    await page.getByText(/Loading builds|Checking the game folder/).first().waitFor({ state: "detached", timeout: 60000 });
    await page.waitForTimeout(1500); // scope preview
    await shot(page, "build-test");

    await context.close();
  } finally {
    await browser?.close();
    await services.down();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
