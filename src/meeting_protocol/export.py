"""Deterministic plain text plus a separate, self-contained review report."""

import copy
import html
import re
import uuid
from pathlib import Path

from .storage import atomic_write, canonical, fingerprint
from .word import word_document

EXPORT_FILES = {
    ".docx": "transcript.docx",
    ".txt": "transcript.txt",
    ".json": "transcript.json",
    ".html": "review.html",
}

FLAG_LABELS = {
    "speaker_boundary": "Check speaker at this transition",
    "speaker_unknown": "Speaker needs assigning",
    "approximate_speaker_timing": "Speaker assigned from nearby speech; please check",
    "overlapping_speech": "Voices overlap",
    "low_recognition_confidence": "Wording needs checking",
    "low_word_confidence": "Some words are uncertain",
    "possible_repetition": "Check repeated wording",
    "unexpected_language": "Check the detected language",
    "segment_timing_only": "Timing is approximate",
    "window_boundary": "Check the transition between passages",
}


def describe_flags(flags):
    return " · ".join(FLAG_LABELS.get(flag, flag.replace("_", " ")) for flag in flags)


def apply_corrections(transcript, corrections, names=()):
    """Per-turn corrections, then speaker names, which follow the speaker ID, not the label.

    `names` is the (speaker_id, name) history; the last name for each speaker is current.
    """
    result = copy.deepcopy(transcript)
    # A corrected label may be an original label or any name given since, newest first.
    known = {s["label"]: s["id"] for s in result.get("speakers", [])}
    for speaker_id, name in reversed(names):
        known.setdefault(name, speaker_id)
    names = dict(names)
    for turn in result["turns"]:
        if turn["id"] in corrections:
            update = corrections[turn["id"]]
            turn.update(update)
            if "job_id" in result:
                turn["speaker_id"] = known.get(
                    turn["speaker"],
                    str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL, result["job_id"] + ":manual:" + turn["speaker"]
                        )
                    ),
                )
            turn["human_edited"] = True
            # Word-level alignment belongs to the original text, never to the edited text.
            turn["original_words"] = turn.pop("words", [])
    if "speakers" in result:
        seen = {s["id"] for s in result["speakers"]}
        for turn in result["turns"]:
            if turn.get("speaker_id") and turn["speaker_id"] not in seen:
                result["speakers"].append({"id": turn["speaker_id"], "label": turn["speaker"]})
                seen.add(turn["speaker_id"])
        for speaker in result["speakers"]:
            speaker["label"] = names.get(speaker["id"], speaker["label"])
    for turn in result["turns"]:
        turn["speaker"] = names.get(turn.get("speaker_id"), turn["speaker"])
    return result


def corrected(store, transcript):
    return apply_corrections(transcript, store.corrections(), store.speaker_names())


def check_label(label):
    if not label or any(c in label for c in '\n\r:"'):
        raise ValueError("Speaker labels must be a single line without quotes or colons.")


def rename_speakers(store, transcript, names):
    """Name every turn labelled with each `{current label: name}`. A shared name merges them.

    All labels are resolved before any is saved, so swapping or chaining names is safe.
    """
    turns = corrected(store, transcript)["turns"]
    resolved = []
    for old, new in names.items():
        old, new = old.strip(), new.strip()
        check_label(new)
        if old == "Speaker Unknown":
            raise ValueError("Assign unknown turns one by one; they may be different people.")
        ids = {t["speaker_id"] for t in turns if t["speaker"] == old}
        if not ids:
            raise ValueError(f"No speaker is labelled {old!r}.")
        if None in ids:
            raise ValueError(f"{old!r} has no speaker identity to rename; correct its turns.")
        resolved.append((sorted(ids), new))
    for ids, new in resolved:
        store.rename_speaker(ids, new)


def merged_turns(turns):
    merged = []
    for turn in turns:
        label = turn["speaker"].strip()
        check_label(label)
        text = re.sub(r"\s+", " ", turn["text"]).strip()
        if merged and merged[-1][0] == label:
            merged[-1][1] += " " + text
        else:
            merged.append([label, text])
    return merged


def plain_text(turns):
    return "".join(f"{label}: {text}\n" for label, text in merged_turns(turns))


def render_html(transcript):
    rows = []
    for t in transcript["turns"]:
        flags = describe_flags(t["flags"]) if not t["reviewed"] else "Reviewed"
        rows.append(
            f'<article><div class="meta">{t["start"]:.1f}–{t["end"]:.1f}s · '
            f"{html.escape(t['speaker'])} · {html.escape(t['language'])}</div>"
            f"<p>{html.escape(t['text'])}</p><small>{html.escape(flags)}</small></article>"
        )
    issue_rows = "".join(
        f"<li>{i['start']:.1f}–{i['end']:.1f}s: {html.escape(i['message'])}</li>"
        for i in transcript["issues"]
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'\">"
        "<title>Meeting transcript review</title><style>"
        "body{font:17px/1.6 system-ui;max-width:850px;margin:3rem auto;padding:0 2rem;"
        "background:#f6f5f1;color:#162c32}article{background:white;padding:1.2rem 1.5rem;"
        "margin:1rem 0;border-radius:12px}.meta,small{font-size:13px;color:#53676c}"
        "p{margin:.5rem 0}h1{font-size:32px}</style><h1>Meeting transcript</h1>"
        "<p>Local draft. Use the desktop app to listen, correct text and assign speakers. "
        "Word timings are approximate, especially for Swiss German reformulation.</p>"
        + ("<p>Speaker diarisation has not been run.</p>" if not transcript["diarized"] else "")
        + (f"<h2>Passages to check</h2><ul>{issue_rows}</ul>" if issue_rows else "")
        + "".join(rows)
        + "</html>"
    )


def export_transcript(store, transcript):
    result = corrected(store, transcript)
    result["review_status"] = (
        "reviewed"
        if (
            result["turns"] and all(t["reviewed"] for t in result["turns"]) and not result["issues"]
        )
        else "draft"
    )
    folder = store.root / "exports"
    revision = fingerprint({"transcript": result, "export_format_version": 3})[:16]
    result["revision"] = revision
    outputs = {
        "transcript.txt": plain_text(result["turns"]).encode(),
        "transcript.docx": word_document(merged_turns(result["turns"])),
        "transcript.json": canonical(result),
        "review.html": render_html(result).encode(),
    }
    for name, data in outputs.items():
        atomic_write(folder / "revisions" / revision / name, data)
    atomic_write(folder / "current.json", canonical({"revision": revision}))
    for name, data in outputs.items():
        atomic_write(folder / name, data)
    return result


def export_to_file(store, transcript, destination):
    """Export the current corrected revision, never stale UI/model text. Caller holds job lock."""
    destination = Path(destination).expanduser().resolve()
    name = EXPORT_FILES.get(destination.suffix.lower())
    if name is None:
        raise ValueError("Choose a .docx, .txt, .json or .html filename.")
    source = transcript.get("source_path")
    if source and destination == Path(source).resolve():
        raise ValueError("Choose a destination other than the original recording.")
    root = store.root.resolve()
    if (
        destination.is_relative_to(root)
        and destination != root / "exports" / name
        and (
            not destination.is_relative_to(root / "exports")
            or destination.is_relative_to(root / "exports" / "revisions")
            or destination.name == "current.json"
        )
    ):
        raise ValueError("Choose a destination outside the meeting's internal data files.")
    result = export_transcript(store, transcript)
    revision_file = root / "exports" / "revisions" / result["revision"] / name
    atomic_write(destination, revision_file.read_bytes())
    return result
