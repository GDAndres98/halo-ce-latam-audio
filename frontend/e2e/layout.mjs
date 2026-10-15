// Layout audit: every page of the Studio at 360, 390, 430, 768, 1024, 1440 and 1920 px, on disposable data
// with the real decisions and the real build folders (work/ is linked, read-only here).
//
//   npm run test:layout              (from frontend/; needs Microsoft Edge; about 2 minutes)
//   npm run test:layout -- --shots   also writes a full-page screenshot per page and width to e2e/out/layout/
//
// For each page and width it checks, on the rendered page (not the CSS):
// - the document does not scroll sideways;
// - no visible text escapes its box: an element whose content is wider than its box and does not clip,
//   ellipsize or scroll it on purpose (overflow other than visible) is reported with its text;
// - no visible element sticks out of the window on the right;
// - on touch widths (430 px and below), buttons and fields are at least 40 px tall.
// The Build & Test checks: builds are listed newest first, by their real timestamps; the desktop table and the
// phone cards are each the one shown at their widths; long names keep the row inside the window.
// Nothing is installed or built: the server gets a throw-away, empty --mcc-root, so install is impossible.

import { lstat, mkdir, mkdtemp, readdir, rm, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture } from "./harness.mjs";

const OUT = join(HERE, "out", "layout");
const SHOTS = process.argv.includes("--shots");
const WIDTHS = [360, 390, 430, 768, 1024, 1440, 1920];
const PAGES = [
  { name: "dashboard", path: "#/" },
  { name: "match-list", path: "#/match?level=a10&pane=mcc" },
  { name: "match-line", path: "#/match?level=a10&slot=es%3AA10_350_captkeyes%230&pane=match" },
  { name: "match-ce", path: "#/match?level=a10&slot=es%3AA10_350_captkeyes%230&pane=ce" },
  { name: "builds", path: "#/builds" },
  { name: "data", path: "#/data" },
  { name: "network", path: "#/network" },
];

const results = [];
function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}

