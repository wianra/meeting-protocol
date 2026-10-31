"""Sequential decoding with durable PCM blocks and sample-accurate offsets."""

import json
import subprocess
from pathlib import Path

from .compat import hidden
from .storage import atomic_write, canonical, digest_file, fingerprint

RATE = 16000
BLOCK_SAMPLES = 60 * RATE


def inspect_audio(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        check=True,
        **hidden(),
    )
    data = json.loads(result.stdout)
    streams = [s for s in data["streams"] if s["codec_type"] == "audio"]
    if not streams:
        raise ValueError("The selected file has no audio stream.")
    stream = streams[0]
    return {
        "duration": float(data["format"]["duration"]),
        "channels": int(stream["channels"]),
        "sample_rate": int(stream["sample_rate"]),
        "codec": stream["codec_name"],
    }


def read_block(pipe, size: int) -> bytes:
    parts, remaining = [], size
    while remaining:
        data = pipe.read(remaining)
        if not data:
            break
        parts.append(data)
        remaining -= len(data)
    return b"".join(parts)


def prepare(store, config: dict, progress) -> dict:
    source = Path(config["input"])
    if not source.is_file() or digest_file(source) != config["input_sha256"]:
        raise RuntimeError("Input file has moved or changed. Create a new job for changed audio.")
    key = fingerprint(["decode-v1", config["input_sha256"], config["channel"]])
    cached = store.get_json(key)
    if cached and all(store.read(k) is not None for k in cached["blocks"]):
        blocks = cached["blocks"]
        meta = cached
        progress("decode", len(blocks), len(blocks), "Using verified saved audio")
    else:
        args = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map", "0:a:0"]
        if config["channel"] is not None:
            args += ["-af", f"pan=mono|c0=c{config['channel']}"]
        args += ["-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"]
        # Stderr to a local file avoids a pipe deadlock and keeps diagnostics on-device.
        with (store.root / "decode.log").open("wb") as err:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, **hidden())
            blocks, samples = [], 0
            total = max(1, int(config["audio"]["duration"] / 60) + 1)
            try:
                while data := read_block(proc.stdout, BLOCK_SAMPLES * 2):
                    if len(data) % 2:
                        raise RuntimeError("Decoder returned an incomplete audio sample.")
                    block_key = fingerprint([key, len(blocks)])
                    if store.read(block_key) is None:
                        store.put(block_key, data, "decode")
                    blocks.append(block_key)
                    samples += len(data) // 2
                    progress("decode", len(blocks), total, "Audio block saved")
                if proc.wait() != 0:
                    raise RuntimeError("Audio decoding failed. See the local decode.log.")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait()
                proc.stdout.close()
        if samples == 0:
            raise ValueError("The selected audio is empty.")
        meta = {
            "sample_rate": RATE,
            "samples": samples,
            "duration": samples / RATE,
            "blocks": blocks,
        }
        store.put_json(key, meta, "decode")
    # A memory-mappable, disposable view of durable blocks. Rebuild only when necessary.
    pcm = store.root / "audio.pcm"
    marker = store.root / "audio.json"
    valid = (
        pcm.exists()
        and marker.exists()
        and json.loads(marker.read_text()).get("sha256") == digest_file(pcm)
    )
    if not valid:
        import os

        temporary = store.root / "audio.pcm.pending"
        with temporary.open("wb") as out:
            for block in blocks:
                out.write(store.read(block))
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(pcm)
        atomic_write(marker, canonical({**meta, "sha256": digest_file(pcm)}))
    return meta


def waveform(root: Path):
    import numpy as np

    return np.memmap(root / "audio.pcm", dtype="<i2", mode="r")
