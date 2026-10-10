"""M-SYS: discovery of the Campaign Evolved systemic voice sets (Audio/Systemic/<character>/) as the
pseudo-mission SYS. Fake container listing only.

Run: python -m unittest discover -s tests
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("build_ce_catalog", ROOT / "scripts/catalog/build_ce_catalog.py")
bcc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bcc)

A = "Meteorite/Content/Audio/"


class FakeCtx:
    def __init__(self, paths):
        self.paths = paths

    def list_packages(self, prefix):
        return [p for p in self.paths if p.startswith(prefix)]


PATHS = [A + "Systemic/HAC_Systemic.uasset",                                   # category, not a voice set
         A + "Systemic/vo_sys_grunt/vo_sys_default_01contact_ambush_grunt.uasset",
         A + "Systemic/vo_sys_grunt/vo_sys_default_02combat_taunt_grunt.uasset",
         A + "Systemic/VO_SYS_Williams/vo_sys_default_01contact_ambush_williams.uasset",
         A + "scripted/VO_SCR_M01PILLAROFAUTUMN/VO_SCR_M01_00460_CryoTech.uasset",
         A + "cinematic/vo_cin_m01pillarofautumn/vo_cin_m01_cin01_sc02_bridge_00010_keyes.uasset"]


class SystemicDiscoveryTests(unittest.TestCase):
    def test_every_character_folder_and_nothing_else(self):
        f = bcc.discover_voice_folders(FakeCtx(PATHS), bcc.SYSTEMIC)
        self.assertEqual(sorted(f), [A + "Systemic/VO_SYS_Williams", A + "Systemic/vo_sys_grunt"])
        self.assertEqual(len(f[A + "Systemic/vo_sys_grunt"]), 2)
        self.assertNotIn(A + "Systemic/HAC_Systemic.uasset", [p for v in f.values() for p in v])

    def test_missions_unchanged_and_sys_is_not_a_mission(self):
        ctx = FakeCtx(PATHS)
        self.assertEqual(bcc.discover_missions(ctx), ["M01"])
        self.assertEqual(sorted(bcc.discover_voice_folders(ctx, "M01")),
                         [A + "cinematic/vo_cin_m01pillarofautumn", A + "scripted/VO_SCR_M01PILLAROFAUTUMN"])

    def test_family_and_mission_are_derived_from_the_path(self):
        from common.ce_catalog import classify
        c = classify(A + "Systemic/vo_sys_grunt/vo_sys_default_01contact_ambush_grunt.uasset")
        self.assertEqual((c["family"], c["mission"], c["folder"]), ("systemic", None, "vo_sys_grunt"))


if __name__ == "__main__":
    unittest.main()