/** Everything wrong with the layout of the current page, as short strings. */
function audit(touch) {
  const W = document.documentElement.clientWidth;
  const out = [];
  const label = (el) => {
    const cls = [...el.classList].slice(0, 3).join(".");
    const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
    return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} "${text}"`;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none";
  };
  // Containers that scroll or clip on purpose: their children may be wider, and the user can reach them.
  const clips = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.overflowX !== "visible") return true;
    }
    return false;
  };
  if (document.documentElement.scrollWidth > W + 1) out.push(`page scrolls sideways: ${document.documentElement.scrollWidth}px in ${W}px`);
  const skip = ".backdrop, .backdrop *, svg, svg *, wave, wave *, canvas, [data-audit-ignore], [data-audit-ignore] *";
  for (const el of document.querySelectorAll("body *")) {
    if (el.matches(skip) || !visible(el)) continue;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    // Text wider than its own box, drawn outside it. Bars that run edge to edge on purpose (negative side
    // margins or fixed to the window, inside it) are not overflow.
    const fullBleed = (c) => {
      const cs = getComputedStyle(c);
      return (cs.position === "fixed" || parseFloat(cs.marginLeft) < 0 || parseFloat(cs.marginRight) < 0) && c.getBoundingClientRect().right <= W + 1;
    };
    const limit = r.right - parseFloat(s.paddingRight) + 1;
    const wide = [...el.querySelectorAll("*")].filter((c) => c.getBoundingClientRect().right > limit && c.getBoundingClientRect().width > 0);
    const excused = (c) => {
      for (let a = c; a && a !== el; a = a.parentElement) if (fullBleed(a)) return true;
      return false;
    };
    if (wide.length && wide.every(excused)) continue;
    // Nothing real is wider: a decoration (::before / ::after, such as the selected line's connector) is.
    // (Descendant elements would be in `wide`; only the element's own text can still be the cause.)
    if (!wide.length) {
      const ownText = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim());
      const textRight = Math.max(0, ...ownText.map((n) => {
        const range = document.createRange();
        range.selectNodeContents(n);
        return range.getBoundingClientRect().right;
      }));
      if (textRight <= limit) continue;
    }
    if (s.overflowX === "visible" && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0 && s.display !== "inline" && el.tagName !== "TABLE" && el.tagName !== "TBODY" && el.tagName !== "THEAD" && el.tagName !== "TR") {
      out.push(`content escapes ${label(el)} (${el.scrollWidth} > ${el.clientWidth})`);
    }
    // Sticking out of the window on the right (outside any scrolling container).
    if (r.right > W + 1 && !clips(el)) out.push(`outside the window ${label(el)} (right ${Math.round(r.right)} > ${W})`);
    if (touch && el.matches("button, select, input:not([type=checkbox]):not([type=radio]):not([type=range]), summary, a.button") && r.height < 40 && !el.closest("[data-audit-small-ok]")) {
      out.push(`small touch target ${label(el)} (${Math.round(r.height)}px)`);
    }
  }
  // An element and its parent often both report: keep the deepest ones, at most 12.
  return [...new Set(out)].slice(-12);
}

/** Deletes the temporary folder. Its work/ and reference-audio/ are junctions to the real folders: every link is
 *  unlinked first (that removes the link, never what it points to), and nothing is deleted if one remains. */
async function removeFixture(base) {
  const links = [];
  const walk = async (dir) => {
    for (const name of await readdir(dir).catch(() => [])) {
      const path = join(dir, name);
      const st = await lstat(path);
      if (st.isSymbolicLink()) links.push(path);
      else if (st.isDirectory()) await walk(path);
    }
  };
  await walk(base);
  for (const link of links) await unlink(link).catch(() => {});
  const left = [];
  links.length = 0;
  await walk(base);
  left.push(...links);
  if (left.length) {
    console.log(`left ${base} in place: links remain (${left.join(", ")})`);
    return;
  }
  await rm(base, { recursive: true, force: true }).catch(() => {});
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const base = await mkdtemp(join(tmpdir(), "studio-layout-"));
  const fixture = await runFixture(join(base, "data"));
  const game = join(base, "no-game");
  await mkdir(game, { recursive: true });
  const services = new Services(fixture.root, ["--mcc-root", game, "--deploy-state", join(base, "deploy")]);
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });
    for (const width of WIDTHS) {
      const touch = width <= 430;
      const context = await browser.newContext({ viewport: { width, height: touch ? 844 : 900 }, hasTouch: touch, isMobile: touch, deviceScaleFactor: 1 });
      const page = await context.newPage();
      for (const p of PAGES) {
        await page.goto(`http://localhost:${WEB_PORT}/${p.path}`);
        await page.waitForLoadState("networkidle").catch(() => {});
        await page.waitForTimeout(600);
        if (p.name === "builds") await page.getByTestId("build-list").waitFor({ timeout: 15000 }).catch(() => {});
        const problems = await page.evaluate(audit, touch);
        record(`${p.name} @ ${width}px`, problems.length === 0, problems.join(" | "));
        if (SHOTS) await page.screenshot({ path: join(OUT, `${p.name}-${width}.png`), fullPage: true });
      }

      // Build & Test: order and presentation.
      try {
        await page.goto(`http://localhost:${WEB_PORT}/#/builds`);
        const list = page.getByTestId("build-list");
        await list.waitFor({ timeout: 15000 });
        const rows = await page.evaluate(() =>
          [...document.querySelectorAll('[data-testid="build-list"] [data-build]')]
            .filter((el) => el.getBoundingClientRect().height > 0)
            .map((el) => ({ name: el.dataset.build, at: el.dataset.builtAt })),
        );
        if (SHOTS && width < 1000) await page.locator(".build-cards > li").nth(0).screenshot({ path: join(OUT, `builds-card-${width}.png`) });
        const times = rows.map((r) => (r.at ? Date.parse(r.at) : NaN));
        const sorted = times.every((t, i) => i === 0 || Number.isNaN(t) || Number.isNaN(times[i - 1]) || times[i - 1] >= t);
        const undatedLast = times.findIndex((t) => Number.isNaN(t)) === -1 || times.slice(times.findIndex((t) => Number.isNaN(t))).every((t) => Number.isNaN(t));
        record(`builds newest first @ ${width}px`, rows.length > 0 && sorted && undatedLast, rows.slice(0, 3).map((r) => `${r.name} ${r.at}`).join(", "));
        if (SHOTS) await page.locator('section[aria-labelledby="builds-title"]').screenshot({ path: join(OUT, `builds-panel-${width}.png`) });
        const shown = await page.evaluate(() => ({
          table: Boolean(document.querySelector(".build-table")?.getBoundingClientRect().height),
          cards: Boolean(document.querySelector(".build-cards")?.getBoundingClientRect().height),
        }));
        const wantCards = width < 1000;
        record(`builds ${wantCards ? "cards" : "table"} @ ${width}px`, shown.cards === wantCards && shown.table === !wantCards, JSON.stringify(shown));
        // Open the first build's details: still nothing sideways.
        const toggle = page.locator('[data-testid="build-list"] [data-build] [aria-expanded]:visible').first();
        await toggle.click();
        await page.getByTestId("build-detail").first().waitFor({ timeout: 10000 });
        await page.waitForTimeout(300);
        const detailProblems = await page.evaluate(audit, false);
        record(`build details open @ ${width}px`, detailProblems.length === 0, detailProblems.join(" | "));
        if (SHOTS) await page.locator('section[aria-labelledby="builds-title"]').screenshot({ path: join(OUT, `builds-detail-${width}.png`) });
        // Keyboard: the toggle is a real button and answers Enter.
        await toggle.focus();
        await page.keyboard.press("Enter");
        record(`build details close with the keyboard @ ${width}px`, (await toggle.getAttribute("aria-expanded")) === "false");
      } catch (e) {
        record(`builds page @ ${width}px`, false, String(e?.message ?? e).split("\n")[0]);
      }
      await context.close();
    }
  } finally {
    await browser?.close().catch(() => {});
    await services.down();
    await removeFixture(base);
  }
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
