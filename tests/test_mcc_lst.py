"""The .lst.bin writer (common/mcc_lst.build_lst): the exact inverse of parse_lst. The shipped Spanish index is
checked when its pinned copy is present (git-ignored); otherwise synthetic data only.

Run: python -m unittest tests.test_mcc_lst
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common.mcc_lst import build_lst, check_ranges, parse_lst  # noqa: E402

SHIPPED = ROOT / "reference-audio/stage1/lst/sounds_dialogs_spanish.lst.bin"


class LstWriterTests(unittest.TestCase):
    def test_round_trip(self):
        recs = [(r"sound\dialog\a10\a10_010_cryotech", 0, 1), (r"sound\dialog\grunt\death_violent", 1, 4)]
        data = build_lst(1, recs)
        self.assertEqual(parse_lst(data), {"version": 1, "records": recs})
        self.assertTrue(check_ranges(recs, 5)["total_matches_bank"])

    @unittest.skipUnless(SHIPPED.is_file(), "pinned Spanish index copy not present")
    def test_reproduces_the_shipped_index_byte_for_byte(self):
        data = SHIPPED.read_bytes()
        p = parse_lst(data)
        self.assertEqual(build_lst(p["version"], p["records"]), data)


if __name__ == "__main__":
    unittest.main()
