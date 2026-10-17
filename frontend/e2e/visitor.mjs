// Browser test of the public read-only view (docs/public-access.md): the production server with its public
// listener, opened by an anonymous visitor on a desktop and on a phone, next to the owner's own address.
//
//   npm run test:visitor        (from frontend/; needs Microsoft Edge and the catalogs under work/)
//
// It builds the Studio, makes a disposable copy of the mapping data (scripts/ui/e2e_fixture.py) and starts
// scripts/ui/m4_server.py --public on it. Checks: the visitor browses levels, lines, decisions, subtitles, flags
// and builds; sees the Read-only badge and Sign in to edit; never sees Save, Approve, Use, Unmatch, Install,
// play or download controls; keyboard shortcuts do nothing; the page requests no audio and sends no write at all;
// direct writes, audio and downloads from the page are refused (401). The owner's address keeps the full editor.
// It never installs anything, and the real mapping decisions are checked unchanged at the end.

import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, devices } from "playwright-core";
import { spawn } from "node:child_process";
import { FRONTEND, HERE, REPO, runFixture, sha256File, start, stopProcess, waitForHttp } from "./harness.mjs";

const OUT = join(HERE, "out");
const LOCAL_PORT = 8798;
const PUBLIC_PORT = 8797;
const SLOT = "es:A10_010_cryotech#0";
const SIGN_IN = "https://admin.example.com/";
// E2E_PUBLIC_PREVIEWS=1: the owner's "public": {"previews": true}: one approved line of the disposable copy is
// published (scripts/build/publish_previews.py --slot) and the visitor plays and seeks it; originals stay private.
const PREVIEWS = process.env.E2E_PUBLIC_PREVIEWS === "1";
let previewSlot = null;

