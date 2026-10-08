"""Synthetic tests for the B1 baseline helper's text comparison (no game data)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "discovery"))
import b1_baseline as b  # noqa: E402

TEXTS = {
    "t1": {"SU_Halo1": "Hola, amigo. Toma esto ahora.", "SP_Halo1": "Hola, amigo. Coged esto ya."},
    "t2": {"SU_Halo1": "Jefe Maestro, venga.", "SP_Halo1": "jefe maestro, venga."},
}


class B1BaselineTests(unittest.TestCase):
    def test_distinguishing_words_ignore_case_and_punctuation(self):
        self.assertEqual(b.distinguishing_words(*TEXTS["t2"].values()), ([], []))
        only_su, only_sp = b.distinguishing_words(*TEXTS["t1"].values())
        self.assertEqual(only_su, ["toma", "ahora"])
        self.assertEqual(only_sp, ["coged", "ya"])

    def test_match_picks_table_and_line(self):
        tag, _, verdict = b.match("hola amigo toma esto ahora", TEXTS)
        self.assertEqual((tag, verdict), ("t1", "SU_Halo1"))
        tag, _, verdict = b.match("Hola amigo, coged esto ya", TEXTS)
        self.assertEqual((tag, verdict), ("t1", "SP_Halo1"))

    def test_case_only_difference_is_inconclusive(self):
        _, scores, verdict = b.match("Jefe Maestro, venga.", TEXTS)
        self.assertEqual(verdict, "inconclusive")
        self.assertEqual(scores["SU_Halo1"], scores["SP_Halo1"])

    def test_unrelated_text_is_inconclusive(self):
        self.assertEqual(b.match("algo completamente distinto", TEXTS)[2], "inconclusive")


if __name__ == "__main__":
    unittest.main()
