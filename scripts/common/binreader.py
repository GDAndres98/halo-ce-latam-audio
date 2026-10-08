"""Little-endian cursor over a bytes object, with Unreal FString support."""
import struct


class Reader:
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def _unpack(self, fmt):
        v = struct.unpack_from("<" + fmt, self.data, self.pos)
        self.pos += struct.calcsize("<" + fmt)
        return v[0]

    def u8(self): return self._unpack("B")
    def i8(self): return self._unpack("b")
    def u16(self): return self._unpack("H")
    def i16(self): return self._unpack("h")
    def u32(self): return self._unpack("I")
    def i32(self): return self._unpack("i")
    def u64(self): return self._unpack("Q")
    def i64(self): return self._unpack("q")
    def f32(self): return self._unpack("f")
    def f64(self): return self._unpack("d")

    def bytes(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError(f"read of {n} bytes at {self.pos} past end ({len(self.data)})")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def fstring(self):
        """Unreal FString: int32 length (negative = UTF-16 code units), NUL-terminated."""
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            return self.bytes(-2 * n).decode("utf-16-le").rstrip("\0")
        return self.bytes(n).decode("utf-8", errors="replace").rstrip("\0")

    def remaining(self):
        return len(self.data) - self.pos
