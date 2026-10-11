// Playwright comparison: the classic M4 page against the Studio's matching workspace, on disposable data.
//
//   npm run compare:m4        (from frontend/; needs Microsoft Edge)
//
// The same task is done in both: pick the line es:A10_010_cryotech#0, choose the Campaign Evolved
// recording vo_scr_m01_00460_cryotech#0, and save the draft. Every click and fill is counted, and the
// time to finish is measured. Each page's visible controls are inventoried. Writes only to the disposable
// copy of the mapping data (scripts/ui/e2e_fixture.py); the real decisions are checked at the end.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { API_PORT, HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const LINE = "a10_010_cryotech";
const CE_REF = "vo_scr_m01_00460_cryotech#0";

/** Counts the actions of one run and times it. */
function tracker(page) {
  const log = { actions: 0, steps: [], started: 0, finished: 0 };
  return {
    log,
    async click(locator, label) {
      if (!log.started) log.started = Date.now();
      log.actions += 1;
      log.steps.push(`click: ${label}`);
      await locator.click();
    },
    async fill(locator, text, label) {
      if (!log.started) log.started = Date.now();
      log.actions += 1;
      log.steps.push(`type "${text}" in ${label}`);
      await locator.fill(text);
    },
    done() {
      log.finished = Date.now();
      log.seconds = Number(((log.finished - log.started) / 1000).toFixed(1));
      return log;
    },
  };
}

/** Visible controls on the first screen: a rough measure of how much the page asks the user to know. */
async function inventory(page) {
  return page.evaluate(() => {
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const count = (sel) => [...document.querySelectorAll(sel)].filter(visible).length;
    return {
      buttons: count("button"),
      textInputs: count('input[type="search"], input[type="text"], input:not([type]), textarea'),
      selects: count("select"),
      checkboxes: count('input[type="checkbox"]'),
      radios: count('input[type="radio"]'),
    };
  });
}

async function runClassic(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:${API_PORT}/`);
  await page.locator("#slots").waitFor({ timeout: 60000 });
  const t = tracker(page);
  const inv = await inventory(page);
  await page.screenshot({ path: join(OUT, "compare-classic.png") });

  await t.click(page.locator("#slots").getByText(LINE, { exact: false }).first(), `line ${LINE} in the MCC list`);
  await t.fill(page.locator("#cq"), CE_REF.split("#")[0], "the candidate search (#cq)");
  await t.click(page.locator(`[data-use="${CE_REF}"]`), `"+ use for this slot" on ${CE_REF}`);
  // Wait for the server's answer, not for a piece of text: the page also says "unsaved" elsewhere.
  const answered = page.waitForResponse((r) => r.url().includes("/api/save") && r.request().method() === "POST", { timeout: 20000 });
  await t.click(page.locator("#save"), "Save");
  const response = await answered;
  if (response.status() !== 200) throw new Error(`classic save answered ${response.status()}`);
  const log = t.done();
  await page.close();
  return { app: "classic M4", ...log, inventory: inv };
}

async function runStudio(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.on("dialog", (d) => d.accept());
  handleConfirms(page);
  await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10`);
  await page.getByPlaceholder(/Accents and case ignored/).waitFor({ timeout: 60000 });
  const t = tracker(page);
  const inv = await inventory(page);
  await page.screenshot({ path: join(OUT, "compare-studio.png") });

  // The MCC list shows the level's lines without a search, as the classic list does, so no search here.
  await t.click(page.locator("li.row-item", { hasText: LINE }).first(), `line ${LINE} in the MCC list`);
  await t.fill(page.getByPlaceholder(/Partial words/), CE_REF.split("#")[0], "the candidate search");
  await t.click(page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }), "Use this recording");
  await t.click(page.getByRole("button", { name: /Save draft/ }), "Save draft");
  try {
    await page.getByText("Draft saved.").waitFor({ timeout: 20000 });
  } catch (e) {
    const banner = await page.locator(".error, .problems").allInnerTexts();
    await page.screenshot({ path: join(OUT, "compare-studio-failed.png") });
    throw new Error(`Studio did not confirm the draft; banners: ${JSON.stringify(banner)}`);
  }
  const log = t.done();
  await page.close();
  return { app: "Studio", ...log, inventory: inv };
}

/** One fresh disposable copy of the data and its servers per interface, so the two runs cannot affect
 * each other (the second run would otherwise find the line already matched). */
async function runIsolated(name, run) {
  const tmp = await mkdtemp(join(tmpdir(), "studio-compare-"));
  const fixture = await runFixture(join(tmp, "root"));
  const services = new Services(fixture.root);
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });
    return await run(browser);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
    if (name === "done") console.log("");
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const real = await runFixture(join(await mkdtemp(join(tmpdir(), "studio-real-")), "probe"));
  const realBefore = real.real_mappings_sha256;
  const results = [];
  results.push(await runIsolated("classic", runClassic));
  results.push(await runIsolated("studio", runStudio));
  const after = await sha256File(join(real.real_mappings, "manual_mappings.json"));
  await writeFile(join(OUT, "compare.json"), JSON.stringify({ results, real_mappings_unchanged: after === realBefore }, null, 2));
  for (const r of results) {
    console.log(`${r.app.padEnd(10)} actions=${r.actions}  seconds=${r.seconds}  controls=${JSON.stringify(r.inventory)}`);
    for (const s of r.steps) console.log(`    - ${s}`);
  }
  console.log(`real mapping decisions unchanged: ${after === realBefore}`);
  process.exitCode = after === realBefore ? 0 : 1;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
