"""Build & Test dashboard backend: build listings with stale detection, and dry-run builds.

Nothing here touches the MCC install. Dry runs write only under work/m6/ through
scripts/build/m6_build.py. Deploying and restoring stay in scripts/build/m6_install.py, which needs the
owner's explicit approval for each build; the dashboard does not call it.

A build is stale when the decisions it was made from are not the decisions on disk now. The build
manifest records the hash of manual_mappings.json at build time, so comparing hashes is enough.
"""
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from m4_app import ApiError

NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
LEVEL_RE = re.compile(r"^[a-z0-9]{1,8}$")
M6_BUILD = Path("scripts/build/m6_build.py")


def _read_json(path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class BuildBoard:
    def __init__(self, root, known_levels, runner=None):
        self.root = Path(root)
        self.build_root = self.root / "work" / "m6"
        self.decisions = self.root / "mappings" / "manual_mappings.json"
        self.known_levels = known_levels  # callable -> set of MCC level names from the catalogs
        self.runner = runner or self._run_m6_build  # injectable so tests never start a real build
        self._lock = threading.Lock()
        self._jobs = {}

    # ----------------------------------------------------------------- listings
    def list_builds(self):
        current = hashlib.sha256(self.decisions.read_bytes()).hexdigest() if self.decisions.is_file() else None
        builds = []
        for folder in sorted(p for p in self.build_root.glob("*") if p.is_dir()):
            manifest = _read_json(folder / "build_manifest.json")
            if manifest is None:
                continue  # logs, caches and the like are not builds
            report = _read_json(folder / "validation_report.json") or {}
            built_from = manifest.get("inputs", {}).get("mappings_sha256")
            builds.append({
                "name": folder.name,
                "levels": manifest.get("levels", []),
                "built_at": manifest.get("built_at"),
                "counts": manifest.get("counts", {}),
                "subtitles": manifest.get("subtitles", {}),
                "validation_ok": report.get("ok"),
                "stale": built_from is not None and built_from != current,
                "built_from_sha256": built_from,
                "candidate_sha256": report.get("candidate_sha256"),
            })
        return {"builds": builds, "decisions_sha256": current}

    # ----------------------------------------------------------------- dry runs
    def start_dry_run(self, levels, name=None):
        if not levels or any(not LEVEL_RE.match(lv) or lv not in self.known_levels() for lv in levels):
            raise ApiError(400, f"unknown MCC level(s) {levels}")
        name = name or "_".join(levels) + "_" + dt.datetime.now().strftime("%Y%m%d%H%M%S")
        if not NAME_RE.match(name):
            raise ApiError(400, "build name: lowercase letters, digits and _ only (up to 40)")
        if (self.build_root / name).exists():
            raise ApiError(409, f"work/m6/{name} already exists; choose another name (existing builds are kept)")
        with self._lock:
            if any(j["state"] == "running" for j in self._jobs.values()):
                raise ApiError(409, "a build is already running")
            job = {"id": uuid.uuid4().hex, "name": name, "levels": list(levels), "state": "running",
                   "started": dt.datetime.now().isoformat(timespec="seconds"), "returncode": None, "log_tail": ""}
            self._jobs[job["id"]] = job
        threading.Thread(target=self._finish, args=(job, levels, name), daemon=True).start()
        return self.public(job)

    def _finish(self, job, levels, name):
        code, log = self.runner(levels, name)
        with self._lock:
            job.update(state="done" if code == 0 else "failed", returncode=code, log_tail=log[-4000:])

    def job(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, "unknown build job")
        return self.public(job)

    @staticmethod
    def public(job):
        return dict(job)

    def _run_m6_build(self, levels, name):
        """The real runner: m6_build.py writes work/m6/<name> and its log next to it."""
        cmd = [sys.executable, str(self.root / M6_BUILD)]
        for lv in levels:
            cmd += ["--level", lv]
        cmd += ["--name", name]
        proc = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log = proc.stdout + proc.stderr
        self.build_root.mkdir(parents=True, exist_ok=True)
        (self.build_root / f"{name}_build.log").write_text(log, encoding="utf-8")
        return proc.returncode, log
