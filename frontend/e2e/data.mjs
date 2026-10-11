// Browser test of the Data page: JSON <-> SQLite sync and its recovery actions.
//
//   npm run test:data        (from frontend/; needs Microsoft Edge)
//
// On a disposable copy of the mapping data (scripts/ui/e2e_fixture.py) it plays the two ways the export can
// drift: a git checkout that rewrites it with CRLF (same content: must keep working), and a real outside edit
// (must be refused, then imported after a preview, or overwritten by an export that keeps the edited file).
// The real mappings are hashed before and after.

import { mkdtemp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { HERE, WEB_PORT, Services, runFixture, runPython, sha256File } from "./harness.mjs";

const OUT = join(HERE, "out");
const SLOT = "es:A10_020_cryotech#0";
const results = [];
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
    if (page) await page.screenshot({ path: join(OUT, "data-failed.png") }).catch(() => {});
    throw e;
  }
}
const check = (ok, message) => {
  if (!ok) throw new Error(message);
};

/** Edits the notes of one slot the way an outside tool would: canonical JSON, database not told. */
const EDIT = `
import json, sys
p, slot, text = sys.argv[1], sys.argv[2], sys.argv[3]
doc = json.loads(open(p, encoding="utf-8").read())
next(s for s in doc["slots"] if s["slot_id"] == slot)["notes"] = text
open(p, "w", encoding="utf-8", newline="\\n").write(json.dumps(doc, indent=2, ensure_ascii=False) + "\\n")
`;

