// Browser test of the installable app (PWA, docs/mobile.md §9): the production server, reached through its
// signed-in remote listener as a phone would (bound to 127.0.0.1 here, which browsers treat as secure, as they
// do the Tailscale https address).
//
//   npm run test:pwa        (from frontend/; needs Microsoft Edge)
//
// Checks: the manifest and icons; Chromium's own installability verdict; the service worker controls the page
// but never answers or stores /api and /audio (no decisions, recordings or sessions on the phone); the
// session survives closing the app; the app opens with an "unreachable host" or "offline" screen instead of
// a browser error; a new build is offered with "Reload" instead of reloading by itself; the phone layout and
// audio work in the installed shell. Disposable mapping data; the real mappings are hashed before and after.

import { spawn } from "node:child_process";
import { cp, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { FRONTEND, HERE, REPO, runFixture, sha256File, start, stopProcess, waitForHttp } from "./harness.mjs";

const OUT = join(HERE, "out");
const LOCAL_PORT = 8797;
const REMOTE_PORT = 8798;
const BASE = `http://127.0.0.1:${REMOTE_PORT}/`;
const SLOT = "es:A10_010_cryotech#0";
const PASSWORD = "e2e-pwa-password-1"; // a throw-away account in the disposable copy only

const results = [];
const pageErrors = [];
function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
let page = null;
async function step(name, fn) {
  try {
    record(name, true, (await fn()) ?? "");
  } catch (e) {
    record(name, false, String(e && e.message ? e.message : e).split("\n")[0]);
    if (page) await page.screenshot({ path: join(OUT, "pwa-failed.png") }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

function run(command, args, options = {}) {
  return new Promise((done) => {
    const child = spawn(command, args, { cwd: options.cwd ?? REPO, env: { ...process.env, ...options.env }, windowsHide: true });
    let out = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (out += c));
    child.on("exit", (code) => done({ code, out }));
  });
}
const vite = (args) => run(process.execPath, [join(FRONTEND, "node_modules", "vite", "bin", "vite.js"), ...args], { cwd: FRONTEND });

/** Width and height of a PNG, from its header. */
async function pngSize(path) {
  const data = await readFile(path);
  check(data.toString("ascii", 1, 4) === "PNG", `${path} is not a PNG`);
  return [data.readUInt32BE(16), data.readUInt32BE(20)];
}

/** Every URL in the page's Cache Storage. */
const cachedUrls = () =>
  page.evaluate(async () => {
    const urls = [];
    for (const name of await caches.keys()) for (const req of await (await caches.open(name)).keys()) urls.push(req.url);
    return urls;
  });

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-pwa-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  const live = join(tmp, "dist-live"); // what the server serves; replaced by a newer build later
  let server;
  let context;
  const startServer = async () => {
    server = start("api", "python", ["scripts/ui/m4_server.py", "--root", root, "--port", String(LOCAL_PORT), "--lan",
      "--remote-host", "127.0.0.1", "--remote-port", String(REMOTE_PORT), "--static-dir", live, "--no-open",
      "--state-dir", join(root, "studio-state")], { cwd: REPO });
    await waitForHttp(`${BASE}api/session`);
  };

  try {
    await step("build the Studio with the app manifest and the service worker", async () => {
      const { code, out } = await vite(["build"]);
      check(code === 0, out.slice(-400));
      await cp(join(FRONTEND, "dist"), live, { recursive: true });
      return "frontend/dist";
    });

    await step("the manifest names the app, opens standalone and lists valid icons", async () => {
      const manifest = JSON.parse(await readFile(join(live, "manifest.webmanifest"), "utf-8"));
      check(manifest.name === "Halo CE Localization Studio", `name ${manifest.name}`);
      check(manifest.short_name === "Halo Studio", `short_name ${manifest.short_name}`);
      check(manifest.display === "standalone", `display ${manifest.display}`);
      check(manifest.theme_color && manifest.background_color, "no theme or background colour");
      const sizes = [];
      for (const icon of manifest.icons) {
        const [w, h] = await pngSize(join(live, icon.src));
        check(`${w}x${h}` === icon.sizes, `${icon.src} is ${w}x${h}, manifest says ${icon.sizes}`);
        sizes.push(`${icon.sizes} ${icon.purpose}`);
      }
      for (const need of ["192x192 any", "512x512 any", "512x512 maskable"]) check(sizes.includes(need), `missing ${need} icon`);
      const [aw, ah] = await pngSize(join(live, "icons/apple-touch-icon-180.png"));
      check(aw === 180 && ah === 180, "Apple touch icon is not 180x180");
      const html = await readFile(join(live, "index.html"), "utf-8");
      for (const tag of ['rel="manifest"', 'rel="apple-touch-icon"', 'rel="icon"', 'name="theme-color"']) check(html.includes(tag), `index.html lacks ${tag}`);
      return sizes.join(", ") + ", apple 180x180";
    });

    await step("the service worker precaches only the Studio's own files and never answers the server's routes", async () => {
      const sw = await readFile(join(live, "sw.js"), "utf-8");
      const urls = [...sw.matchAll(/url:"([^"]+)"/g)].map((m) => m[1]);
      check(urls.length > 5, "no precache list found");
      check(!urls.some((u) => /^(api|audio|classic)\b|\.(wav|wem|fsb|json|db)$/i.test(u)), `unexpected precache entries: ${urls.join(" ")}`);
      for (const route of ["api", "audio", "classic"]) check(sw.includes(`^\\/${route}`), `the navigation fallback does not exclude /${route}`);
      check(!/runtimeCaching|CacheFirst|StaleWhileRevalidate|NetworkFirst/.test(sw), "the worker caches at run time");
      return `${urls.length} precached files (scripts, styles, fonts, icons, the page)`;
    });

    await step("create a throw-away account and start the host with remote access", async () => {
      const { code, out } = await run("python", ["scripts/ui/studio_users.py", "--root", root, "--state-dir", join(root, "studio-state"), "add", "phone", "--role", "editor"], { env: { STUDIO_PASSWORD: PASSWORD } });
      check(code === 0, out);
      await startServer();
      const res = await fetch(`${BASE}manifest.webmanifest`);
      check(res.headers.get("content-type")?.startsWith("application/manifest+json"), `manifest served as ${res.headers.get("content-type")}`);
      const sw = await fetch(`${BASE}sw.js`);
      check(sw.headers.get("cache-control") === "no-cache", `sw.js Cache-Control ${sw.headers.get("cache-control")}`);
      return "manifest application/manifest+json; sw.js no-cache";
    });

    // A persistent profile, as on a real phone: browsers never offer installing from a private window.
    context = await chromium.launchPersistentContext(join(tmp, "profile"), {
      channel: "msedge",
      headless: true,
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    });
    page = await context.newPage();
    page.on("pageerror", (err) => pageErrors.push(err.message));
    const fromWorker = [];
    page.on("response", (res) => {
      const path = new URL(res.url()).pathname;
      if ((path.startsWith("/api/") || path.startsWith("/audio/")) && res.fromServiceWorker()) fromWorker.push(path);
    });

    await step("sign in on the phone; the service worker takes control", async () => {
      await page.goto(BASE);
      await page.getByRole("heading", { name: "Sign in" }).waitFor({ timeout: 30000 });
      await page.getByLabel("User name").fill("phone");
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.getByTestId("menu-toggle").waitFor({ timeout: 15000 });
      await page.evaluate(() => navigator.serviceWorker.ready);
      await page.reload();
      await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller), null, { timeout: 15000 });
      return "controlled by sw.js";
    });

    await step("Chromium reports the app as installable", async () => {
      const cdp = await context.newCDPSession(page);
      const { installabilityErrors } = await cdp.send("Page.getInstallabilityErrors");
      check(installabilityErrors.length === 0, JSON.stringify(installabilityErrors));
      const manifest = await cdp.send("Page.getAppManifest");
      check(!manifest.errors?.length, JSON.stringify(manifest.errors));
      return "no installability errors";
    });

    await step("matching works in the app shell: the line opens and its audio plays from the host", async () => {
      await page.goto(`${BASE}#/match?level=a10&slot=${encodeURIComponent(SLOT)}`);
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      check((await page.evaluate(() => document.documentElement.dataset.layout)) === "phone", "not the phone layout");
      const play = page.getByTestId("match-context").getByRole("button", { name: /^ES$/ });
      await play.tap();
      await page.waitForFunction((el) => el.getAttribute("aria-pressed") === "true", await play.elementHandle(), { timeout: 15000 });
      await play.tap();
      check(fromWorker.length === 0, `answered by the service worker: ${fromWorker.join(" ")}`);
      return "Spain's recording played; every /api and /audio answer came from the host";
    });

    await step("nothing private is stored on the phone: no audio, decisions or API answers in Cache Storage", async () => {
      const urls = await cachedUrls();
      check(urls.length > 0, "nothing precached");
      const leaks = urls.filter((u) => /\/(api|audio|classic)\b/.test(new URL(u).pathname));
      check(leaks.length === 0, `cached: ${leaks.join(" ")}`);
      const cookies = await context.cookies();
      const session = cookies.find((c) => c.httpOnly);
      check(session && session.expires > Date.now() / 1000 + 3600, "the session cookie does not outlive closing the app");
      const storage = await page.evaluate(() => Object.keys(localStorage).join(" "));
      check(!/token|session|csrf/i.test(storage), `localStorage holds ${storage}`);
      return `${urls.length} cached files, all app shell; session cookie HttpOnly and persistent`;
    });

    await step("standalone: the installed app hides the install offer (installed state simulated)", async () => {
      await page.goto(`${BASE}#/network`);
      await page.getByTestId("install-panel").waitFor({ timeout: 15000 });
      // Headless Chromium cannot open an installed app or emulate display-mode; this page reports itself
      // installed the way Safari on iOS does (navigator.standalone), to check what the Studio does then.
      await page.addInitScript(() => Object.defineProperty(navigator, "standalone", { value: true }));
      await page.reload();
      await page.getByRole("heading", { name: /Network access/ }).waitFor({ timeout: 15000 });
      check((await page.getByTestId("install-panel").count()) === 0, "the install offer shows inside the installed app");
      check((await page.getByTestId("install-app").count()) === 0, "the menu offers installing inside the installed app");
      return "no install offer when running as the app";
    });

    await step("the session survives closing and reopening the app", async () => {
      await page.close();
      page = await context.newPage();
      await page.goto(`${BASE}#/match`);
      await page.getByTestId("tab-mcc").waitFor({ timeout: 30000 });
      check((await page.getByRole("heading", { name: "Sign in" }).count()) === 0, "asked to sign in again");
      return "still signed in";
    });

    await step("with the host off, the app opens and explains what to check", async () => {
      await stopProcess(server);
      await page.reload();
      const box = page.getByTestId("host-unreachable");
      await box.waitFor({ timeout: 20000 });
      check(/can't reach the studio host/i.test(await box.innerText()), await box.innerText());
      await page.screenshot({ path: join(OUT, "pwa-unreachable.png") });
      await startServer();
      await page.getByTestId("retry-host").tap();
      await page.getByTestId("tab-mcc").waitFor({ timeout: 30000 });
      return "unreachable screen, then back after Try again";
    });

    await step("offline, the app says the device is offline", async () => {
      await context.setOffline(true);
      await page.reload();
      await page.getByTestId("host-unreachable").getByText(/This device is offline/i).waitFor({ timeout: 20000 });
      await context.setOffline(false);
      await page.getByTestId("tab-mcc").waitFor({ timeout: 30000 }); // reconnects by itself
      return "offline message, reconnected by itself";
    });

    await step("a new build is offered with Reload, never applied by itself", async () => {
      // A second build that differs by one precached file, served in place of the first.
      const publicCopy = join(tmp, "public-v2");
      await cp(join(FRONTEND, "public"), publicCopy, { recursive: true });
      await writeFile(join(publicCopy, "build-v2.svg"), '<svg xmlns="http://www.w3.org/2000/svg"/>');
      const config = join(OUT, "pwa-v2.config.mjs");
      await writeFile(config, `import base from ${JSON.stringify(join(FRONTEND, "vite.config.ts").replace(/\\/g, "/"))};
export default { ...base, publicDir: ${JSON.stringify(publicCopy)}, build: { outDir: ${JSON.stringify(join(tmp, "dist-v2"))}, emptyOutDir: true } };\n`);
      const { code, out } = await vite(["build", "--config", config]);
      check(code === 0, out.slice(-400));
      await rm(live, { recursive: true, force: true });
      await cp(join(tmp, "dist-v2"), live, { recursive: true });
      const marker = await page.evaluate(() => (window.__probe = "same page"));
      await page.evaluate(() => navigator.serviceWorker.getRegistration().then((r) => r.update()));
      await page.getByTestId("pwa-update").waitFor({ timeout: 30000 });
      check((await page.evaluate(() => window.__probe)) === marker, "the page reloaded by itself");
      await page.getByTestId("pwa-update").getByRole("button", { name: "Reload" }).tap();
      await page.waitForFunction(() => window.__probe === undefined, null, { timeout: 30000 });
      await page.getByTestId("tab-mcc").waitFor({ timeout: 30000 });
      const urls = await cachedUrls();
      check(urls.some((u) => u.includes("build-v2.svg")), "the new version's files are not in use");
      return "banner shown; Reload switched to the new build";
    });

    await step("no errors in the page", async () => {
      const real = pageErrors.filter((e) => !/Failed to fetch|NetworkError|ERR_INTERNET_DISCONNECTED|ERR_CONNECTION_REFUSED/.test(e));
      check(real.length === 0, real.slice(0, 3).join(" | "));
    });

    await step("the real mappings were not touched", async () => {
      const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
      check(after === fixture.real_mappings_sha256, "the real mapping file changed");
      return "hash unchanged";
    });
  } finally {
    await context?.close().catch(() => {});
    await stopProcess(server);
    await writeFile(join(OUT, "pwa-results.json"), JSON.stringify({ results, pageErrors }, null, 2));
  }
}

main().then(
  () => {
    const failed = results.filter((r) => !r.ok).length;
    console.log(`\n${results.length - failed}/${results.length} passed`);
    process.exit(failed ? 1 : 0);
  },
  (e) => {
    console.error(e);
    process.exit(1);
  },
);
