"""Build & Test backend: builds, deployment to MCC and restore, driven from the Studio.

Everything here runs the existing tools as subprocesses, one job at a time:
  build    scripts/build/m6_build.py --kind audio|subtitles|both (the Spanish bank from the approved audio
           decisions, recipes and global gain; SU_Halo1.bin + SP_Halo1.bin from the approved subtitle
           decisions; or all three)
  install  scripts/build/m6_install.py preflight, then install (MCC closed, Steam build pinned, every
           original hash-checked and backed up outside the game, snapshot diff, originals restored on any
           failure)
  restore  scripts/build/m6_install.py rollback (verified backups; backups are kept), for every build whose
           files are installed, in one job
Install and restore only run after the owner confirms them in the page (confirm: true), for the build they
picked. Nothing here launches MCC, and nothing runs on its own. A combined build's three files are one
install: the installer restores all of them if any step fails.

The MCC folder: a test override given to the server (--mcc-root, a throw-away copy), else the folder saved
from the page (config/mcc_install.json, git-ignored), else HALO_MCC_FOLDER in .env, else the default Steam
libraries. It must contain halo1/sound/pc/sounds_dialogs_spanish.fsb.

A build is stale when the decisions it was made from are not the decisions on disk now, when the custom
subtitle text it was made with changed (subtitle builds), or when the global audio gain it was made with is
not the gain configured now (audio builds). Stale builds are reported, never rebuilt automatically; the
installer itself refuses a build whose replaced lines or written subtitles are no longer approved.
"""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "discovery"))
from b2_bank_install import running_game_processes  # noqa: E402
from common.env import load_env  # noqa: E402
from common.export_config import load_export_config  # noqa: E402
from common.m6_build import BUILD_KINDS, SUBTITLE_TABLES, mission_folders, plan_audio, subtitle_plan  # noqa: E402
from m4_app import ApiError  # noqa: E402

NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
LEVEL_RE = re.compile(r"^[a-z0-9]{1,8}$")
# The tools read the repository's decisions and write work/m6/ themselves, so they always run from the repo.
REPO = Path(__file__).resolve().parents[2]
M6_BUILD = REPO / "scripts/build/m6_build.py"
M6_INSTALL = REPO / "scripts/build/m6_install.py"
MCC_CONFIG = Path("config/mcc_install.json")
BANK_REL = "halo1/sound/pc/sounds_dialogs_spanish.fsb"
STEAM_DEFAULTS = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"]
MCC_DIR_NAME = "Halo The Master Chief Collection"
LOCAL = Path("mappings/manual_mappings.local.json")
KIND_SUFFIX = {"audio": "", "subtitles": "_subs", "both": "_both"}
RUNTIME_NOTE = ("Subtitle tables are rewritten with longer or shorter text (variable length). The files pass "
                "every offline structural and content check; MCC loading a table of a different size is "
                "still to be confirmed in the game (only same-length edits were tested in game, B1).")


