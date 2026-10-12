"""Change notifications for every open Studio (Server-Sent Events on GET /api/events).

The decisions database is the only shared state, so the feed watches it rather than the requests: a poll
of the newest history ids (slot_history, document_history) once a second sees every change, whether it
came from this server, another browser, or a script run on the host. Each change is published as

    {"seq": n, "slots": [slot_id, ...], "documents": [file name, ...], "by": {slot_id: user}}

Saves through this server name their author (`note_author`), so the other screens can say who changed a
line. Nothing here writes to the database; it is opened read-only.
"""
import json
import queue
import sqlite3
import threading
import time
from pathlib import Path


class LiveFeed:
    def __init__(self, db_path, interval_s=1.0):
        self.db_path = Path(db_path)
        self.interval_s = interval_s
        self._subs = set()
        self._lock = threading.Lock()
        self._authors = {}  # slot_id -> (user, time)
        self.seq = 0
        self._last = None
        self._stop = threading.Event()
        self._thread = None

    # ---------------------------------------------------------------- subscribers
    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def subscribers(self):
        with self._lock:
            return len(self._subs)

    def publish(self, event):
        with self._lock:
            self.seq += 1
            event = dict(event, seq=self.seq)
            for q in list(self._subs):
                try:
                    q.put_nowait(event)
                except queue.Full:  # a stalled client: drop it; its EventSource reconnects and reloads
                    self._subs.discard(q)
        return event

    def note_author(self, slot_id, user):
        with self._lock:
            self._authors[slot_id] = (user, time.time())

    # ---------------------------------------------------------------- database watch
    def _connect(self):
        return sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=5)

    def _heads(self, conn):
        s = conn.execute("SELECT COALESCE(MAX(id), 0) FROM slot_history").fetchone()[0]
        d = conn.execute("SELECT COALESCE(MAX(id), 0) FROM document_history").fetchone()[0]
        return s, d

    def poll_once(self):
        """Compare the history heads with the last poll and publish what changed. -> the event or None."""
        if not self.db_path.is_file():
            return None
        conn = self._connect()
        try:
            heads = self._heads(conn)
            if self._last is None:
                self._last = heads
                return None
            if heads == self._last:
                return None
            slots, docs = set(), set()
            for before, after in conn.execute("SELECT before_body, after_body FROM slot_history WHERE id > ?",
                                              (self._last[0],)):
                body = after or before
                try:
                    slots.add(json.loads(body)["slot_id"])
                except (TypeError, ValueError, KeyError):
                    pass
            for (name,) in conn.execute("SELECT name FROM document_history WHERE id > ?", (self._last[1],)):
                docs.add(name)
            self._last = heads
        finally:
            conn.close()
        now = time.time()
        with self._lock:
            by = {s: a[0] for s, a in self._authors.items() if s in slots and now - a[1] < 30}
            self._authors = {s: a for s, a in self._authors.items() if now - a[1] < 30}
        return self.publish({"type": "change", "slots": sorted(slots), "documents": sorted(docs), "by": by})

    def start(self):
        if self._thread:
            return
        try:
            self.poll_once()  # the starting point
        except sqlite3.Error:
            pass

        def run():
            while not self._stop.wait(self.interval_s):
                try:
                    self.poll_once()
                except sqlite3.Error:
                    pass  # busy or being replaced (an import); the next poll catches up

        self._thread = threading.Thread(target=run, daemon=True, name="live-feed")
        self._thread.start()

    def stop(self):
        self._stop.set()
