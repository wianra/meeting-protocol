"""First-run setup for the packaged app: a one-time download of the speech model.

Runs before the network sandbox, so it never opens recordings or jobs. It only starts
`provision asr` and shows how much has arrived.
"""

import sys

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..compat import stop_supervisor
from ..models import ASR_BYTES
from ..privacy import home
from .common import DEVICE, ICON, set_app_icon
from .main import STYLE, button, font, label

WIDTH = 520


def folder_bytes(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def gigabytes(n):
    return f"{n / 1e9:.1f} GB"


class Setup(QWidget):
    def __init__(self):
        super().__init__()
        self.ok = False
        self.errors = ""
        self.setObjectName("main")
        self.setWindowTitle("Meeting Protocol")
        self.setFixedWidth(WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON)).pixmap(56, 56))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        intro = QVBoxLayout()
        intro.setSpacing(6)
        intro.addWidget(label("Set up Meeting Protocol", 20, weight=QFont.Weight.Bold))
        intro.addWidget(
            label(
                f"Meeting Protocol transcribes meetings on this {DEVICE}. It needs a one-time "
                f"download of the speech model ({gigabytes(ASR_BYTES)}). After that it works "
                f"offline, and recordings never leave this {DEVICE}.",
                14,
                wrap=True,
            )
        )
        head.addLayout(intro, 1)
        layout.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = label("", 13, "muted", wrap=True)
        self.status.hide()
        layout.addWidget(self.status)
        layout.addSpacing(6)
        actions = QHBoxLayout()
        actions.addStretch()
        self.quit_button = button("Quit")
        self.quit_button.clicked.connect(self.close)
        self.start_button = button("Download", "primary")
        self.start_button.clicked.connect(self.start)
        actions.addWidget(self.quit_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)

        self.process = QProcess(self)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.fit()

    def fit(self):
        # Wrapped labels make Qt overestimate the height; size to the content at this width.
        self.setFixedHeight(self.layout().totalHeightForWidth(WIDTH))

    def start(self):
        self.errors = ""
        self.start_button.setEnabled(False)
        self.start_button.setText("Downloading…")
        self.progress.show()
        self.status.show()
        self.status.setText("Starting the download…")
        self.fit()
        self.process.start(
            sys.executable, ["-m", "meeting_protocol.cli", "provision", "asr", "--tested"]
        )
        self.timer.start(500)

    def tick(self):
        done = min(folder_bytes(home() / "models" / "asr"), ASR_BYTES)
        self.progress.setValue(int(done / ASR_BYTES * 1000))
        self.status.setText(
            f"{gigabytes(done)} of {gigabytes(ASR_BYTES)}. "
            "If you quit, the download continues from here next time."
        )

    def read_errors(self):
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self.errors = (self.errors + text)[-2000:]

    def finished(self, code, _status):
        self.timer.stop()
        if code == 0:
            self.ok = True
            self.close()
            return
        self.start_button.setEnabled(True)
        self.start_button.setText("Try again")
        last = self.errors.strip().splitlines()[-1:] or ["The download stopped."]
        self.status.setText(
            f"{last[0]}\nCheck the internet connection and try again. Finished parts are kept."
        )
        self.fit()

    def closeEvent(self, event):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            stop_supervisor(self.process)
            self.process.waitForFinished(5000)
        event.accept()


def run_setup():
    """Show setup until the model is installed; True if the app can continue."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Meeting Protocol")
    set_app_icon(app)
    app.setFont(font(14))
    app.setStyleSheet(STYLE)
    window = Setup()
    window.show()
    app.exec()
    return window.ok
