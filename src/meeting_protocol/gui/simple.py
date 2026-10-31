"""The simple review window: edit, review and export one meeting.

It shares storage, corrections and exports with ``classic.py``; only the interface differs.
Visual language: ink on paper, square corners, 2px rules, offset shadows on the one surface
you work on, mono labels, and colour only where it means something.
"""

import html
import json
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..export import apply_corrections, describe_flags, export_to_file, export_transcript
from ..jobs import read_config, resolve_job
from ..privacy import home, require_offline
from ..storage import Store, lock
from .common import set_app_icon

INK = "#1c1e21"
PAPER = "#fafaf8"
CARD = "#ffffff"
SUNK = "#f2f2f0"
HAIRLINE = "#e8e8e4"
RULE = "#d9d9d4"
EDGE = "#c9c9c4"
BODY = "#3f4249"
MUTED = "#5f646c"
FAINT = "#696e76"
SIGNAL = "#3948ac"
WARN = "#f6a06b"
OK = "#00572e"
LIFT = 6
UNKNOWN = "Speaker Unknown"
SANS = ["Figtree", "Figtree Variable", "Helvetica Neue", "Arial"]
MONO = ["SF Mono", "Menlo", "Monaco", "Courier New"]
PATTERNS = [
    Qt.BrushStyle.SolidPattern,
    Qt.BrushStyle.BDiagPattern,
    Qt.BrushStyle.Dense5Pattern,
    Qt.BrushStyle.CrossPattern,
    Qt.BrushStyle.FDiagPattern,
    Qt.BrushStyle.Dense3Pattern,
]
FORMATS = [
    (".docx", "Word document", "Speaker names in bold, quoted paragraphs. No timestamps.", "Word"),
    (".txt", "Plain text", 'One line per turn: Speaker A: "…"', "text"),
    (".json", "Structured JSON", "Timings, flags and every correction.", "JSON"),
    (".html", "Review page", "One self-contained file for a second listen.", "review page"),
]

STYLE = f"""
QMainWindow, QScrollArea, QWidget#canvas {{ background: {PAPER}; }}
QWidget {{ color: {INK}; }}
QFrame#header {{ background: {PAPER}; border: 0; border-bottom: 2px solid {INK}; }}
QFrame#footer {{ background: {PAPER}; border: 0; border-top: 2px solid {INK}; }}
QPushButton {{ background: {CARD}; color: {INK}; border: 2px solid {INK}; border-radius: 0;
  padding: 0 16px; min-height: 36px; }}
QPushButton:hover {{ background: {SUNK}; }}
QPushButton:focus {{ outline: none; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {EDGE}; background: {SUNK}; }}
QPushButton#ink {{ background: {INK}; color: {PAPER}; }}
QPushButton#signal {{ background: {SIGNAL}; color: #ffffff; }}
QPushButton#signal:disabled {{ background: {SUNK}; color: {FAINT}; }}
QPushButton#small {{ min-height: 28px; padding: 0 10px; }}
QPushButton#smallInk {{ min-height: 28px; padding: 0 10px; background: {INK}; color: {PAPER}; }}
QPushButton#tab, QPushButton#seg {{ min-height: 36px; padding: 0 14px; }}
QPushButton#seg {{ min-height: 28px; padding: 0 10px; }}
QPushButton#tab:checked, QPushButton#seg:checked {{ background: {INK}; color: {PAPER}; }}
QPushButton#file {{ border: 0; background: transparent; padding: 0; min-height: 0;
  text-align: left; }}
QPushButton#file:hover {{ text-decoration: underline; }}
QPushButton#file::menu-indicator {{ image: none; width: 0; }}
QPushButton#quiet {{ border-color: transparent; background: transparent; }}
QPushButton#quiet:hover {{ background: {SUNK}; }}
QTextEdit#editor {{ background: transparent; border: 0; padding: 0;
  selection-background-color: {INK}; selection-color: {PAPER}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; }}
QLabel#body {{ color: {BODY}; }}
QLabel#chipCheck {{ background: {WARN}; color: {INK}; border: 2px solid {INK}; padding: 0 5px; }}
QLabel#chipOk {{ background: {OK}; color: #ffffff; border: 2px solid {OK}; padding: 0 5px; }}
QFrame#rule {{ background: {INK}; border: 0; }}
QFrame#hairline {{ background: {HAIRLINE}; border: 0; }}
QFrame#empty {{ border: 2px dashed {EDGE}; background: transparent; }}
QScrollBar:vertical {{ background: {PAPER}; width: 10px; margin: 0; border: 0; }}
QScrollBar::handle:vertical {{ background: {EDGE}; min-height: 32px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QMenu {{ background: {CARD}; border: 2px solid {INK}; padding: 0; }}
QMenu::item {{ padding: 9px 18px; }}
QMenu::item:selected {{ background: {INK}; color: {PAPER}; }}
QMenu::separator {{ height: 1px; background: {HAIRLINE}; }}
"""


