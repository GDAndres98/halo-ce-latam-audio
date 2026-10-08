"""Read-only UE5 IoStore (.utoc/.ucas) reader.

Parses the TOC (chunk ids, offsets, compression blocks, directory index)
and reads a chunk's bytes, Oodle-decompressing blocks in memory. Refuses
encrypted containers (no key handling, by project rule).
"""
import struct
from pathlib import Path

from .binreader import Reader
from .pak import EncryptedError

TOC_MAGIC = b"-==--==--==--==-"
NONE = 0xFFFFFFFF

# EIoChunkType (UE5)
CHUNK_EXPORT_BUNDLE_DATA = 1
CHUNK_BULK_DATA = 2
CHUNK_SCRIPT_OBJECTS = 6


def _u40be(b):
    return int.from_bytes(b, "big")


def parse_header(b):
    if b[:16] != TOC_MAGIC:
        raise ValueError("not an IoStore .utoc")
    hdr = {"version": b[16]}
    (hdr["header_size"], hdr["entry_count"], hdr["block_count"], hdr["block_entry_size"],
     hdr["method_count"], hdr["method_len"], hdr["block_size"], hdr["dir_index_size"],
     hdr["partition_count"]) = struct.unpack_from("<9I", b, 20)
    hdr["key_guid_is_zero"] = b[64:80] == bytes(16)
    hdr["flags"] = b[80]
    hdr["compressed"] = bool(hdr["flags"] & 1)
    hdr["encrypted"] = bool(hdr["flags"] & 2)
    hdr["signed"] = bool(hdr["flags"] & 4)
    hdr["indexed"] = bool(hdr["flags"] & 8)
    hdr["perfect_hash_seeds"], = struct.unpack_from("<I", b, 84)
    hdr["partition_size"], = struct.unpack_from("<Q", b, 88)
    hdr["no_perfect_hash"], = struct.unpack_from("<I", b, 96)
    return hdr


class IoStore:
    def __init__(self, utoc_path):
        self.utoc = Path(utoc_path)
        b = self.utoc.read_bytes()
        h = self.header = parse_header(b)
        if h["encrypted"]:
            raise EncryptedError(f"{self.utoc.name}: container is encrypted -- stopping (project rule)")
        n = h["entry_count"]
        o = h["header_size"]
        self.chunk_ids = [b[o + 12 * i:o + 12 * (i + 1)] for i in range(n)]
        o += 12 * n
        self.offlen = [(_u40be(b[o + 10 * i:o + 10 * i + 5]), _u40be(b[o + 10 * i + 5:o + 10 * i + 10]))
                       for i in range(n)]
        o += 10 * n
        if h["version"] >= 4:
            o += 4 * h["perfect_hash_seeds"]
        if h["version"] >= 5:
            o += 4 * h["no_perfect_hash"]
        self.blocks = []
        for i in range(h["block_count"]):
            e = b[o + 12 * i:o + 12 * (i + 1)]
            self.blocks.append((int.from_bytes(e[0:5], "little"), int.from_bytes(e[5:8], "little"),
                                int.from_bytes(e[8:11], "little"), e[11]))
        o += 12 * h["block_count"]
        self.methods = [b[o + h["method_len"] * i:o + h["method_len"] * (i + 1)].split(b"\0")[0].decode()
                        for i in range(h["method_count"])]
        o += h["method_count"] * h["method_len"]
        if h["signed"]:
            hs, = struct.unpack_from("<i", b, o)
            o += 4 + 2 * hs + 20 * h["block_count"]
        self.files = self._dir_index(b[o:o + h["dir_index_size"]]) if h["dir_index_size"] else {}

    @staticmethod
    def _dir_index(d):
        r = Reader(d)
        mount = r.fstring()
        dirs = [struct.unpack_from("<4I", d, r.pos + 16 * i) for i in range(r.i32())]
        r.pos += 16 * len(dirs)
        files = [struct.unpack_from("<3I", d, r.pos + 12 * i) for i in range(r.i32())]
        r.pos += 12 * len(files)
        strings = [r.fstring() for _ in range(r.i32())]
        out = {}

        def walk(di, prefix):
            name, child, _sib, fi = dirs[di]
            here = prefix + (strings[name] + "/" if name != NONE else "")
            while fi != NONE:
                fname, nxt, toc_index = files[fi]
                out[(here + strings[fname]).replace("../", "")] = toc_index
                fi = nxt
            c = child
            while c != NONE:
                walk(c, here)
                c = dirs[c][2]
        walk(0, mount)
        return out

    def chunk_type(self, toc_index):
        return self.chunk_ids[toc_index][11]

    def find_chunk(self, chunk_id_bytes):
        try:
            return self.chunk_ids.index(chunk_id_bytes)
        except ValueError:
            return None

    def _ucas_path(self, partition):
        stem = self.utoc.with_suffix("")
        return Path(f"{stem}.ucas") if partition == 0 else Path(f"{stem}_s{partition}.ucas")

    def read_chunk(self, toc_index, oodle=None):
        offset, length = self.offlen[toc_index]
        bs = self.header["block_size"]
        first, last = offset // bs, (offset + length - 1) // bs
        out = bytearray()
        handles = {}
        try:
            for bi in range(first, last + 1):
                boff, csize, usize, method = self.blocks[bi]
                part = boff // self.header["partition_size"] if self.header["partition_size"] else 0
                f = handles.get(part) or handles.setdefault(part, open(self._ucas_path(part), "rb"))
                f.seek(boff - part * self.header["partition_size"])
                raw = f.read(csize)
                if method == 0:
                    out += raw[:usize]
                else:
                    name = self.methods[method - 1]
                    if name.lower() != "oodle" or oodle is None:
                        raise ValueError(f"block needs {name} decompression")
                    out += oodle.decompress(raw, usize)
        finally:
            for f in handles.values():
                f.close()
        start = offset - first * bs
        return bytes(out[start:start + length])
