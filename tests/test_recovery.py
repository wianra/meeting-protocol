import multiprocessing
from pathlib import Path

import numpy as np
import pytest

from meeting_protocol.diarization import BatchCache
from meeting_protocol.storage import Store, atomic_write, digest_file, lock


def commit_then_crash(folder):
    import os

    store = Store(Path(folder))
    store.put("finished", b"completed inference", "test", 1.25)
    os._exit(7)


def test_committed_artifact_survives_process_death(tmp_path):
    process = multiprocessing.get_context("spawn").Process(
        target=commit_then_crash, args=(str(tmp_path),)
    )
    process.start()
    process.join(20)
    assert process.exitcode == 7
    store = Store(tmp_path)
    assert store.read("finished") == b"completed inference"
    assert store.read("unfinished") is None
    store.close()


def test_corruption_recomputes_only_invalid_batch(tmp_path):
    store = Store(tmp_path)
    calls = []

    def infer(x, masks=None):
        calls.append(x.copy())
        return x * 2

    cache = BatchCache(store, "model-revision-and-settings", lambda *args: None)
    x, y = np.arange(5), np.arange(7)
    assert np.array_equal(cache.call("embedding", infer, x), x * 2)
    assert np.array_equal(cache.call("embedding", infer, y), y * 2)
    paths = list(store.db.execute("SELECT path FROM artifacts ORDER BY created"))
    (tmp_path / paths[0][0]).write_bytes(b"corrupted")
    cache.call("embedding", infer, x)
    cache.call("embedding", infer, y)
    assert len(calls) == 3
    assert cache.hits == 1
    store.close()


def test_model_and_mask_changes_invalidate_feature_cache(tmp_path):
    store = Store(tmp_path)
    calls = []

    def infer(x, masks=None):
        calls.append(1)
        return x.copy()

    x = np.ones((2, 5), dtype=np.float32)
    cache = BatchCache(store, "model-a", lambda *args: None)
    cache.call("embedding", infer, x, masks=x)
    cache.call("embedding", infer, x, masks=x.copy())
    cache.call("embedding", infer, x, masks=x * 0)
    BatchCache(store, "model-b", lambda *a: None).call("embedding", infer, x, masks=x)
    assert len(calls) == 3
    store.close()


def test_atomic_failed_replace_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint"
    atomic_write(path, b"previous")
    before = digest_file(path)

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("meeting_protocol.storage.os.replace", fail)
    with pytest.raises(OSError):
        atomic_write(path, b"new")
    assert digest_file(path) == before
    assert not list(tmp_path.glob(".pending-*"))


def test_job_lock_rejects_concurrent_writer(tmp_path):
    with (
        lock(tmp_path / "lock"),
        pytest.raises(RuntimeError, match="already running"),
        lock(tmp_path / "lock"),
    ):
        pass


def test_corrections_survive_inference_retry(tmp_path):
    store = Store(tmp_path)
    store.correction("turn-1", "Corrected meaning", "Speaker B", True)
    store.put_json("asr", {"text": "original model output"}, "asr")
    store.close()
    resumed = Store(tmp_path)
    assert resumed.corrections()["turn-1"]["text"] == "Corrected meaning"
    assert resumed.corrections()["turn-1"]["reviewed"] is True
    resumed.close()
