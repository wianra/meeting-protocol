import json
from itertools import pairwise

import numpy as np
import pytest

from meeting_protocol.export import apply_corrections, plain_text, render_html
from meeting_protocol.transcript import assign, letter
from meeting_protocol.transcription import owned_words, windows


def test_exact_plain_export_no_metadata_and_merge_adjacent():
    turns = [
        {"speaker": "Speaker A", "text": 'Hallo.\nEr sagte "ja".', "start": 1},
        {"speaker": "Speaker A", "text": " Noch etwas. ", "start": 2},
        {"speaker": "Speaker B", "text": "Oui.", "start": 3},
        {"speaker": "Speaker A", "text": "Danke.", "start": 4},
    ]
    assert plain_text(turns) == (
        'Speaker A: Hallo. Er sagte "ja". Noch etwas.\nSpeaker B: Oui.\nSpeaker A: Danke.\n'
    )


def test_invalid_speaker_label_cannot_inject_extra_lines():
    with pytest.raises(ValueError):
        plain_text([{"speaker": "Speaker A\nSpeaker B", "text": "hello"}])


def test_speaker_identity_tracks_turns_not_language():
    exclusive = [
        {"start": 0, "end": 1, "speaker": "person-one"},
        {"start": 1, "end": 2, "speaker": "person-two"},
        {"start": 1200, "end": 1201, "speaker": "person-one"},
    ]
    assert (
        assign({"start": 0.2, "end": 0.4, "language": "de"}, exclusive, exclusive)[0]
        == "person-one"
    )
    assert (
        assign({"start": 1200.2, "end": 1200.4, "language": "fr"}, exclusive, exclusive)[0]
        == "person-one"
    )
    assert assign({"start": 1.2, "end": 1.4}, exclusive, exclusive)[0] == "person-two"


def test_overlap_and_unknown_attribution_are_explicit():
    regular = [{"start": 0, "end": 1, "speaker": "a"}, {"start": 0.2, "end": 0.8, "speaker": "b"}]
    speaker, flags = assign({"start": 0.3, "end": 0.5}, regular[:1], regular)
    assert speaker == "a" and "overlapping_speech" in flags
    assert assign({"start": 4, "end": 5}, regular, regular) == (None, ["speaker_unknown"])


def test_window_cores_cover_long_audio_exactly_once():
    pcm = np.zeros(120 * 60 * 16000, dtype=np.int16)
    regions = list(windows(pcm, 20))
    assert regions[0]["start"] == 0 and regions[-1]["end"] == len(pcm)
    assert all(a["end"] == b["start"] for a, b in pairwise(regions))
    assert all(0 < w["end"] - w["start"] <= 20 * 16000 for w in regions)


def test_context_ownership_preserves_real_repetition():
    entry = {
        "window": {"start": 0, "end": 16000, "read_start": 0},
        "language": "fr",
        "segments": [
            {
                "words": [
                    {"word": "Oui", "start": 0.1, "end": 0.2},
                    {"word": " oui", "start": 0.4, "end": 0.5},
                    {"word": " next", "start": 1.1, "end": 1.4},
                ]
            }
        ],
    }
    words, _ = owned_words([entry])
    assert [w["text"] for w in words] == ["Oui", " oui"]


def test_user_correction_does_not_claim_original_word_alignment():
    transcript = {"turns": [{"id": "one", "text": "old", "words": [{"text": "old"}]}]}
    edited = apply_corrections(
        transcript, {"one": {"text": "new", "speaker": "Speaker A", "reviewed": True}}
    )
    assert "words" not in edited["turns"][0]
    assert "original_words" in edited["turns"][0]
    assert transcript["turns"][0]["text"] == "old"


def test_html_escapes_content_and_disables_network():
    result = render_html(
        {
            "diarized": True,
            "issues": [],
            "turns": [
                {
                    "start": 0,
                    "end": 1,
                    "speaker": "Speaker A",
                    "language": "de",
                    "reviewed": False,
                    "flags": [],
                    "text": '<script src="https://bad.test/a"></script>',
                }
            ],
        }
    )
    assert "<script" not in result
    assert "default-src 'none'" in result


def test_speaker_labels_continue_beyond_z():
    assert [letter(i) for i in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]


def test_small_timing_gap_uses_nearby_speaker_but_marks_uncertainty():
    turns = [{"start": 0.3, "end": 1.0, "speaker": "a"}]
    assert assign({"start": 0.0, "end": 0.14}, turns, turns) == (
        "a",
        ["approximate_speaker_timing"],
    )
    ambiguous = [
        {"start": 0.0, "end": 1.0, "speaker": "a"},
        {"start": 1.2, "end": 2.0, "speaker": "b"},
    ]
    assert assign({"start": 1.08, "end": 1.12}, ambiguous, ambiguous)[0] is None


