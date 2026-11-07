import json
import os
import wave
from pathlib import Path

import pytest

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


def test_processing_strip_follows_each_step_and_freezes_when_paused(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui import main
    from meeting_protocol.storage import Store

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    done = make_job(tmp_path)
    root = make_job(tmp_path, "running", with_text=False)
    config = json.loads((root / "job.json").read_text())
    config.update(audio={"duration": 2832.0}, min_speakers=2, max_speakers=10, language="de")
    (root / "job.json").write_text(json.dumps(config))
    app = QApplication.instance() or QApplication([])
    window = main.Window(str(done))
    window.show()
    app.processEvents()
    page = window.process_page
    monkeypatch.setattr(main.Window, "is_busy", lambda self: True)
    page.start(name="running")
    window.set_busy(True)
    assert window.pages.currentWidget() is page and page.crumb.text() == "MEETINGS / NEW"

    window.handle_event({"job": str(root), "status": "running"})
    assert page.facts.text() == "47:12 · 2–10 SPEAKERS · GERMAN"
    window.handle_event(
        {"stage": "decode", "done": 20, "total": 48, "message": "Audio block saved"}
    )
    assert page.lanes["audio"]["done"] == 20 and page.step.text() == "1 / 4"
    # Decoding never reports done == total; the next step finishing it is what counts.
    window.handle_event(
        {"stage": "decode", "done": 47, "total": 48, "message": "Audio block saved"}
    )
    window.handle_event(
        {
            "stage": "transcription",
            "done": 23,
            "total": 41,
            "message": "Window saved",
            "at": 1726.0,
            "latest": "dann schieben wir das Release",
            "latest_at": 1700.0,
        }
    )
    assert page.lanes["audio"] == {"done": 47, "total": 47, "cells": True, "complete": True}
    assert page.windows.text() == "23 / 41" and page.step.text() == "2 / 4"
    assert page.now_caption.text() == "LATEST · 28:20" and "Release" in page.now_text.text()
    window.handle_event(
        {"stage": "speaker_segmentation", "done": 0, "total": 0, "message": "Saved batches: 0"}
    )
    assert page.lanes["text"]["complete"] and page.step.text() == "3 / 4"
    assert "Speaker segmentation" in page.now_text.text()
    window.handle_event({"stage": "export", "done": 1, "total": 1, "message": "Draft saved"})
    assert page.lanes["speakers"]["complete"] and page.lanes["draft"]["complete"]
    page.strip.grab()  # Paints every lane without errors.

    # Stopped part-way: the strip shows the saved progress, with Resume instead of Pause.
    store = Store(root)
    store.event("decode", 47, 48, "Audio block saved")
    store.event("transcription", 23, 41, "Window saved")
    store.close()
    monkeypatch.setattr(main.Window, "is_busy", lambda self: False)
    page.stop()
    window.open_job(root)
    assert window.pages.currentWidget() is page and page.crumb.text() == "MEETINGS / NOT FINISHED"
    assert page.windows.text() == "23 / 41" and "window 24" in page.now_text.text()
    assert page.pause_button.isHidden() and not window.resume_card.isHidden()
    assert window.add_speakers_button.isHidden() and window.resume_button.isEnabled()
    page.strip.grab()

    # Adding speakers to a text-only meeting: the worker turns the Speakers step on.
    config["asr_only"] = True
    (root / "job.json").write_text(json.dumps(config))
    window.open_job(root)
    assert not window.add_speakers_button.isHidden() and page.step.text() == "2 / 3"

    def started(*args):
        monkeypatch.setattr(main.Window, "is_busy", lambda self: True)

    monkeypatch.setattr(window.process, "start", started)
    window.add_speakers_button.click()
    assert page.busy and page.crumb.text() == "MEETINGS / RESUMING"
    config["asr_only"] = False
    (root / "job.json").write_text(json.dumps(config))
    window.handle_event({"job": str(root), "status": "running"})
    window.handle_event({"stage": "speaker_segmentation", "done": 4, "total": 9, "message": ""})
    assert "speakers" not in page.strip.skipped and page.step.text() == "3 / 4"
    monkeypatch.setattr(main.Window, "is_busy", lambda self: False)
    page.stop()
    window.close()


def queue_window(tmp_path, monkeypatch):
    """Use real Qt scheduling with a controllable local worker boundary."""
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui import main

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    previous = make_job(tmp_path, "previous")
    window = main.Window(str(previous))
    worker = {"running": False, "starts": [], "stops": 0}

    def start(executable, args):
        assert not worker["running"], "Only one recording may run at a time"
        worker["running"] = True
        worker["starts"].append(args)

    def stop(*args):
        worker["stops"] += 1

    monkeypatch.setattr(window.process, "start", start)
    monkeypatch.setattr(
        window.process,
        "state",
        lambda: (
            QProcess.ProcessState.Running if worker["running"] else QProcess.ProcessState.NotRunning
        ),
    )
    monkeypatch.setattr(main, "stop_supervisor", stop)
    monkeypatch.setattr(window, "receive", lambda: None)
    monkeypatch.setattr(window, "receive_errors", lambda: None)
    monkeypatch.setattr(window, "notice", lambda text: (_ for _ in ()).throw(AssertionError(text)))
    return app, window, worker


def finish_worker(window, worker, code=0):
    from PySide6.QtCore import QProcess

    worker["running"] = False
    window.finished(code, QProcess.ExitStatus.NormalExit)


def test_queue_runs_sequentially_continues_after_failure_and_pauses(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    a = make_job(tmp_path, "a")
    sources = [str(tmp_path / f"{name}.wav") for name in "abcd"]
    window.enqueue([["transcribe", path] for path in sources[:3]])
    assert len(worker["starts"]) == 1 and window.new_button.isEnabled()
    assert not window.job_list.isEnabled()
    window.handle_event({"job": str(a), "status": "running"})
    window.enqueue([["transcribe", sources[3]]])
    assert len(worker["starts"]) == 1
    finish_worker(window, worker)
    app.processEvents()
    assert worker["starts"][-1][3] == sources[1]

    # Failure before the job event must not assign the previous recording to this entry.
    window.errors = "Original audio is missing"
    finish_worker(window, worker, 1)
    app.processEvents()
    assert worker["starts"][-1][3] == sources[2]
    failed = window.queue.entries[0]
    assert failed["state"] == "failed" and failed["job"] is None
    assert failed["error"] == "Original audio is missing"
    assert window.root == a
    window.pause_queue()
    assert worker["stops"] == 1
    finish_worker(window, worker, 130)
    app.processEvents()
    assert len(worker["starts"]) == 3
    # The finished recording has left the queue; its meeting stays in the job list.
    assert [e["state"] for e in window.queue.entries] == ["failed", "paused", "waiting"]

    # Retry queues the failed recording and waits for an explicit resume.
    window.queue_list.setCurrentRow(0)
    window.retry_queue_entry()
    assert len(worker["starts"]) == 3
    window.toggle_queue()
    assert worker["starts"][-1][3] == sources[1]
    finish_worker(window, worker)
    app.processEvents()
    assert worker["starts"][-1][3] == sources[2]
    window.pause_queue()
    finish_worker(window, worker, 130)
    window.close()


def test_close_cannot_launch_next_and_reopening_requires_resume(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    root = make_job(tmp_path, "active", with_text=False)
    source = Path(json.loads((root / "job.json").read_text())["input"])
    original = source.read_bytes()
    window.enqueue([["transcribe", str(source)], ["transcribe", str(tmp_path / "later.wav")]])
    window.handle_event({"job": str(root), "status": "running"})

    def stopped(timeout):
        assert window.closing
        finish_worker(window, worker, 130)
        return True

    monkeypatch.setattr(window.process, "waitForFinished", stopped)
    window.close()
    app.processEvents()
    assert len(worker["starts"]) == 1
    assert [e["state"] for e in window.queue.entries] == ["paused", "waiting"]

    from meeting_protocol.gui.main import Window

    reopened = Window()
    assert reopened.active_entry is None and not reopened.queue_running
    app.processEvents()
    assert not reopened.is_busy()
    # Removing a paused entry changes queue membership, not source files or job files.
    reopened.queue_list.setCurrentRow(0)
    reopened.remove_queue_entry()
    assert source.read_bytes() == original and (root / "job.json").exists()
    reopened.close()


def test_failed_worker_start_advances_and_missing_resume_job_is_retryable(tmp_path, monkeypatch):
    from PySide6.QtCore import QProcess

    app, window, worker = queue_window(tmp_path, monkeypatch)
    normal_start = window.process.start
    attempts = []

    def start(executable, args):
        attempts.append(args)
        if len(attempts) == 1:
            window.process_error(QProcess.ProcessError.FailedToStart)
        else:
            normal_start(executable, args)

    monkeypatch.setattr(window.process, "start", start)
    window.enqueue(
        [
            ["transcribe", str(tmp_path / "first.wav")],
            ["resume", str(tmp_path / "deleted-job")],
            ["transcribe", str(tmp_path / "third.wav")],
        ]
    )
    app.processEvents()
    app.processEvents()
    assert [e["state"] for e in window.queue.entries] == ["failed", "failed", "running"]
    assert "Could not start" in window.queue.entries[0]["error"]
    assert len(attempts) == 2
    window.pause_queue()
    finish_worker(window, worker, 130)
    window.close()


def test_multiple_file_picker_and_explicit_file_locations(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from meeting_protocol.gui.files import FilesDialog
    from meeting_protocol.gui.main import NewRecording

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    root = make_job(tmp_path)
    a, b = str(tmp_path / "first.wav"), str(tmp_path / "second.wav")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kw: ([a, b], ""))
    dialog = NewRecording(None)
    dialog.browse()
    dialog.browse()
    assert dialog.sources.count() == 2
    dialog.language.setCurrentIndex(2)
    dialog.asr_only.setChecked(True)
    assert dialog.commands() == [
        [
            "transcribe",
            source,
            "--language",
            "fr",
            "--min-speakers",
            "2",
            "--max-speakers",
            "10",
            "--asr-only",
        ]
        for source in (a, b)
    ]
    dialog.sources.setCurrentRow(0)
    dialog.remove_selected()
    assert dialog.sources.count() == 1
    dialog.close()
    files = FilesDialog(None, root)
    files.show()
    app.processEvents()
    assert files.source_path.text() == json.loads((root / "job.json").read_text())["input"]
    assert files.outputs_path.text() == str(root / "exports")
    assert files.job_path.text() == str(root)
    assert files.data_path.text() == str(tmp_path / "data")
    assert "no copy of the original is imported" in files.source_note.text()
    files.close()


def test_paused_recording_resumes_its_saved_job(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    root = make_job(tmp_path, "saved", with_text=False)
    source = json.loads((root / "job.json").read_text())["input"]
    window.enqueue([["transcribe", source, "--language", "de"]])
    window.handle_event({"job": str(root), "status": "running"})
    window.pause_queue()
    finish_worker(window, worker, 130)
    app.processEvents()
    window.resume_job(False)
    assert len(window.queue.entries) == 1
    assert worker["starts"][-1] == ["-m", "meeting_protocol.cli", "resume", str(root)]
    window.pause_queue()
    finish_worker(window, worker, 130)
    window.close()


def test_queue_disk_failure_prevents_worker_launch(tmp_path, monkeypatch):
    from meeting_protocol import queue as module

    app, window, worker = queue_window(tmp_path, monkeypatch)
    window.queue.add([["transcribe", str(tmp_path / "a.wav")]])
    notices = []
    monkeypatch.setattr(window, "notice", notices.append)

    def no_space(*args):
        raise OSError("No space left")

    monkeypatch.setattr(module, "atomic_write", no_space)
    window.toggle_queue()
    app.processEvents()
    assert worker["starts"] == []
    assert not window.queue_running and window.queue_storage_error
    assert not window.new_button.isEnabled() and not window.queue_toggle.isEnabled()
    assert "No space left" in notices[0]
    window.close()


def test_resume_while_worker_is_stopping_does_not_skip_the_paused_file(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    source = str(tmp_path / "first.wav")
    window.enqueue([["transcribe", source], ["transcribe", str(tmp_path / "later.wav")]])
    window.pause_queue()
    window.toggle_queue()  # Request resume before the old supervisor has actually exited.
    assert len(worker["starts"]) == 1
    finish_worker(window, worker, 130)
    app.processEvents()
    assert window.queue.entries[0]["state"] == "running"
    assert worker["starts"][-1][3] == source
    window.pause_queue()
    finish_worker(window, worker, 130)
    window.close()


def test_resume_runs_the_open_meeting_before_other_paused_recordings(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    first = make_job(tmp_path, "first", with_text=False)
    other = make_job(tmp_path, "other", with_text=False)
    window.enqueue([["transcribe", str(tmp_path / "first.wav")]])
    window.handle_event({"job": str(first), "status": "running"})
    window.pause_queue()
    finish_worker(window, worker, 130)
    app.processEvents()
    window.open_job(other)
    window.resume_job(False)
    assert worker["starts"][-1] == ["-m", "meeting_protocol.cli", "resume", str(other)]
    assert [e["state"] for e in window.queue.entries] == ["running", "paused"]
    window.pause_queue()
    finish_worker(window, worker, 130)
    window.close()


def test_queue_is_empty_and_hidden_once_every_recording_is_done(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    flashes = []
    monkeypatch.setattr(window, "flash", flashes.append)
    window.show()
    assert window.queue_panel.isHidden()
    window.enqueue([["transcribe", str(tmp_path / f"{name}.wav")] for name in "ab"])
    assert not window.queue_panel.isHidden()
    window.pause_queue()
    finish_worker(window, worker, 130)
    assert flashes[-1].startswith("Queue paused")
    window.toggle_queue()
    for _ in range(2):
        finish_worker(window, worker)
        app.processEvents()
    assert window.queue.entries == [] and window.queue_list.count() == 0
    assert window.queue_panel.isHidden()
    assert json.loads(window.queue.path.read_text())["entries"] == []
    window.close()


def test_second_window_and_corrupt_queue_do_not_crash_startup(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from meeting_protocol.gui import main

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "queue.json").write_text("{not json")
    QApplication.instance() or QApplication([])
    notices = []
    monkeypatch.setattr(main.Window, "notice", lambda self, text: notices.append(text))
    window = main.Window()
    QApplication.processEvents()
    assert "set aside" in notices[0] and window.queue.entries == []

    messages = []
    monkeypatch.setattr(main, "require_offline", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    with pytest.raises(SystemExit) as exit_:
        main.launch()
    assert exit_.value.code == 0 and "already open" in messages[0]
    window.close()


def test_add_dialog_shows_placeholder_until_files_are_chosen(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from meeting_protocol.gui.main import NewRecording

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    QApplication.instance() or QApplication([])
    dialog = NewRecording(None)
    assert dialog.source_stack.currentWidget() is dialog.empty
    assert not dialog.remove.isEnabled()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: (["/x/a.wav"], ""))
    dialog.browse()
    assert dialog.source_stack.currentWidget() is dialog.sources
    dialog.sources.setCurrentRow(0)
    assert dialog.remove.isEnabled()
    dialog.remove_selected()
    assert dialog.source_stack.currentWidget() is dialog.empty
    dialog.close()


def test_resume_retries_a_failed_meeting_instead_of_duplicating_it(tmp_path, monkeypatch):
    app, window, worker = queue_window(tmp_path, monkeypatch)
    root = make_job(tmp_path, "broken", with_text=False)
    window.enqueue([["transcribe", str(tmp_path / "broken.wav")]])
    window.handle_event({"job": str(root), "status": "running"})
    window.errors = "Model crashed"
    finish_worker(window, worker, 1)
    app.processEvents()
    assert [e["state"] for e in window.queue.entries] == ["failed"]
    notices = []
    monkeypatch.setattr(window, "notice", notices.append)
    window.ask_delete(root)
    assert "Remove this meeting from the queue" in notices[0] and root.exists()

    window.open_job(root)
    window.resume_job(False)
    assert [e["state"] for e in window.queue.entries] == ["running"]
    assert worker["starts"][-1] == ["-m", "meeting_protocol.cli", "resume", str(root)]
    window.pause_queue()
    finish_worker(window, worker, 130)
    window.close()


def test_suspension_is_measured_from_a_late_tick():
    from meeting_protocol.logs import suspended_for

    assert suspended_for(1000.0, 1031.0, 30) == 0.0  # Timer jitter.
    assert suspended_for(1000.0, 1000.0 + 30 + 3600, 30) == 3600


def test_stall_is_logged_and_reported_without_transcript_text(tmp_path, monkeypatch):
    from meeting_protocol.gui import main
    from meeting_protocol.logs import path as log_path

    _app, window, worker = queue_window(tmp_path, monkeypatch)
    signals = []
    monkeypatch.setattr(main.os, "kill", lambda pid, sig: signals.append(sig))
    window.enqueue([["transcribe", str(tmp_path / "a.wav")]])
    window.pending = ""
    event = {"stage": "transcription", "done": 1, "total": 9, "latest": "Secret words"}
    monkeypatch.setattr(
        window.process, "readAllStandardOutput", lambda: (json.dumps(event) + "\n").encode()
    )
    main.Window.receive(window)

    # Sleeping for an hour is not a stall.
    window.last_tick -= 3600
    window.last_event -= 3600
    window.check_health()
    assert not window.stalled and not signals

    window.last_event -= main.STALL_SECONDS
    window.check_health()
    assert window.stalled and "No progress" in window.process_page.status
    if not main.WINDOWS:
        assert signals == [main.signal.SIGUSR1]
    text = log_path().read_text()
    assert "suspended for about 60 min" in text
    assert "progress: transcription 1/9" in text and "no progress for" in text
    assert "Secret words" not in text
    finish_worker(window, worker, 130)
    window.close()


def test_pause_that_does_not_stop_the_worker_is_forced(tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    _app, window, worker = queue_window(tmp_path, monkeypatch)
    timers, kills = [], []
    monkeypatch.setattr(QTimer, "singleShot", lambda ms, fn: timers.append(fn))
    monkeypatch.setattr(window.process, "kill", lambda: kills.append(True))
    window.enqueue([["transcribe", str(tmp_path / "a.wav")]])
    window.pause_queue()
    assert worker["stops"] == 1 and not kills
    timers[-1]()
    assert kills == [True]

    # A pause that ended in time leaves a later run alone.
    finish_worker(window, worker, 130)
    timers[-1]()
    assert kills == [True]
    window.close()


def test_any_start_failure_fails_the_entry_instead_of_wedging_the_queue(tmp_path, monkeypatch):
    import sqlite3

    from meeting_protocol.logs import path as log_path

    app, window, worker = queue_window(tmp_path, monkeypatch)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(window.process_page, "start", locked)
    window.enqueue([["transcribe", str(tmp_path / "a.wav")]])
    app.processEvents()
    assert window.active_entry is None and not worker["starts"]
    assert window.queue.entries[0]["state"] == "failed"
    assert "database is locked" in window.queue.entries[0]["error"]
    assert "OperationalError: database is locked" in log_path().read_text()
    window.close()


def test_entry_running_without_a_worker_is_recovered(tmp_path, monkeypatch):
    _app, window, worker = queue_window(tmp_path, monkeypatch)
    window.enqueue([["transcribe", str(tmp_path / "a.wav")]])
    worker["running"] = False  # The worker vanished without a finished signal.
    window.check_health()
    assert window.active_entry is not None  # One tick may be a race; two are not.
    window.check_health()
    assert window.active_entry is None
    assert window.queue.entries[0]["state"] == "failed"
    window.close()


def test_long_recording_names_do_not_widen_the_window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui.main import STYLE, Window

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    widths = {}
    for name in ("short", "Besprechung mit Konferenz " * 8 + "aufzeichnung"):
        for with_text in (True, False):
            root = make_job(tmp_path, f"{name[:5]}-{with_text}", with_text)
            config = json.loads((root / "job.json").read_text())
            audio = Path(config["input"]).rename(Path(config["input"]).with_name(f"{name}.wav"))
            (root / "job.json").write_text(json.dumps({**config, "input": str(audio)}))
            window = Window(str(root))
            window.show()
            app.processEvents()
            widths[name[:5], with_text] = window.minimumSizeHint().width()
            if name != "short":
                shown = window.title if with_text else window.process_page.heading
                assert shown.text().lower().startswith("besprechung")
                assert shown.toolTip().lower() == shown.text().lower()  # Full name on hover.
            window.close()
    assert widths["Bespr", True] == widths["short", True]
    assert widths["Bespr", False] == widths["short", False]
