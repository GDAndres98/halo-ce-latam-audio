"""Campaign Evolved source-build identification and file hashing, shared by
the M1 catalog builder and the M1b audio exporter. Read-only."""
import hashlib

from .asset_metadata import EXPLICIT, UNRESOLVED, derived
from .ce_assets import parse_steam_acf, read_pe_file_version


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()



def source_build_ids(ctx):
    exe = ctx.remake / "Meteorite" / "Binaries" / "Win64" / "HaloCampaignEvolved.exe"
    fv = read_pe_file_version(exe) if exe.is_file() else None
    out = {"exe_file_version": fv, "exe_file_version_evidence": EXPLICIT if fv else UNRESOLVED}
    steamapps = ctx.remake.parent.parent
    for acf in sorted(steamapps.glob("appmanifest_*.acf")):
        kv = parse_steam_acf(acf.read_text(encoding="utf-8", errors="replace"))
        if kv.get("installdir", "").lower() == ctx.remake.name.lower():
            out.update({"steam_appid": kv.get("appid"), "steam_buildid": kv.get("buildid"),
                        "steam_buildid_evidence": EXPLICIT})
            break
    else:
        out.update({"steam_buildid": None, "steam_buildid_evidence": UNRESOLVED})
    out["usmap_name"] = ctx.usmap_path.name
    out["usmap_build_string_evidence"] = derived("ue4ss_usmap_filename")
    return out