def sans(size, weight=QFont.Weight.Normal):
    font = QFont()
    font.setFamilies(SANS)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def mono(size, bold=False, spacing=0.05):
    """Mono label face. Qt has no text-transform, so callers pass `caps(...)` text."""
    font = QFont()
    font.setFamilies(MONO)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(size)
    font.setBold(bold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * spacing)
    return font


def label(text, font, name=None, wrap=False):
    widget = QLabel(text)
    widget.setFont(font)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def caps(widget, text):
    """Render uppercase while the accessible name keeps the real words."""
    widget.setText(text.upper())
    widget.setAccessibleName(text)
    return widget


def button(text, name=None, font=None, accessible=None):
    widget = QPushButton()
    caps(widget, text)
    if accessible:
        widget.setAccessibleName(accessible)
    widget.setFont(font or button_font())
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if name:
        widget.setObjectName(name)
    return widget


def button_font(size=12):
    font = sans(size, QFont.Weight.Bold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.04)
    return font


def lift(widget, size):
    """Hard offset shadow; hover shortens it to 2px instead of moving the button."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(0)
    effect.setOffset(size, size)
    effect.setColor(QColor(INK))
    widget.setGraphicsEffect(effect)
    widget.installEventFilter(_LiftHover(widget, effect, size))
    return effect


class _LiftHover(QObject):
    def __init__(self, owner, effect, size):
        super().__init__(owner)
        self.effect, self.size = effect, size

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self.effect.setOffset(2, 2)
        elif kind == QEvent.Type.Leave:
            self.effect.setOffset(self.size, self.size)
        return False


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02}"


def short(speaker):
    return "?" if speaker == UNKNOWN else speaker.removeprefix("Speaker ").strip() or speaker


def needs_check(turn):
    return bool(turn["flags"]) and not turn["reviewed"]


def reasons(flags):
    text = describe_flags(flags)
    return (text + ".") if text else "Listen once to confirm the wording."


class Swatch(QWidget):
    """A speaker is told apart by fill, never by colour."""

    def __init__(self, size=12):
        super().__init__()
        self.setFixedSize(size, size)
        self.index = 0

    def set_index(self, index):
        self.index = index
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor(CARD))
        if self.index >= 0:
            pattern = PATTERNS[self.index % len(PATTERNS)]
            painter.fillRect(rect, QBrush(QColor(INK), pattern))
        pen = QPen(QColor(INK), 2)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.drawRect(rect)


class Mark(QWidget):
    """The lifted P: an ink square holding a paper letter, on a square ink shadow."""

    def __init__(self, size=26):
        super().__init__()
        self.side = size
        self.setFixedSize(size + 3, size + 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(3, 3, self.side, self.side, QColor(INK))
        painter.fillRect(0, 0, self.side, self.side, QColor(INK))
        painter.setPen(QColor(PAPER))
        painter.setFont(sans(int(self.side * 0.66), QFont.Weight.ExtraBold))
        painter.drawText(QRectF(0, 0, self.side, self.side), Qt.AlignmentFlag.AlignCenter, "P")


class Timeline(QWidget):
    """Who spoke when, with the playhead. Click to seek."""

    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.spans, self.duration, self.position = [], 1.0, 0.0
        self.setAccessibleName("Who spoke when")

    def set_spans(self, spans, duration):
        self.spans = spans
        ends = [end for _, end, _ in spans]
        self.duration = max([duration or 0, *ends, 1.0])
        self.update()

    def set_position(self, seconds):
        self.position = seconds
        self.update()

    def mousePressEvent(self, event):
        self.seek.emit(max(0.0, event.position().x() / max(1, self.width()) * self.duration))

    def paintEvent(self, event):
        painter = QPainter(self)
        width, track = self.width(), QRectF(0, 6, self.width(), 8)
        painter.fillRect(track, QColor(SUNK))
        for start, end, index in self.spans:
            x0 = start / self.duration * width
            rect = QRectF(x0, 6, max(3.0, (end - start) / self.duration * width), 8)
            painter.fillRect(rect, QColor(CARD))
            if index >= 0:
                painter.fillRect(rect, QBrush(QColor(INK), PATTERNS[index % len(PATTERNS)]))
            painter.setPen(QPen(QColor(INK), 1))
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        x = self.position / self.duration * width
        painter.fillRect(QRectF(min(width - 2, max(0, x - 1)), 0, 2, 20), QColor(SIGNAL))


class AutoText(QTextEdit):
    """Plain-text editor that grows with its content instead of scrolling."""

    def __init__(self):
        super().__init__()
        self.setObjectName("editor")
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.textChanged.connect(self.fit)

    def fit(self):
        self.document().setTextWidth(self.viewport().width())
        self.setFixedHeight(max(28, int(self.document().size().height()) + 4))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()


class TurnRow(QFrame):
    activated = Signal(object)
    play = Signal(object)
    check = Signal(object)
    speaker_changed = Signal(object)

    def __init__(self, window, turn):
        super().__init__()
        self.owner, self.turn = window, turn
        self.active, self.dirty, self.loading = False, False, False
        self.speaker = turn["speaker"]
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAccessibleName(f"Turn at {clock(turn['start'])}")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(22, 18, 22 + LIFT, 18 + LIFT)
        outer.setSpacing(20)

        side = QWidget()
        side.setFixedWidth(112)
        left = QVBoxLayout(side)
        left.setContentsMargins(0, 3, 0, 0)
        left.setSpacing(5)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.swatch = Swatch(12)
        self.name = label("", mono(11, bold=True))
        name_row.addWidget(self.swatch)
        name_row.addWidget(self.name)
        name_row.addStretch()
        left.addLayout(name_row)
        self.time = label(clock(turn["start"]), mono(11), "faint")
        left.addWidget(self.time)
        self.chip = caps(label("", mono(10, bold=True, spacing=0.04), "chipCheck"), "Listen")
        self.chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        left.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignLeft)
        left.addStretch()
        outer.addWidget(side, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.read = label("", sans(17), wrap=True)
        self.read.setTextFormat(Qt.TextFormat.RichText)
        self.read.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        right.addWidget(self.read)

        self.editor = AutoText()
        self.editor.setFont(sans(17))
        self.editor.textChanged.connect(self.mark_dirty)
        self.editor.setAccessibleName("What was said")
        right.addWidget(self.editor)
        self.why = label("", sans(12), "muted", wrap=True)
        right.addWidget(self.why)

        self.actions = QWidget()
        bar = QVBoxLayout(self.actions)
        bar.setContentsMargins(0, 2, 0, 0)
        bar.setSpacing(12)
        line = QFrame()
        line.setObjectName("hairline")
        line.setFixedHeight(1)
        bar.addWidget(line)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.play_button = button("▶ Play", "smallInk", mono(11, bold=True), "Play this turn")
        self.play_button.clicked.connect(lambda: self.play.emit(self))
        row.addWidget(self.play_button)
        self.speakers = QHBoxLayout()
        self.speakers.setSpacing(0)
        row.addLayout(self.speakers)
        row.addStretch()
        self.check_button = button("Mark as checked ⌘↵", "small", mono(11, bold=True))
        self.check_button.clicked.connect(lambda: self.check.emit(self))
        row.addWidget(self.check_button)
        self.done_chip = caps(label("", mono(10, bold=True, spacing=0.04), "chipOk"), "Checked")
        row.addWidget(self.done_chip)
        bar.addLayout(row)
        right.addWidget(self.actions)
        outer.addLayout(right, 1)
        self.refresh()
        self.set_active(False)

    # -- state -----------------------------------------------------------------------------
    def current_text(self):
        return self.editor.toPlainText().strip() if self.active else self.turn["text"]

    def mark_dirty(self):
        if not self.loading:
            self.dirty = True

    def set_speaker(self, speaker):
        if speaker != self.speaker:
            self.speaker = speaker
            self.dirty = True
            self.refresh_name()
            self.speaker_changed.emit(self)

    def refresh_name(self):
        caps(self.name, self.speaker)
        self.swatch.set_index(self.owner.speaker_index(self.speaker))
        for i in range(self.speakers.count()):
            widget = self.speakers.itemAt(i).widget()
            if widget is not None and widget.property("speaker") is not None:
                widget.setChecked(widget.property("speaker") == self.speaker)

    def refresh(self):
        """Redraw from `self.turn` (after a save) without touching unsaved edits."""
        self.speaker = self.turn["speaker"] if not self.dirty else self.speaker
        self.refresh_name()
        self.read.setText(self.rich_text())
        pending = needs_check(self.turn)
        self.chip.setVisible(pending)
        self.why.setText(reasons(self.turn["flags"]))
        self.why.setVisible(pending and self.active)
        self.check_button.setVisible(pending)
        self.done_chip.setVisible(bool(self.turn["flags"]) and self.turn["reviewed"])

    def rich_text(self):
        """Uncertain words get the attention fill, but only while the model's text stands."""
        words = self.turn.get("words") or []
        joined = "".join(w.get("text", "") for w in words)
        if words and joined.split() == self.turn["text"].split():
            parts = []
            for word in words:
                text = html.escape(word.get("text", ""))
                if "low_word_confidence" in word.get("flags", []) and needs_check(self.turn):
                    lead = " " if text.startswith(" ") else ""
                    text = f'{lead}<span style="background-color:{WARN};">{text.strip()}</span>'
                parts.append(text)
            body = "".join(parts).strip()
        else:
            body = html.escape(self.turn["text"])
        return f'<p style="line-height:150%; margin:0;">{body}</p>'

    def rebuild_speakers(self, labels):
        while self.speakers.count():
            item = self.speakers.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        group = QButtonGroup(self)
        for i, name in enumerate([*labels, UNKNOWN]):
            seg = button(short(name), "seg", mono(11, bold=True), f"Set speaker to {name}")
            seg.setCheckable(True)
            seg.setProperty("speaker", name)
            seg.setMinimumWidth(36)
            if i:
                seg.setStyleSheet("border-left: 0;")
            seg.clicked.connect(lambda _=False, n=name: self.set_speaker(n))
            group.addButton(seg)
            self.speakers.addWidget(seg)
        add = button("+", "seg", mono(11, bold=True), "Name a new speaker")
        add.setStyleSheet("border-left: 0;")
        add.clicked.connect(self.new_speaker)
        self.speakers.addWidget(add)
        self.refresh_name()

    def new_speaker(self):
        name, ok = QInputDialog.getText(self, "New speaker", "Label for this speaker:")
        name = name.strip()
        if ok and name:
            if any(c in name for c in '\r\n:"'):
                self.owner.notice("Use one line without quotes or colons.")
                return
            self.set_speaker(name)
            self.rebuild_speakers(self.owner.speaker_labels(extra=name))

    def set_active(self, active):
        self.active = active
        self.loading = True
        if active:
            self.editor.setPlainText(self.turn["text"] if not self.dirty else self.editor_text())
            self.rebuild_speakers(self.owner.speaker_labels())
        self.loading = False
        self.read.setVisible(not active)
        self.editor.setVisible(active)
        self.actions.setVisible(active)
        self.why.setVisible(active and needs_check(self.turn))
        self.setCursor(Qt.CursorShape.ArrowCursor if active else Qt.CursorShape.IBeamCursor)
        if active:
            QTimer.singleShot(0, self.focus_editor)
        self.update()

    def editor_text(self):
        return self.editor.toPlainText() or self.turn["text"]

    def focus_editor(self):
        self.editor.fit()
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    # -- events ----------------------------------------------------------------------------
    def mousePressEvent(self, event):
        if not self.active:
            self.activated.emit(self)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0, 0, -LIFT, -LIFT)
        if self.active:
            painter.fillRect(rect.translated(LIFT, LIFT), QColor(INK))
            painter.fillRect(rect, QColor(CARD))
            pen = QPen(QColor(INK), 2)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        elif self.underMouse():
            painter.fillRect(rect, QColor(SUNK))


