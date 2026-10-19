"""m6_install.py against a throw-away game folder: a combined audio + subtitle build installed as one operation,
restored, and the automatic restore after a failure part-way through. Fake file contents only; the real MCC
install and work/ are never touched (the module's repository root is pointed at a temporary folder).

Run: python -m unittest tests.test_m6_install
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import m6_install  # noqa: E402

FILES = {"halo1/sound/pc/sounds_dialogs_spanish.fsb": (b"original bank", b"candidate bank, longer"),
         "Data/ui/localization/SU_Halo1.bin": (b"original SU", b"candidate SU"),
         "Data/ui/localization/SP_Halo1.bin": (b"original SP", b"candidate SP!")}
sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        self.game = base / "steam" / "steamapps" / "common" / "Halo The Master Chief Collection"
        for rel, (orig, _) in FILES.items():
            (self.game / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.game / rel).write_bytes(orig)
        (self.game / "halo1/sound/pc/other.fsb").write_bytes(b"not part of the build")
        (base / "steam/steamapps/appmanifest_976730.acf").write_text(
            '"AppState"\n{\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"Halo The Master Chief Collection"\n'
            '\t"buildid"\t\t"19905945"\n}\n')
        build = self.repo / "work/m6/combo"
        build.mkdir(parents=True)
        install_files = []
        for rel, (orig, cand) in FILES.items():
            (build / Path(rel).name).write_bytes(cand)
            install_files.append({"install_rel": rel, "original_sha256": sha(orig),
                                  "candidate": f"work/m6/combo/{Path(rel).name}", "candidate_sha256": sha(cand)})
        (build / "build_manifest.json").write_text(json.dumps({"kind": "both", "levels": ["z10"],
                                                               "install_files": install_files, "slots": []}))
        (build / "validation_report.json").write_text(json.dumps({"ok": True}))
        self.history = base / "history.jsonl"
        patches = [mock.patch.object(m6_install, "REPO_ROOT", self.repo),
                   mock.patch.object(m6_install, "stale_check", lambda b: None),  # tested in test_m6_subtitles
                   mock.patch.object(m6_install, "running_game_processes", lambda: [])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.backups, self.state = base / "backup", base / "state"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, fail_after=None):
        b = m6_install.Build("combo", self.game, self.backups, self.state, self.history)
        b.fail_after = fail_after
        return b

    def installed(self):
        return {rel: (self.game / rel).read_bytes() for rel in FILES}

    def events(self):
        return [json.loads(x) for x in self.history.read_text(encoding="utf-8").splitlines()]

    def test_install_and_restore_all_three_files_together(self):
        m6_install.preflight(self.build())
        m6_install.install(self.build())
        self.assertEqual(self.installed(), {rel: cand for rel, (_, cand) in FILES.items()})
        self.assertEqual((self.game / "halo1/sound/pc/other.fsb").read_bytes(), b"not part of the build")
        m6_install.rollback(self.build())
        self.assertEqual(self.installed(), {rel: orig for rel, (orig, _) in FILES.items()})
        rb = json.loads((self.state / "rollback.json").read_text())
        self.assertEqual(rb["hashed_files_changed"], [])
        self.assertEqual([(e["action"], e["result"]) for e in self.events()], [("install", "ok"), ("rollback", "ok")])
        for rel, (orig, _) in FILES.items():
            self.assertEqual((self.backups / "19905945" / rel).read_bytes(), orig)   # backups are kept

    def test_a_failure_part_way_restores_every_original(self):
        for n in (1, 2):
            m6_install.preflight(self.build())
            with self.assertRaises(SystemExit) as cm:
                m6_install.install(self.build(fail_after=n))
            self.assertIn("originals restored and verified", str(cm.exception))
            self.assertEqual(self.installed(), {rel: orig for rel, (orig, _) in FILES.items()}, n)
        failed = [e for e in self.events() if e["result"] == "failed"]
        self.assertEqual(len(failed), 2)
        self.assertTrue(all(e["rolled_back"] for e in failed))
        self.assertTrue(all(f["installed_sha256"] == f["original_sha256"] for e in failed for f in e["files"]))

    def test_refuses_a_modified_install_or_a_changed_candidate(self):
        (self.game / "Data/ui/localization/SP_Halo1.bin").write_bytes(b"someone else's mod")
        with self.assertRaises(SystemExit) as cm:
            m6_install.check(self.build())
        self.assertIn("not the pinned original", str(cm.exception))
        (self.game / "Data/ui/localization/SP_Halo1.bin").write_bytes(FILES["Data/ui/localization/SP_Halo1.bin"][0])
        (self.repo / "work/m6/combo/SU_Halo1.bin").write_bytes(b"tampered")
        with self.assertRaises(SystemExit) as cm:
            m6_install.check(self.build())
        self.assertIn("does not match the manifest", str(cm.exception))
        self.assertEqual(self.installed(), {rel: orig for rel, (orig, _) in FILES.items()})

    def test_an_unvalidated_build_is_refused(self):
        (self.repo / "work/m6/combo/validation_report.json").write_text(json.dumps({"ok": False}))
        with self.assertRaises(SystemExit):
            m6_install.check(self.build())


class ExperimentTests(unittest.TestCase):
    """The permutation experiment (scripts/discovery/perm_experiment.py): the Spanish bank and its sound index
    (.lst.bin) are one unit; a bank-only build refuses to go on top of a changed index."""
    BANK, LST = m6_install.BANK_REL, m6_install.LST_REL

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        self.game = base / "steam" / "steamapps" / "common" / "Halo The Master Chief Collection"
        self.orig = {self.BANK: b"original bank", self.LST: b"original index"}
        self.cand = {self.BANK: b"bank with 2 more takes", self.LST: b"index, count 2 -> 4"}
        for rel, data in self.orig.items():
            (self.game / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.game / rel).write_bytes(data)
        for t in ("SU", "SP"):
            (self.game / f"Data/ui/localization/{t}_Halo1.bin").parent.mkdir(parents=True, exist_ok=True)
            (self.game / f"Data/ui/localization/{t}_Halo1.bin").write_bytes(t.encode())
        (base / "steam/steamapps/appmanifest_976730.acf").write_text(
            '"AppState"\n{\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"Halo The Master Chief Collection"\n'
            '\t"buildid"\t\t"19905945"\n}\n')
        self.make_build("exp", "experiment", [self.BANK, self.LST])
        self.make_build("audio", "audio", [self.BANK])
        real_stale = m6_install.stale_check
        patches = [mock.patch.object(m6_install, "REPO_ROOT", self.repo),
                   mock.patch.object(m6_install, "LST_PIN", sha(self.orig[self.LST])),
                   mock.patch.object(m6_install, "running_game_processes", lambda: []),
                   # the experiment's own check runs for real; an audio build's needs catalogs (test_m6_subtitles)
                   mock.patch.object(m6_install, "stale_check",
                                     lambda b: real_stale(b) if b.kind == "experiment" else None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.base = base

    def make_build(self, name, kind, rels):
        d = self.repo / f"work/m6/{name}"
        d.mkdir(parents=True)
        files = []
        for rel in rels:
            (d / Path(rel).name).write_bytes(self.cand[rel] + name.encode())
            files.append({"install_rel": rel, "original_sha256": sha(self.orig[rel]),
                          "candidate": f"work/m6/{name}/{Path(rel).name}",
                          "candidate_sha256": sha(self.cand[rel] + name.encode())})
        (d / "build_manifest.json").write_text(json.dumps({"kind": kind, "levels": ["grunt"], "install_files": files,
                                                           "slots": []}))
        (d / "validation_report.json").write_text(json.dumps({"ok": True}))

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, name, fail_after=None):
        b = m6_install.Build(name, self.game, self.base / "backup", self.base / f"state_{name}", self.base / "h.jsonl")
        b.fail_after = fail_after
        return b

    def installed(self):
        return {rel: (self.game / rel).read_bytes() for rel in self.orig}

    def test_bank_and_index_install_and_restore_together(self):
        m6_install.preflight(self.build("exp"))
        m6_install.install(self.build("exp"))
        self.assertEqual(self.installed(), {r: self.cand[r] + b"exp" for r in self.orig})
        m6_install.rollback(self.build("exp"))
        self.assertEqual(self.installed(), self.orig)

    def test_a_failure_after_the_bank_restores_the_bank_too(self):
        m6_install.preflight(self.build("exp"))
        with self.assertRaises(SystemExit) as cm:
            m6_install.install(self.build("exp", fail_after=1))
        self.assertIn("originals restored and verified", str(cm.exception))
        self.assertEqual(self.installed(), self.orig)

    def test_a_bank_only_build_refuses_a_changed_index(self):
        m6_install.preflight(self.build("exp"))
        m6_install.install(self.build("exp"))
        (self.game / self.BANK).write_bytes(self.orig[self.BANK])  # only the bank put back (e.g. by hand)
        with self.assertRaises(SystemExit) as cm:
            m6_install.check(self.build("audio"))
        self.assertIn("is not the original", str(cm.exception))
        m6_install.rollback(self.build("exp"))  # restoring the experiment puts both back
        self.assertEqual(self.installed(), self.orig)
        m6_install.check(self.build("audio"))  # now allowed


if __name__ == "__main__":
    unittest.main()
