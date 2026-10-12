// Browser test of the waveform editor and the comparison players (prompt 36).
//
//   npm run test:editor      (from frontend/; needs Microsoft Edge)
//
// Drives the real interface with the mouse and the keyboard: seek by clicking, drag selections, drag the trim
// handles, cut, fade, undo, reset, preview, A/B and sequential playback, persistence after a reload, the M6
// planner reading the recipe, and the protection of approved audio. Works on a disposable copy of the mapping
// data (scripts/ui/e2e_fixture.py); the real mappings are hashed before and after.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, runPython, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_010_cryotech#0";
const CE_REF = "vo_scr_m01_00460_cryotech#0";

const results = [];
const pageErrors = [];
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
    if (page) await page.screenshot({ path: join(OUT, "editor-failed.png") }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};
const near = (a, b, tolerance) => Math.abs(a - b) <= tolerance;

// ---- Locators. The editor is the "Audio editing" section; the comparison is "Compare the original…".
const editor = () => page.getByRole("region", { name: "Audio editing" });
const compare = () => page.getByRole("region", { name: "Compare the original and the replacement" });
const editorWave = () => editor().locator(".wave-view");
const waveA = () => compare().locator(".wave-view").nth(0);
const waveB = () => compare().locator(".wave-view").nth(1);

