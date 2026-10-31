"""Network-denied execution is mandatory for every audio-processing entry point."""

import errno
import os
import socket
import sys
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("DIARIZE_HOME", Path.cwd() / ".local")).expanduser().resolve()


def configure(*, offline: bool = True) -> None:
    os.umask(0o077)
    root = home()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("cache", "huggingface", "models", "jobs", "tmp"):
        (root / name).mkdir(exist_ok=True)
    os.environ.update(
        {
            "HF_HOME": str(root / "huggingface"),
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "PYANNOTE_METRICS_ENABLED": "0",
            "DO_NOT_TRACK": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "MPLCONFIGDIR": str(root / "cache" / "matplotlib"),
            "NUMBA_CACHE_DIR": str(root / "cache" / "numba"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "TMPDIR": str(root / "tmp"),
            "HF_HUB_OFFLINE": "1" if offline else "0",
            "TRANSFORMERS_OFFLINE": "1" if offline else "0",
        }
    )


def network_is_denied() -> bool:
    # Loopback only: no meeting data and no external address. Refused != blocked.
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", 9)) in (errno.EPERM, errno.EACCES)


def require_offline() -> None:
    if not network_is_denied():
        raise RuntimeError("Processing requires the macOS network sandbox. Use ./diarize.")


def enter_sandbox() -> None:
    if os.environ.get("DIARIZE_SANDBOXED") == "1":
        require_offline()
        return
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise RuntimeError("This release requires macOS sandbox-exec for offline processing.")
    os.environ["DIARIZE_SANDBOXED"] = "1"
    os.execv(
        "/usr/bin/sandbox-exec",
        [
            "sandbox-exec",
            "-p",
            "(version 1) (allow default) (deny network*)",
            sys.executable,
            "-m",
            "meeting_protocol.cli",
            *sys.argv[1:],
        ],
    )
