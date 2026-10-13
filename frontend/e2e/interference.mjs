// Browser test of Victor 933's interference lane (owner prompt 45).
//
//   npm run test:interference      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the mapping data: the lane shows the curve and the 11 phrase guides for Victor 933's
// line only; points can be added, dragged, nudged and removed; a drawn stretch replaces the curve under it and
// the guide list warns when a masked phrase becomes audible; Ctrl+Z undoes; Reset regenerates the curve; zoom
// and the MCC reference overlay work; the curve is saved and survives a reload. The real mappings are hashed.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:c10_010_captpilot#0";
const HEIGHT = 220;
const RULER = 18;
const TOP = 16;
const results = [];
const pageErrors = [];
let page = null;
function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
async function step(name, fn) {
  try {
    record(name, true, (await fn()) ?? "");
  } catch (e) {
    record(name, false, String(e && e.message ? e.message : e).split("\n")[0]);
    if (page) await page.screenshot({ path: join(OUT, "interference-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const lane = () => page.getByTestId("interference-lane");
const section = () => page.getByTestId("interference");

async function nextPreview(change) {
  const response = page.waitForResponse((r) => r.url().includes("/api/edit/preview") && r.request().method() === "POST", { timeout: 120000 });
  await change();
  const r = await response;
  check(r.ok(), `preview answered ${r.status()}`);
  return (await r.json()).stats;
}

/** Page coordinates of (time, intensity) on the lane at the current zoom (scrolled to the start). */
async function at(t, v, duration) {
  await lane().scrollIntoViewIfNeeded();
  const box = await lane().boundingBox();
  return { x: box.x + (t / duration) * box.width, y: box.y + TOP + (1 - v) * (HEIGHT - RULER - TOP) };
}

async function guideTexts() {
  return section().getByTestId("interference-guide").allInnerTexts();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-interference-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  let duration = 0;
  let pointsBefore = 0;
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    page.on("dialog", (d) => d.accept());
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    await step("Victor 933's line shows the lane: curve, 11 guides, masked phrases hidden, continuous rendering", async () => {
      const first = page.waitForResponse((r) => r.url().includes("/api/edit/preview"), { timeout: 120000 });
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=c10&slot=${encodeURIComponent(SLOT)}`);
      await lane().waitFor({ timeout: 60000 });
      const guides = await guideTexts();
      check(guides.length === 11, `${guides.length} guides`);
      check(guides.filter((g) => /hidden/.test(g) && !/meant/.test(g)).length === 6, `masked status: ${guides.join(" | ")}`);
      const stats = (await (await first).json()).stats;
      check(stats.interference && stats.interference.masked_hidden === true, JSON.stringify(stats.interference));
      check(Math.abs(stats.output_s - stats.edited_s) < 0.3, "the interference changed the length"); // clicks add 0.267 s
      pointsBefore = stats.interference.points;
      const detail = await page.evaluate(async (slot) => (await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json()), SLOT);
      duration = detail.interference["vo_scr_m06_00740_victor933#0"].duration_s;
      await section().scrollIntoViewIfNeeded();
      await section().screenshot({ path: join(OUT, "interference-lane.png") });
      return `${pointsBefore} points; peak ${stats.output_peak_dbfs} dBFS`;
    });

    await step("click adds a point, dragging moves it, Delete removes it (each re-renders)", async () => {
      const p = await at(12.75, 0.8, duration); // empty space (the bed points sit near 0.35)
      let stats = await nextPreview(() => page.mouse.click(p.x, p.y));
      check(stats.interference.points === pointsBefore + 1, `${stats.interference.points} points after adding`);
      const time = section().getByLabel("Selected point time (s)");
      check(Math.abs(Number(await time.inputValue()) - 12.75) < 0.05, `selected time ${await time.inputValue()}`);
      const q = await at(12.75, 0.55, duration);
      stats = await nextPreview(async () => {
        await page.mouse.move(p.x, p.y);
        await page.mouse.down();
        for (let i = 1; i <= 8; i++) await page.mouse.move(p.x, p.y + ((q.y - p.y) * i) / 8);
        await page.mouse.up();
      });
      const v = Number(await section().getByLabel("Selected point intensity").inputValue());
      check(Math.abs(v - 0.55) < 0.05, `dragged to ${v}`);
      stats = await nextPreview(() => lane().press("Delete"));
      check(stats.interference.points === pointsBefore, `${stats.interference.points} points after Delete`);
    });

    await step("drawing over a masked phrase replaces the curve and the guide warns; Ctrl+Z restores it", async () => {
      await section().getByRole("button", { name: /Draw/ }).click();
      const a = await at(1.7, 0.2, duration);
      const b = await at(2.8, 0.2, duration);
      await nextPreview(async () => {
        await page.mouse.move(a.x, a.y);
        await page.mouse.down();
        for (let i = 1; i <= 20; i++) await page.mouse.move(a.x + ((b.x - a.x) * i) / 20, a.y);
        await page.mouse.up();
      });
      const warned = (await guideTexts())[1];
      check(/audible!/.test(warned), `guide 2 after drawing: ${warned}`);
      await section().getByRole("button", { name: /Points/ }).click();
      await page.locator("body").click({ position: { x: 5, y: 5 } });
      await nextPreview(() => page.keyboard.press("Control+z"));
      const back = (await guideTexts())[1];
      check(/hidden/.test(back), `guide 2 after undo: ${back}`);
    });

    await step("the static source can be synthetic (made from scratch) or MCC Spain's sample", async () => {
      const select = section().getByLabel("Static source");
      check((await select.inputValue()) === "synthetic", `static source ${await select.inputValue()}`);
      let stats = await nextPreview(() => select.selectOption("mcc"));
      check(stats.interference.texture === "mcc" && stats.interference.static_sha256, "mcc texture");
      stats = await nextPreview(() => select.selectOption("synthetic"));
      check(stats.interference.texture === "synthetic" && stats.interference.static_sha256 === null, "synthetic texture");
      check(stats.interference.masked_hidden === true, "masked phrases not hidden");
    });

    await step("zoom, MCC reference overlay and play from the cursor", async () => {
      await section().getByRole("button", { name: "Zoom in" }).click();
      check((await section().getByTestId("lane-zoom").innerText()) === "2×", "zoom");
      const ref = page.waitForResponse((r) => r.url().includes("/api/interference/reference"), { timeout: 120000 });
      await section().getByLabel("MCC reference overlay").selectOption("spanish");
      const body = await (await ref).json();
      check(body.values.length > 1000 && body.language === "spanish", "reference curve");
      await section().getByRole("button", { name: "Zoom out" }).click();
      await section().getByTestId("lane-play-spanish").click();
      await page.waitForFunction(() => document.querySelector('[data-testid="lane-play-spanish"]')?.getAttribute("aria-pressed") === "true");
      await section().getByRole("button", { name: "Stop" }).click();
      return `reference ${body.values.length} frames`;
    });

    await step("Reset regenerates the curve; the curve is saved and is there after a reload", async () => {
      const p = await at(13.05, 0.85, duration);
      await nextPreview(() => page.mouse.click(p.x, p.y));
      await page.keyboard.press("Control+s");
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      await page.reload();
      await lane().waitFor({ timeout: 60000 });
      const detail = await page.evaluate(async (slot) => (await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json()), SLOT);
      const saved = detail.mapping.audio.edit.interference.points;
      check(saved.length === pointsBefore + 1 && saved.some((q) => Math.abs(q.t - 13.05) < 0.05), `saved ${saved.length} points`);
      const stats = await nextPreview(() => section().getByRole("button", { name: /Reset curve/ }).click());
      check(stats.interference.points === pointsBefore, `${stats.interference.points} points after reset`);
    });

    await step("another line has no interference lane", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent("es:A10_010_cryotech#0")}`);
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      check((await page.getByTestId("interference").count()) === 0, "the lane appears on another line");
    });
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }
  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === realBefore, "real manual_mappings.json changed");
  });
  const unexpected = pageErrors.filter((e) => !/409/.test(e));
  record("no unexpected browser errors", unexpected.length === 0, unexpected.slice(0, 3).join(" | "));
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "interference-report.json"), JSON.stringify({ results, pageErrors }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
