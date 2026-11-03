"""Durable desktop FIFO. Each entry delegates to the existing single-recording CLI."""

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .storage import atomic_write, canonical, lock

# "done" is still accepted when loading: earlier versions kept finished entries.
STATES = {"waiting", "running", "paused", "done", "failed"}
ACTIVE = {"waiting", "running", "paused"}


class QueueInUse(RuntimeError):
    pass


def validate(data):
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("entries"), list)
    ):
        raise ValueError("Unsupported processing queue format.")
    ids = set()
    for entry in data["entries"]:
        if (
            not isinstance(entry, dict)
            or not {"id", "args", "state", "job", "error"} <= entry.keys()
            or entry.get("state") not in STATES
            or not isinstance(entry.get("id"), str)
            or entry["id"] in ids
            or not isinstance(entry.get("args"), list)
            or len(entry["args"]) < 2
            or entry["args"][0] not in {"transcribe", "resume"}
            or not all(isinstance(arg, str) for arg in entry["args"])
            or not isinstance(entry.get("job"), (str, type(None)))
            or not isinstance(entry.get("error", ""), str)
        ):
            raise ValueError("Invalid processing queue entry.")
        ids.add(entry["id"])
    return data["entries"]


class ProcessingQueue:
    def __init__(self, directory):
        self.path = Path(directory) / "queue.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = lock(self.path.with_suffix(".lock"))
        try:
            self._lock.__enter__()
        except RuntimeError as exc:
            raise QueueInUse("The processing queue is open in another app window.") from exc
        # Set when an unreadable queue file was moved aside so the app could still open.
        self.recovered = None
        try:
            self.entries = []
            if self.path.exists():
                try:
                    self.entries = validate(json.loads(self.path.read_text()))
                except ValueError:
                    self.recovered = self.path.with_name("queue.json.bad")
                    os.replace(self.path, self.recovered)
            # Never start inference simply because the app was reopened.
            entries = [e for e in deepcopy(self.entries) if e["state"] != "done"]
            for entry in entries:
                if entry["state"] == "running":
                    entry["state"] = "paused"
            if entries != self.entries:
                self._commit(entries)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._lock is not None:
            self._lock.__exit__(None, None, None)
            self._lock = None

    def _commit(self, entries):
        atomic_write(self.path, canonical({"version": 1, "entries": entries}))
        self.entries = entries

    def add(self, commands):
        entries = deepcopy(self.entries)
        added = []
        for args in commands:
            args = list(args)
            args[1] = str(Path(args[1]).expanduser().resolve())
            if any(e["args"] == args and e["state"] in ACTIVE for e in entries):
                continue
            entry = {
                "id": uuid4().hex,
                "args": args,
                "job": args[1] if args[0] == "resume" else None,
                "state": "waiting",
                "error": "",
            }
            entries.append(entry)
            added.append(entry["id"])
        if added:
            self._commit(entries)
        return added

    def update(self, entry_id, **changes):
        entries = deepcopy(self.entries)
        entry = next(e for e in entries if e["id"] == entry_id)
        entry.update(changes)
        self._commit(entries)
        return entry

    def find(self, job, states=ACTIVE):
        """The entry for a meeting folder, comparing resolved paths (/var vs /private/var)."""
        job = Path(job).resolve()
        return next(
            (
                e
                for e in self.entries
                if e["job"] and e["state"] in states and Path(e["job"]).resolve() == job
            ),
            None,
        )

    def prioritize(self, entry_id, **changes):
        """Move an entry to the front so it is the next one to run."""
        entries = deepcopy(self.entries)
        entry = next(e for e in entries if e["id"] == entry_id)
        entry.update(changes)
        self._commit([entry, *(e for e in entries if e is not entry)])
        return entry

    def complete(self, entry_id):
        """Finished recordings leave the queue; their meetings stay in the job list."""
        self._commit([e for e in self.entries if e["id"] != entry_id])

    def next(self):
        if any(e["state"] == "running" for e in self.entries):
            return None
        entry = next((e for e in self.entries if e["state"] in {"waiting", "paused"}), None)
        return self.update(entry["id"], state="running", error="") if entry else None

    def retry(self, entry_id):
        entry = next(e for e in self.entries if e["id"] == entry_id)
        if entry["state"] != "failed":
            raise ValueError("Only failed recordings can be retried.")
        self.update(entry_id, state="waiting", error="")

    def remove(self, entry_id):
        entry = next(e for e in self.entries if e["id"] == entry_id)
        if entry["state"] == "running":
            raise ValueError("Pause the queue before removing the active recording.")
        self._commit([e for e in self.entries if e["id"] != entry_id])
