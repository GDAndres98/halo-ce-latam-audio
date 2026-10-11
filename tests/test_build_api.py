"""Build & Test dashboard backend: listings, stale detection, dry-run guards.

Everything runs in a temporary folder with a fake runner, so no real build starts and no game file is
read or written.
"""
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ui"))

from build_api import BuildBoard  # noqa: E402
from m4_app import ApiError  # noqa: E402


def write_build(root, name, mappings_sha, ok=True, kind=None, local_sha=None, gain=4.0, install_files=()):
    folder = root / "work" / "m6" / name
    folder.mkdir(parents=True)
    manifest = {
        "schema": "m6-build-manifest/1", "name": name, "levels": [name], "built_at": "2026-10-10T10:00:00",
        "inputs": {"mappings_sha256": mappings_sha, "local_sha256": local_sha}, "counts": {"audio": 3},
        "subtitles": {"enabled": kind in ("subtitles", "both")},
        "global_gain": {"configured_db": gain},  # 4.0 = the default gain: most tests are about the decisions
        "install_files": list(install_files)}
    if kind:
        manifest["kind"] = kind
    (folder / "build_manifest.json").write_text(json.dumps(manifest))
    (folder / "validation_report.json").write_text(json.dumps({"ok": ok, "candidate_sha256": "c" * 64}))


class BuildBoardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "mappings").mkdir()
        (self.root / "mappings" / "manual_mappings.json").write_bytes(b"decisions v2")
        self.current = hashlib.sha256(b"decisions v2").hexdigest()
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def board(self, runner=None):
        def fake_runner(levels, name):
            self.calls.append((list(levels), name))
            return 0, "built"
        return BuildBoard(self.root, lambda: {"a10", "x10"}, runner=runner or fake_runner)

    def wait_for(self, board, job_id):
        for _ in range(200):
            job = board.job(job_id)
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_a_build_made_from_older_decisions_is_stale(self):
        write_build(self.root, "a10", "0" * 64)
        write_build(self.root, "x10", self.current)
        builds = {b["name"]: b for b in self.board().list_builds()["builds"]}
        self.assertTrue(builds["a10"]["stale"])
        self.assertFalse(builds["x10"]["stale"])
        self.assertTrue(builds["x10"]["validation_ok"])

    def test_folders_without_a_manifest_are_not_builds(self):
        (self.root / "work" / "m6" / "a10_build.log").parent.mkdir(parents=True)
        (self.root / "work" / "m6" / "a10_build.log").write_text("log")
        self.assertEqual(self.board().list_builds()["builds"], [])

    def test_dry_run_builds_with_the_given_levels_and_name(self):
        board = self.board()
        started = board.start_dry_run(["a10"], "a10_test")
        job = self.wait_for(board, started["id"])
        self.assertEqual(self.calls, [(["--level", "a10", "--kind", "audio"], "a10_test")])  # m6_build.py arguments
        self.assertEqual((job["state"], job["returncode"]), ("done", 0))

    def test_refuses_unknown_levels_bad_names_and_existing_builds(self):
        board = self.board()
        with self.assertRaises(ApiError) as cm:
            board.start_dry_run(["z99"], "ok")
        self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ApiError) as cm:
            board.start_dry_run(["a10"], "../escape")
        self.assertEqual(cm.exception.status, 400)
        write_build(self.root, "a10", self.current)
        with self.assertRaises(ApiError) as cm:
            board.start_dry_run(["a10"], "a10")  # never overwrite an existing build
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.calls, [])

    def test_only_one_build_runs_at_a_time(self):
        release = threading.Event()

        def slow_runner(levels, name):
            release.wait(5)
            return 0, ""
        board = self.board(runner=slow_runner)
        first = board.start_dry_run(["a10"], "first")
        with self.assertRaises(ApiError) as cm:
            board.start_dry_run(["x10"], "second")
        self.assertEqual(cm.exception.status, 409)
        release.set()
        self.wait_for(board, first["id"])

    def test_a_failed_build_is_reported_with_its_log(self):
        board = self.board(runner=lambda levels, name: (1, "validation failed: bank"))
        job = self.wait_for(board, board.start_dry_run(["a10"], "bad")["id"])
        self.assertEqual(job["state"], "failed")
        self.assertIn("validation failed", job["log_tail"])

    def test_unknown_job_is_404(self):
        with self.assertRaises(ApiError) as cm:
            self.board().job("nope")
        self.assertEqual(cm.exception.status, 404)

    def test_build_scopes_pass_the_matching_builder_arguments(self):
        (self.root / "work/mcc").mkdir(parents=True, exist_ok=True)
        (self.root / "work/mcc/level_folders.json").write_text(json.dumps({"levels": {"a10": {}}}))
        board = self.board()
        self.wait_for(board, board.start_build({"scope": "mission", "mission": "a10", "name": "m1"})["id"])
        self.wait_for(board, board.start_build({"scope": "all_mapped", "name": "m2"})["id"])
        self.assertEqual(self.calls, [(["--mission", "a10", "--kind", "audio"], "m1"),
                                      (["--all-mapped", "--kind", "audio"], "m2")])
        with self.assertRaises(ApiError):
            board.start_build({"scope": "mission", "mission": "zz9"})

    def test_subtitle_and_combined_builds_pass_their_kind(self):
        board = self.board()
        self.wait_for(board, board.start_build({"kind": "subtitles", "scope": "levels", "levels": ["a10"],
                                                "name": "s1"})["id"])
        self.wait_for(board, board.start_build({"kind": "both", "scope": "levels", "levels": ["a10", "x10"],
                                                "name": "b1"})["id"])
        self.assertEqual(self.calls, [(["--level", "a10", "--kind", "subtitles"], "s1"),
                                      (["--level", "a10", "--level", "x10", "--kind", "both"], "b1")])
        job = self.wait_for(board, board.start_build({"kind": "subtitles", "scope": "levels", "levels": ["a10"]})["id"])
        self.assertTrue(job["name"].startswith("a10_subs_"))
        with self.assertRaises(ApiError) as cm:
            board.start_build({"kind": "everything", "scope": "levels", "levels": ["a10"]})
        self.assertEqual(cm.exception.status, 400)

    def test_subtitle_build_staleness_follows_custom_text_not_the_gain(self):
        (self.root / "mappings" / "manual_mappings.local.json").write_bytes(b"custom v1")
        local = hashlib.sha256(b"custom v1").hexdigest()
        write_build(self.root, "subs", self.current, kind="subtitles", local_sha=local, gain=-3.0)
        write_build(self.root, "both", self.current, kind="both", local_sha=local)
        builds = {b["name"]: b for b in self.board().list_builds()["builds"]}
        self.assertFalse(builds["subs"]["stale"], builds["subs"]["stale_reasons"])  # the gain is an audio setting
        self.assertEqual(builds["subs"]["kind"], "subtitles")
        (self.root / "mappings" / "manual_mappings.local.json").write_bytes(b"custom v2")
        builds = {b["name"]: b for b in self.board().list_builds()["builds"]}
        for name in ("subs", "both"):
            self.assertIn("custom subtitle text changed since the build", builds[name]["stale_reasons"])

    def test_install_and_restore_need_an_explicit_confirmation(self):
        board = self.board()
        for call in (lambda: board.start_install({"build": "a10"}), lambda: board.start_restore({})):
            with self.assertRaises(ApiError) as cm:
                call()
            self.assertEqual(cm.exception.status, 400)


