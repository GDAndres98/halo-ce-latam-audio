// Browser test of the subtitle conflicts list on Build & Test (components/build/SubtitleConflicts.vue).
//
//   npm run test:build-conflicts      (from frontend/; needs Microsoft Edge; under a minute, nothing is built)
//
// On a disposable copy of the mapping data (scripts/ui/e2e_fixture.py): approves two different custom subtitles
// on two takes of one MCC line (one subtitle key) in the COPY, then checks that the scope preview lists the
// conflict under "Conflicts" (open, the line's short name, its key, a plain explanation, each take with the text
// it would write), that those takes are not repeated among the excluded rows, that a take links to that line in
// Matching, that every conflict the API returns for "every folder with a mapping" is shown, and that a phone
// width does not overflow. The server's game folder is an empty temporary folder (nothing is built or
// installed). The real mappings are hashed before and after.

import { mkdir, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { API_PORT, HERE, REPO, WEB_PORT, Services, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const TEXT_A = "[E2E conflicto A] Texto de prueba";
const TEXT_B = "[E2E conflicto B] Otro texto";
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
    if (page) await page.screenshot({ path: join(OUT, "build-conflicts-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
// Straight to the API server (its local listener), not through the Vite proxy: the line list is large.
const api = (path, init) =>
  fetch(`http://127.0.0.1:${API_PORT}${path}`, init).then(async (r) => ({ status: r.status, body: await r.json() }));
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** Two takes of one subtitled line whose sound plays its Spain takes (their decisions are changed in the copy). */
async function findTwoTakes() {
  const { body } = await api("/api/slots?level=all");
  const byTag = new Map();
  for (const s of body.slots) {
    if (s.permutations < 2 || s.own_set || s.channels !== 1) continue;
    byTag.set(s.mcc_tag, [...(byTag.get(s.mcc_tag) ?? []), s]);
  }
  for (const [tag, rows] of byTag) {
    if (rows.length < 2) continue;
    const details = [];
    for (const r of rows.slice(0, 2)) details.push((await api(`/api/slot?id=${encodeURIComponent(r.slot_id)}`)).body);
    // the line has a subtitle entry (key) in SU and SP; its text may be empty (text is null when the key is missing)
    const subtitled = ["SU", "SP"].every((t) => typeof details[0].mcc_subtitles?.[t]?.text === "string");
    if (subtitled && details.every((d) => !d.sound || d.sound.mode === "per_take")) return { tag, level: rows[0].level, slots: rows.slice(0, 2).map((r) => r.slot_id) };
  }
  throw new Error("no subtitled line with two takes in the copy");
}

async function approveCustom(slot, text) {
  let d = (await api(`/api/slot?id=${encodeURIComponent(slot)}`)).body;
  if (d.mapping?.subtitle.status === "approved") {  // an approved subtitle changes only after Needs rework
    const res = await post("/api/save", { slot_id: slot, loaded_sha256: d.sha256.mappings, local_sha256: d.sha256.local,
                                          actions: [{ action: "needs_rework", field: "subtitle" }] });
    check(res.status === 200, `needs rework ${slot}: ${res.status} ${res.body.error ?? ""}`);
    d = (await api(`/api/slot?id=${encodeURIComponent(slot)}`)).body;
  }
  const res = await post("/api/save", {
    slot_id: slot, loaded_sha256: d.sha256.mappings, local_sha256: d.sha256.local,
    subtitle: { source: "custom", custom_text: text }, actions: [{ action: "approve", field: "subtitle" }],
  });
  check(res.status === 200, `save ${slot}: ${res.status} ${res.body.error ?? ""}`);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-build-conflicts-"));
  const fixture = await runFixture(join(tmp, "root"));
  const game = join(tmp, "empty-game");
  await mkdir(game, { recursive: true });
  const realBefore = await sha256File(join(REPO, "mappings", "manual_mappings.json"));
  const services = new Services(fixture.root, ["--mcc-root", game, "--deploy-state", join(tmp, "deploy-state")]);
  let browser;
  let pick;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return fixture.root;
    });
    await step("two takes of one line get different approved subtitles (in the copy)", async () => {
      pick = await findTwoTakes();
      await approveCustom(pick.slots[0], TEXT_A);
      await approveCustom(pick.slots[1], TEXT_B);
      const { body } = await post("/api/builds/preview", { scope: "levels", levels: [pick.level] });
      const c = body.subtitles.conflict_list.find((x) => x.mcc_tag === pick.tag);
      check(c && c.code.endsWith("_for_one_subtitle_key"), `API conflict: ${JSON.stringify(c)?.slice(0, 300)}`);
      const textOf = (slot) => c.takes.find((t) => t.slot_id === slot)?.text;
      check(textOf(pick.slots[0]) === TEXT_A && textOf(pick.slots[1]) === TEXT_B, `API takes: ${JSON.stringify(c.takes).slice(0, 300)}`);
      return `${pick.tag} (${pick.slots.join(", ")})`;
    });

    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    page.on("pageerror", (e) => pageErrors.push(String(e.message)));
    await page.goto(`http://localhost:${WEB_PORT}/#/builds`);
    const preview = page.getByTestId("scope-preview");

    await step("the scope preview lists the conflict take by take, open, with an explanation", async () => {
      await page.getByLabel("Chosen folders").check();
      const boxes = page.locator(".level-picks input[type=checkbox]");
      for (let i = 0; i < (await boxes.count()); i++) if (await boxes.nth(i).isChecked()) await boxes.nth(i).uncheck();
      await page.locator(".level-picks label", { hasText: new RegExp(`^\\s*${pick.level}\\s*$`) }).locator("input").check();
      const short = pick.tag.split("\\").pop();
      const group = preview.getByTestId("conflict-group").filter({ hasText: short });
      await group.waitFor({ timeout: 30000 });
      check(await preview.getByTestId("preview-conflicts").evaluate((d) => d.open), "the Conflicts section is closed");
      const text = (await group.innerText()).replace(/\s+/g, " ");
      check(/different texts|keeps MCC's text/.test(text), `no explanation: ${text}`);
      check(/0x[0-9A-F]{8}/.test(text), `no key: ${text}`);
      for (const [i, t] of [TEXT_A, TEXT_B].entries()) {
        const take = group.locator(`[data-testid="conflict-take"][data-slot="${pick.slots[i]}"]`);
        check((await take.getAttribute("data-outcome")) === "text", `take ${pick.slots[i]} outcome`);
        check((await take.innerText()).includes(t), `take ${pick.slots[i]} does not show its text`);
      }
      await preview.screenshot({ path: join(OUT, "build-conflicts-preview.png") });
      return text.slice(0, 140);
    });

    await step("conflict takes are not repeated among the excluded rows", async () => {
      const excluded = preview.getByTestId("preview-excluded");
      const shown = (await excluded.count()) ? await excluded.innerText() : "";
      check(!pick.slots.some((s) => shown.includes(s)), "a conflict take is listed as excluded too");
      const badge = await preview.getByTestId("preview-subtitles").innerText();
      return badge.replace(/\s+/g, " ").match(/\d+ excluded.*conflicts?/)?.[0] ?? badge.slice(0, 80);
    });

    await step("every conflict of 'every folder with a mapping' is shown", async () => {
      await page.getByLabel("Every folder with a mapping").check();
      const { body } = await post("/api/builds/preview", { scope: "all_mapped" });
      const n = body.subtitles.conflict_list.length;
      const takes = body.subtitles.conflict_list.reduce((a, c) => a + c.takes.length, 0);
      await page.waitForFunction((k) => document.querySelectorAll('[data-testid="scope-preview"] [data-testid="conflict-group"]').length === k, n, { timeout: 30000 });
      check((await preview.getByTestId("conflict-take").count()) === takes, "take count differs from the API");
      const rows = new Set(body.subtitles.excluded_rows.filter((r) => r.category === "conflict").map((r) => r.slot_id));
      const shown = (await preview.getByTestId("preview-excluded").count()) ? await preview.getByTestId("preview-excluded").innerText() : "";
      check(![...rows].some((s) => shown.includes(s)), "a conflict row is listed as excluded too");
      return `${n} conflict(s), ${takes} takes`;
    });

    await step("the page does not overflow at phone width", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(400);
      const { sw, cw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
      check(sw <= cw, `page scrolls sideways: ${sw} > ${cw}`);
      const wide = await page.evaluate(() => [...document.querySelectorAll('[data-testid="subtitle-conflicts"] *')]
        .filter((el) => el.getBoundingClientRect().right > document.documentElement.clientWidth + 1).length);
      check(wide === 0, `${wide} conflict element(s) wider than the screen`);
      await preview.getByTestId("subtitle-conflicts").screenshot({ path: join(OUT, "build-conflicts-phone.png") });
      await page.setViewportSize({ width: 1400, height: 1000 });
      return `${sw} <= ${cw}`;
    });

    await step("a take links to that line in Matching", async () => {
      const link = preview.locator(`[data-testid="conflict-take"][data-slot="${pick.slots[1]}"] a`);
      await link.click();
      await page.waitForFunction(() => location.hash.startsWith("#/match"), null, { timeout: 15000 });
      const hash = decodeURIComponent(await page.evaluate(() => location.hash));
      check(hash.includes(`slot=${pick.slots[1]}`) && hash.includes(`level=${pick.level}`), `URL ${hash}`);
      await page.waitForFunction((s) => document.querySelector('[data-testid="mcc-key"]')?.textContent?.trim() === s, pick.slots[1], { timeout: 30000 });
      return hash;
    });
  } finally {
    await browser?.close().catch(() => {});
    await services.down();
    // the temporary folder is left in place, like the other tests: its work/ is a junction to the real one
  }
  const realAfter = await sha256File(join(REPO, "mappings", "manual_mappings.json"));
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
