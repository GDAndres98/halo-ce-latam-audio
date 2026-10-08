"""Readers for the Campaign Evolved assets on the verified line-link chain
(docs/poc-ce-line-link.md §2), shared by the PoC linker and the catalog
builder.

Pure helpers (`unwrap`, `import_target`, `soft_path`, `event_languages`,
`parse_string_table_tail`, `parse_steam_acf`) take already-decoded values
or bytes and are unit-tested with synthetic input. The `read_*` helpers
need a `CEContext` and open the installed containers read-only.
"""
import ctypes
import sys

from .binreader import Reader


def unwrap(v):
    """Strip parser wrappers: {'name': x} -> x, {'_default': True} -> None."""
    if isinstance(v, dict):
        if v.get("_default"):
            return None
        if set(v) == {"name"}:
            return v["name"]
    return v


def import_target(ref):
    """ObjectProperty value -> imported package path (explicit, from the import map)."""
    r = (ref or {}).get("ref") or {}
    t = r.get("target")
    return t.get("package") if isinstance(t, dict) else None


def soft_path(v):
    """SoftObjectPath value -> '/Game/...' path, or None for the null path 'None.None'."""
    v = unwrap(v)
    p = v.get("soft_path") if isinstance(v, dict) else None
    if not p or p.split(":")[0] in ("None.None", "."):
        return None
    return p


def event_languages(cooked):
    """WwiseLocalizedEventCookedData -> {wwise_language: {event_id, media[], soundbanks[]}}.

    Every value is copied from the cooked struct; nothing is computed.
    """
    out = {}
    for kv in cooked.get("EventLanguageMap") or []:
        lang = unwrap(kv["key"]["LanguageName"])
        v = kv["value"]
        eid = unwrap(v.get("EventId"))
        out[lang] = {
            "event_id": eid & 0xFFFFFFFF if isinstance(eid, int) else None,
            "media": [{"media_id": unwrap(m["MediaId"]) & 0xFFFFFFFF,
                       "media_path": unwrap(m["MediaPathName"]),
                       "streaming": unwrap(m.get("bStreaming")),
                       "source_name": unwrap(m.get("DebugName"))} for m in v.get("Media") or []],
            "soundbanks": [{"bank_id": unwrap(b["SoundBankId"]) & 0xFFFFFFFF,
                            "bank_path": unwrap(b.get("SoundBankPathName")),
                            "bank_name": unwrap(b.get("DebugName"))} for b in v.get("SoundBanks") or []],
        }
    return out


def parse_string_table_tail(r):
    """StringTable native data after the tagged properties:
    int32 HasGuid, FString TableNamespace, int32 n, n x (FString key, FString source).
    Returns (namespace, [(key, source), ...]) in file order."""
    r.i32()  # UObject HasGuid flag
    namespace = r.fstring()
    entries = [(r.fstring(), r.fstring()) for _ in range(r.i32())]
    return namespace, entries


def read_string_table(ctx, game_path):
    pkg_info = ctx.load_package(ctx.game_path_to_vfs(game_path))
    if not pkg_info:
        return None
    pkg = pkg_info["package"]
    if pkg.exports[0]["class"] != "StringTable":
        return {"vfs_path": pkg_info["vfs_path"], "container": pkg_info["container"],
                "class": pkg.exports[0]["class"]}
    _props, r = pkg.read_export_properties(0)
    namespace, entries = parse_string_table_tail(Reader(r.data, r.pos))
    # Source (English) strings are not kept: the subtitle text comes from each culture's .locres.
    return {"vfs_path": pkg_info["vfs_path"], "container": pkg_info["container"],
            "class": "StringTable", "namespace": namespace, "keys": [k for k, _ in entries]}


def read_event_cooked_data(ctx, game_path):
    pkg_info = ctx.load_package(ctx.game_path_to_vfs(game_path))
    if not pkg_info:
        return None, None
    pkg = pkg_info["package"]
    _props, r = pkg.read_export_properties(0)
    rr = Reader(r.data, r.pos)
    rr.i32()  # UObject HasGuid flag precedes the Wwise cooked-data struct
    cooked = pkg.read_struct(rr, "WwiseLocalizedEventCookedData")
    pkg_info["trailing_bytes"] = len(r.data) - rr.pos
    pkg_info["class"] = pkg.exports[0]["class"]
    return pkg_info, cooked


def parse_steam_acf(text):
    """Flat key/value read of a Steam appmanifest_*.acf (top-level "AppState" fields only)."""
    out = {}
    depth = 0
    for line in text.splitlines():
        s = line.strip()
        if s == "{":
            depth += 1
        elif s == "}":
            depth -= 1
        elif depth == 1 and s.startswith('"'):
            parts = [p for p in s.split('"') if p.strip()]
            if len(parts) == 2:
                out[parts[0]] = parts[1]
    return out


def read_pe_file_version(path):
    """FileVersion string from a PE version resource (Windows API, read-only), or None."""
    if sys.platform != "win32":
        return None
    ver = ctypes.windll.version
    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    ptr, n = ctypes.c_void_p(), ctypes.c_uint()
    if not ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(n)) or n.value < 4:
        return None
    lang, cp = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    sub = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileVersion"
    if not ver.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(n)) or not n.value:
        return None
    return ctypes.wstring_at(ptr, n.value - 1)
