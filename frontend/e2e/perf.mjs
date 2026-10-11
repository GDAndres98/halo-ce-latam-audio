// Browser benchmark of the repeated matching workflow (prompt 38), on disposable data.
//
//   npm run perf              (from frontend/; needs Microsoft Edge)   PERF_ITERATIONS=8 PERF_LABEL=after
//
// For several undecided MCC lines in turn, in the Studio and in the classic M4 page:
//   select the line -> search a Campaign Evolved recording -> use it -> save the draft
// Each step is timed until the page shows its result (the line's heading and the original waveform, the
// candidate row, the confirmation). The first iteration is reported apart (cold: nothing cached yet).
// Also times opening the workspace, switching level and moving to the next line with the keyboard.
// Results: e2e/out/perf_<label>.json. Writes only to the disposable copy; the real mappings are checked.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { API_PORT, HERE, WEB_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const ITERATIONS = Number(process.env.PERF_ITERATIONS ?? 8);
const LABEL = process.env.PERF_LABEL ?? "run";
const LEVEL = process.env.PERF_LEVEL ?? "a30";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const CE_QUERY = "00460_cryotech";

const now = () => performance.now();
async function timed(fn) {
  const t = now();
  await fn();
  return now() - t;
}
function stats(values) {
  const warm = values.slice(1).sort((a, b) => a - b);
  const pick = (q) => warm[Math.min(warm.length - 1, Math.round(q * (warm.length - 1)))];
  return { cold_ms: Math.round(values[0]), median_ms: Math.round(pick(0.5)), p95_ms: Math.round(pick(0.95)), n: values.length };
}

async function undecidedLines(n) {
  const res = await fetch(`http://127.0.0.1:${API_PORT}/api/slots?level=${LEVEL}&status=undecided`);
  const body = await res.json();
  const rows = body.slots.filter((r) => r.channels === 1).slice(0, n);
  if (rows.length < n) throw new Error(`only ${rows.length} undecided mono lines in ${LEVEL}`);
  return rows;
}

async function studio(browser, lines) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  try {
    return await studioSteps(page, lines);
  } catch (e) {
    await page.screenshot({ path: join(OUT, "perf-failed.png") }).catch(() => {});
    throw new Error(`${stage}: ${String(e.message ?? e).split(String.fromCharCode(10))[0]}`);
  }
}