class OptionRow(QFrame):
    chosen = Signal(str)

    def __init__(self, suffix, name, desc):
        super().__init__()
        self.suffix = suffix
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setAccessibleName(name)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 11, 16, 11)
        layout.setSpacing(12)
        self.mark = label("□", mono(13))
        self.mark.setFixedWidth(16)
        layout.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(name, sans(14, QFont.Weight.Bold)))
        text.addWidget(label(desc, sans(12), "muted", wrap=True))
        layout.addLayout(text, 1)

    def set_selected(self, selected):
        self.mark.setText("■" if selected else "□")

    def mousePressEvent(self, event):
        self.chosen.emit(self.suffix)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.underMouse():
            painter.fillRect(self.rect(), QColor(SUNK))
        painter.fillRect(0, self.height() - 1, self.width(), 1, QColor(HAIRLINE))


class ExportPopup(QWidget):
    """One menu, Word first. Stamped in under the Export button with the surface lift."""

    def __init__(self, window):
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.owner = window
        self.suffix = ".docx"
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(370 + LIFT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2 + LIFT, 2 + LIFT)
        layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 16, 12)
        title = caps(label("", sans(14, QFont.Weight.ExtraBold)), "Export")
        head.addWidget(title)
        head.addStretch()
        layout.addLayout(head)
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(2)
        layout.addWidget(rule)
        self.options = []
        for suffix, name, desc, _ in FORMATS:
            row = OptionRow(suffix, name, desc)
            row.chosen.connect(self.choose)
            self.options.append(row)
            layout.addWidget(row)
        self.warning = label("", sans(13), "body", wrap=True)
        self.warning.setContentsMargins(16, 10, 16, 10)
        layout.addWidget(self.warning)
        foot = QHBoxLayout()
        foot.setContentsMargins(16, 12, 16, 14)
        foot.setSpacing(10)
        self.folder = button("Open folder", "quiet", button_font(12))
        self.folder.clicked.connect(self.open_folder)
        foot.addWidget(self.folder)
        foot.addStretch()
        self.save = button("Save", "ink", button_font(12))
        self.save.clicked.connect(self.save_file)
        foot.addWidget(self.save)
        layout.addLayout(foot)
        self.choose(self.suffix)

    def choose(self, suffix):
        self.suffix = suffix
        for row in self.options:
            row.set_selected(row.suffix == suffix)
        noun = next(f[3] for f in FORMATS if f[0] == suffix)
        caps(self.save, f"Save {noun} file…")

    def show_under(self, anchor):
        pending = self.owner.open_count()
        self.warning.setText(
            f"{pending} passage{'s' if pending != 1 else ''} not checked yet. You can still export."
            if pending
            else "Everything is checked."
        )
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height() + 8))
        self.move(point.x() - self.width() + LIFT, point.y())
        self.show()

    def save_file(self):
        self.hide()
        self.owner.export_as(self.suffix)

    def open_folder(self):
        self.hide()
        self.owner.open_export_folder()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0, 0, -LIFT, -LIFT)
        painter.fillRect(rect.translated(LIFT, LIFT), QColor(INK))
        painter.fillRect(rect, QColor(CARD))
        pen = QPen(QColor(INK), 2)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(1, 1, -1, -1))


