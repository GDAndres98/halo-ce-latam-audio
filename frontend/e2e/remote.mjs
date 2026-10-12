// Browser test of remote access (docs/remote-access.md): the production server (no Vite), reached through
// this computer's LAN address the way a second computer reaches it.
//
//   npm run test:remote        (from frontend/; needs Microsoft Edge, ffmpeg and the catalogs under work/)
//
// It builds the Studio, makes a disposable copy of the mapping data (scripts/ui/e2e_fixture.py), creates two
// throw-away accounts in that copy, starts scripts/ui/m4_server.py --lan on it, and drives two separate
// browser sessions (an editor and an admin, as if on two computers). It never installs anything: the game
// folder is never touched, and the real mapping decisions are checked unchanged at the end.

import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { networkInterfaces, tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { FRONTEND, HERE, REPO, handleConfirms, runFixture, sha256File, start, stopProcess, waitForHttp } from "./harness.mjs";

const OUT = join(HERE, "out");
const LOCAL_PORT = 8795;
const REMOTE_PORT = 8796;
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const PASSWORD = "e2e-remote-password-1"; // throw-away accounts in the disposable copy only

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

/** This computer's LAN address: what another computer on the network would type. */
function lanAddress() {
  for (const list of Object.values(networkInterfaces())) {
    for (const a of list ?? []) {
      if (a.family === "IPv4" && !a.internal && !a.address.startsWith("169.254.")) return a.address;
    }
  }
  throw new Error("no LAN address found");
}

function run(command, args, options = {}) {
  return new Promise((done) => {
    const child = spawn(command, args, { cwd: options.cwd ?? REPO, env: { ...process.env, ...options.env }, windowsHide: true, shell: options.shell });
    let out = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (out += c));
    child.on("exit", (code) => done({ code, out }));
  });
}

async function openSession(browser, base, label) {
  const context = await browser.newContext({ viewport: { width: 1500, height: 980 } });
  const page = await context.newPage();
  handleConfirms(page);
  page.on("pageerror", (err) => pageErrors.push(`[${label}] ${err.message}`));
  page.on("console", (msg) => msg.type() === "error" && pageErrors.push(`[${label}] ${msg.text()}`));
  const audio = [];
  page.on("response", (res) => {
    const u = new URL(res.url());
    if (u.pathname.startsWith("/audio/")) audio.push({ path: u.pathname, status: res.status(), type: res.headers()["content-type"] });
  });
  await page.goto(base);
  return { context, page, audio };
}

async function signIn(page, user) {
  await page.getByRole("heading", { name: "Sign in" }).waitFor({ timeout: 30000 });
  await page.getByLabel("User name").fill(user);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("signed-in-user").waitFor({ timeout: 15000 });
}

async function openLine(page, base) {
  await page.goto(`${base}#/match?level=a10&slot=${encodeURIComponent(SLOT)}&cq=${encodeURIComponent("00460_cryotech")}`);
  await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
}

