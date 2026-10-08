"""Read-only UE .pak (v10/v11, path-hash index era) reader.

Supports listing files and reading one entry (uncompressed or Oodle
block-compressed). Refuses encrypted indexes or entries -- this project
never handles encryption keys.
"""
import struct
from pathlib import Path

from .binreader import Reader

PAK_MAGIC = 0x5A6F12E1
FOOTER_SIZE = 16 + 1 + 4 + 4 + 8 + 8 + 20 + 5 * 32  # v8+ footer, 5 compression names


class EncryptedError(RuntimeError):
    pass


def parse_footer(tail):
    """Parse the fixed-size footer (last FOOTER_SIZE bytes of a pak)."""
    if len(tail) != FOOTER_SIZE:
        raise ValueError("bad footer size")
    key_guid = tail[0:16]
    encrypted_index = tail[16]
    magic, version, index_offset, index_size = struct.unpack_from("<IiQQ", tail, 17)
    if magic != PAK_MAGIC:
        raise ValueError(f"not a pak footer (magic=0x{magic:08x})")
    names = [tail[61 + 32 * i:61 + 32 * (i + 1)].split(b"\0")[0].decode("ascii") for i in range(5)]
    return {
        "key_guid_is_zero": key_guid == bytes(16),
        "encrypted_index": bool(encrypted_index),
        "version": version,
        "index_offset": index_offset,
        "index_size": index_size,
        "compression_methods": [n for n in names if n],
    }


def decode_entry(enc, off):
    """Decode one bit-packed FPakEntry from the encoded entries blob (v10+)."""
    r = Reader(enc, off)
    v = r.u32()
    comp_block_size = (v & 0x3F) << 11
    block_count = (v >> 6) & 0xFFFF
    encrypted = bool(v & (1 << 22))
    method = (v >> 23) & 0x3F
    offset = r.u32() if v & (1 << 31) else r.u64()
    usize = r.u32() if v & (1 << 30) else r.u64()
    size = (r.u32() if v & (1 << 29) else r.u64()) if method else usize
    # Block sizes follow only when there is more than one block (or encryption).
    blocks = []
    header_size = 8 + 8 + 8 + 4 + 20 + 1 + 4 + (4 + 16 * block_count if method else 0)
    if method:
        if block_count == 1 and not encrypted:
            blocks = [(header_size, header_size + size)]
        else:
            start = header_size
            for _ in range(block_count):
                bsz = r.u32()
                blocks.append((start, start + bsz))
                start += bsz  # alignment only applies when encrypted (refused below)
    return {
        "offset": offset, "size": size, "usize": usize, "method": method,
        "encrypted": encrypted, "block_size": comp_block_size or usize,
        "blocks": blocks, "header_size": header_size,
    }


class PakFile:
    def __init__(self, path):
        self.path = Path(path)
        with open(self.path, "rb") as f:
            f.seek(-FOOTER_SIZE, 2)
            self.footer = parse_footer(f.read(FOOTER_SIZE))
            if self.footer["encrypted_index"]:
                raise EncryptedError(f"{self.path.name}: index is encrypted -- stopping (project rule)")
            f.seek(self.footer["index_offset"])
            idx = f.read(self.footer["index_size"])
            r = Reader(idx)
            self.mount_point = r.fstring()
            self.entry_count = r.i32()
            r.u64()  # path hash seed
            if r.i32():
                r.i64(); r.i64(); r.bytes(20)
            if not r.i32():
                raise ValueError("pak has no full directory index")
            fdi_off, fdi_size = r.i64(), r.i64()
            r.bytes(20)
            enc_size = r.i32()
            self._encoded = r.bytes(enc_size)
            f.seek(fdi_off)
            fdi = Reader(f.read(fdi_size))
        self.files = {}
        for _ in range(fdi.i32()):
            d = fdi.fstring()
            for _ in range(fdi.i32()):
                name = fdi.fstring()
                loc = fdi.i32()
                if loc >= 0:
                    self.files[self.normalize(self.mount_point + d + name)] = loc

    @staticmethod
    def normalize(p):
        while p.startswith("../"):
            p = p[3:]
        return p.lstrip("/")

    def entry(self, path):
        return decode_entry(self._encoded, self.files[path])

    def read(self, path, oodle=None):
        e = self.entry(path)
        if e["encrypted"]:
            raise EncryptedError(f"{path}: entry is encrypted -- stopping (project rule)")
        with open(self.path, "rb") as f:
            if not e["method"]:
                f.seek(e["offset"] + e["header_size"])
                return f.read(e["usize"])
            name = self.footer["compression_methods"][e["method"] - 1]
            if name.lower() != "oodle" or oodle is None:
                raise ValueError(f"{path}: needs {name} decompression")
            out = bytearray()
            for i, (start, end) in enumerate(e["blocks"]):
                f.seek(e["offset"] + start)
                raw = min(e["block_size"], e["usize"] - i * e["block_size"])
                out += oodle.decompress(f.read(end - start), raw)
            return bytes(out)
