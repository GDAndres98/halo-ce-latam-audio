# Steam Workshop Feasibility (WC-1, documentation only)

**Status:** 2026-10-08. Nothing was packaged, uploaded or published.

Labels:
- **CONFIRMED:** official documentation or our own local tests;
- **COMMUNITY:** community reports;
- **ASSUMPTION:** inferred, not verified.

## 1. Can Workshop carry our files?

| Question | Answer | Label |
|---|---|---|
| Excession can package Halo CE mods | Yes. Excession is the official tool to configure mods and upload them to Workshop; mod types are Campaign, Multiplayer Maps and Firefight Maps [^exc-overview][^exc-create] | CONFIRMED |
| What a package contains | A mod folder. `ModInfo.json` is created by Excession. "All **.map** files of the mod package need to be manually placed to the **maps** subfolder". Excession "simply uploads all contents of the mod folder … without any validation" [^exc-folders] | CONFIRMED |
| A documented way to override `halo1/sound/pc/*.fsb` or `Data/ui/localization/*.bin` | **None found.** The official docs describe maps and per-type JSON only. `ModInfo.json` has `GameModContents.HasSharedFiles`, but no public document says what "shared files" may contain or whether they replace retail files [^vortex] | CONFIRMED (absence in docs) |
| Whether arbitrary files in the mod folder are loaded | Unknown. "Uploads all contents" means extra files would be *uploaded*, not that MCC *loads* them | ASSUMPTION |
| Whether a custom H1 `.map` can carry its own dialogue audio | Unproven. H1A sounds live in FMOD banks; `tool export-sounds-to-fsb` builds only the SFX bank (b2-audio-research §1.6) | ASSUMPTION |
| Loading requirement | Mods run only with **EAC disabled** ("Play Halo: MCC Anti-Cheat Disabled") [^hs-eac] | CONFIRMED |
| Behaviour after updates | Mods carry a game-version range, and mods outside it are disabled after an update. Users edit `MaxAppVersion` by hand to re-enable them [^steam-maxver] | COMMUNITY |
| Our replacement works in game | Edited `SU`/`SP` text displays (B1), and a rebuilt Spanish bank plays (E1) — **when the installed files are replaced** | CONFIRMED (local) |

**Conclusion:** our working delivery route is to **replace two or
three retail files** in place:
- `sounds_dialogs_spanish.fsb`;
- `SU_Halo1.bin` and `SP_Halo1.bin`.

Nothing documented shows that Workshop can do that, so a Workshop
package is **not** a confirmed delivery channel for this mod today. The
likely WC outcome is **C** (Workshop can't deliver this content), or
**B** (rebuild campaign `.map` files, which is unproven and much
larger).

The cheap way to settle it is **WC-2**. You subscribe to one existing
Halo CE Workshop mod, and we inspect its downloaded folder read-only, to
see whether any mod ships non-map files and whether MCC reads them. This
needs your approval.

## 2. Redistribution limits (CE assets)

| Source | Text | Effect |
|---|---|---|
| MCC EULA FAQ (343i) [^faq] | "Only the assets contained within the retail version of MCC are allowed for use in modding efforts." It was asked about assets from other 343 games; mods may not be sold | CE es-MX audio and text are **another game's assets**, so a public mod containing them is presumed **not permitted** |
| Microsoft Game Content Usage Rules [^gcur] | Personal, non-commercial use; "You can't reverse engineer our games to access the assets…" | Local personal use fits best. Public redistribution of extracted CE audio has no clear permission |

**Paths that could be compliant:**
- **written permission** from Halo Studios / Microsoft (M8.1 draft
  request);
- **new LATAM recordings** by consenting voice actors, wired into the
  same slots (`user_recording` already exists);
- **your own subtitle text**, or MCC's own `SU` text;
- a **`public` build profile** that refuses any CE-derived slot.

A patcher that rebuilds the bank on the player's machine from *their*
CE install avoids shipping CE files, but it still puts non-MCC assets
into an MCC mod, against the FAQ. It stays rejected unless you decide
otherwise.

[^exc-overview]: Microsoft Learn, [Excession Tool Overview](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/excessionoverview).
[^exc-create]: Microsoft Learn, [Creating a Mod Package](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/creatingmodpackage/creatinghome).
[^exc-folders]: Microsoft Learn, [Excession Folder Structure](https://learn.microsoft.com/en-us/halo-master-chief-collection/excession/setup/folderstructure) (fetched 2026-10-08).
[^vortex]: Nexus-Mods/Vortex, [Halo MCC: New Mod format, issue #13745](https://github.com/Nexus-Mods/Vortex/issues/13745) (`ModInfo.json`, `GameModContents.HasSharedFiles`).
[^hs-eac]: Halo Support, [Launch MCC with EAC disabled](https://support.halowaypoint.com/hc/en-us/articles/360037475251-How-to-Launch-Halo-The-Master-Chief-Collection-with-Easy-Anti-Cheat-EAC-Disabled) (page blocks automated fetches; search-result text).
[^steam-maxver]: Steam Community, [Fix and future proof mods in Halo MCC](https://steamcommunity.com/discussions/forum/7/597412189643614641/) (2025-09-17).
[^faq]: Halo Waypoint, [MCC's EULA: the FAQ](https://www.halowaypoint.com/news/mccs-eula-the-faq).
[^gcur]: Microsoft, [Game Content Usage Rules](https://www.xbox.com/en-US/developers/rules).
