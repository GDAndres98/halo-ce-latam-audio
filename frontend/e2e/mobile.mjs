// Browser test of the Studio on phones and tablets (prompt 46).
//
//   npm run test:mobile      (from frontend/; needs Microsoft Edge)
//
// Emulates a phone (390 x 844, touch, mobile viewport) and drives the matching workflow with the finger: real
// touch events (Chrome DevTools Protocol) for taps and drags on the waveform, not mouse clicks. Then turns the
// phone sideways, opens the same page as a tablet and as a desktop, and checks that the work survives every
// layout change without the panels being created again, and that nothing overflows sideways.
//
// Works on a disposable copy of the mapping data (scripts/ui/e2e_fixture.py); the real mappings are hashed
// before and after.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { API_PORT, HERE, WEB_PORT, Services, handleConfirms, runFixture, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";
const CUSTOM_TEXT = "¡Despierte, Jefe Maestro! (prueba móvil)";
const PHONE = { width: 390, height: 844 };

const results = [];
const pageErrors = [];
let page = null;
let cdp = null;

function record(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
async function step(name, fn) {
  try {
    record(name, true, (await fn()) ?? "");
  } catch (e) {
    record(name, false, String(e && e.message ? e.message : e).split("\n")[0]);
    if (page) await page.screenshot({ path: join(OUT, "mobile-failed.png") }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const near = (a, b, tolerance) => Math.abs(a - b) <= tolerance;
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- Touch input through the DevTools protocol: the page receives touch (and pointer) events, as from a finger.
async function touchDrag(points, { stepMs = 25 } = {}) {
  const [first, ...rest] = points;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: first.x, y: first.y }] });
  await pause(150); // longer than WaveSurfer's touch delay (100 ms) before a drag counts
  for (const p of rest) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: p.x, y: p.y }] });
    await pause(stepMs);
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await pause(150);
}
function line(x1, y1, x2, y2, steps = 12) {
  return Array.from({ length: steps + 1 }, (_, i) => ({ x: x1 + ((x2 - x1) * i) / steps, y: y1 + ((y2 - y1) * i) / steps }));
}
async function tap(locator) {
  await locator.scrollIntoViewIfNeeded();
  await locator.tap();
}

// ---- Page helpers.
const layout = () => page.evaluate(() => document.documentElement.dataset.layout);
const pane = () => page.evaluate(() => new URLSearchParams(location.hash.split("?")[1] ?? "").get("pane"));
async function noSideways(label) {
  const { scroll, width } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  if (scroll > width + 1) {
    const culprits = await page.evaluate((w) => {
      const out = [];
      for (const el of document.querySelectorAll("body *:not(.backdrop):not(.backdrop *):not(.section-chips *)")) {
        const r = el.getBoundingClientRect();
        const parent = el.parentElement?.getBoundingClientRect();
        if (r.right > w + 1 && r.width > 0 && parent && parent.right <= w + 1) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${(el.textContent ?? "").trim().slice(0, 30)}" ${Math.round(r.right)}`);
      }
      return out.slice(-8).join(", ");
    }, width);
    throw new Error(`${label}: the page is ${scroll}px wide in a ${width}px window (${culprits})`);
  }
  return `${label} ${width}px`;
}
async function visible(selector) {
  return page.locator(selector).first().isVisible();
}
const editor = () => page.getByRole("region", { name: "Audio editing" });
const compare = () => page.getByRole("region", { name: "Compare the original and the replacement" });
const editorWave = () => editor().locator(".wave-view");
const waveA = () => compare().locator(".wave-view").nth(0);
const waveB = () => compare().locator(".wave-view").nth(1);

