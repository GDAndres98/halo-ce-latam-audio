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


def write_build(root, name, mappings_sha, ok=True):
    folder = root / "work" / "m6" / name
    folder.mkdir(parents=True)
    (folder / "build_manifest.json").write_text(json.dumps({
        "schema": "m6-build-manifest/1", "name": name, "levels": [name], "built_at": "2026-10-10T10:00:00",
        "inputs": {"mappings_sha256": mappings_sha}, "counts": {"audio": 3}, "subtitles": {"enabled": False},
        "global_gain": {"configured_db": 4.0}}))  # the default gain: these tests are about the decisions only
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
        self.assertEqual(self.calls, [(["a10"], "a10_test")])
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


if __name__ == "__main__":
    unittest.main()
