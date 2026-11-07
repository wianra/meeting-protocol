"""Explain the app's source references, generated files and export destinations."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..jobs import read_config
from ..logs import path as log_path
from ..privacy import home


def path_label(path):
    widget = QLabel(str(path))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class FilesDialog(QDialog):
    def __init__(self, parent, root):
        super().__init__(parent)
        self.setWindowTitle("Recording and saved files")
        self.setMinimumWidth(580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Recording and saved files")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        source = Path(read_config(root)["input"])
        self.source_path = path_label(source)
        self.outputs_path = path_label(root / "exports")
        self.job_path = path_label(root)
        self.data_path = path_label(home())
        self.section(layout, "Original recording", self.source_path)
        self.source_note = QLabel(
            "The app references this file in place; no copy of the original is imported. "
            "It is never moved, changed or deleted. Decoded working audio is saved with "
            "meeting checkpoints. Keep the original at this path for playback and resume."
            + ("\nThe original recording is currently missing." if not source.is_file() else "")
        )
        self.source_note.setWordWrap(True)
        layout.addWidget(self.source_note)
        self.open_button(layout, "Open source folder", source.parent)
        self.section(layout, "Saved transcript outputs", self.outputs_path)
        note = QLabel(
            "Word (.docx), plain text (.txt), structured JSON and review HTML are created "
            "when processing finishes and updated when you save corrections. Earlier export "
            "revisions are kept. Export… saves an additional copy wherever you choose."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.open_button(layout, "Open outputs folder", root / "exports")
        self.section(layout, "Meeting working files", self.job_path)
        note = QLabel(
            "Contains decoded audio, checkpoints and corrections. Deleting a meeting moves "
            "this folder, including its saved outputs, to the Trash. Your original recording "
            "and copies exported elsewhere stay in place."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.section(layout, "App data folder", self.data_path)
        self.open_button(layout, "Open app data folder", home())
        self.log_path = path_label(log_path())
        self.section(layout, "Diagnostic log", self.log_path)
        note = QLabel(
            "Records when processing starts, stops or stalls, and why. It contains file "
            "paths but no transcript text. Include it when reporting a problem."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.open_button(layout, "Open log folder", log_path().parent)
        actions = QHBoxLayout()
        actions.addStretch()
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        actions.addWidget(done)
        layout.addLayout(actions)
        # Wrapped paths and notes need more height than the dialog's default size hint.
        layout.activate()
        height = layout.totalHeightForWidth(self.minimumWidth())
        screen = (parent.screen() if parent else None) or QGuiApplication.primaryScreen()
        if screen:
            height = min(height, screen.availableGeometry().height() - 60)
        self.setMinimumHeight(height)

    @staticmethod
    def section(layout, title, path):
        heading = QLabel(title)
        bold = heading.font()
        bold.setBold(True)
        heading.setFont(bold)
        layout.addSpacing(6)
        layout.addWidget(heading)
        layout.addWidget(path)

    @staticmethod
    def open_button(layout, title, directory):
        widget = QPushButton(title)
        widget.setEnabled(directory.is_dir())
        widget.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))))
        layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignLeft)
