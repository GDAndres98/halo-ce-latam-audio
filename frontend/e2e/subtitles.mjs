// Browser test of subtitle builds on Build & Test, into a THROW-AWAY game folder:
//   scope preview -> Build subtitles -> details -> Install -> Restore -> simulated failed install (automatic
//   restore) -> Build audio + subtitles -> Install (three files as one) -> Restore.
//
//   npm run test:subtitles     (from frontend/; needs Microsoft Edge; about 3 minutes, one real audio build)
//
// The server runs with --mcc-root pointing at a temporary copy of the game layout (the pinned original Spanish
// bank and SU/SP tables, plus a Steam appmanifest with the pinned build) and --deploy-state for its backups and
// install history. The real MCC install is never written: its bank's and tables' size and modification time
// are compared before and after. The real mappings are compared by hash. The test builds are deleted at the end.

import { copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, REPO, WEB_PORT, Services, handleConfirms, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const BANK_REL = "halo1/sound/pc/sounds_dialogs_spanish.fsb";
const SU_REL = "Data/ui/localization/SU_Halo1.bin";
const SP_REL = "Data/ui/localization/SP_Halo1.bin";
const STAMP = Date.now().toString(36);
const SUBS = `e2e_subs_${STAMP}`;
const BOTH = `e2e_both_${STAMP}`;
const results = [];
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
    if (page) await page.screenshot({ path: join(OUT, "subtitles-failed.png"), fullPage: true }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const hash = (path) =>
  new Promise((done, fail) => {
    const h = createHash("sha256");
    createReadStream(path).on("data", (c) => h.update(c)).on("end", () => done(h.digest("hex"))).on("error", fail);
  });

async function sandboxGame(base) {
  const game = join(base, "steamapps", "common", "Halo The Master Chief Collection");
  await mkdir(join(game, "halo1", "sound", "pc"), { recursive: true });
  await mkdir(join(game, "Data", "ui", "localization"), { recursive: true });
  const pins = JSON.parse(await readFile(join(REPO, "work", "mcc", "build.json"), "utf-8")).files;
  await copyFile(join(REPO, pins["spanish.fsb"].copy), join(game, BANK_REL));
  for (const t of ["SU", "SP"]) await copyFile(join(REPO, "work/mcc/loc/copies", `${t}_Halo1.bin`), join(game, "Data/ui/localization", `${t}_Halo1.bin`));
  await writeFile(join(base, "steamapps", "appmanifest_976730.acf"),
    '"AppState"\n{\n\t"appid"\t\t"976730"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"Halo The Master Chief Collection"\n\t"buildid"\t\t"19905945"\n}\n');
  const originals = {};
  for (const rel of [BANK_REL, SU_REL, SP_REL]) originals[rel] = await hash(join(game, rel));
  return { game, originals };
}

/** Size and modification time of the real game's bank and tables (never their content: they are not read). */
async function realGameStat() {
  const env = await readFile(join(REPO, ".env"), "utf-8").catch(() => "");
  const m = env.match(/^HALO_MCC_FOLDER\s*=\s*"?([^"\r\n]+)"?/m);
  if (!m || !existsSync(join(m[1], BANK_REL))) return null;
  const out = [];
  for (const rel of [BANK_REL, SU_REL, SP_REL]) {
    const s = await stat(join(m[1], rel)).catch(() => null);
    out.push(s ? `${s.size}:${s.mtimeMs}` : "missing");
  }
  return out.join("|");
}

let lastJobId = null;
async function waitJob(kind, timeout) {
  const box = page.getByTestId("job");
  await page.waitForFunction(([k, prev]) => {
    const el = document.querySelector('[data-testid="job"]');
    return el && el.dataset.kind === k && el.dataset.id !== prev && el.dataset.state !== "running";
  }, [kind, lastJobId], { timeout });
  lastJobId = await box.getAttribute("data-id");
  return { state: await box.getAttribute("data-state"), log: await box.locator("pre").innerText().catch(() => "") };
}

async function manifest(name) {
  return JSON.parse(await readFile(join(REPO, "work", "m6", name, "build_manifest.json"), "utf-8"));
}

async function gameHashes(game) {
  const out = {};
  for (const rel of [BANK_REL, SU_REL, SP_REL]) out[rel] = await hash(join(game, rel));
  return out;
}

async function installFromPage(build, confirms) {
  await page.locator(`tr[data-build="${build}"]`).getByRole("button", { name: /Install to MCC/ }).click();
  const { state, log } = await waitJob("install", 5 * 60 * 1000);
  check(state === "done", `install ${state}: ${log.slice(-400)}`);
  return { log, confirm: confirms.messages.at(-1) ?? "" };
}

async function restoreFromPage() {
  await page.getByRole("button", { name: /Restore originals/ }).click();
  const { state, log } = await waitJob("restore", 5 * 60 * 1000);
  check(state === "done", `restore ${state}: ${log.slice(-400)}`);
  await page.getByTestId("deploy-status").getByText("original game files").waitFor({ timeout: 15000 });
  return log;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-subtitles-"));
  const fixture = await runFixture(join(tmp, "root"));
  const { game, originals } = await sandboxGame(join(tmp, "steam"));
  const state = join(tmp, "deploy-state");
  const realBefore = await realGameStat();
  const realMappings = await sha256File(join(REPO, "mappings", "manual_mappings.json"));
  const services = new Services(fixture.root, ["--mcc-root", game, "--deploy-state", state]);
  let browser;

  try {
    await step("start the Studio with a throw-away game folder", async () => {
      await services.up();
      return game;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
    const confirms = handleConfirms(page);
    await page.goto(`http://localhost:${WEB_PORT}/#/builds`);
    await page.getByTestId("deploy-status").getByText("original game files").waitFor({ timeout: 30000 });

    let previewEntries = 0;
    await step("the scope preview counts approved subtitle decisions and the build buttons are enabled", async () => {
      const preview = page.getByTestId("scope-preview");
      await preview.getByTestId("preview-entries").waitFor({ timeout: 30000 });
      previewEntries = Number(await preview.getByTestId("preview-entries").innerText());
      const approved = Number(await preview.getByTestId("preview-approved").innerText());
      check(previewEntries > 0 && approved >= previewEntries, `preview: ${approved} approved, ${previewEntries} entries`);
      for (const label of [/^\s*Build audio\s*$/, /Build subtitles/, /Build audio \+ subtitles/]) {
        check(!(await page.getByRole("button", { name: label }).isDisabled()), `${label} is disabled`);
      }
      check(!(await page.getByRole("button", { name: /Build subtitles/ }).innerText()).includes("Lock"), "still locked");
      return `mission a10: ${approved} approved subtitle decision(s), ${previewEntries} entries`;
    });

    await step("the preview follows the scope (a folder with no approved subtitles disables subtitle builds)", async () => {
      await page.getByLabel("Chosen folders").check();
      const boxes = page.locator(".level-picks input[type=checkbox]");
      // keep only one generic folder that the real data has no approved subtitle text for (if one exists)
      const res = await page.evaluate(async () => {
        const st = await (await fetch("/api/state")).json();
        for (const l of st.levels.map((x) => x.level)) {
          const r = await fetch("/api/builds/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope: "levels", levels: [l] }) });
          const p = await r.json();
          if (p.subtitles && p.subtitles.keys_to_write === 0) return l;
        }
        return null;
      });
      if (!res) return "every folder has subtitle text (skipped)";
      for (let i = 0; i < (await boxes.count()); i++) if (await boxes.nth(i).isChecked()) await boxes.nth(i).uncheck();
      await page.locator(".level-picks label", { hasText: new RegExp(`^\\s*${res}\\s*$`) }).locator("input").check();
      await page.waitForFunction(() => document.querySelector('[data-testid="preview-entries"]')?.textContent?.trim() === "0", null, { timeout: 15000 });
      check(await page.getByRole("button", { name: /Build subtitles/ }).isDisabled(), "subtitle build offered with nothing approved");
      await page.getByLabel("Mission (its folder").check();
      await page.waitForFunction(() => Number(document.querySelector('[data-testid="preview-entries"]')?.textContent) > 0, null, { timeout: 15000 });
      return `folder ${res}: 0 entries, Build subtitles disabled`;
    });

    await step("Build subtitles for mission a10 from the page", async () => {
      await page.getByLabel("Build name").fill(SUBS);
      await page.getByRole("button", { name: /Build subtitles/ }).click();
      const { state: s, log } = await waitJob("build", 5 * 60 * 1000);
      check(s === "done", `build ${s}: ${log.slice(-400)}`);
      const row = page.locator(`tr[data-build="${SUBS}"]`);
      await row.waitFor({ timeout: 15000 });
      const text = await row.innerText();
      check(text.includes("passed") && text.includes("Subtitles") && text.includes("SU_Halo1.bin") && text.includes("SP_Halo1.bin"),
        `row: ${text.replace(/\s+/g, " ").slice(0, 200)}`);
      const m = await manifest(SUBS);
      check(m.kind === "subtitles" && m.install_files.length === 2, "manifest is not a two-table subtitle build");
      check(m.install_files.every((f) => f.install_rel !== BANK_REL), "a subtitle build lists the bank");
      const report = JSON.parse(await readFile(join(REPO, "work", "m6", SUBS, "validation_report.json"), "utf-8"));
      const checks = Object.entries(report.checks);
      check(report.ok && checks.every(([, v]) => v), `failed checks: ${checks.filter(([, v]) => !v).map(([k]) => k)}`);
      for (const f of m.install_files) check((await hash(join(REPO, f.candidate))) === f.candidate_sha256, `${f.candidate} hash`);
      const written = m.subtitles.summary.keys_to_write;
      check(written > 0, "nothing written");
      return `${written} entries per table (preview ${previewEntries}); ${checks.length}/${checks.length} checks`;
    });

    await step("the build's details show both tables, the written entries and the exclusions", async () => {
      await page.getByRole("button", { name: `Details of ${SUBS}` }).click();
      const detail = page.getByTestId("build-detail");
      await detail.getByTestId("detail-tables").waitFor({ timeout: 15000 });
      const tables = await detail.getByTestId("detail-tables").innerText();
      check(tables.includes("SU_Halo1.bin") && tables.includes("SP_Halo1.bin") && tables.includes("3400"), `tables: ${tables}`);
      await detail.getByTestId("detail-written").locator("summary").click();
      const rows = await detail.getByTestId("detail-written").locator("tbody tr").count();
      check(rows > 0, "no written entries listed");
      await detail.getByRole("button", { name: /Build log/ }).click();
      await detail.getByTestId("detail-log").waitFor({ timeout: 10000 });
      check((await detail.getByTestId("detail-log").innerText()).includes("PASS"), "log does not show PASS");
      return `${rows} entries listed`;
    });

    await step("Install the subtitle build to MCC after a confirmation listing both tables", async () => {
      const m = await manifest(SUBS);
      const { log, confirm } = await installFromPage(SUBS, confirms);
      check(confirm.includes(SU_REL) && confirm.includes(SP_REL) && confirm.includes(game), `confirmation: ${confirm.slice(0, 200)}`);
      check(confirm.includes("still to be confirmed in the game"), "confirmation does not say runtime is unverified");
      const now = await gameHashes(game);
      for (const f of m.install_files) check(now[f.install_rel] === f.candidate_sha256, `${f.install_rel} is not the candidate`);
      check(now[BANK_REL] === originals[BANK_REL], "a subtitle install changed the bank");
      check(existsSync(join(state, "backup", "19905945", SU_REL)) && existsSync(join(state, "backup", "19905945", SP_REL)), "no table backups");
      await page.getByTestId("deploy-status").getByText(`build ${SUBS}`).first().waitFor({ timeout: 15000 });
      const history = page.getByTestId("deploy-history");
      await history.locator('li[data-action="install"][data-result="ok"]').first().waitFor({ state: "attached", timeout: 10000 });
      return log.split("\n").find((l) => l.startsWith("INSTALL OK"))?.slice(0, 100);
    });

    await step("Restore originals restores both tables", async () => {
      const log = await restoreFromPage();
      check((await gameHashes(game))[SU_REL] === originals[SU_REL] && (await gameHashes(game))[SP_REL] === originals[SP_REL], "tables are not the originals");
      check(log.includes("hashed files changed vs preflight: none"), "rollback reported other changed files");
      return log.split("\n").find((l) => l.startsWith("ROLLBACK OK"));
    });

    await step("a failure part-way through an install restores every original automatically", async () => {
      const res = await page.evaluate(async (b) => {
        const r = await fetch("/api/deploy/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ build: b, confirm: true, simulate_failure_after: 1 }) });
        return { status: r.status, job: await r.json() };
      }, SUBS);
      check(res.status === 202, `start answered ${res.status}: ${JSON.stringify(res.job).slice(0, 200)}`);
      let job = res.job;
      for (let i = 0; i < 240 && job.state === "running"; i++) {
        await page.waitForTimeout(500);
        job = await page.evaluate(async (id) => (await fetch(`/api/job?id=${id}`)).json(), job.id);
      }
      check(job.state === "failed" && job.log_tail.includes("originals restored and verified"), `job ${job.state}: ${job.log_tail.slice(-300)}`);
      const now = await gameHashes(game);
      check(Object.entries(originals).every(([rel, h]) => now[rel] === h), "a file is not the original after the failed install");
      await page.reload();
      const history = page.getByTestId("deploy-history");
      await history.locator('li[data-action="install"][data-result="failed"]').first().waitFor({ state: "attached", timeout: 15000 });
      check(await history.evaluate((el) => el.open), "the history does not open on a failed install");
      return job.log_tail.split("\n").find((l) => l.includes("STOP"))?.slice(0, 110);
    });

    await step("the real game folder refuses a simulated failure (test mode only)", async () => {
      // This server is in test mode, so the API accepts the flag; the installer itself refuses it for the real
      // folder (checked by running it without --mcc-root, which never gets past argument checks).
      const { spawnSync } = await import("node:child_process");
      const r = spawnSync("python", ["scripts/build/m6_install.py", "--build", SUBS, "--simulate-failure-after", "0", "status"], { cwd: REPO, encoding: "utf-8" });
      check(r.status !== 0 && /only for a throw-away game folder/.test(r.stdout + r.stderr), `installer answered ${r.status}: ${(r.stdout + r.stderr).slice(-200)}`);
    });

    await step("Build audio + subtitles for folder a10 from the page", async () => {
      await page.getByLabel("Chosen folders").check();
      const boxes = page.locator(".level-picks input[type=checkbox]");
      for (let i = 0; i < (await boxes.count()); i++) if (await boxes.nth(i).isChecked()) await boxes.nth(i).uncheck();
      await page.locator(".level-picks label", { hasText: /^\s*a10\s*$/ }).locator("input").check();
      await page.getByLabel("Build name").fill(BOTH);
      await page.getByRole("button", { name: /Build audio \+ subtitles/ }).click();
      const { state: s, log } = await waitJob("build", 20 * 60 * 1000);
      check(s === "done", `build ${s}: ${log.slice(-400)}`);
      const row = page.locator(`tr[data-build="${BOTH}"]`);
      await row.waitFor({ timeout: 15000 });
      const text = await row.innerText();
      check(text.includes("passed") && text.includes("Audio + subtitles"), `row: ${text.replace(/\s+/g, " ").slice(0, 200)}`);
      const m = await manifest(BOTH);
      check(m.kind === "both" && m.install_files.map((f) => f.install_rel).join() === [BANK_REL, SU_REL, SP_REL].join(), "manifest files");
      return log.split("\n").find((l) => l.startsWith("PASS"));
    });

    await step("Install the combined build: bank and both tables as one operation", async () => {
      const m = await manifest(BOTH);
      const { confirm } = await installFromPage(BOTH, confirms);
      check([BANK_REL, SU_REL, SP_REL].every((rel) => confirm.includes(rel)), "confirmation does not list all three files");
      const now = await gameHashes(game);
      for (const f of m.install_files) check(now[f.install_rel] === f.candidate_sha256, `${f.install_rel} is not the candidate`);
      await page.getByTestId("deploy-status").getByText(`build ${BOTH}`).first().waitFor({ timeout: 15000 });
      check(await page.locator(`tr[data-build="${SUBS}"]`).getByRole("button", { name: /Install to MCC/ }).isDisabled(),
        "another build can be installed on top");
      return "3 files = candidates";
    });

    await step("Restore originals restores all three files", async () => {
      await restoreFromPage();
      const now = await gameHashes(game);
      check(Object.entries(originals).every(([rel, h]) => now[rel] === h), "not every file is the original");
      return "bank, SU and SP = originals";
    });
    await page.getByRole("button", { name: `Details of ${BOTH}` }).click();
    await page.screenshot({ path: join(OUT, "subtitles.png"), fullPage: true });
  } catch (e) {
    record("subtitle test stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
    for (const b of [SUBS, BOTH]) {
      await rm(join(REPO, "work", "m6", b), { recursive: true, force: true });
      await rm(join(REPO, "work", "m6", `${b}_build.log`), { force: true });
    }
  }

  await step("the real MCC install and the real mappings were not touched", async () => {
    check((await realGameStat()) === realBefore, "the real bank or tables changed size or modification time");
    check((await sha256File(join(REPO, "mappings", "manual_mappings.json"))) === realMappings, "real mappings changed");
    check((await sha256File(join(fixture.real_mappings, "manual_mappings.json"))) === fixture.real_mappings_sha256, "real mappings changed");
    return realBefore ? "real bank and tables: size/mtime unchanged" : "no real MCC folder configured";
  });
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "subtitles-report.json"), JSON.stringify({ results }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
