import json
import os
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def make_job(tmp_path):
    audio = tmp_path / "silence.wav"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * 48000)
    root = tmp_path / "simple-job"
    root.mkdir()
    (root / "job.json").write_text(
        json.dumps({"job_id": "fixture", "input": str(audio), "asr_only": False})
    )
    turns = [
        {
            "id": f"turn-{i}",
            "text": f"Invented sentence {i}",
            "speaker": "Speaker A" if i != 1 else "Speaker B",
            "start": float(i),
            "end": float(i + 1),
            "language": "de",
            "flags": ["low_word_confidence"] if i < 2 else [],
            "reviewed": False,
            "words": [],
        }
        for i in range(3)
    ]
    (root / "transcript.raw.json").write_text(
        json.dumps({"job_id": "fixture", "diarized": True, "issues": [], "turns": turns})
    )
    return root


def test_simple_window_edits_reviews_and_exports(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from meeting_protocol.gui.simple import STYLE, Window

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    root = make_job(tmp_path)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window = Window(str(root))
    window.show()
    app.processEvents()
    assert window.root == root and len(window.rows) == 3
    assert window.open_count() == 2

    # Editing a turn and moving to the next one saves the correction.
    window.activate(window.rows[0])
    window.rows[0].editor.setPlainText("Human correction")
    window.activate(window.rows[1])
    app.processEvents()
    output = json.loads((root / "exports/transcript.json").read_text())
    assert output["turns"][0]["text"] == "Human correction"

    # Changing the speaker is saved too, and only for this turn.
    window.rows[1].set_speaker("Speaker A")
    window.check_row(window.rows[1])
    output = json.loads((root / "exports/transcript.json").read_text())
    assert output["turns"][1]["speaker"] == "Speaker A" and output["turns"][1]["reviewed"]
    assert window.open_count() == 1

    # "To check" shows only what still needs a listen.
    window.set_filter(True)
    app.processEvents()
    assert [r.isVisible() for r in window.rows] == [True, False, False]
    window.check_active()
    assert window.open_count() == 0 and window.empty.isVisible()

    # Export writes the latest saved revision in the chosen format, with no model run.
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from meeting_protocol.word import W

    window.set_filter(False)
    window.activate(window.rows[2])
    window.rows[2].editor.setPlainText("Unsaved before export")
    destination = tmp_path / "chosen-name"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **kw: (str(destination), "Word document")
    )
    window.export_as(".docx")
    with ZipFile(destination.with_suffix(".docx")) as archive:
        doc = ET.fromstring(archive.read("word/document.xml"))
    text = "".join(t.text or "" for t in doc.iter(f"{{{W}}}t"))
    assert "Human correction" in text and "Unsaved before export" in text

    window.export_as(".txt")
    plain = destination.with_suffix(".txt").read_text()
    assert "Speaker A: Human correction" in plain
    window.close()
