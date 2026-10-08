"""Read-only UE5 zen (IoStore) package parser with unversioned-property
decoding driven by a .usmap.

Scope is deliberately small: enough to read the property values of the
dialogue-related assets (HaloAudioSound, AkAudioEvent, StringTable, ...).
Unsupported types raise UnsupportedProperty instead of guessing, so a
caller can record the relationship as unresolved.
"""
from .binreader import Reader

INDEX_MASK = (1 << 62) - 1
TYPE_EXPORT, TYPE_SCRIPT_IMPORT, TYPE_PACKAGE_IMPORT, TYPE_NULL = 0, 1, 2, 3

# Structs whose cooked form is a fixed binary blob (no unversioned header).
NATIVE_FIXED = {
    "Guid": 16, "Vector": 24, "Vector2D": 16, "Vector4": 32, "Rotator": 24, "Quat": 32,
    "Color": 4, "LinearColor": 16, "IntPoint": 8, "IntVector": 12, "DateTime": 8,
    "Timespan": 8, "FrameNumber": 4, "Box": 49, "Box2D": 33,
}


class UnsupportedProperty(Exception):
    pass


def load_name_batch(r):
    n = r.u32()
    if n == 0:
        return []
    r.u32()  # total string bytes
    r.u64()  # hash version
    r.pos += 8 * n  # hashes
    headers = [r.bytes(2) for _ in range(n)]
    names = []
    for h in headers:
        utf16 = bool(h[0] & 0x80)
        length = ((h[0] & 0x7F) << 8) | h[1]
        if utf16:
            if r.pos & 1:
                r.pos += 1
            names.append(r.bytes(2 * length).decode("utf-16-le"))
        else:
            names.append(r.bytes(length).decode("latin-1"))
    return names


def load_script_objects(global_chunk):
    """Return {global_index: name} from the global ScriptObjects chunk."""
    r = Reader(global_chunk)
    names = load_name_batch(r)
    out = {}
    for _ in range(r.i32()):
        name_idx, number = r.u32(), r.u32()
        gidx = r.u64()
        r.u64(); r.u64()  # outer, CDO class
        name = names[name_idx & 0x3FFFFFFF]
        out[gidx] = name if number == 0 else f"{name}_{number - 1}"
    return out