class DeployTests(unittest.TestCase):
    """Install / restore orchestration against a fake game folder. The installer is replaced by a recorder, so
    nothing is copied here (m6_install.py itself is tested in test_m6_install.py)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        (self.root / "mappings").mkdir(parents=True)
        (self.root / "mappings" / "manual_mappings.json").write_bytes(b"d")
        self.game = Path(self._tmp.name) / "game"
        (self.game / "halo1/sound/pc").mkdir(parents=True)
        (self.game / "Data/ui/localization").mkdir(parents=True)
        self.files = {"halo1/sound/pc/sounds_dialogs_spanish.fsb": b"bank",
                      "Data/ui/localization/SU_Halo1.bin": b"su", "Data/ui/localization/SP_Halo1.bin": b"sp"}
        for rel, data in self.files.items():
            (self.game / rel).write_bytes(data)
        self.state = Path(self._tmp.name) / "state"
        self.board = BuildBoard(self.root, lambda: {"a10"}, runner=lambda a, n: (0, ""), mcc_root=self.game,
                                deploy_state=self.state)
        self.runs = []
        self.board._run = lambda cmd: (self.runs.append(cmd), (0, "OK"))[1]

    def tearDown(self):
        self._tmp.cleanup()

    def install_file(self, rel, candidate):
        return {"install_rel": rel, "candidate": f"work/m6/x/{Path(rel).name}",
                "original_sha256": hashlib.sha256(self.files[rel]).hexdigest(),
                "candidate_sha256": hashlib.sha256(candidate).hexdigest()}

    def wait(self, job):
        for _ in range(200):
            job = self.board.job(job["id"])
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        self.fail("job did not finish")

    def test_restore_without_a_name_restores_every_installed_build(self):
        bank_rel, su_rel, sp_rel = list(self.files)
        write_build(self.root, "audio1", "x", kind="audio", install_files=[self.install_file(bank_rel, b"new bank")])
        write_build(self.root, "subs1", "x", kind="subtitles",
                    install_files=[self.install_file(su_rel, b"new su"), self.install_file(sp_rel, b"new sp")])
        for rel, data in ((bank_rel, b"new bank"), (su_rel, b"new su"), (sp_rel, b"new sp")):
            (self.game / rel).write_bytes(data)
        self.assertEqual(self.board.deploy_status()["active_builds"], ["audio1", "subs1"])
        job = self.wait(self.board.start_restore({"confirm": True}))
        self.assertEqual(job["state"], "done")
        self.assertEqual([cmd[cmd.index("--build") + 1] for cmd in self.runs], ["audio1", "subs1"])
        self.assertTrue(all(cmd[-1] == "rollback" and "--history" in cmd for cmd in self.runs))

    def test_install_refuses_unvalidated_builds_and_limits_failure_simulation_to_test_mode(self):
        su_rel = "Data/ui/localization/SU_Halo1.bin"
        write_build(self.root, "bad", "x", ok=False, kind="subtitles", install_files=[self.install_file(su_rel, b"n")])
        with self.assertRaises(ApiError) as cm:
            self.board.start_install({"build": "bad", "confirm": True})
        self.assertEqual(cm.exception.status, 409)
        write_build(self.root, "good", "x", kind="subtitles", install_files=[self.install_file(su_rel, b"n")])
        job = self.wait(self.board.start_install({"build": "good", "confirm": True, "simulate_failure_after": 0}))
        self.assertEqual(job["state"], "done")
        self.assertEqual([c[-1] for c in self.runs], ["preflight", "install"])
        self.assertIn("--simulate-failure-after", self.runs[1])
        real = BuildBoard(self.root, lambda: {"a10"})  # no --mcc-root: the real game folder
        with self.assertRaises(ApiError) as cm:
            real.start_install({"build": "good", "confirm": True, "simulate_failure_after": 0})
        self.assertNotEqual(cm.exception.status, 202)

    def test_history_is_read_newest_first(self):
        self.state.mkdir(parents=True)
        (self.state / "deploy_history.jsonl").write_text(
            json.dumps({"action": "install", "result": "ok"}) + "\n"
            + json.dumps({"action": "rollback", "result": "ok"}) + "\n", encoding="utf-8")
        self.assertEqual([e["action"] for e in self.board.history()["events"]], ["rollback", "install"])


if __name__ == "__main__":
    unittest.main()
