"""Build check, run by the packaged Meeting Protocol.exe with a minimal PATH: everything the
app needs must load from the folder itself. Prints "smoke ok" on success."""

import math
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path

home = Path(tempfile.mkdtemp())
os.environ["DIARIZE_HOME"] = str(home)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from meeting_protocol.privacy import configure, enter_sandbox, network_is_denied

configure()
enter_sandbox()
assert network_is_denied(), "network guard inactive"
assert sys.executable.endswith("Meeting Protocol.exe"), sys.executable
print("python", sys.version.split()[0], sys.executable)

# Locks: a second holder must be refused.
from meeting_protocol.storage import lock

with lock(home / "test.lock"):
    try:
        with lock(home / "test.lock"):
            raise AssertionError("lock was not exclusive")
    except RuntimeError:
        pass
print("locks ok")

# ffmpeg/ffprobe from the bundled bin folder, as the app calls them.
from meeting_protocol.audio import inspect_audio

sample = home / "tone ü.wav"
with wave.open(str(sample), "wb") as out:
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(16000)
    out.writeframes(
        b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(16000 * 3))
    )
info = inspect_audio(sample)
assert info["channels"] == 1 and abs(info["duration"] - 3) < 0.1, info
print("ffprobe ok", info)

# Speaker model from the bundle, run on noise.
import torch
from pyannote.audio import Pipeline

from meeting_protocol.models import install_bundled, model_info

install_bundled("diarization")
pipeline = Pipeline.from_pretrained(model_info("diarization")["path"])
pipeline({"waveform": torch.randn(1, 16000 * 5) * 0.01, "sample_rate": 16000})
print("pyannote ok")

import ctranslate2  # noqa: F401
import faster_whisper  # noqa: F401

from meeting_protocol.jobs import runtime_versions

print("runtime", runtime_versions())

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from meeting_protocol.compat import WorkerGroup
from meeting_protocol.gui.common import set_app_icon
from meeting_protocol.gui.main import STYLE, Window

app = QApplication([])
set_app_icon(app)
app.setStyleSheet(STYLE)
player = QMediaPlayer()
window = Window()
window.show()
app.processEvents()
assert WorkerGroup().job, "job object not created"
print("smoke ok")
