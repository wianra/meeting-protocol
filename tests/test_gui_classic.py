import json
import os
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def test_explicit_job_stays_selected_and_edits_survive_switching(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui.classic import Window

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    audio = tmp_path / "silence.wav"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * 32000)
    root = tmp_path / "explicit-job"
    root.mkdir()
    (root / "job.json").write_text(
        json.dumps({"job_id": "fixture", "input": str(audio), "asr_only": False})
    )
    turns = [
        {
            "id": f"turn-{i}",
            "text": f"Invented sentence {i}",
            "speaker": "Speaker A",
            "start": float(i),
            "end": float(i + 1),
            "language": "de",
            "flags": [],
            "reviewed": False,
            "words": [],
        }
        for i in range(2)
    ]
    (root / "transcript.raw.json").write_text(
        json.dumps({"job_id": "fixture", "diarized": True, "issues": [], "turns": turns})
    )
    app = QApplication.instance() or QApplication([])
    window = Window(str(root))
    window.show()
    app.processEvents()
    assert window.root == root and window.table.rowCount() == 2
    window.table.setCurrentCell(0, 2)
    window.text.setPlainText("Human correction")
    window.table.setCurrentCell(1, 2)
    app.processEvents()
    output = json.loads((root / "exports/transcript.json").read_text())
    assert output["turns"][0]["text"] == "Human correction"
    assert window.text.toPlainText() == "Invented sentence 1"
    # Export must save the edit still in the editor, without re-running any model.
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from PySide6.QtWidgets import QFileDialog

    from meeting_protocol.word import W

    window.text.setPlainText("Latest unsaved correction")
    destination = tmp_path / "chosen-name"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **kw: (str(destination), "Word document (*.docx)"),
    )
    window.export_button.click()
    app.processEvents()
    assert not window.dirty
    with ZipFile(destination.with_suffix(".docx")) as archive:
        doc = ET.fromstring(archive.read("word/document.xml"))
    assert "Latest unsaved correction" in "".join(t.text or "" for t in doc.iter(f"{{{W}}}t"))
    assert "Exported:" in window.location.text()
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True
    )
    window.open_exports.click()
    assert opened == [str(root / "exports")]
    # Cancelling a save dialog must not write a destination or show a success message.
    before = window.location.text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    window.export_button.click()
    assert window.location.text() == before
    window.set_busy(True)
    assert not window.export_button.isEnabled()
    assert not window.open_exports.isEnabled()
    window.set_busy(False)
    window.close()
