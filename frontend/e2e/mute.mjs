// Browser test of Mute / No replacement (2026-10-16).
//
//   npm run test:mute      (from frontend/; needs Microsoft Edge)
//
// Opens an unmatched line, chooses "Mute in game", gives a reason, saves, reloads, approves the audio, then
// reworks it and goes back to Spain's audio. Works on a disposable copy of the mapping data
// (scripts/ui/e2e_fixture.py); the real mappings are hashed before and after.

import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
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
    if (page) await page.screenshot({ path: join(OUT, "mute-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

const saveButton = () => page.getByTestId("save-draft");
const problems = () => page.locator(".save-bar .problems li").allInnerTexts();
const errorText = () => page.locator(".state-message.error, [role=alert]").allInnerTexts();

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-mute-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  let slotId = null;
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${fixture.root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&status=undecided`);
    const first = page.locator("li.row-item").first();
    await first.waitFor({ timeout: 30000 });

    await step("an unmatched line can be muted with a reason and saved", async () => {
      slotId = (await first.getAttribute("id")).replace(/^mcc-/, "");
      await first.click();
      await page.getByTestId("keep-spain").waitFor({ timeout: 30000 });
      await page.getByTestId("mute-line").check();
      await page.getByTestId("mute-reason").waitFor();
      check((await problems()).some((p) => /why/.test(p)), `problems ${JSON.stringify(await problems())}`);
      check(await page.getByTestId("mute-reason").evaluate((el) => el === document.activeElement), "the reason box has no focus");
      await page.getByTestId("mute-reason").fill("No Campaign Evolved equivalent");
      await page.waitForTimeout(300);
      check(await saveButton().isEnabled(), `save disabled; problems ${JSON.stringify(await problems())}`);
      await saveButton().click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 }).catch(async () => {
        throw new Error(`no "Draft saved."; errors ${JSON.stringify(await errorText())}`);
      });
      return slotId;
    });

    await step("after a reload the line is still muted, with its reason and a badge", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&status=muted&slot=${encodeURIComponent(slotId)}`);
      await page.getByTestId("mute-reason").waitFor({ timeout: 30000 });
      check((await page.getByTestId("mute-reason").inputValue()) === "No Campaign Evolved equivalent", "reason lost");
      check(await page.getByTestId("mute-line").isChecked(), "mute not selected");
      await page.locator(`[id="mcc-${slotId}"] [data-testid=muted-pill]`).waitFor({ timeout: 10000 });
    });

    await step("the muted audio can be approved, reworked and set back to Spain's audio", async () => {
      await page.getByRole("button", { name: /Approve audio$/ }).first().click();
      await page.getByText(/approved audio/).waitFor({ timeout: 15000 });
      check(await page.getByTestId("mute-line").isDisabled(), "approved mute is not read-only");
      await page.getByRole("button", { name: /Needs rework/ }).first().click();
      await page.getByText(/marked Needs rework/).waitFor({ timeout: 15000 });
      await page.getByTestId("keep-spain").check();
      await saveButton().click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      check((await page.locator(`[id="mcc-${slotId}"] [data-testid=muted-pill]`).count()) === 0, "badge still shown");
    });

    await step("a line with approved Campaign Evolved audio can be reworked, muted and saved", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&status=approved`);
      const row = page.locator(`li.row-item[id^="mcc-"]:not([id="mcc-${slotId}"])`).first();
      await row.waitFor({ timeout: 30000 });
      const id = (await row.getAttribute("id")).replace(/^mcc-/, "");
      const tag = (await row.locator("strong.tag").innerText()).replace(/ #\d+$/, "");
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&status=approved&slot=${encodeURIComponent(id)}`);
      await page.reload();
      await page.getByRole("heading", { level: 2, name: tag }).waitFor({ timeout: 30000 });
      await page.waitForTimeout(500);
      const shown = await page.locator(".source-card").first().innerText();
      check(await page.getByTestId("mute-line").isDisabled(), `approved audio is not read-only (row ${id}, url ${page.url()}, shown ${shown.replace(/\s+/g, " ")})`);
      await page.getByRole("button", { name: /Needs rework/ }).first().click();
      await page.getByText(/marked Needs rework/).waitFor({ timeout: 15000 });
      await page.getByTestId("mute-line").check();
      await page.getByTestId("mute-reason").fill("Muted for the test");
      await page.waitForTimeout(300);
      check(await saveButton().isEnabled(), `save disabled; problems ${JSON.stringify(await problems())}`);
      await saveButton().click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 }).catch(async () => {
        throw new Error(`no "Draft saved."; errors ${JSON.stringify(await errorText())}`);
      });
      return id;
    });

    await step("the owner's line es:keyes01#0 (audio and subtitle in needs rework) can be muted and saved", async () => {
      const id = "es:keyes01#0";
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=x10&slot=${encodeURIComponent(id)}`);
      await page.reload();
      await page.getByTestId("mute-line").waitFor({ timeout: 30000 });
      await page.waitForTimeout(800);
      await page.getByTestId("mute-line").check();
      await page.getByTestId("mute-reason").fill("No equivalent");
      await page.waitForTimeout(300);
      if (!(await saveButton().isEnabled())) {
        await page.screenshot({ path: join(OUT, "mute-keyes01.png"), fullPage: true });
        throw new Error(`save disabled; problems ${JSON.stringify(await problems())}`);
      }
      await saveButton().click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 }).catch(async () => {
        await page.screenshot({ path: join(OUT, "mute-keyes01.png"), fullPage: true });
        throw new Error(`no "Draft saved."; errors ${JSON.stringify(await errorText())}`);
      });
    });
  } finally {
    await browser?.close().catch(() => {});
    await services.down();
  }
  const realAfter = await sha256File(join(HERE, "..", "..", "mappings", "manual_mappings.json"));
  record("the real mappings are unchanged", realAfter === realBefore, realAfter.slice(0, 16));
  record("no page errors", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));
  const failed = results.filter((r) => !r.ok);
  console.log(`${failed.length ? "FAILED" : "PASS"}: ${results.length - failed.length}/${results.length}`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
