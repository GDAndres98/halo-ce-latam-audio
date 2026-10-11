"""Global audio gain set from the Studio: save rules, history, and the builds it makes stale.

Works in a temporary folder only. The real config/audio_export.json is never touched.
"""
import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))

from common.export_config import (  # noqa: E402
    CONFIG,
    DEFAULT_GLOBAL_GAIN_DB,
    ConfigError,
    load_export_config,
    save_global_gain,
)
from build_api import BuildBoard  # noqa: E402

NOW = dt.datetime(2026, 10, 10, 12, 0, 0)


class GlobalGainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "config").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def sha(self):
        p = self.root / CONFIG
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

    def test_the_default_is_plus_four_dB_without_a_file(self):
        self.assertEqual(load_export_config(self.root)["global_gain_db"], 4.0)
        self.assertEqual(DEFAULT_GLOBAL_GAIN_DB, 4.0)

    def test_a_saved_gain_is_read_back_and_kept_as_a_canonical_file(self):
        saved = save_global_gain(self.root, 2.5, None, now=NOW)
        self.assertEqual(saved["global_gain_db"], 2.5)
        self.assertEqual(json.loads((self.root / CONFIG).read_text(encoding="utf-8")),
                         {"schema": "audio-export-config/1", "global_gain_db": 2.5})
        self.assertEqual(load_export_config(self.root)["global_gain_db"], 2.5)

    def test_values_outside_the_range_are_refused_and_nothing_is_written(self):
        for bad in (13, -12.5, "loud", None):
            with self.assertRaises((ConfigError, TypeError, ValueError)):
                save_global_gain(self.root, bad, None)
        self.assertFalse((self.root / CONFIG).exists())

    def test_a_file_changed_since_it_was_loaded_is_refused(self):
        save_global_gain(self.root, 1.0, None, now=NOW)
        loaded = self.sha()
        save_global_gain(self.root, 3.0, loaded, now=NOW + dt.timedelta(seconds=1))
        with self.assertRaises(ConfigError):
            save_global_gain(self.root, 5.0, loaded, now=NOW + dt.timedelta(seconds=2))  # stale hash
        self.assertEqual(load_export_config(self.root)["global_gain_db"], 3.0)

    def test_the_previous_file_is_kept_in_history(self):
        save_global_gain(self.root, 1.0, None, now=NOW)
        save_global_gain(self.root, 3.0, self.sha(), now=NOW + dt.timedelta(seconds=1))
        kept = list((self.root / "config" / ".history").glob("audio_export.*.json"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(json.loads(kept[0].read_text(encoding="utf-8"))["global_gain_db"], 1.0)


class GainStalenessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "mappings").mkdir()
        (self.root / "config").mkdir()
        (self.root / "mappings" / "manual_mappings.json").write_bytes(b"decisions")
        self.decisions = hashlib.sha256(b"decisions").hexdigest()

    def tearDown(self):
        self._tmp.cleanup()

    def write_build(self, name, gain_db):
        folder = self.root / "work" / "m6" / name
        folder.mkdir(parents=True)
        manifest = {"schema": "m6-build-manifest/1", "levels": [name], "built_at": "2026-10-10T10:00:00",
                    "inputs": {"mappings_sha256": self.decisions}}
        if gain_db is not None:
            manifest["global_gain"] = {"configured_db": gain_db}
        (folder / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def listing(self):
        board = BuildBoard(self.root, lambda: {"a10"}, runner=lambda *_: (0, ""))
        return {b["name"]: b for b in board.list_builds()["builds"]}

    def test_a_build_made_with_the_current_gain_is_current(self):
        self.write_build("a10", 4.0)
        self.assertFalse(self.listing()["a10"]["stale"])

    def test_changing_the_gain_marks_builds_stale_with_the_reason(self):
        self.write_build("a10", 4.0)
        save_global_gain(self.root, 2.0, None, now=NOW)
        build = self.listing()["a10"]
        self.assertTrue(build["stale"])
        self.assertEqual(build["stale_reasons"], ["export gain changed since the build"])
        self.assertEqual(build["built_gain_db"], 4.0)

    def test_a_build_that_does_not_record_its_gain_is_stale_not_guessed(self):
        self.write_build("a10", None)
        build = self.listing()["a10"]
        self.assertTrue(build["stale"])
        self.assertEqual(build["stale_reasons"], ["build does not record the export gain"])


if __name__ == "__main__":
    unittest.main()
