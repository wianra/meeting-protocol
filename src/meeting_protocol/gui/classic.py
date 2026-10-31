"""A native, network-blocked desktop interface; no local web server or CDN."""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..export import apply_corrections, describe_flags, export_to_file, export_transcript
from ..jobs import read_config, resolve_job
from ..privacy import home, require_offline
from ..storage import Store, lock
from .common import set_app_icon

STYLE = """
QMainWindow, QWidget { background: #f5f4ef; color: #193438; font-size: 13px; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#eyebrow { color: #357769; font-weight: 700; font-size: 11px; }
QLabel#hint { color: #617773; }
QPushButton { background: #e4eae4; border: 0; border-radius: 7px; padding: 9px 14px; }
QPushButton:hover { background: #d2e0d7; }
QPushButton#primary { background: #225e51; color: white; font-weight: 600; }
QPushButton:disabled { color: #899692; background: #e6e7e1; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background: white; border: 1px solid #d5ddd6;
  border-radius: 5px; padding: 6px; selection-background-color: #c4e5d7; }
QTableWidget, QListWidget { background: #fff; border: 1px solid #dbe1da;
  border-radius: 7px; alternate-background-color: #f5f8f3; }
QTableWidget::item, QListWidget::item { padding: 8px; }
QTableWidget::item:selected, QListWidget::item:selected { background: #d7e9df; color: #193438; }
QHeaderView::section { background: #e9eee7; border: none; padding: 8px; font-weight: 600; }
QProgressBar { border: 0; background: #e0e8df; border-radius: 5px; height: 12px; }
QProgressBar::chunk { background: #39806b; border-radius: 5px; }
"""