async function main() {
  await mkdir(OUT, { recursive: true });
  const tmp = await mkdtemp(join(tmpdir(), "studio-data-"));
  const fixture = await runFixture(join(tmp, "root"));
  const root = fixture.root;
  const json = join(root, "mappings", "manual_mappings.json");
  const realBefore = fixture.real_mappings_sha256;
  const services = new Services(root);
  let browser;
  const api = (path, init) => fetch(`http://localhost:${WEB_PORT}${path}`, init).then(async (r) => ({ status: r.status, body: await r.json() }));
  const notesOf = async () => (await api(`/api/slot?id=${encodeURIComponent(SLOT)}`)).body.mapping?.notes;

  try {
    await step("start the API and the Studio on disposable data", async () => {
      await services.up();
      return root;
    });
    browser = await chromium.launch({ channel: "msedge", headless: true });
    page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    page.on("dialog", (d) => d.accept());

    await step("the Data page reports the file in sync", async () => {
      await page.goto(`http://localhost:${WEB_PORT}/#/data`);
      await page.getByTestId("sync-status").getByText("in sync").waitFor({ timeout: 20000 });
      check(await page.getByRole("button", { name: /Preview import/ }).isDisabled(), "import offered while in sync");
    });

    await step("a CRLF rewrite (git checkout) is not an outside edit; matching keeps working", async () => {
      const lf = await readFile(json);
      await writeFile(json, Buffer.from(lf.toString("utf-8").replace(/\n/g, "\r\n"), "utf-8"));
      await page.getByRole("button", { name: "Check again" }).click();
      await page.getByTestId("sync-status").getByText("line endings only").waitFor();
      const state = await api("/api/state");
      check(state.status === 200, `state answered ${state.status}: ${state.body.error}`);
      const slot = await api(`/api/slot?id=${encodeURIComponent(SLOT)}`);
      check(slot.status === 200, `slot answered ${slot.status}`);
      return "status line_endings; /api/state and /api/slot answer 200";
    });

    await step("a save after the CRLF rewrite writes LF and is in sync again", async () => {
      const slot = (await api(`/api/slot?id=${encodeURIComponent(SLOT)}`)).body;
      const res = await api("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot_id: SLOT, loaded_sha256: slot.sha256.mappings, local_sha256: slot.sha256.local, notes: "nota tras CRLF" }),
      });
      check(res.status === 200, `save answered ${res.status}: ${res.body.error}`);
      check(!(await readFile(json)).includes(Buffer.from("\r\n")), "the file still has CRLF");
      check((await api("/api/data/status")).body.state === "in_sync", "not in sync after the save");
    });

    await step("a real outside edit is refused by the matching page, with the way out", async () => {
      const r = await runPython(["-c", EDIT, json, SLOT, "editado fuera del Studio"]);
      check(r.code === 0, r.out);
      const res = await api(`/api/slot?id=${encodeURIComponent(SLOT)}`);
      check(res.status === 409 && /changed outside the Studio/.test(res.body.error) && /Data/.test(res.body.error), `answer ${res.status}: ${res.body.error}`);
      await page.getByRole("button", { name: "Check again" }).click();
      await page.getByTestId("sync-status").getByText("changed outside the Studio").waitFor();
      return res.body.error.slice(0, 80) + "…";
    });

    await step("the import preview lists the changed slot and writes nothing", async () => {
      const before = await sha256File(json);
      await page.getByRole("button", { name: /Preview import/ }).click();
      const preview = page.getByTestId("import-preview");
      await preview.waitFor();
      await preview.getByText(SLOT).waitFor();
      check((await preview.getByText("1 slot(s) would change").count()) === 1, "the preview does not say 1 slot");
      check((await sha256File(json)) === before, "the preview wrote the file");
      check((await api("/api/data/status")).body.state === "external_edit", "the preview changed the state");
    });

    await step("import after confirmation: the database takes the file's decisions", async () => {
      await page.getByRole("button", { name: "Import these changes" }).click();
      await page.getByText(/Imported: 1 slot/).waitFor({ timeout: 15000 });
      await page.getByTestId("sync-status").getByText("in sync").waitFor();
      check((await notesOf()) === "editado fuera del Studio", "the imported note is not served");
      const backups = (await readdir(join(root, "mappings", ".history"))).filter((n) => n.endsWith(".before-import.db"));
      check(backups.length === 1, `database backups: ${backups.length}`);
      return `backup ${backups[0]}`;
    });

    await step("export: the database is written over another outside edit, which is kept", async () => {
      const r = await runPython(["-c", EDIT, json, SLOT, "edición que se descarta"]);
      check(r.code === 0, r.out);
      await page.getByRole("button", { name: "Check again" }).click();
      await page.getByTestId("sync-status").getByText("changed outside the Studio").waitFor();
      await page.getByRole("button", { name: /Export database to JSON/ }).click();
      await page.getByText("Exported").waitFor({ timeout: 15000 });
      check((await notesOf()) === "editado fuera del Studio", "the export did not restore the database's note");
      const kept = (await readdir(join(root, "mappings", ".history"))).filter((n) => n.endsWith(".replaced-by-export.json"));
      check(kept.length === 1, `kept files: ${kept.length}`);
      const keptText = await readFile(join(root, "mappings", ".history", kept[0]), "utf-8");
      check(keptText.includes("edición que se descarta"), "the replaced file was not kept as it was");
      return `kept ${kept[0]}`;
    });

    await step("the import and export endpoints refuse without confirmation or with stale hashes", async () => {
      const status = (await api("/api/data/status")).body;
      const noConfirm = await api("/api/data/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_sha256: status.file_sha256 }) });
      const stale = await api("/api/data/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_sha256: "0".repeat(64), confirm: true }) });
      const badImport = await api("/api/data/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_sha256: status.file_sha256, db_export_sha256: "0".repeat(64), confirm: true }) });
      check(noConfirm.status === 400 && stale.status === 409 && badImport.status === 409, `${noConfirm.status} ${stale.status} ${badImport.status}`);
      return "400 without confirm; 409 for stale hashes";
    });

    await page.screenshot({ path: join(OUT, "data.png") });
  } catch (e) {
    record("data test stopped early", false, String(e.message ?? e).split("\n")[0]);
  } finally {
    if (browser) await browser.close().catch(() => {});
    await services.down();
  }

  await step("the real mapping decisions did not change", async () => {
    const after = await sha256File(join(fixture.real_mappings, "manual_mappings.json"));
    check(after === realBefore, "real manual_mappings.json changed");
    return `sha256 ${after.slice(0, 16)}…`;
  });
  const failed = results.filter((r) => !r.ok);
  await writeFile(join(OUT, "data-report.json"), JSON.stringify({ results, root }, null, 2));
  console.log(failed.length ? `\n${failed.length} step(s) failed.` : "\nAll steps passed.");
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
