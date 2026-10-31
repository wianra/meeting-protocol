"""Bounded MLX inference with independent, persistent window results."""

import time
from importlib.metadata import version

from .audio import RATE, waveform
from .storage import fingerprint


def windows(pcm, seconds: float):
    import numpy as np

    size = int(seconds * RATE)
    start, length = 0, len(pcm)
    while start < length:
        end = min(start + size, length)
        # Prefer a quiet 100 ms boundary in the final two seconds of a full window.
        if end < length:
            candidates = list(range(max(start + size // 2, end - 2 * RATE), end, RATE // 10))
            if candidates:
                energy = [
                    np.mean(np.abs(pcm[c : c + RATE // 10].astype(np.float32))) for c in candidates
                ]
                end = candidates[int(np.argmin(energy))] + RATE // 20
        yield {
            "start": start,
            "end": end,
            "read_start": max(0, start - RATE),
            "read_end": min(length, end + RATE),
        }
        start = end


def run(store, config, progress):
    import mlx.core as mx
    import mlx_whisper
    import numpy as np

    pcm = waveform(store.root)
    parts = list(windows(pcm, config["window_seconds"]))
    result = []
    for index, window in enumerate(parts):
        key = fingerprint(
            [
                "asr-v1",
                config["input_sha256"],
                config["channel"],
                window,
                config["models"]["asr"]["fingerprint"],
                config["language"],
                config["glossary"],
                version("mlx-whisper"),
                version("mlx"),
            ]
        )
        cached = store.get_json(key)
        if cached is None:
            progress("transcription", index, len(parts), "Transcribing next window locally")
            audio = pcm[window["read_start"] : window["read_end"]].astype(np.float32) / 32768
            start = time.monotonic()
            mx.random.seed(0)
            output = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=config["models"]["asr"]["path"],
                language=None if config["language"] == "auto" else config["language"],
                task="transcribe",
                word_timestamps=True,
                verbose=None,
                condition_on_previous_text=False,
                temperature=0.0,
                initial_prompt=config["glossary"] or None,
            )
            elapsed = time.monotonic() - start
            # Keep all candidates locally; the ownership rule below is only for final assembly.
            cached = {
                "window": window,
                "language": output["language"],
                "segments": output["segments"],
                "seconds": elapsed,
            }
            # MLX/numpy scalar types must not leak into the durable JSON format.
            import json

            cached = json.loads(json.dumps(cached, default=lambda x: x.item()))
            store.put_json(key, cached, "transcription", elapsed)
        progress("transcription", index + 1, len(parts), "Window saved")
        result.append(cached)
    return result


def owned_words(results):
    """Keep overlapping inference context, but give every word one core window owner."""
    words, issues = [], []
    for entry in results:
        window = entry["window"]
        offset = window["read_start"] / RATE
        left, right = window["start"] / RATE, window["end"] / RATE
        if not entry["segments"]:
            issues.append(
                {
                    "start": left,
                    "end": right,
                    "kind": "no_text",
                    "message": "No text detected; check against speech activity.",
                }
            )
        for segment in entry["segments"]:
            flags = []
            if segment.get("avg_logprob", 0) < -1:
                flags.append("low_recognition_confidence")
            if segment.get("compression_ratio", 0) > 2.4:
                flags.append("possible_repetition")
            if entry["language"] not in ("de", "fr", "it"):
                flags.append("unexpected_language")
            candidates = segment.get("words") or [
                {
                    "word": segment["text"],
                    "start": segment["start"],
                    "end": segment["end"],
                    "segment_only": True,
                }
            ]
            for word in candidates:
                begin, end = offset + word["start"], offset + word["end"]
                midpoint = (begin + end) / 2
                if not (left <= midpoint < right):
                    continue
                extra = list(flags)
                if word.get("probability", 1) < 0.5:
                    extra.append("low_word_confidence")
                if word.get("segment_only"):
                    extra.append("segment_timing_only")
                if left > 0 and begin < left + 0.4:
                    extra.append("window_boundary")
                words.append(
                    {
                        "text": word["word"],
                        "start": max(0.0, begin),
                        "end": max(begin, end),
                        "language": entry["language"],
                        "flags": extra,
                    }
                )
    words.sort(key=lambda w: (w["start"], w["end"]))
    return words, issues