let stage = "";
async function studioSteps(page, lines) {
  page.on("dialog", (d) => d.accept());
  handleConfirms(page);
  const steps = { select: [], search: [], use: [], save: [], total: [] };
  const extra = {};
  extra.open_workspace_ms = Math.round(await timed(async () => {
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=${LEVEL}&status=undecided`);
    await page.locator("li.row-item").first().waitFor({ timeout: 60000 });
  }));
  for (const row of lines) {
    const t0 = now();
    stage = "select " + row.slot_id;
    steps.select.push(await timed(async () => {
      await page.locator(`[id="mcc-${row.slot_id}"]`).click();
      await page.getByRole("heading", { level: 2, name: row.tag_name }).waitFor({ timeout: 30000 });
      // A live query (the comparison is rebuilt for each line, so an element handle could be the old one).
      await page.waitForFunction(
        (slot) => {
          const host = document.querySelector('[aria-label="Compare the original and the replacement"] [data-testid="wave-host"]');
          return document.querySelector(".line-title p")?.textContent?.includes(slot) && Number(host?.dataset.duration) > 0;
        },
        row.slot_id,
        { timeout: 30000 },
      );
    }));
    const search = page.getByPlaceholder(/Partial words/);
    // Start from a search with no results, so the timed search really has to fetch the recording.
    await search.fill("zzqx_no_match");
    await page.getByText("No recordings match.").waitFor({ timeout: 30000 });
    stage = "search " + row.slot_id;
    steps.search.push(await timed(async () => {
      await search.fill(CE_QUERY);
      await page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).waitFor({ timeout: 30000 });
    }));
    stage = "use " + row.slot_id;
    steps.use.push(await timed(async () => {
      await page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).click();
      await page.getByText("Recording chosen").waitFor({ timeout: 10000 });
    }));
    stage = "save " + row.slot_id;
    steps.save.push(await timed(async () => {
      await page.getByRole("button", { name: /^Save draft/ }).click();
      await page.getByText("Draft saved.").waitFor({ timeout: 30000 });
    }));
    steps.total.push(now() - t0);
  }
  // Keyboard: next line (j) until the heading changes.
  const nav = [];
  for (let i = 0; i < Math.min(6, lines.length); i++) {
    const before = await page.locator(".line-title h2").innerText();
    nav.push(await timed(async () => {
      await page.locator(".line-title h2").click();
      await page.keyboard.press("j");
      await page.waitForFunction((b) => document.querySelector(".line-title h2")?.textContent !== b, before, { timeout: 15000 });
    }));
  }
  extra.next_line_keyboard = stats(nav);
  extra.switch_level_ms = Math.round(await timed(async () => {
    await page.locator("select").first().selectOption("a50");
    await page.waitForResponse((r) => r.url().includes("/api/slots") && r.url().includes("level=a50"), { timeout: 30000 });
    await page.locator("li.row-item").first().waitFor();
  }));
  await page.close();
  return { app: "Studio", steps: Object.fromEntries(Object.entries(steps).map(([k, v]) => [k, stats(v)])), ...extra };
}

async function classic(browser, lines) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  page.on("dialog", (d) => d.accept());
  const steps = { select: [], search: [], use: [], save: [], total: [] };
  await page.goto(`http://127.0.0.1:${API_PORT}/`);
  await page.locator("#slots").waitFor({ timeout: 60000 });
  // The classic page opens a level from its selector.
  const levelSelect = page.locator("select").first();
  await levelSelect.selectOption(LEVEL).catch(() => {});
  await page.waitForTimeout(500);
  for (const row of lines) {
    const t0 = now();
    steps.select.push(await timed(async () => {
      await page.locator("#slots").getByText(row.tag_name, { exact: false }).first().click();
      await page.getByText(row.slot_id).first().waitFor({ timeout: 30000 });
    }));
    await page.locator("#cq").fill("zzqx_no_match");
    await page.locator(`[data-use="${CE_REF}"]`).waitFor({ state: "detached", timeout: 30000 });
    steps.search.push(await timed(async () => {
      await page.locator("#cq").fill(CE_QUERY);
      await page.locator(`[data-use="${CE_REF}"]`).waitFor({ timeout: 30000 });
    }));
    steps.use.push(await timed(async () => {
      await page.locator(`[data-use="${CE_REF}"]`).click();
    }));
    steps.save.push(await timed(async () => {
      const answered = page.waitForResponse((r) => r.url().includes("/api/save") && r.request().method() === "POST", { timeout: 30000 });
      await page.locator("#save").click();
      const res = await answered;
      if (res.status() !== 200) throw new Error(`classic save ${res.status()}`);
    }));
    steps.total.push(now() - t0);
  }
  await page.close();
  return { app: "classic M4", steps: Object.fromEntries(Object.entries(steps).map(([k, v]) => [k, stats(v)])) };
}

async function isolated(run) {
  const fixture = await runFixture(join(await mkdtemp(join(tmpdir(), "studio-perf-")), "root"));
  const services = new Services(fixture.root);
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const lines = await undecidedLines(ITERATIONS);
    return { ...(await run(browser, lines)), realBefore: fixture.real_mappings_sha256, real: fixture.real_mappings };
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const results = [];
  for (const run of [studio, classic]) {
    try {
      results.push(await isolated(run));
    } catch (e) {
      results.push({ app: run.name, error: String(e.message ?? e).split("\n")[0] });
    }
  }
  const ok = results.find((r) => r.real);
  const unchanged = ok ? (await sha256File(join(ok.real, "manual_mappings.json"))) === ok.realBefore : null;
  for (const r of results) {
    delete r.real;
    delete r.realBefore;
    if (r.error) {
      console.log(`${r.app}: ERROR ${r.error}`);
      continue;
    }
    console.log(`== ${r.app}`);
    for (const [k, v] of Object.entries(r.steps)) console.log(`  ${k.padEnd(8)} cold ${String(v.cold_ms).padStart(6)}  median ${String(v.median_ms).padStart(6)}  p95 ${String(v.p95_ms).padStart(6)} ms`);
    for (const k of ["open_workspace_ms", "switch_level_ms"]) if (r[k] !== undefined) console.log(`  ${k} ${r[k]}`);
    if (r.next_line_keyboard) console.log(`  next line (j) median ${r.next_line_keyboard.median_ms} p95 ${r.next_line_keyboard.p95_ms} ms`);
  }
  console.log(`real mappings unchanged: ${unchanged}`);
  await writeFile(join(OUT, `perf_${LABEL}.json`), JSON.stringify({ label: LABEL, iterations: ITERATIONS, level: LEVEL, results, real_mappings_unchanged: unchanged }, null, 2));
  process.exitCode = results.some((r) => r.error) || unchanged === false ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
