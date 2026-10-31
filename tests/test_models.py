import json

import pytest

from meeting_protocol.models import install_bundled, is_installed, model_info
from meeting_protocol.storage import digest_file


def make_bundle(root, content=b"weights"):
    model = root / "diarization" / "rev1"
    model.mkdir(parents=True)
    (model / "config.yaml").write_bytes(content)
    manifest = {
        "repository": "example/model",
        "revision": "rev1",
        "files": {"config.yaml": digest_file(model / "config.yaml")},
    }
    (root / "diarization" / "manifest.json").write_text(json.dumps(manifest))
    return model


def test_bundled_model_is_copied_into_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("MEETING_PROTOCOL_BUNDLED_MODELS", str(tmp_path / "app"))
    make_bundle(tmp_path / "app")
    assert not is_installed("diarization")
    install_bundled("diarization")
    info = model_info("diarization")
    # Jobs record this path, so it must not point into the (movable) app bundle.
    assert info["path"] == str(tmp_path / "data" / "models" / "diarization" / "rev1")
    assert is_installed("diarization")


def test_damaged_bundled_model_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("MEETING_PROTOCOL_BUNDLED_MODELS", str(tmp_path / "app"))
    model = make_bundle(tmp_path / "app")
    (model / "config.yaml").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="damaged"):
        install_bundled("diarization")
    assert not is_installed("diarization")


def test_no_bundle_outside_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("MEETING_PROTOCOL_BUNDLED_MODELS", raising=False)
    with pytest.raises(RuntimeError, match="No bundled"):
        install_bundled("diarization")


def test_failed_app_launch_is_logged_and_shown(tmp_path, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QMessageBox

    from meeting_protocol import cli

    monkeypatch.setenv("DIARIZE_HOME", str(tmp_path / "data"))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: shown.append(a[2]))
    try:
        raise RuntimeError("The bundled diarization model is damaged; reinstall the app.")
    except RuntimeError as exc:
        cli.report_launch_error(exc)
    log = (tmp_path / "data" / "logs" / "app.log").read_text()
    assert "RuntimeError" in log and "damaged" in log
    assert "damaged" in shown[0] and "app.log" in shown[0]
