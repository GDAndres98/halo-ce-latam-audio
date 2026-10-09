"""CELT 0.11.0 encode/decode via the libcelt-0110.dll bundled with the approved vgmstream r2117.

That DLL is the decoder vgmstream uses for FMOD FSB5 CELT (bitstream 0x80000010) and also exports
the encoder (symbols suffixed `_0110`). MCC's dialogue banks use a custom CELT mode at 44,100 Hz with
512-sample frames and constant 370-byte packets (mono) / 464-byte packets (stereo); each packet is
wrapped in an FMOD frame: sync b"\\x17\\xc3\\x0d\\xf3" + u32 LE packet size + packet
(docs/b2-audio-research.md §1.3/1.5).

Pure ctypes; nothing is installed. PCM is 16-bit little-endian, interleaved.
"""
import ctypes
import struct
from pathlib import Path

DEFAULT_DLL = Path("D:/Tools/vgmstream-r2117/libcelt-0110.dll")
SAMPLE_RATE = 44100
FRAME_SAMPLES = 512
PACKET_BYTES = {1: 370, 2: 464}  # as in every MCC dialogue sample
SYNC = b"\x17\xc3\x0d\xf3"

# CELT 0.11 encoder ctl requests (libcelt/celt.h); verified: both return 0, an unknown request -5.
CELT_SET_COMPLEXITY_REQUEST = 2
CELT_SET_PREDICTION_REQUEST = 4
# Encoder settings. "fmod" reproduces the frame profile of every MCC dialogue packet (1.67 M frames
# parsed, docs/b2-audio-research.md §5.8): intra-coded (no inter-frame prediction), no transient
# short blocks, no post-filter. "default" is libcelt's default (inter-frame prediction, transients):
# it crashed MCC in E2 and must not be used for game banks.
PROFILES = {"fmod": {CELT_SET_PREDICTION_REQUEST: 0, CELT_SET_COMPLEXITY_REQUEST: 0}, "default": {}}


class CeltError(RuntimeError):
    pass


class Celt011:
    """One CELT 0.11 custom mode (44.1 kHz, 512-sample frames) plus encoder/decoder factories."""

    def __init__(self, dll_path=DEFAULT_DLL):
        self.lib = ctypes.CDLL(str(dll_path))
        L, vp, ci, pci = self.lib, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        for name, res, args in (
                ("celt_mode_create_0110", vp, [ctypes.c_int32, ci, pci]),
                ("celt_mode_destroy_0110", None, [vp]),
                ("celt_encoder_create_custom_0110", vp, [vp, ci, pci]),
                ("celt_encoder_destroy_0110", None, [vp]),
                ("celt_encoder_ctl_0110", ci, [vp, ci, ci]),
                ("celt_encode_0110", ci, [vp, ctypes.POINTER(ctypes.c_int16), ci, ctypes.c_char_p, ci]),
                ("celt_decoder_create_custom_0110", vp, [vp, ci, pci]),
                ("celt_decoder_destroy_0110", None, [vp]),
                ("celt_decode_0110", ci, [vp, ctypes.c_char_p, ci, ctypes.POINTER(ctypes.c_int16), ci])):
            fn = getattr(L, name)
            fn.restype, fn.argtypes = res, args
        err = ctypes.c_int(0)
        self.mode = L.celt_mode_create_0110(SAMPLE_RATE, FRAME_SAMPLES, ctypes.byref(err))
        if not self.mode or err.value:
            raise CeltError(f"celt_mode_create failed ({err.value})")

    def close(self):
        if self.mode:
            self.lib.celt_mode_destroy_0110(self.mode)
            self.mode = None

    def encode(self, pcm, channels=1, packet_bytes=None, profile="fmod"):
        """16-bit PCM bytes -> list of CBR packets (last frame zero-padded). Returns (packets, frames)."""
        packet_bytes = packet_bytes or PACKET_BYTES[channels]
        err = ctypes.c_int(0)
        enc = self.lib.celt_encoder_create_custom_0110(self.mode, channels, ctypes.byref(err))
        if not enc or err.value:
            raise CeltError(f"celt_encoder_create_custom failed ({err.value})")
        for request, value in PROFILES[profile].items():
            rc = self.lib.celt_encoder_ctl_0110(enc, request, value)
            if rc != 0:
                self.lib.celt_encoder_destroy_0110(enc)
                raise CeltError(f"celt_encoder_ctl({request}, {value}) failed ({rc})")
        frame_bytes = FRAME_SAMPLES * channels * 2
        frames = -(-len(pcm) // frame_bytes)
        pcm = pcm + b"\0" * (frames * frame_bytes - len(pcm))
        out = ctypes.create_string_buffer(packet_bytes)
        packets = []
        try:
            for k in range(frames):
                chunk = (ctypes.c_int16 * (FRAME_SAMPLES * channels)).from_buffer_copy(
                    pcm[k * frame_bytes:(k + 1) * frame_bytes])
                n = self.lib.celt_encode_0110(enc, chunk, FRAME_SAMPLES, out, packet_bytes)
                if n < 0:
                    raise CeltError(f"celt_encode failed ({n}) at frame {k}")
                packets.append(out.raw[:n])
        finally:
            self.lib.celt_encoder_destroy_0110(enc)
        return packets, frames

    def decode(self, packets, channels=1):
        """Packets -> 16-bit PCM bytes (FRAME_SAMPLES per packet)."""
        err = ctypes.c_int(0)
        dec = self.lib.celt_decoder_create_custom_0110(self.mode, channels, ctypes.byref(err))
        if not dec or err.value:
            raise CeltError(f"celt_decoder_create_custom failed ({err.value})")
        buf = (ctypes.c_int16 * (FRAME_SAMPLES * channels))()
        out = bytearray()
        try:
            for p in packets:
                n = self.lib.celt_decode_0110(dec, p, len(p), buf, FRAME_SAMPLES)
                if n < 0:
                    raise CeltError(f"celt_decode failed ({n})")
                out += bytes(buf)
        finally:
            self.lib.celt_decoder_destroy_0110(dec)
        return bytes(out)


def fmod_frames(packets):
    """Wrap CELT packets as an FMOD FSB5 CELT stream (sync + u32 size + packet per frame)."""
    return b"".join(SYNC + struct.pack("<I", len(p)) + p for p in packets)


def split_fmod_frames(stream):
    """FMOD CELT stream -> list of packets."""
    p, out = 0, []
    while p < len(stream):
        if stream[p:p + 4] != SYNC:
            raise ValueError(f"bad CELT sync at {p}")
        n = struct.unpack_from("<I", stream, p + 4)[0]
        out.append(stream[p + 8:p + 8 + n])
        p += 8 + n
    return out


def profile_violations(packets):
    """Indices of packets outside MCC's observed CELT profile (post-filter, transient, or a non-silent
    frame that is not intra-coded). An empty list matches every original MCC dialogue packet."""
    from .celt_header import frame_flags
    bad = []
    for k, p in enumerate(packets):
        f = frame_flags(p)
        if f["postfilter"] or f["transient"] or (not f["silence"] and not f["intra"]):
            bad.append(k)
    return bad
