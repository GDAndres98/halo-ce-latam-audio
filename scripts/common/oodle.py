"""In-memory Oodle decompression via the oodle-data-shared.dll that FModel
already downloaded (approved for read-only use, see docs). Decompression
only -- no compression entry point is ever called.
"""
import ctypes
from pathlib import Path

FMODEL_RELATIVE_DLL = Path("Output") / ".data" / "oodle-data-shared.dll"


class Oodle:
    def __init__(self, dll_path):
        self.dll_path = Path(dll_path)
        self._lib = ctypes.WinDLL(str(self.dll_path))
        fn = self._lib.OodleLZ_Decompress
        fn.restype = ctypes.c_int64
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_int64, ctypes.c_int]
        self._fn = fn

    def decompress(self, src, raw_size):
        out = ctypes.create_string_buffer(raw_size)
        n = self._fn(src, len(src), out, raw_size, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if n != raw_size:
            raise ValueError(f"OodleLZ_Decompress returned {n}, expected {raw_size}")
        return out.raw
