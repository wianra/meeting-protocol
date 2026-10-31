"""Deterministic plain text plus a separate, self-contained review report."""

import copy
import html
import json
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


def apply_corrections(transcript, corrections):
    result = copy.deepcopy(transcript)
    for turn in result["turns"]:
        if turn["id"] in corrections:
            update = corrections[turn["id"]]
            turn.update(update)
            if "job_id" in result:
                known = {s["label"]: s["id"] for s in result.get("speakers", [])}
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
    return result


def merged_turns(turns):
    merged = []
    for turn in turns:
        label = turn["speaker"].strip()
        if not label or any(c in label for c in '\n\r:"'):
            raise ValueError("Speaker labels must be a single line without quotes or colons.")
        text = re.sub(r"\s+", " ", turn["text"]).strip()
        if merged and merged[-1][0] == label:
            merged[-1][1] += " " + text
        else:
            merged.append([label, text])
    return merged


def plain_text(turns):
    return "".join(
        f"{label}: {json.dumps(text, ensure_ascii=False)}\n" for label, text in merged_turns(turns)
    )


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
    result = apply_corrections(transcript, store.corrections())
    result["review_status"] = (
        "reviewed"
        if (
            result["turns"] and all(t["reviewed"] for t in result["turns"]) and not result["issues"]
        )
        else "draft"
    )
    folder = store.root / "exports"
    revision = fingerprint({"transcript": result, "export_format_version": 2})[:16]
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