/** "0:01.234" -> 1.234 */
function parsePosition(text) {
  const [m, s] = text.trim().split(":");
  return Number(m) * 60 + Number(s);
}
async function playhead(wave) {
  const text = await wave.getByTestId("wave-time").innerText();
  return parsePosition(text.split("/")[0]);
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
async function isPlaying(wave) {
  return (await wave.getAttribute("data-playing")) === "true";
}
async function waitPlaying(wave, playing = true, timeout = 15000) {
  await page.waitForFunction(
    ([el, want]) => el.dataset.playing === (want ? "true" : "false"),
    [await wave.elementHandle(), playing],
    { timeout },
  );
}

/** The waveform's drawing area (inside WaveSurfer's shadow root), in page pixels. */
async function waveBox(wave) {
  await wave.scrollIntoViewIfNeeded();
  const box = await wave.getByTestId("wave-host").boundingBox();
  // The time ruler (16 px) sits under the waveform; aim at the waveform itself.
  return { x: box.x, y: box.y, width: box.width, height: box.height - 16 };
}
const xAt = (box, fraction) => box.x + box.width * fraction;

/** A drag with the mouse, the way a person does: press, move in steps, release. */
async function dragBetween(x1, x2, y) {
  await page.mouse.move(x1, y);
  await page.mouse.down();
  for (let i = 1; i <= 10; i++) await page.mouse.move(x1 + ((x2 - x1) * i) / 10, y);
  await page.mouse.up();
}

async function cutCount() {
  return editor().getByTestId("cut").count();
}
async function fieldNumber(label) {
  return Number(await editor().getByLabel(label).inputValue());
}
async function afterEdits() {
  return Number((await editor().getByTestId("after-edits").innerText()).replace(" s", ""));
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-editor-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(root);
  let browser;
  let duration = 0;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on("dialog", (d) => d.accept());
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent(SLOT)}&cq=${encodeURIComponent("00460_cryotech")}`);
    await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });

    await step("the original MCC recording is available before any replacement is chosen", async () => {
      const seconds = await waveDuration(waveA());
      check((await waveA().innerText()).includes("Original MCC (Spain, read-only)"), "A is not labelled as the original");
      return `A ${seconds.toFixed(3)} s`;
    });

    await step("choose the Campaign Evolved recording; the editor and player B load it", async () => {
      await page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).click();
      duration = await waveDuration(editorWave());
      const b = await waveDuration(waveB());
      check(near(b, duration, 0.01), `B ${b} differs from the editor ${duration}`);
      check((await waveB().innerText()).includes("Campaign Evolved LATAM (edited)"), "B is not the edited replacement by default");
      return `replacement ${duration.toFixed(3)} s`;
    });

    await step("A and B play independently, and only one plays at a time", async () => {
      await waveA().getByRole("button", { name: "Play", exact: true }).click();
      await waitPlaying(waveA());
      await waveB().getByRole("button", { name: "Play", exact: true }).click();
      await waitPlaying(waveB());
      await waitPlaying(waveA(), false, 5000);
      await page.keyboard.press("Escape");
      await waitPlaying(waveB(), false, 5000);
      return "starting B paused A; Escape stopped B";
    });

    await step("the durations of A and B are compared", async () => {
      const a = Number((await compare().getByTestId("duration-a").innerText()).replace(" s", ""));
      const b = Number((await compare().getByTestId("duration-b").innerText()).replace(" s", ""));
      const diff = Number((await compare().getByTestId("duration-diff").innerText()).replace(" s", ""));
      check(near(diff, b - a, 0.002), `difference ${diff} is not ${b - a}`);
      return `A ${a} s, B ${b} s, difference ${diff >= 0 ? "+" : ""}${diff} s`;
    });

    await step("clicking the waveform moves the playhead there", async () => {
      const box = await waveBox(editorWave());
      await page.mouse.click(xAt(box, 0.5), box.y + box.height / 2);
      const at = await playhead(editorWave());
      check(near(at, duration * 0.5, duration * 0.03), `playhead ${at} s, expected about ${(duration * 0.5).toFixed(3)} s`);
      check((await selection(editorWave())) === null, "a click made a selection");
      return `clicked at 50% -> ${at.toFixed(3)} s`;
    });

    await step("dragging across the waveform selects a region (also over the kept part)", async () => {
      const box = await waveBox(editorWave());
      await dragBetween(xAt(box, 0.3), xAt(box, 0.42), box.y + box.height / 2);
      const s = await selection(editorWave());
      check(s, "no selection after dragging");
      check(near(s.start, duration * 0.3, duration * 0.02) && near(s.end, duration * 0.42, duration * 0.02), `selection ${s.start}–${s.end}`);
      return `${s.start.toFixed(3)}–${s.end.toFixed(3)} s`;
    });

    await step("a selection boundary can be adjusted by dragging its edge", async () => {
      const before = await selection(editorWave());
      const box = await waveBox(editorWave());
      const edge = xAt(box, before.end / duration) - 2; // the right-hand handle sits just inside the end
      await dragBetween(edge, edge + box.width * 0.05, box.y + box.height / 2);
      const after = await selection(editorWave());
      check(after.end > before.end + duration * 0.02, `end moved from ${before.end} to ${after.end}`);
      check(near(after.start, before.start, 0.01), "the start moved too");
      return `end ${before.end.toFixed(3)} -> ${after.end.toFixed(3)} s`;
    });

    await step("the selection plays on its own", async () => {
      await editorWave().getByRole("button", { name: "Play selection" }).click();
      await waitPlaying(editorWave());
      await page.keyboard.press("Escape");
      await waitPlaying(editorWave(), false, 5000);
    });

    let firstCut = null;
    await step("Cut selection removes the interior section", async () => {
      firstCut = await selection(editorWave());
      await editor().getByRole("button", { name: "Cut selection" }).click();
      check((await cutCount()) === 1, "no cut listed");
      check((await selection(editorWave())) === null, "the selection was not cleared");
      const expected = duration - (firstCut.end - firstCut.start);
      check(near(await afterEdits(), expected, 0.01), `after edits ${await afterEdits()} s, expected ${expected.toFixed(3)} s`);
      check((await editorWave().locator('[part~="studio-cut-0"]').count()) === 1, "the cut is not drawn");
      return `cut ${firstCut.start.toFixed(3)}–${firstCut.end.toFixed(3)} s`;
    });

    await step("a second cut, made with the X key", async () => {
      const box = await waveBox(editorWave());
      await dragBetween(xAt(box, 0.65), xAt(box, 0.75), box.y + box.height / 2);
      check(await selection(editorWave()), "no selection");
      await page.keyboard.press("x");
      check((await cutCount()) === 2, `expected 2 cuts, have ${await cutCount()}`);
      return "2 cuts";
    });

    await step("dragging the start handle trims the beginning", async () => {
      const box = await waveBox(editorWave());
      await dragBetween(box.x + 3, xAt(box, 0.1), box.y + box.height / 2);
      const trim = await fieldNumber("Trim start (s)");
      check(near(trim, duration * 0.1, duration * 0.03), `trim start ${trim} s, expected about ${(duration * 0.1).toFixed(3)}`);
      check((await cutCount()) === 2, "the cuts were lost by the trim");
      check((await editorWave().locator('[part~="studio-trim-start"]').count()) === 1, "the trimmed part is not shaded");
      return `trim start ${trim} s`;
    });

    await step("Ctrl+Z undoes the trim; Reset clears everything and can be undone", async () => {
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).click(); // keys go to the page, not a field
      await page.keyboard.press("Control+z");
      check((await fieldNumber("Trim start (s)")) === 0, "the trim was not undone");
      check((await cutCount()) === 2, "undo removed the cuts");
      await editor().getByRole("button", { name: "Reset edits" }).click();
      check((await cutCount()) === 0, "reset kept cuts");
      check(near(await afterEdits(), duration, 0.002), "reset did not restore the full length");
      await editor().getByRole("button", { name: "Undo" }).click();
      check((await cutCount()) === 2, "undoing the reset did not bring the cuts back");
      return "trim undone; reset undone";
    });

    await step("Trim to selection keeps only the selection", async () => {
      const box = await waveBox(editorWave());
      await dragBetween(xAt(box, 0.05), xAt(box, 0.95), box.y + box.height / 2);
      await page.keyboard.press("t");
      const start = await fieldNumber("Trim start (s)");
      const end = await fieldNumber("Trim end (s)");
      check(near(start, duration * 0.05, duration * 0.02) && near(end, duration * 0.05, duration * 0.02), `trims ${start} / ${end}`);
      check((await cutCount()) === 2, "the cuts inside the selection were dropped");
      return `trims ${start} s / ${end} s, cuts kept`;
    });

    await step("fade in and fade out are set, limited to the server's 500 ms, and drawn", async () => {
      await editor().getByLabel("Fade in (ms)").fill("120");
      await editor().getByLabel("Fade in (ms)").press("Tab");
      await editor().getByLabel("Fade out (ms)").fill("900");
      await editor().getByLabel("Fade out (ms)").press("Tab");
      check((await fieldNumber("Fade in (ms)")) === 120, "fade in not kept");
      check((await fieldNumber("Fade out (ms)")) === 500, `fade out ${await fieldNumber("Fade out (ms)")}, expected 500`);
      check((await editorWave().locator('[part~="studio-fade-in"]').count()) === 1, "fade in not drawn");
      check((await editorWave().locator('[part~="studio-fade-out"]').count()) === 1, "fade out not drawn");
      return "120 ms in, 900 -> 500 ms out";
    });

    await step("zoom in, zoom out and fit the waveform", async () => {
      const host = editorWave().getByTestId("wave-host");
      await editorWave().getByRole("button", { name: "Zoom in" }).click();
      await editorWave().getByRole("button", { name: "Zoom in" }).click();
      check((await host.getAttribute("data-zoom")) === "4", `zoom ${await host.getAttribute("data-zoom")}`);
      const scrolls = await host.evaluate((el) => {
        const scroller = el.querySelector("div")?.shadowRoot?.querySelector(".scroll");
        return scroller ? scroller.scrollWidth > scroller.clientWidth : null;
      });
      await editorWave().getByRole("button", { name: "Zoom out" }).click();
      check((await host.getAttribute("data-zoom")) === "2", "zoom out did not step back");
      await editorWave().getByRole("button", { name: "Fit the whole recording" }).click();
      check((await host.getAttribute("data-zoom")) === "1", "fit did not reset the zoom");
      check(scrolls === true, "the zoomed waveform does not scroll horizontally");
      return "4x zoom scrolls horizontally; zoom out to 2x; fit to 1x";
    });

    let edited = 0;
    await step("the recipe is rendered automatically; B plays the edited recording", async () => {
      await page.waitForFunction(
        () => document.querySelector('[data-testid="preview-status"]')?.getAttribute("data-state") === "ready",
        null,
        { timeout: 90000 },
      );
      await compare().getByText("Campaign Evolved LATAM (edited)").waitFor({ timeout: 15000 });
      await page.waitForFunction(
        (el) => el.dataset.duration && Number(el.dataset.duration) > 0 && Number(el.dataset.duration) < Number(el.dataset.full),
        await (async () => {
          const h = await waveB().getByTestId("wave-host").elementHandle();
          await h.evaluate((el, full) => (el.dataset.full = String(full)), duration);
          return h;
        })(),
        { timeout: 30000 },
      );
      edited = await waveDuration(waveB());
      const expected = await afterEdits();
      // Each cut joins with a 20 ms crossfade, so the render is a little shorter than the plain arithmetic.
      check(near(edited, expected, 0.1), `edited preview ${edited} s, recipe says ${expected} s`);
      const gain = await compare().getByTestId("gain-report").innerText();
      check(/Global gain \+4\.0 dB/.test(gain) || /reduced/.test(gain), `gain report: ${gain}`);
      return `edited ${edited.toFixed(3)} s (recipe ${expected} s); ${gain.split("·")[0].trim()}`;
    });

    await step("the encoded preview can be heard as B", async () => {
      await compare().getByLabel("Which replacement B plays").selectOption("encoded");
      await waveB().getByText("encoded for the game").waitFor();
      const encoded = await waveDuration(waveB());
      await compare().getByLabel("Which replacement B plays").selectOption("edited");
      await page.waitForFunction((el) => Number(el.dataset.duration) > 0, await waveB().getByTestId("wave-host").elementHandle());
      return `encoded ${encoded.toFixed(3)} s`;
    });

    await step("A/B switches between the original and the edited replacement (A key)", async () => {
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).click();
      await page.keyboard.press("a");
      await waitPlaying(waveA());
      await page.waitForTimeout(400);
      await page.keyboard.press("a");
      await waitPlaying(waveB());
      check(!(await isPlaying(waveA())), "A kept playing");
      const at = await playhead(waveB());
      check(at > 0.2, `B did not start near A's position (${at} s)`);
      await page.keyboard.press("Escape");
      await waitPlaying(waveB(), false, 5000);
      return `B took over at ${at.toFixed(3)} s`;
    });

    await step("A then B plays the original and then the replacement (B key)", async () => {
      await page.keyboard.press("b");
      await waitPlaying(waveA());
      await waitPlaying(waveB(), true, 20000);
      check(!(await isPlaying(waveA())), "A still playing when B started");
      await page.keyboard.press("Escape");
      return "A finished, B started";
    });

    await step("a recipe change renders again; the outdated preview is not offered meanwhile", async () => {
      await editor().getByLabel("Fade in (ms)").fill("150");
      await editor().getByLabel("Fade in (ms)").press("Tab");
      check((await compare().getByTestId("preview-status").getAttribute("data-state")) === "rendering", "not rendering");
      check(await waveB().getByRole("button", { name: "Play", exact: true }).isDisabled(), "B playable while rendering");
      await page.waitForFunction(
        () => document.querySelector('[data-testid="preview-status"]')?.getAttribute("data-state") === "ready",
        null,
        { timeout: 90000 },
      );
      return "rendering, then ready";
    });

    await step("the W key plays the replacement on the editor waveform", async () => {
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).click();
      await page.keyboard.press("w");
      await waitPlaying(editorWave());
      await page.keyboard.press("Escape");
      await waitPlaying(editorWave(), false, 5000);
    });

    await step("typing in a field does not trigger the editing keys", async () => {
      const cuts = await cutCount();
      await page.getByLabel("Notes", { exact: true }).click();
      await page.keyboard.type("xtwpab");
      check((await page.getByLabel("Notes", { exact: true }).inputValue()).endsWith("xtwpab"), "typed text lost");
      check((await cutCount()) === cuts, "typing changed the cuts");
      check(!(await isPlaying(editorWave())) && !(await isPlaying(waveA())), "typing started playback");
      await page.keyboard.press("Control+z"); // the field's own undo, not the editor's
      check((await cutCount()) === cuts, "Ctrl+Z in a field undid an edit");
      return "keys stayed in the Notes field";
    });

    let saved = null;
    await step("Ctrl+S saves the recipe; it is still there after a reload", async () => {
      await page.keyboard.press("Control+s");
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      saved = { cuts: await cutCount(), trim: await fieldNumber("Trim start (s)"), fadeIn: await fieldNumber("Fade in (ms)"), fadeOut: await fieldNumber("Fade out (ms)") };
      await page.reload();
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).waitFor({ timeout: 30000 });
      await waveDuration(editorWave());
      const now = { cuts: await cutCount(), trim: await fieldNumber("Trim start (s)"), fadeIn: await fieldNumber("Fade in (ms)"), fadeOut: await fieldNumber("Fade out (ms)") };
      check(JSON.stringify(now) === JSON.stringify(saved), `after reload ${JSON.stringify(now)}, saved ${JSON.stringify(saved)}`);
      check((await editorWave().locator('[part~="studio-cut-1"]').count()) === 1, "the cuts are not drawn after reload");
      return JSON.stringify(now);
    });

    await step("approve the edited audio", async () => {
      await page.getByRole("button", { name: "Approve audio" }).click();
      await page.getByText("approved audio").waitFor({ timeout: 15000 });
    });

    await step("the M6 planner plans the approved recipe as a replacement, following the render rules", async () => {
      const { code, out } = await runPython(["scripts/ui/e2e_check_m6.py", "--root", root, "--slot", SLOT]);
      const result = JSON.parse(out.trim().split("\n").pop());
      check(code === 0 && result.ok, `planner: ${JSON.stringify(result.checks)} ${result.reason}`);
      check(result.edit.cuts.length === saved.cuts && result.edit.fade_in_ms === saved.fadeIn, `planner edit ${JSON.stringify(result.edit)}`);
      check(!("speed" in result.edit) && !("gain_db" in result.edit), "a removed field came back");
      return `action ${result.action}; ${result.edit.cuts.length} cuts, fade ${result.edit.fade_in_ms}/${result.edit.fade_out_ms} ms`;
    });

    await step("approved audio: the editor is read-only and the server refuses edits", async () => {
      await editor().getByText("Approved: read-only").waitFor();
      for (const name of ["Cut selection", "Trim to selection", "Undo", "Reset edits"]) {
        check(await editor().getByRole("button", { name }).isDisabled(), `${name} is enabled`);
      }
      check(await editor().getByLabel("Fade in (ms)").isDisabled(), "fade field editable");
      check((await editorWave().locator('[part~="studio-keep"]').count()) === 0, "trim handles still shown");
      const box = await waveBox(editorWave());
      await dragBetween(xAt(box, 0.3), xAt(box, 0.5), box.y + box.height / 2);
      check((await selection(editorWave())) === null, "a drag made a selection on approved audio");
      const cuts = await cutCount();
      await page.getByRole("heading", { level: 2, name: "a10_010_cryotech" }).click();
      await page.keyboard.press("Control+z");
      check((await cutCount()) === cuts, "Ctrl+Z changed approved audio");
      check((await page.locator(".center .status-row").getByText("unsaved changes", { exact: true }).count()) === 0, "the approved line became dirty");
      const status = await page.evaluate(async (slot) => {
        const current = await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json();
        const edit = { ...current.mapping.audio.edit, cuts: [] };
        delete edit.for_source;
        const res = await fetch("/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot_id: slot, loaded_sha256: current.sha256.mappings, local_sha256: current.sha256.local,
            audio: { source: "ce", sources: current.mapping.audio.sources.map(({ ce_line_ref, language }) => ({ ce_line_ref, language })), edit },
          }),
        });
        return res.status;
      }, SLOT);
      check(status === 409, `the API answered ${status}`);
      return "controls disabled, no handles, drag ignored, API 409";
    });

    await page.screenshot({ path: join(OUT, "editor.png"), fullPage: false });
    // The centre column scrolls; a tall window shows the whole decision panel at once.
    await page.setViewportSize({ width: 1600, height: 2400 });
    await page.locator(".column.center").screenshot({ path: join(OUT, "editor-panel.png") });
  } catch (e) {
    record("editor test stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }

  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === realBefore, "real manual_mappings.json changed");
    return `sha256 ${after.slice(0, 16)}…`;
  });

  const unexpected = pageErrors.filter((e) => !/409/.test(e));
  record("no unexpected browser errors", unexpected.length === 0, unexpected.slice(0, 3).join(" | "));
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "editor-report.json"), JSON.stringify({ results, root, pageErrors }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed. Report: e2e/out/editor-report.json` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
