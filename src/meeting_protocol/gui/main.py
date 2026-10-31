"""Main desktop window: meetings on the left; player and transcript in the centre.

Read top to bottom: pick a meeting, listen, click a time to jump there, click a turn to
correct it, mark uncertain turns as checked, export. Storage, corrections, exports and
processing are shared with the classic window (`gui/classic.py`); only the interface differs.
"""

import html
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..export import apply_corrections, describe_flags, export_to_file, export_transcript
from ..jobs import read_config, resolve_job
from ..privacy import home, require_offline
from ..storage import Store, lock
from .common import restore_job, set_app_icon, trash_job

BG = "#f6f6f4"
CARD = "#ffffff"
LINE = "#e2e2de"
CONTROL = "#d6d6d1"
HOVER = "#ececea"
SOFT = "#fafaf8"
TEXT = "#1c1e21"
MUTED = "#6b7078"
ACCENT = "#3948ac"
ACCENT_DARK = "#2f3c94"
ACCENT_TINT = "#eef0fa"
WAVE = "#c9c9c4"
WARN_TINT = "#fde8d8"
WARN_TEXT = "#8a3b0c"
OK_TINT = "#e1eee5"
OK_TEXT = "#1f5a33"
DANGER = "#b42318"
DANGER_DARK = "#912018"
DANGER_TINT = "#fbe4e1"
SPEAKER_FILLS = ["#1c1e21", "#9aa0a8", "#5f646c", "#c9c9c4", "#3f4249", "#b4b8be"]
UNKNOWN = "Speaker Unknown"
TIME_W, SPEAKER_W, STATUS_W, GAP, PAD = 64, 120, 92, 14, 16
HINTS = "Click a time to play from there   ·   Click text to edit   ·   Space play / pause   ·   ⌘↵ mark as checked   ·   Esc close"

STYLE = f"""
QMainWindow, QWidget#main {{ background: {BG}; }}
QWidget {{ color: {TEXT}; }}
QFrame#sidebar {{ background: {BG}; border: 0; border-right: 1px solid {LINE}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px; }}
QScrollArea#list {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px; }}
QWidget#rows {{ background: {CARD}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#caption {{ color: {MUTED}; }}
QLabel#why {{ color: {WARN_TEXT}; }}
QLabel#pillCheck {{ background: {WARN_TINT}; color: {WARN_TEXT}; border-radius: 9px; padding: 1px 8px; }}
QLabel#pillOk {{ background: {OK_TINT}; color: {OK_TEXT}; border-radius: 9px; padding: 1px 8px; }}
QLabel#pillDraft {{ background: {HOVER}; color: #5f646c; border-radius: 9px; padding: 1px 8px; }}
QPushButton {{ background: {CARD}; color: {TEXT}; border: 1px solid {CONTROL}; border-radius: 6px;
  padding: 0 14px; min-height: 32px; font-weight: 600; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:disabled {{ color: #a2a6ac; background: {SOFT}; border-color: {LINE}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #b9bfe0; border-color: #b9bfe0; }}
QPushButton#ghost {{ border-color: transparent; background: transparent; }}
QPushButton#ghost:hover {{ background: {HOVER}; }}
QPushButton#small {{ min-height: 26px; padding: 0 10px; font-size: 12px; }}
QPushButton#play {{ background: {TEXT}; border-color: {TEXT}; color: #ffffff; border-radius: 20px;
  min-height: 40px; max-height: 40px; min-width: 40px; max-width: 40px; padding: 0; }}
QPushButton#play:hover {{ background: #3f4249; }}
QPushButton#segLeft, QPushButton#segRight {{ min-height: 28px; padding: 0 12px; font-size: 12px; }}
QPushButton#segLeft {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton#segRight {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: 0; }}
QPushButton#segLeft:checked, QPushButton#segRight:checked {{ background: {TEXT}; color: #ffffff;
  border-color: {TEXT}; }}
QPushButton#danger {{ background: {DANGER}; border-color: {DANGER}; color: #ffffff; }}
QPushButton#danger:hover {{ background: {DANGER_DARK}; }}
QPushButton#toastUndo {{ background: transparent; color: #ffffff; border-color: #5f646c;
  min-height: 26px; padding: 0 10px; font-size: 12px; }}
QPushButton#toastUndo:hover {{ background: #3f4249; }}
QFrame#toast {{ background: {TEXT}; border-radius: 8px; }}
QLabel#toastText {{ color: #ffffff; }}
QFrame#keep {{ background: {BG}; border-radius: 6px; }}
QPushButton#time {{ border: 0; background: transparent; color: {ACCENT}; padding: 0; min-height: 0;
  text-align: left; font-weight: 400; text-decoration: underline; }}
QPushButton#time:hover {{ color: {ACCENT_DARK}; }}
QListWidget#jobs {{ background: transparent; border: 0; outline: none; }}
QListWidget#jobs::item {{ padding: 0; margin: 1px 0; border-radius: 6px; color: {TEXT}; }}
QListWidget#jobs::item:hover {{ background: {HOVER}; }}
QListWidget#jobs::item:selected {{ background: {CARD}; border: 1px solid {CONTROL}; color: {TEXT}; }}
QTextEdit#editor, QLineEdit, QComboBox, QSpinBox {{ background: {CARD}; border: 1px solid {CONTROL};
  border-radius: 6px; padding: 6px 8px; selection-background-color: {ACCENT}; }}
QTextEdit#editor:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
  border: 1px solid {ACCENT}; }}
QProgressBar {{ border: 0; background: {HOVER}; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {CONTROL}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


# -- helpers --------------------------------------------------------------------------------
def font(size, weight=QFont.Weight.Normal):
    result = QFont()
    result.setFamilies(["SF Pro Text", "Helvetica Neue", "Arial"])
    result.setPixelSize(size)
    result.setWeight(weight)
    return result


def label(text="", size=14, name=None, weight=QFont.Weight.Normal, wrap=False):
    widget = QLabel(text)
    widget.setFont(font(size, weight))
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, name=None, size=13, tip=None):
    widget = QPushButton(text)
    widget.setFont(font(size, QFont.Weight.DemiBold))
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    # Buttons must not swallow Space: that key belongs to play / pause.
    widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if name:
        widget.setObjectName(name)
    if tip:
        widget.setToolTip(tip)
        widget.setAccessibleName(tip)
    return widget


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02}"


def needs_check(turn):
    return bool(turn["flags"]) and not turn["reviewed"]


def status_of(turn):
    if needs_check(turn):
        return "Check", "pillCheck"
    if turn["reviewed"]:
        return "Checked", "pillOk"
    return "Draft", "pillDraft"


def load_transcript(root):
    raw = root / "transcript.raw.json"
    if not raw.exists():
        return None
    store = Store(root)
    try:
        return apply_corrections(json.loads(raw.read_text()), store.corrections())
    finally:
        store.close()


def envelope(root, bins=180):
    """Loudness per bin from the job's 16 kHz int16 PCM view; None if it is not there."""
    try:
        import numpy as np

        pcm = root / "audio.pcm"
        if not pcm.exists() or pcm.stat().st_size < bins * 4:
            return None
        samples = np.memmap(pcm, dtype="<i2", mode="r")
        usable = len(samples) - len(samples) % bins
        chunks = np.abs(samples[:usable].reshape(bins, -1).astype(np.float32))
        level = np.sqrt((chunks**2).mean(axis=1))
        top = float(np.percentile(level, 98)) or 1.0
        return [min(1.0, float(v) / top) for v in level]
    except Exception:  # noqa: BLE001 -- the waveform is decoration; never block review on it.
        return None