const results = [];
const pageErrors = [];
function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
async function step(name, fn) {
  try {
    record(name, true, (await fn()) ?? "");
  } catch (e) {
    record(name, false, String(e && e.message ? e.message : e).split("\n")[0]);
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

function run(command, args, options = {}) {
  return new Promise((done) => {
    const child = spawn(command, args, { cwd: options.cwd ?? REPO, windowsHide: true });
    let out = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (out += c));
    child.on("exit", (code) => done({ code, out }));
  });
}

/** A visitor's browser: records every request the page makes (none may be audio or a write). */
async function openVisitor(browser, options, label) {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  page.on("pageerror", (err) => pageErrors.push(`[${label}] ${err.message}`));
  page.on("console", (msg) => msg.type() === "error" && pageErrors.push(`[${label}] ${msg.text()}`));
  const requests = [];
  page.on("request", (req) => {
    const u = new URL(req.url());
    requests.push({ method: req.method(), path: u.pathname });
  });
  return { context, page, requests };
}

const forbidden = (requests) =>
  requests.filter((r) => (r.path.startsWith("/audio/") && !(PREVIEWS && r.path === "/audio/public")) ||
    r.method !== "GET" || r.path === "/api/events");

async function openLine(page, base) {
  await page.goto(`${base}#/match?level=a10&slot=${encodeURIComponent(SLOT)}`);
  await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const base = `http://127.0.0.1:${PUBLIC_PORT}/`;
  const owner = `http://127.0.0.1:${LOCAL_PORT}/`;
  const tmp = await mkdtemp(join(tmpdir(), "studio-visitor-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  const config = join(tmp, "studio_server.json");
  await writeFile(config, JSON.stringify({ schema: "studio-server/1", public: { enabled: true, port: PUBLIC_PORT, sign_in_url: SIGN_IN, previews: PREVIEWS } }));
  let server;
  let browser;
  const pages = [];

  try {
    await step("build the Studio for production", async () => {
      const { code, out } = await run(process.execPath, [join(FRONTEND, "node_modules", "vite", "bin", "vite.js"), "build"], { cwd: FRONTEND });
      check(code === 0, out.slice(-400));
      return "frontend/dist";
    });

    if (PREVIEWS) {
      await step("publish the edited preview of one approved line (disposable copy)", async () => {
        const doc = JSON.parse(await readFile(join(root, "mappings", "manual_mappings.json"), "utf-8"));
        const m = doc.slots.find((x) => x.audio.status === "approved" && x.audio.source === "ce" && x.audio.sources.length === 1 && x.slot_id.startsWith("es:A10_"));
        check(m, "no approved a10 line in the copy");
        previewSlot = m.slot_id;
        const { code, out } = await run("python", ["scripts/build/publish_previews.py", "--root", root, "--slot", previewSlot]);
        check(code === 0 && /published 1 preview/.test(out), out.slice(-300));
        return previewSlot;
      });
    }

    await step("start the server with the public read-only listener", async () => {
      server = start("api", "python", ["scripts/ui/m4_server.py", "--root", root, "--config", config, "--port", String(LOCAL_PORT),
        "--static-dir", join(FRONTEND, "dist"), "--no-open", "--state-dir", join(root, "studio-state")], { cwd: REPO });
      await waitForHttp(`${owner}api/session`);
      await waitForHttp(`${base}api/session`);
      return `owner ${owner}, public ${base}`;
    });

    await step("direct requests: browsing allowed, writes / audio / downloads / settings refused", async () => {
      const ok = ["api/session", "api/state", "api/slots?level=a10", `api/slot?id=${encodeURIComponent(SLOT)}`, "api/ce?mission=M01", "api/builds", "api/deploy/history"];
      for (const p of ok) check((await fetch(base + p)).status === 200, `${p} not 200`);
      const audio = ["audio/mcc?level=a10&lang=spanish&index=0", "audio/ce?ref=vo_scr_m01_00460_cryotech%230&lang=Spanish(Mexico)",
        "audio/peaks?src=%2Faudio%2Fmcc%3Flevel%3Da10%26lang%3Dspanish%26index%3D0"];
      if (PREVIEWS) {
        const res = await fetch(`${base}audio/public?slot=${encodeURIComponent(previewSlot)}`, { headers: { Range: "bytes=0-99" } });
        check(res.status === 206 && res.headers.get("content-type") === "audio/wav", `published preview answered ${res.status}`);
      }
      const refused = [...audio, "audio/preview?key=abc&kind=edited", "api/events", "api/network", "api/settings/export",
        "api/data/status", "api/deploy/status", "api/builds/log?name=a10"];
      const codes = [];
      for (const p of refused) codes.push((await fetch(base + p)).status);
      for (const p of ["api/save", "api/progress", "api/builds/start", "api/data/export", "api/deploy/install", "api/edit/preview"]) {
        codes.push((await fetch(base + p, { method: "POST", headers: { "Content-Type": "application/json", "Cf-Access-Authenticated-User-Email": "owner@example.com" }, body: JSON.stringify({ slot_id: SLOT, notes: "x", confirm: true }) })).status);
      }
      check(codes.every((c) => c === 401), `codes ${codes}`);
      const session = await (await fetch(base + "api/session")).json();
      check(session.visitor === true && !session.permissions.edit && session.sign_in_url === SIGN_IN, JSON.stringify(session));
      return `${ok.length} reads 200; ${codes.length} refused with 401`;
    });

    browser = await chromium.launch({ channel: "msedge", headless: true });
    const desk = await openVisitor(browser, { viewport: { width: 1500, height: 980 } }, "desktop");
    pages.push(["desktop", desk.page]);

    await step("desktop: the visitor opens the Studio without signing in", async () => {
      await desk.page.goto(base);
      await desk.page.getByTestId("visitor-mode").waitFor({ timeout: 30000 });
      check((await desk.page.getByRole("heading", { name: "Sign in" }).count()) === 0, "a sign-in form was shown");
      const href = await desk.page.getByTestId("sign-in-to-edit").getAttribute("href");
      check(href === SIGN_IN, `sign-in link ${href}`);
      const nav = await desk.page.locator("#main-nav").innerText();
      check(!/\bData\b/.test(nav) && !/\bNetwork\b/.test(nav), `owner pages in the menu: ${nav}`);
      await desk.page.screenshot({ path: join(OUT, "visitor-dashboard.png") });
      return "Read-only badge, Sign in to edit, no Data / Network";
    });

    await step("desktop: a line shows its decision read-only, with no editing, audio or download controls", async () => {
      await openLine(desk.page, base);
      await desk.page.getByTestId("readonly-notice").waitFor({ timeout: 15000 });
      await desk.page.getByTestId("recipe-summary").waitFor({ timeout: 15000 });
      await desk.page.locator("li.row-item").first().waitFor({ timeout: 30000 });
      const counts = await desk.page.evaluate(() => ({
        save: document.querySelectorAll('[data-testid="save-draft"], [data-testid="approve-both"], .save-bar').length,
        unmatch: document.querySelectorAll('[data-testid="unmatch"]').length,
        use: [...document.querySelectorAll("button")].filter((b) => /Use this recording|Needs rework|Approve/.test(b.textContent ?? "")).length,
        download: document.querySelectorAll("a.download-link, a[download]").length,
        notes: document.querySelectorAll('[data-section="flags"] textarea').length,
        enabledInputs: [...document.querySelectorAll("#pane-match input, #pane-match textarea, #pane-match select")].filter((el) => !el.disabled && !el.closest("fieldset:disabled") && !el.closest('[data-section="compare"]')).length,
      }));
      check(Object.values(counts).every((n) => n === 0), JSON.stringify(counts));
      const players = await desk.page.locator("button.play").count();
      const compare = await desk.page.locator('[data-section="compare"]').count();
      check(players === 0 && compare === 0, `players ${players}, compare ${compare}`);
      const subtitle = await desk.page.getByTestId("subtitle-preview-text").innerText().catch(() => "");
      check(subtitle.length > 0, "no subtitle shown");
      await desk.page.screenshot({ path: join(OUT, "visitor-match.png") });
      return `subtitle "${subtitle.slice(0, 40)}…"; ${JSON.stringify(counts)}`;
    });

    await step("desktop: shortcuts and clicks change nothing and play nothing", async () => {
      await desk.page.locator("li.row-item").nth(1).click();
      for (const key of ["s", "Control+s", "Control+Enter", " ", "m", "e", "n", "1"]) await desk.page.keyboard.press(key);
      await desk.page.waitForTimeout(800);
      const bad = forbidden(desk.requests);
      check(bad.length === 0, `requests: ${JSON.stringify(bad.slice(0, 5))}`);
      return `${desk.requests.length} requests, all GET and none for audio`;
    });

    if (PREVIEWS) {
      await step("desktop: the approved line's edited preview plays and seeks; others say it is unavailable", async () => {
        const detail = await (await fetch(`${base}api/slot?id=${encodeURIComponent(previewSlot)}`)).json();
        await desk.page.goto(`${base}#/match?level=${detail.level}&slot=${encodeURIComponent(previewSlot)}`);
        const player = desk.page.getByTestId("public-preview-player");
        await player.waitFor({ timeout: 30000 });
        check((await player.getAttribute("controlslist"))?.includes("nodownload"), "the player offers a download");
        const played = await player.evaluate(async (a) => {
          a.muted = true;
          await a.play();
          await new Promise((done) => setTimeout(done, 700));
          const t = a.currentTime;
          a.currentTime = Math.min(0.2, a.duration / 4);
          await new Promise((done) => a.addEventListener("seeked", done, { once: true }));
          a.pause();
          return { t, duration: a.duration, after: a.currentTime };
        });
        check(played.t > 0.2 && played.duration > 0.5, `did not play: ${JSON.stringify(played)}`);
        await desk.page.screenshot({ path: join(OUT, "visitor-preview.png") });
        const rows = (await (await fetch(`${base}api/slots?level=a10`)).json()).slots;
        const other = rows.find((r) => r.slot_id !== previewSlot && r.decision?.audio !== "approved");
        await desk.page.goto(`${base}#/match?level=a10&slot=${encodeURIComponent(other.slot_id)}`);
        await desk.page.getByTestId("public-preview-unavailable").waitFor({ timeout: 30000 });
        const status = (await fetch(`${base}audio/public?slot=${encodeURIComponent(other.slot_id)}`)).status;
        check(status === 404, `an unapproved line's preview answered ${status}`);
        return `${previewSlot}: played ${played.t.toFixed(2)} s of ${played.duration.toFixed(2)} s, seeked; ${other.slot_id}: unavailable (404)`;
      });
    }

    await step("desktop: owner pages redirect; Build & Test shows builds read-only", async () => {
      await desk.page.goto(`${base}#/data`);
      await desk.page.waitForURL((u) => u.hash === "#/", { timeout: 15000 });
      await desk.page.goto(`${base}#/builds`);
      await desk.page.getByTestId("public-install-history").waitFor({ timeout: 15000 });
      const buttons = await desk.page.evaluate(() =>
        [...document.querySelectorAll("button")].filter((b) => /Build audio|Build subtitles|Install|Restore|Use this folder/.test(b.textContent ?? "")).length);
      check(buttons === 0, `${buttons} build / install buttons`);
      await desk.page.screenshot({ path: join(OUT, "visitor-builds.png"), fullPage: true });
      const status = await desk.page.evaluate(async (slot) => (await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot_id: slot, notes: "x" }) })).status, SLOT);
      check(status === 401, `save from the page answered ${status}`);
      check(forbidden(desk.requests).filter((r) => r.path !== "/api/save").length === 0, "the page itself sent a write or asked for audio");
      return "no build, install or restore controls; a save sent by hand is refused (401)";
    });

    const phone = await openVisitor(browser, { ...devices["Pixel 7"] }, "phone");
    pages.push(["phone", phone.page]);
    await step("phone: badge in view, one pane at a time, no save strip", async () => {
      await openLine(phone.page, base);
      check(await phone.page.getByTestId("visitor-mode").isVisible(), "the Read-only badge is not visible on a phone");
      check((await phone.page.getByTestId("action-strip").count()) === 0, "a save strip is shown");
      await phone.page.getByTestId("readonly-notice").scrollIntoViewIfNeeded();
      await phone.page.screenshot({ path: join(OUT, "visitor-phone.png") });
      const wide = await phone.page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      check(!wide, "horizontal scroll on the phone");
      check(forbidden(phone.requests).length === 0, "the phone page asked for audio or sent a write");
      return "Read-only badge visible; no horizontal scroll";
    });

    const own = await openVisitor(browser, { viewport: { width: 1500, height: 980 } }, "owner");
    pages.push(["owner", own.page]);
    await step("the owner's address keeps the full editor", async () => {
      await openLine(own.page, owner);
      await own.page.getByTestId("save-draft").waitFor({ timeout: 15000 });
      check((await own.page.getByTestId("visitor-mode").count()) === 0, "the owner sees the Read-only badge");
      check((await own.page.locator("button.play").count()) > 0, "no play buttons for the owner");
      return "Save draft, approvals and players present";
    });
  } catch (e) {
    record("visitor test stopped early", false, String(e.message ?? e).split("\n")[0]);
    for (const [name, p] of pages) await p.screenshot({ path: join(OUT, `visitor-failed-${name}.png`) }).catch(() => {});
  } finally {
    if (browser) await browser.close().catch(() => {});
    await stopProcess(server);
  }

  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === fixture.real_mappings_sha256, "real manual_mappings.json changed");
    return `sha256 ${after.slice(0, 16)}…`;
  }).catch(() => {});

  if (pageErrors.length) console.log("\nbrowser errors:\n" + pageErrors.slice(0, 20).join("\n"));
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "visitor-report.json"), JSON.stringify({ results, root, base, pageErrors }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed. Report: e2e/out/visitor-report.json` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
