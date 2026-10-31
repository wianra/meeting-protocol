import json
import os
import wave
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def make_job(tmp_path, name="main-job", with_text=True):
    audio = tmp_path / f"{name}.wav"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * 48000)
    root = tmp_path / "data" / "jobs" / name
    root.mkdir(parents=True)
    (root / "job.json").write_text(
        json.dumps({"job_id": name, "input": str(audio), "asr_only": False})
    )
    if with_text:
        turns = [
            {
                "id": f"turn-{i}",
                "text": f"Invented sentence {i}",
                "speaker": "Speaker A" if i != 1 else "Speaker B",
                "start": float(i),
                "end": float(i) + 0.9,
                "language": "de",
                "flags": ["low_word_confidence"] if i < 2 else [],
                "reviewed": False,
                "words": [],
            }
            for i in range(3)
        ]
        (root / "transcript.raw.json").write_text(
            json.dumps({"job_id": name, "diarized": True, "issues": [], "turns": turns})
        )
    return root


def test_main_window_listens_edits_checks_and_exports(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from meeting_protocol.gui.main import STYLE, Window

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    root = make_job(tmp_path)
    make_job(tmp_path, "unfinished", with_text=False)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window = Window(str(root))
    window.show()
    app.processEvents()
    assert window.root == root and len(window.rows) == 3
    assert window.job_list.count() == 2 and window.open_count() == 2

    # Auto-play off: clicking a turn only moves the playhead there.
    window.autoplay.setChecked(False)
    window.select_row(window.rows[1])
    assert window.stop_at is None and window.wave.position == 1.0
    # Auto-play on: clicking a turn plays that turn and stops at its end.
    window.autoplay.setChecked(True)
    window.select_row(window.rows[0])
    assert window.stop_at == int(0.9 * 1000) + 250

    # Edits save when moving to another turn.
    window.rows[0].editor.setPlainText("Human correction")
    window.select_row(window.rows[2])
    app.processEvents()
    output = json.loads((root / "exports/transcript.json").read_text())
    assert output["turns"][0]["text"] == "Human correction"

    # Speaker change and check, then "To check" shows only what is left.
    window.select_row(window.rows[1])
    window.rows[1].speaker.setCurrentText("Speaker A")
    window.check_row(window.rows[1])
    output = json.loads((root / "exports/transcript.json").read_text())
    assert output["turns"][1]["speaker"] == "Speaker A" and output["turns"][1]["reviewed"]
    window.set_filter(True)
    app.processEvents()
    assert [r.isVisible() for r in window.rows] == [True, False, False]
    window.check_selected()
    assert window.open_count() == 0 and window.empty.isVisible()

    # Export saves the editor's latest text first, with no model run.
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from meeting_protocol.word import W

    window.set_filter(False)
    window.select_row(window.rows[2])
    window.rows[2].editor.setPlainText("Unsaved before export")
    destination = tmp_path / "chosen-name"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **kw: (str(destination), "Word document (*.docx)"),
    )
    window.export_button.click()
    with ZipFile(destination.with_suffix(".docx")) as archive:
        doc = ET.fromstring(archive.read("word/document.xml"))
    text = "".join(t.text or "" for t in doc.iter(f"{{{W}}}t"))
    assert "Human correction" in text and "Unsaved before export" in text

    # A meeting without a transcript offers Resume instead of an empty player.
    window.open_job(tmp_path / "data" / "jobs" / "unfinished")
    assert window.rows == [] and not window.resume_card.isHidden()
    assert window.player_card.isHidden()
    window.close()


