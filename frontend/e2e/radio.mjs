// Browser test of the radio filter in the audio editor (2026-10-13).
//
//   npm run test:radio      (from frontend/; needs Microsoft Edge)
//
// Chooses a preset, checks that the automatic preview is re-rendered with the filter (the server's stats),
// changes a value (the preset becomes Custom), turns hiss on, undoes, saves and reloads. Works on a disposable
// copy of the mapping data (scripts/ui/e2e_fixture.py); the real mappings are hashed before and after.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";

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
    if (page) await page.screenshot({ path: join(OUT, "radio-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

const radio = () => page.getByTestId("radio-filter");
const preset = () => radio().getByLabel("Radio filter preset");

/** Waits for the preview the next change triggers; -> the server's render stats. */
async function nextPreview(change) {
  const response = page.waitForResponse((r) => r.url().includes("/api/edit/preview") && r.request().method() === "POST", { timeout: 60000 });
  await change();
  const r = await response;
  check(r.ok(), `preview answered ${r.status()}`);
  return (await r.json()).stats;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-radio-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${fixture.root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on("dialog", (d) => d.accept());
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent(SLOT)}&cq=${encodeURIComponent("00460_cryotech")}`);
    await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });

    await step("the radio filter is off until a Campaign Evolved recording is chosen", async () => {
      await page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).click();
      await radio().waitFor();
      await page.waitForFunction(() => {
        const s = document.querySelector('[aria-label="Radio filter preset"]');
        return s && !s.disabled;
      }, null, { timeout: 30000 });
      check((await preset().inputValue()) === "off", "the filter is not off");
      check((await radio().getByLabel("Radio low cut (Hz)").count()) === 0, "values shown while off");
    });

    await step("Spain radio is rendered in the automatic preview", async () => {
      const stats = await nextPreview(() => preset().selectOption("spain"));
      check(stats.radio && stats.radio.preset === "spain", `stats.radio ${JSON.stringify(stats.radio)}`);
      check(Number(await radio().getByLabel("Radio low cut (Hz)").inputValue()) === 700, "low cut is not 700");
      check(await radio().getByLabel("Add MCC radio clicks").isChecked(), "Spain radio has no clicks");
      check(stats.radio.clicks && stats.radio.clicks.in_s === 0.05 && stats.radio.clicks.out_s === 0.217,
        `clicks ${JSON.stringify(stats.radio.clicks)}`);
      check(stats.output_s > stats.edited_s + 0.26, `output ${stats.output_s} s, edited ${stats.edited_s} s`);
      return `${stats.radio.summary}; clicks ${stats.radio.clicks.in_s} + ${stats.radio.clicks.out_s} s`;
    });

    await step("changing a value makes the filter Custom and re-renders", async () => {
      const field = radio().getByLabel("Radio low cut (Hz)");
      const stats = await nextPreview(async () => {
        await field.fill("600");
        await field.press("Tab");
      });
      check((await preset().inputValue()) === "custom", "preset did not become custom");
      check(/600–3300/.test(stats.radio.summary), stats.radio.summary);
      return stats.radio.summary;
    });

    await step("an out-of-range value is refused and the field snaps back", async () => {
      const field = radio().getByLabel("Radio low cut (Hz)");
      await field.fill("20");
      await field.press("Tab");
      await radio().locator("..").getByRole("alert").waitFor({ timeout: 5000 }).catch(() => {});
      check(Number(await field.inputValue()) === 600, `field shows ${await field.inputValue()}`);
    });

    await step("the MCC clicks can be turned off and on", async () => {
      const off = await nextPreview(() => radio().getByLabel("Add MCC radio clicks").uncheck());
      check(!off.radio.clicks && /no clicks/.test(off.radio.summary), off.radio.summary);
      const on = await nextPreview(() => radio().getByLabel("Add MCC radio clicks").check());
      check(on.radio.clicks, "clicks not back");
      return on.radio.summary;
    });

        await step("hiss can be turned on", async () => {
      const stats = await nextPreview(() => radio().getByLabel("Add hiss").check());
      check(/hiss -55 dBFS/.test(stats.radio.summary), stats.radio.summary);
      return stats.radio.summary;
    });

    await step("Ctrl+Z undoes the last radio change", async () => {
      await page.locator("body").click({ position: { x: 5, y: 5 } });
      await page.keyboard.press("Control+z");
      check(!(await radio().getByLabel("Add hiss").isChecked()), "hiss still on after undo");
    });

    await step("the filter is saved with the audio decision and is there after a reload", async () => {
      await page.keyboard.press("Control+s");
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      await page.reload();
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      await radio().waitFor();
      check((await preset().inputValue()) === "custom", `preset after reload ${await preset().inputValue()}`);
      check(Number(await radio().getByLabel("Radio low cut (Hz)").inputValue()) === 600, "low cut lost");
      await radio().scrollIntoViewIfNeeded();
      await radio().screenshot({ path: join(OUT, "radio-filter.png") });
    });

    await step("the Spain echo is rendered and lengthens the line by its ring-out", async () => {
      const echo = page.getByTestId("echo-effect");
      const stats = await nextPreview(() => echo.getByLabel("Echo preset").selectOption("spain"));
      check(stats.echo && stats.echo.preset === "spain" && stats.echo.tail_s > 0.5, `echo ${JSON.stringify(stats.echo)}`);
      const custom = await nextPreview(async () => {
        const f = echo.getByLabel("Echo delay (ms)");
        await f.fill("200");
        await f.press("Tab");
      });
      check((await echo.getByLabel("Echo preset").inputValue()) === "custom" && /200 ms/.test(custom.echo.summary), custom.echo.summary);
      await echo.scrollIntoViewIfNeeded();
      await echo.screenshot({ path: join(OUT, "echo-effect.png") });
      return custom.echo.summary;
    });

    await step("Off removes the filter", async () => {
      await preset().selectOption("off");
      check((await radio().getByLabel("Radio low cut (Hz)").count()) === 0, "values still shown");
    });
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }

  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === realBefore, "real manual_mappings.json changed");
    return `sha256 ${after.slice(0, 16)}…`;
  });
  const unexpected = pageErrors.filter((e) => !/409/.test(e));
  record("no unexpected browser errors", unexpected.length === 0, unexpected.slice(0, 3).join(" | "));
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "radio-report.json"), JSON.stringify({ results, pageErrors }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed. Report: e2e/out/radio-report.json` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