function parsePosition(text) {
  const [m, s] = text.trim().split(":");
  return Number(m) * 60 + Number(s);
}
async function playhead(wave) {
  return parsePosition((await wave.getByTestId("wave-time").innerText()).split("/")[0]);
}
async function waveDuration(wave) {
  const host = wave.getByTestId("wave-host");
  await page.waitForFunction((el) => Number(el.dataset.duration) > 0, await host.elementHandle(), { timeout: 30000 });
  return Number(await host.getAttribute("data-duration"));
}
async function selection(wave) {
  const box = wave.getByTestId("wave-selection");
  if (!(await box.count())) return null;
  const [a, b] = (await box.innerText()).split("(")[0].split("–").map((t) => parsePosition(t));
  return { start: a, end: b };
}
async function waitPlaying(wave, playing = true, timeout = 15000) {
  await page.waitForFunction(([el, want]) => el.dataset.playing === (want ? "true" : "false"), [await wave.elementHandle(), playing], {
    timeout,
  });
}
/** The waveform's drawing area in page pixels (the 16 px time ruler under it is left out). */
async function waveBox(wave) {
  await wave.scrollIntoViewIfNeeded();
  const box = await wave.getByTestId("wave-host").boundingBox();
  return { x: box.x, y: box.y, width: box.width, height: box.height - 16 };
}

