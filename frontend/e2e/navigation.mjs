// Browser test of the fast matching loop (prompt 38), on disposable data.
//
//   npm run test:navigation   (from frontend/; needs Microsoft Edge)
//
// Checks that a save updates only what changed (the saved row and the counters, no list or candidate
// reload), that "Save & next unmatched" and its keys move on without approving anything, that the candidate
// search survives line changes, that a revisited recording is revalidated (304) rather than downloaded again,
// and that rapid typing in a search shows the results of the last query. The real mappings are checked.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const LEVEL = "a30";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const results = [];
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
    if (page) await page.screenshot({ path: join(OUT, "navigation-failed.png") }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

async function main() {
  await mkdir(OUT, { recursive: true });
  const fixture = await runFixture(join(await mkdtemp(join(tmpdir(), "studio-nav-")), "root"));
  const services = new Services(fixture.root);
  let browser;
  const requests = [];
  const audio = [];
  const title = () => page.locator(".line-title h2").innerText();
  const selectedRow = () => page.locator("li.row-item.selected");
  const rowMark = (slot, what) => page.locator(`[id="mcc-${slot}"] [aria-label^="${what}: "]`).getAttribute("aria-label");
  const progressText = () => page.locator(".column.mcc .progress").innerText();
  const count = (part) => requests.filter((u) => u.includes(part)).length;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on("dialog", (d) => d.accept());
    page.on("request", (r) => requests.push(r.url()));
    page.on("requestfinished", async (r) => {
      if (!r.url().includes("/audio/")) return;
      const headers = await r.allHeaders().catch(() => ({}));
      const sizes = await r.sizes().catch(() => ({ responseBodySize: -1 }));
      const res = await r.response();
      audio.push({ url: r.url(), status: res?.status(), revalidated: Boolean(headers["if-none-match"]), body: sizes.responseBodySize });
    });
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=${LEVEL}&status=undecided&cq=00460_cryotech`);
    await page.locator("li.row-item").first().waitFor({ timeout: 60000 });

    let first, second;
    await step("open the first unmatched line; the candidate search from the address is applied", async () => {
      await page.locator("li.row-item").first().click();
      await page.locator(".line-title h2").waitFor();
      first = await selectedRow().getAttribute("id");
      await page.locator("li.row-item", { hasText: CE_REF }).waitFor();
      return first;
    });

    await step("Save & next unmatched: the row and counters update in place, the next line opens, nothing is approved", async () => {
      const before = await progressText();
      const slotsRequests = count("/api/slots");
      const ceRequests = count("/api/ce?");
      await page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).click();
      await page.getByRole("button", { name: /Save & next unmatched/ }).click();
      await page.waitForFunction((id) => document.querySelector("li.row-item.selected")?.id !== id, first, { timeout: 15000 });
      second = await selectedRow().getAttribute("id");
      const slot = first.slice(4);
      check((await rowMark(slot, "match")) === "match: matched", `saved row shows ${await rowMark(slot, "match")}`);
      check((await rowMark(slot, "audio")) === "audio: draft", `saved row audio ${await rowMark(slot, "audio")} (must not be approved)`);
      const after = await progressText();
      check(after !== before, `counters did not change: ${after}`);
      check(count("/api/slots") === slotsRequests, "the MCC list was reloaded");
      check(count("/api/ce?") === ceRequests, "the candidates were reloaded");
      check((await page.getByPlaceholder(/Partial words/).inputValue()) === "00460_cryotech", "the candidate search was lost");
      return `${first} -> ${second}; ${before.split("·")[0].trim()} -> ${after.split("·")[0].trim()}`;
    });

    await step("Ctrl+Enter from the Notes field saves and moves on", async () => {
      await page.getByLabel("Notes").fill("nota rápida");
      await page.getByLabel("Notes").press("Control+Enter");
      await page.waitForFunction((id) => document.querySelector("li.row-item.selected")?.id !== id, second, { timeout: 15000 });
      const slot = second.slice(4);
      const saved = await page.evaluate(async (s) => (await (await fetch(`/api/slot?id=${encodeURIComponent(s)}`)).json()).mapping?.notes, slot);
      check(saved === "nota rápida", `note on ${slot} is ${saved}`);
      return `${second} saved with its note`;
    });

    await step("U moves to the next unmatched line; unsaved changes ask first", async () => {
      const here = await selectedRow().getAttribute("id");
      let asked = 0;
      page.removeAllListeners("dialog");
      page.on("dialog", (d) => {
        asked += 1;
        d.dismiss();
      });
      await page.getByLabel("Notes").fill("sin guardar");
      await page.locator(".line-title h2").click();
      await page.keyboard.press("u");
      await page.waitForTimeout(300);
      check(asked === 1 && (await selectedRow().getAttribute("id")) === here, "left a line with unsaved changes without asking");
      page.removeAllListeners("dialog");
      page.on("dialog", (d) => d.accept());
      await page.keyboard.press("u");
      await page.waitForFunction((id) => document.querySelector("li.row-item.selected")?.id !== id, here, { timeout: 15000 });
      return "dismissed: stayed; accepted: moved";
    });

    await step("revisiting a line revalidates its recording (304) instead of downloading it again", async () => {
      const back = first.slice(4);
      audio.length = 0;
      await page.locator(`[id="mcc-${back}"]`).click();
      await page.waitForFunction(() => Number(document.querySelector('[aria-label="Compare the original and the replacement"] [data-testid="wave-host"]')?.dataset.duration) > 0, null, { timeout: 15000 });
      await page.waitForTimeout(500);
      const index = await page.evaluate(async (s) => (await (await fetch(`/api/slot?id=${encodeURIComponent(s)}`)).json()).spanish.index, back);
      const mcc = audio.filter((a) => a.url.includes("/audio/mcc") && a.url.endsWith(`index=${index}`));
      const fmt = (list) => list.map((a) => `${a.status}${a.revalidated ? " (If-None-Match)" : ""} ${a.body} B`).join(", ");
      check(mcc.length > 0 && mcc.every((a) => a.revalidated && (a.status === 304 || a.body === 0)), `MCC audio: ${fmt(mcc)}`);
      return `MCC audio: ${fmt(mcc)}`;
    });

    await step("rapid typing in the candidate search shows the last query's results", async () => {
      const box = page.getByPlaceholder(/Partial words/);
      for (const q of ["c", "co", "cor", "cort", "corta", "cortan", "cortana"]) await box.fill(q);
      await page.waitForTimeout(1200);
      const rows = await page.locator(".column.ce li.row-item").allInnerTexts();
      check(rows.length > 0 && rows.every((t) => /cortana/i.test(t)), `a row without "cortana": ${rows.find((t) => !/cortana/i.test(t))?.slice(0, 80)}`);
      return `${rows.length} rows, all match`;
    });

    await step("switching lines with the keyboard does not reload the candidates", async () => {
      const ce = count("/api/ce?");
      await page.locator(".line-title h2").click();
      for (let i = 0; i < 4; i++) {
        const t = await title();
        await page.keyboard.press("j");
        await page.waitForFunction((b) => document.querySelector(".line-title h2")?.textContent !== b, t, { timeout: 10000 });
      }
      check(count("/api/ce?") === ce, `${count("/api/ce?") - ce} candidate requests`);
      return "4 lines, 0 candidate requests";
    });
  } catch (e) {
    record("navigation test stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }
  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === fixture.real_mappings_sha256, "real manual_mappings.json changed");
  });
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "navigation-report.json"), JSON.stringify({ results }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
