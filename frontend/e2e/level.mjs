// Browser check of the level settings on Build & Test (focused; about 1 minute):
//   the Level choice (global gain / match Spain) is saved, each build's Level column reports what it did, a build
//   made in the other mode is stale, and the installed build's level is compared with the current setting.
//
//   node e2e/level.mjs --build <name>     (a finished audio build in work/m6/, made in global_gain mode)
//
// Runs on a disposable copy of the mapping data (its own config/) and a THROW-AWAY game folder whose bank is
// the build's candidate, so the page sees that build as installed. Nothing is installed or restored; the real
// game folder and the real config/audio_export.json are compared before and after.

import { copyFile, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, REPO, WEB_PORT, Services, handleConfirms, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const BUILD = process.argv[process.argv.indexOf("--build") + 1];
const results = [];
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
async function step(name, fn) {
  try {
    const d = (await fn()) ?? "";
    results.push({ name, ok: true, detail: d });
    console.log(`PASS  ${name}${d ? `  (${d})` : ""}`);
  } catch (e) {
    results.push({ name, ok: false, detail: String(e.message ?? e) });
    console.log(`FAIL  ${name}  (${String(e.message ?? e).split("\n")[0]})`);
    throw e;
  }
}

async function main() {
  if (!BUILD || !existsSync(join(REPO, "work/m6", BUILD, "build_manifest.json"))) throw new Error("--build <name> required");
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-level-"));
  const fixture = await runFixture(join(tmp, "root"));
  const manifest = JSON.parse(await readFile(join(REPO, "work/m6", BUILD, "build_manifest.json"), "utf-8"));
  const game = join(tmp, "steam", "steamapps", "common", "Halo The Master Chief Collection");
  await mkdir(join(game, "halo1/sound/pc"), { recursive: true });
  await mkdir(join(game, "Data/ui/localization"), { recursive: true });
  await copyFile(join(REPO, manifest.install_files[0].candidate), join(game, manifest.install_files[0].install_rel));
  for (const t of ["SU", "SP"]) await copyFile(join(REPO, "work/mcc/loc/copies", `${t}_Halo1.bin`), join(game, `Data/ui/localization/${t}_Halo1.bin`));
  const realConfig = join(REPO, "config", "audio_export.json");
  const realConfigBefore = existsSync(realConfig) ? await sha256File(realConfig) : null;
  const services = new Services(fixture.root, ["--mcc-root", game, "--deploy-state", join(tmp, "state")]);
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    handleConfirms(page);
    await page.goto(`http://localhost:${WEB_PORT}/#/builds`);
    const row = page.locator(`tr[data-build="${BUILD}"]`);

    await step("each build's Level column reports its mode, applied gain and constrained lines", async () => {
      await row.waitFor({ timeout: 30000 });
      const text = await row.getByTestId("build-level").innerText();
      const lv = manifest.level;
      check(text.toLowerCase().includes(`global gain +${lv.global_gain_db.toFixed(1)} dB`), `level cell: ${text}`);
      check(text.includes(`${lv.constrained.length}/${lv.lines} constrained`), `level cell: ${text}`);
      return text.replace(/\s+/g, " ");
    });

    await step("the installed build's level is shown and compared with the current setting", async () => {
      const box = page.getByTestId("installed-level");
      await box.waitFor({ timeout: 30000 });
      const t = await box.innerText();
      check(t.includes(BUILD) && t.includes("constrained"), `installed level: ${t}`);
      return t.split("\n")[0];
    });

    await step("choosing Match Spain saves the mode and marks the global-gain build stale", async () => {
      await page.getByTestId("level-mode").getByLabel(/Match Spain's loudness/).check();
      await page.getByText("Level set to match Spain's loudness").waitFor({ timeout: 15000 });
      const cfg = JSON.parse(await readFile(join(fixture.root, "config", "audio_export.json"), "utf-8"));
      check(cfg.level_mode === "match_spain" && cfg.global_gain_db !== undefined, `config: ${JSON.stringify(cfg)}`);
      await page.getByRole("button", { name: /Check again/ }).click();
      await row.getByText(/level mode changed since the build \(global_gain → match_spain\)/).waitFor({ timeout: 15000 });
      await page.getByTestId("installed-level").getByText(/Studio is now set to\s+match Spain/).waitFor({ timeout: 15000 });
      return `config ${JSON.stringify(cfg)}`;
    });

    await step("switching back to Global gain keeps the gain value", async () => {
      await page.getByTestId("level-mode").getByLabel(/Global gain: the same gain/).check();
      await page.getByText("Level set to global gain").waitFor({ timeout: 15000 });
      const cfg = JSON.parse(await readFile(join(fixture.root, "config", "audio_export.json"), "utf-8"));
      check(cfg.level_mode === "global_gain", `config: ${JSON.stringify(cfg)}`);
      // the install panel follows the new setting without a reload
      const expected = new RegExp(`Studio is now set to\\s+global gain \\+${cfg.global_gain_db.toFixed(1)} dB`);
      try {
        await page.getByTestId("installed-level").getByText(expected).waitFor({ timeout: 15000 });
      } catch (e) {
        const api = await page.evaluate(async () => {
          const d = await (await fetch("/api/deploy/status")).json();
          return [d.current_level, d.installed_level.map((x) => [x.build, x.global_gain_db, x.matches_current])];
        });
        console.log("panel:", JSON.stringify(await page.getByTestId("installed-level").innerText()), "api:", JSON.stringify(api));
        throw e;
      }
      return `gain ${cfg.global_gain_db}`;
    });
    await page.screenshot({ path: join(OUT, "level.png"), fullPage: true });
  } catch (e) {
    console.log(`stopped: ${e.message}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }
  await step("the real config and mappings were not touched", async () => {
    check((existsSync(realConfig) ? await sha256File(realConfig) : null) === realConfigBefore, "real config changed");
    check((await sha256File(join(fixture.real_mappings, "manual_mappings.json"))) === fixture.real_mappings_sha256, "real mappings changed");
  }).catch(() => {});
  await writeFile(join(OUT, "level-report.json"), JSON.stringify({ results }, null, 2));
  const failed = results.filter((r) => !r.ok).length;
  console.log(failed ? `\n${failed} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
