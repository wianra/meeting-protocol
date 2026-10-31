"""Operating-system differences in one place. macOS behaviour is the reference; Windows
gets equivalents for file locks, hidden console windows and worker supervision."""

import os
import subprocess
import sys

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import msvcrt
else:
    import fcntl


def try_lock(f) -> bool:
    """Exclusive, non-blocking lock on an open file; False if another process holds it."""
    if WINDOWS:
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def unlock(f) -> None:
    if WINDOWS:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(f, fcntl.LOCK_UN)


def hidden() -> dict:
    """Popen arguments that keep console tools (ffmpeg, workers) from opening a window."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}


def fix_missing_streams() -> None:
    # A Windows GUI app has no console: stdout/stderr are None and writing to them fails.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


class WorkerGroup:
    """Ends worker processes together with their supervisor.

    macOS: workers watch for their parent to change (see jobs.worker). Windows never
    reparents, so workers join a job object that the system closes when the supervisor
    exits for any reason, including being killed.
    """

    def __init__(self):
        self.job = None
        if WINDOWS:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.OpenProcess.restype = wintypes.HANDLE
            self.k32 = k32

            class Limits(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class Counters(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rt", "wt", "ot")]

            class Extended(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", Limits),
                    ("IoInfo", Counters),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            self.job = k32.CreateJobObjectW(None, None)
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(
                wintypes.HANDLE(self.job), 9, ctypes.byref(info), ctypes.sizeof(info)
            )

    def popen_args(self) -> dict:
        return hidden() if WINDOWS else {"start_new_session": True}

    def add(self, proc) -> None:
        if WINDOWS and self.job:
            from ctypes import wintypes

            handle = self.k32.OpenProcess(0x0101, False, proc.pid)  # TERMINATE | SET_QUOTA
            if handle:
                self.k32.AssignProcessToJobObject(
                    wintypes.HANDLE(self.job), wintypes.HANDLE(handle)
                )
                self.k32.CloseHandle(wintypes.HANDLE(handle))


def stop_supervisor(process) -> None:
    """Pause a running job started by the desktop app (a QProcess).

    macOS sends SIGTERM, which the supervisor turns into a clean pause (exit code 130).
    A windowless Windows process ignores QProcess.terminate(), so end it with code 130
    directly; its workers end with it and the checkpoints already written stay valid.
    """
    if not WINDOWS:
        process.terminate()
        return
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(0x0001, False, int(process.processId()))  # PROCESS_TERMINATE
    if handle:
        k32.TerminateProcess(wintypes.HANDLE(handle), 130)
        k32.CloseHandle(wintypes.HANDLE(handle))
    else:
        process.kill()
