// Browser test of the matching workflow changes of prompt 40, and only those:
//
//   npm run test:workflow      (from frontend/; needs Microsoft Edge)
//
//  1. the selected MCC key is shown at the top of the centre panel and follows the selection;
//  2. the key can be copied;
//  3. the edited recording is rendered automatically when a replacement is chosen;
//  4. editing renders it again, never offering an outdated preview, and nothing plays by itself;
//  5. the centre panel sections are in the requested order;
//  6. audio, subtitle, flags and notes are chosen and saved in one request, and a subtitle-only decision works;
//  7. the chosen recording's LATAM subtitle is proposed, without overriding a decided subtitle;
//  8. approved decisions stay protected;
//  9. the flag icons are distinct and labelled;
// 10. Insert silence (addendum): insert, mark, lengthen the result, preview, edit, undo, save, reload;
// 11. quick changes: list names and players, English takes and MCC subtitles on top, custom text start,
//     approvals (including both) in the save bar, es-MX seconds in the candidates.
//
// Works on a disposable copy of the mapping data (scripts/ui/e2e_fixture.py); the real mappings are hashed
// before and after.

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, API_PORT, Services, runFixture, sha256File, handleConfirms } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_010_cryotech#0"; // reset to undecided in the fixture
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
    if (page) await page.screenshot({ path: join(OUT, "workflow-failed.png") }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

const api = async (path) => (await fetch(`http://127.0.0.1:${API_PORT}${path}`)).json();
const center = () => page.locator("section.column.center");
const compare = () => page.getByRole("region", { name: "Compare the original and the replacement" });
const subtitles = () => page.getByRole("region", { name: "Subtitles" });
const replacement = () => page.getByRole("region", { name: "Replacement audio" });
const previewState = () => compare().getByTestId("preview-status").getAttribute("data-state");
const waveB = () => compare().locator(".wave-view").nth(1);

async function waitPreviewState(state, timeout = 90000) {
  await page.waitForFunction(
    (want) => document.querySelector('[data-testid="preview-status"]')?.getAttribute("data-state") === want,
    state,
    { timeout },
  );
}
async function waitBLoaded() {
  await page.waitForFunction(
    () => Number(document.querySelectorAll('[aria-label="Compare the original and the replacement"] [data-testid="wave-host"]')[1]?.dataset.duration) > 0,
    null,
    { timeout: 30000 },
  );
}
/** Waits until the selected line is the one shown and its decision has loaded. */
async function waitLine(id) {
  await page.waitForFunction(
    (want) =>
      document.querySelector('[data-testid="mcc-key"]')?.textContent === want &&
      document.querySelector("section.column.center")?.getAttribute("aria-busy") !== "true",
    id,
    { timeout: 15000 },
  );
}
async function nothingPlays() {
  return page.evaluate(() => [...document.querySelectorAll(".wave-view")].every((w) => w.dataset.playing !== "true"));
}
/** Sets a number field of the editor the way a person does: type, then leave the field. */
async function setField(label, value) {
  const field = page.getByRole("region", { name: "Audio editing" }).getByLabel(label);
  await field.fill(String(value));
  await field.press("Tab");
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-workflow-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(root);
  const previewBodies = [];
  const saveBodies = [];
  let browser;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return `root ${root}`;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: `http://localhost:${WEB_PORT}` });
    page = await context.newPage();
    handleConfirms(page);
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => msg.type() === "error" && pageErrors.push(msg.text()));
    page.on("request", (r) => {
      if (r.url().includes("/api/edit/preview")) previewBodies.push(JSON.parse(r.postData() ?? "{}"));
      if (r.url().includes("/api/save")) saveBodies.push(JSON.parse(r.postData() ?? "{}"));
    });

    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent(SLOT)}&cq=${encodeURIComponent("00460_cryotech")}`);
    await center().getByTestId("mcc-key").waitFor({ timeout: 30000 });

    // ---- 1. The MCC key at the top, following the selection.
    await step("1. the selected MCC key is shown at the top of the centre panel and follows the selection", async () => {
      check((await center().getByTestId("mcc-key").innerText()) === SLOT, "the key is not the selected line's");
      const other = page.locator("li.row-item").nth(3);
      const otherId = (await other.getAttribute("id")).replace(/^mcc-/, "");
      await other.click();
      await page.waitForFunction((id) => document.querySelector('[data-testid="mcc-key"]')?.textContent === id, otherId, { timeout: 5000 });
      await page.locator(`li.row-item[id="mcc-${SLOT}"]`).click();
      await page.waitForFunction((id) => document.querySelector('[data-testid="mcc-key"]')?.textContent === id, SLOT, { timeout: 5000 });
      await waitLine(SLOT);
      check((await center().getByTestId("ce-replacement").innerText()).includes("None: Spain's audio stays"), "no-replacement state not shown");
      return `${SLOT} -> ${otherId} -> ${SLOT}; shown without a replacement`;
    });

    // ---- 2. Copy.
    await step("2. the MCC key can be copied", async () => {
      await center().getByRole("button", { name: "Copy the MCC key" }).click();
      const copied = await page.evaluate(() => navigator.clipboard.readText());
      check(copied === SLOT, `clipboard holds ${JSON.stringify(copied)}`);
      return "clipboard = key";
    });

    await step("12. the shortcuts legend is replaced by a button that opens the list", async () => {
      check((await page.locator("ul.keys").count()) === 0, "the old legend is still shown");
      const dialog = page.getByTestId("shortcuts-dialog");
      check(!(await dialog.isVisible()), "the list is open before clicking");
      await page.getByTestId("shortcuts-button").click();
      await dialog.waitFor({ state: "visible", timeout: 5000 });
      const text = await dialog.innerText();
      check(/Save the draft/.test(text) && /Next \/ previous MCC line/.test(text), "the list is incomplete");
      const before = await center().getByTestId("mcc-key").innerText();
      await page.keyboard.press("j"); // shortcuts are paused while the list is open
      check((await center().getByTestId("mcc-key").innerText()) === before, "a shortcut fired behind the list");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "hidden", timeout: 5000 });
      await page.getByTestId("shortcuts-button").click();
      await dialog.getByRole("button", { name: "Close" }).click();
      await dialog.waitFor({ state: "hidden", timeout: 5000 });
      return "button opens it; Esc and Close close it; shortcuts paused meanwhile";
    });

    // ---- 5. Section order.
    await step("5. the centre panel follows the requested section order", async () => {
      const labels = await center().evaluate((el) =>
        [...el.querySelectorAll(":scope > section[aria-label]")].map((s) => s.getAttribute("aria-label")),
      );
      const expected = [
        "Replacement audio",
        "Flags and notes",
        "Audio editing",
        "Compare the original and the replacement",
        "Subtitles",
        "Save the decision",
      ];
      check(JSON.stringify(labels) === JSON.stringify(expected), `order ${labels.join(" | ")}`);
      const first = await center().locator(":scope > section").first().getByTestId("mcc-key").count();
      check(first === 1, "the MCC key is not in the first section");
      return labels.slice(0, 5).join(" → ");
    });

    // ---- 9. Flag icons.
    await step("11a. MCC list rows: classic name, Spain and English players, English subtitle", async () => {
      const slots = await api("/api/slots?level=a10&limit=400");
      const multi = slots.slots.find((r) => r.permutations > 1);
      const plain = slots.slots.find((r) => r.slot_id === SLOT);
      const row = page.locator(`li.row-item[id="mcc-${SLOT}"]`);
      check((await row.locator("strong.tag").innerText()) === (plain.permutations > 1 ? `${plain.tag_name} #${plain.ordinal}` : plain.tag_name), "row name");
      check((await row.getByRole("button", { name: /ES/ }).count()) === 1 && (await row.getByRole("button", { name: /EN/ }).count()) === 1, "ES/EN players");
      check((await row.locator(".preview").innerText()) === plain.english_preview, "preview is not the English subtitle");
      let multiName = "none in a10";
      if (multi) {
        const other = page.locator(`li.row-item[id="mcc-${multi.slot_id}"] strong.tag`);
        if (await other.count()) {
          multiName = await other.innerText();
          check(multiName === `${multi.tag_name} #${multi.ordinal}`, `takes name ${multiName}`);
        }
      }
      const playing = page.waitForResponse((r) => r.url().includes("/audio/mcc") && r.url().includes("lang=english"), { timeout: 15000 });
      await row.getByRole("button", { name: /EN/ }).click();
      check((await playing).status() < 400, "English audio did not load");
      await page.keyboard.press("Escape");
      return `"${plain.english_preview.slice(0, 30)}…"; takes: ${multiName}`;
    });

    await step("11b. the centre panel starts with the English takes and MCC's subtitles", async () => {
      const detail = await api(`/api/slot?id=${encodeURIComponent(SLOT)}`);
      const takes = replacement().getByTestId("english-takes");
      const names = await takes.locator("li .mono").allInnerTexts();
      const expected = detail.english.map((e) => `${e.name_in_bank} #${e.ordinal_in_tag}`);
      check(JSON.stringify(names) === JSON.stringify(expected), `takes ${names.join(", ")}`);
      check((await takes.getByRole("button").count()) === expected.length, "a take has no play button");
      const texts = await replacement().getByTestId("mcc-subtitles").innerText();
      for (const key of ["SU", "SP", "EN"]) {
        const text = detail.mcc_subtitles[key]?.text;
        if (text) check(texts.includes(text), `${key} text missing at the top`);
      }
      return `${expected.join(", ")}; SU/SP/EN shown`;
    });

    await step("9. the flag icons are distinct and labelled (flags, list filters)", async () => {
      const expected = { radio: ["lucide-radio-tower", "Needs radio effect"], recording: ["lucide-mic", "Needs recording"], fits: ["lucide-puzzle", "Different but fits"] };
      for (const [name, [icon, label]] of Object.entries(expected)) {
        const box = page.getByTestId(`flag-${name}`);
        check((await box.innerText()).trim() === label, `${name}: label ${await box.innerText()}`);
        check((await box.locator(`svg.${icon}`).count()) === 1, `${name}: no ${icon} in the checkbox`);
        const filter = page.getByTestId(`flag-filter-${name}`);
        check((await filter.locator(`svg.${icon}`).count()) === 1, `${name}: no ${icon} in the list filter`);
        check((await filter.textContent()).includes(label), `${name}: filter label missing`);
      }
      const shapes = await page.evaluate(() =>
        ["radio", "recording", "fits"].map((n) => document.querySelector(`[data-testid="flag-${n}"] svg`).innerHTML),
      );
      check(new Set(shapes).size === 3, "two flags draw the same icon");
      return "radio-tower, mic, puzzle";
    });

    // ---- 3 + 7. Choosing a replacement: automatic preview, proposed subtitle.
    const ceLine = await api(`/api/ce_line?ref=${encodeURIComponent(CE_REF)}`);
    const latam = ceLine.subtitles["es-MX"].text;
    await step("3. choosing a replacement renders the edited recording automatically, as the default B", async () => {
      const before = previewBodies.length;
      await page.locator("li.row-item", { hasText: CE_REF }).getByRole("button", { name: /Use this recording/ }).click();
      await waitPreviewState("ready");
      await waitBLoaded();
      check(previewBodies.length > before, "no preview was requested");
      check((await waveB().innerText()).includes("Campaign Evolved LATAM (edited)"), "B is not the edited recording");
      check((await compare().getByLabel("Which replacement B plays").inputValue()) === "edited", "B does not default to edited");
      check(await nothingPlays(), "something started playing");
      const ceKey = await center().getByTestId("ce-replacement").textContent();
      check(ceKey.includes(CE_REF), `the CE key is not shown: ${ceKey}`);
      return `${previewBodies.length - before} render(s), no click on any preview button`;
    });

    await step("11c. candidates show the es-MX length and one header line", async () => {
      const row = page.locator("section.column.ce li.row-item", { hasText: CE_REF });
      await page.waitForFunction(
        (ref) => /\d+\.\d\d s/.test([...document.querySelectorAll("section.column.ce li.row-item")].find((li) => li.textContent.includes(ref))?.querySelector('[data-testid="clip-seconds"]')?.textContent ?? ""),
        CE_REF,
        { timeout: 20000 },
      );
      const shown = Number((await row.getByTestId("clip-seconds").innerText()).replace(" s", ""));
      check(Math.abs(shown - 3.63) < 0.05, `es-MX ${shown} s`);
      check((await row.locator(".line-head").count()) === 1, "more than one header line");
      return `${shown.toFixed(2)} s`;
    });

    await step("7. the chosen recording's LATAM subtitle is proposed, unsaved", async () => {
      const preview = subtitles().getByTestId("subtitle-preview");
      await preview.getByText("proposed from the chosen recording · unsaved").waitFor({ timeout: 10000 }).catch(async (e) => {
        throw new Error(`${e.message.split("\n")[0]} | preview:${(await preview.textContent()).replace(/\s+/g, " ")}`);
      });
      check((await preview.getByTestId("subtitle-preview-text").innerText()) === latam, "the preview is not the CE LATAM text");
      check(await subtitles().getByLabel("Use a Campaign Evolved subtitle").isChecked(), "CE subtitle not selected");
      const stored = (await api(`/api/slot?id=${encodeURIComponent(SLOT)}`)).mapping;
      check(!stored || stored.match.ce_line_refs.length === 0, "something was saved already");
      check(saveBodies.length === 0, "a save was sent");
      return `"${latam.slice(0, 40)}…"`;
    });

    // ---- 4. Edits refresh the preview; no stale playback.
    await step("4. an edit renders again; B offers no outdated preview while rendering", async () => {
      await setField("Fade in (ms)", 200);
      check((await previewState()) === "rendering", `state ${await previewState()} right after the edit`);
      const bState = await waveB().evaluate((el) => ({ duration: el.querySelector('[data-testid="wave-host"]').dataset.duration, text: el.innerText.slice(0, 200) }));
      check(await waveB().getByRole("button", { name: "Play", exact: true }).isDisabled(), `B can play during rendering ${JSON.stringify(bState)} ${JSON.stringify(previewBodies.slice(-3).map((b) => b.edit))}`);
      await waitPreviewState("ready");
      await waitBLoaded();
      check(previewBodies.at(-1).edit.fade_in_ms === 200, "the last render is not the current recipe");
      return "rendering → ready with fade in 200 ms";
    });

    await step("4b. quick successive edits are debounced; only the latest recipe is offered", async () => {
      const before = previewBodies.length;
      await setField("Fade in (ms)", 100);
      await setField("Fade in (ms)", 300);
      await setField("Fade out (ms)", 150);
      await waitPreviewState("ready");
      const sent = previewBodies.slice(before);
      const last = sent.at(-1).edit;
      check(last.fade_in_ms === 300 && last.fade_out_ms === 150, `last render ${JSON.stringify(last)}`);
      check(sent.length <= 2, `${sent.length} renders for 3 quick edits`);
      check(await nothingPlays(), "something started playing");
      return `${sent.length} render(s) for 3 edits`;
    });

    await step("4c. the unedited recording can still be compared", async () => {
      await compare().getByLabel("Which replacement B plays").selectOption("unedited");
      await waveB().getByText("Campaign Evolved LATAM (unedited)").waitFor();
      await waitBLoaded();
      await compare().getByLabel("Which replacement B plays").selectOption("edited");
      return "B switched to unedited and back";
    });

    // ---- 10. Insert silence (addendum to prompt 40).
    const editorRegion = () => page.getByRole("region", { name: "Audio editing" });
    const editorWave = () => editorRegion().locator(".wave-view");
    const afterEdits = async () => Number((await editorRegion().getByTestId("after-edits").innerText()).replace(" s", ""));
    const bSeconds = async () => Number(await waveB().getByTestId("wave-host").getAttribute("data-duration"));
    async function clickWaveAt(fraction) {
      await editorWave().scrollIntoViewIfNeeded();
      const box = await editorWave().getByTestId("wave-host").boundingBox();
      await page.mouse.click(box.x + box.width * fraction, box.y + (box.height - 16) / 2);
    }

    await step("10. Insert silence at the playhead: listed, marked on the waveform, added to the duration", async () => {
      const beforeEdits = await afterEdits();
      await waitPreviewState("ready");
      await waitBLoaded();
      const beforeB = await bSeconds();
      await clickWaveAt(0.5);
      await editorRegion().getByLabel("Silence length (ms)").fill("400");
      await editorRegion().getByTestId("insert-silence").click();
      check((await editorRegion().getByTestId("silence").count()) === 1, "no silence listed");
      const marker = editorWave().locator(".silence-marker");
      await marker.first().waitFor({ timeout: 5000 });
      check((await marker.first().textContent()) === "+400 ms", `marker says ${await marker.first().textContent()}`);
      const grown = (await afterEdits()) - beforeEdits;
      check(Math.abs(grown - 0.4) < 0.002, `after edits grew by ${grown}`);
      // The preview renders by itself and B plays the recording with the silence.
      check((await previewState()) === "rendering", "the preview did not start rendering");
      await waitPreviewState("ready");
      await waitBLoaded();
      const body = previewBodies.at(-1).edit;
      check(body.silences.length === 1 && body.silences[0].dur_s === 0.4, `rendered ${JSON.stringify(body.silences)}`);
      const longer = (await bSeconds()) - beforeB;
      check(Math.abs(longer - 0.4) < 0.03, `B is ${longer.toFixed(3)} s longer`);
      return `at ${body.silences[0].at_s} s; B +${longer.toFixed(3)} s`;
    });

    await step("10b. an inserted silence can be edited, and a second one undone", async () => {
      await waitBLoaded();
      const beforeB = await bSeconds();
      const length = editorRegion().getByLabel("Length of silence 1 (ms)");
      await length.fill("600");
      await length.press("Tab");
      await waitPreviewState("ready");
      await waitBLoaded();
      check(previewBodies.at(-1).edit.silences[0].dur_s === 0.6, "the new length was not rendered");
      const longer = (await bSeconds()) - beforeB;
      check(Math.abs(longer - 0.2) < 0.03, `B grew by ${longer.toFixed(3)} s, not 0.2 s`);
      await clickWaveAt(0.2);
      await editorRegion().getByTestId("insert-silence").click();
      check((await editorRegion().getByTestId("silence").count()) === 2, "second silence not listed");
      check((await editorWave().locator(".silence-marker").count()) === 2, "second marker missing");
      await editorRegion().getByRole("button", { name: "Undo" }).click();
      check((await editorRegion().getByTestId("silence").count()) === 1, "undo did not remove the second silence");
      await waitPreviewState("ready");
      return "600 ms rendered; second silence undone";
    });

    // ---- 6. Everything saved together.
    await step("6. audio, edits, subtitle, flags and notes are saved by one Save draft", async () => {
      await page.getByTestId("flag-recording").locator("input").check();
      await page.getByRole("region", { name: "Flags and notes" }).getByLabel("Notes").fill("prompt 40 test");
      const before = saveBodies.length;
      await page.getByTestId("save-draft").click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      check(saveBodies.length === before + 1, `${saveBodies.length - before} save requests`);
      const body = saveBodies.at(-1);
      check(body.audio?.source === "ce" && body.subtitle?.source === "ce_locres" && body.needs_recording?.marked === true, "the request is missing a part");
      check(!body.actions, "the save carried an approval");
      const m = (await api(`/api/slot?id=${encodeURIComponent(SLOT)}`)).mapping;
      check(m.audio.source === "ce" && m.audio.sources[0].ce_line_ref === CE_REF, "audio not saved");
      check(m.audio.edit.fade_in_ms === 300, "recipe not saved");
      check(m.audio.edit.silences.length === 1 && m.audio.edit.silences[0].dur_s === 0.6, `silences saved: ${JSON.stringify(m.audio.edit.silences)}`);
      check(m.subtitle.source === "ce_locres" && m.subtitle.ce_locres.ce_line_ref === CE_REF, "subtitle not saved");
      check(m.needs_recording?.marked === true && m.notes === "prompt 40 test", "flag or notes not saved");
      check(m.audio.status === "draft" && m.subtitle.status === "draft", "something was approved");
      return "one request; audio + recipe + subtitle + flag + notes; nothing approved";
    });

    await step("10c. after a reload the saved silence is listed and marked again", async () => {
      await page.reload();
      await waitLine(SLOT);
      const row = editorRegion().getByTestId("silence");
      await row.first().waitFor({ timeout: 15000 });
      check((await row.count()) === 1, `${await row.count()} silences after reload`);
      check((await editorRegion().getByLabel("Length of silence 1 (ms)").inputValue()) === "600", "length lost");
      await editorWave().locator(".silence-marker").first().waitFor({ timeout: 15000 });
      return "1 silence, 600 ms, marked";
    });

    await step("9b. the MCC list shows the saved flag with its icon and label", async () => {
      const pill = page.locator(`li.row-item[id="mcc-${SLOT}"] [data-flag="recording"]`);
      await pill.waitFor({ timeout: 5000 });
      check((await pill.getAttribute("aria-label")) === "Needs recording", "pill not labelled");
      check((await pill.locator("svg.lucide-mic").count()) === 1, "pill without the mic icon");
      return "mic pill, labelled";
    });

    // ---- 7b. A decided subtitle is never replaced by a proposal.
    let otherRef = "";
    await step("7b. choosing another recording keeps a subtitle the user decided", async () => {
      await subtitles().getByLabel("Write my own LATAM Spanish text").check();
      const start = await subtitles().getByLabel("Subtitle text (LATAM Spanish)").inputValue();
      check(start === latam, `custom text starts as ${JSON.stringify(start)}`);
      await subtitles().getByLabel("Subtitle text (LATAM Spanish)").fill("Texto propio de prueba");
      await page.getByTestId("save-draft").click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      const search = page.locator("section.column.ce").getByRole("searchbox");
      await search.fill("cryotech");
      const candidate = page.locator("section.column.ce li.row-item").filter({ hasNotText: CE_REF }).first();
      await candidate.waitFor({ timeout: 10000 });
      otherRef = (await candidate.locator("strong.tag").innerText()).trim();
      await candidate.getByRole("button", { name: /Use this recording/ }).click();
      await page.waitForFunction((ref) => document.querySelector('[data-testid="ce-key"]')?.textContent !== ref, CE_REF, { timeout: 5000 });
      await page.waitForTimeout(500); // the line's subtitle is read before any proposal
      check(await subtitles().getByLabel("Write my own LATAM Spanish text").isChecked(), "the custom subtitle was replaced");
      check((await subtitles().getByTestId("subtitle-preview-text").innerText()) === "Texto propio de prueba", "the preview changed");
      check((await subtitles().getByText("proposed from the chosen recording · unsaved").count()) === 0, "a proposal is shown");
      // Back to the saved recording for the approval step.
      await page.locator("li").filter({ hasText: CE_REF }).locator('input[name="replacement"]').check();
      await page.waitForFunction((ref) => document.querySelector('[data-testid="ce-key"]')?.textContent === ref, CE_REF, { timeout: 5000 });
      return `custom text kept after choosing ${otherRef || "another line"}`;
    });

    // ---- 8. Approved decisions stay protected.
    await step("8. approved audio and subtitle stay protected", async () => {
      if (await page.getByTestId("save-draft").isEnabled()) {
        await page.getByTestId("save-draft").click();
        await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      }
      await page.getByTestId("approval-audio").getByRole("button", { name: "Approve audio" }).click();
      await page.getByText("Saved; approved audio.").waitFor({ timeout: 15000 });
      await page.getByTestId("approval-subtitle").getByRole("button", { name: "Approve subtitle" }).click();
      await page.getByText("Saved; approved subtitle.").waitFor({ timeout: 15000 });
      // The UI refuses a new recording and keeps the subtitle.
      await page.locator("section.column.ce li.row-item").filter({ hasNotText: CE_REF }).first().getByRole("button", { name: /Use this recording/ }).click();
      await page.getByText("The audio decision is approved.").first().waitFor({ timeout: 5000 });
      check((await center().getByTestId("ce-key").innerText()) === CE_REF, "the approved recording changed");
      check(await replacement().getByTestId("keep-spain").isDisabled(), "audio choice editable");
      check(await subtitles().getByLabel("Write my own LATAM Spanish text").isDisabled(), "subtitle choice editable");
      // The API refuses a change too.
      const status = await page.evaluate(async (slot) => {
        const current = await (await fetch(`/api/slot?id=${encodeURIComponent(slot)}`)).json();
        const res = await fetch("/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slot_id: slot, loaded_sha256: current.sha256.mappings, local_sha256: current.sha256.local, subtitle: { source: "none" } }),
        });
        return res.status;
      }, SLOT);
      check(status === 409, `the API answered ${status}`);
      // Flags stay independent of approvals.
      await page.getByTestId("flag-recording").locator("input").uncheck();
      await page.getByTestId("save-draft").click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      const m = (await api(`/api/slot?id=${encodeURIComponent(SLOT)}`)).mapping;
      check(m.audio.status === "approved" && m.subtitle.status === "approved", "an approval was lost");
      check(m.needs_recording.marked === false, "flag did not change");
      return "UI locked, API 409, flags still editable, approvals kept";
    });

    // ---- 6b. A subtitle-only decision.
    await step("6b. a subtitle-only decision saves without an audio replacement", async () => {
      // Any undecided line will do (the owner's a10 may be fully decided by now).
      const list = await api("/api/slots?level=all&status=undecided&limit=5");
      const target = list.slots.find((s) => s.slot_id !== SLOT);
      check(target, "no undecided line in the fixture");
      await page.goto(`http://localhost:${WEB_PORT}/#/match?level=${target.level}&slot=${encodeURIComponent(target.slot_id)}`);
      await waitLine(target.slot_id);
      await subtitles().getByLabel("Write my own LATAM Spanish text").check();
      const su = (await api(`/api/slot?id=${encodeURIComponent(target.slot_id)}`)).mcc_subtitles.SU?.text ?? "";
      const start = await subtitles().getByLabel("Subtitle text (LATAM Spanish)").inputValue();
      check(start === su, `custom text starts as ${JSON.stringify(start)}, SU is ${JSON.stringify(su)}`);
      await subtitles().getByLabel("Subtitle text (LATAM Spanish)").fill("Solo subtítulo");
      await page.getByTestId("save-draft").click();
      await page.getByText("Draft saved.").waitFor({ timeout: 15000 });
      const m = (await api(`/api/slot?id=${encodeURIComponent(target.slot_id)}`)).mapping;
      check(m.audio.source === "keep_original" && m.subtitle.source === "custom", "not a subtitle-only decision");
      check(m.subtitle.status === "draft", "the subtitle was approved");
      // 11d. Approve both, from the save bar.
      const bar = page.getByRole("region", { name: "Save the decision" });
      check((await bar.getByRole("button", { name: "Approve audio" }).count()) === 1, "no Approve audio in the save bar");
      check((await bar.getByRole("button", { name: "Approve subtitle" }).count()) === 1, "no Approve subtitle in the save bar");
      await bar.getByTestId("approve-both").click();
      await page.getByText("Saved; approved audio, approved subtitle.").waitFor({ timeout: 15000 });
      const approved = (await api(`/api/slot?id=${encodeURIComponent(target.slot_id)}`)).mapping;
      check(approved.audio.status === "approved" && approved.subtitle.status === "approved", "approve both did not approve both");
      return `${target.slot_id}; custom text started from SU; approved both from the save bar`;
    });

    await page.setViewportSize({ width: 1600, height: 2600 });
    await page.goto(`http://localhost:${WEB_PORT}/#/match?level=a10&slot=${encodeURIComponent(SLOT)}`);
    await waitLine(SLOT);
    await page.waitForTimeout(1500);
    await center().screenshot({ path: join(OUT, "workflow-panel.png") });
  } catch (e) {
    record("workflow test stopped early", false, String(e.message ?? e).split("\n")[0]);
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
  await writeFile(join(OUT, "workflow-report.json"), JSON.stringify({ results, root, pageErrors }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed. Report: e2e/out/workflow-report.json` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