def test_main_window_moves_meetings_to_trash_and_undoes(tmp_path, monkeypatch):
    import shutil

    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui import main
    from meeting_protocol.storage import Store

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    trash = tmp_path / "Trash"
    trash.mkdir()
    # Never touch the real ~/.Trash or block on a modal dialog in tests.
    monkeypatch.setattr(main, "trash_job", lambda root: Path(shutil.move(root, trash / root.name)))
    asked = []
    monkeypatch.setattr(
        main.Window, "confirm_delete", lambda self, name: asked.append(name) or True
    )

    keep = make_job(tmp_path, "keep")
    gone = make_job(tmp_path, "gone")
    app = QApplication.instance() or QApplication([])
    window = main.Window(str(keep))
    window.show()
    app.processEvents()
    assert window.job_list.count() == 2

    # Deleting another meeting keeps the open one, including its unsaved edit.
    window.select_row(window.rows[0])
    window.rows[0].editor.setPlainText("Kept correction")
    window.ask_delete(gone)
    assert asked == ["gone.wav"] and not gone.exists() and (trash / "gone").is_dir()
    assert window.root == keep and window.job_list.count() == 1
    assert window.toast.isVisible() and "gone.wav" in window.toast.text.text()
    assert Store(keep).corrections()  # the edit was saved before the dialog
    assert (tmp_path / "gone.wav").exists()  # the recording itself is untouched

    # Undo restores the folder and opens it.
    window.toast.undo.emit()
    assert gone.is_dir() and window.root == gone and window.job_list.count() == 2

    # Deleting the open meeting opens the next one; deleting the last shows the empty state.
    window.delete_button.click()
    assert window.root == keep and not gone.exists()
    window.ask_delete(keep)
    assert window.root is None and window.job_list.count() == 0
    assert window.delete_button.isHidden() and window.title.text() == "No meetings yet"

    # Undo brings back corrections with the folder.
    window.undo_delete()
    assert window.root == keep
    assert window.rows[0].turn["text"] == "Kept correction"
    window.close()


def test_delete_is_disabled_while_processing(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui import main

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    root = make_job(tmp_path)
    app = QApplication.instance() or QApplication([])
    window = main.Window(str(root))
    monkeypatch.setattr(main.Window, "is_busy", lambda self: True)
    monkeypatch.setattr(
        main.Window, "confirm_delete", lambda *a: (_ for _ in ()).throw(AssertionError)
    )
    window.set_busy(True)
    app.processEvents()
    assert not window.delete_button.isEnabled() and not window.job_list.isEnabled()
    window.ask_delete(root)
    assert root.exists()
    monkeypatch.setattr(main.Window, "is_busy", lambda self: False)
    window.close()


def test_trash_job_refuses_while_a_worker_holds_the_job(tmp_path):
    import pytest

    from meeting_protocol.gui.common import trash_job
    from meeting_protocol.storage import lock

    root = make_job(tmp_path)
    with lock(root / ".worker.lock"), pytest.raises(RuntimeError):
        trash_job(root)
    assert root.exists()


def test_main_window_names_speakers_in_every_turn_and_export(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog

    from meeting_protocol.gui import main

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    root = make_job(tmp_path)
    raw = json.loads((root / "transcript.raw.json").read_text())
    raw["speakers"] = [{"id": "a", "label": "Speaker A"}, {"id": "b", "label": "Speaker B"}]
    for turn in raw["turns"]:
        turn["speaker_id"] = "b" if turn["speaker"] == "Speaker B" else "a"
    (root / "transcript.raw.json").write_text(json.dumps(raw))
    app = QApplication.instance() or QApplication([])
    window = main.Window(str(root))

    def name_them(dialog):
        dialog.fields["Speaker A"].setText("Raphael Winkler")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main.SpeakersDialog, "exec", name_them)
    window.speakers_button.click()
    app.processEvents()
    assert [r.name.text() for r in window.rows] == [
        "Raphael Winkler",
        "Speaker B",
        "Raphael Winkler",
    ]
    assert (root / "exports/transcript.txt").read_text() == (
        "Raphael Winkler: Invented sentence 0\n"
        "Speaker B: Invented sentence 1\n"
        "Raphael Winkler: Invented sentence 2\n"
    )
    # The name survives reopening the meeting.
    window.open_job(root)
    assert window.rows[0].name.text() == "Raphael Winkler"
    window.close()
