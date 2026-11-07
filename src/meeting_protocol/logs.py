"""A local diagnostic log shared by the window, the supervisor and its workers.

It records what ran, when and how it ended. It never records transcript text: progress
is logged as stage and counts only, never the event's message or latest line.
"""

import os
import time
from pathlib import Path

from .privacy import home

LIMIT = 5 * 1024 * 1024


def path() -> Path:
    return home() / "logs" / "app.log"


def log(message: str) -> None:
    """Append one line. Best effort: diagnostics must never stop processing."""
    try:
        file = path()
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as out:
            out.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {message}\n")
    except OSError:
        pass


def rotate() -> None:
    """Keep one previous log; called when the window opens."""
    file = path()
    try:
        if file.stat().st_size > LIMIT:
            os.replace(file, file.with_name("app.log.1"))
    except OSError:
        pass


def enable_crash_traces() -> None:
    """Native crashes (Metal, segfaults) and, on SIGUSR1, hangs leave Python stacks here."""
    import faulthandler
    import signal
    import sys

    try:
        file = path()
        file.parent.mkdir(parents=True, exist_ok=True)
        out = file.open("a", encoding="utf-8")  # Kept open for the process.
    except OSError:
        return
    faulthandler.enable(out, all_threads=True)
    if sys.platform != "win32":
        faulthandler.register(signal.SIGUSR1, out, all_threads=True)


def suspended_for(previous: float, now: float, interval: float) -> float:
    """Seconds a timer missed, from wall-clock time between two ticks. Sleep and App Nap
    both freeze the process; a tick that arrives far too late is how it notices."""
    late = now - previous - interval
    return late if late > 60 else 0.0
