// Browser test of replacement sets from the owner's selections (docs/replacement-set-conversion.md, 2026-10-18).
//
//   npm run test:take-sets      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the mapping data (scripts/ui/e2e_fixture.py): the Take sets page lists the multi-take
// sounds; on crewman killedenemycm (2 Spain takes that select the same recording) the line panel previews
// "2 original MCC takes -> 1 replacement take", stages it (the line decisions stay), approves the take with "Approve
// unchanged converted takes" (the list shows its two approved source lines), switches, and undoes it through its
// preview (the decisions come back with their approvals). Then the single-take sets filter and a bulk stage from the
// Take sets page. The real mappings are hashed before and after.

import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const LEVEL = "crewman";
const SLOT = "es:killedenemycm01#0";
const TAG = "sound\\dialog\\crewman\\conditional\\combat\\killingpeople\\killedenemycm";
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
    if (page) await page.screenshot({ path: join(OUT, "take-sets-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const takes = () => page.getByTestId("added-takes");
const set = () => page.getByTestId("replacement-set");
const text = async (loc) => (await loc.innerText()).replace(/\s+/g, " ");

async function openLine() {
  await page.goto(`http://localhost:${WEB_PORT}/#/match?level=${LEVEL}&slot=${encodeURIComponent(SLOT)}`);
  await page.reload();
  await takes().waitFor({ timeout: 30000 });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-take-sets-"));
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
    const confirms = handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    await step("Take sets lists the multi-take sounds with a preview of each", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/take-sets`);
      const list = page.getByTestId("take-sets");
      await list.waitFor({ timeout: 60000 });
      const row = list.locator(`tr[data-sound="${TAG.replace(/\\/g, "\\\\")}"]`);
      await row.waitFor({ timeout: 15000 });
      const t = await text(row);
      check(/2 original MCC takes -> 1 replacement take/.test(t), `row: ${t}`);
      const ready = await text(page.getByTestId("filter-ready"));
      return ready;
    });

    await step("the line panel sums the sound up and previews the set (read-only)", async () => {
      await openLine();
      const summary = await text(takes().getByTestId("sound-summary"));
      check(/2 original MCC takes, each decided on its own/.test(summary), summary);
      check((await takes().getByRole("button", { name: /ES/ }).count()) >= 2, "Spain takes not playable");
      await set().getByTestId("set-preview").click();
      await set().getByTestId("set-preview-panel").waitFor({ timeout: 15000 });
      const s = await text(set().getByTestId("set-summary"));
      check(/2 original MCC takes -> 1 replacement take \(1 duplicate selection merged\)/.test(s), s);
      check((await set().getByTestId("set-proposed").locator("li").count()) === 1, "expected one proposed take");
      await page.getByTestId("added-takes").screenshot({ path: join(OUT, "take-sets-preview.png") });
      return s;
    });

    await step("staging adds a draft take and keeps the line decisions", async () => {
      await set().getByTestId("set-stage").click();
      await set().getByTestId("set-staged").waitFor({ timeout: 20000 });
      check(/replacement set staged/i.test(await text(takes().getByTestId("sound-mode"))), "mode badge");
      await takes().getByTestId("take-staged").first().waitFor({ timeout: 10000 });
      await page.getByTestId("staged-set-line").waitFor({ timeout: 10000 });
      check(await set().getByTestId("set-activate").isDisabled(), "switch enabled with a draft take");
      check(confirms.messages.some((m) => /Nothing is approved for you/.test(m)), "no staging confirmation");
    });

    await step("Approve unchanged converted takes lists the take with its approved sources, then approves it", async () => {
      await set().getByTestId("set-approvable").click();
      const panel = set().getByTestId("set-approvable-panel");
      await panel.waitFor({ timeout: 15000 });
      const listed = await text(panel.getByTestId("approvable-included"));
      check(/killedenemycm01#0 \(approved .*killedenemycm02#0 \(approved/.test(listed), listed);
      await panel.getByTestId("approve-unchanged").click();
      await set().getByTestId("set-note").filter({ hasText: /Approved t-/ }).waitFor({ timeout: 20000 });
      check(confirms.messages.some((m) => /new approval of each take/.test(m)), "no approval confirmation");
      await set().getByTestId("set-approvable-panel").waitFor({ state: "detached", timeout: 10000 }).catch(() => {});
      return listed;
    });

    await step("the switch makes the set active", async () => {
      await page.waitForFunction(() => !document.querySelector('[data-testid="set-activate"]')?.disabled, null, { timeout: 15000 });
      await set().getByTestId("set-activate").click();
      await takes().getByTestId("own-set-badge").waitFor({ timeout: 20000 });
      const summary = await text(takes().getByTestId("sound-summary"));
      check(/2 original MCC takes → 1 replacement take/.test(summary), summary);
      await page.getByTestId("own-set-line").waitFor({ timeout: 15000 });
      return summary;
    });

    await step("undo: a preview first, then the decisions come back with their approvals", async () => {
      await set().getByTestId("set-revert-preview").click();
      const panel = set().getByTestId("set-undo-panel");
      await panel.waitFor({ timeout: 15000 });
      const shown = await text(panel);
      check(/audio approval restored/.test(shown) && !/Nothing can be undone/.test(shown), shown.slice(0, 300));
      await panel.getByTestId("set-revert").click();
      await set().getByTestId("set-note").filter({ hasText: /Undone/ }).waitFor({ timeout: 20000 });
      const note = await text(set().getByTestId("set-note"));
      check(/Undone: 2 decision\(s\) restored/.test(note), note);
      await openLine();
      const summary = await text(takes().getByTestId("sound-summary"));
      check(/each decided on its own/.test(summary), summary);
      const stored = await page.evaluate(async (slot) => (await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json()).mapping, SLOT);
      check(stored?.audio?.status === "approved" && stored?.subtitle?.status === "approved",
            `the approval did not come back: ${stored?.audio?.status}/${stored?.subtitle?.status}`);
      const badges = (await page.locator(`[id="mcc-${SLOT}"] .badges`).innerText()).replace(/\s+/g, "");
      check(/A✓/.test(badges), `row pills ${badges}`);
      return note;
    });

    await step("Take sets lists the own sets on single-take sounds apart", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/take-sets`);
      const list = page.getByTestId("take-sets");
      await list.waitFor({ timeout: 60000 });
      await page.getByTestId("filter-single_take").click();
      await list.locator("tbody tr").first().waitFor({ timeout: 15000 });
      const n = await list.locator("tbody tr").count();
      const head = await text(list.locator(".panel-head, header").first());
      check(n >= 1 && /own sets on single-take sounds/i.test(head), `${n} rows; ${head}`);
      return `${n} single-take sets; ${head}`;
    });

    await step("bulk: stage two ready sounds from the Take sets page", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/take-sets`);
      const list = page.getByTestId("take-sets");
      await list.waitFor({ timeout: 60000 });
      await page.getByTestId("filter-ready").click().catch(() => {});
      if (!(await page.getByTestId("filter-ready").getAttribute("class"))?.includes("on")) await page.getByTestId("filter-ready").click();
      const boxes = list.locator("tbody input[type=checkbox]");
      await boxes.first().waitFor({ timeout: 15000 });
      await boxes.nth(0).check();
      await boxes.nth(1).check();
      await page.getByTestId("bulk-stage").click();
      await page.getByText(/Staged 2 sound\(s\)/).waitFor({ timeout: 30000 });
      await page.waitForFunction(() => /staged\s*2/i.test(document.querySelector('[data-testid="filter-staged"]')?.textContent ?? ""),
                                 null, { timeout: 60000 });  // the list is previewed again after the stage
      await page.getByTestId("filter-staged").click();
      await list.locator("tbody tr").first().waitFor({ timeout: 15000 });
      const staged = await list.locator("tbody tr").count();
      check(staged === 2, `expected 2 staged, got ${staged}`);
      await page.screenshot({ path: join(OUT, "take-sets-page.png"), fullPage: false });
      return `${staged} staged`;
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
