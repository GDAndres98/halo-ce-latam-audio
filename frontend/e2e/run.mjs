// Browser end-to-end test of the matching workflow (acceptance test, prompt 34 section 15).
//
//   npm run test:e2e        (from frontend/; needs Microsoft Edge installed, and the Python API deps)
//
// It starts a disposable API server and a Vite dev server, drives Microsoft Edge through the real
// interface, restarts both to prove persistence, and checks that the real mapping decisions did not change.
// Nothing here writes to the real mappings folder: the test works on a copy made by scripts/ui/e2e_fixture.py.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { API_PORT, HERE, WEB_PORT, Services, runFixture, runPython, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const CUSTOM_TEXT = "¡Despierte, Jefe Maestro!";

const results = [];
let livePage = null; // the page the current step uses, for failure screenshots
const pageErrors = [];
function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
async function step(name, fn) {
  try {
    const detail = await fn();
    record(name, true, detail ?? "");
  } catch (e) {
    record(name, false, String(e && e.message ? e.message : e).split("\n")[0]);
    throw e; // later steps depend on earlier ones
  }
}

async function openMatching(browser, query = "", waitForLine = true) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.on("dialog", (dialog) => dialog.accept());
  handleConfirms(page);
  page.on("pageerror", (err) => pageErrors.push(`${err.message}\n    ${(err.stack ?? "").split("\n").slice(1, 3).join("\n    ")}`));
  page.on("response", (res) => {
    // The browser asks for /favicon.ico on its own; that 404 is not a Studio error.
    if (res.status() >= 400 && !res.url().endsWith("/favicon.ico")) pageErrors.push(`HTTP ${res.status()} ${res.url()}`);
  });
  page.on("console", (msg) => { if (msg.type() === "error") pageErrors.push(`${msg.text()} @ ${msg.location().url}`); });
  livePage = page;
  await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10${query}`);
  if (waitForLine) await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
  else await page.getByPlaceholder(/Accents and case ignored/).waitFor({ timeout: 30000 });
  return page;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-e2e-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  const services = new Services(root);
  const realMappingsBefore = fixture.real_mappings_sha256;
  let browser;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${root}`;
    });

    browser = await chromium.launch({ channel: "msedge", headless: true });

    // Step 4-5: open the line and find the Campaign Evolved recording by its identifier.
    let page = await openMatching(browser, "", false);
    await step("select the a10 mission and the line es:A10_010_cryotech#0", async () => {
      await page.getByPlaceholder(/Accents and case ignored/).fill("a10_010_cryotech");
      const row = page.locator("li.row-item", { hasText: "a10_010_cryotech" }).first();
      await row.waitFor({ timeout: 30000 });
      await row.click();
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
    });

    await step("search Campaign Evolved recordings by identifier", async () => {
      await page.getByPlaceholder(/Partial words/).fill(CE_REF.split("#")[0]);
      await page.getByText(CE_REF, { exact: true }).first().waitFor({ timeout: 15000 });
    });

    // Step 6-7: both recordings play (the play buttons toggle to the stop symbol while playing).
    await step("play the MCC recording", async () => {
      // The selected row's play button plays Spain's recording (the same clip the m key plays).
      const spainButton = page.locator("li.row-item.selected button.play").first();
      await spainButton.click();
      await page.locator("li.row-item.selected button.play.active").first().waitFor({ timeout: 10000 });
      await spainButton.click();
    });
    await step("play the Campaign Evolved recording", async () => {
      const row = page.locator("li.row-item", { hasText: CE_REF });
      await row.getByRole("button", { name: "es-MX" }).click();
      await row.locator("button.play.active", { hasText: "es-MX" }).waitFor({ timeout: 10000 });
      await row.locator("button.play.active", { hasText: "es-MX" }).click();
    });

    // Step 8-9: explicitly choose the recording, then save the draft.
    await step("choose the Campaign Evolved recording as the replacement", async () => {
      const row = page.locator("li.row-item", { hasText: CE_REF });
      await row.getByRole("button", { name: /Use this recording/ }).click();
      await page.getByText("Recording chosen").waitFor();
    });
    await step("save the selection as a draft", async () => {
      await page.getByRole("button", { name: /Save draft/ }).click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
    });

    // Step 10-11: a custom LATAM Spanish subtitle, saved as a draft.
    await step("write a custom LATAM Spanish subtitle and save the draft", async () => {
      await page.getByLabel("Write my own LATAM Spanish text").check();
      await page.locator("textarea").first().fill(CUSTOM_TEXT);
      await page.getByRole("button", { name: /Save draft/ }).click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
    });

    // Step 12-13: approve audio and subtitle independently.
    await step("approve the audio independently", async () => {
      await page.getByRole("button", { name: "Approve audio" }).click();
      await page.getByText("approved audio").waitFor({ timeout: 15000 });
    });
    await step("approve the subtitle independently", async () => {
      await page.getByRole("button", { name: "Approve subtitle" }).click();
      await page.getByText("approved subtitle").waitFor({ timeout: 15000 });
    });

    // Step 14: the radio-effect flag (independent of approvals; allowed on an approved line).
    await step("set the Needs Radio Effect flag", async () => {
      await page.getByRole("checkbox", { name: /Needs radio effect/ }).check();
      await page.getByRole("button", { name: /Save draft/ }).click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
    });

    // Step 18 (checked before editing, while approved): the audio is read-only.
    await step("an approved audio decision cannot be edited", async () => {
      const trim = page.getByLabel("Trim start (s)");
      if (!(await trim.isDisabled())) throw new Error("trim field is editable while the audio is approved");
      const refused = await page.evaluate(async (slot) => {
        const current = await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json();
        const body = {
          slot_id: slot,
          loaded_sha256: current.sha256.mappings,
          local_sha256: current.sha256.local,
          audio: { source: "ce", sources: [{ ce_line_ref: "vo_scr_m01_00460_cryotech#0", language: "Spanish(Mexico)" }],
                   edit: { trim_start_s: 0.2, trim_end_s: 0, gap_s: 0, cuts: [], silences: [], fade_in_ms: 0, fade_out_ms: 0, crossfade_ms: 20 } },
        };
        const res = await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        return res.status;
      }, SLOT);
      if (refused !== 409) throw new Error(`expected 409 from the API, got ${refused}`);
      return "field disabled; API refused the change with 409";
    });

    // Step 15: a trim needs Needs Rework first, then preview, then save and approve again.
    await step("mark the audio Needs rework to make a trim", async () => {
      await page.getByRole("button", { name: "Needs rework (audio)" }).click();
      await page.getByText("Audio marked Needs rework").waitFor({ timeout: 15000 });
    });
    await step("apply a trim and preview the edited recording", async () => {
      await page.getByLabel("Trim start (s)").fill("0.2");
      await page.getByLabel("Trim start (s)").press("Tab"); // number fields apply on change
      // The edited recording is rendered automatically after the change.
      await page.waitForResponse((r) => r.url().includes("/api/edit/preview") && r.status() === 200, { timeout: 60000 });
    });
    await step("save the trim and approve the audio again", async () => {
      await page.getByRole("button", { name: /Save draft/ }).click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      await page.getByRole("button", { name: "Approve audio" }).click();
      await page.getByText("approved audio").waitFor({ timeout: 15000 });
    });

    // Step 16-17: close everything, start again, and check that the decisions and the recipe persisted.
    await browser.close();
    browser = null;
    await services.down();
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await openMatching(browser, `&slot=${encodeURIComponent(SLOT)}`);
    await step("after a restart, the decisions and the recipe are still there", async () => {
      await page.getByLabel("Trim start (s)").waitFor({ timeout: 30000 });
      const trim = await page.getByLabel("Trim start (s)").inputValue();
      if (Number(trim) !== 0.2) throw new Error(`trim start is ${trim}, expected 0.2`);
      if (!(await page.getByRole("checkbox", { name: /Needs radio effect/ }).isChecked())) throw new Error("radio flag lost");
      if (!(await page.getByLabel("Write my own LATAM Spanish text").isChecked())) throw new Error("subtitle source lost");
      const text = await page.locator("textarea").first().inputValue();
      if (text !== CUSTOM_TEXT) throw new Error(`custom subtitle is "${text}"`);
      const approved = await page.getByRole("button", { name: "Approve audio" }).isDisabled();
      if (!approved) throw new Error("audio is not approved after the restart");
      return `trim 0.2 s, radio on, custom text kept`;
    });

    await step("the restored line keeps its matched recording and approvals", async () => {
      // The badges of the centre panel only (the list shows the same words for other lines).
      const centre = page.locator(".status-row");
      await centre.getByText("match: matched").waitFor({ timeout: 15000 });
      // The approval badges are in the save bar (since the approvals moved there).
      const saveBar = page.locator(".save-bar");
      await saveBar.getByText("audio: approved").waitFor({ timeout: 15000 });
      await saveBar.getByText("subtitle: approved").waitFor({ timeout: 15000 });
    });

    await step("keyboard: m plays, Escape stops, typing in a field does not trigger shortcuts, Ctrl+S saves", async () => {
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).click();
      await page.keyboard.press("m");
      await page.locator("li.row-item.selected button.play.active").first().waitFor({ timeout: 10000 });
      await page.keyboard.press("Escape");
      await page.locator("li.row-item.selected button.play:not(.active)").first().waitFor({ timeout: 10000 });

      await page.getByLabel("Notes", { exact: true }).click();
      await page.keyboard.type("mj");
      if (!(await page.getByLabel("Notes", { exact: true }).inputValue()).endsWith("mj")) throw new Error("typing was not kept");
      if (await page.locator("li.row-item.selected button.play.active").count()) throw new Error("typing started playback");
      await page.keyboard.press("Control+s");
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      return "m plays, Escape stops, typed letters stay in the field, Ctrl+S saved the note";
    });

    await step("the M6 planner reads the saved decision as a replacement", async () => {
      const { code, out } = await runPython(["scripts/ui/e2e_check_m6.py", "--root", root, "--slot", SLOT]);
      const result = JSON.parse(out.trim().split("\n").pop());
      if (code !== 0 || !result.ok) throw new Error(`planner says ${result.action}: ${result.reason}`);
      return `action ${result.action}, trim ${result.edit?.trim_start_s} s`;
    });

    await step("the audio endpoints refuse paths outside the catalogue", async () => {
      const probes = [
        `/audio/ce?ref=${encodeURIComponent("../../etc/passwd")}&lang=Spanish(Mexico)`,
        `/audio/mcc?level=..%2F..&lang=spanish&index=0`,
        `/audio/preview?key=..%2F..%2Fsecret&kind=edited`,
      ];
      const codes = [];
      for (const path of probes) {
        const res = await fetch(`http://127.0.0.1:${API_PORT}${path}`);
        codes.push(res.status);
      }
      if (codes.some((c) => c < 400)) throw new Error(`a traversal probe was answered: ${codes}`);
      return `refused with ${codes.join(", ")}`;
    });

    await page.screenshot({ path: join(OUT, "matching-after-restart.png"), fullPage: false });
  } catch (e) {
    if (browser) await browser.close().catch(() => {});
    if (browser) browser = null;
    record("workflow stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }

  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    if (after !== realMappingsBefore) throw new Error("real manual_mappings.json changed");
    return `sha256 ${after.slice(0, 16)}…`;
  });

  if (pageErrors.length) console.log("\nbrowser errors:\n" + pageErrors.slice(0, 20).join("\n"));
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "report.json"), JSON.stringify({ results, root }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed. Report: e2e/out/report.json` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
