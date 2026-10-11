"""Global export gain (common/export_config, audio_edit.global_gain) and the one-time speed / manual-gain
migration (mapping_store.reset_removed_edit_fields, scripts/validate/migrate_reset_speed_gain.py).
Synthetic data only.

Run: python -m unittest discover -s tests
"""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import audio_edit as ae  # noqa: E402
from common import mapping_db, mapping_store  # noqa: E402
from common.export_config import DEFAULT_GLOBAL_GAIN_DB, ConfigError, load_export_config  # noqa: E402
from test_audio_edit import SRC, speech  # noqa: E402
from test_m4 import AppTestBase  # noqa: E402

FS = 44100
spec = importlib.util.spec_from_file_location("migrate_cli", ROOT / "scripts/validate/migrate_reset_speed_gain.py")
migrate_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_cli)


def tone(amp, seconds=1.0):
    return ae.float_to_pcm16([amp * math.sin(2 * math.pi * 220 * k / FS) for k in range(int(seconds * FS))])


class ConfigTests(unittest.TestCase):
    def test_default_and_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_export_config(tmp), {"global_gain_db": DEFAULT_GLOBAL_GAIN_DB, "level_mode": "global_gain", "source": "default",
                                                       "sha256": None})
            self.assertEqual(DEFAULT_GLOBAL_GAIN_DB, 4.0)
            (Path(tmp) / "config").mkdir()
            cfg = Path(tmp) / "config/audio_export.json"
            cfg.write_text(json.dumps({"schema": "audio-export-config/1", "global_gain_db": 1.5}))
            c = load_export_config(tmp)
            self.assertEqual((c["global_gain_db"], c["source"]), (1.5, "config/audio_export.json"))
            for bad in ({"schema": "audio-export-config/1", "global_gain_db": 40},
                        {"schema": "audio-export-config/1", "gain": 1}, {"global_gain_db": 1}):
                cfg.write_text(json.dumps(bad))
                with self.assertRaises(ConfigError, msg=bad):
                    load_export_config(tmp)
            cfg.write_text("{nope")
            with self.assertRaises(ConfigError):
                load_export_config(tmp)

    def test_shipped_example_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config").mkdir()
            (Path(tmp) / "config/audio_export.json").write_bytes((ROOT / "config/audio_export.example.json").read_bytes())
            c = load_export_config(tmp)                      # valid; its value is the owner's to choose
            self.assertEqual(c["source"], "config/audio_export.json")
            self.assertTrue(-12 <= c["global_gain_db"] <= 12)


class GlobalGainTests(unittest.TestCase):
    def test_quiet_normal_loud(self):
        quiet = ae.render(tone(0.05), dict(ae.EDIT_ZERO), global_gain_db=3.0)["stats"]   # peak -26 dBFS
        normal = ae.render(tone(0.5), dict(ae.EDIT_ZERO), global_gain_db=3.0)["stats"]   # peak -6 dBFS
        loud = ae.render(tone(0.8), dict(ae.EDIT_ZERO), global_gain_db=3.0)["stats"]     # peak -1.9 dBFS
        hot = ae.render(tone(0.95), dict(ae.EDIT_ZERO), global_gain_db=3.0)["stats"]     # peak -0.45 dBFS
        self.assertEqual((quiet["global_gain_applied_db"], quiet["global_gain_shortfall_db"]), (3.0, 0.0))
        self.assertEqual((normal["global_gain_applied_db"], normal["global_gain_shortfall_db"]), (3.0, 0.0))
        self.assertAlmostEqual(normal["output_peak_dbfs"], -6.02 + 3.0, delta=0.02)
        self.assertAlmostEqual(loud["global_gain_applied_db"], 0.94, delta=0.02)  # up to the -1 dBFS ceiling
        self.assertAlmostEqual(loud["global_gain_shortfall_db"], 2.06, delta=0.02)
        self.assertLessEqual(loud["output_peak_dbfs"], -1.0 + 0.01)
        self.assertTrue(any("global gain" in w for w in loud["warnings"]))
        self.assertEqual((hot["global_gain_applied_db"], hot["global_gain_shortfall_db"]), (0.0, 3.0))  # never attenuated
        for st in (quiet, normal, loud, hot):
            self.assertNotIn("limiter_max_reduction_db", st)   # no limiting or compression, ever
        neg = ae.render(tone(0.95), dict(ae.EDIT_ZERO), global_gain_db=-2.0)["stats"]
        self.assertEqual((neg["global_gain_applied_db"], neg["global_gain_shortfall_db"]), (-2.0, 0.0))

    def test_gain_is_linear_exact_and_applied_once(self):
        pcm = tone(0.25)
        out = ae.render(pcm, dict(ae.EDIT_ZERO), global_gain_db=6.0)
        x, y = ae.pcm16_to_float(pcm), ae.pcm16_to_float(out["pcm"])
        g = 10 ** (6 / 20)
        self.assertTrue(all(abs(b - a * g) <= 1 / 32768 for a, b in zip(x, y)))
        self.assertEqual(out["stats"]["total_gain_db"], 6.0)

    def test_the_global_gain_is_the_only_level_change(self):
        pcm = ae.float_to_pcm16(speech(1.5, amp=0.05))
        e = ae.normalize({"trim_start_s": 0.1}, SRC)
        r0 = ae.render(pcm, e, ref_lufs=-20.0, global_gain_db=0.0)["stats"]
        r3 = ae.render(pcm, e, ref_lufs=-20.0, global_gain_db=3.0)["stats"]
        self.assertAlmostEqual(r3["output_lufs"] - r0["output_lufs"], 3.0, delta=0.05)  # +3 once
        self.assertEqual((r0["total_gain_db"], r3["total_gain_db"]), (0.0, 3.0))       # nothing per line


