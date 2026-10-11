// Browser test of Build & Test: build -> install -> restore, entirely from the page, into a THROW-AWAY game folder.
//
//   npm run test:deploy       (from frontend/; needs Microsoft Edge; about 2 minutes, one real audio build)
//
// The server is started with --mcc-root pointing at a temporary copy of the game layout (the pinned original
// Spanish bank and SU/SP tables, plus a Steam appmanifest with the pinned build), and --deploy-state for its
// backups. The real MCC install is never written: its bank's size and modification time are compared before
// and after. The test build folder in work/m6/ is deleted at the end.

import { copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, REPO, WEB_PORT, Services, handleConfirms, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const BANK_REL = "halo1/sound/pc/sounds_dialogs_spanish.fsb";
const BUILD = `e2e_deploy_${Date.now().toString(36)}`;
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
    if (page) await page.screenshot({ path: join(OUT, "deploy-failed.png"), fullPage: true }).catch(() => {});
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

/** A minimal game layout: what m6_install reads and hashes, with the pinned originals. */
async function sandboxGame(base) {
  const game = join(base, "steamapps", "common", "Halo The Master Chief Collection");
  await mkdir(join(game, "halo1", "sound", "pc"), { recursive: true });
  await mkdir(join(game, "Data", "ui", "localization"), { recursive: true });
  const pins = JSON.parse(await readFile(join(REPO, "work", "mcc", "build.json"), "utf-8")).files;
  await copyFile(join(REPO, pins["spanish.fsb"].copy), join(game, BANK_REL));
  for (const t of ["SU", "SP"]) await copyFile(join(REPO, "work/mcc/loc/copies", `${t}_Halo1.bin`), join(game, "Data/ui/localization", `${t}_Halo1.bin`));
  await writeFile(join(base, "steamapps", "appmanifest_976730.acf"),
    '"AppState"\n{\n\t"appid"\t\t"976730"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"Halo The Master Chief Collection"\n\t"buildid"\t\t"19905945"\n}\n');
  return { game, original: pins["spanish.fsb"].sha256 };
}

async function realBankStat() {
  const env = await readFile(join(REPO, ".env"), "utf-8").catch(() => "");
  const m = env.match(/^HALO_MCC_FOLDER\s*=\s*"?([^"\r\n]+)"?/m);
  if (!m || !existsSync(join(m[1], BANK_REL))) return null;
  const s = await stat(join(m[1], BANK_REL));
  return `${s.size}:${s.mtimeMs}`;
}

