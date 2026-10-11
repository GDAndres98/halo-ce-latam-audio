// Shared helpers for the browser tests: start and stop the API and Vite servers, run repository scripts,
// and make a disposable copy of the mapping data. Used by run.mjs (the workflow test) and by
// compare-m4.mjs (the comparison with the classic page).
//
// Nothing here writes to the real mappings folder: the fixture copies it first.

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const HERE = dirname(fileURLToPath(import.meta.url));
export const FRONTEND = resolve(HERE, "..");
export const REPO = resolve(FRONTEND, "..");
export const WEB_PORT = 5190;
export const API_PORT = 8790;

export function start(name, command, args, options = {}) {
  const child = spawn(command, args, { cwd: options.cwd ?? FRONTEND, env: { ...process.env, ...options.env }, windowsHide: true });
  child.stdout.on("data", () => {});
  child.stderr.on("data", (chunk) => {
    if (process.env.E2E_VERBOSE) process.stderr.write(`[${name}] ${chunk}`);
  });
  return child;
}

export async function stopProcess(child) {
  if (!child || child.exitCode !== null) return;
  // taskkill stops the whole tree (npm and vite spawn children on Windows).
  await new Promise((done) => {
    const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
    killer.on("exit", done);
  });
}

export async function waitForHttp(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) throw new Error(`no answer from ${url}`);
    await new Promise((r) => setTimeout(r, 500));
  }
}

export async function sha256File(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

/** Runs a Python script of this repository and returns its exit code and output. */
export function runPython(args) {
  return new Promise((done) => {
    const child = spawn("python", args, { cwd: REPO, windowsHide: true });
    let out = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (out += c));
    child.on("exit", (code) => done({ code, out }));
  });
}

/** Makes the disposable copy of the mapping data (scripts/ui/e2e_fixture.py). */
export function runFixture(dest) {
  return new Promise((done, fail) => {
    const child = spawn("python", ["scripts/ui/e2e_fixture.py", "--dest", dest], { cwd: REPO, windowsHide: true });
    let out = "";
    let err = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (err += c));
    child.on("exit", (code) =>
      code === 0 ? done(JSON.parse(out.trim().split("\n").pop())) : fail(new Error(err || `fixture exit ${code}`)),
    );
  });
}

/** The API server (on a disposable root) and the Vite dev server for the Studio. */
export class Services {
  /** extraArgs: more m4_server.py flags (the deploy test passes --mcc-root and --deploy-state). */
  constructor(root, extraArgs = []) {
    this.root = root;
    this.extraArgs = extraArgs;
  }

  async up() {
    this.api = start("api", "python", ["scripts/ui/m4_server.py", "--root", this.root, "--port", String(API_PORT), "--no-open", ...this.extraArgs], { cwd: REPO });
    await waitForHttp(`http://127.0.0.1:${API_PORT}/api/state`);
    this.web = start("web", process.execPath, [join(FRONTEND, "node_modules", "vite", "bin", "vite.js"), "--port", String(WEB_PORT), "--strictPort"],
      { env: { STUDIO_API: `http://127.0.0.1:${API_PORT}` } });
    await waitForHttp(`http://localhost:${WEB_PORT}/`);
  }

  async down() {
    await stopProcess(this.web);
    await stopProcess(this.api);
  }
}

/**
 * Answers the Studio's confirmation dialogs (components/ui/ConfirmDialog.vue) by clicking their buttons, the
 * way a person does. `decide(message)` returns true to confirm, false to cancel; by default everything is
 * confirmed. Every message seen is kept in `messages`. Replaces page.on("dialog") now that the Studio no
 * longer uses the browser's own confirm().
 */
export function handleConfirms(page, decide = () => true) {
  const state = { decide, messages: [], active: true };
  const dialog = page.locator("dialog.confirm-dialog[open]");
  (async () => {
    while (state.active && !page.isClosed()) {
      try {
        if (await dialog.count()) {
          const text = await dialog.locator(".body").innerText({ timeout: 1000 });
          state.messages.push(text);
          const yes = await state.decide(text);
          await dialog.locator(`[data-confirm="${yes ? "yes" : "no"}"]`).click({ timeout: 2000 });
          await dialog.waitFor({ state: "detached", timeout: 2000 }).catch(() => {});
        }
      } catch {
        // the page navigated or closed while answering: look again
      }
      await new Promise((r) => setTimeout(r, 80));
    }
  })();
  return {
    messages: state.messages,
    set: (fn) => (state.decide = fn),
    stop: () => (state.active = false),
  };
}