const compare = (page) => page.getByRole("region", { name: "Compare the original and the replacement" });
async function waveDuration(page, wave) {
  const host = wave.getByTestId("wave-host");
  await page.waitForFunction((el) => Number(el.dataset.duration) > 0, await host.elementHandle(), { timeout: 30000 });
  return Number(await host.getAttribute("data-duration"));
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const ip = lanAddress();
  const base = `http://${ip}:${REMOTE_PORT}/`;
  const tmp = await mkdtemp(join(tmpdir(), "studio-remote-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  let server;
  let browser;
  const pages = [];

  try {
    await step("build the Studio for production", async () => {
      const { code, out } = await run(process.execPath, [join(FRONTEND, "node_modules", "vite", "bin", "vite.js"), "build"], { cwd: FRONTEND });
      check(code === 0, out.slice(-400));
      return "frontend/dist";
    });

    await step("create two throw-away accounts in the disposable copy", async () => {
      for (const [name, role] of [["sofia", "editor"], ["owner", "admin"]]) {
        const { code, out } = await run("python", ["scripts/ui/studio_users.py", "--root", root, "--state-dir", join(root, "studio-state"), "add", name, "--role", role], { env: { STUDIO_PASSWORD: PASSWORD } });
        check(code === 0, out);
      }
      return "sofia (editor), owner (admin)";
    });

    await step("1. start the host server with remote access", async () => {
      server = start("api", "python", ["scripts/ui/m4_server.py", "--root", root, "--port", String(LOCAL_PORT), "--lan",
        "--remote-host", ip, "--remote-port", String(REMOTE_PORT), "--static-dir", join(FRONTEND, "dist"), "--no-open",
        "--state-dir", join(root, "studio-state")], { cwd: REPO });
      await waitForHttp(`http://127.0.0.1:${LOCAL_PORT}/api/session`);
      await waitForHttp(`${base}api/session`);
      return `local 127.0.0.1:${LOCAL_PORT}, remote ${base}`;
    });

    await step("9. unauthenticated requests are blocked", async () => {
      const probes = ["api/state", "api/slots?level=a10", `api/slot?id=${encodeURIComponent(SLOT)}`,
        "audio/mcc?level=a10&lang=spanish&index=0", "api/events", "api/network"];
      const codes = [];
      for (const p of probes) codes.push((await fetch(base + p)).status);
      const save = await fetch(`${base}api/save`, { method: "POST", headers: { "Content-Type": "application/json", Origin: base.slice(0, -1) }, body: JSON.stringify({ slot_id: SLOT, notes: "x" }) });
      codes.push(save.status);
      check(codes.every((c) => c === 401), `codes ${codes}`);
      const wrong = await fetch(`${base}api/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "sofia", password: "wrong-password-1" }) });
      check(wrong.status === 401, `wrong password answered ${wrong.status}`);
      return `${codes.length} requests answered 401; wrong password 401`;
    });

    browser = await chromium.launch({ channel: "msedge", headless: true });
    const a = await openSession(browser, base, "sofia");
    const b = await openSession(browser, base, "owner");
    pages.push(["sofia", a.page], ["owner", b.page]);

    await step("2. the Studio opens through the LAN address and asks to sign in", async () => {
      await signIn(a.page, "sofia");
      await signIn(b.page, "owner");
      return `${base} (two separate browser sessions)`;
    });

    await step("3. MCC and Campaign Evolved audio load over the network", async () => {
      await openLine(a.page, base);
      const seconds = await waveDuration(a.page, compare(a.page).locator(".wave-view").nth(0));
      const spain = a.page.locator("li.row-item.selected button.play").first();
      await spain.click();
      await a.page.locator("li.row-item.selected button.play.active").first().waitFor({ timeout: 15000 });
      await spain.click();
      const row = a.page.locator("li.row-item", { hasText: CE_REF });
      await row.waitFor({ timeout: 30000 });
      for (const lang of ["es-MX", "EN"]) {
        await row.getByRole("button", { name: lang, exact: true }).click();
        await row.locator("button.play.active", { hasText: lang }).waitFor({ timeout: 15000 });
        await row.locator("button.play.active", { hasText: lang }).click();
      }
      const ok = a.audio.filter((r) => r.status === 200 || r.status === 206 || r.status === 304);
      check(ok.some((r) => r.path === "/audio/mcc"), "no MCC audio response");
      check(ok.filter((r) => r.path === "/audio/ce").length >= 2, "no es-MX and EN responses");
      check(ok.some((r) => r.path === "/audio/peaks"), "the waveform did not use server peaks");
      check(a.audio.every((r) => r.status < 400), `failed audio: ${JSON.stringify(a.audio.filter((r) => r.status >= 400))}`);
      return `original ${seconds.toFixed(3)} s; ${a.audio.length} audio responses (${[...new Set(a.audio.map((r) => r.path))].join(", ")})`;
    });

    await step("4. seek (range requests) and compare A / B", async () => {
      const ranged = await a.page.evaluate(async () => {
        const res = await fetch("/audio/mcc?level=a10&lang=spanish&index=0", { headers: { Range: "bytes=1000-1999" } });
        return { status: res.status, range: res.headers.get("Content-Range"), size: (await res.arrayBuffer()).byteLength };
      });
      check(ranged.status === 206 && ranged.size === 1000, `range answer ${JSON.stringify(ranged)}`);
      await a.page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).click();
      await a.page.getByText("Recording chosen").waitFor({ timeout: 15000 });
      const waveA = compare(a.page).locator(".wave-view").nth(0);
      const waveB = compare(a.page).locator(".wave-view").nth(1);
      await waveDuration(a.page, waveB);
      // Seek A by clicking in the middle of its waveform, play from there, then switch to B at the same position.
      const position = async (wave) => {
        const [m, sec] = (await wave.getByTestId("wave-time").innerText()).split("/")[0].trim().split(":");
        return Number(m) * 60 + Number(sec);
      };
      const durationA = await waveDuration(a.page, waveA);
      await waveA.scrollIntoViewIfNeeded();
      const box = await waveA.getByTestId("wave-host").boundingBox();
      await a.page.mouse.click(box.x + box.width * 0.5, box.y + (box.height - 16) / 2);
      const seeked = await position(waveA);
      check(Math.abs(seeked - durationA / 2) < 0.25, `the click put A at ${seeked} s (duration ${durationA})`);
      await waveA.getByRole("button", { name: "Play", exact: true }).click();
      await a.page.waitForFunction((el) => el.dataset.playing === "true", await waveA.elementHandle(), { timeout: 15000 });
      await a.page.waitForTimeout(300);
      const playingAt = await position(waveA);
      check(playingAt >= seeked - 0.05, `A played from ${playingAt} s instead of the seek position ${seeked} s`);
      await compare(a.page).getByRole("button", { name: /A \/ B/ }).click();
      await a.page.waitForFunction((el) => el.dataset.playing === "true", await waveB.elementHandle(), { timeout: 15000 });
      const atB = await position(waveB);
      await a.page.keyboard.press("Escape");
      check(atB >= seeked - 0.05, `B started at ${atB} s, not near A's position`);
      return `206 ${ranged.range}; A seeked to ${seeked.toFixed(2)} s and played from there; A/B switched, B at ${atB.toFixed(2)} s`;
    });

    await step("5. an edited preview is rendered on the host and streamed", async () => {
      const editor = a.page.getByRole("region", { name: "Audio editing" });
      const rendered = a.page.waitForResponse((r) => r.url().includes("/api/edit/preview") && r.status() === 200, { timeout: 90000 });
      await editor.getByLabel("Trim start (s)").fill("0.15");
      await editor.getByLabel("Trim start (s)").press("Tab");
      await rendered;
      await a.page.waitForFunction(() => document.querySelector('[data-testid="preview-status"]')?.getAttribute("data-state") === "ready", null, { timeout: 90000 });
      const waveB = compare(a.page).locator(".wave-view").nth(1);
      const seconds = await waveDuration(a.page, waveB);
      await waveB.getByRole("button", { name: "Play", exact: true }).click();
      await a.page.waitForFunction((el) => el.dataset.playing === "true", await waveB.elementHandle(), { timeout: 15000 });
      await a.page.keyboard.press("Escape");
      const preview = a.audio.filter((r) => r.path === "/audio/preview" && r.status < 400);
      check(preview.length > 0 && preview.every((r) => r.type === "audio/wav"), `preview responses ${JSON.stringify(preview)}`);
      return `edited preview ${seconds.toFixed(3)} s, played from the host`;
    });

    let rowBefore = "";
    await step("the admin session opens the same line (before the editor saves)", async () => {
      await openLine(b.page, base);
      rowBefore = await b.page.locator("li.row-item.selected").innerHTML();
      return "owner sees the stored version";
    });

    await step("6. save audio + subtitle + note from the remote editor session", async () => {
      await a.page.getByLabel("Notes", { exact: true }).fill("remote save from sofia");
      await a.page.getByRole("button", { name: /Save draft/ }).click();
      await a.page.getByText("Draft saved.").waitFor({ timeout: 20000 });
      return "draft saved through the remote address";
    });

    await step("7. the other session sees the update without reloading", async () => {
      await b.page.getByText("This line was just updated by sofia.").waitFor({ timeout: 15000 });
      const notes = await b.page.getByLabel("Notes", { exact: true }).inputValue();
      check(notes === "remote save from sofia", `notes on the other computer: "${notes}"`);
      await b.page.waitForFunction(
        (before) => document.querySelector("li.row-item.selected")?.innerHTML !== before, rowBefore, { timeout: 15000 });
      return "owner's open line and list row updated live (Server-Sent Events)";
    });

    await step("8. a conflicting edit is refused safely and the typing is kept", async () => {
      await b.page.getByLabel("Notes", { exact: true }).fill("owner's unsaved note");
      await a.page.getByLabel("Notes", { exact: true }).fill("sofia's second note");
      const saved = a.page.waitForResponse((r) => r.url().endsWith("/api/save"), { timeout: 20000 });
      await a.page.getByRole("button", { name: /Save draft/ }).click();
      check((await saved).status() === 200, "sofia's second save failed");
      await b.page.getByTestId("remote-change").waitFor({ timeout: 15000 });
      check((await b.page.getByLabel("Notes", { exact: true }).inputValue()) === "owner's unsaved note", "the owner's typing was replaced");
      const refused = b.page.waitForResponse((r) => r.url().endsWith("/api/save"), { timeout: 15000 });
      await b.page.getByRole("button", { name: /Save draft/ }).click();
      check((await refused).status() === 409, "the stale save was not refused");
      await b.page.getByText(/changed elsewhere/).first().waitFor({ timeout: 10000 });
      check((await b.page.getByLabel("Notes", { exact: true }).inputValue()) === "owner's unsaved note", "the typing was lost after the refusal");
      await b.page.getByRole("button", { name: "Reload and keep my edits" }).first().click();
      await b.page.getByText("Your edits are kept: check them").waitFor({ timeout: 15000 });
      check((await b.page.getByLabel("Notes", { exact: true }).inputValue()) === "owner's unsaved note", "reload lost the typing");
      await b.page.getByRole("button", { name: /Save draft/ }).click();
      await b.page.getByText("Draft saved.").waitFor({ timeout: 20000 });
      await a.page.getByText("This line was just updated by owner.").waitFor({ timeout: 15000 });
      return "409 with nothing written; edits kept; reload-and-keep then saved; the editor saw it live";
    });

    await step("approve audio and subtitle independently from the remote session", async () => {
      await a.page.getByRole("button", { name: "Approve audio" }).click();
      await a.page.getByText("approved audio").waitFor({ timeout: 20000 });
      await a.page.getByRole("button", { name: "Approve subtitle" }).click();
      await a.page.getByText("approved subtitle").waitFor({ timeout: 20000 });
      await a.page.getByRole("button", { name: "Needs rework (audio)" }).click();
      await a.page.getByText("Audio marked Needs rework").waitFor({ timeout: 20000 });
      return "approve audio, approve subtitle, needs rework (audio)";
    });

    await step("10. file access is restricted to the Studio's own files", async () => {
      const probes = ["../mappings/manual_mappings.db", "%2e%2e/mappings/manual_mappings.json", "mappings/manual_mappings.db",
        "config/studio_users.json", "work/studio/sessions.sqlite", "assets/..%2f..%2f..%2fREADME.md", "..%5c..%5cREADME.md",
        `audio/peaks?src=${encodeURIComponent("file:///C:/Windows/win.ini")}`, `audio/ce?ref=${encodeURIComponent("../../etc/passwd")}&lang=Spanish(Mexico)`,
        "audio/preview?key=..%2F..%2Fsecret&kind=edited", "classic"];
      const answers = await a.page.evaluate(async (paths) => {
        const out = [];
        for (const p of paths) {
          const res = await fetch("/" + p);
          out.push([p, res.status, (res.headers.get("content-type") || "").split(";")[0]]);
        }
        return out;
      }, probes);
      const leaked = answers.filter(([, status]) => status < 400);
      check(!leaked.length, `answered: ${JSON.stringify(leaked)}`);
      return answers.map(([, s]) => s).join(" ");
    });

    await step("11. game files cannot be modified from another computer", async () => {
      await b.page.goto(`${base}#/builds`);
      await b.page.getByTestId("install-host-only").waitFor({ timeout: 30000 });
      const enabled = await b.page.locator("button:has-text('Install to MCC'):not([disabled]), button:has-text('Restore originals'):not([disabled])").count();
      check(enabled === 0, `${enabled} install/restore button(s) enabled remotely`);
      const codes = await b.page.evaluate(async () => {
        const session = await (await fetch("/api/session")).json();
        const out = {};
        for (const [path, body] of [["/api/deploy/install", { build: "a10", confirm: true }], ["/api/deploy/restore", { confirm: true }],
                                    ["/api/settings/mcc", { mcc_folder: "C:/" }]]) {
          const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Studio-CSRF": session.csrf }, body: JSON.stringify(body) });
          out[path] = res.status;
        }
        return { codes: out, role: session.role, install: session.permissions.install };
      });
      check(Object.values(codes.codes).every((c) => c === 403), `answers ${JSON.stringify(codes.codes)}`);
      const editorCodes = await a.page.evaluate(async () => {
        const session = await (await fetch("/api/session")).json();
        const res = await fetch("/api/builds/start", { method: "POST", headers: { "Content-Type": "application/json", "X-Studio-CSRF": session.csrf }, body: JSON.stringify({ scope: "all_mapped" }) });
        return res.status;
      });
      check(editorCodes === 403, `an editor could start a build (${editorCodes})`);
      return `admin (${codes.role}) refused ${JSON.stringify(codes.codes)}; editor build refused 403`;
    });

    await step("the Network page shows the connection details", async () => {
      await b.page.goto(`${base}#/network`);
      await b.page.getByTestId("network-addresses").getByText(base).first().waitFor({ timeout: 15000 });
      await b.page.getByTestId("network-accounts").waitFor({ timeout: 15000 });
      await b.page.screenshot({ path: join(OUT, "remote-network.png"), fullPage: true });
      return "addresses, accounts and signed-in sessions listed";
    });

    await step("signing out ends the session", async () => {
      await a.page.getByRole("button", { name: "Sign out" }).click();
      await a.page.getByRole("heading", { name: "Sign in" }).waitFor({ timeout: 15000 });
      const status = await a.page.evaluate(async () => (await fetch("/api/state")).status);
      check(status === 401, `after sign-out /api/state answered ${status}`);
      return "401 after sign-out";
    });
    await a.page.screenshot({ path: join(OUT, "remote-login.png") });
  } catch (e) {
    record("remote test stopped early", false, String(e.message ?? e).split("\n")[0]);
    for (const [name, p] of pages) await p.screenshot({ path: join(OUT, `remote-failed-${name}.png`) }).catch(() => {});
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
  await writeFile(join(OUT, "remote-report.json"), JSON.stringify({ results, root, base }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed. Report: e2e/out/remote-report.json` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
