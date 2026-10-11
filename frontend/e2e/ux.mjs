// Browser tests of the Studio's layout, theme, gain setting and accessibility (prompt 35, section 8).
//
//   npm run test:ux          (from frontend/; needs Microsoft Edge)
//
// Works on a disposable copy of the mapping data and a disposable config folder. Nothing here writes to the
// real mappings or the real config/audio_export.json.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, runPython, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const LINE = "a10_010_cryotech";
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const DEFAULT_LEFT = 300;
const DEFAULT_RIGHT = 360;

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
    throw e;
  }
}

const matchingUrl = (query = "") => `http://localhost:${WEB_PORT}/#/match?level=a10${query}`;

async function openPage(browser, url, viewport = { width: 1440, height: 960 }) {
  const page = await browser.newPage({ viewport });
  page.on("dialog", (d) => d.accept());
  await page.goto(url);
  return page;
}

async function widths(page) {
  return page.evaluate(() => {
    const w = (sel) => Math.round(document.querySelector(sel).getBoundingClientRect().width);
    return { left: w(".column.mcc"), centre: w(".column.center"), right: w(".column.ce") };
  });
}

/** Drags a divider by dx pixels, with the mouse, the way a person does. */
async function drag(page, side, dx) {
  const handle = page.locator(`.split-handle.side-${side}`);
  const box = await handle.boundingBox();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 8; i++) await page.mouse.move(x + (dx * i) / 8, y);
  await page.mouse.up();
}