# -- widgets --------------------------------------------------------------------------------
class Toggle(QAbstractButton):
    """A small labelled switch."""

    def __init__(self, text, checked=True):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setText(text)
        self.setFont(font(12, QFont.Weight.DemiBold))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggled.connect(self.update)

    def sizeHint(self):
        width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(width + 24 + 8 + 22, 30)

    def paintEvent(self, event):
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(ACCENT if on else CONTROL), 1))
        painter.setBrush(QColor(ACCENT_TINT if on else CARD))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        track = QRectF(7, (self.height() - 14) / 2, 24, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT if on else CONTROL))
        painter.drawRoundedRect(track, 7, 7)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(track.x() + (12 if on else 2), track.y() + 2, 10, 10))
        painter.setPen(QColor(ACCENT if on else MUTED))
        painter.setFont(self.font())
        painter.drawText(
            QRectF(track.right() + 8, 0, self.width(), self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )


class Waveform(QWidget):
    """Loudness bars over who-spoke-when. Click or drag to jump."""

    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Recording timeline. Click to jump.")
        self.levels, self.spans, self.duration, self.position = None, [], 1.0, 0.0

    def set_data(self, levels, spans, duration):
        self.levels, self.spans = levels, spans
        self.duration = max([duration or 0, *(end for _, end, _ in spans), 1.0])
        self.update()

    def set_position(self, seconds):
        self.position = seconds
        self.update()

    def jump(self, event):
        x = min(max(0.0, event.position().x()), float(self.width()))
        self.seek.emit(x / max(1, self.width()) * self.duration)

    def mousePressEvent(self, event):
        self.jump(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.jump(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        width, wave_h = self.width(), 36.0
        bins = len(self.levels) if self.levels else max(40, width // 5)
        step = width / bins
        played = self.position / self.duration * width
        for i in range(bins):
            if self.levels:
                level = self.levels[i]
            else:
                t = (i + 0.5) / bins * self.duration
                level = 0.55 if any(a <= t <= b for a, b, _ in self.spans) else 0.05
            h = max(2.0, level * wave_h)
            x = i * step
            color = ACCENT if x + step / 2 <= played else WAVE
            painter.fillRect(
                QRectF(x + 0.5, (wave_h - h) / 2, max(1.0, step - 1.5), h), QColor(color)
            )
        for start, end, index in self.spans:
            rect = QRectF(start / self.duration * width, wave_h + 6, 0, 6)
            rect.setWidth(max(2.0, (end - start) / self.duration * width))
            fill = SPEAKER_FILLS[index % len(SPEAKER_FILLS)] if index >= 0 else CARD
            painter.fillRect(rect, QColor(fill))
            if index < 0:
                painter.setPen(QPen(QColor(MUTED), 1))
                painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.fillRect(QRectF(min(width - 2.0, max(0.0, played - 1)), 0, 2, 48), QColor(TEXT))


class Swatch(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(9, 9)
        self.index = 0

    def set_index(self, index):
        self.index = index
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.index >= 0:
            painter.fillRect(self.rect(), QColor(SPEAKER_FILLS[self.index % len(SPEAKER_FILLS)]))
        else:
            painter.fillRect(self.rect(), QColor(CARD))
            painter.setPen(QColor(MUTED))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class AutoText(QTextEdit):
    """Plain-text editor that grows with its content."""

    def __init__(self):
        super().__init__()
        self.setObjectName("editor")
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self.fit)

    def fit(self):
        self.document().setTextWidth(self.viewport().width())
        self.setFixedHeight(max(64, int(self.document().size().height()) + 18))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()


def grid_row(margins=(PAD, 12, PAD, 12)):
    row = QHBoxLayout()
    row.setContentsMargins(*margins)
    row.setSpacing(GAP)
    return row


class TurnRow(QFrame):
    clicked = Signal(object)
    seek = Signal(object)
    play = Signal(object)
    check = Signal(object)
    done = Signal(object)
    edited = Signal(object)

    def __init__(self, owner, turn):
        super().__init__()
        self.owner, self.turn = owner, turn
        self.selected = self.playing = self.dirty = self.loading = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        layout = grid_row()

        self.time = button(clock(turn["start"]), "time", 12, f"Play from {clock(turn['start'])}")
        self.time.setFixedWidth(TIME_W)
        self.time.clicked.connect(lambda: self.seek.emit(self))
        layout.addWidget(self.time, 0, Qt.AlignmentFlag.AlignTop)

        speaker_box = QWidget()
        speaker_box.setFixedWidth(SPEAKER_W)
        speaker_layout = QVBoxLayout(speaker_box)
        speaker_layout.setContentsMargins(0, 2, 0, 0)
        name_row = QHBoxLayout()
        name_row.setSpacing(7)
        self.swatch = Swatch()
        self.name = label(turn["speaker"], 13, weight=QFont.Weight.DemiBold)
        name_row.addWidget(self.swatch)
        name_row.addWidget(self.name, 1)
        self.name_widget = QWidget()
        self.name_widget.setLayout(name_row)
        name_row.setContentsMargins(0, 0, 0, 0)
        speaker_layout.addWidget(self.name_widget)
        self.speaker = QComboBox()
        self.speaker.setEditable(True)
        self.speaker.setFont(font(13))
        self.speaker.setAccessibleName("Speaker")
        self.speaker.currentTextChanged.connect(self.mark_dirty)
        speaker_layout.addWidget(self.speaker)
        speaker_layout.addStretch()
        layout.addWidget(speaker_box, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(10)
        self.read = label("", 15, wrap=True)
        self.read.setTextFormat(Qt.TextFormat.RichText)
        self.read.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        body.addWidget(self.read)
        self.editor = AutoText()
        self.editor.setFont(font(15))
        self.editor.setAccessibleName("Transcript text")
        self.editor.textChanged.connect(self.mark_dirty)
        body.addWidget(self.editor)
        self.why = label("", 12, "why", wrap=True)
        body.addWidget(self.why)
        self.actions = QWidget()
        actions = QHBoxLayout(self.actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.play_button = button("▶  Play this turn", "small", 12)
        self.play_button.clicked.connect(lambda: self.play.emit(self))
        actions.addWidget(self.play_button)
        self.check_button = button("✓  Mark as checked", "small", 12)
        self.check_button.clicked.connect(lambda: self.check.emit(self))
        actions.addWidget(self.check_button)
        actions.addStretch()
        self.hint = label("", 12, "caption")
        actions.addWidget(self.hint)
        close = button("Done", "small", 12)
        close.setObjectName("ghost")
        close.clicked.connect(lambda: self.done.emit(self))
        actions.addWidget(close)
        body.addWidget(self.actions)
        layout.addLayout(body, 1)

        self.pill = label("", 11, weight=QFont.Weight.DemiBold)
        status_box = QWidget()
        status_box.setFixedWidth(STATUS_W)
        status_layout = QHBoxLayout(status_box)
        status_layout.setContentsMargins(0, 2, 0, 0)
        status_layout.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        status_layout.addStretch()
        layout.addWidget(status_box, 0, Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)
        self.refresh()
        self.set_selected(False)

    def mark_dirty(self, *args):
        if not self.loading and self.selected:
            self.dirty = True
            self.edited.emit(self)

    def current_text(self):
        return self.editor.toPlainText().strip() if self.selected else self.turn["text"]

    def current_speaker(self):
        return self.speaker.currentText().strip() if self.selected else self.turn["speaker"]

    def refresh(self):
        self.name.setText(self.turn["speaker"])
        self.swatch.set_index(self.owner.speaker_index(self.turn["speaker"]))
        self.read.setText(self.rich_text())
        text, name = status_of(self.turn)
        self.pill.setText(text)
        self.pill.setObjectName(name)
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        reason = describe_flags(self.turn["flags"])
        self.why.setText(f"{reason}." if reason else "")
        self.why.setVisible(self.selected and needs_check(self.turn))
        self.check_button.setVisible(needs_check(self.turn))

    def rich_text(self):
        """Uncertain words are tinted while the model's own wording stands."""
        words = self.turn.get("words") or []
        if words and "".join(w.get("text", "") for w in words).split() == self.turn["text"].split():
            parts = []
            for word in words:
                text = html.escape(word.get("text", ""))
                if "low_word_confidence" in word.get("flags", []) and needs_check(self.turn):
                    lead = " " if text.startswith(" ") else ""
                    text = (
                        f'{lead}<span style="background-color:{WARN_TINT};">{text.strip()}</span>'
                    )
                parts.append(text)
            body = "".join(parts).strip()
        else:
            body = html.escape(self.turn["text"])
        return f'<p style="line-height:150%; margin:0;">{body}</p>'

    def set_selected(self, selected):
        self.selected = selected
        self.loading = True
        if selected:
            self.editor.setPlainText(self.turn["text"])
            self.speaker.clear()
            self.speaker.addItems(self.owner.speaker_labels())
            self.speaker.setCurrentText(self.turn["speaker"])
            self.hint.setText(
                "Auto-play on · saves when you move on"
                if self.owner.autoplay.isChecked()
                else "Saves when you move on"
            )
        self.loading = False
        self.dirty = False
        self.read.setVisible(not selected)
        self.name_widget.setVisible(not selected)
        self.editor.setVisible(selected)
        self.speaker.setVisible(selected)
        self.actions.setVisible(selected)
        self.why.setVisible(selected and needs_check(self.turn))
        self.setCursor(Qt.CursorShape.ArrowCursor if selected else Qt.CursorShape.IBeamCursor)
        if selected:
            QTimer.singleShot(0, self.focus_editor)
        self.update()

    def focus_editor(self):
        self.editor.fit()
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    def set_playing(self, playing):
        if playing != self.playing:
            self.playing = playing
            self.update()

    def mousePressEvent(self, event):
        if not self.selected:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        if self.selected:
            painter.fillRect(rect, QColor(CARD))
            painter.setPen(QPen(QColor(TEXT), 1))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.fillRect(0, 0, 3, rect.height(), QColor(TEXT))
            return
        if self.playing:
            painter.fillRect(rect, QColor(ACCENT_TINT))
            painter.fillRect(0, 0, 3, rect.height(), QColor(ACCENT))
        elif self.underMouse():
            painter.fillRect(rect, QColor(SOFT))
        painter.fillRect(0, rect.height() - 1, rect.width(), 1, QColor(HOVER))


class TrashButton(QAbstractButton):
    """The design's bin icon. Framed in the header; bare in the meeting list."""

    def __init__(self, tip, framed=False):
        super().__init__()
        self.framed = framed
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(QSize(34, 34) if framed else QSize(28, 28))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        hover = self.underMouse() and self.isEnabled()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.framed:
            painter.setPen(QPen(QColor(LINE if not self.isEnabled() else CONTROL), 1))
            painter.setBrush(QColor(HOVER if hover else SOFT if not self.isEnabled() else CARD))
            painter.drawRoundedRect(rect, 6, 6)
        elif hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DANGER_TINT))
            painter.drawRoundedRect(rect, 6, 6)
        color = "#a2a6ac" if not self.isEnabled() else DANGER if hover else MUTED
        if self.framed and self.isEnabled() and not hover:
            color = TEXT
        path = QPainterPath()
        for points in (
            [(2.5, 4), (13.5, 4)],
            [(6, 4), (6, 2.5), (10, 2.5), (10, 4)],
            [(4, 4), (4.7, 13.5), (11.3, 13.5), (12, 4)],
            [(6.6, 6.5), (6.6, 11)],
            [(9.4, 6.5), (9.4, 11)],
        ):
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)
        painter.translate((self.width() - 16) / 2, (self.height() - 16) / 2)
        painter.setPen(QPen(QColor(color), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class JobRow(QWidget):
    """One meeting in the sidebar. The bin shows on hover and on the open meeting."""

    trash = Signal(str)

    def __init__(self, root, name, meta):
        super().__init__()
        self.root = str(root)
        self.selected = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 6, 9)
        layout.setSpacing(4)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.name = label(name, 13)
        self.meta = label(meta, 12, "muted")
        for widget in (self.name, self.meta):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text.addWidget(self.name)
        text.addWidget(self.meta)
        layout.addLayout(text, 1)
        self.bin = TrashButton(f"Delete {name}")
        self.bin.clicked.connect(lambda: self.trash.emit(self.root))
        keep = self.bin.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        self.bin.setSizePolicy(keep)
        layout.addWidget(self.bin, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_bin()

    def set_text(self, name, meta):
        self.name.setText(name)
        self.meta.setText(meta)

    def set_selected(self, selected):
        self.selected = selected
        self.name.setFont(font(13, QFont.Weight.DemiBold if selected else QFont.Weight.Normal))
        self.refresh_bin()

    def refresh_bin(self):
        self.bin.setVisible(self.selected or self.underMouse() or self.bin.hasFocus())

    def enterEvent(self, event):
        self.bin.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.refresh_bin()
        super().leaveEvent(event)


class DeleteDialog(QDialog):
    """Confirms moving a meeting to the Trash. Cancel is the default; Esc cancels."""

    def __init__(self, parent, name):
        super().__init__(parent)
        self.setWindowTitle("Delete meeting")
        self.setModal(True)
        self.setFixedWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(
            label(f"Delete \u201c{name}\u201d?", 18, weight=QFont.Weight.Bold, wrap=True)
        )
        layout.addWidget(
            label(
                "The transcript, your corrections and the exports saved with this meeting "
                "move to the Trash. You can put them back from there.",
                14,
                wrap=True,
            )
        )
        keep = QFrame()
        keep.setObjectName("keep")
        kept = QVBoxLayout(keep)
        kept.setContentsMargins(12, 10, 12, 10)
        kept.setSpacing(6)
        for text in (
            "\u2713  The recording itself stays where it is.",
            "\u2713  Files you exported to other folders are not touched.",
        ):
            kept.addWidget(label(text, 13, wrap=True))
        layout.addWidget(keep)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        actions.addStretch()
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        confirm = button("Move to Trash", "danger")
        confirm.clicked.connect(self.accept)
        for widget in (cancel, confirm):
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            actions.addWidget(widget)
        cancel.setDefault(True)
        cancel.setFocus()
        layout.addLayout(actions)


class Toast(QFrame):
    """Bottom-centre notice with Undo; hides itself after a few seconds."""

    undo = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(14)
        self.text = label("", 13, "toastText")
        layout.addWidget(self.text)
        undo = button("Undo", "toastUndo", 12)
        undo.clicked.connect(self.undo.emit)
        layout.addWidget(undo)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text, seconds=7):
        self.text.setText(text)
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.timer.start(seconds * 1000)

    def place(self):
        area = self.parentWidget().rect()
        self.move((area.width() - self.width()) // 2, area.height() - self.height() - 24)


class NewRecording(QDialog):
    """Choose a recording and the few settings that matter, then transcribe."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("New recording")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Transcribe a recording", 18, weight=QFont.Weight.Bold))
        layout.addWidget(
            label(
                "German and Swiss German are written as Standard German. French and Italian "
                "stay as spoken. Nothing leaves this Mac.",
                13,
                "muted",
                wrap=True,
            )
        )
        pick = QHBoxLayout()
        self.source = QLineEdit()
        self.source.setPlaceholderText("Choose a recording on this Mac")
        pick.addWidget(self.source, 1)
        browse = button("Choose…")
        browse.clicked.connect(self.browse)
        pick.addWidget(browse)
        layout.addLayout(pick)
        options = QHBoxLayout()
        options.setSpacing(10)
        self.language = QComboBox()
        for name, value in (
            ("Detect per passage", "auto"),
            ("German / Swiss German", "de"),
            ("French", "fr"),
            ("Italian", "it"),
        ):
            self.language.addItem(name, value)
        options.addWidget(label("Language", 13, "muted"))
        options.addWidget(self.language)
        options.addSpacing(10)
        options.addWidget(label("Speakers", 13, "muted"))
        self.minimum, self.maximum = QSpinBox(), QSpinBox()
        for spin, value in ((self.minimum, 2), (self.maximum, 10)):
            spin.setRange(1, 50)
            spin.setValue(value)
        options.addWidget(self.minimum)
        options.addWidget(label("to", 13, "muted"))
        options.addWidget(self.maximum)
        options.addStretch()
        layout.addLayout(options)
        self.asr_only = QCheckBox("Text only for now (add speakers later)")
        layout.addWidget(self.asr_only)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        go = button("Transcribe", "primary")
        go.clicked.connect(self.accept_if_ready)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        layout.addLayout(buttons)

    def browse(self):
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Choose local audio",
            "",
            "Audio (*.m4a *.wav *.mp3 *.flac *.aac *.ogg *.mp4);;All files (*)",
        )
        if name:
            self.source.setText(name)

    def accept_if_ready(self):
        if not self.source.text().strip():
            self.browse()
        if self.source.text().strip():
            self.accept()

    def arguments(self):
        args = [
            "transcribe",
            self.source.text().strip(),
            "--language",
            self.language.currentData(),
            "--min-speakers",
            str(self.minimum.value()),
            "--max-speakers",
            str(max(self.minimum.value(), self.maximum.value())),
        ]
        if self.asr_only.isChecked():
            args.append("--asr-only")
        return args


# -- window ---------------------------------------------------------------------------------
class Window(QMainWindow):
    def __init__(self, initial=None):
        super().__init__()
        self.setWindowTitle("Meeting Protocol")
        self.resize(1280, 860)
        self.root = self.transcript = self.selected = None
        self.rows, self.filter, self.stop_at, self.duration = [], False, None, 0.0
        self.playing_row = None
        self.pending, self.errors = "", ""

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
        self.player.positionChanged.connect(self.on_position)
        self.player.playbackStateChanged.connect(self.on_playback)

        central = QWidget()
        central.setObjectName("main")
        self.setCentralWidget(central)
        page = QHBoxLayout(central)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self.build_sidebar())
        page.addLayout(self.build_main(), 1)

        for keys, handler in (
            ("Ctrl+Return", self.check_selected),
            ("Ctrl+Enter", self.check_selected),
            ("Escape", self.close_selected),
        ):
            QShortcut(QKeySequence(keys), self, activated=handler)

        self.toast = Toast(central)
        self.toast.undo.connect(self.undo_delete)
        self.trashed = None

        self.refresh_jobs()
        root = resolve_job(initial) if initial else self.first_job()
        if root:
            self.open_job(root)
        else:
            self.show_empty()
        self.set_busy(False)

    # -- layout ----------------------------------------------------------------------------
    def build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 0, 0)
        title = label("MEETINGS", 11, "muted", QFont.Weight.Bold)
        title.setAccessibleName("Meetings")
        head.addWidget(title)
        head.addStretch()
        self.new_button = button("+ New", "small", 12, "Transcribe a new recording")
        self.new_button.clicked.connect(self.new_recording)
        head.addWidget(self.new_button)
        layout.addLayout(head)
        self.job_list = QListWidget()
        self.job_list.setObjectName("jobs")
        self.job_list.setFont(font(13))
        self.job_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.job_list.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.job_list.currentItemChanged.connect(self.select_job)
        layout.addWidget(self.job_list, 1)
        layout.addWidget(label("Offline. Audio and text stay on this Mac.", 12, "muted", wrap=True))
        return side

    def build_main(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(28, 18, 28, 12)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        ident = QVBoxLayout()
        ident.setSpacing(2)
        self.title = label("", 22, weight=QFont.Weight.Bold)
        self.meta = label("", 13, "muted")
        ident.addWidget(self.title)
        ident.addWidget(self.meta)
        header.addLayout(ident, 1)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.show_all = button("All", "segLeft", 12)
        self.show_check = button("To check", "segRight", 12)
        group = QButtonGroup(self)
        for widget in (self.show_all, self.show_check):
            widget.setCheckable(True)
            group.addButton(widget)
            seg.addWidget(widget)
        self.show_all.setChecked(True)
        self.show_all.clicked.connect(lambda: self.set_filter(False))
        self.show_check.clicked.connect(lambda: self.set_filter(True))
        header.addLayout(seg)
        header.addSpacing(4)
        self.folder_button = button("Open folder")
        self.folder_button.clicked.connect(self.open_export_folder)
        header.addWidget(self.folder_button)
        self.delete_button = TrashButton("Delete this meeting", framed=True)
        self.delete_button.clicked.connect(lambda: self.ask_delete(self.root))
        header.addWidget(self.delete_button)
        self.export_button = button("Export…", "primary")
        self.export_button.clicked.connect(self.export_file)
        header.addWidget(self.export_button)
        layout.addLayout(header)

        # Shown only while processing runs.
        self.run_card = QFrame()
        self.run_card.setObjectName("card")
        run = QHBoxLayout(self.run_card)
        run.setContentsMargins(16, 12, 16, 12)
        run.setSpacing(14)
        run_text = QVBoxLayout()
        run_text.setSpacing(6)
        self.run_status = label("", 13, wrap=True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        run_text.addWidget(self.run_status)
        run_text.addWidget(self.progress)
        run.addLayout(run_text, 1)
        self.pause_button = button("Pause")
        self.pause_button.clicked.connect(self.process.terminate)
        run.addWidget(self.pause_button)
        layout.addWidget(self.run_card)

        # Shown when a meeting has saved progress but no transcript yet.
        self.resume_card = QFrame()
        self.resume_card.setObjectName("card")
        resume = QHBoxLayout(self.resume_card)
        resume.setContentsMargins(16, 14, 16, 14)
        resume.setSpacing(10)
        self.resume_text = label("", 14, wrap=True)
        resume.addWidget(self.resume_text, 1)
        self.resume_button = button("Resume", "primary")
        self.resume_button.clicked.connect(lambda: self.resume_job(False))
        self.add_speakers_button = button("Add speakers")
        self.add_speakers_button.clicked.connect(lambda: self.resume_job(True))
        resume.addWidget(self.add_speakers_button)
        resume.addWidget(self.resume_button)
        layout.addWidget(self.resume_card)

        self.player_card = QFrame()
        self.player_card.setObjectName("card")
        bar = QHBoxLayout(self.player_card)
        bar.setContentsMargins(16, 12, 16, 12)
        bar.setSpacing(12)
        self.play_button = button("▶", "play", 13, "Play or pause")
        self.play_button.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_button)
        back = button("−5 s", "ghost", 12, "Back five seconds")
        back.clicked.connect(lambda: self.seek_to(self.player.position() / 1000 - 5))
        bar.addWidget(back)
        self.clock = label("0:00 / 0:00", 13)
        self.clock.setMinimumWidth(86)
        bar.addWidget(self.clock)
        self.wave = Waveform()
        self.wave.seek.connect(self.seek_to)
        bar.addWidget(self.wave, 1)
        self.rate_button = button("1×", "ghost", 12, "Playback speed")
        self.rate_button.clicked.connect(self.cycle_rate)
        bar.addWidget(self.rate_button)
        self.autoplay = Toggle("Auto-play", True)
        self.autoplay.setToolTip("Play a turn as soon as you click it")
        self.autoplay.toggled.connect(self.autoplay_changed)
        bar.addWidget(self.autoplay)
        layout.addWidget(self.player_card)

        heads = grid_row((PAD + 1, 4, PAD + 1, 0))
        for text, width in (("TIME", TIME_W), ("SPEAKER", SPEAKER_W), ("TRANSCRIPT", 0)):
            head = label(text, 11, "muted", QFont.Weight.Bold)
            head.setAccessibleName(text.title())
            if width:
                head.setFixedWidth(width)
                heads.addWidget(head)
            else:
                heads.addWidget(head, 1)
        status = label("STATUS", 11, "muted", QFont.Weight.Bold)
        status.setAccessibleName("Status")
        status.setFixedWidth(STATUS_W)
        heads.addWidget(status)
        self.heads = QWidget()
        self.heads.setLayout(heads)
        layout.addWidget(self.heads)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("list")
        self.scroll.setWidgetResizable(True)
        rows = QWidget()
        rows.setObjectName("rows")
        self.row_layout = QVBoxLayout(rows)
        self.row_layout.setContentsMargins(1, 1, 1, 1)
        self.row_layout.setSpacing(0)
        self.empty = label("", 14, "muted", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setContentsMargins(16, 40, 16, 40)
        self.row_layout.addWidget(self.empty)
        self.row_layout.addStretch()
        self.scroll.setWidget(rows)
        layout.addWidget(self.scroll, 1)

        self.footer = label(HINTS, 12, "muted")
        layout.addWidget(self.footer)
        return layout

    def notice(self, message):
        QMessageBox.information(self, "Meeting Protocol", str(message))

    def flash(self, message):
        self.footer.setText(message)
        QTimer.singleShot(5000, lambda: self.footer.setText(HINTS))

    # -- meetings --------------------------------------------------------------------------
    def jobs(self):
        files = (home() / "jobs").glob("*/job.json")
        return sorted((f.parent for f in files), key=lambda p: -p.stat().st_mtime)

    def first_job(self):
        jobs = self.jobs()
        return next((j for j in jobs if (j / "transcript.raw.json").exists()), None) or (
            jobs[0] if jobs else None
        )

    def describe_job(self, root):
        """(name, meta line) for the sidebar."""
        cfg = read_config(root)
        date = time.strftime("%d %b", time.localtime((root / "job.json").stat().st_mtime))
        length = clock((cfg.get("audio") or {}).get("duration") or 0)
        try:
            transcript = load_transcript(root)
        except Exception:  # noqa: BLE001 -- a damaged job still gets listed.
            transcript = None
        if transcript is None:
            state = "not finished"
        else:
            pending = sum(1 for t in transcript["turns"] if needs_check(t))
            state = f"{pending} to check" if pending else "all checked"
        return Path(cfg["input"]).name, f"{date} · {length} · {state}"

    def refresh_jobs(self):
        self.job_list.blockSignals(True)
        self.job_list.clear()
        for root in self.jobs():
            row = JobRow(root, *self.describe_job(root))
            row.trash.connect(lambda path: self.ask_delete(Path(path)))
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(root))
            item.setSizeHint(row.sizeHint())
            self.job_list.addItem(item)
            self.job_list.setItemWidget(item, row)
            if root == self.root:
                self.job_list.setCurrentItem(item)
        self.job_list.blockSignals(False)
        self.mark_current_job()

    def job_rows(self):
        for i in range(self.job_list.count()):
            yield self.job_list.itemWidget(self.job_list.item(i))

    def mark_current_job(self):
        for row in self.job_rows():
            row.set_selected(self.root is not None and row.root == str(self.root))

    def update_job_item(self):
        for row in self.job_rows():
            if self.root and row.root == str(self.root):
                row.set_text(*self.describe_job(self.root))

    def select_job(self, item, old=None):
        if item is None:
            return
        root = Path(item.data(Qt.ItemDataRole.UserRole))
        if root == self.root:
            return
        if not self.save_selected():
            self.job_list.blockSignals(True)
            self.job_list.setCurrentItem(old)
            self.job_list.blockSignals(False)
            return
        self.open_job(root)

    def show_empty(self):
        self.title.setText("No meetings yet")
        self.meta.setText("Click + New to transcribe a recording.")
        for widget in (self.player_card, self.heads, self.scroll, self.resume_card):
            widget.hide()
        self.set_busy(self.is_busy())

    def clear_rows(self):
        self.selected = self.playing_row = None
        for row in self.rows:
            self.row_layout.removeWidget(row)
            row.deleteLater()
        self.rows = []

    def open_job(self, root):
        self.player.stop()
        self.clear_rows()
        self.root = Path(root)
        cfg = read_config(self.root)
        self.job_list.blockSignals(True)
        for i in range(self.job_list.count()):
            if self.job_list.item(i).data(Qt.ItemDataRole.UserRole) == str(self.root):
                self.job_list.setCurrentRow(i)
        self.job_list.blockSignals(False)
        self.mark_current_job()
        self.title.setText(Path(cfg["input"]).name)
        self.duration = float((cfg.get("audio") or {}).get("duration") or 0)
        self.player.setSource(QUrl.fromLocalFile(cfg["input"]))
        self.transcript = load_transcript(self.root)
        has_text = self.transcript is not None
        for widget in (self.player_card, self.heads, self.scroll):
            widget.setVisible(has_text)
        self.resume_card.setVisible(not has_text)
        if not has_text:
            self.meta.setText("Processing has not finished.")
            self.resume_text.setText(
                "This meeting has saved progress. Resume to finish it; completed work is reused."
            )
            self.add_speakers_button.setVisible(bool(cfg.get("asr_only")))
            self.set_busy(self.is_busy())
            return
        speakers_missing = cfg.get("asr_only")
        self.add_speakers_button.setVisible(False)
        for turn in self.transcript["turns"]:
            row = TurnRow(self, turn)
            row.clicked.connect(self.select_row)
            row.seek.connect(self.play_from)
            row.play.connect(self.play_turn)
            row.check.connect(self.check_row)
            row.done.connect(lambda _r: self.close_selected())
            row.edited.connect(lambda _r: self.update_meta())
            self.rows.append(row)
            self.row_layout.insertWidget(self.row_layout.count() - 2, row)
        self.wave.set_data(envelope(self.root), self.spans(), self.duration)
        self.update_view()
        if speakers_missing:
            self.flash("Text only so far. Use the classic app or CLI to add speakers.")
        self.set_busy(self.is_busy())

    # -- speakers --------------------------------------------------------------------------
    def speaker_labels(self):
        seen = []
        for row in self.rows:
            if row.turn["speaker"] not in seen and row.turn["speaker"] != UNKNOWN:
                seen.append(row.turn["speaker"])
        return [*seen, UNKNOWN]

    def speaker_index(self, speaker):
        labels = self.speaker_labels()
        return -1 if speaker == UNKNOWN or speaker not in labels else labels.index(speaker)

    def spans(self):
        return [
            (r.turn["start"], r.turn["end"], self.speaker_index(r.turn["speaker"]))
            for r in self.rows
        ]

    # -- view state ------------------------------------------------------------------------
    def open_count(self):
        return sum(1 for r in self.rows if needs_check(r.turn))

    def update_meta(self):
        if not self.transcript:
            return
        speakers = len(self.speaker_labels()) - 1
        languages = sorted({t.get("language") for t in self.transcript["turns"]} - {None})
        names = {"de": "German", "fr": "French", "it": "Italian", "en": "English"}
        lang = ", ".join(names.get(code, code) for code in languages)
        saved = "editing…" if self.selected and self.selected.dirty else "saved"
        length = clock(self.duration or (self.rows[-1].turn["end"] if self.rows else 0))
        plural = "s" if speakers != 1 else ""
        self.meta.setText(f"{length} · {speakers} speaker{plural} · {lang} · {saved}")

    def update_view(self):
        pending = self.open_count()
        self.show_all.setText(f"All {len(self.rows)}")
        self.show_check.setText(f"To check {pending}")
        visible = 0
        for row in self.rows:
            show = not self.filter or needs_check(row.turn) or row is self.selected
            row.setVisible(show)
            visible += show
        self.empty.setText(
            "Everything is checked. Ready to export."
            if self.filter
            else "No turns in this meeting."
        )
        self.empty.setVisible(visible == 0)
        self.update_meta()

    def set_filter(self, on):
        if not self.save_selected():
            self.show_all.setChecked(not self.filter)
            self.show_check.setChecked(self.filter)
            return
        self.filter = on
        if on and (self.selected is None or not needs_check(self.selected.turn)):
            target = self.next_open(self.selected)
            if target:
                self.select_row(target)
            else:
                self.close_selected()
        self.update_view()

    def next_open(self, after):
        start = self.rows.index(after) + 1 if after in self.rows else 0
        ordered = self.rows[start:] + self.rows[:start]
        return next((r for r in ordered if needs_check(r.turn) and r is not after), None)

    # -- selection and editing -------------------------------------------------------------
    def select_row(self, row):
        if row is self.selected:
            return
        if not self.save_selected():
            return
        if self.selected:
            self.selected.set_selected(False)
        self.selected = row
        row.set_selected(True)
        self.update_view()
        if self.autoplay.isChecked():
            self.play_turn(row)
        else:
            self.stop_at = None
            self.player.pause()
            self.seek_to(row.turn["start"])
        QTimer.singleShot(30, lambda: self.scroll.ensureWidgetVisible(row, 0, 80))

    def close_selected(self):
        if self.selected and self.save_selected():
            self.selected.set_selected(False)
            self.selected = None
            self.update_view()

    def check_selected(self):
        if self.selected and needs_check(self.selected.turn):
            self.check_row(self.selected)

    def check_row(self, row):
        if not self.save_row(row, reviewed=True):
            return
        target = self.next_open(row)
        if target:
            self.select_row(target)
        elif self.selected:
            self.close_selected()
        self.update_view()
        if not self.open_count():
            self.flash("Everything is checked. Ready to export.")

    def save_selected(self):
        return self.save_row(self.selected) if self.selected else True

    def save_row(self, row, reviewed=None):
        if row is None or not self.root:
            return True
        review = row.turn["reviewed"] if reviewed is None else reviewed
        if not row.dirty and review == row.turn["reviewed"]:
            return True
        text, speaker = row.current_text(), row.current_speaker()
        if not text or not speaker or any(c in speaker for c in '\r\n:"'):
            self.notice("Enter text and a single-line speaker label without quotes or colons.")
            return False
        store = Store(self.root)
        try:
            with lock(self.root / ".lock"):
                store.correction(row.turn["id"], text, speaker, review)
                raw = json.loads((self.root / "transcript.raw.json").read_text())
                self.transcript = export_transcript(store, raw)
        except Exception as exc:  # noqa: BLE001 -- show storage errors in the window.
            self.notice(exc)
            return False
        finally:
            store.close()
        by_id = {turn["id"]: turn for turn in self.transcript["turns"]}
        row.dirty = False
        for each in self.rows:
            each.turn = by_id.get(each.turn["id"], each.turn)
            each.refresh()
        self.wave.set_data(self.wave.levels, self.spans(), self.duration)
        self.update_job_item()
        self.update_view()
        return True

    # -- audio -----------------------------------------------------------------------------
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.stop_at = None
            self.player.play()

    def play_from(self, row):
        """A time link plays on from that point, without opening the editor."""
        self.stop_at = None
        self.seek_to(row.turn["start"])
        self.player.play()

    def play_turn(self, row):
        self.seek_to(row.turn["start"])
        self.stop_at = int(row.turn["end"] * 1000) + 250
        self.player.play()

    def seek_to(self, seconds):
        seconds = max(0.0, seconds)
        self.player.setPosition(int(seconds * 1000))
        self.on_position(int(seconds * 1000))

    def cycle_rate(self):
        rates = [1.0, 1.25, 1.5, 0.75]
        current = self.player.playbackRate()
        rate = rates[(rates.index(current) + 1) % len(rates)] if current in rates else 1.0
        self.player.setPlaybackRate(rate)
        self.rate_button.setText(f"{rate:g}×")

    def autoplay_changed(self, on):
        if self.selected:
            self.selected.hint.setText(
                "Auto-play on · saves when you move on" if on else "Saves when you move on"
            )

    def on_position(self, ms):
        seconds = ms / 1000
        self.wave.set_position(seconds)
        self.clock.setText(f"{clock(seconds)} / {clock(self.wave.duration)}")
        current = None
        for row in self.rows:
            if seconds >= row.turn["start"] - 0.05:
                current = row
        if current is not self.playing_row:
            if self.playing_row:
                self.playing_row.set_playing(False)
            self.playing_row = current
            if current:
                current.set_playing(True)
                playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                if playing and self.selected is None and current.isVisible():
                    self.scroll.ensureWidgetVisible(current, 0, 120)
        if self.stop_at is not None and ms >= self.stop_at:
            self.stop_at = None
            self.player.pause()

    def on_playback(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("❚❚" if playing else "▶")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            self.toggle_play()
            return
        super().keyPressEvent(event)

    # -- delete ----------------------------------------------------------------------------
    def confirm_delete(self, name):
        return DeleteDialog(self, name).exec() == QDialog.DialogCode.Accepted

    def ask_delete(self, root):
        if root is None or self.is_busy():
            return
        name = Path(read_config(root)["input"]).name
        current = root == self.root
        # Save the open edit first so it survives either way, including after Undo.
        if not self.save_selected():
            return
        if not self.confirm_delete(name):
            return
        if current:
            self.player.stop()
            self.player.setSource(QUrl())
        try:
            trashed = trash_job(root)
        except Exception as exc:  # noqa: BLE001 -- locked job or Trash failure.
            if current:
                self.player.setSource(QUrl.fromLocalFile(read_config(root)["input"]))
            self.notice(exc)
            return
        self.trashed = (trashed, root, name)
        if current:
            self.clear_rows()
            self.root = self.transcript = None
        self.refresh_jobs()
        if current:
            nxt = self.first_job()
            if nxt:
                self.open_job(nxt)
            else:
                self.show_empty()
        self.toast.show_message(f"Moved \u201c{name}\u201d to the Trash.")

    def undo_delete(self):
        self.toast.hide()
        if not self.trashed or self.is_busy() or not self.save_selected():
            return
        trashed, root, _name = self.trashed
        try:
            restore_job(trashed, root)
        except Exception as exc:  # noqa: BLE001 -- emptied Trash or a clash at the old path.
            self.notice(exc)
            return
        self.trashed = None
        self.refresh_jobs()
        self.open_job(root)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.place()

    # -- export ----------------------------------------------------------------------------
    def export_file(self):
        if not self.root or self.transcript is None or not self.save_selected():
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
            str(Path.home() / "Documents" / f"{stem}-transcript.docx"),
            ";;".join(formats),
            "Word document (*.docx)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not filename:
            return
        destination = Path(filename)
        suffix = formats.get(selected, ".docx")
        if destination.suffix.lower() not in formats.values():
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
            pending = self.open_count()
            note = (
                f" · {pending} turn{'s' if pending != 1 else ''} still unchecked" if pending else ""
            )
            self.flash(f"Saved {destination.name}{note}")
        except Exception as exc:  # noqa: BLE001 -- display local filesystem/export failures.
            self.notice(exc)
        finally:
            store.close()

    def open_export_folder(self):
        if not self.root or self.transcript is None or not self.save_selected():
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

    # -- processing ------------------------------------------------------------------------
    def is_busy(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def set_busy(self, busy):
        has_text = self.transcript is not None
        self.run_card.setVisible(busy)
        self.new_button.setEnabled(not busy)
        self.job_list.setEnabled(not busy)
        self.resume_button.setEnabled(not busy)
        self.add_speakers_button.setEnabled(not busy)
        self.export_button.setEnabled(not busy and has_text)
        self.folder_button.setEnabled(not busy and has_text)
        self.delete_button.setEnabled(not busy and self.root is not None)
        self.delete_button.setVisible(self.root is not None)
        self.scroll.setEnabled(not busy)
        self.pause_button.setEnabled(busy)

    def new_recording(self):
        if not self.save_selected():
            return
        dialog = NewRecording(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.begin(dialog.arguments())

    def resume_job(self, add_speakers):
        if self.root:
            self.begin(["resume", str(self.root), *(["--add-speakers"] if add_speakers else [])])

    def begin(self, args):
        if not self.save_selected():
            return
        self.player.stop()
        self.pending, self.errors = "", ""
        self.run_status.setText("Checking the recording and the local models…")
        self.progress.setRange(0, 0)
        self.set_busy(True)
        self.process.start(sys.executable, ["-m", "meeting_protocol.cli", *args])

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
                stage = event["stage"].replace("_", " ").capitalize()
                message = event.get("message", "")
                self.run_status.setText(f"{stage} · {message}" if message else stage)

    def receive_errors(self):
        self.errors = (
            self.errors
            + bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        )[-3000:]

    def finished(self, code, status):
        self.receive()
        self.receive_errors()
        root = self.root
        self.root = None
        self.refresh_jobs()
        if root:
            self.open_job(root)
        self.refresh_jobs()
        self.set_busy(False)
        if code != 0:
            self.flash("Stopped. Completed work is saved; resume to continue.")
            if code != 130:
                self.notice(self.errors or "The worker stopped. Resume to retry saved work.")

    def closeEvent(self, event):
        if not self.save_selected():
            event.ignore()
            return
        if self.is_busy():
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
    app.setFont(font(14))
    app.setStyleSheet(STYLE)
    window = Window(initial)
    window.show()
    sys.exit(app.exec())