class ZenPackage:
    def __init__(self, data, script_objects, usmap):
        self.data = data
        self.usmap = usmap
        self.script_objects = script_objects
        r = Reader(data)
        has_versioning = r.u32()
        self.header_size = r.u32()
        name_idx, _num = r.u32(), r.u32()
        self.package_flags = r.u32()
        self.cooked_header_size = r.u32()
        (pub_hash_off, import_off, export_off, bundle_off,
         dep_hdr_off, _dep_ent_off, imp_pkg_names_off) = (r.i32() for _ in range(7))
        if has_versioning:
            r.u32()           # zen version
            r.i32(); r.i32()  # file version UE4/UE5
            r.i32()           # licensee version
            r.pos += 20 * r.i32()  # custom versions (guid + int)
        self.names = load_name_batch(r)
        self.name = self.names[name_idx]
        rr = Reader(data, imp_pkg_names_off)
        self.imported_package_names = load_name_batch(rr)
        self.imported_public_export_hashes = [
            Reader(data, pub_hash_off + 8 * i).u64() for i in range((import_off - pub_hash_off) // 8)]
        self.imports = [Reader(data, import_off + 8 * i).u64() for i in range((export_off - import_off) // 8)]
        self.exports = []
        for i in range((bundle_off - export_off) // 72):
            e = Reader(data, export_off + 72 * i)
            serial_off, serial_size = e.u64(), e.u64()
            obj_name, obj_num = e.u32(), e.u32()
            outer, cls, sup, tmpl = e.u64(), e.u64(), e.u64(), e.u64()
            self.exports.append({
                "name": self.names[obj_name] + ("" if obj_num == 0 else f"_{obj_num - 1}"),
                "serial_offset": serial_off, "serial_size": serial_size,
                "outer": outer, "class_index": cls, "class": self.resolve_index(cls),
            })
        # Export data is laid out after the header in export-bundle "Serialize" order.
        pos = self.header_size
        for i in range((dep_hdr_off - bundle_off) // 8):
            b = Reader(data, bundle_off + 8 * i)
            local_index, command = b.u32(), b.u32()
            if command == 1:  # EExportCommandType::Serialize
                self.exports[local_index]["data_start"] = pos
                pos += self.exports[local_index]["serial_size"]

    # ---- object index resolution -------------------------------------------------
    def resolve_index(self, v):
        kind = v >> 62
        if kind == TYPE_NULL or v == 0xFFFFFFFFFFFFFFFF:
            return None
        if kind == TYPE_SCRIPT_IMPORT:
            return self.script_objects.get(v, f"<script 0x{v:016x}>")
        if kind == TYPE_PACKAGE_IMPORT:
            pkg = (v & INDEX_MASK) >> 32
            exp = v & 0xFFFFFFFF
            pname = self.imported_package_names[pkg] if pkg < len(self.imported_package_names) else f"<pkg {pkg}>"
            h = self.imported_public_export_hashes[exp] if exp < len(self.imported_public_export_hashes) else None
            return {"package": pname, "public_export_hash": h}
        if kind == TYPE_EXPORT:
            return {"export": v & INDEX_MASK}
        return None

    def resolve_package_index(self, i):
        """FPackageIndex (int32) -> description dict, explicit from the import/export maps."""
        if i == 0:
            return None
        if i < 0:
            raw = self.imports[-i - 1]
            res = self.resolve_index(raw)
            return {"import": -i - 1, "target": res}
        e = self.exports[i - 1]
        return {"export": i - 1, "name": e["name"]}

    # ---- export data -------------------------------------------------------------
    def export_data(self, idx):
        e = self.exports[idx]
        start = e["data_start"]
        return start, start + e["serial_size"]

    def read_export_properties(self, idx, class_name=None):
        start, end = self.export_data(idx)
        r = Reader(self.data[:end], start)
        cls = class_name or self.exports[idx]["class"]
        props = self.read_struct(r, cls)
        return props, r

    # ---- unversioned properties --------------------------------------------------
    def read_struct(self, r, struct_name):
        if struct_name in NATIVE_FIXED:
            return {"_native_hex": r.bytes(NATIVE_FIXED[struct_name]).hex()}
        if struct_name == "SoftObjectPath":
            return self._soft_path(r)
        schema = self.usmap.flattened(struct_name)
        frags = []
        while True:
            packed = r.u16()
            frags.append((packed & 0x7F, bool(packed & 0x80), packed >> 9))
            if packed & 0x100:
                break
        zero_count = sum(v for _s, z, v in frags if z)
        mask = 0
        if zero_count:
            if zero_count <= 8:
                mask = r.u8()
            elif zero_count <= 16:
                mask = r.u16()
            else:
                words = (zero_count + 31) // 32
                for w in range(words):
                    mask |= r.u32() << (32 * w)
        out = {}
        idx = 0
        zbit = 0
        for skip, has_zero, num in frags:
            idx += skip
            for _ in range(num):
                if idx >= len(schema) or schema[idx] is None:
                    raise UnsupportedProperty(f"{struct_name}: property index {idx} not in usmap schema")
                name, ptype, arr = schema[idx]
                key = name if arr == 0 else f"{name}[{arr}]"
                is_zero = has_zero and (mask >> zbit) & 1
                if has_zero:
                    zbit += 1
                out[key] = {"_default": True} if is_zero else self.read_value(r, ptype)
                idx += 1
        return out

    def read_value(self, r, t):
        k = t.type
        if k == "BoolProperty":
            return bool(r.u8())
        if k in ("ByteProperty", "Int8Property"):
            return r.u8() if k == "ByteProperty" else r.i8()
        if k == "IntProperty":
            return r.i32()
        if k == "UInt32Property":
            return r.u32()
        if k == "Int16Property":
            return r.i16()
        if k == "UInt16Property":
            return r.u16()
        if k == "Int64Property":
            return r.i64()
        if k == "UInt64Property":
            return r.u64()
        if k == "FloatProperty":
            return r.f32()
        if k == "DoubleProperty":
            return r.f64()
        if k == "NameProperty":
            return self._fname(r)
        if k in ("StrProperty", "Utf8StrProperty", "AnsiStrProperty"):
            return r.fstring()
        if k == "EnumProperty":
            raw = self.read_value(r, t.inner)
            if isinstance(raw, dict) and "name" in raw:  # FName-backed enum
                return raw["name"]
            return self.usmap.enums.get(t.enum, {}).get(raw, raw)
        if k in ("ObjectProperty", "ClassProperty", "WeakObjectProperty", "LazyObjectProperty",
                 "InterfaceProperty"):
            i = r.i32()
            return {"package_index": i, "ref": self.resolve_package_index(i)}
        if k in ("SoftObjectProperty", "AssetObjectProperty"):
            return self._soft_path(r)
        if k == "TextProperty":
            return self._text(r)
        if k == "StructProperty":
            return self.read_struct(r, t.struct)
        if k in ("ArrayProperty", "SetProperty"):
            if k == "SetProperty":
                removed = r.i32()
                for _ in range(removed):
                    self.read_value(r, t.inner)
            return [self.read_value(r, t.inner) for _ in range(r.i32())]
        if k == "MapProperty":
            for _ in range(r.i32()):
                self.read_value(r, t.inner)
            return [{"key": self.read_value(r, t.inner), "value": self.read_value(r, t.value)}
                    for _ in range(r.i32())]
        raise UnsupportedProperty(k)

    def _fname(self, r):
        idx, num = r.u32(), r.u32()
        base = self.names[idx] if idx < len(self.names) else f"<name {idx}>"
        return {"name": base if num == 0 else f"{base}_{num - 1}"}

    def _soft_path(self, r):
        pkg = self._fname(r)["name"]
        asset = self._fname(r)["name"]
        sub = r.fstring()
        return {"soft_path": f"{pkg}.{asset}" + (f":{sub}" if sub else "")}

    def _text(self, r):
        flags = r.u32()
        history = r.i8()
        if history == -1:
            has = r.i32()
            return {"text_history": "None", "flags": flags, "invariant": r.fstring() if has else None}
        if history == 0:
            return {"text_history": "Base", "flags": flags, "namespace": r.fstring(),
                    "key": r.fstring(), "source": r.fstring()}
        if history == 11:
            return {"text_history": "StringTableEntry", "flags": flags,
                    "table_id": self._fname(r)["name"], "key": r.fstring()}
        raise UnsupportedProperty(f"FText history type {history}")
