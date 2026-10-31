import io
import json
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from meeting_protocol.export import export_to_file, merged_turns
from meeting_protocol.storage import Store
from meeting_protocol.word import W, word_document


def paragraphs(data):
    with ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        return ["".join(p.itertext()) for p in root.findall(f".//{{{W}}}p")]


def test_word_preserves_multilingual_text_and_has_no_private_metadata():
    turns = [
        {"speaker": "Speaker A", "text": 'Grüezi & bienvenue. Er sagte "ja".'},
        {"speaker": "Speaker A", "text": "Encore une chose."},
        {"speaker": "Speaker B", "text": "È già pronto <oggi>."},
    ]
    doc = word_document(merged_turns(turns))
    assert paragraphs(doc) == [
        'Speaker A: Grüezi & bienvenue. Er sagte "ja". Encore une chose.',
        "Speaker B: È già pronto <oggi>.",
    ]
    with ZipFile(io.BytesIO(doc)) as archive:
        assert "docProps/core.xml" not in archive.namelist()
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        assert b'TargetMode="External"' not in b"".join(archive.read(n) for n in archive.namelist())
        assert b"<w:b/>" in archive.read("word/document.xml")
        assert b"<w:keepLines" not in archive.read("word/document.xml")
    assert doc == word_document(merged_turns(turns))


def test_word_rejects_invalid_xml_characters():
    with pytest.raises(ValueError, match="control character"):
        word_document([("Speaker A", "bad\x00text")])


def fixture():
    return {
        "job_id": "test",
        "diarized": True,
        "issues": [],
        "turns": [
            {
                "id": "one",
                "speaker": "Speaker A",
                "text": "Original",
                "reviewed": False,
                "flags": [],
                "start": 0.0,
                "end": 1.0,
                "language": "de",
                "words": [],
            }
        ],
    }


def test_save_as_uses_latest_correction_without_changing_old_revision(tmp_path):
    store = Store(tmp_path / "job")
    raw = fixture()
    first = export_to_file(store, raw, tmp_path / "before.docx")
    store.correction("one", "Korrigiert", "Speaker B", True)
    second = export_to_file(store, raw, tmp_path / "after.docx")
    assert paragraphs((tmp_path / "before.docx").read_bytes()) == ["Speaker A: Original"]
    assert paragraphs((tmp_path / "after.docx").read_bytes()) == ["Speaker B: Korrigiert"]
    assert first["revision"] != second["revision"]
    saved = json.loads((store.root / "exports/transcript.json").read_text())
    assert saved["turns"][0]["reviewed"] is True
    assert raw["turns"][0]["text"] == "Original"
    store.close()


def test_save_as_cannot_overwrite_internal_job_data(tmp_path):
    store = Store(tmp_path / "job")
    for dest in (
        store.root / "job.json",
        store.root / "exports/current.json",
        store.root / "exports/revisions/old/transcript.docx",
    ):
        with pytest.raises(ValueError, match="internal data"):
            export_to_file(store, fixture(), dest)
    with pytest.raises(ValueError, match="filename"):
        export_to_file(store, fixture(), tmp_path / "unknown.pdf")
    store.close()
