// Browser test of two recordings in one replacement (docs/combine-recordings.md, 2026-10-19).
//
//   npm run test:combine      (from frontend/; needs Microsoft Edge, ffmpeg and libcelt for the previews)
//
// On a disposable copy of the mapping data (scripts/ui/e2e_fixture.py): matches two Campaign Evolved recordings to
// es:A10_010_cryotech#0, joins them (two part editors, a negative gap, the result rendered as the build would),
// saves, then plays them at the same time with an offset, saves and approves. The stored decision is read back
// from the API. The real mappings are hashed before and after.

import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_010_cryotech#0"; // reset to undecided in the fixture
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
    if (page) await page.screenshot({ path: join(OUT, "combine-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const stored = () => page.evaluate(async (slot) => (await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json()).mapping, SLOT);
const editor = () => page.getByTestId("combine-editor");

async function save() {
  await page.getByTestId("save-draft").click();
  await page.getByText("Draft saved.").waitFor({ timeout: 20000 });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-combine-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  let other = "";
  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${fixture.root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    await step("match two Campaign Evolved recordings to the line", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent(SLOT)}&cq=cryotech`);
      await page.reload();
      const first = page.locator("section.column.ce li.row-item", { hasText: CE_REF }).first();
      await first.waitFor({ timeout: 30000 });
      await first.getByRole("button", { name: /Use this recording/ }).click();
      const second = page.locator("section.column.ce li.row-item").filter({ hasNotText: CE_REF }).first();
      other = (await second.locator("strong.tag").innerText()).trim();
      await second.getByRole("button", { name: /Use this recording/ }).click();
      await page.waitForFunction(() => !document.querySelector('[data-testid="join-two"]')?.disabled, null, { timeout: 10000 });
      return other;
    });

    await step("join them: two part editors, a gap, the result rendered", async () => {
      await page.getByTestId("join-two").check();
      await editor().waitFor({ timeout: 10000 });
      const heads = await editor().locator("h3").allInnerTexts();
      check(heads.some((h) => /Part 1/i.test(h)) && heads.some((h) => /Part 2/i.test(h)), `editors: ${heads.join(" | ")}`);
      check((await editor().getByTestId("radio-filter").count()) === 0, "a part offers the radio filter");
      await editor().getByTestId("combine-gap").locator("input").fill("-0.2");
      await editor().getByTestId("combine-gap").locator("input").press("Tab");
      await editor().getByTestId("combine-result").filter({ hasText: /Result: .* s/ }).waitFor({ timeout: 60000 });
      const result = (await editor().getByTestId("combine-result").innerText()).replace(/\s+/g, " ");
      check(/overlap/.test(result), `no overlap reported: ${result}`);
      await save();
      const m = await stored();
      check(m.audio.source === "ce_concat" && m.audio.edit.gap_s === -0.2 && m.audio.sources.length === 2,
            `stored ${JSON.stringify(m.audio).slice(0, 200)}`);
      await page.getByTestId("combine-editor").screenshot({ path: join(OUT, "combine-join.png") });
      return result;
    });

    await step("play them at the same time with an offset, save and approve", async () => {
      await page.getByTestId("mix-two").check();
      await editor().getByTestId("combine-offset").waitFor({ timeout: 10000 });
      check((await editor().locator("h3").allInnerTexts()).length === 1, "an overlay shows part editors");
      await editor().getByTestId("combine-offset").locator("input").fill("0.3");
      await editor().getByTestId("combine-offset").locator("input").press("Tab");
      await editor().getByTestId("combine-result").filter({ hasText: /Result: .* s/ }).waitFor({ timeout: 60000 });
      await save();
      await page.getByTestId("approval-audio").getByRole("button", { name: "Approve audio" }).click();
      await page.getByText("Saved; approved audio.").waitFor({ timeout: 20000 });
      const m = await stored();
      check(m.audio.source === "ce_mix" && m.audio.edit.offset_s === 0.3 && m.audio.status === "approved",
            `stored ${JSON.stringify(m.audio).slice(0, 200)}`);
      check(m.audio.fingerprint.sources.length === 2, "the approval does not pin both recordings");
      const key = (await page.getByTestId("ce-key-combined").innerText()).replace(/\s+/g, " ");
      check(key.includes(CE_REF) && key.includes("with"), key);
      return key;
    });
  } finally {
    await browser?.close().catch(() => {});
    await services.down();
  }
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
