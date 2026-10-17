// Browser test of added takes (docs/added-takes-design.md, 2026-10-17).
//
//   npm run test:takes      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the mapping data (scripts/ui/e2e_fixture.py): opens Grunt death_violent, focuses a
// Campaign Evolved Grunt death, adds it as a take, approves it, checks the list badge and the reload, marks it
// Needs rework, removes it; and checks that a subtitled line refuses added takes. The real mappings are hashed
// before and after.

import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:deathviolent%2001#1";
const CE_REF = "vo_sys_default_11involuntary_die_ass_grunt#0";
const SUBTITLED = "es:A10_010_cryotech#0";
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
    if (page) await page.screenshot({ path: join(OUT, "takes-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const takes = () => page.getByTestId("added-takes");
const takeRows = () => takes().getByTestId("added-take");

async function openLine(level, slot, cq = "") {
  await page.goto(`http://localhost:${WEB_PORT}/#/match?level=${level}&slot=${encodeURIComponent(slot)}${cq ? `&cq=${encodeURIComponent(cq)}` : ""}`);
  await page.reload();
  await takes().waitFor({ timeout: 30000 });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-takes-"));
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
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    await step("a subtitled line refuses added takes", async () => {
      await openLine("a10", SUBTITLED);
      await takes().getByTestId("takes-not-allowed").waitFor({ timeout: 10000 });
    });

    await step("Grunt death_violent: the focused recording is added as a draft take", async () => {
      await openLine("grunt", SLOT, "die_ass_grunt");
      check((await takeRows().count()) === 0, "the fixture already has added takes here");
      const row = page.locator("li.row-item", { hasText: CE_REF }).first();
      await row.waitFor({ timeout: 30000 });
      await row.locator(".badges").click({ position: { x: 2, y: 2 } }).catch(() => row.click());
      await page.waitForFunction(() => {
        const b = document.querySelector('[data-testid="take-add"]');
        return b && !b.disabled;
      }, null, { timeout: 15000 });
      await takes().getByTestId("take-add").click();
      await takeRows().first().waitFor({ timeout: 15000 });
      const text = await takeRows().first().innerText();
      check(text.includes(CE_REF) && /draft/.test(text), text.replace(/\s+/g, " "));
      await takes().screenshot({ path: join(OUT, "takes-section.png") });
      return text.replace(/\s+/g, " ").slice(0, 90);
    });

    await step("approve it; it stays after a reload and the list shows +1", async () => {
      await takeRows().first().getByTestId("take-approve").click();
      await takes().getByText(/Approved t-/).waitFor({ timeout: 15000 });
      await openLine("grunt", SLOT, "die_ass_grunt");
      check(/approved/.test(await takeRows().first().innerText()), "not approved after reload");
      await page.locator(`[id="mcc-${SLOT}"] [data-testid=takes-pill]`).waitFor({ timeout: 15000 });
      check(await takeRows().first().getByTestId("take-remove").isDisabled(), "an approved take can be removed");
    });

    await step("Needs rework, then remove", async () => {
      await takeRows().first().getByTestId("take-rework").click();
      await takes().getByText(/marked Needs rework/).waitFor({ timeout: 15000 });
      await takeRows().first().getByTestId("take-remove").click();
      await takes().getByText(/Removed t-/).waitFor({ timeout: 15000 });
      check((await takeRows().count()) === 0, "the take is still listed");
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