class Window(QMainWindow):
    def __init__(self, initial=None):
        super().__init__()
        self.setWindowTitle("Meeting Protocol · Local")
        self.resize(1250, 850)
        self.root = self.transcript = None
        self.pending = ""
        self.errors = ""
        self.dirty = False
        self.loading = False
        self.current_turn_id = None
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.receive)
        self.process.readyReadStandardError.connect(self.receive_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(
            lambda _: self.notice("Could not start the local worker.")
        )
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        sidebar = QVBoxLayout()
        label = QLabel("ON THIS MAC")
        label.setObjectName("eyebrow")
        sidebar.addWidget(label)
        self.job_list = QListWidget()
        self.job_list.setFixedWidth(230)
        self.job_list.currentItemChanged.connect(self.select_job)
        sidebar.addWidget(self.job_list)
        refresh = QPushButton("Refresh meetings")
        refresh.clicked.connect(self.refresh)
        sidebar.addWidget(refresh)
        privacy = QLabel(
            "Audio stays on this Mac.\nNetwork access is blocked.\n\nModel downloads use the CLI."
        )
        privacy.setObjectName("hint")
        sidebar.addWidget(privacy)
        layout.addLayout(sidebar)

        body = QVBoxLayout()
        title = QLabel("Meeting Protocol")
        title.setObjectName("title")
        body.addWidget(title)
        subtitle = QLabel("German · Swiss German → Standard German · French · Italian")
        subtitle.setObjectName("hint")
        body.addWidget(subtitle)
        pick = QHBoxLayout()
        self.source = QLineEdit()
        self.source.setPlaceholderText("Choose a recording on this Mac")
        browse = QPushButton("Choose audio…")
        browse.clicked.connect(self.browse)
        pick.addWidget(self.source, 1)
        pick.addWidget(browse)
        body.addLayout(pick)

        options = QHBoxLayout()
        self.language = QComboBox()
        for name, value in (
            ("Multilingual / auto", "auto"),
            ("German / Swiss German", "de"),
            ("French", "fr"),
            ("Italian", "it"),
        ):
            self.language.addItem(name, value)
        options.addWidget(self.language)
        options.addWidget(QLabel("Speakers"))
        self.minimum, self.maximum = QSpinBox(), QSpinBox()
        for spin in (self.minimum, self.maximum):
            spin.setRange(1, 50)
        self.minimum.setValue(2)
        self.maximum.setValue(10)
        options.addWidget(self.minimum)
        options.addWidget(QLabel("to"))
        options.addWidget(self.maximum)
        self.asr_only = QCheckBox("Text only (no speakers)")
        options.addWidget(self.asr_only)
        options.addStretch()
        body.addLayout(options)
        actions = QHBoxLayout()
        self.start = QPushButton("Transcribe recording")
        self.start.setObjectName("primary")
        self.start.clicked.connect(self.start_job)
        self.resume = QPushButton("Resume")
        self.resume.clicked.connect(lambda: self.resume_job(False))
        self.add_speakers = QPushButton("Add speaker analysis")
        self.add_speakers.clicked.connect(lambda: self.resume_job(True))
        self.pause = QPushButton("Pause")
        self.pause.clicked.connect(self.process.terminate)
        self.pause.setEnabled(False)
        for button in (self.start, self.resume, self.add_speakers, self.pause):
            actions.addWidget(button)
        actions.addStretch()
        body.addLayout(actions)
        self.status = QLabel("Choose a recording or open a saved meeting.")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        body.addWidget(self.progress)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Speaker", "Transcript", "Review"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView

        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 85)
        self.table.setColumnWidth(1, 125)
        self.table.setColumnWidth(3, 110)
        self.table.currentCellChanged.connect(self.select_turn)
        split.addWidget(self.table)

        editor = QWidget()
        edit_layout = QVBoxLayout(editor)
        edit_layout.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.speaker = QComboBox()
        self.speaker.setEditable(True)
        row.addWidget(QLabel("Speaker"))
        row.addWidget(self.speaker)
        self.reviewed = QCheckBox("Reviewed against audio")
        row.addWidget(self.reviewed)
        self.play = QPushButton("Play / pause")
        self.play.clicked.connect(self.toggle_play)
        row.addWidget(self.play)
        self.save = QPushButton("Save correction")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self.save_turn)
        row.addWidget(self.save)
        edit_layout.addLayout(row)
        self.text = QTextEdit()
        self.text.setPlaceholderText("Select a turn to review and correct it.")
        edit_layout.addWidget(self.text)
        self.flags = QLabel()
        self.flags.setWordWrap(True)
        self.flags.setObjectName("hint")
        edit_layout.addWidget(self.flags)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda n: self.seek.setRange(0, int(n)))
        self.player.positionChanged.connect(lambda n: self.seek.setValue(int(n)))
        edit_layout.addWidget(self.seek)
        split.addWidget(editor)
        split.setSizes([350, 230])
        body.addWidget(split, 1)
        export_actions = QHBoxLayout()
        self.export_button = QPushButton("Export…")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.export_file)
        self.open_exports = QPushButton("Open export folder")
        self.open_exports.clicked.connect(self.open_export_folder)
        export_actions.addWidget(self.export_button)
        export_actions.addWidget(self.open_exports)
        export_actions.addStretch()
        body.addLayout(export_actions)
        self.location = QLabel("Word, plain text, JSON and review HTML are saved with each job.")
        self.location.setWordWrap(True)
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.location)
        layout.addLayout(body, 1)
        self.text.textChanged.connect(self.mark_dirty)
        self.speaker.currentTextChanged.connect(self.mark_dirty)
        self.reviewed.toggled.connect(self.mark_dirty)
        self.refresh()
        if initial:
            self.open_job(resolve_job(initial))
        self.set_busy(False)

    def mark_dirty(self, *args):
        if not self.loading and self.current_turn_id:
            self.dirty = True

    def notice(self, message):
        QMessageBox.information(self, "Meeting Protocol", str(message))

    def browse(self):
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Choose local audio",
            "",
            "Audio (*.m4a *.wav *.mp3 *.flac *.aac *.ogg *.mp4);;All files (*)",
        )
        if name:
            self.source.setText(name)

    def refresh(self):
        self.job_list.blockSignals(True)
        self.job_list.clear()
        for file in sorted((home() / "jobs").glob("*/job.json"), key=lambda p: -p.stat().st_mtime):
            cfg = read_config(file.parent)
            item = QListWidgetItem(f"{Path(cfg['input']).name}\n{cfg['job_id'][:8]}")
            item.setData(Qt.ItemDataRole.UserRole, str(file.parent))
            self.job_list.addItem(item)
        self.job_list.blockSignals(False)

    def select_job(self, item, old=None):
        if item:
            if self.dirty and not self.save_turn():
                return
            self.open_job(Path(item.data(Qt.ItemDataRole.UserRole)))

    def open_job(self, root):
        self.root = root
        cfg = read_config(root)
        self.job_list.blockSignals(True)
        item = next(
            (
                self.job_list.item(i)
                for i in range(self.job_list.count())
                if self.job_list.item(i).data(Qt.ItemDataRole.UserRole) == str(root)
            ),
            None,
        )
        if item is None:
            item = QListWidgetItem(f"{Path(cfg['input']).name}\n{cfg['job_id'][:8]}")
            item.setData(Qt.ItemDataRole.UserRole, str(root))
            self.job_list.addItem(item)
        self.job_list.setCurrentItem(item)
        self.job_list.blockSignals(False)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(cfg["input"]))
        self.source.setText(cfg["input"])
        self.current_turn_id = None
        self.table.setRowCount(0)
        self.transcript = None
        raw = root / "transcript.raw.json"
        if raw.exists():
            store = Store(root)
            try:
                self.transcript = apply_corrections(
                    json.loads(raw.read_text()), store.corrections()
                )
            finally:
                store.close()
            self.table.setRowCount(len(self.transcript["turns"]))
            for index, turn in enumerate(self.transcript["turns"]):
                start = int(turn["start"])
                values = [
                    f"{start // 60:02}:{start % 60:02}",
                    turn["speaker"],
                    turn["text"],
                    "Reviewed" if turn["reviewed"] else "Check" if turn["flags"] else "Draft",
                ]
                for col, value in enumerate(values):
                    self.table.setItem(index, col, QTableWidgetItem(value))
            issue_count = len(self.transcript["issues"])
            self.status.setText(
                f"Saved draft · {len(self.transcript['turns'])} turns · "
                f"{issue_count} audio passages to check"
            )
            if issue_count:
                self.status.setToolTip(
                    "\n".join(
                        f"{i['start']:.1f}s: {i['message']}" for i in self.transcript["issues"]
                    )
                )
        else:
            self.status.setText("This meeting has saved progress. Resume to finish processing.")
        self.location.setText(f"Exports: {root / 'exports'}")
        self.set_busy(self.process.state() != QProcess.ProcessState.NotRunning)

    def select_turn(self, row, col, previous_row, previous_col):
        if not self.transcript or row < 0:
            return
        if self.dirty and not self.save_turn():
            return
        turn = self.transcript["turns"][row]
        self.loading = True
        self.current_turn_id = turn["id"]
        self.speaker.clear()
        self.speaker.addItems(sorted({t["speaker"] for t in self.transcript["turns"]}))
        self.speaker.setCurrentText(turn["speaker"])
        self.text.setPlainText(turn["text"])
        self.reviewed.setChecked(turn["reviewed"])
        self.flags.setText(describe_flags(turn["flags"]) or "Draft: listen to verify the wording.")
        self.player.setPosition(int(turn["start"] * 1000))
        self.loading, self.dirty = False, False

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def save_turn(self):
        if not self.current_turn_id or not self.root:
            return True
        text, speaker = self.text.toPlainText().strip(), self.speaker.currentText().strip()
        if not text or not speaker or any(c in speaker for c in '\r\n:"'):
            self.notice("Enter text and a single-line speaker label without quotes or colons.")
            return False
        store = Store(self.root)
        try:
            with lock(self.root / ".lock"):
                store.correction(self.current_turn_id, text, speaker, self.reviewed.isChecked())
                raw = json.loads((self.root / "transcript.raw.json").read_text())
                self.transcript = export_transcript(store, raw)
            for row, turn in enumerate(self.transcript["turns"]):
                if turn["id"] == self.current_turn_id:
                    self.table.item(row, 1).setText(speaker)
                    self.table.item(row, 2).setText(text)
                    self.table.item(row, 3).setText("Reviewed" if turn["reviewed"] else "Draft")
            self.dirty = False
            return True
        except Exception as exc:  # noqa: BLE001 -- show worker/storage errors in the desktop UI.
            self.notice(exc)
            return False
        finally:
            store.close()

    def set_busy(self, busy):
        self.start.setEnabled(not busy)
        self.resume.setEnabled(not busy and self.root is not None)
        self.add_speakers.setEnabled(
            not busy and self.root is not None and read_config(self.root)["asr_only"]
        )
        self.pause.setEnabled(busy)
        self.job_list.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.save.setEnabled(not busy and self.transcript is not None)
        self.export_button.setEnabled(not busy and self.transcript is not None)
        self.open_exports.setEnabled(not busy and self.transcript is not None)
        self.text.setReadOnly(busy)

    def export_file(self):
        if not self.root or self.transcript is None:
            return
        if self.dirty and not self.save_turn():
            return
        formats = {
            "Word document (*.docx)": ".docx",
            "Plain text (*.txt)": ".txt",
            "Review report (*.html)": ".html",
            "Structured transcript (*.json)": ".json",
        }
        stem = Path(read_config(self.root)["input"]).stem
        filename, selected = QFileDialog.getSaveFileName(
            self,
            "Export corrected transcript",
            str(self.root / "exports" / f"{stem}-transcript.docx"),
            ";;".join(formats),
            "Word document (*.docx)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not filename:
            return
        destination = Path(filename)
        suffix = formats.get(selected, ".docx")
        if destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)
        if (
            destination.exists()
            and QMessageBox.question(
                self,
                "Replace existing file?",
                f"Replace {destination.name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        store = Store(self.root)
        try:
            with lock(self.root / ".lock"):
                raw = json.loads((self.root / "transcript.raw.json").read_text())
                self.transcript = export_to_file(store, raw, destination)
            self.location.setText(f"Exported: {destination}")
        except Exception as exc:  # noqa: BLE001 -- display local filesystem/export failures.
            self.notice(exc)
        finally:
            store.close()

    def open_export_folder(self):
        if not self.root or self.transcript is None:
            return
        if self.dirty and not self.save_turn():
            return
        store = Store(self.root)
        try:
            with lock(self.root / ".lock"):
                raw = json.loads((self.root / "transcript.raw.json").read_text())
                self.transcript = export_transcript(store, raw)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root / "exports"))):
                self.notice(f"Open this folder in Finder: {self.root / 'exports'}")
        except Exception as exc:  # noqa: BLE001 -- display local filesystem/export failures.
            self.notice(exc)
        finally:
            store.close()

    def begin(self, args):
        if self.dirty and not self.save_turn():
            return
        self.player.stop()
        self.pending, self.errors = "", ""
        self.set_busy(True)
        self.status.setText("Verifying local input and model files…")
        self.progress.setRange(0, 0)
        self.process.start(sys.executable, ["-m", "meeting_protocol.cli", *args])

    def start_job(self):
        if not self.source.text().strip():
            self.browse()
            if not self.source.text().strip():
                return
        args = [
            "transcribe",
            self.source.text().strip(),
            "--language",
            self.language.currentData(),
            "--min-speakers",
            str(self.minimum.value()),
            "--max-speakers",
            str(self.maximum.value()),
        ]
        if self.asr_only.isChecked():
            args.append("--asr-only")
        self.begin(args)

    def resume_job(self, add):
        if self.root:
            self.begin(["resume", str(self.root), *(["--add-speakers"] if add else [])])

    def receive(self):
        self.pending += bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if "job" in event:
                self.root = Path(event["job"])
            if "stage" in event:
                total = event.get("total", 0)
                self.progress.setRange(0, total)
                self.progress.setValue(event.get("done", 0))
                self.status.setText(
                    f"{event['stage'].replace('_', ' ').title()} · {event.get('message', '')}"
                )

    def receive_errors(self):
        self.errors = (
            self.errors
            + bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        )[-3000:]

    def finished(self, code, status):
        self.receive()
        self.receive_errors()
        self.refresh()
        if self.root:
            self.open_job(self.root)
        self.set_busy(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if code == 0 else 0)
        if code != 0:
            self.status.setText("Stopped. Completed checkpoints are saved.")
            if code != 130:
                self.notice(self.errors or "The worker stopped. Resume to retry saved work.")

    def closeEvent(self, event):
        if self.dirty and not self.save_turn():
            event.ignore()
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(7000):
                event.ignore()
                self.notice("Waiting for the worker to stop safely. Try closing again shortly.")
                return
        self.player.stop()
        event.accept()


def launch(initial=None):
    require_offline()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Meeting Protocol")
    set_app_icon(app)
    app.setFont(QFont("Helvetica Neue", 13))
    app.setStyleSheet(STYLE)
    window = Window(initial)
    window.show()
    sys.exit(app.exec())
