"""M4 audio editor previews: the exact audio M6 would put in the bank for a recipe, before saving.

For one CE source WAV, one recipe and the global export gain (common/audio_edit, common/export_config)
it renders, with the same functions the M6 build calls (audio_pipeline.render_edited /
to_mcc_pcm + encode_for_mcc):
  edited.wav   the 44.1 kHz PCM handed to the encoder ("pre-codec")
  encoded.wav  that PCM encoded with the MCC CELT profile and decoded by the same libcelt, codec delay
               removed: what MCC plays (M6 verifies vgmstream's decode of the bank equals this decode)
Results are cached in work/m4/preview/<key>/ (key = hash of render engine, source PCM, recipe,
reference loudness and global gain). Originals are only read. Nothing here touches mappings.
"""
import hashlib
import json
import os
import re
import threading
from pathlib import Path

from . import audio_edit
from .audio_pipeline import codec_roundtrip, sha256_file, to_mcc_pcm

KINDS = ("edited", "encoded")
KEY_RE = re.compile(r"^[0-9a-f]{24}$")


class EditPreview:
    def __init__(self, root, ffmpeg, celt_factory):
        """celt_factory() -> a Celt011 (created on first use; the DLL is loaded once)."""
        self.dir = Path(root) / "work" / "m4" / "preview"
        self.ffmpeg, self._celt_factory, self._celt = ffmpeg, celt_factory, None
        self._lock = threading.Lock()  # one render at a time: libcelt and ffmpeg calls stay sequential
        self._pcm, self._ref = {}, {}

    def _source(self, wav):
        k = (str(wav), sha256_file(wav))
        if k not in self._pcm:
            if len(self._pcm) > 64:
                self._pcm.clear()
            self._pcm[k] = to_mcc_pcm(self.ffmpeg, wav, 1)
        return self._pcm[k]

    def reference_lufs(self, mcc_wav):
        k = (str(mcc_wav), sha256_file(mcc_wav))
        if k not in self._ref:
            self._ref[k] = audio_edit.wav_loudness(mcc_wav)
        return self._ref[k]

    def path(self, key, kind):
        if not KEY_RE.match(key or "") or kind not in KINDS:
            raise ValueError("bad preview key or kind")
        return self.dir / key / f"{kind}.wav"

    def render(self, src_wav, edit, ref_lufs, global_gain_db, level_mode="global_gain", clicks=None):
        """-> {"key", "stats"}; writes edited.wav / encoded.wav. Raises audio_edit.EditError.
        Same processing as M6 for every line: recipe, then the build-level level mode (global export gain,
        or match Spain with ref_lufs as the target)."""
        with self._lock:
            pcm = self._source(src_wav)
            key = hashlib.sha256(json.dumps({"engine": audio_edit.RENDER_ENGINE, "pcm": hashlib.sha256(pcm).hexdigest(),
                                             "edit": edit, "ref": ref_lufs, "global_gain_db": global_gain_db,
                                             "level_mode": level_mode,
                                             "clicks": clicks["sha256"] if clicks else None},
                                            sort_keys=True).encode()).hexdigest()[:24]
            out = self.dir / key
            if (out / "stats.json").is_file():
                return {"key": key, "stats": json.loads((out / "stats.json").read_text(encoding="utf-8"))}
            r = audio_edit.render(pcm, edit, ref_lufs=ref_lufs, global_gain_db=global_gain_db, level_mode=level_mode,
                                  clicks=clicks)
            edited, stats = r["pcm"], r["stats"]
            if self._celt is None:
                self._celt = self._celt_factory()
            encoded, enc = codec_roundtrip(self._celt, edited)
            stats["encoded_sample_count"] = enc["sample_count"]
            stats["encoded_s"] = round(enc["sample_count"] / audio_edit.SAMPLE_RATE, 3)
            tmp = out.with_name(out.name + ".tmp")
            tmp.mkdir(parents=True, exist_ok=True)
            audio_edit.write_wav(tmp / "edited.wav", edited)
            audio_edit.write_wav(tmp / "encoded.wav", encoded)
            (tmp / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
            try:
                os.replace(tmp, out)
            except OSError:  # another render of the same key won the race
                pass
            return {"key": key, "stats": stats}