class MigrationTests(AppTestBase):
    """Approved and draft mappings carrying speed / gain_db, as the 2026-10-09 editor saved them."""

    def setUp(self):
        super().setUp()
        doc = self.doc()
        base = {"trim_start_s": 0.1, "trim_end_s": 0, "gap_s": 0, "engine": "audio-edit/1",
                "for_source": SRC, "cuts": [{"start_s": 0.5, "end_s": 0.6}],
                "silences": [{"at_s": 0.3, "dur_s": 0.2}], "fade_in_ms": 10, "fade_out_ms": 0,
                "crossfade_ms": 20, "loudness": {"mode": "off", "offset_db": 0}}
        self.save(match={"status": "matched", "ce_line_refs": ["line_a#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_a#0"}]},
                  radio_effect={"needed": True}, subtitle={"source": "custom", "custom_text": "Hola"},
                  actions=[{"action": "approve", "field": "audio"}, {"action": "approve", "field": "subtitle"}])
        self.save(slot_id="es:Z10_020_cortana#0", loaded_sha256=self.sha(),
                  match={"status": "matched", "ce_line_refs": ["line_b#0"]},
                  audio={"source": "ce", "sources": [{"ce_line_ref": "line_b#0"}]})
        doc = self.doc()
        doc["slots"][0]["audio"]["edit"] = dict(base, speed=1.16, gain_db=0)                 # approved
        doc["slots"][1]["audio"]["edit"] = dict(base, for_source={"ce_line_ref": "line_b#0",
                                                                  "language": "Spanish(Mexico)"},
                                                speed=1, gain_db=-2.5)                          # draft
        self.path = self.root / "mappings/manual_mappings.json"
        # The file as an older app version left it: written by hand, before the database existed.
        (self.root / "mappings/manual_mappings.db").unlink(missing_ok=True)
        self.path.write_bytes(mapping_db.serialize(doc))
        self.before = self.path.read_bytes()
        self.local_before = (self.root / "mappings/manual_mappings.local.json").read_bytes()
        self.other = {p.name: p.read_bytes() for p in (self.root / "mappings").glob("*.json")
                      if p.name not in ("manual_mappings.json", "manual_mappings.local.json")}

    def test_store_migration_keeps_everything_but_the_two_fields(self):
        old = json.loads(self.before)
        new_sha, changes = mapping_store.reset_removed_edit_fields(self.path, hashlib.sha256(self.before).hexdigest())
        self.assertEqual([(c["mapping_id"], c["audio_status"], c["previous"]) for c in changes],
                         [("m-000001", "approved", {"speed": 1.16, "gain_db": 0}),
                          ("m-000002", "draft", {"speed": 1, "gain_db": -2.5})])
        self.assertEqual([c["non_default"] for c in changes], [{"speed": 1.16}, {"gain_db": -2.5}])
        new = json.loads(self.path.read_bytes())
        self.assertEqual(mapping_store.proof_only_removed_fields(old, new), [])
        for o, n in zip(old["slots"], new["slots"]):
            self.assertEqual({k: v for k, v in o["audio"]["edit"].items() if k not in ("speed", "gain_db")},
                             n["audio"]["edit"])                                    # trims, cuts, silences kept
            self.assertEqual({k: v for k, v in o["audio"].items() if k != "edit"},
                             {k: v for k, v in n["audio"].items() if k != "edit"})  # approval untouched
            self.assertEqual((o["subtitle"], o["radio_effect"], o["match"]), (n["subtitle"], n["radio_effect"], n["match"]))
        self.assertEqual(new["slots"][0]["audio"]["status"], "approved")           # not needs_rework
        self.assertTrue(list((self.root / "mappings/.history").glob("manual_mappings.*.json")))
        # idempotent
        self.assertEqual(mapping_store.reset_removed_edit_fields(self.path, new_sha), (None, []))
        # stale refusal
        with self.assertRaises(mapping_store.StaleError):
            mapping_store.reset_removed_edit_fields(self.path, hashlib.sha256(self.before).hexdigest())

    def test_proof_refuses_any_other_change(self):
        old = json.loads(self.before)
        new, _ = mapping_store.strip_removed_edit_fields(old)
        self.assertEqual(mapping_store.proof_only_removed_fields(old, new), [])
        for mutate in (lambda d: d["slots"][0]["audio"].update(status="needs_rework"),
                       lambda d: d["slots"][0]["audio"]["edit"]["cuts"].clear(),
                       lambda d: d["slots"][0]["radio_effect"].update(needed=False),
                       lambda d: d["slots"][1]["subtitle"].update(source="none"),
                       lambda d: d["slots"].pop()):
            bad = copy.deepcopy(new)
            mutate(bad)
            self.assertTrue(mapping_store.proof_only_removed_fields(old, bad))

    def test_cli_backup_report_idempotency_and_rollback(self):
        now = dt.datetime(2026, 10, 9, 12, 0, 0)
        dry, out = migrate_cli.migrate(self.root, write=False, now=now)
        self.assertIsNone(out)
        self.assertEqual((dry["affected"], dry["non_default"], dry["affected_by_status"]),
                         (2, 2, {"approved": 1, "draft": 1}))
        self.assertEqual(self.path.read_bytes(), self.before)                         # dry run writes nothing
        rep, out = migrate_cli.migrate(self.root, write=True, now=now)
        v = rep["verification"]
        self.assertTrue(all(x is True for x in v.values() if isinstance(x, bool)), v)
        self.assertEqual(v["approved_fingerprint_drift"], 0)
        # (the fixture's made-up level z10 fails the real mission-map schema; the mappings themselves are clean)
        self.assertEqual([e for e in rep["validator_error_samples"] if e["file"].endswith("manual_mappings.json")], [])
        b = json.loads((out / "backup/backup_manifest.json").read_text())
        self.assertTrue(b["verified"])
        self.assertEqual((out / "backup/manual_mappings.json").read_bytes(), self.before)
        self.assertEqual((out / "backup/manual_mappings.local.json").read_bytes(), self.local_before)
        self.assertEqual((self.root / "mappings/manual_mappings.local.json").read_bytes(), self.local_before)
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / "mappings").glob("*.json")
                          if p.name not in ("manual_mappings.json", "manual_mappings.local.json")}, self.other)
        (out / "report.json").write_text(json.dumps(rep), encoding="utf-8")
        self.assertIn("m-000001", migrate_cli.report_md(rep))
        migrated = self.path.read_bytes()
        again, out2 = migrate_cli.migrate(self.root, write=True, now=now + dt.timedelta(seconds=1))
        self.assertEqual((again["affected"], out2), (0, None))                         # idempotent
        self.assertEqual(self.path.read_bytes(), migrated)
        self.assertTrue(migrate_cli.rollback(self.root, out))                           # exact bytes back
        self.assertEqual(self.path.read_bytes(), self.before)
        with self.assertRaises(SystemExit):
            migrate_cli.rollback(self.root, out)                                        # not the migrated file now

    def test_validator_reports_unmigrated_fields_and_head_protection_accepts_the_removal(self):
        from common.project_validation import check_approved_protected
        old = json.loads(self.before)
        new, _ = mapping_store.strip_removed_edit_fields(old)
        self.assertEqual(check_approved_protected(old, new), [])   # HEAD still has them: allowed removal
        tampered = copy.deepcopy(new)
        tampered["slots"][0]["audio"]["edit"]["fade_in_ms"] = 99
        self.assertEqual([f["code"] for f in check_approved_protected(old, tampered)], ["approved_object_modified"])
