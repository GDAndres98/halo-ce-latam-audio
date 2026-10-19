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
const mine = () => takeRows().filter({ hasText: CE_REF });
let base = 0; // takes the copied mappings already have on this sound

/** Waits until every row of the picker inside `testId` matches `text` (the search result arrived). */
async function pickerShows(testId, text) {
  await page.waitForFunction(([sel, t]) => {
    const picker = document.querySelector(`[data-testid="${sel}"] [data-testid="take-picker"]`);
    const rows = picker ? [...picker.querySelectorAll(".pick-list li")] : [];
    const input = picker?.querySelector('[data-testid="take-picker-search"]');
    return rows.length > 0 && input?.value === t && !/Loading/.test(picker.textContent) &&
      rows[0].textContent.toLowerCase().includes(t.toLowerCase());
  }, [testId, text], { timeout: 15000 });
}

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
      base = await takeRows().count();
      check((await mine().count()) === 0, "the fixture already has this recording as a take");
      const row = page.locator("li.row-item", { hasText: CE_REF }).first();
      await row.waitFor({ timeout: 30000 });
      await row.locator(".badges").click({ position: { x: 2, y: 2 } }).catch(() => row.click());
      await page.waitForFunction(() => {
        const b = document.querySelector('[data-testid="take-add"]');
        return b && !b.disabled;
      }, null, { timeout: 15000 });
      await takes().getByTestId("take-add").click();
      await mine().first().waitFor({ timeout: 15000 });
      const text = await mine().first().innerText();
      check(text.includes(CE_REF) && /draft/.test(text), text.replace(/\s+/g, " "));
      await takes().screenshot({ path: join(OUT, "takes-section.png") });
      return text.replace(/\s+/g, " ").slice(0, 90);
    });

    await step("approve it; it stays after a reload and the list shows +1", async () => {
      await mine().first().getByTestId("take-approve").click();
      await takes().getByText(/Approved t-/).waitFor({ timeout: 15000 });
      await openLine("grunt", SLOT, "die_ass_grunt");
      check(/approved/.test(await mine().first().innerText()), "not approved after reload");
      await page.locator(`[id="mcc-${SLOT}"] [data-testid=takes-pill]`).waitFor({ timeout: 15000 });
      check(await mine().first().getByTestId("take-remove").isDisabled(), "an approved take can be removed");
    });

    await step("Needs rework, then remove", async () => {
      await mine().first().getByTestId("take-rework").click();
      await takes().getByText(/marked Needs rework/).waitFor({ timeout: 15000 });
      await mine().first().getByTestId("take-remove").click();
      await takes().getByText(/Removed t-/).waitFor({ timeout: 15000 });
      check((await takeRows().count()) === base, "the take is still listed");
    });

    await step("lines of the same sound: 'Spain take n/N', a bracket in the list, 'this line' in the panel", async () => {
      const first = page.locator(`[id="mcc-${SLOT}"]`);
      const second = page.locator(`[id="mcc-es:deathviolent%2002#1"]`);
      check((await first.getByTestId("take-of").innerText()) === "Spain take 1/2", "first row label");
      check((await second.getByTestId("take-of").innerText()) === "Spain take 2/2", "second row label");
      check(/grp-first/.test(await first.getAttribute("class")) && /grp-last/.test(await second.getAttribute("class")), "no bracket");
      check(/Spain take 1 of 2 of this sound/.test(await page.getByTestId("take-of-sound").innerText()), "panel line");
      check((await takes().locator("li.take.here").getAttribute("data-slot")) === SLOT, "'this line' marks another take");
      await page.locator(".column.mcc").screenshot({ path: join(OUT, "takes-list-group.png") });
    });

    await step("Add several takes: tick recordings in the picker and add them in one save", async () => {
      await takes().getByTestId("take-add-several").click();
      const picker = takes().getByTestId("take-picker");
      await picker.getByTestId("take-picker-search").fill("die_ass_grunt");
      await pickerShows("added-takes", "die_ass_grunt");
      check((await picker.locator('[data-testid="take-pick"]:checked').count()) === 0, "something was pre-ticked");
      const boxes = picker.locator('[data-testid="take-pick"]:not([disabled])');
      const n = Math.min(3, await boxes.count());
      check(n >= 2, `only ${n} pickable recordings`);
      for (let i = 0; i < n; i++) await boxes.nth(i).check();
      await picker.getByTestId("take-picker-add").click();
      await takes().getByText(new RegExp(`Added ${n} takes as drafts`)).waitFor({ timeout: 15000 });
      check((await takeRows().count()) === base + n, `expected ${base + n} takes, got ${await takeRows().count()}`);
      check(!(await takes().getByTestId("take-picker").isVisible().catch(() => false)), "the picker stayed open");
      await openLine("grunt", SLOT, "die_ass_grunt");
      check((await takeRows().count()) === base + n, "the takes are gone after a reload");
      return `${n} takes added`;
    });

    await step("Add as extra take works again for a second recording", async () => {
      const before = await takeRows().count();
      const rows = page.locator("li.row-item", { hasText: "die_ass_grunt" });
      await rows.first().waitFor({ timeout: 30000 });
      const count = await rows.count();
      for (let i = 0; i < count; i++) {
        const row = rows.nth(i);
        await row.locator(".badges").click({ position: { x: 2, y: 2 } }).catch(() => row.click());
        const ok = await page.waitForFunction(() => {
          const b = document.querySelector('[data-testid="take-add"]');
          return b && !b.disabled;
        }, null, { timeout: 2000 }).then(() => true, () => false);
        if (ok) {
          await takes().getByTestId("take-add").click();
          await page.waitForFunction((n) => document.querySelectorAll('[data-testid="added-take"]').length === n + 1, before, { timeout: 15000 });
          return `${before} -> ${before + 1}`;
        }
      }
      throw new Error("no recording could be added one at a time");
    });

    await step("4th audio option: lists the Spain takes it replaces (playable), several recordings, then back", async () => {
      await openLine("grunt", SLOT, "die_ass_grunt");
      if (await page.getByTestId("whole-sound-option").isChecked()) {  // the copied data may already have it on
        await page.getByTestId("whole-sound").getByTestId("own-set-off").click();
        await page.getByTestId("whole-sound").waitFor({ state: "detached", timeout: 15000 });
      }
      const n = await takeRows().count();
      await page.getByTestId("whole-sound-option").check();
      const panel = page.getByTestId("whole-sound");
      await panel.waitFor({ timeout: 15000 });
      const replaced = panel.getByTestId("whole-sound-replaced").locator("li");
      check((await replaced.count()) === 2, `expected 2 Spain takes, got ${await replaced.count()}`);
      check((await replaced.first().getByRole("button", { name: /ES/ }).count()) === 1, "no Spain player");
      check(/this line/.test(await replaced.first().innerText()), "this line not marked");
      const playing = page.waitForResponse((r) => r.url().includes("/audio/mcc"), { timeout: 15000 });
      await replaced.nth(1).getByRole("button", { name: /ES/ }).click();
      check((await playing).status() < 400, "Spain audio did not load");
      await page.keyboard.press("Escape");
      await panel.getByTestId("take-picker-search").fill("dth_fall_grunt");
      await pickerShows("whole-sound", "dth_fall_grunt");
      const boxes = panel.locator('[data-testid="take-pick"]:not([disabled])');
      const k = Math.min(2, await boxes.count());
      check(k > 0, "no free Grunt recording to tick");
      for (let i = 0; i < k; i++) await boxes.nth(i).check();
      await panel.getByTestId("take-picker-add").click();
      await page.getByTestId("whole-sound").getByText(/Every take replaced/).waitFor({ timeout: 20000 }).catch(async (e) => {
        throw new Error(`no note; panel: ${(await page.getByTestId("whole-sound").innerText()).replace(/\s+/g, " ").slice(-300)}`);
      });
      await takes().getByTestId("own-set-badge").waitFor({ timeout: 15000 });
      check((await takeRows().count()) === n + k, `expected ${n + k} takes, got ${await takeRows().count()}`);
      check((await takes().locator("li.take.spain.removed").count()) === 2, "Spain takes not marked removed");
      await page.getByTestId("own-set-line").waitFor({ timeout: 15000 });
      check(await page.getByTestId("whole-sound-option").isChecked(), "4th option not checked while on");
      check(await page.getByTestId("keep-spain").isDisabled(), "the line's own options are not locked");
      await page.getByTestId("own-set-savebar").waitFor({ timeout: 15000 });
      check((await page.getByRole("button", { name: /Approve audio/ }).count()) === 0, "line approve buttons still shown");
      await page.locator(`[id="mcc-${SLOT}"] [data-testid=own-set-pill]`).waitFor({ timeout: 15000 });
      const badges = (await page.locator(`[id="mcc-${SLOT}"] .badges`).innerText()).replace(/\s+/g, "");
      check(badges.startsWith("M✓") && badges.includes("S⊘") && !badges.includes("M–"), `row pills ${badges}`);
      await page.getByTestId("whole-sound").screenshot({ path: join(OUT, "takes-whole-sound.png") });
      await page.getByTestId("whole-sound").getByTestId("own-set-off").click();
      await page.getByTestId("whole-sound").waitFor({ state: "detached", timeout: 15000 });
      check((await takes().locator("li.take.spain.removed").count()) === 0, "still marked removed");
      check(!(await page.getByTestId("whole-sound-option").isChecked()), "4th option still checked");
      return `${k} recordings added, ${n + k} takes`;
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