/** Computes WCAG contrast for every visible piece of text on the page. */
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
      return { r: 14, g: 19, b: 25, a: 1 };
    };
    const failures = [];
    const seen = new Set();
    for (const el of document.querySelectorAll("body *")) {
      const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join("");
      if (!text) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none" || el.getBoundingClientRect().width === 0) continue;
      const fg = parse(style.color);
      const bg = background(el);
      if (!fg) continue;
      const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
      const ratio = (hi + 0.05) / (lo + 0.05);
      const size = parseFloat(style.fontSize);
      const bold = Number(style.fontWeight) >= 700;
      const needed = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      if (ratio < needed) {
        const key = `${text.slice(0, 40)}|${ratio.toFixed(2)}`;
        if (!seen.has(key)) {
          seen.add(key);
          failures.push({ text: text.slice(0, 60), ratio: Number(ratio.toFixed(2)), needed });
        }
      }
    }
    return failures;
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-ux-"));
  const fixture = await runFixture(join(tmp, "root"));
  const services = new Services(fixture.root);
  let browser;
  try {
    await services.up();
    browser = await chromium.launch({ channel: "msedge", headless: true });

    // ---- 1-2: three panels render.
    let page = await openPage(browser, matchingUrl(`&slot=${encodeURIComponent(SLOT)}`));
    await step("the three matching panels render", async () => {
      await page.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 60000 });
      const w = await widths(page);
      if (!w.left || !w.centre || !w.right) throw new Error(`a panel is missing: ${JSON.stringify(w)}`);
      return `left ${w.left}px, centre ${w.centre}px, right ${w.right}px`;
    });

    // ---- 3: both dividers resize, with the mouse.
    await step("drag the divider between the MCC and centre panels", async () => {
      const before = await widths(page);
      await drag(page, "left", 60);
      const after = await widths(page);
      if (Math.abs(after.left - before.left - 60) > 6) throw new Error(`left panel went ${before.left} -> ${after.left}`);
      return `left ${before.left} -> ${after.left} px`;
    });
    await step("drag the divider between the centre and candidate panels", async () => {
      const before = await widths(page);
      await drag(page, "right", -60);
      const after = await widths(page);
      if (after.right - before.right < 50) throw new Error(`right panel went ${before.right} -> ${after.right}`);
      return `right ${before.right} -> ${after.right} px`;
    });

    // ---- 4: minimum widths hold.
    await step("panels keep their minimum widths", async () => {
      await drag(page, "left", -2000);
      await drag(page, "right", 2000);
      const w = await widths(page);
      if (w.left < 240 || w.right < 260 || w.centre < 420) throw new Error(`below minimum: ${JSON.stringify(w)}`);
      return `left ${w.left}, centre ${w.centre}, right ${w.right} px`;
    });

    // ---- 7: search text and selection survive a resize.
    await step("resizing keeps the search text, the selected line and the candidate search", async () => {
      await page.getByPlaceholder(/Accents and case ignored/).fill("cryotech");
      await page.getByPlaceholder(/Partial words/).fill("vo_scr_m01_00460");
      await drag(page, "left", 40);
      await drag(page, "right", -40);
      const mccSearch = await page.getByPlaceholder(/Accents and case ignored/).inputValue();
      const ceSearch = await page.getByPlaceholder(/Partial words/).inputValue();
      const heading = await page.getByRole("heading", { level: 2, name: LINE }).count();
      if (mccSearch !== "cryotech" || ceSearch !== "vo_scr_m01_00460" || !heading) throw new Error("state lost during resize");
      return "both searches and the selected line kept";
    });

    // ---- 8: playback and subtitle editing still work after resizing.
    await step("audio plays and subtitle text can be typed after resizing", async () => {
      await page.getByRole("button", { name: "Play (m)" }).click();
      await page.getByRole("button", { name: "■ Play (m)" }).waitFor({ timeout: 10000 });
      await page.keyboard.press("Escape");
      await page.getByRole("checkbox", { name: /Needs radio effect/ }).check();
      await page.getByLabel("Notes").fill("nota de prueba de diseño");
      if ((await page.getByLabel("Notes").inputValue()) !== "nota de prueba de diseño") throw new Error("typing lost");
      return "play, stop and typing work";
    });

    // ---- 5: reload keeps the proportions.
    await step("panel proportions persist across a reload", async () => {
      const before = await widths(page);
      await drag(page, "left", 50);
      const changed = await widths(page);
      await page.reload();
      await page.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 60000 });
      const after = await widths(page);
      if (Math.abs(after.left - changed.left) > 2) throw new Error(`reload: ${changed.left} -> ${after.left}`);
      if (Math.abs(before.left - changed.left) < 20) throw new Error("the drag did not change the width");
      return `left ${after.left} px after reload`;
    });

    // ---- 6: reset returns to the defaults.
    await step("Reset layout restores the default proportions", async () => {
      await page.getByRole("button", { name: "Reset layout" }).click();
      const w = await widths(page);
      if (Math.abs(w.left - DEFAULT_LEFT) > 2 || Math.abs(w.right - DEFAULT_RIGHT) > 2) throw new Error(JSON.stringify(w));
      return `left ${w.left}, right ${w.right} px`;
    });

    // ---- 18: keyboard reaches the dividers, with a visible focus ring, and arrows resize.
    await step("the dividers are keyboard-operable with a visible focus ring", async () => {
      // Reach the divider with Tab, as a keyboard user does (script focus does not show the focus ring).
      const divider = page.locator(".split-handle.side-left");
      await page.locator("body").click({ position: { x: 4, y: 4 } });
      for (let i = 0; i < 60; i++) {
        if (await divider.evaluate((el) => el === document.activeElement)) break;
        await page.keyboard.press("Tab");
      }
      if (!(await divider.evaluate((el) => el === document.activeElement))) throw new Error("Tab does not reach the divider");
      const ring = await divider.evaluate((el) => getComputedStyle(el).outlineStyle);
      if (ring === "none") throw new Error("no focus ring on the divider");
      const before = (await widths(page)).left;
      await page.keyboard.press("ArrowRight");
      const after = (await widths(page)).left;
      if (after !== before + 16) throw new Error(`ArrowRight moved ${before} -> ${after}`);
      await page.keyboard.press("ArrowLeft");
      return "focus ring visible; arrows move the divider 16 px";
    });

    // ---- 16: theme and contrast on each main page.
    for (const [name, url] of [["Dashboard", `http://localhost:${WEB_PORT}/#/`], ["Matching", matchingUrl(`&slot=${encodeURIComponent(SLOT)}`)], ["Build & Test", `http://localhost:${WEB_PORT}/#/builds`]]) {
      await step(`text contrast meets WCAG AA on ${name}`, async () => {
        const p = await openPage(browser, url);
        await p.waitForLoadState("networkidle");
        await p.locator("h1, h2").first().waitFor({ timeout: 60000 });
        await p.waitForTimeout(800);
        const failures = await contrastFailures(p);
        await p.screenshot({ path: join(OUT, `theme-${name.replace(/\W+/g, "-").toLowerCase()}.png`), fullPage: true });
        await p.close();
        if (failures.length) throw new Error(`${failures.length} low-contrast text(s): ${JSON.stringify(failures.slice(0, 3))}`);
        return "all visible text meets its ratio";
      });
    }

    // ---- 17: responsive widths, no horizontal scrolling.
    for (const width of [1440, 1100, 820, 390]) {
      await step(`no horizontal scrolling at ${width} px`, async () => {
        const p = await openPage(browser, matchingUrl(`&slot=${encodeURIComponent(SLOT)}`), { width, height: 900 });
        await p.getByRole("heading", { level: 2, name: LINE }).waitFor({ timeout: 60000 });
        const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        const stacked = width <= 1000 ? await p.locator(".split-handle").first().isHidden() : true;
        await p.close();
        if (overflow > 1) throw new Error(`page is ${overflow} px wider than the window`);
        if (!stacked) throw new Error("dividers are shown on a narrow screen");
        return `overflow ${Math.max(0, overflow)} px`;
      });
    }
    await page.close();

    // ---- 9-12, 14: the global gain, in the disposable environment.
    page = await openPage(browser, `http://localhost:${WEB_PORT}/#/builds`);
    await step("the default global gain is +4.0 dB", async () => {
      await page.getByRole("heading", { name: "Global audio gain" }).waitFor({ timeout: 60000 });
      const text = await page.locator("#gain-help").innerText();
      if (!/\+4\.0 dB/.test(text)) throw new Error(`shown as: ${text}`);
      return text.replace(/\s+/g, " ").slice(0, 80);
    });
    await step("the gain can be changed and the change persists after a reload", async () => {
      const gain = page.getByLabel("Gain (dB)");
      await gain.fill("2.5");
      await page.getByRole("button", { name: "Save gain" }).click();
      await page.getByText(/Global gain set to \+2\.5 dB/).waitFor({ timeout: 15000 });
      await page.reload();
      await page.getByRole("heading", { name: "Global audio gain" }).waitFor({ timeout: 60000 });
      const value = await page.getByLabel("Gain (dB)").inputValue();
      if (Number(value) !== 2.5) throw new Error(`after reload: ${value}`);
      return "2.5 dB kept";
    });
    await step("the M6 export reads the saved gain", async () => {
      const { code, out } = await runPython(["-c",
        `import sys; sys.path.insert(0, 'scripts'); from common.export_config import load_export_config as l; print(l(r'${fixture.root}')['global_gain_db'])`]);
      if (code !== 0 || Number(out.trim()) !== 2.5) throw new Error(`export reads ${out.trim()}`);
      return "2.5 dB";
    });
    await step("changing the gain marks the existing builds stale, and does not rebuild them", async () => {
      const builds = await page.evaluate(async () => (await fetch("/api/builds")).json());
      if (!builds.builds.length) throw new Error("no builds in the disposable copy to check");
      const reasons = builds.builds.map((b) => b.stale_reasons.join(" / "));
      if (!builds.builds.every((b) => b.stale)) throw new Error(`not all stale: ${reasons.join(" | ")}`);
      return `${builds.builds.length} build(s) stale: ${[...new Set(reasons)].join(" | ")}`;
    });
    await step("Reset to default brings the gain back to +4.0 dB", async () => {
      await page.getByRole("button", { name: /Reset to default/ }).click();
      await page.getByText(/Global gain set to \+4\.0 dB/).waitFor({ timeout: 15000 });
      return "+4.0 dB";
    });
    await page.close();

    // ---- 15: approved decisions stay protected (the workflow test covers the full cycle).
    await step("the real mapping decisions did not change", async () => {
      const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
      if (after !== fixture.real_mappings_sha256) throw new Error("real manual_mappings.json changed");
      return `sha256 ${after.slice(0, 16)}…`;
    });
  } catch (e) {
    record("the UX run stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }

  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "ux-report.json"), JSON.stringify({ results }, null, 2));
  console.log(failed.length ? `\n${failed.length} check(s) failed. Report: e2e/out/ux-report.json` : "\nAll UX checks passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
