"""Whisper through faster-whisper (CTranslate2) on the CPU: the backend where MLX is
unavailable, i.e. Windows. Same windows, checkpoints and output shape as the MLX path."""

import json
import os
import time
from importlib.metadata import version

from .audio import RATE, waveform
from .storage import fingerprint


def segment_dict(segment):
    # The keys transcription.owned_words reads, as plain JSON types.
    return {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": segment.text,
        "avg_logprob": float(segment.avg_logprob),
        "compression_ratio": float(segment.compression_ratio),
        "no_speech_prob": float(segment.no_speech_prob),
        "words": [
            {
                "word": w.word,
                "start": float(w.start),
                "end": float(w.end),
                "probability": float(w.probability),
            }
            for w in (segment.words or [])
        ],
    }


def run(store, config, progress):
    import numpy as np
    from faster_whisper import WhisperModel

    from .transcription import windows

    pcm = waveform(store.root)
    parts = list(windows(pcm, config["window_seconds"]))
    model = None  # loaded once, and only if a window still needs transcribing
    result = []
    for index, window in enumerate(parts):
        key = fingerprint(
            [
                "asr-ct2-v1",
                config["input_sha256"],
                config["channel"],
                window,
                config["models"]["asr"]["fingerprint"],
                config["language"],
                config["glossary"],
                version("faster-whisper"),
                version("ctranslate2"),
            ]
        )
        cached = store.get_json(key)
        if cached is None:
            progress("transcription", index, len(parts), "Transcribing next window locally")
            if model is None:
                model = WhisperModel(
                    config["models"]["asr"]["path"],
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=os.cpu_count() or 4,
                    local_files_only=True,
                )
            audio = pcm[window["read_start"] : window["read_end"]].astype(np.float32) / 32768
            start = time.monotonic()
            segments, info = model.transcribe(
                audio,
                language=None if config["language"] == "auto" else config["language"],
                task="transcribe",
                beam_size=1,
                temperature=0.0,
                word_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt=config["glossary"] or None,
                vad_filter=False,
            )
            segments = [segment_dict(s) for s in segments]  # the generator does the work
            elapsed = time.monotonic() - start
            cached = {
                "window": window,
                "language": info.language,
                "segments": segments,
                "seconds": elapsed,
            }
            cached = json.loads(json.dumps(cached))
            store.put_json(key, cached, "transcription", elapsed)
        latest = next((s for s in reversed(cached["segments"]) if s["text"].strip()), None)
        progress(
            "transcription",
            index + 1,
            len(parts),
            "Window saved",
            at=window["end"] / RATE,
            **(
                {
                    "latest": latest["text"].strip(),
                    "latest_at": window["read_start"] / RATE + latest["start"],
                }
                if latest
                else {}
            ),
        )
        result.append(cached)
    return result
