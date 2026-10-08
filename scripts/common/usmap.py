"""Read-only parser for .usmap type mappings (UE4SS / UnrealMappingsDumper
format, versions 0-4, uncompressed payload only).
"""
from .binreader import Reader

USMAP_MAGIC = 0x30C4

PROPERTY_TYPES = [
    "ByteProperty", "BoolProperty", "IntProperty", "FloatProperty", "ObjectProperty",
    "NameProperty", "DelegateProperty", "DoubleProperty", "ArrayProperty", "StructProperty",
    "StrProperty", "TextProperty", "InterfaceProperty", "MulticastDelegateProperty",
    "WeakObjectProperty", "LazyObjectProperty", "AssetObjectProperty", "SoftObjectProperty",
    "UInt64Property", "UInt32Property", "UInt16Property", "Int64Property", "Int16Property",
    "Int8Property", "MapProperty", "SetProperty", "EnumProperty", "FieldPathProperty",
    "OptionalProperty", "Utf8StrProperty", "AnsiStrProperty",
]


class PropType:
    __slots__ = ("type", "inner", "value", "struct", "enum")

    def __init__(self, type_, inner=None, value=None, struct=None, enum=None):
        self.type, self.inner, self.value, self.struct, self.enum = type_, inner, value, struct, enum

    def __repr__(self):
        extra = self.struct or self.enum or ""
        return f"{self.type}({extra}{', ' + repr(self.inner) if self.inner else ''})"


class Usmap:
    def __init__(self, data):
        r = Reader(data)
        if r.u16() != USMAP_MAGIC:
            raise ValueError("not a .usmap file")
        self.version = r.u8()
        if self.version >= 1 and r.i32():
            raise ValueError("usmap with package versioning info is not supported")
        method = r.u8()
        comp_size, size = r.u32(), r.u32()
        if method != 0:
            raise ValueError(f"compressed usmap (method {method}) not supported")
        r = Reader(r.bytes(comp_size))
        long_names = self.version >= 2
        self.names = []
        for _ in range(r.u32()):
            n = r.u16() if long_names else r.u8()
            self.names.append(r.bytes(n).decode("utf-8"))
        self.enums = {}
        for _ in range(r.u32()):
            name = self.names[r.u32()]
            count = r.u16() if self.version >= 3 else r.u8()
            values = {}
            for i in range(count):
                if self.version >= 4:
                    v = r.u64()
                    values[v] = self.names[r.u32()]
                else:
                    values[i] = self.names[r.u32()]
            self.enums[name] = values
        self.structs = {}
        for _ in range(r.u32()):
            name = self.names[r.u32()]
            super_idx = r.u32()
            prop_count = r.u16()
            props = []
            for _ in range(r.u16()):
                index = r.u16()
                array_dim = r.u8()
                pname = self.names[r.u32()]
                props.append((index, array_dim, pname, self._read_type(r)))
            self.structs[name] = {
                "super": None if super_idx == 0xFFFFFFFF else self.names[super_idx],
                "prop_count": prop_count,
                "props": props,
            }

    def _read_type(self, r):
        t = PROPERTY_TYPES[r.u8()]
        if t == "EnumProperty":
            inner = self._read_type(r)
            return PropType(t, inner=inner, enum=self.names[r.u32()])
        if t == "StructProperty":
            return PropType(t, struct=self.names[r.u32()])
        if t in ("ArrayProperty", "SetProperty", "OptionalProperty"):
            return PropType(t, inner=self._read_type(r))
        if t == "MapProperty":
            k = self._read_type(r)
            return PropType(t, inner=k, value=self._read_type(r))
        return PropType(t)

    def flattened(self, struct_name):
        """All serializable properties in schema-index order, including supers.

        Returns a list indexed by unversioned property index -> (name, PropType, array_idx).
        """
        chain = []
        s = struct_name
        while s:
            if s not in self.structs:
                raise KeyError(f"struct {s!r} not in usmap")
            chain.append(s)
            s = self.structs[s]["super"]
        out = []
        for s in reversed(chain):
            st = self.structs[s]
            base = len(out)
            slots = [None] * st["prop_count"]
            for index, dim, pname, ptype in st["props"]:
                for a in range(dim):
                    slots[index + a] = (pname, ptype, a)
            out.extend(slots)
            assert len(out) == base + st["prop_count"]
        return out