def level_report(manifest):
    """The level settings a build used and what they did (manifest `level`, or the older `global_gain` block)."""
    lv = manifest.get("level")
    g = manifest.get("global_gain") or {}
    if lv:
        return {"mode": lv["mode"], "global_gain_db": lv["global_gain_db"], "lines": lv["lines"],
                "effective_gain_db": lv["effective_gain_db"], "constrained": len(lv["constrained"]),
                "fallback": len(lv["fallback_to_global_gain"]), "limiter_max_reduction_db": lv["limiter_max_reduction_db"],
                "loudness_vs_spain_db": lv["loudness_vs_spain_db"], "source": lv["source"]}
    slots = [e for e in manifest.get("slots", []) if e.get("action") == "replace"]
    gains = sorted(e.get("global_gain_applied_db", 0.0) for e in slots)
    return {"mode": "global_gain", "global_gain_db": g.get("configured_db"), "lines": len(slots),
            "effective_gain_db": {"min": gains[0], "median": gains[len(gains) // 2], "max": gains[-1]} if gains else None,
            "constrained": len(g.get("short", [])), "fallback": 0, "limiter_max_reduction_db": None,
            "loudness_vs_spain_db": None, "source": g.get("source")}


def _sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _read_json(path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _is_mcc(folder):
    return folder is not None and (Path(folder) / BANK_REL).is_file()


class BuildBoard:
    def __init__(self, root, known_levels, runner=None, mcc_root=None, deploy_state=None, app=None):
        self.root = Path(root)
        self.build_root = self.root / "work" / "m6"
        self.decisions = self.root / "mappings" / "manual_mappings.json"
        self.known_levels = known_levels  # callable -> set of MCC level names from the catalogs
        self.runner = runner or self._run_m6_build  # injectable so tests never start a real build
        # Test sandbox: a throw-away game folder and its own backups/state (never the real install).
        self.mcc_override = Path(mcc_root) if mcc_root else None
        self.deploy_state = Path(deploy_state) if deploy_state else None
        self.app = app  # the M4App (catalogs, decisions) for scope previews; None in unit tests
        self._lock = threading.Lock()
        self._jobs = {}
        self._hash_cache = {}

    # ----------------------------------------------------------------- listings
    def list_builds(self):
        current = hashlib.sha256(self.decisions.read_bytes()).hexdigest() if self.decisions.is_file() else None
        local_now = _sha_file(self.root / LOCAL)
        cfg_now = load_export_config(self.root)
        gain_now, mode_now = cfg_now["global_gain_db"], cfg_now["level_mode"]
        builds = []
        for folder in sorted(p for p in self.build_root.glob("*") if p.is_dir()):
            manifest = _read_json(folder / "build_manifest.json")
            if manifest is None:
                continue  # logs, caches and the like are not builds
            report = _read_json(folder / "validation_report.json") or {}
            kind = manifest.get("kind", "audio")
            audio, subs = kind in ("audio", "both"), kind in ("subtitles", "both")
            inputs = manifest.get("inputs", {})
            built_from = inputs.get("mappings_sha256")
            built_gain = (manifest.get("global_gain") or {}).get("configured_db")
            reasons = []
            if built_from is not None and built_from != current:
                reasons.append("decisions changed since the build")
            if subs and inputs.get("local_sha256") != local_now:
                reasons.append("custom subtitle text changed since the build")
            built_mode = (manifest.get("global_gain") or {}).get("level_mode", "global_gain")
            if audio and built_mode != mode_now:
                reasons.append(f"level mode changed since the build ({built_mode} → {mode_now})")
            elif audio and built_mode == "global_gain" and (built_gain is None or built_gain != gain_now):
                reasons.append("export gain changed since the build" if built_gain is not None
                               else "build does not record the export gain")
            sub = manifest.get("subtitles") or {}
            builds.append({
                "name": folder.name,
                "kind": kind,
                "levels": manifest.get("levels", []),
                "built_at": manifest.get("built_at"),
                "counts": manifest.get("counts", {}),
                "subtitles": {"enabled": bool(sub.get("enabled")), "summary": sub.get("summary"),
                              "tables": sub.get("tables"), "warnings": sub.get("warnings", []),
                              "conflicts": len(sub.get("conflicts", []))},
                "failed_checks": [k for k, v in (report.get("checks") or {}).items() if not v],
                "validation_ok": report.get("ok"),
                "stale": bool(reasons),
                "stale_reasons": reasons,
                "built_gain_db": built_gain,
                "level": level_report(manifest) if audio else None,
                "built_from_sha256": built_from,
                "candidate_sha256": report.get("candidate_sha256"),
                "install_files": [{"install_rel": f["install_rel"], "candidate": f.get("candidate"),
                                   "candidate_sha256": f["candidate_sha256"], "size": f.get("size")}
                                  for f in manifest.get("install_files", [])],
                "has_log": (self.build_root / f"{folder.name}_build.log").is_file(),
            })
        return {"builds": builds, "decisions_sha256": current, "kinds": list(BUILD_KINDS),
                "runtime_note": RUNTIME_NOTE, "missions": self.missions()}

    def build_detail(self, name):
        """One build's subtitle entries, exclusions, conflicts and checks, for the page's details view."""
        m = _read_json(self.build_root / name / "build_manifest.json") if NAME_RE.match(name or "") else None
        if not m:
            raise ApiError(404, f"no build {name!r}")
        report = _read_json(self.build_root / name / "validation_report.json") or {}
        sub = m.get("subtitles") or {}
        written = [{"key_hex": k["key_hex"], "mcc_tag": k["mcc_tag"], "level": k["level"], "slots": k["slots"],
                    "text": k["text"], "before": {t: (k["tables"].get(t) or {}).get("old_text") for t in SUBTITLE_TABLES}}
                   for k in sub.get("keys", []) if k.get("action") == "write"] if sub.get("enabled") else []
        excluded = [{k: r.get(k) for k in ("slot_id", "mcc_tag", "status", "source", "category", "result")}
                    for r in sub.get("rows", []) if r.get("category") in ("excluded", "conflict", "missing_key")]
        return {"name": name, "kind": m.get("kind", "audio"), "levels": m.get("levels", []),
                "subtitles_enabled": bool(sub.get("enabled")), "summary": sub.get("summary"),
                "tables": sub.get("tables"), "written": written, "excluded": excluded,
                "conflicts": sub.get("conflicts", []), "warnings": sub.get("warnings", []),
                "checks": report.get("checks", {}), "ok": report.get("ok"),
                "install_files": m.get("install_files", []), "not_written": m.get("not_written", [])}

    def build_log(self, name):
        if not NAME_RE.match(name or ""):
            raise ApiError(400, "bad build name")
        p = self.build_root / f"{name}_build.log"
        if not p.is_file():
            raise ApiError(404, f"no log for {name!r} (builds made outside the Studio log to the console)")
        return {"name": name, "log": p.read_text(encoding="utf-8", errors="replace")[-200000:]}

    # ----------------------------------------------------------------- scope preview
    def scope_levels(self, body):
        """The MCC folders a scope selects (the same rule as m6_build.py). -> (levels, description)."""
        scope = body.get("scope", "levels")
        if scope == "mission":
            mission = (body.get("mission") or "").lower()
            if mission not in self.missions():
                raise ApiError(400, f"unknown mission {mission!r}")
            lf = _read_json(self.root / "work" / "mcc" / "level_folders.json")
            return mission_folders(lf, mission)["selected"], f"mission {mission}"
        if scope == "levels":
            levels = body.get("levels") or []
            if not levels or any(not LEVEL_RE.match(lv) or lv not in self.known_levels() for lv in levels):
                raise ApiError(400, f"unknown MCC folder(s) {levels}")
            return sorted(set(levels)), "chosen folders"
        if scope == "all_mapped":
            if self.app is None:
                raise ApiError(409, "no catalogs loaded")
            doc, _ = self.app._mappings()
            idx = self.app.slot_index
            return sorted({idx[s["slot_id"]][0] for s in doc["slots"] if s["slot_id"] in idx}), "every mapped folder"
        raise ApiError(400, f"unknown build scope {scope!r}")

    def preview(self, body):
        """What a build of this scope would contain, from the current decisions. Read-only, nothing is built."""
        if self.app is None:
            raise ApiError(409, "no catalogs loaded")
        levels, label = self.scope_levels(body)
        app = self.app
        doc, _ = app._mappings()
        local, _ = app._local()
        idx = dict(slot_index=app.slot_index, ce_lines=app.ce_lines, ce_idx=app.ce_idx, mcc_idx=app.mcc_idx)
        audio = plan_audio(doc, levels, local=local, **idx)
        subs = subtitle_plan(doc, set(levels), local=local, tables={t: app.loc.get(t) for t in SUBTITLE_TABLES}, **idx)
        acts = {}
        for e in audio["entries"]:
            acts[e["action"]] = acts.get(e["action"], 0) + 1
        excluded = [{k: r.get(k) for k in ("slot_id", "status", "category", "result")}
                    for r in subs["rows"] if r["category"] in ("excluded", "conflict", "missing_key")]
        return {"levels": levels, "scope": label,
                "audio": {"replace": acts.get("replace", 0), "keep_original": acts.get("keep_original", 0),
                          "not_eligible": acts.get("not_eligible", 0), "conflicts": len(audio["conflicts"])},
                "subtitles": {**subs["summary"], "excluded_rows": excluded, "conflict_list": subs["conflicts"]}}

    def missions(self):
        """Playable maps that have a folder association (a mission build = its folder + its cinematics)."""
        lf = _read_json(self.root / "work" / "mcc" / "level_folders.json") or {}
        return sorted(lf.get("levels", {}))

    # ----------------------------------------------------------------- builds
    def start_build(self, body):
        """body: {kind: audio|subtitles|both, scope: mission|levels|all_mapped, mission?, levels?, name?}"""
        kind = body.get("kind", "audio")
        if kind not in BUILD_KINDS:
            raise ApiError(400, f"unknown build kind {kind!r} (audio, subtitles or both)")
        scope = body.get("scope", "levels")
        args, default_name = [], None
        if scope == "mission":
            mission = (body.get("mission") or "").lower()
            if mission not in self.missions():
                raise ApiError(400, f"unknown mission {mission!r}")
            args, default_name = ["--mission", mission], f"mission_{mission}"
        elif scope == "levels":
            levels = body.get("levels") or []
            if not levels or any(not LEVEL_RE.match(lv) or lv not in self.known_levels() for lv in levels):
                raise ApiError(400, f"unknown MCC folder(s) {levels}")
            args, default_name = [a for lv in levels for a in ("--level", lv)], "_".join(levels)
        elif scope == "all_mapped":
            args, default_name = ["--all-mapped"], "all_mapped"
        else:
            raise ApiError(400, f"unknown build scope {scope!r}")
        args += ["--kind", kind]
        name = body.get("name") or f"{default_name}{KIND_SUFFIX[kind]}_{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
        if not NAME_RE.match(name):
            raise ApiError(400, "build name: lowercase letters, digits and _ only (up to 40)")
        if (self.build_root / name).exists():
            raise ApiError(409, f"work/m6/{name} already exists; choose another name (existing builds are kept)")
        return self._start("build", name, lambda: self.runner(args, name),
                           detail={"scope": scope, "kind": kind, "args": args})

    def start_dry_run(self, levels, name=None):  # the earlier API; same as a folders-scope audio build
        # (the runner receives "--kind audio" too)
        return self.start_build({"kind": "audio", "scope": "levels", "levels": levels, "name": name})

    def _run_m6_build(self, args, name):
        """The real runner: m6_build.py writes work/m6/<name> and its log next to it."""
        cmd = [sys.executable, str(M6_BUILD), *args, "--name", name]
        code, log = self._run(cmd)
        self.build_root.mkdir(parents=True, exist_ok=True)
        (self.build_root / f"{name}_build.log").write_text(log, encoding="utf-8")
        return code, log

    # ----------------------------------------------------------------- MCC folder
    def mcc_folder(self):
        """-> (path or None, where it came from)."""
        if self.mcc_override:
            return self.mcc_override, "test override (server --mcc-root)"
        saved = (_read_json(self.root / MCC_CONFIG) or {}).get("mcc_folder")
        if saved:
            return Path(saved), "saved in the Studio (config/mcc_install.json)"
        env, _ = load_env()
        if env.get("HALO_MCC_FOLDER"):
            return Path(env["HALO_MCC_FOLDER"]), ".env HALO_MCC_FOLDER"
        for steam in STEAM_DEFAULTS:
            libraries = [steam]
            vdf = steam / "steamapps" / "libraryfolders.vdf"
            if vdf.is_file():
                libraries += [Path(p.replace("\\\\", "\\")) for p in
                              re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace"))]
            for lib in libraries:
                candidate = lib / "steamapps" / "common" / MCC_DIR_NAME
                if _is_mcc(candidate):
                    return candidate, "found in the Steam library"
        return None, "not found"

    def set_mcc_folder(self, folder):
        if self.mcc_override:
            raise ApiError(409, "the MCC folder is fixed by the server's --mcc-root (test mode)")
        path = Path(str(folder or "")).expanduser()
        if not _is_mcc(path):
            raise ApiError(400, f"{path} is not an MCC install (no {BANK_REL})")
        (self.root / MCC_CONFIG).parent.mkdir(parents=True, exist_ok=True)
        (self.root / MCC_CONFIG).write_text(json.dumps({"mcc_folder": str(path)}, indent=2) + "\n", encoding="utf-8")
        return self.deploy_status()

    # ----------------------------------------------------------------- deployment
    def _hash(self, path):
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in self._hash_cache:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 22), b""):
                    h.update(chunk)
            self._hash_cache = {k: v for k, v in self._hash_cache.items() if k[0] != str(path)}
            self._hash_cache[key] = h.hexdigest()
        return self._hash_cache[key]

    def _manifests(self):
        out = {}
        for folder in sorted(p for p in self.build_root.glob("*") if p.is_dir()):
            m = _read_json(folder / "build_manifest.json")
            if m and m.get("install_files"):
                out[folder.name] = m
        return out

    def deploy_status(self):
        """What the game folder holds now: for every file a build replaces, original / which build / unknown."""
        folder, source = self.mcc_folder()
        out = {"mcc_folder": str(folder) if folder else None, "source": source, "valid": _is_mcc(folder),
               "fixed": self.mcc_override is not None, "game_running": running_game_processes(),
               "files": [], "active_builds": [], "mod_installed": False}
        if not out["valid"]:
            return out
        manifests = self._manifests()
        files = {}
        for name, m in manifests.items():
            for f in m["install_files"]:
                entry = files.setdefault(f["install_rel"], {"install_rel": f["install_rel"],
                                                            "original_sha256": f["original_sha256"], "builds": []})
                entry["builds"].append((name, f["candidate_sha256"]))
        active = set()
        for rel, entry in sorted(files.items()):
            installed = folder / rel
            sha = self._hash(installed) if installed.is_file() else None
            matches = [name for name, cand in entry["builds"] if cand == sha]
            state = "original" if sha == entry["original_sha256"] else "build" if matches else "unknown"
            active.update(matches)
            out["files"].append({"install_rel": rel, "sha256": sha, "state": state, "builds": matches})
        out["active_builds"] = sorted(active)
        out["mod_installed"] = any(f["state"] != "original" for f in out["files"])
        # The level settings inside the installed audio, against what the Studio is set to now.
        cfg = load_export_config(self.root)
        out["current_level"] = {"mode": cfg["level_mode"], "global_gain_db": cfg["global_gain_db"]}
        out["installed_level"] = []
        for name in out["active_builds"]:
            m = manifests[name]
            if m.get("kind", "audio") in ("audio", "both"):
                lv = level_report(m)
                lv.update(build=name, built_at=m.get("built_at"),
                          matches_current=lv["mode"] == cfg["level_mode"] and (
                              lv["mode"] != "global_gain" or lv["global_gain_db"] == cfg["global_gain_db"]))
                out["installed_level"].append(lv)
        return out

    def install_plan(self, name):
        """What installing build `name` would do, for the confirmation dialog. Read-only."""
        m = _read_json(self.build_root / name / "build_manifest.json") if NAME_RE.match(name or "") else None
        if not m or not m.get("install_files"):
            raise ApiError(404, f"no installable build {name!r}")
        report = _read_json(self.build_root / name / "validation_report.json") or {}
        build = next((b for b in self.list_builds()["builds"] if b["name"] == name), {})
        kind = m.get("kind", "audio")
        sub = (m.get("subtitles") or {}).get("summary") or {}
        folder, _ = self.mcc_folder()
        backups = (self.deploy_state / "backup") if self.deploy_state else self.root / "work" / "mcc" / "backup"
        return {"build": name, "mcc_folder": str(folder) if folder else None, "validation_ok": report.get("ok"),
                "stale": build.get("stale"), "stale_reasons": build.get("stale_reasons", []),
                "counts": m.get("counts", {}), "levels": m.get("levels", []),
                "files": [{"install_rel": f["install_rel"], "installed_path": str((folder or Path("?")) / f["install_rel"]),
                           "candidate_bytes": (self.root / f["candidate"]).stat().st_size
                           if (self.root / f["candidate"]).is_file() else None,
                           "original_sha256": f["original_sha256"], "candidate_sha256": f["candidate_sha256"],
                           "backup_folder": str(backups)} for f in m["install_files"]],
                "kind": kind,
                "subtitles": (f"SU and SP rewritten: {sub.get('keys_to_write', 0)} entr(ies) each at most; "
                              f"{sub.get('excluded', 0)} excluded, {sub.get('conflicts', 0)} conflict(s). "
                              + RUNTIME_NOTE) if kind in ("subtitles", "both")
                else "not changed (audio-only build)",
                "audio": "Spanish dialogue bank replaced" if kind in ("audio", "both") else "not changed (subtitle-only build)"}

    def _install_args(self, name):
        folder, _ = self.mcc_folder()
        if not _is_mcc(folder):
            raise ApiError(409, "set the MCC folder first")
        args = ["--build", name, "--mcc-root", str(folder), "--history", str(self.history_path())]
        if self.deploy_state:
            args += ["--backup-root", str(self.deploy_state / "backup"), "--state-dir", str(self.deploy_state / name)]
        return args

    def history_path(self):
        return (self.deploy_state / "deploy_history.jsonl") if self.deploy_state \
            else self.build_root / "deploy_history.jsonl"

    def history(self, limit=30):
        """The latest install / restore events (newest first) from the installer's append-only history."""
        p = self.history_path()
        if not p.is_file():
            return {"events": []}
        events = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        return {"events": events[::-1][:limit]}

    def start_install(self, body):
        """body: {build, confirm: true}. preflight (checks + verified backups + snapshot), then install.
        simulate_failure_after: N is accepted only in test mode (--mcc-root), to prove the automatic restore."""
        name = body.get("build") or ""
        fail_after = body.get("simulate_failure_after")
        if fail_after is not None and (not self.mcc_override or not isinstance(fail_after, int) or fail_after < 0):
            raise ApiError(400, "simulate_failure_after is only for the test server's throw-away game folder")
        install_extra = ["--simulate-failure-after", str(fail_after)] if fail_after is not None else []
        if body.get("confirm") is not True:
            raise ApiError(400, "installing changes game files; it needs confirm: true")
        plan = self.install_plan(name)  # 404 for unknown builds
        if plan["validation_ok"] is not True:
            raise ApiError(409, "this build did not pass validation; rebuild it")
        if running_game_processes():
            raise ApiError(409, "MCC (or its anti-cheat) is running; close it completely first")
        args = self._install_args(name)
        script = str(M6_INSTALL)

        def work():
            code, log = self._run([sys.executable, script, *args, "preflight"])
            if code != 0:
                return code, log + "\nInstall not started: the preflight stopped (nothing in the game changed)."
            code2, log2 = self._run([sys.executable, script, *args, *install_extra, "install"])
            return code2, log + "\n" + log2
        return self._start("install", name, work)

    def start_restore(self, body):
        """body: {build?, confirm: true}. Restores every file of that build from its verified backup; without a
        build, every installed build (for example an audio build and a subtitle build installed one after the
        other), one after another in one job. Stops at the first failure."""
        if body.get("confirm") is not True:
            raise ApiError(400, "restoring changes game files; it needs confirm: true")
        status = self.deploy_status()
        names = [body["build"]] if body.get("build") else status["active_builds"]
        if not names:
            if not status["mod_installed"]:
                raise ApiError(409, "the game files are already the originals")
            raise ApiError(409, "the installed files match no build here; name the build to restore with, "
                                "or use Steam's 'Verify integrity of game files'")
        for name in names:
            self.install_plan(name)
        if running_game_processes():
            raise ApiError(409, "MCC (or its anti-cheat) is running; close it completely first")
        runs = [(name, self._install_args(name)) for name in names]

        def work():
            logs = []
            for name, args in runs:
                code, log = self._run([sys.executable, str(M6_INSTALL), *args, "rollback"])
                logs.append(f"[{name}]\n{log}")
                if code != 0:
                    return code, "\n".join(logs)
            return 0, "\n".join(logs)
        return self._start("restore", ", ".join(names), work)

    # ----------------------------------------------------------------- jobs
    def _start(self, kind, name, work, detail=None):
        with self._lock:
            if any(j["state"] == "running" for j in self._jobs.values()):
                raise ApiError(409, "another build or install is running; wait for it to finish")
            job = {"id": uuid.uuid4().hex, "kind": kind, "name": name, "state": "running", "detail": detail or {},
                   "started": dt.datetime.now().isoformat(timespec="seconds"), "returncode": None, "log_tail": ""}
            self._jobs[job["id"]] = job

        def finish():
            try:
                code, log = work()
            except Exception as e:  # noqa: BLE001 - report in the job, never crash the server
                code, log = 1, f"{type(e).__name__}: {e}"
            with self._lock:
                job.update(state="done" if code == 0 else "failed", returncode=code, log_tail=log[-6000:],
                           finished=dt.datetime.now().isoformat(timespec="seconds"))
            self._hash_cache.clear()  # installed files may have changed
        threading.Thread(target=finish, daemon=True).start()
        return self.public(job)

    def job(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, "unknown build job")
        return self.public(job)

    @staticmethod
    def public(job):
        return dict(job)

    def _run(self, cmd):
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.returncode, proc.stdout + proc.stderr
