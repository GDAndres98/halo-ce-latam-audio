"""On-demand decoding of single MCC samples and CE lines to WAV (M4 playback).

Full-campaign catalogs are built without decoding (`build_mcc_catalog.py
--no-audio`, `build_ce_catalog.py`). The M4 UI asks for one recording at a
time. These helpers:

- reuse an existing eager decode (the M1b/M2 manifests) when it has the
  recording with status `ok`;
- otherwise decode exactly that recording into a cache under `work/`:
    work/mcc/audio/ondemand/<language>/<index>_<data_sha256[:12]>.wav
    work/ce/audio/ondemand/<language>/<media_id>.wav
  (the .wem source is kept byte-identical in work/ce/media/<language>/,
  as in M1b).

Sources are verified before decoding: the MCC bank copy must still hash to
the pin in work/mcc/build.json, and a CE .wem must hash to the catalog's
`wem_sha256`. Nothing is substituted from another language; a failure is an
error the caller shows. Reading game containers and running the decoder are
injected callables, so tests use fakes. Writes nothing outside `work/`.
"""
import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

from .ce_audio_export import OK, inspect_wav, sha256_file

MCC_LANG_FILE = {"spanish": "spanish.fsb", "english": "english.fsb"}


class AudioUnavailable(Exception):
    pass


def vgmstream_decoder(exe):
    """decode(src, out_wav, subsong=None) -> (ok, message) with the approved vgmstream-cli."""
    def decode(src, out, subsong=None):
        cmd = [str(exe), "-o", str(out)] + (["-s", str(subsong)] if subsong else []) + [str(src)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0, (res.stderr or res.stdout or "").strip()
    return decode


def _decode_to(path, decode, src, subsong=None):
    """Decode atomically to `path`; return inspect_wav facts or raise AudioUnavailable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    ok, msg = decode(src, tmp, subsong)
    if not ok or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise AudioUnavailable(f"decode failed: {(msg or 'no output')[:200]}")
    info = inspect_wav(tmp)
    if info["status"] != OK:
        tmp.unlink(missing_ok=True)
        raise AudioUnavailable(f"decoded audio is {info['status']}")
    os.replace(tmp, path)
    return info


class _Locks:
    def __init__(self):
        self._guard, self._locks = threading.Lock(), {}

    def __call__(self, key):
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())


class MccAudio:
    """WAVs for MCC bank samples, keyed by (language, bank index)."""

    def __init__(self, root, decode):
        self.root, self.decode = Path(root), decode
        self.work = self.root / "work" / "mcc"
        self._verified, self._eager, self._lock = {}, {}, _Locks()

    def _bank(self, language):
        """Pinned copy of the bank; verified once per process."""
        if language not in self._verified:
            build = json.loads((self.work / "build.json").read_text(encoding="utf-8"))
            pin = build["files"][MCC_LANG_FILE[language]]
            path = self.root / pin["copy"]
            if not path.is_file() or sha256_file(path) != pin["sha256"]:
                raise AudioUnavailable(f"{pin['copy']} is missing or no longer matches its pin")
            self._verified[language] = path
        return self._verified[language]

    def _eager_units(self, level):
        if level not in self._eager:
            p = self.work / "audio" / level / "manifest.json"
            units = json.loads(p.read_text(encoding="utf-8"))["units"] if p.is_file() else []
            self._eager[level] = {(u["language"], u["index"]): self.work / "audio" / level / u["wav_path"]
                                  for u in units if u.get("status") == OK}
        return self._eager[level]

    def cached(self, level, language, sample):
        p = self._eager_units(level).get((language, sample["index"]))
        if p and p.is_file():
            return p
        p = self.ondemand_path(language, sample)
        return p if p.is_file() else None

    def ondemand_path(self, language, sample):
        return self.work / "audio" / "ondemand" / language / f"{sample['index']}_{sample['data_sha256'][:12]}.wav"

    def wav(self, level, language, sample):
        """Path of a decoded WAV for this catalog sample, decoding it if needed."""
        hit = self.cached(level, language, sample)
        if hit:
            return hit
        out = self.ondemand_path(language, sample)
        with self._lock(str(out)):
            if not out.is_file():
                _decode_to(out, self.decode, self._bank(language), sample["subsong"])
        return out


class CeAudio:
    """WAVs for CE line media, keyed by (language, media_id)."""

    def __init__(self, root, decode, read_source):
        """read_source(language, wem_vfs_path) -> bytes | None (reads the installed pak, read-only)."""
        self.root, self.decode, self.read_source = Path(root), decode, read_source
        self.work = self.root / "work" / "ce"
        self._eager, self._lock = {}, _Locks()

    def _eager_units(self, mission):
        m = mission.lower()
        if m not in self._eager:
            p = self.work / "audio" / m / "manifest.json"
            units = json.loads(p.read_text(encoding="utf-8"))["units"] if p.is_file() else []
            self._eager[m] = {(u["language"], u["media_id"]): self.work / "audio" / m / u["wav_path"]
                              for u in units if u.get("status") == OK}
        return self._eager[m]

    def ondemand_path(self, language, media_id):
        return self.work / "audio" / "ondemand" / language / f"{media_id}.wav"

    def cached(self, mission, language, media):
        p = self._eager_units(mission).get((language, media["media_id"]))
        if p and p.is_file():
            return p
        p = self.ondemand_path(language, media["media_id"])
        return p if p.is_file() else None

    def wav(self, mission, language, media):
        """media: one catalog media item ({media_id, vfs_path, wem_sha256, ...})."""
        hit = self.cached(mission, language, media)
        if hit:
            return hit
        out = self.ondemand_path(language, media["media_id"])
        with self._lock(str(out)):
            if out.is_file():
                return out
            wem = self.work / "media" / language / f"{media['media_id']}.wem"
            if not (wem.is_file() and sha256_file(wem) == media["wem_sha256"]):
                data = self.read_source(language, media["vfs_path"])
                if data is None:
                    raise AudioUnavailable("media not found in the language pak")
                if hashlib.sha256(data).hexdigest() != media["wem_sha256"]:
                    raise AudioUnavailable("pak .wem no longer matches the catalog; rebuild the catalog")
                wem.parent.mkdir(parents=True, exist_ok=True)
                wem.write_bytes(data)
            _decode_to(out, self.decode, wem)
        return out


def ce_source_reader(oodle_dll=None):
    """Lazy read-only reader over the installed CE language paks (CEContext is built on first use)."""
    state = {"ctx": None, "paks": {}}
    lock = threading.Lock()

    def read(language, vfs_path):
        with lock:
            if state["ctx"] is None:
                from .asset_metadata import CEContext
                state["ctx"] = CEContext(oodle_dll=oodle_dll)
            ctx = state["ctx"]
            if language not in state["paks"]:
                state["paks"][language] = ctx.pak_for_wwise_language(language)
            pak = state["paks"][language]
            if not pak or vfs_path not in pak.files:
                return None
            return pak.read(vfs_path, ctx.oodle)
    return read