let lastJobId = null;
/** Waits for a NEW job of this kind (not the previous one) to finish. */
async function waitJob(kind, timeout) {
  const box = page.getByTestId("job");
  await page.waitForFunction(([k, prev]) => {
    const el = document.querySelector('[data-testid="job"]');
    return el && el.dataset.kind === k && el.dataset.id !== prev && el.dataset.state !== "running";
  }, [kind, lastJobId], { timeout });
  lastJobId = await box.getAttribute("data-id");
  const state = await box.getAttribute("data-state");
  const log = await box.locator("pre").innerText().catch(() => "");
  return { state, log };
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-deploy-"));
  const fixture = await runFixture(join(tmp, "root"));
  const { game, original } = await sandboxGame(join(tmp, "steam"));
  const state = join(tmp, "deploy-state");
  const realBefore = await realBankStat();
  const services = new Services(fixture.root, ["--mcc-root", game, "--deploy-state", state]);
  let browser;
  let candidate = null;

  try {
    await step("start the Studio with a throw-away game folder", async () => {
      await services.up();
      return game;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
    const confirms = handleConfirms(page);
    await page.goto(`http://localhost:${WEB_PORT}/#/builds`);

    await step("the page shows the folder (fixed in test mode) and the original files", async () => {
      const card = page.getByTestId("deploy-status");
      await card.getByText("original game files").waitFor({ timeout: 30000 });
      check((await card.innerText()).includes("test override"), "the folder source is not the test override");
      check((await page.getByLabel("MCC folder").count()) === 0, "the folder can be changed in test mode");
      check(await page.getByRole("button", { name: /Restore originals/ }).isDisabled(), "restore offered with nothing installed");
      check(!(await page.getByRole("button", { name: /Build subtitles/ }).isDisabled()), "subtitle build not offered");
    });

    await step("Build audio for the a10 folder from the page", async () => {
      await page.getByLabel("Chosen folders").check();
      await page.getByLabel("Build name").fill(BUILD);
      await page.getByRole("button", { name: "Build audio", exact: true }).click();
      const { state: s, log } = await waitJob("build", 15 * 60 * 1000);
      check(s === "done", `build ${s}: ${log.slice(-300)}`);
      const row = page.locator(`tr[data-build="${BUILD}"]`);
      await row.waitFor({ timeout: 15000 });
      check((await row.innerText()).includes("passed"), "validation did not pass");
      const manifest = JSON.parse(await readFile(join(REPO, "work", "m6", BUILD, "build_manifest.json"), "utf-8"));
      candidate = manifest.install_files[0].candidate_sha256;
      return log.split("\n").find((l) => l.startsWith("PASS")) ?? "built";
    });

    await step("the API still refuses an install without confirmation", async () => {
      const res = await page.evaluate(async (b) => (await fetch("/api/deploy/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ build: b }) })).status, BUILD);
      check(res === 400, `answered ${res}`);
    });

    await step("Install to MCC, after a confirmation listing the file", async () => {
      await page.locator(`tr[data-build="${BUILD}"]`).getByRole("button", { name: /Install to MCC/ }).click();
      const { state: s, log } = await waitJob("install", 5 * 60 * 1000);
      check(s === "done", `install ${s}: ${log.slice(-400)}`);
      const confirmText = confirms.messages.at(-1) ?? "";
      check(confirmText.includes(BANK_REL) && confirmText.includes(game), `confirmation did not list the file and folder: ${confirmText.slice(0, 200)}`);
      check((await hash(join(game, BANK_REL))) === candidate, "the game bank is not the build's candidate");
      check(existsSync(join(state, "backup", "19905945", BANK_REL)), "no backup of the original");
      await page.getByTestId("deploy-status").getByText(`build ${BUILD}`).first().waitFor({ timeout: 15000 });
      return log.split("\n").find((l) => l.startsWith("INSTALL OK"))?.slice(0, 90);
    });

    await step("with a build installed, another install is refused by the installer's checks", async () => {
      const res = await page.evaluate(async (b) => {
        const r = await fetch("/api/deploy/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ build: b, confirm: true }) });
        return { status: r.status, job: await r.json() };
      }, BUILD);
      check(res.status === 202, `start answered ${res.status}`);
      let job = res.job;
      for (let i = 0; i < 120 && job.state === "running"; i++) {
        await page.waitForTimeout(500);
        job = await page.evaluate(async (id) => (await fetch(`/api/job?id=${id}`)).json(), job.id);
      }
      check(job.state === "failed" && /not the pinned original|STOP/.test(job.log_tail), `second install: ${job.state} ${job.log_tail.slice(-200)}`);
      check((await hash(join(game, BANK_REL))) === candidate, "the refused install changed the file");
      return job.log_tail.split("\n").find((l) => l.includes("STOP"))?.slice(0, 100);
    });

    await step("Restore originals from the page", async () => {
      await page.reload();
      await page.getByTestId("deploy-status").getByText(`build ${BUILD}`).first().waitFor({ timeout: 30000 });
      await page.getByRole("button", { name: /Restore originals/ }).click();
      const { state: s, log } = await waitJob("restore", 5 * 60 * 1000);
      check(s === "done", `restore ${s}: ${log.slice(-400)}`);
      check((await hash(join(game, BANK_REL))) === original, "the game bank is not the original again");
      await page.getByTestId("deploy-status").getByText("original game files").waitFor({ timeout: 15000 });
      check(log.includes("hashed files changed vs preflight: none"), "rollback reported other changed files");
      return log.split("\n").find((l) => l.startsWith("ROLLBACK OK"));
    });
    await page.screenshot({ path: join(OUT, "deploy.png"), fullPage: true });
  } catch (e) {
    record("deploy test stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
    await rm(join(REPO, "work", "m6", BUILD), { recursive: true, force: true });
    await rm(join(REPO, "work", "m6", `${BUILD}_build.log`), { force: true });
  }

  await step("the real MCC install and the real mappings were not touched", async () => {
    check((await realBankStat()) === realBefore, "the real Spanish bank changed size or modification time");
    check((await sha256File(join(fixture.real_mappings, "manual_mappings.json"))) === fixture.real_mappings_sha256, "real mappings changed");
    return realBefore ? "real bank size/mtime unchanged" : "no real MCC folder configured";
  });
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "deploy-report.json"), JSON.stringify({ results }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
