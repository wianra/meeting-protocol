"""The supervisor keeps models in separate processes and persists every stage."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from importlib.metadata import version
from pathlib import Path

from .audio import inspect_audio
from .models import model_info
from .privacy import home, require_offline
from .storage import Store, atomic_write, canonical, digest_file, fingerprint, lock

RUNTIME_PACKAGES = ("mlx", "mlx-whisper", "pyannote-audio", "torch", "numpy")


def runtime_versions():
    return {name: version(name) for name in RUNTIME_PACKAGES}


def create_job(
    source,
    *,
    language="auto",
    min_speakers=2,
    max_speakers=10,
    channel=None,
    window_seconds=20.0,
    glossary="",
    asr_only=False,
) -> Path:
    require_offline()
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ValueError("Audio file does not exist.")
    if not 1 <= min_speakers <= max_speakers <= 50:
        raise ValueError("Speaker range must satisfy 1 <= minimum <= maximum <= 50.")
    if not 5 <= window_seconds <= 26:
        raise ValueError("Transcription windows must be between 5 and 26 seconds.")
    info = inspect_audio(source)
    if channel is not None and not 0 <= channel < info["channels"]:
        raise ValueError("Selected channel is outside the audio's channel range.")
    models = {"asr": model_info("asr")}
    if not asr_only:
        models["diarization"] = model_info("diarization")
    config = {
        "schema_version": 1,
        "input": str(source),
        "input_sha256": digest_file(source),
        "audio": info,
        "language": language,
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
        "channel": channel,
        "window_seconds": window_seconds,
        "glossary": glossary.strip(),
        "asr_only": asr_only,
        "models": models,
        "runtime": runtime_versions(),
    }
    job_id = fingerprint(config)[:16]
    root = home() / "jobs" / job_id
    root.mkdir(parents=True, exist_ok=True)
    with lock(root / ".lock"):
        if not (root / "job.json").exists():
            atomic_write(root / "job.json", canonical({**config, "job_id": job_id}))
    return root


def resolve_job(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_dir():
        if Path(value).name != value:
            raise ValueError("Job directory not found.")
        path = home() / "jobs" / value
    path = path.resolve()
    if not (path / "job.json").exists():
        raise ValueError("Not a meeting-protocol job directory.")
    return path


def read_config(root):
    return json.loads((root / "job.json").read_text())


def validate_job(config):
    if config["runtime"] != runtime_versions():
        raise RuntimeError(
            "Runtime versions changed. Restore the locked environment or start a new job."
        )
    source = Path(config["input"])
    if not source.is_file() or digest_file(source) != config["input_sha256"]:
        raise RuntimeError("Original audio has moved or changed; cannot resume this job.")
    for name, info in config["models"].items():
        for file, sha in info["files"].items():
            p = Path(info["path"]) / file
            if not p.is_file() or digest_file(p) != sha:
                raise RuntimeError(f"Saved {name} model is missing or damaged; provision it again.")


def run_job(root: Path, *, add_speakers=False):
    require_offline()
    with lock(root / ".lock"):
        config = read_config(root)
        if add_speakers and config["asr_only"]:
            config["models"]["diarization"] = model_info("diarization")
            config["asr_only"] = False
            atomic_write(root / "job.json", canonical(config))
        validate_job(config)
        stages = ["decode", "asr"]
        if not config["asr_only"]:
            stages.append("diarization")
        stages.append("export")
        print(json.dumps({"job": str(root), "status": "running"}), flush=True)
        for stage in stages:
            proc = subprocess.Popen(
                [sys.executable, "-m", "meeting_protocol.cli", "_worker", str(root), stage],
                start_new_session=True,
                env={**os.environ, "DIARIZE_PARENT_PID": str(os.getpid())},
            )
            try:
                if proc.wait() != 0:
                    raise RuntimeError(
                        f"{stage} failed; completed checkpoints are saved. "
                        "Resume this job after resolving the error."
                    )
            except BaseException:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                raise
        print(
            json.dumps({"job": str(root), "status": "complete", "exports": str(root / "exports")}),
            flush=True,
        )


def worker(root: Path, stage: str):
    require_offline()
    expected_parent = os.environ.get("DIARIZE_PARENT_PID")
    if expected_parent:

        def watch_parent():
            while True:
                if os.getppid() != int(expected_parent):
                    os._exit(143)
                time.sleep(0.25)

        threading.Thread(target=watch_parent, daemon=True).start()
    with lock(root / ".worker.lock"):
        _worker_locked(root, stage)


def _worker_locked(root: Path, stage: str):
    config = read_config(root)
    store = Store(root)
    last_time = 0.0

    def progress(name, done, total, message="", **extra):
        nonlocal last_time
        now = time.monotonic()
        # Do not emit thousands of cached-batch updates on resume.
        if now - last_time < 0.25 and done != total:
            return
        last_time = now
        store.event(name, done, total, message)
        # Extras (how far the text has got, its latest line) are for the live window only.
        event = {"stage": name, "done": done, "total": total, "message": message, **extra}
        print(json.dumps(event), flush=True)

    try:
        if stage == "decode":
            from .audio import prepare

            prepare(store, config, progress)
        elif stage == "asr":
            from .transcription import run

            result = run(store, config, progress)
            atomic_write(root / "asr.json", canonical(result))
        elif stage == "diarization":
            from .diarization import run

            result = run(store, config, progress)
            atomic_write(root / "diarization.json", canonical(result))
        elif stage == "export":
            from .export import export_transcript
            from .transcript import assemble

            asr = json.loads((root / "asr.json").read_text())
            diarization = (
                None if config["asr_only"] else json.loads((root / "diarization.json").read_text())
            )
            transcript = assemble(config, asr, diarization)
            atomic_write(root / "transcript.raw.json", canonical(transcript))
            export_transcript(store, transcript)
            progress("export", 1, 1, "Local draft and review report saved")
        else:
            raise ValueError("Unknown stage.")
    finally:
        store.close()


def install_cancel_handler():
    def cancel(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, cancel)
