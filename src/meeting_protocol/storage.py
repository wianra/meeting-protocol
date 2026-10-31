"""Content-verified, atomic artifacts and a single-writer job journal."""

import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("This job is already running or being edited.") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "job.sqlite", timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS artifacts (
            key TEXT PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT NOT NULL,
            stage TEXT NOT NULL, seconds REAL NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, at REAL, stage TEXT, done INTEGER, total INTEGER,
            message TEXT
          );
          CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY, turn_id TEXT, text TEXT, speaker TEXT,
            reviewed INTEGER, created REAL
          );
          CREATE TABLE IF NOT EXISTS speaker_names (
            id INTEGER PRIMARY KEY, speaker_id TEXT, name TEXT, created REAL
          );
        """)

    def close(self):
        self.db.close()

    def read(self, key: str) -> bytes | None:
        row = self.db.execute("SELECT path, sha256 FROM artifacts WHERE key=?", (key,)).fetchone()
        if row:
            path = self.root / row[0]
            if path.is_file() and digest_file(path) == row[1]:
                return path.read_bytes()
            with self.db:
                self.db.execute("DELETE FROM artifacts WHERE key=?", (key,))
        return None

    def put(self, key: str, data: bytes, stage: str, seconds: float = 0) -> None:
        relative = f"artifacts/{key}.bin"
        atomic_write(self.root / relative, data)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?, ?, ?, ?, ?, ?)",
                (key, relative, hashlib.sha256(data).hexdigest(), stage, seconds, time.time()),
            )

    def get_json(self, key: str):
        raw = self.read(key)
        return None if raw is None else json.loads(raw)

    def put_json(self, key: str, value, stage: str, seconds: float = 0):
        self.put(key, canonical(value), stage, seconds)

    def event(self, stage: str, done: int, total: int, message: str = ""):
        with self.db:
            self.db.execute(
                "INSERT INTO events(at, stage, done, total, message) VALUES(?,?,?,?,?)",
                (time.time(), stage, done, total, message),
            )

    def correction(self, turn_id: str, text: str, speaker: str, reviewed: bool):
        with self.db:
            self.db.execute(
                "INSERT INTO corrections(turn_id,text,speaker,reviewed,created) VALUES(?,?,?,?,?)",
                (turn_id, text, speaker, int(reviewed), time.time()),
            )

    def corrections(self) -> dict:
        return {
            row[0]: {"text": row[1], "speaker": row[2], "reviewed": bool(row[3])}
            for row in self.db.execute(
                "SELECT turn_id,text,speaker,reviewed FROM corrections ORDER BY id"
            )
        }

    def rename_speaker(self, speaker_ids, name: str):
        with self.db:
            self.db.executemany(
                "INSERT INTO speaker_names(speaker_id,name,created) VALUES(?,?,?)",
                [(speaker_id, name, time.time()) for speaker_id in speaker_ids],
            )

    def speaker_names(self) -> list:
        """Every (speaker_id, name) in order; the last name for a speaker is current."""
        return list(self.db.execute("SELECT speaker_id,name FROM speaker_names ORDER BY id"))

    def latest_events(self) -> dict:
        """The last (done, total, message) recorded for each stage."""
        rows = self.db.execute(
            "SELECT stage,done,total,message FROM events WHERE id IN "
            "(SELECT MAX(id) FROM events GROUP BY stage) ORDER BY id"
        )
        return {stage: (done, total, message) for stage, done, total, message in rows}

    def summary(self):
        last = self.db.execute(
            "SELECT stage,done,total,message FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        stages = list(
            self.db.execute(
                "SELECT stage,COUNT(*),ROUND(SUM(seconds),2),"
                "ROUND(MAX(seconds),2) FROM artifacts GROUP BY stage"
            )
        )
        return {"progress": last, "stages": stages}