class Window(QMainWindow):
    def __init__(self, initial=None):
        super().__init__()
        self.setWindowTitle("Meeting Protocol")
        self.resize(1180, 860)
        self.root = self.transcript = None
        self.rows, self.active, self.filter, self.stop_at = [], None, False, None
        self.duration = 0.0

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self.on_position)
        self.player.playbackStateChanged.connect(self.on_playback)

        central = QWidget()
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self.build_header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas = QWidget()
        canvas.setObjectName("canvas")
        center = QHBoxLayout(canvas)
        center.setContentsMargins(32, 0, 32, 0)
        center.addStretch()
        column = QWidget()
        column.setMaximumWidth(780 + LIFT)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.column = QVBoxLayout(column)
        self.column.setContentsMargins(0, 28, 0, 40)
        self.column.setSpacing(4)
        self.review_line = label("", sans(13), "muted", wrap=True)
        self.review_line.setContentsMargins(22, 0, 22, 10)
        self.column.addWidget(self.review_line)
        self.turn_area = QVBoxLayout()
        self.turn_area.setSpacing(4)
        self.column.addLayout(self.turn_area)
        self.empty = QFrame()
        self.empty.setObjectName("empty")
        box = QVBoxLayout(self.empty)
        box.setContentsMargins(24, 36, 24, 36)
        box.setSpacing(6)
        self.empty_title = caps(label("", sans(14, QFont.Weight.Bold)), "Everything is checked")
        self.empty_text = label("The transcript is ready to export.", sans(13), "muted", wrap=True)
        for widget in (self.empty_title, self.empty_text):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(widget)
        self.column.addWidget(self.empty)
        self.column.addStretch()
        center.addWidget(column, 100)
        center.addStretch()
        self.scroll.setWidget(canvas)
        page.addWidget(self.scroll, 1)
        page.addWidget(self.build_footer())

        self.popup = ExportPopup(self)
        for keys, handler in (
            ("Ctrl+Return", self.check_active),
            ("Ctrl+Enter", self.check_active),
            ("Ctrl+]", lambda: self.step(1)),
            ("Ctrl+[", lambda: self.step(-1)),
            ("Escape", self.close_active),
            ("Ctrl+E", self.show_export),
        ):
            QShortcut(QKeySequence(keys), self, activated=handler)

        root = resolve_job(initial) if initial else self.latest_job()
        if root:
            self.open_job(root)
        else:
            self.show_nothing()

    # -- chrome ----------------------------------------------------------------------------
    def build_header(self):
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(32, 12, 32, 14)
        row.setSpacing(14)
        row.addWidget(Mark(26), 0, Qt.AlignmentFlag.AlignVCenter)
        ident = QVBoxLayout()
        ident.setSpacing(1)
        self.file = QPushButton("")
        self.file.setObjectName("file")
        self.file.setFont(sans(15, QFont.Weight.ExtraBold))
        self.file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file.setAccessibleName("Choose a meeting")
        self.jobs_menu = QMenu(self)
        self.jobs_menu.aboutToShow.connect(self.fill_jobs_menu)
        self.file.setMenu(self.jobs_menu)
        ident.addWidget(self.file)
        self.meta = label("", mono(10, spacing=0.08), "muted")
        ident.addWidget(self.meta)
        row.addLayout(ident)
        row.addStretch()
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.tab_all = button("All", "tab", mono(12, bold=True))
        self.tab_check = button("To check", "tab", mono(12, bold=True))
        self.tab_check.setStyleSheet("border-left: 0;")
        group = QButtonGroup(self)
        for tab in (self.tab_all, self.tab_check):
            tab.setCheckable(True)
            group.addButton(tab)
            tabs.addWidget(tab)
        self.tab_all.setChecked(True)
        self.tab_all.clicked.connect(lambda: self.set_filter(False))
        self.tab_check.clicked.connect(lambda: self.set_filter(True))
        row.addLayout(tabs)
        row.addSpacing(10)
        self.export_button = button("Export ▾", "signal", button_font(13))
        self.export_button.setMinimumHeight(40)
        self.export_button.clicked.connect(self.show_export)
        lift(self.export_button, 4)
        row.addWidget(self.export_button)
        row.addSpacing(4)
        return header

    def build_footer(self):
        footer = QFrame()
        footer.setObjectName("footer")
        row = QHBoxLayout(footer)
        row.setContentsMargins(32, 10, 32, 10)
        row.setSpacing(16)
        self.play_all = button("▶", None, mono(14, bold=True), "Play or pause")
        self.play_all.setFixedSize(40, 40)
        self.play_all.setStyleSheet("padding: 0;")
        self.play_all.clicked.connect(self.toggle_play)
        row.addWidget(self.play_all)
        self.clock = label("0:00 / 0:00", mono(12), "muted")
        row.addWidget(self.clock)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek_to)
        row.addWidget(self.timeline, 1)
        self.hint = caps(
            label("", mono(10, spacing=0.08), "faint"), "Space play · ⌘↵ checked · ⌘[ ⌘] turn"
        )
        row.addWidget(self.hint)
        return footer

    def notice(self, message):
        QMessageBox.information(self, "Meeting Protocol", str(message))

    def flash(self, message):
        caps(self.hint, message)
        QTimer.singleShot(5000, lambda: caps(self.hint, "Space play · ⌘↵ checked · ⌘[ ⌘] turn"))

    # -- jobs ------------------------------------------------------------------------------
    def jobs(self):
        found = []
        for file in (home() / "jobs").glob("*/job.json"):
            if (file.parent / "transcript.raw.json").exists():
                found.append(file.parent)
        return sorted(found, key=lambda p: -p.stat().st_mtime)

    def latest_job(self):
        jobs = self.jobs()
        return jobs[0] if jobs else None

    def fill_jobs_menu(self):
        self.jobs_menu.clear()
        for root in self.jobs():
            cfg = read_config(root)
            action = self.jobs_menu.addAction(
                f"{Path(cfg['input']).name}   ·   {cfg['job_id'][:8]}"
            )
            action.setCheckable(True)
            action.setChecked(root == self.root)
            action.triggered.connect(lambda _=False, r=root: self.switch_job(r))
        if self.jobs_menu.isEmpty():
            self.jobs_menu.addAction("No transcribed meetings yet").setEnabled(False)
        self.jobs_menu.addSeparator()
        self.jobs_menu.addAction("Transcribe new recordings in the classic app").setEnabled(False)

    def switch_job(self, root):
        if root != self.root and self.save_active():
            self.open_job(root)

    def show_nothing(self):
        self.file.setText("No meeting yet")
        caps(self.meta, "Transcribe a recording with ./diarize gui")
        self.export_button.setEnabled(False)
        self.update_counts()

    def open_job(self, root):
        self.player.stop()
        self.clear_rows()
        self.root = Path(root)
        cfg = read_config(self.root)
        self.player.setSource(QUrl.fromLocalFile(cfg["input"]))
        self.file.setText(f"{Path(cfg['input']).name}  ▾")
        self.duration = float((cfg.get("audio") or {}).get("duration") or 0)
        raw = self.root / "transcript.raw.json"
        if not raw.exists():
            caps(self.meta, "Still processing · resume it in the classic app")
            self.export_button.setEnabled(False)
            self.update_counts()
            return
        store = Store(self.root)
        try:
            self.transcript = apply_corrections(json.loads(raw.read_text()), store.corrections())
        finally:
            store.close()
        self.export_button.setEnabled(True)
        for turn in self.transcript["turns"]:
            row = TurnRow(self, turn)
            row.activated.connect(self.activate)
            row.play.connect(self.play_turn)
            row.check.connect(self.check_row)
            row.speaker_changed.connect(lambda _r: self.update_timeline())
            self.rows.append(row)
            self.turn_area.addWidget(row)
        self.update_timeline()
        self.update_counts()
        first = next((r for r in self.rows if needs_check(r.turn)), None)
        if self.filter and first:
            self.activate(first)

    def clear_rows(self):
        self.active = None
        while self.turn_area.count():
            item = self.turn_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows, self.transcript = [], None

    # -- speakers --------------------------------------------------------------------------
    def speaker_labels(self, extra=None):
        seen = []
        for row in self.rows:
            for name in (row.turn["speaker"], row.speaker):
                if name != UNKNOWN and name not in seen:
                    seen.append(name)
        if extra and extra not in seen and extra != UNKNOWN:
            seen.append(extra)
        return seen

    def speaker_index(self, speaker):
        if speaker == UNKNOWN:
            return -1
        labels = self.speaker_labels(extra=speaker)
        return labels.index(speaker)

    # -- review flow -----------------------------------------------------------------------
    def open_count(self):
        return sum(1 for r in self.rows if needs_check(r.turn))

    def update_counts(self):
        total, pending = len(self.rows), self.open_count()
        flagged = sum(1 for r in self.rows if r.turn["flags"])
        caps(self.tab_all, f"All {total}")
        caps(self.tab_check, f"To check · {pending}")
        if self.root and self.transcript is not None:
            speakers = len(self.speaker_labels())
            length = clock(self.duration or (self.rows[-1].turn["end"] if self.rows else 0))
            state = "unsaved edit" if (self.active and self.active.dirty) else "saved"
            caps(
                self.meta,
                f"{length} · {speakers} speaker{'s' if speakers != 1 else ''} · {state}",
            )
        self.review_line.setText(
            f"{flagged - pending} of {flagged} uncertain passages checked. "
            "Listen, fix what is wrong, then mark it as checked."
        )
        self.review_line.setVisible(self.filter and bool(self.rows))
        visible = 0
        for row in self.rows:
            show = not self.filter or needs_check(row.turn) or row is self.active
            row.setVisible(show)
            visible += show
        self.empty.setVisible(self.filter and visible == 0 and bool(self.rows))

    def update_timeline(self):
        spans = [(r.turn["start"], r.turn["end"], self.speaker_index(r.speaker)) for r in self.rows]
        self.timeline.set_spans(spans, self.duration)
        for row in self.rows:
            row.swatch.set_index(self.speaker_index(row.speaker))

    def set_filter(self, on):
        if not self.save_active():
            return
        self.filter = on
        self.tab_check.setChecked(on)
        self.tab_all.setChecked(not on)
        if on and (self.active is None or not needs_check(self.active.turn)):
            target = self.next_open(self.active)
            if target:
                self.activate(target)
            else:
                self.close_active()
        self.update_counts()

    def next_open(self, after):
        if not self.rows:
            return None
        start = self.rows.index(after) + 1 if after in self.rows else 0
        ordered = self.rows[start:] + self.rows[:start]
        return next((r for r in ordered if needs_check(r.turn) and r is not after), None)

    def activate(self, row):
        if row is self.active:
            return
        if not self.save_active():
            return
        if self.active:
            self.active.set_active(False)
        self.active = row
        row.set_active(True)
        self.update_counts()
        self.player.setPosition(int(row.turn["start"] * 1000))
        self.timeline.set_position(row.turn["start"])
        QTimer.singleShot(30, lambda: self.scroll.ensureWidgetVisible(row, 0, 120))

    def close_active(self):
        if self.popup.isVisible():
            self.popup.hide()
            return
        if self.active and self.save_active():
            self.active.set_active(False)
            self.active = None
            self.update_counts()

    def step(self, delta):
        visible = [r for r in self.rows if r.isVisible()]
        if not visible:
            return
        if self.active in visible:
            index = (visible.index(self.active) + delta) % len(visible)
        else:
            index = 0 if delta > 0 else len(visible) - 1
        self.activate(visible[index])

    def check_active(self):
        if self.active and needs_check(self.active.turn):
            self.check_row(self.active)

    def check_row(self, row):
        if not self.save_row(row, reviewed=True):
            return
        target = self.next_open(row)
        if target:
            self.activate(target)
        elif self.filter:
            self.close_active()
        self.update_counts()
        if not self.open_count():
            self.flash("Everything is checked · ready to export")

    def save_active(self):
        return self.save_row(self.active) if self.active else True

    def save_row(self, row, reviewed=None):
        if row is None or not self.root:
            return True
        review = row.turn["reviewed"] if reviewed is None else reviewed
        text, speaker = row.current_text(), row.speaker.strip()
        if not row.dirty and review == row.turn["reviewed"]:
            return True
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
        if row.active:
            row.loading = True
            row.editor.setPlainText(row.turn["text"])
            row.loading = False
        self.update_timeline()
        self.update_counts()
        return True

    # -- audio -----------------------------------------------------------------------------
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.stop_at = None
            self.player.play()

    def play_turn(self, row):
        self.player.setPosition(int(row.turn["start"] * 1000))
        self.stop_at = int(row.turn["end"] * 1000) + 250
        self.player.play()

    def seek_to(self, seconds):
        self.player.setPosition(int(seconds * 1000))
        self.timeline.set_position(seconds)

    def on_position(self, ms):
        seconds = ms / 1000
        self.timeline.set_position(seconds)
        self.clock.setText(f"{clock(seconds)} / {clock(self.timeline.duration)}")
        if self.stop_at is not None and ms >= self.stop_at:
            self.stop_at = None
            self.player.pause()

    def on_playback(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_all.setText("❚❚" if playing else "▶")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            self.toggle_play()
            return
        super().keyPressEvent(event)

    # -- export ----------------------------------------------------------------------------
    def show_export(self):
        if self.transcript is None or not self.save_active():
            return
        self.popup.show_under(self.export_button)

    def export_as(self, suffix):
        if not self.root or self.transcript is None or not self.save_active():
            return
        name = next(f[1] for f in FORMATS if f[0] == suffix)
        stem = Path(read_config(self.root)["input"]).stem
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export transcript",
            str(Path.home() / "Documents" / f"{stem}-transcript{suffix}"),
            f"{name} (*{suffix})",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not filename:
            return
        destination = Path(filename)
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
            self.flash(f"Saved {destination.name}")
        except Exception as exc:  # noqa: BLE001 -- display local filesystem/export failures.
            self.notice(exc)
        finally:
            store.close()

    def open_export_folder(self):
        if not self.root or self.transcript is None or not self.save_active():
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

    def closeEvent(self, event):
        if not self.save_active():
            event.ignore()
            return
        self.player.stop()
        event.accept()


def launch(initial=None):
    require_offline()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Meeting Protocol")
    set_app_icon(app)
    app.setFont(sans(14))
    app.setStyleSheet(STYLE)
    window = Window(initial)
    window.show()
    sys.exit(app.exec())