/** Marks the three panels, to prove later that they were not created again (a new element has no mark). */
async function markPanels() {
  await page.evaluate(() => {
    for (const id of ["pane-mcc", "pane-match", "pane-ce"]) document.getElementById(id).dataset.probe = "kept";
    document.querySelector("#pane-match .editor .wave-view").dataset.probe = "kept";
  });
}
async function panelsKept() {
  return page.evaluate(() =>
    ["pane-mcc", "pane-match", "pane-ce"].every((id) => document.getElementById(id)?.dataset.probe === "kept") &&
    document.querySelector("#pane-match .editor .wave-view")?.dataset.probe === "kept",
  );
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-mobile-"));
  const fixture = await runFixture(join(tmp, "root"));
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(fixture.root);
  let browser;
  let context;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${fixture.root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    context = await browser.newContext({
      viewport: PHONE,
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
      userAgent:
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    });
    page = await context.newPage();
    cdp = await context.newCDPSession(page);
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));

    // ---------------------------------------------------------------- Phone, portrait
    await step("a phone gets the one-pane layout with the bottom navigation", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10`);
      await page.getByPlaceholder(/Accents and case ignored/).waitFor({ timeout: 30000 });
      check((await layout()) === "phone", `layout is ${await layout()}`);
      check(await page.evaluate(() => matchMedia("(pointer: coarse)").matches), "the emulated phone has no coarse pointer");
      check(await visible('[data-testid="tab-mcc"]'), "no bottom navigation");
      const nav = await page.locator(".workspace-tabs").boundingBox();
      check(near(nav.y + nav.height, PHONE.height, 2), `the navigation is not at the bottom (${nav.y + nav.height})`);
      check(await visible("#pane-mcc"), "the MCC list is not shown first");
      check(!(await visible("#pane-ce")) && !(await visible("#pane-match")), "more than one pane is shown");
      check(!(await visible(".split-handle")) && !(await visible(".layout-bar")), "desktop resizing controls are shown");
      await page.screenshot({ path: join(OUT, "mobile-phone-mcc.png") });
      return await noSideways("MCC pane");
    });

    await step("the header menu folds behind a button and opens with a tap", async () => {
      check(!(await visible("#main-nav")), "the main menu is open on a phone");
      await tap(page.getByTestId("menu-toggle"));
      await page.locator("#main-nav").waitFor({ state: "visible" });
      const link = await page.locator("#main-nav a").first().boundingBox();
      check(link.height >= 43, `menu items are ${link.height}px tall`);
      await tap(page.getByTestId("menu-toggle"));
      await page.locator("#main-nav").waitFor({ state: "hidden" });
      return `menu item ${Math.round(link.height)}px tall`;
    });

    let mccScroll = 0;
    await step("search the MCC lines and scroll the list", async () => {
      const search = page.getByPlaceholder(/Accents and case ignored/);
      await tap(search);
      await search.fill("cryotech");
      await page.locator("#pane-mcc li.row-item", { hasText: "a10_140_cryotech" }).waitFor({ timeout: 15000 });
      await page.evaluate(() => document.activeElement.blur());
      await page.evaluate(() => window.scrollTo({ top: 600 }));
      mccScroll = await page.evaluate(() => window.scrollY);
      check(mccScroll > 300, `the list did not scroll (${mccScroll})`);
      return `scrolled to ${mccScroll}px`;
    });

    await step("play Spain's recording from the list without opening the line", async () => {
      const row = page.locator("#pane-mcc li.row-item", { hasText: "a10_140_cryotech" });
      const play = row.getByRole("button", { name: /^ES$/ });
      await tap(play);
      await page.waitForFunction((el) => el.getAttribute("aria-pressed") === "true", await play.elementHandle(), { timeout: 15000 });
      check((await pane()) !== "match", "playing a recording opened the line");
      await tap(play); // stop it again
      return "played and stopped";
    });

    await step("tapping a line opens it on the Matching pane with its key in view", async () => {
      await tap(page.locator("#pane-mcc li.row-item", { hasText: "a10_010_cryotech" }).first());
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      check((await pane()) === "match", `pane is ${await pane()}`);
      check(await visible("#pane-match") && !(await visible("#pane-mcc")), "the Matching pane is not the one shown");
      const key = await page.getByTestId("context-key").innerText();
      check(key === SLOT, `context bar shows ${key}`);
      const bar = await page.getByTestId("match-context").boundingBox();
      const header = await page.locator("header.top").boundingBox();
      check(header.height < 70, `the header takes ${header.height}px (it wraps)`);
      check(near(bar.y, header.y + header.height, 2), `the line's bar is not under the header (${bar.y})`);
      await page.screenshot({ path: join(OUT, "mobile-phone-matching.png") });
      return await noSideways("Matching pane");
    });

    await step("the line's bar stays at the top while the decision scrolls, with section shortcuts", async () => {
      await page.locator(".section-chips").getByRole("button", { name: "Subtitles" }).tap();
      await pause(400);
      const bar = await page.getByTestId("match-context").boundingBox();
      check(bar.y <= 1, "the bar scrolled away");
      const subtitles = await page.locator('#pane-match [data-section="subtitles"]').boundingBox();
      check(subtitles.y >= bar.height - 4 && subtitles.y < 300, `the Subtitles section is at ${subtitles.y}`);
      await page.locator(".section-chips").getByRole("button", { name: "Audio" }).tap();
      return `bar ${Math.round(bar.height)}px; Subtitles section at ${Math.round(subtitles.y)}px`;
    });

    let ceScroll = 0;
    await step("search Campaign Evolved candidates and listen to one", async () => {
      await tap(page.getByTestId("tab-ce"));
      check((await pane()) === "ce", `pane is ${await pane()}`);
      check((await page.getByTestId("context-key").innerText()) === SLOT, "the open line's key is gone on the candidates pane");
      const search = page.getByPlaceholder(/Partial words/);
      await tap(search);
      await search.fill("00460_cryotech");
      const row = page.locator("#pane-ce li.row-item", { hasText: CE_REF });
      await row.waitFor({ timeout: 15000 });
      await page.evaluate(() => document.activeElement.blur());
      const play = row.getByRole("button", { name: /^es-MX$/ });
      await tap(play);
      await page.waitForFunction((el) => el.getAttribute("aria-pressed") === "true", await play.elementHandle(), { timeout: 15000 });
      await tap(play);
      ceScroll = await page.evaluate(() => window.scrollY);
      await page.screenshot({ path: join(OUT, "mobile-phone-ce.png") });
      return await noSideways("candidates pane");
    });

    await step("switching panes keeps each pane's search and scroll position", async () => {
      await tap(page.getByTestId("tab-mcc"));
      check((await page.getByPlaceholder(/Accents and case ignored/).inputValue()) === "cryotech", "the MCC search was lost");
      await page.evaluate(() => window.scrollTo({ top: 500 }));
      mccScroll = await page.evaluate(() => window.scrollY);
      await tap(page.getByTestId("tab-ce"));
      await tap(page.getByTestId("tab-mcc"));
      const back = await page.evaluate(() => window.scrollY);
      check(near(back, mccScroll, 40), `MCC list scrolled to ${back}, was ${mccScroll}`);
      await tap(page.getByTestId("tab-ce"));
      check((await page.getByPlaceholder(/Partial words/).inputValue()) === "00460_cryotech", "the candidate search was lost");
      const ceBack = await page.evaluate(() => window.scrollY);
      check(near(ceBack, ceScroll, 40), `candidates scrolled to ${ceBack}, was ${ceScroll}`);
      return `MCC back at ${back}px, candidates at ${ceBack}px`;
    });

    await step("use a candidate: the save strip offers to review it, the tabs show the change", async () => {
      await tap(page.locator("#pane-ce li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }));
      await page.getByTestId("action-strip").waitFor({ timeout: 15000 });
      await page.getByTestId("strip-review").waitFor({ timeout: 15000 }); // the Review offer, on the candidates pane
      check((await page.locator(".tab-count").innerText()) === "1", "the candidates tab does not count the chosen recording");
      check(await visible(".tab-match .tab-dot"), "the Matching tab does not show unsaved changes");
      const strip = await page.getByTestId("action-strip").boundingBox();
      const nav = await page.locator(".workspace-tabs").boundingBox();
      check(strip.y + strip.height <= nav.y + 1, "the save strip overlaps the navigation");
      await page.screenshot({ path: join(OUT, "mobile-phone-chosen.png") });
      await tap(page.getByTestId("strip-review"));
      check((await pane()) === "match", "Review did not open the Matching pane");
      check((await editor().getByTestId("wave-host").count()) === 1, "no editor waveform");
      return "Review → Matching";
    });

    let duration = 0;
    await step("tap the waveform to move the playhead", async () => {
      duration = await waveDuration(editorWave());
      const box = await waveBox(editorWave());
      await page.touchscreen.tap(box.x + box.width * 0.5, box.y + box.height / 2);
      await pause(200);
      const at = await playhead(editorWave());
      check(near(at, duration * 0.5, duration * 0.04), `playhead ${at} s after tapping the middle of ${duration} s`);
      check((await selection(editorWave())) === null, "a tap made a selection");
      return `tapped at 50% → ${at.toFixed(3)} s`;
    });

    await step("the waveform leaves up-and-down swipes to the page", async () => {
      const touchAction = await page.evaluate(() => {
        const host = document.querySelector("#pane-match .editor .wave-host > div");
        const part = host?.shadowRoot?.querySelector('[part="scroll"]');
        return part ? getComputedStyle(part).touchAction : null;
      });
      check(touchAction === "pan-y", `the waveform's touch-action is ${touchAction}`);
      const box = await waveBox(editorWave());
      const before = await page.evaluate(() => window.scrollY);
      const x = box.x + box.width * 0.6;
      await touchDrag(line(x, box.y + box.height - 4, x + 3, box.y - 160, 10));
      await pause(400);
      const after = await page.evaluate(() => window.scrollY);
      // Synthetic touch events do not always start the browser's own scrolling; what matters is that the
      // swipe did not select, and that the waveform leaves vertical panning to the page (touch-action).
      check((await selection(editorWave())) === null, "a vertical swipe made a selection");
      return `touch-action pan-y; page scroll ${before} → ${after}px`;
    });

    await step("drag sideways with a finger to select", async () => {
      const box = await waveBox(editorWave());
      const y = box.y + box.height / 2;
      await touchDrag(line(box.x + box.width * 0.3, y, box.x + box.width * 0.45, y));
      const s = await selection(editorWave());
      check(s, "no selection after a sideways drag");
      check(near(s.start, duration * 0.3, duration * 0.04) && near(s.end, duration * 0.45, duration * 0.05), `selection ${s.start}–${s.end}`);
      return `${s.start.toFixed(3)}–${s.end.toFixed(3)} s`;
    });

    await step("cut the selection, then undo", async () => {
      await tap(editor().getByRole("button", { name: /Cut selection/ }));
      await editor().getByTestId("cut").first().waitFor();
      check((await editor().getByTestId("cut").count()) === 1, "no cut");
      await tap(editor().getByRole("button", { name: /^Undo/ }));
      check((await editor().getByTestId("cut").count()) === 0, "undo did not remove the cut");
      return "cut, undone";
    });

    await step("drag the wide trim handle with a finger", async () => {
      const box = await waveBox(editorWave());
      const handle = await page.evaluate(() => {
        const host = document.querySelector("#pane-match .editor .wave-host > div");
        const keep = [...(host?.shadowRoot?.querySelectorAll('[part~="studio-keep"]') ?? [])][0];
        const left = keep?.querySelector('[part*="region-handle-left"]');
        const r = left?.getBoundingClientRect();
        return r ? { x: r.x + r.width / 2, width: r.width } : null;
      });
      check(handle, "no trim handle");
      check(handle.width >= 24, `the trim handle is ${handle.width}px wide`);
      const y = box.y + box.height / 2;
      const x0 = Math.max(handle.x, box.x + 3);
      await touchDrag(line(x0, y, x0 + box.width * 0.1, y));
      const trimStart = Number(await editor().getByLabel("Trim start (s)").inputValue());
      check(trimStart > duration * 0.04, `trim start ${trimStart} s after dragging the handle`);
      return `handle ${handle.width}px; trim start ${trimStart} s`;
    });

    await step("type a selection by number, then trim to it", async () => {
      const start = editor().getByLabel("Selection start (s)");
      const end = editor().getByLabel("Selection end (s)");
      await start.fill("0.5");
      await start.blur();
      await end.fill("1.2");
      await end.blur();
      const s = await selection(editorWave());
      check(s && near(s.start, 0.5, 0.01) && near(s.end, 1.2, 0.01), `selection ${JSON.stringify(s)}`);
      await tap(editor().getByRole("button", { name: /Trim to selection/ }));
      const trimStart = Number(await editor().getByLabel("Trim start (s)").inputValue());
      check(near(trimStart, 0.5, 0.01), `trim start ${trimStart}`);
      await tap(editor().getByRole("button", { name: /^Undo/ }));
      return "0.5–1.2 s selected and trimmed (undone)";
    });

    await step("zoom in, switch to Pan to scroll along the recording, fit again", async () => {
      await tap(editorWave().getByRole("button", { name: "Zoom in" }));
      await tap(editorWave().getByRole("button", { name: "Zoom in" }));
      const toggle = editorWave().getByTestId("pan-toggle");
      await toggle.waitFor();
      await tap(toggle);
      check((await toggle.getAttribute("aria-pressed")) === "true", "Pan is not on");
      const touchAction = await page.evaluate(() => {
        const part = document.querySelector("#pane-match .editor .wave-host > div")?.shadowRoot?.querySelector('[part="scroll"]');
        return getComputedStyle(part).touchAction;
      });
      check(touchAction.includes("pan-x"), `in Pan mode touch-action is ${touchAction}`);
      await tap(editorWave().getByRole("button", { name: "Fit the whole recording" }));
      check((await editorWave().getByTestId("pan-toggle").count()) === 0, "the Pan switch stays after fitting");
      return `Pan mode touch-action ${touchAction}`;
    });

    await step("insert a silence and set a fade with the numeric fields", async () => {
      await tap(editor().getByTestId("insert-silence"));
      await editor().getByTestId("silence").first().waitFor();
      const fade = editor().getByLabel("Fade in (ms)");
      await fade.fill("40");
      await fade.blur();
      check((await fade.inputValue()) === "40", "fade not kept");
      return "silence inserted; fade in 40 ms";
    });

    await step("the full-screen editor covers the screen and keeps the edits", async () => {
      await tap(editor().getByTestId("expand-editor"));
      const box = await editor().boundingBox();
      check(near(box.width, PHONE.width, 2) && near(box.height, PHONE.height, 2), `full screen is ${box.width}x${box.height}`);
      check(await page.evaluate(() => document.documentElement.classList.contains("editor-expanded")), "the page behind still scrolls");
      check((await editor().getByTestId("silence").count()) === 1, "the inserted silence is gone");
      await editor().getByRole("button", { name: /^Original$/ }).waitFor();
      await page.screenshot({ path: join(OUT, "mobile-phone-editor-full.png") });
      await tap(editor().getByTestId("expand-editor"));
      check(!(await page.evaluate(() => document.documentElement.classList.contains("editor-expanded"))), "full screen did not close");
      return `${box.width}x${box.height}`;
    });

    await step("listen and compare with one thumb: Original, Replacement, A then B", async () => {
      await compare().getByTestId("preview-status").scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelector('[data-testid="preview-status"]')?.dataset.state === "ready", null, {
        timeout: 60000,
      });
      await waveDuration(waveB());
      await tap(compare().getByTestId("play-a"));
      await waitPlaying(waveA());
      await tap(compare().getByTestId("play-b"));
      await waitPlaying(waveB());
      await waitPlaying(waveA(), false, 5000);
      await tap(compare().getByRole("button", { name: /Stop both|^Stop$/ }).last());
      await waitPlaying(waveB(), false, 5000);
      await tap(compare().getByRole("button", { name: /A then B/ }));
      await waitPlaying(waveA());
      await waitPlaying(waveB(), true, 20000); // B starts by itself when A ends
      await tap(compare().getByRole("button", { name: /Stop both|^Stop$/ }).last());
      const diff = await compare().getByTestId("duration-diff").innerText();
      return `A then B played; difference ${diff}`;
    });

    await step("write a custom subtitle; the bottom bars step aside for the keyboard", async () => {
      const sub = page.locator('#pane-match [data-section="subtitles"]');
      await tap(sub.getByText("Write my own LATAM Spanish text"));
      const box = sub.locator("textarea");
      await tap(box);
      check(await page.locator(".match-view.typing").count(), "typing is not detected");
      check(!(await visible('[data-testid="tab-match"]')), "the navigation covers the keyboard area while typing");
      await box.fill(CUSTOM_TEXT);
      const size = await box.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      check(size >= 16, `the subtitle box text is ${size}px (phones zoom in below 16px)`);
      await page.evaluate(() => document.activeElement.blur());
      await noSideways("after typing");
      check(await visible('[data-testid="tab-match"]'), "the navigation did not come back");
      check((await sub.getByTestId("subtitle-preview-text").innerText()) === CUSTOM_TEXT, "the preview does not show the text");
      return `${size}px text`;
    });

    await step("unsaved work survives switching panes", async () => {
      await tap(page.getByTestId("tab-mcc"));
      await tap(page.getByTestId("tab-ce"));
      await tap(page.getByTestId("tab-match"));
      check((await page.locator('#pane-match [data-section="subtitles"] textarea').inputValue()) === CUSTOM_TEXT, "the subtitle was lost");
      check((await editor().getByTestId("silence").count()) === 1, "the edits were lost");
      check(await visible(".tab-match .tab-dot"), "the unsaved mark is gone");
      return "draft, edits and text kept";
    });

    await step("save the audio and the subtitle together", async () => {
      await tap(page.getByTestId("save-draft"));
      await page.waitForFunction(() => !document.querySelector(".tab-match .tab-dot"), null, { timeout: 30000 });
      const saved = await (await fetch(`http://127.0.0.1:${API_PORT}/api/slot?id=${encodeURIComponent(SLOT)}`)).json();
      check(saved.mapping?.audio?.ce_line_ref === CE_REF || JSON.stringify(saved.mapping?.audio ?? {}).includes(CE_REF), "the audio was not saved");
      check(saved.custom_text === CUSTOM_TEXT, `the subtitle was not saved (${JSON.stringify(saved.custom_text)})`);
      return "saved";
    });

    await step("approve the audio and the subtitle separately, each confirmed", async () => {
      const bar = page.locator('#pane-match [data-section="save"]');
      await tap(bar.getByRole("button", { name: "Approve audio" }));
      await bar.getByText("audio: approved").waitFor({ timeout: 15000 });
      check(await bar.getByRole("button", { name: "Approve subtitle" }).isEnabled(), "the subtitle cannot be approved on its own");
      await tap(bar.getByRole("button", { name: "Approve subtitle" }));
      await bar.getByText("subtitle: approved").waitFor({ timeout: 15000 });
      check(await editor().getByLabel("Trim start (s)").isDisabled(), "approved audio can still be edited");
      await page.screenshot({ path: join(OUT, "mobile-phone-approved.png") });
      return "audio approved, then subtitle approved";
    });

    await step("Needs rework unlocks the audio again", async () => {
      const bar = page.locator('#pane-match [data-section="save"]');
      await tap(bar.getByRole("button", { name: "Needs rework (audio)" }));
      await bar.getByText("audio: needs rework").waitFor({ timeout: 15000 });
      check(!(await editor().getByLabel("Trim start (s)").isDisabled()), "the audio is still locked");
      check(await bar.getByText("subtitle: approved").isVisible(), "the subtitle approval changed too");
      return "audio needs rework; subtitle still approved";
    });

    await step("Save & next opens the next unmatched line from the save strip", async () => {
      // a10 is fully decided in the real data: list a campaign level that still has undecided lines.
      const state = await (await fetch(`http://127.0.0.1:${API_PORT}/api/state`)).json();
      const open = state.levels.find((l) => l.group === "campaign" && l.progress.decided < l.slots);
      check(open, "no campaign level with undecided lines in the data");
      await tap(page.getByTestId("tab-mcc"));
      await page.getByPlaceholder(/Accents and case ignored/).fill("");
      await page.locator("#pane-mcc select").first().selectOption(open.level);
      await page.evaluate(() => document.activeElement.blur());
      await page.waitForFunction(() => document.querySelectorAll("#pane-mcc li.row-item").length > 20, null, { timeout: 15000 });
      await tap(page.getByTestId("tab-match"));
      const flag = page.getByTestId("flag-fits").locator("input");
      await tap(page.getByTestId("flag-fits"));
      check(await flag.isChecked(), "the flag did not change");
      await page.evaluate(() => window.scrollTo({ top: 0 }));
      await page.getByTestId("action-strip").waitFor();
      await tap(page.getByTestId("action-strip").getByRole("button", { name: /Next/ }));
      await page.waitForFunction((slot) => !decodeURIComponent(location.hash).includes(`slot=${slot}`), SLOT, { timeout: 30000 });
      const key = await page.getByTestId("context-key").innerText();
      check(key !== SLOT, "still on the same line");
      check((await pane()) === "match", "the next line did not open on the Matching pane");
      return `next: ${key}`;
    });

    // ---------------------------------------------------------------- Layout changes without remounting
    await step("go back to the test line", async () => {
      await tap(page.getByTestId("tab-mcc"));
      await page.locator("#pane-mcc select").first().selectOption("a10");
      await tap(page.locator("#pane-mcc li.row-item", { hasText: "a10_010_cryotech" }).first());
      await page.waitForFunction((slot) => decodeURIComponent(location.hash).includes(`slot=${slot}`), SLOT);
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      await waveDuration(editorWave());
      await markPanels();
    });

    await step("a phone turned sideways keeps the one-pane layout, shorter bars, nothing reloaded", async () => {
      await page.setViewportSize({ width: 844, height: 390 });
      await pause(300);
      check((await layout()) === "phone", `layout is ${await layout()}`);
      check(await panelsKept(), "a panel was created again");
      const nav = await page.locator(".workspace-tabs").boundingBox();
      check(nav.height < 56, `the navigation is ${nav.height}px tall sideways`);
      await page.screenshot({ path: join(OUT, "mobile-phone-landscape.png") });
      return await noSideways("landscape");
    });

    await step("a tablet shows a list beside the Matching panel", async () => {
      await page.setViewportSize({ width: 768, height: 1024 });
      await pause(300);
      check((await layout()) === "tablet", `layout is ${await layout()}`);
      check(await panelsKept(), "a panel was created again");
      check(await visible("#pane-match") && (await visible("#pane-mcc")), "the MCC list and the Matching panel are not side by side");
      check(!(await visible('[data-testid="tab-match"]')), "the tablet offers a Matching tab");
      const list = await page.locator("#pane-mcc").boundingBox();
      const centre = await page.locator("#pane-match").boundingBox();
      check(list.x + list.width <= centre.x + 1, "the panes overlap");
      await tap(page.getByTestId("tab-ce"));
      check(await visible("#pane-ce") && !(await visible("#pane-mcc")) && (await visible("#pane-match")), "the list did not switch");
      await page.screenshot({ path: join(OUT, "mobile-tablet.png") });
      return await noSideways("tablet");
    });

    await step("a desktop window gets the three resizable panels back", async () => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await pause(300);
      check((await layout()) === "desktop", `layout is ${await layout()}`);
      check(await panelsKept(), "a panel was created again");
      for (const id of ["#pane-mcc", "#pane-match", "#pane-ce"]) check(await visible(id), `${id} hidden on a desktop`);
      check((await page.locator(".split-handle:visible").count()) === 2, "the dividers are missing");
      check(await visible(".layout-bar"), "the layout bar is missing");
      for (const hidden of [".workspace-tabs", ".match-context", ".menu-toggle"]) check(!(await visible(hidden)), `${hidden} shown on a desktop`);
      const mcc = await page.locator("#pane-mcc").boundingBox();
      const centre = await page.locator("#pane-match").boundingBox();
      const ce = await page.locator("#pane-ce").boundingBox();
      check(mcc.x < centre.x && centre.x < ce.x && near(mcc.y, ce.y, 2), "the panels are not side by side");
      await page.screenshot({ path: join(OUT, "mobile-desktop.png") });
      return await noSideways("desktop");
    });

    await step("no page overflows sideways at common phone and tablet widths", async () => {
      const sizes = [
        [360, 740],
        [390, 844],
        [430, 932],
        [768, 1024],
        [1024, 768],
      ];
      const seen = [];
      for (const [width, height] of sizes) {
        await page.setViewportSize({ width, height });
        for (const tab of ["mcc", "match", "ce"]) {
          if ((await layout()) === "phone") await tap(page.getByTestId(`tab-${tab}`));
          await pause(150);
          await noSideways(`${width}x${height} ${tab}`);
          if ((await layout()) !== "phone") break;
        }
        for (const route of ["/", "/builds", "/data", "/network"]) {
          await page.goto(`http://localhost:${WEB_PORT}/#${route}`);
          await pause(600);
          await noSideways(`${width}x${height} ${route}`);
        }
        await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent(SLOT)}`);
        await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
        seen.push(`${width}x${height} (${await layout()})`);
      }
      return seen.join(", ");
    });

    await step("no errors in the page", async () => {
      check(pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));
    });

    await step("the real mappings were not touched", async () => {
      const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
      check(after === realBefore, "the real mapping file changed");
      return "hash unchanged";
    });
  } finally {
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
    await services.down();
    await writeFile(join(OUT, "mobile-results.json"), JSON.stringify({ results, pageErrors }, null, 2));
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