def test_export_versions_preserve_previous_text(tmp_path):
    from meeting_protocol.export import export_transcript
    from meeting_protocol.storage import Store

    store = Store(tmp_path)
    raw = {
        "job_id": "test",
        "diarized": True,
        "issues": [],
        "speakers": [],
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
    first = export_transcript(store, raw)
    store.correction("one", "Corrected", "Speaker B", True)
    second = export_transcript(store, raw)
    assert first["revision"] != second["revision"]
    previous = tmp_path / "exports" / "revisions" / first["revision"] / "transcript.txt"
    assert previous.read_text() == "Speaker A: Original\n"
    assert (tmp_path / "exports/transcript.txt").read_text() == "Speaker B: Corrected\n"
    assert second["speakers"][0]["label"] == "Speaker B"
    assert (
        json.loads((tmp_path / "exports/current.json").read_text())["revision"]
        == second["revision"]
    )
    store.close()


def named_fixture():
    turn = {"reviewed": False, "flags": [], "language": "de", "words": [{"text": "x"}], "end": 9}
    return {
        "job_id": "test",
        "diarized": True,
        "issues": [],
        "speakers": [{"id": "a", "label": "Speaker A"}, {"id": "b", "label": "Speaker B"}],
        "turns": [
            {
                **turn,
                "id": "1",
                "speaker": "Speaker A",
                "speaker_id": "a",
                "text": "Hi.",
                "start": 0,
            },
            {
                **turn,
                "id": "2",
                "speaker": "Speaker B",
                "speaker_id": "b",
                "text": "Hey.",
                "start": 1,
            },
            {
                **turn,
                "id": "3",
                "speaker": "Speaker B",
                "speaker_id": "b",
                "text": "Ok.",
                "start": 2,
            },
        ],
    }


def test_renamed_speaker_appears_in_every_turn_and_export(tmp_path):
    from meeting_protocol.export import export_transcript, rename_speakers
    from meeting_protocol.storage import Store

    store = Store(tmp_path)
    raw = named_fixture()
    rename_speakers(store, raw, {"Speaker B": "Raphael Winkler"})
    result = export_transcript(store, raw)
    assert [t["speaker"] for t in result["turns"]] == ["Speaker A", "Raphael Winkler"] * 1 + [
        "Raphael Winkler"
    ]
    assert {"id": "b", "label": "Raphael Winkler"} in result["speakers"]
    # A rename is not a text correction: word alignment and review state stay.
    assert all(t["words"] and not t["reviewed"] for t in result["turns"])
    assert (tmp_path / "exports/transcript.txt").read_text() == (
        "Speaker A: Hi.\nRaphael Winkler: Hey. Ok.\n"
    )
    store.close()


def test_rename_follows_speaker_through_later_corrections(tmp_path):
    from meeting_protocol.export import corrected, rename_speakers
    from meeting_protocol.storage import Store

    store = Store(tmp_path)
    raw = named_fixture()
    rename_speakers(store, raw, {"Speaker B": "Raphael"})
    store.correction("1", "Hi.", "Raphael", False)
    rename_speakers(store, raw, {"Raphael": "Raphael Winkler"})
    assert {t["speaker"] for t in corrected(store, raw)["turns"]} == {"Raphael Winkler"}
    store.close()


def test_renames_in_one_step_do_not_chain(tmp_path):
    from meeting_protocol.export import corrected, rename_speakers
    from meeting_protocol.storage import Store

    store = Store(tmp_path)
    raw = named_fixture()
    rename_speakers(store, raw, {"Speaker A": "Speaker B", "Speaker B": "Anna"})
    assert [t["speaker"] for t in corrected(store, raw)["turns"]] == ["Speaker B", "Anna", "Anna"]
    store.close()


@pytest.mark.parametrize(
    ("old", "new"),
    [("Speaker A", "Bad: name"), ("Speaker A", ""), ("Speaker Unknown", "X"), ("Nobody", "X")],
)
def test_invalid_renames_are_rejected(tmp_path, old, new):
    from meeting_protocol.export import rename_speakers
    from meeting_protocol.storage import Store

    store = Store(tmp_path)
    with pytest.raises(ValueError):
        rename_speakers(store, named_fixture(), {old: new})
    assert store.speaker_names() == []
    store.close()
