// Browser test of Victor 933's one-off "Transmission interference" section (2026-10-13).
//
//   npm run test:interference      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the mapping data: the section shows the 11 aligned regions for Victor 933's line only,
// a region edit re-renders the automatic preview with the interference, an invalid edit is refused, Reset
// restores the aligned timings, and another line has no such section. The real mappings are hashed before/after.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:c10_010_captpilot#0";
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
const section = () => page.getByTestId("interference");

async function nextPreview(change) {
  const response = page.waitForResponse((r) => r.url().includes("/api/edit/preview") && r.request().method() === "POST", { timeout: 120000 });
  await change();
  const r = await response;
  check(r.ok(), `preview answered ${r.status()}`);
  return (await r.json()).stats;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-interference-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on("dialog", (d) => d.accept());
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    await step("Victor 933's line shows the 11 aligned regions, with the preview rendering them", async () => {
      const first = page.waitForResponse((r) => r.url().includes("/api/edit/preview"), { timeout: 120000 });
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=c10&slot=${encodeURIComponent(SLOT)}`);
      await section().waitFor({ timeout: 60000 });
      const rows = section().getByTestId("interference-region");
      check((await rows.count()) === 11, `${await rows.count()} regions`);
      check((await rows.nth(1).getByLabel("Effect of region 2").inputValue()) === "masked", "region 2 is not masked");
      check((await rows.nth(0).getByLabel("Effect of region 1").inputValue()) === "partial", "region 1 is not partial");
      const stats = (await (await first).json()).stats;
      check(stats.interference && stats.interference.masked === 6 && stats.interference.partial === 5, JSON.stringify(stats.interference));
      check(Math.abs(stats.output_s - stats.edited_s) < 0.01, "the interference changed the length");
      await section().scrollIntoViewIfNeeded();
      await section().screenshot({ path: join(OUT, "interference.png") });
      return `${stats.interference.masked} masked, ${stats.interference.partial} partial; peak ${stats.output_peak_dbfs} dBFS`;
    });

    await step("a timing edit re-renders; an overlapping one is refused and snaps back", async () => {
      const end = section().getByLabel("End of region 11 (s)");
      const stats = await nextPreview(async () => {
        await end.fill("26.0");
        await end.press("Tab");
      });
      check(stats.interference.regions === 11, "regions lost");
      const start2 = section().getByLabel("Start of region 2 (s)");
      await start2.fill("0.2");
      await start2.press("Tab");
      check(Number(await start2.inputValue()) === 1.93, `start of region 2 is ${await start2.inputValue()}`);
    });

    await step("Reset restores the aligned timings", async () => {
      await section().getByRole("button", { name: /Reset to the aligned timings/ }).click();
      check(Number(await section().getByLabel("End of region 11 (s)").inputValue()) === 25.93, "not reset");
    });

    await step("another line has no interference section", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent("es:A10_010_cryotech#0")}`);
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      check((await page.getByTestId("interference").count()) === 0, "the section appears on another line");
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
