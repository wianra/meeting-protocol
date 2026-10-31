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
