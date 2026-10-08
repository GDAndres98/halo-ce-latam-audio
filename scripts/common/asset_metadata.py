"""Shared context + evidence helpers for Campaign Evolved metadata work.

`CEContext` opens the game's containers strictly read-only (paths from
.env), loads the .usmap from USMAP_FILEC and the Oodle DLL bundled with
FModel. Evidence values follow docs/dialogue-catalog-design.md §3.3.
"""
import hashlib
from pathlib import Path

from .env import load_env, require_path
from .iostore import IoStore
from .oodle import FMODEL_RELATIVE_DLL, Oodle
from .pak import PakFile
from .usmap import Usmap
from .zen import ZenPackage, load_script_objects

EXPLICIT = "explicit"
EXPLICIT_INDEX = "explicit:index"
UNRESOLVED = "unresolved"

# Wwise language -> UE culture used by the Subtitles localization target.
WWISE_TO_CULTURE = {"English(US)": "en", "Spanish(Mexico)": "es-MX", "Spanish(Spain)": "es-ES"}

DEFAULT_FMODEL_DIR = Path.home() / "Downloads" / "858461d19e29803479555059acb59a03a0986de8"


def derived(rule):
    return f"derived:{rule}"


def fnv1_32(name):
    """Wwise ShortID: 32-bit FNV-1 over the lowercased ASCII name."""
    h = 2166136261
    for c in name.lower().encode("ascii"):
        h = ((h * 16777619) & 0xFFFFFFFF) ^ c
    return h


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def hop(name, evidence, **details):
    return {"hop": name, "evidence": evidence, **details}


class CEContext:
    def __init__(self, env_path=None, oodle_dll=None):
        self.env, problems = load_env(env_path)
        if problems:
            raise SystemExit("; ".join(problems))
        self.remake = require_path(self.env, "HALO_REMAKE_FOLDER", "dir")
        self.paks = self.remake / "Meteorite" / "Content" / "Paks"
        self.usmap_path = require_path(self.env, "USMAP_FILEC", "file")
        dll = Path(oodle_dll) if oodle_dll else DEFAULT_FMODEL_DIR / FMODEL_RELATIVE_DLL
        if not dll.is_file():
            raise SystemExit(f"Oodle DLL not found at {dll}")
        self.oodle = Oodle(dll)
        self.usmap = Usmap(self.usmap_path.read_bytes())
        g = IoStore(self.paks / "global.utoc")
        self.script_objects = load_script_objects(g.read_chunk(0, self.oodle))
        self._stores = None
        self._paks = {}

    @property
    def stores(self):
        if self._stores is None:
            self._stores = [IoStore(p) for p in sorted(self.paks.glob("pakchunk*-Windows.utoc"))
                            if p.stat().st_size > 0]
            self._stores = [s for s in self._stores if s.files]
        return self._stores

    def pak(self, name):
        if name not in self._paks:
            self._paks[name] = PakFile(self.paks / name)
        return self._paks[name]

    def find_package(self, vfs_path):
        """Locate a package by its VFS path ('Meteorite/Content/...uasset'), case-insensitive."""
        want = vfs_path.lower()
        for s in self.stores:
            for p, idx in s.files.items():
                if p.lower() == want:
                    return s, p, idx
        return None

    @staticmethod
    def game_path_to_vfs(game_path):
        """'/Game/Audio/x/y' -> 'Meteorite/Content/Audio/x/y.uasset' (strips '.Object' suffix)."""
        p = game_path.split(".")[0]
        if not p.startswith("/Game/"):
            raise ValueError(f"not a /Game path: {game_path}")
        return "Meteorite/Content/" + p[len("/Game/"):] + ".uasset"

    def load_package(self, vfs_path):
        hit = self.find_package(vfs_path)
        if not hit:
            return None
        store, path, idx = hit
        data = store.read_chunk(idx, self.oodle)
        return {"container": store.utoc.name, "vfs_path": path,
                "package": ZenPackage(data, self.script_objects, self.usmap)}

    def pak_for_wwise_language(self, language):
        """Find the language pak by looking for its directory in each pakchunkN index."""
        for p in sorted(self.paks.glob("pakchunk*-Windows.pak")):
            if p.stat().st_size < 1024:
                continue
            pf = self.pak(p.name)
            if any(f.startswith(f"Meteorite/Content/WwiseAudio/{language}/") for f in pf.files):
                return pf
        return None
