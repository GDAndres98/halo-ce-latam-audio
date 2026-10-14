// Browser test of the match panel's download buttons for the replacement (2026-10-13).
//
//   npm run test:downloads      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the mapping data: a line with a chosen Campaign Evolved recording shows a download
// button for that recording (es-MX) and, once the automatic preview has rendered, one for the edited draft. Both
// are real WAV downloads with readable file names. The real mappings are hashed before and after.

import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:c10_010_captpilot#0";
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
    if (page) await page.screenshot({ path: join(OUT, "downloads-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

/** Clicks a download link and returns {name, rate, seconds} of the saved WAV. */
async function download(testId, dir) {
  const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), page.getByTestId(testId).click()]);
  const path = join(dir, dl.suggestedFilename());
  await dl.saveAs(path);
  const b = await readFile(path);
  check(b.toString("ascii", 0, 4) === "RIFF" && b.toString("ascii", 8, 12) === "WAVE", `${dl.suggestedFilename()} is not a WAV`);
  const rate = b.readUInt32LE(24);
  const bytesPerSec = b.readUInt32LE(28);
  const data = b.indexOf("data");
  return { name: dl.suggestedFilename(), rate, seconds: (b.readUInt32LE(data + 4) / bytesPerSec).toFixed(2) };
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-downloads-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });
    page = await context.newPage();
    handleConfirms(page);
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=c10&slot=${encodeURIComponent(SLOT)}`);
    await page.getByTestId("ce-key").waitFor({ timeout: 60000 });

    await step("the Campaign Evolved es-MX recording downloads as a WAV", async () => {
      const f = await download("download-ce", tmp);
      check(f.name === "vo_scr_m06_00740_victor933_0_es-MX.wav", f.name);
      check(f.rate === 48000, `rate ${f.rate}`);
      return `${f.name}, ${f.rate} Hz, ${f.seconds} s`;
    });

    await step("the edited draft downloads once rendered, as the build renders it (44.1 kHz)", async () => {
      await page.getByTestId("download-ce-draft").waitFor({ timeout: 120000 });
      const f = await download("download-ce-draft", tmp);
      check(f.name === "c10_c10_010_captpilot_0_vo_scr_m06_00740_victor933_0_es-MX_draft.wav", f.name);
      check(f.rate === 44100, `rate ${f.rate}`);
      await page.getByTestId("ce-replacement").screenshot({ path: join(OUT, "downloads.png") });
      return `${f.name}, ${f.rate} Hz, ${f.seconds} s`;
    });
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }
  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === realBefore, "real manual_mappings.json changed");
  });
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "downloads-report.json"), JSON.stringify({ results }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
