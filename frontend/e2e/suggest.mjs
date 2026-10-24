// Browser test of the read-only Suggestions tab (docs/suggested-matching.md, owner 2026-10-23).
//
//   npm run test:suggest      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the data (scripts/ui/e2e_fixture.py): Suggestions lists a10's sounds with scored CE lines
// (a10_010_cryotech's best is VO_SCR_M01_00460_CryoTech, its identical English line), "Open" goes to Matching with the
// MCC line open and the CE list filtered to the suggested line, and nothing is written: the disposable mappings and
// the real ones hash the same before and after. Also a phone-width screenshot.

import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const TAG = "sound\\dialog\\a10\\a10_010_cryotech";
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
    if (page) await page.screenshot({ path: join(OUT, "suggest-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const text = async (loc) => (await loc.innerText()).replace(/\s+/g, " ");

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-suggest-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const copyFile = join(fixture.root, "mappings", "manual_mappings.json");
  const copyBefore = await sha256File(copyFile);
  const services = new Services(fixture.root);
  let browser;
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${fixture.root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    await step("the nav has Suggestions; a10 lists sounds with scored CE lines", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/`);
      await page.getByRole("link", { name: "Suggestions" }).click();
      await page.getByTestId("suggest-summary").waitFor({ timeout: 60000 });
      await page.goto(`http://localhost:${WEB_PORT}/#/suggest?level=a10&show=all`);
      const card = page.locator(`section[data-sound="${TAG.replace(/\\/g, "\\\\")}"]`);
      await card.waitFor({ timeout: 60000 });
      const first = card.locator("tbody tr").first();
      check((await first.getAttribute("data-ref")) === "vo_scr_m01_00460_cryotech#0",
            `best: ${await first.getAttribute("data-ref")}`);
      const t = await text(first);
      check(/100%/.test(t), `row: ${t}`);
      await page.waitForFunction(() => /^\s*101 of 101 sounds listed/.test(
        document.querySelector('[data-testid="suggest-summary"]')?.textContent ?? ""), null, { timeout: 30000 })
        .catch(async () => check(false, `every sound should be listed: ${await text(page.getByTestId("suggest-summary"))}`));
      await page.screenshot({ path: join(OUT, "suggest-page.png"), fullPage: false });
      return await text(page.getByTestId("suggest-summary"));
    });

    await step("Ask Claude explains what it needs when the SDK is missing", async () => {
      const button = page.getByTestId("ask-claude").first();
      const title = (await button.getAttribute("title")) ?? "";
      if (await button.isDisabled()) check(/anthropic|admin/.test(title), `title: ${title}`);
      return (await button.isDisabled()) ? "disabled: " + title.slice(0, 60) : "enabled";
    });

    await step("Open goes to Matching with the line open and the CE list filtered to the suggestion", async () => {
      const card = page.locator(`section[data-sound="${TAG.replace(/\\/g, "\\\\")}"]`);
      await card.locator("tbody tr").first().getByRole("link", { name: "Open" }).click();
      await page.waitForURL(/#\/match\?/, { timeout: 15000 });
      const url = decodeURIComponent(page.url());
      check(url.includes("slot=es:A10_010_cryotech#0") && url.includes("cq=VO_SCR_M01_00460_CryoTech") &&
            url.includes("cm=M01"), url);
      return url.split("#")[1];
    });

    await step("grunt barks: compared with CE's vo_sys_grunt by English sound (or by name before the comparison)", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/suggest?level=grunt&scope=SYS&show=all`);
      const card = page.locator('section[data-sound$="actions\\\\alert_noncombat"]');
      await card.waitFor({ timeout: 60000 });
      await page.waitForFunction(() => /\b55 of 55 sounds listed/.test(
        document.querySelector('[data-testid="suggest-summary"]')?.textContent ?? ""), null, { timeout: 30000 });
      const summary = await text(page.getByTestId("suggest-summary"));
      check(await page.getByTestId("ask-claude-folder").isVisible(), "no folder button");
      if (!/by sound/.test(summary)) {
        check(await page.getByTestId("audio-hint").isVisible(), "no hint to run the audio comparison");
        return `not compared by sound yet: ${summary}`;
      }
      // The English audio comparison: alert_noncombat's takes are CE's 01contact_heardfoe (the owner's own match).
      const first = await card.locator("tbody tr").first().getAttribute("data-ref");
      check(first === "vo_sys_default_01contact_heardfoe_grunt#0", `best: ${first}`);
      const pairs = card.getByTestId("audio-pairs").first();
      check(/6 of 6/.test(await text(pairs)), `pairs: ${await text(pairs)}`);
      check((await card.getByTestId("mcc-takes").locator("button").count()) === 6, "6 MCC English take players");
      // Both sides of a pair play (decoded on demand by the API).
      for (const title of ["Play MCC English take", "Play CE English variation"]) {
        const button = pairs.locator(`button[title^="${title}"]`).first();
        await button.click();
        await pairs.locator('button[title^="Stop"]').first().waitFor({ timeout: 30000 });  // it is playing
        await button.click();
      }
      await page.screenshot({ path: join(OUT, "suggest-grunt.png"), fullPage: false });
      return summary;
    });

    await step("the take and variation audio URLs answer with WAV", async () => {
      const api = (u) => page.request.get(`http://localhost:${WEB_PORT}${u}`);
      const mcc = await api("/audio/mcc?level=grunt&lang=english&index=1213");
      const ce = await api(`/audio/ce?ref=${encodeURIComponent("vo_sys_default_01contact_heardfoe_grunt#0")}&lang=English(US)`);
      check(mcc.ok() && ce.ok(), `mcc ${mcc.status()} ce ${ce.status()}`);
      return `${mcc.headers()["content-type"]}, ${ce.headers()["content-type"]}`;
    });

    await step("phone width: the page fits without sideways scrolling", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`http://localhost:${WEB_PORT}/#/suggest?level=a10&show=all`);
      await page.locator("section.sound").first().waitFor({ timeout: 60000 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await page.screenshot({ path: join(OUT, "suggest-phone.png"), fullPage: false });
      check(overflow <= 1, `page is ${overflow}px wider than the screen`);
      return "fits";
    });
  } finally {
    await browser?.close().catch(() => {});
    await services.down();
  }
  const copyAfter = await sha256File(copyFile);
  record("the page wrote nothing (disposable mappings unchanged)", copyAfter === copyBefore, copyAfter.slice(0, 16));
  const realAfter = await sha256File(join(HERE, "..", "..", "mappings", "manual_mappings.json"));
  record("the real mappings are unchanged by this test", realAfter === realBefore,
         realAfter === realBefore ? realAfter.slice(0, 16) : "changed: check whether the Studio saved meanwhile");
  record("no page errors", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));
  const failed = results.filter((r) => !r.ok);
  console.log(`${failed.length ? "FAILED" : "PASS"}: ${results.length - failed.length}/${results.length}`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
