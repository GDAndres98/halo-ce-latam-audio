// Browser test of the read-only Suggestions tab (docs/suggested-matching.md, owner 2026-10-23).
//
//   npm run test:suggest      (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the data (scripts/ui/e2e_fixture.py): Suggestions lists a10's sounds with scored CE lines
// (a10_010_cryotech's best is VO_SCR_M01_00460_CryoTech, its identical English line), "Open" goes to Matching with the
// MCC line open and the CE list filtered to the suggested line, and nothing is written: the disposable mappings and
// the real ones hash the same before and after. Also a phone-width screenshot.
//
// Replace and approve (owner, 2026-11-07, docs/suggested-matching.md §2f): on a grunt bark compared by sound, ticking
// variations and pressing "Submit and approve selected replacement" asks first; Cancel writes nothing; confirming
// turns the sound's replacement set on with exactly the ticked es-MX variations, approved, in the DISPOSABLE copy.
// The disposable mappings then differ only by that sound; the real ones never change.

import { mkdtemp, mkdir, readFile } from "node:fs/promises";
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
  const copyBeforeDoc = JSON.parse(await readFile(copyFile, "utf-8"));
  const services = new Services(fixture.root);
  let replaced = null;  // {tag, refs}: the one sound the replace step changed in the disposable copy
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
      // A written review (work/suggest/review/), when there is one, is shown on the card.
      const review = card.getByTestId("sound-review");
      if (await page.getByTestId("review-notes").count()) {
        check(/same recordings/.test(await text(review)), `review: ${await text(review)}`);
        check((await review.locator(".review-pick").first().getAttribute("data-ref")) ===
              "vo_sys_default_01contact_heardfoe_grunt#0", "review pick");
      }
      await page.screenshot({ path: join(OUT, "suggest-grunt.png"), fullPage: false });
      return summary;
    });

    await step("by-sound card: tick variations, Cancel writes nothing, confirm saves an approved replacement set", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/`);  // leave the page: the summary below is marines' own
      await page.getByTestId("suggest-summary").waitFor({ state: "detached", timeout: 15000 });
      await page.goto(`http://localhost:${WEB_PORT}/#/suggest?level=marines&show=all`);
      await page.getByTestId("suggest-summary").waitFor({ timeout: 60000 });
      await page.locator("section.sound").first().waitFor({ timeout: 60000 });
      const bars = page.getByTestId("replace-bar");
      if (!(await bars.count())) return "no by-sound card without a replacement set in this data: skipped";
      // A sound with per-take decisions only (no added takes, no set): the flow refuses the others, by design.
      let card = null, tag = null;
      for (const sec of await page.locator("section.sound").all()) {
        if (!(await sec.getByTestId("replace-bar").count())) continue;
        const t = await sec.getAttribute("data-sound");
        const snd = await (await page.request.get(
          `http://localhost:${WEB_PORT}/api/takes/sound?mcc_tag=${encodeURIComponent(t)}`)).json();
        if (snd.mode === "per_take" && snd.allowed) { tag = t; break; }
      }
      if (tag) card = page.locator(`section[data-sound="${tag.replace(/\\/g, "\\\\")}"]`);
      if (!card) return "no per-take by-sound card: skipped";
      const button = card.getByTestId("replace-approve");
      check(await button.isDisabled(), "the button is enabled before anything is ticked");
      const row = card.locator("tbody tr").first();
      const all = row.getByTestId("pick-all");
      if (await all.count()) await all.check(); else await row.getByTestId("pick-variation").first().check();
      const refs = [];
      for (const box of await row.getByTestId("pick-variation").all()) {
        if (await box.isChecked()) refs.push(await box.getAttribute("data-ref"));
      }
      check(refs.length > 0 && !(await button.isDisabled()), `ticked ${refs.length}`);
      const before = await sha256File(copyFile);
      await card.screenshot({ path: join(OUT, "suggest-replace-card.png") });
      await button.click();
      const dialog = page.locator("dialog.confirm-dialog");
      await dialog.waitFor({ timeout: 15000 });
      check(/ONLY these/.test(await text(dialog)), `dialog: ${await text(dialog)}`);
      await page.screenshot({ path: join(OUT, "suggest-replace-dialog.png"), fullPage: false });
      await dialog.getByRole("button", { name: "Cancel" }).click();
      check((await sha256File(copyFile)) === before, "Cancel wrote something");
      await button.click();
      await dialog.getByRole("button", { name: /^Replace and approve/ }).click();
      await page.getByText(/^Replaced: /).first().waitFor({ timeout: 30000 });
      const doc = JSON.parse(await readFile(copyFile, "utf-8"));
      const own = (doc.own_sets ?? []).find((o) => o.mcc_tag === tag);
      check(own && !own.state, "the replacement set is not in force");
      const takes = (doc.added_takes ?? []).filter((t) => t.mcc_tag === tag);
      check(JSON.stringify(takes.map((t) => t.audio.sources[0].ce_line_ref)) === JSON.stringify(refs),
            `takes ${takes.map((t) => t.audio.sources[0].ce_line_ref)} vs ticked ${refs}`);
      check(takes.every((t) => t.audio.status === "approved" && t.audio.sources[0].language === "Spanish(Mexico)"),
            "every new take approved, es-MX");
      check(!doc.slots.some((x) => x.mcc_tag === tag), "the sound's line decisions are still there");
      replaced = { tag, refs };
      return `${tag.split("\\").pop()}: ${refs.length} take(s) approved`;
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
  if (!replaced) {
    record("the page wrote nothing (disposable mappings unchanged)", copyAfter === copyBefore, copyAfter.slice(0, 16));
  } else {  // only the replaced sound changed: its decisions, takes and set; every other sound as before
    const strip = (doc) => JSON.stringify({ ...doc, slots: doc.slots.filter((x) => x.mcc_tag !== replaced.tag),
      added_takes: (doc.added_takes ?? []).filter((t) => t.mcc_tag !== replaced.tag),
      own_sets: (doc.own_sets ?? []).filter((o) => o.mcc_tag !== replaced.tag) });
    const after = JSON.parse(await readFile(copyFile, "utf-8"));
    record("only the replaced sound changed in the disposable mappings", strip(after) === strip(copyBeforeDoc),
           replaced.tag.split("\\").pop());
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
