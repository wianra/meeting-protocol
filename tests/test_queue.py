import json
import os
import subprocess
import sys

import pytest

from meeting_protocol.queue import ProcessingQueue


def test_fifo_recovery_retry_and_removal_keep_recordings(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(b"original recording")
    queue = ProcessingQueue(tmp_path / "data")
    ids = queue.add([["transcribe", str(source)], ["transcribe", str(tmp_path / "b.wav")]])
    assert queue.add([["transcribe", str(source)]]) == []
    assert queue.next()["id"] == ids[0]
    assert queue.next() is None
    queue.update(ids[0], job=str(tmp_path / "job"))
    queue.close()

    # Recovery is durable but explicit: loading changes running to paused, never starts it.
    queue = ProcessingQueue(tmp_path / "data")
    assert [e["state"] for e in queue.entries] == ["paused", "waiting"]
    assert json.loads(queue.path.read_text())["entries"][0]["state"] == "paused"
    assert queue.next()["job"] == str(tmp_path / "job")
    queue.update(ids[0], state="failed", error="Missing model")
    assert queue.next()["id"] == ids[1]
    with pytest.raises(ValueError, match="Pause"):
        queue.remove(ids[1])
    queue.update(ids[1], state="done")
    queue.retry(ids[0])
    assert queue.next()["id"] == ids[0]
    queue.update(ids[0], state="done")
    queue.remove(ids[0])
    assert source.read_bytes() == b"original recording"
    queue.close()


def test_queue_excludes_another_window_and_preserves_corrupt_file(tmp_path):
    queue = ProcessingQueue(tmp_path)
    with pytest.raises(RuntimeError, match="another app window"):
        ProcessingQueue(tmp_path)
    queue.close()
    path = tmp_path / "queue.json"
    path.write_text('{"version": 99, "entries": []}')
    with pytest.raises(ValueError, match="Unsupported"):
        ProcessingQueue(tmp_path)
    assert json.loads(path.read_text())["version"] == 99
    # Failed loading must release the lock too.
    path.write_text('{"version": 1, "entries": []}')
    ProcessingQueue(tmp_path).close()


def test_failed_queue_write_does_not_change_in_memory_or_disk(tmp_path, monkeypatch):
    from meeting_protocol import queue as module

    queue = ProcessingQueue(tmp_path)
    queue.add([["transcribe", str(tmp_path / "a.wav")]])
    saved = queue.path.read_bytes()

    def no_space(*args):
        raise OSError("No space left")

    monkeypatch.setattr(module, "atomic_write", no_space)
    with pytest.raises(OSError, match="No space"):
        queue.next()
    assert queue.entries[0]["state"] == "waiting"
    assert queue.path.read_bytes() == saved
    queue.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix parent-death signal path")
def test_desktop_supervisor_exits_when_its_gui_parent_is_gone():
    # No inference: exercise the same supervisor cancellation handler in a real process.
    code = """
import time
from meeting_protocol.jobs import install_cancel_handler
try:
    install_cancel_handler()
    time.sleep(20)
except KeyboardInterrupt:
    raise SystemExit(130)
"""
    env = {**os.environ, "DIARIZE_GUI_PARENT_PID": "0"}
    result = subprocess.run([sys.executable, "-c", code], env=env, timeout=10, check=False)
    assert result.returncode == 130
