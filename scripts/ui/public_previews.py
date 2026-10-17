"""Published previews: the edited LATAM audio of APPROVED lines, rendered ahead of time for the public view
(docs/public-access.md §2.1, owner request 2026-10-17).

- **Publishing** (`publish`, run by the owner: python scripts/build/publish_previews.py) renders every eligible
  line's SAVED recipe exactly as the build does (M4App.edit_preview: trims, cuts, fades, radio, echo, interference,
  the export gain) and copies the edited WAV into work/public_previews/<sha256>.wav, with index.json. Eligible:
  audio approved, one Campaign Evolved source, mono, no fingerprint drift. Everything else is left out, and files
  of lines that are no longer eligible are removed.
- **Serving** (`PreviewStore.lookup`, the public listener's GET /audio/public?slot=<slot_id>) never renders: it
  serves a published file only while the line's current audio decision is still exactly the one published
  (approved, same `audio_key`). A line sent back to rework, re-edited or un-approved stops playing at once, before
  any republish. Unpublished lines, drafts and the owner's own editor previews are never reachable.

Visitors address a preview by slot id only (already public metadata); file names and preview keys never leave the
server. Anything a browser can play can still be recorded: hiding download buttons is not protection.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

SCHEMA = "public-previews/1"
STORE_REL = "work/public_previews"


def audio_key(mapping):
    """A fingerprint of the whole audio decision (status, sources, recipe, approval, revision): any change, including
    a rework, gives a different key and stops the published preview from being served."""
    audio = (mapping or {}).get("audio") or {}
    return hashlib.sha256(json.dumps(audio, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def ineligible_reason(mapping):
    """None when the line's audio may be published, else why not (shown to visitors)."""
    if not mapping:
        return "this line has no decision yet"
    audio = mapping.get("audio") or {}
    if audio.get("status") != "approved":
        return "the audio is not approved yet"
    sources = audio.get("sources") or []
    if audio.get("source") != "ce" or len(sources) != 1 or sources[0].get("kind") != "ce":
        return ("Spain's audio is kept for this line" if audio.get("source") == "keep_original"
                else "the line is muted in game" if audio.get("source") == "mute"
                else "this kind of replacement has no preview")
    return None


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class PreviewStore:
    """work/public_previews/: index.json + <sha256>.wav. Read again whenever index.json changes (a publish while
    the server runs takes effect without a restart)."""

    def __init__(self, root):
        self.dir = Path(root) / STORE_REL
        self._lock = threading.Lock()
        self._stamp, self._entries = None, {}

    def entries(self):
        p = self.dir / "index.json"
        with self._lock:
            try:
                st = p.stat()
            except FileNotFoundError:
                self._stamp, self._entries = None, {}
                return self._entries
            stamp = (st.st_mtime_ns, st.st_size)
            if stamp != self._stamp:
                doc = json.loads(p.read_text(encoding="utf-8"))
                self._entries = doc.get("entries", {}) if doc.get("schema") == SCHEMA else {}
                self._stamp = stamp
            return self._entries

    def lookup(self, slot_id, mapping):
        """-> (path, None) for a servable preview, or (None, reason)."""
        why = ineligible_reason(mapping)
        if why:
            return None, why
        entry = self.entries().get(slot_id)
        if not entry:
            return None, "no preview has been published for this line yet"
        if entry.get("audio_key") != audio_key(mapping):
            return None, "the line changed since its preview was published"
        name = str(entry.get("file") or "")
        if len(name) != 68 or not name.endswith(".wav") or not all(c in "0123456789abcdef" for c in name[:64]):
            return None, "no preview has been published for this line yet"
        path = self.dir / name
        if not path.is_file():
            return None, "no preview has been published for this line yet"
        return path, None

    def status(self, slot_id, mapping):
        """What the public slot view says about the preview: {available, url, reason}."""
        path, why = self.lookup(slot_id, mapping)
        from urllib.parse import quote  # noqa: PLC0415
        return {"available": path is not None, "reason": why,
                "url": f"/audio/public?slot={quote(slot_id, safe='')}" if path else None}


def publish(app, root, dry_run=False, log=print, only=None):
    """Render and publish every eligible approved line; remove what is no longer eligible. -> summary dict.
    `app` is an M4App with its audio editor (scripts/ui/m4_server.make_app). `only`: a set of slot ids to
    (re)publish; every other published line is kept as it is."""
    store = Path(root) / STORE_REL
    old = PreviewStore(root).entries()
    mappings = app._mappings()[0]["slots"]
    entries, skipped, rendered, reused = {}, {}, 0, 0
    if only is not None:
        unknown = set(only) - {m["slot_id"] for m in mappings}
        if unknown:
            raise ValueError(f"no decision for {sorted(unknown)}")
        entries = {sid: e for sid, e in old.items() if sid not in only}
    for m in mappings:
        sid = m["slot_id"]
        if only is not None and sid not in only:
            continue
        why = ineligible_reason(m)
        if why is None and sid not in app.slot_index:
            why = "the line is not in the MCC catalog"
        if why is None and app.slot(sid, with_interference=False)["fingerprint_drift"].get("audio"):
            why = "the approved audio's sources changed (drift); review it first"
        if why is not None:
            if (m.get("audio") or {}).get("status") == "approved":
                skipped[sid] = why
            continue
        key = audio_key(m)
        prev = old.get(sid)
        if prev and prev.get("audio_key") == key and (store / prev["file"]).is_file():
            entries[sid] = prev
            reused += 1
            continue
        if dry_run:
            entries[sid] = {"pending": True}
            rendered += 1
            continue
        src = m["audio"]["sources"][0]
        try:
            r = app.edit_preview({"slot_id": sid, "ce_line_ref": src["ce_line_ref"], "language": src["language"],
                                  "edit": m["audio"].get("edit") or {}})
            wav = app.preview_wav(r["key"], "edited")
        except Exception as e:  # noqa: BLE001 - one line failing never stops the others; reported
            skipped[sid] = f"render failed: {getattr(e, 'message', None) or e}"
            continue
        sha = _sha_file(wav)
        store.mkdir(parents=True, exist_ok=True)
        dest = store / f"{sha}.wav"
        if not dest.is_file():
            tmp = dest.with_suffix(".tmp")
            shutil.copyfile(wav, tmp)
            os.replace(tmp, dest)
        entries[sid] = {"file": dest.name, "sha256": sha, "audio_key": key, "mapping_id": m["mapping_id"],
                        "ce_line_ref": src["ce_line_ref"], "summary": r.get("summary"),
                        "rendered_at": dt.datetime.now().isoformat(timespec="seconds")}
        rendered += 1
        log(f"  published {sid}")
    summary = {"published": len(entries), "rendered": rendered, "reused": reused, "skipped_approved": skipped,
               "removed": sorted(set(old) - set(entries)), "dry_run": dry_run}
    if dry_run:
        return summary
    store.mkdir(parents=True, exist_ok=True)
    doc = {"schema": SCHEMA, "published_at": dt.datetime.now().isoformat(timespec="seconds"), "entries": entries}
    tmp = store / "index.json.tmp"
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, store / "index.json")
    keep = {e["file"] for e in entries.values()}
    for f in store.glob("*.wav"):
        if f.name not in keep:
            f.unlink()
    return summary
