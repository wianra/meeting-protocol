"""Pieces shared by every desktop window: the app icon and moving meetings to the Trash."""

import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

from PySide6.QtCore import QFile
from PySide6.QtGui import QIcon

from ..storage import lock

ICON = Path(__file__).with_name("assets") / "app-icon.svg"
DEVICE = "Mac" if sys.platform == "darwin" else "PC"


def set_app_icon(app):
    # On macOS this also replaces the Python rocket in the Dock.
    app.setWindowIcon(QIcon(str(ICON)))


def trash_job(root: Path) -> Path:
    """Move a job folder to the system Trash and return where it went.

    Refuses while a worker or another window holds the job's lock. The input recording
    lives outside the job folder and is never touched.
    """
    with ExitStack() as held:
        held.enter_context(lock(root / ".worker.lock"))
        held.enter_context(lock(root / ".lock"))
        if sys.platform == "win32":
            # Windows cannot move a folder with open files; release the checked locks first.
            held.close()
        moved = QFile(str(root))
        if not moved.moveToTrash():
            raise RuntimeError(f"Could not move {root.name} to the Trash.")
        return Path(moved.fileName())


def restore_job(trashed: Path, root: Path) -> None:
    if root.exists():
        raise RuntimeError("A meeting already exists at the original location.")
    if not trashed.is_dir():
        raise RuntimeError(
            "Could not find the meeting in the Trash. Use Put Back in Finder to restore it."
        )
    shutil.move(str(trashed), str(root))
