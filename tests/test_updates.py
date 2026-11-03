import io
import json
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

from meeting_protocol import updates


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path))
    return tmp_path


def test_versions_compare_numerically_and_ignore_other_tags():
    assert updates.newer("0.10.0", "0.9.9") and updates.newer("v1.0.0", "0.2.0")
    assert not updates.newer("0.2.0", "0.2.0") and not updates.newer("0.1.9", "0.2.0")
    assert not updates.newer("windows-test", "0.2.0") and not updates.newer(None, "0.2.0")


def test_nothing_is_fetched_until_the_user_agrees(data, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "fetch", lambda: calls.append(1) or {})
    monkeypatch.setattr(updates.subprocess, "Popen", lambda *a, **k: calls.append(a))
    assert updates.allowed() is None
    updates.start_check()
    updates.check()
    updates.set_allowed(False)
    updates.start_check()
    updates.check()
    assert calls == [] and not updates.result_path().exists()
    updates.set_allowed(True)
    updates.start_check()
    assert calls[0][0][-1] == "_updates"


def test_check_saves_a_newer_release_and_failures_stay_silent(data, monkeypatch):
    updates.set_allowed(True)
    release = {"tag_name": "v9.0.0", "html_url": updates.RELEASES + "tag/v9.0.0"}
    seen = []

    def urlopen(request, timeout, context):
        seen.append(request.full_url)
        return io.BytesIO(json.dumps(release).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    updates.check()
    assert seen == [updates.LATEST]
    assert updates.available() == {"version": "9.0.0", "url": release["html_url"]}

    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    updates.check()  # Keeps the earlier answer; never raises.
    assert updates.available()["version"] == "9.0.0"


def test_only_newer_releases_on_the_project_page_are_offered(data):
    path = updates.result_path()
    for version, url, expected in (
        ("9.0.0", "https://example.com/evil", None),
        ("0.0.1", updates.RELEASES + "tag/v0.0.1", None),
        ("9.0.0", updates.RELEASES + "tag/v9.0.0", "9.0.0"),
    ):
        path.write_text(json.dumps({"version": version, "url": url}))
        assert (updates.available() or {}).get("version") == expected
    path.write_text("{broken")
    assert updates.available() is None


def test_window_asks_once_then_shows_the_notice(data, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui import main

    monkeypatch.setenv(updates.ENABLED, "1")
    app = QApplication.instance() or QApplication([])
    window = main.Window()
    window.show()
    app.processEvents()
    assert window.update_ask.isVisible() and not window.update_card.isVisible()
    assert not window.update_toggle.isVisible()
    window.allow_updates(True)
    assert updates.allowed() is True and not window.update_ask.isVisible()
    assert window.update_toggle.isVisible() and window.update_toggle.isChecked()

    # The separate check process writes its answer while the window is open.
    url = updates.RELEASES + "tag/v9.0.0"
    updates.result_path().write_text(json.dumps({"version": "9.0.0", "url": url}))
    opened = []
    monkeypatch.setattr(main.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    window.poll_update()
    assert window.update_card.isVisible() and "9.0.0" in window.update_text.text()
    window.open_update()
    assert opened == [url]

    window.update_toggle.setChecked(False)
    assert updates.allowed() is False and not window.update_card.isVisible()
    window.close()


def test_source_checkouts_show_no_update_controls(data, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from meeting_protocol.gui import main

    monkeypatch.delenv(updates.ENABLED, raising=False)
    QApplication.instance() or QApplication([])
    window = main.Window()
    assert not hasattr(window, "update_ask")
    window.close()
