// Browser checks of the Halo CE (2001) theme: every screen, the confirmation dialog, the dashboard's menu
// keyboard, fonts, contrast, overflow, reduced motion and rendering cost (docs/ui-design-system.md).
//
//   npm run test:theme        (from frontend/; needs Microsoft Edge)
//
// Works on a disposable copy of the mapping data. Screenshots go to e2e/out/theme-*.png. Nothing here writes to
// the real mappings or config; the one approval dialog opened is cancelled.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, handleConfirms, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const LINE = "a10_010_cryotech";
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const BASE = `http://localhost:${WEB_PORT}/#`;
const PAGES = [
  ["dashboard", `${BASE}/`],
  ["matching", `${BASE}/match?level=a10&slot=${encodeURIComponent(SLOT)}`],
  ["build-test", `${BASE}/builds`],
  ["data", `${BASE}/data`],
];

const results = [];
function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
async function step(name, fn) {
  try {
    record(name, true, (await fn()) ?? "");
  } catch (e) {
    record(name, false, String(e && e.message ? e.message : e).split("\n")[0]);
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

/** Fails the test if the page ever uses the browser's own alert / confirm / prompt. */
function noNativeDialogs(page, seen) {
  page.on("dialog", (d) => {
    seen.push(d.message());
    void d.dismiss();
  });
}

async function openPage(browser, url, viewport = { width: 1440, height: 960 }, options = {}) {
  const context = await browser.newContext({ viewport, reducedMotion: options.reducedMotion ?? "no-preference" });
  const page = await context.newPage();
  return { page, context, url, ready: page.goto(url) };
}

async function ready(page) {
  await page.locator("h1, h2").first().waitFor({ timeout: 60000 });
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
}

/** WCAG contrast for every visible text, against its first opaque-ish background (same rule as ux.mjs). */
async function contrastFailures(page) {
  return page.evaluate(() => {
    const channel = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const parse = (value) => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const [r, g, b, a = "1"] = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return { r, g, b, a };
    };
    const luminance = ({ r, g, b }) => 0.2126 * channel(r / 255) + 0.7152 * channel(g / 255) + 0.0722 * channel(b / 255);
    const background = (el) => {
      for (let node = el; node; node = node.parentElement) {
        const c = parse(getComputedStyle(node).backgroundColor);
        if (c && c.a > 0) return c;
      }
      return { r: 1, g: 4, b: 12, a: 1 };
    };
    const failures = [];
    for (const el of document.querySelectorAll("body *")) {
      const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join("");
      if (!text) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none" || el.getBoundingClientRect().width === 0) continue;
      if (el.closest(".sr-only")) continue;
      const fg = parse(style.color);
      if (!fg) continue;
      const bg = background(el);
      const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
      const ratio = (hi + 0.05) / (lo + 0.05);
      const size = parseFloat(style.fontSize);
      const bold = Number(style.fontWeight) >= 700;
      const needed = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      // Disabled controls are exempt in WCAG (1.4.3); they are still checked against 3:1 here.
      const disabled = el.closest("button:disabled, fieldset:disabled, [aria-disabled='true']");
      if (ratio < (disabled ? 3 : needed)) failures.push({ text: text.slice(0, 50), ratio: Number(ratio.toFixed(2)) });
    }
    return failures;
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-theme-"));
  const fixture = await runFixture(join(tmp, "root"));
  const services = new Services(fixture.root);
  const realBefore = await sha256File(join(HERE, "..", "..", "mappings", "manual_mappings.json")).catch(() => null);
  const nativeDialogs = [];
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });

    // ---- Each screen: renders in the theme (fonts, frame), contrast, screenshot.
    for (const [name, url] of PAGES) {
      await step(`${name}: themed render, fonts loaded, text contrast AA`, async () => {
        const { page, context, ready: loaded } = await openPage(browser, url);
        noNativeDialogs(page, nativeDialogs);
        await loaded;
        await ready(page);
        if (name === "matching") await page.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 60000 });
        const fonts = await page.evaluate(() => ({
          display: document.fonts.check('16px "Michroma"'),
          ui: document.fonts.check('16px "Saira Variable"'),
          h1: getComputedStyle(document.querySelector("h1, .column h2")).fontFamily,
          frame: getComputedStyle(document.querySelector(".top")).borderBottomColor,
        }));
        check(fonts.display && fonts.ui, `fonts not loaded: ${JSON.stringify(fonts)}`);
        check(/Michroma/.test(fonts.h1), `titles not in the display face: ${fonts.h1}`);
        check(fonts.frame === "rgb(47, 140, 255)", `top band rule is ${fonts.frame}`);
        const failures = await contrastFailures(page);
        await page.screenshot({ path: join(OUT, `theme-${name}.png`) });
        await page.screenshot({ path: join(OUT, `theme-${name}-full.png`), fullPage: true });
        await context.close();
        check(!failures.length, `${failures.length} low-contrast text(s): ${JSON.stringify(failures.slice(0, 4))}`);
        return "Michroma + Saira, frame rule, contrast OK";
      });
    }

    // ---- The dashboard reads as a menu: arrow keys move the framed highlight; Enter opens the level.
    await step("dashboard menu: arrow keys move the highlight, Enter opens Matching", async () => {
      const { page, context, ready: loaded } = await openPage(browser, `${BASE}/`);
      await loaded;
      await ready(page);
      const first = page.locator("a.menu-item").first();
      await first.focus();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      const highlighted = await page.locator("a.menu-item.highlighted .code").innerText();
      const detail = await page.locator(".menu-detail h2").innerText();
      check(highlighted.toLowerCase() === "a50", `highlight on ${highlighted}`);
      check(/truth and reconciliation/i.test(detail), `detail shows ${detail}`);
      await page.screenshot({ path: join(OUT, "theme-dashboard-menu.png") });
      await page.keyboard.press("Enter");
      await page.waitForURL(/#\/match\?level=a50/, { timeout: 15000 });
      await context.close();
      return `${highlighted} → ${detail}, Enter → Matching`;
    });

    // ---- Matching: keyboard, playback, waveform, subtitle, the confirmation dialog.
    const { page, context, ready: loaded } = await openPage(browser, PAGES[1][1], { width: 1600, height: 1000 });
    noNativeDialogs(page, nativeDialogs);
    await loaded;
    await page.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 60000 });
    await ready(page);

    await step("matching: the selected line is framed and connected to the centre panel", async () => {
      const row = page.locator("li.row-item.selected");
      const look = await row.evaluate((el) => {
        const after = getComputedStyle(el, "::after");
        return { border: getComputedStyle(el).borderTopColor, connector: after.content !== "none" && after.width };
      });
      check(look.border === "rgb(47, 140, 255)", `selected frame ${look.border}`);
      check(look.connector && parseFloat(look.connector) > 4, `connector ${look.connector}`);
      return `frame ${look.border}, connector ${look.connector}`;
    });

    await step("matching: centre sections are numbered and every section has an icon", async () => {
      const sections = await page.locator(".column.center .block h3").evaluateAll((hs) =>
        hs.map((h) => ({ n: getComputedStyle(h, "::before").content, icon: Boolean(h.querySelector("svg")), text: h.textContent.trim() })),
      );
      check(sections.length >= 6, `${sections.length} sections`);
      check(sections.every((s) => s.icon), `a section has no icon: ${JSON.stringify(sections)}`);
      check(sections[0].n.includes("01") || /counter/.test(sections[0].n) || sections[0].n !== "none", `no number: ${sections[0].n}`);
      return sections.map((s) => s.text).join(" · ");
    });

    await step("matching: J / K keys move through lines and the waveform plays", async () => {
      await page.locator(".line-title h2").click();
      await page.keyboard.press("j");
      await page.waitForFunction((id) => document.querySelector("li.row-item.selected")?.id !== id, `mcc-${SLOT}`, { timeout: 15000 });
      await page.keyboard.press("k");
      await page.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 15000 });
      const wave = page.locator(".wave-view").first();
      await wave.getByRole("button", { name: "Play", exact: true }).click();
      await page.waitForFunction(() => document.querySelector(".wave-view")?.dataset.playing === "true", null, { timeout: 15000 });
      const glow = await wave.evaluate((el) => getComputedStyle(el).borderTopColor);
      await page.keyboard.press("Escape");
      return `playing frame ${glow}`;
    });

    await step("matching: choose a candidate, edit the waveform, type a subtitle (no save)", async () => {
      await page.getByPlaceholder(/Partial words/).fill("vo_scr_m01_00460");
      const row = page.locator("li.row-item", { hasText: CE_REF });
      await row.waitFor({ timeout: 30000 });
      await row.getByRole("button", { name: /Use this recording/ }).click();
      await page.getByText("Recording chosen").waitFor({ timeout: 10000 });
      const editor = page.getByRole("region", { name: "Audio editing" });
      const host = editor.getByTestId("wave-host");
      await page.waitForFunction(() => [...document.querySelectorAll("[data-testid=wave-host]")].some((h) => Number(h.dataset.duration) > 0 && h.closest(".editable")), null, { timeout: 30000 });
      await host.scrollIntoViewIfNeeded();
      const box = await host.boundingBox();
      const y = box.y + (box.height - 16) / 2; // above the time ruler
      await page.mouse.move(box.x + box.width * 0.3, y);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.45, y, { steps: 10 });
      await page.mouse.up();
      await editor.getByTestId("wave-selection").waitFor({ timeout: 5000 });
      await page.getByLabel("Write my own LATAM Spanish text").check();
      await page.locator(".custom-subtitle textarea").fill("Perdón por el sobresalto, Jefe Maestro.");
      await page.screenshot({ path: join(OUT, "theme-matching-editing.png") });
      return "selection made, custom subtitle typed";
    });

    await step("matching: leaving unsaved work opens the themed dialog (Stay keeps the line)", async () => {
      const confirms = handleConfirms(page, () => false);
      await page.locator(".line-title h2").click();
      await page.keyboard.press("j");
      await page.locator("dialog.confirm-dialog[open]").waitFor({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(600);
      confirms.stop();
      check(confirms.messages.some((m) => /unsaved changes/.test(m)), `dialog messages: ${JSON.stringify(confirms.messages)}`);
      check((await page.getByRole("heading", { level: 2, name: LINE }).count()) === 1, "left the line");
      return "Stay on this line: kept";
    });

    await step("the confirmation dialog: framed, focus on Cancel, Esc cancels, shortcuts paused", async () => {
      // Open the dialog by leaving the line, inspect it, then press Esc.
      await page.locator(".line-title h2").click();
      await page.keyboard.press("j");
      const dialog = page.locator("dialog.confirm-dialog[open]");
      await dialog.waitFor({ timeout: 5000 });
      await page.waitForTimeout(250);
      const info = await dialog.evaluate((el) => ({
        border: getComputedStyle(el).borderTopColor,
        focused: document.activeElement?.dataset.confirm,
        title: el.querySelector("h2")?.textContent.trim(),
      }));
      await page.screenshot({ path: join(OUT, "theme-dialog.png") });
      const failures = await contrastFailures(page);
      await page.keyboard.press("k"); // a shortcut: must not move the list while the dialog is open
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached", timeout: 3000 }).catch(() => {});
      check((await page.locator("dialog.confirm-dialog[open]").count()) === 0, "Esc did not close the dialog");
      check(info.focused === "no", `focus starts on ${info.focused}`);
      check((await page.getByRole("heading", { level: 2, name: LINE }).count()) === 1, "a shortcut acted behind the dialog");
      check(!failures.length, `dialog contrast: ${JSON.stringify(failures.slice(0, 3))}`);
      return `${info.title}; border ${info.border}`;
    });

    await step("the browser's own confirm() is never used", async () => {
      check(!nativeDialogs.length, `native dialogs: ${JSON.stringify(nativeDialogs)}`);
      return "none";
    });

    // ---- Rendering cost: keyboard line changes stay quick, and no long tasks while idle.
    await step("performance: J / K line changes and idle long tasks", async () => {
      await page.getByLabel("Notes").fill(""); // the line still has unsaved edits; leave them by confirming
      const confirms = handleConfirms(page, () => true);
      await page.goto(`${BASE}/match?level=a30`);
      await page.locator("li.row-item").first().waitFor({ timeout: 60000 });
      await page.locator("li.row-item").first().click();
      await page.locator(".line-title h2").waitFor({ timeout: 30000 });
      const times = [];
      for (let i = 0; i < 6; i++) {
        const before = await page.locator(".line-title h2").innerText();
        const t = Date.now();
        await page.keyboard.press("j");
        await page.waitForFunction((b) => document.querySelector(".line-title h2")?.textContent !== b, before, { timeout: 15000 });
        times.push(Date.now() - t);
      }
      const longTasks = await page.evaluate(
        () =>
          new Promise((done) => {
            const seen = [];
            const observer = new PerformanceObserver((list) => seen.push(...list.getEntries().map((e) => Math.round(e.duration))));
            observer.observe({ type: "longtask", buffered: false });
            setTimeout(() => {
              observer.disconnect();
              done(seen);
            }, 2000);
          }),
      );
      confirms.stop();
      times.sort((a, b) => a - b);
      const median = times[Math.floor(times.length / 2)];
      check(median < 400, `median line change ${median} ms`);
      check(!longTasks.length, `long tasks while idle: ${longTasks}`);
      return `line change median ${median} ms (max ${times.at(-1)}), idle long tasks ${longTasks.length}`;
    });
    await context.close();

    // ---- Reduced motion: transitions and animations are switched off.
    await step("reduced motion: no transitions or animations", async () => {
      const { page: p, context: c, ready: r } = await openPage(browser, `${BASE}/`, undefined, { reducedMotion: "reduce" });
      await r;
      await ready(p);
      const durations = await p.evaluate(() => {
        const button = document.querySelector("button, a.menu-item");
        return { transition: getComputedStyle(button).transitionDuration };
      });
      await c.close();
      check(durations.transition.split(",").every((d) => parseFloat(d) < 0.001), `transition ${durations.transition}`);
      return `transition ${durations.transition}`;
    });

    // ---- Responsive: no horizontal scrolling on any screen at four widths.
    for (const width of [1440, 1100, 820, 390]) {
      await step(`no horizontal page scroll at ${width} px on every screen`, async () => {
        const overflows = [];
        for (const [name, url] of PAGES) {
          const { page: p, context: c, ready: r } = await openPage(browser, url, { width, height: 900 });
          await r;
          await ready(p);
          const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          if (width === 390) await p.screenshot({ path: join(OUT, `theme-${name}-390.png`), fullPage: false });
          await c.close();
          if (overflow > 1) overflows.push(`${name} +${overflow}px`);
        }
        check(!overflows.length, overflows.join(", "));
        return "none";
      });
    }

    await step("the real mappings file was not touched", async () => {
      const after = await sha256File(join(HERE, "..", "..", "mappings", "manual_mappings.json")).catch(() => null);
      check(after === realBefore, "manual_mappings.json changed");
      return "unchanged";
    });
  } catch (e) {
    record("theme test stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    await browser?.close();
    await services.down();
  }
  await writeFile(join(OUT, "theme-report.json"), JSON.stringify({ results }, null, 2));
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
}

main();
