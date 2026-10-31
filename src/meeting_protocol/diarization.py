"""Cache the original pipeline's neural batches without changing its window grid."""

import hashlib
import io
import time
from importlib.metadata import version

from .audio import RATE, waveform
from .storage import fingerprint


class BatchCache:
    def __init__(self, store, namespace: str, progress):
        self.store, self.namespace, self.progress = store, namespace, progress
        self.hits = self.misses = 0

    def call(self, stage, function, *args, **kwargs):
        import numpy as np

        h = hashlib.sha256(f"{self.namespace}:{stage}".encode())
        for name, value in [(str(i), v) for i, v in enumerate(args)] + sorted(kwargs.items()):
            h.update(name.encode())
            if value is None:
                h.update(b"None")
                continue
            if hasattr(value, "detach"):
                value = value.detach().cpu().numpy()
            array = np.ascontiguousarray(value)
            h.update(f"{array.dtype}:{array.shape}".encode())
            h.update(array.tobytes())
        key = h.hexdigest()
        cached = self.store.read(key)
        if cached is not None:
            self.hits += 1
            return np.load(io.BytesIO(cached), allow_pickle=False)
        start = time.monotonic()
        result = function(*args, **kwargs)
        if not isinstance(result, np.ndarray):
            raise TypeError("Unsupported pyannote batch output; update the pinned adapter.")
        data = io.BytesIO()
        np.save(data, result, allow_pickle=False)
        elapsed = time.monotonic() - start
        self.store.put(key, data.getvalue(), stage, elapsed)
        self.misses += 1
        if elapsed > 180:
            self.progress(
                stage, self.misses, 0, "Warning: a batch exceeded the 3-minute recovery target"
            )
        return result


class EmbeddingProxy:
    def __init__(self, original, cache):
        self.original, self.cache = original, cache

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __call__(self, *args, **kwargs):
        return self.cache.call("speaker_embeddings", self.original, *args, **kwargs)


def run(store, config, progress):
    import numpy as np
    import torch
    from pyannote.audio import Pipeline

    if version("pyannote-audio") != "4.0.7":
        raise RuntimeError("The resumable adapter is pinned to pyannote-audio 4.0.7.")
    identity = [
        "diarization-v1",
        config["input_sha256"],
        config["channel"],
        config["models"]["diarization"]["fingerprint"],
        version("pyannote-audio"),
    ]
    result_key = fingerprint([identity, config["min_speakers"], config["max_speakers"]])
    cached = store.get_json(result_key)
    if cached is not None:
        progress("diarization", 1, 1, "Using saved speaker assignments")
        return cached
    progress("diarization", 0, 1, "Loading local speaker models")
    torch.set_num_threads(6)
    pipeline = Pipeline.from_pretrained(config["models"]["diarization"]["path"])
    if pipeline is None:
        raise RuntimeError("Local diarisation pipeline could not be loaded.")
    pipeline.to(torch.device("cpu"))
    pipeline.segmentation_batch_size = 8
    pipeline.embedding_batch_size = 8
    cache = BatchCache(store, fingerprint(identity), progress)
    original_infer = pipeline._segmentation.infer
    pipeline._segmentation.infer = lambda *a, **kw: cache.call(
        "speaker_segmentation", original_infer, *a, **kw
    )
    pipeline._embedding = EmbeddingProxy(pipeline._embedding, cache)

    def hook(step, artifact=None, *, completed=None, total=None, **kwargs):
        if completed is not None:
            progress(
                step,
                int(completed),
                int(total or 0),
                f"Saved batches: {cache.misses}; reused: {cache.hits}",
            )
        else:
            progress(step, 1, 1, "Stage complete")

    pcm = waveform(store.root)
    audio = torch.from_numpy(pcm.astype(np.float32) / 32768).unsqueeze(0)
    start = time.monotonic()
    output = pipeline(
        {"waveform": audio, "sample_rate": RATE, "uri": "meeting"},
        min_speakers=config["min_speakers"],
        max_speakers=config["max_speakers"],
        hook=hook,
    )

    def turns(annotation):
        return [
            {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]

    result = {
        "turns": turns(output.speaker_diarization),
        "exclusive": turns(output.exclusive_speaker_diarization),
    }
    store.put_json(result_key, result, "diarization", time.monotonic() - start)
    return result
