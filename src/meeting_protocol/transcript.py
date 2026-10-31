"""Speaker attribution and conservative turn assembly; no generative rewriting."""

import re
import uuid

from .storage import fingerprint
from .transcription import owned_words


def letter(index: int) -> str:
    value = ""
    while index >= 0:
        value = chr(65 + index % 26) + value
        index = index // 26 - 1
    return value


def intersection(a, b, c, d):
    return max(0.0, min(b, d) - max(a, c))


def assign(word, exclusive, overlapping):
    a, b = word["start"], word["end"]
    if b - a < 0.02:
        a, b = a - 0.01, b + 0.01
    scores = {}
    for turn in exclusive:
        score = intersection(a, b, turn["start"], turn["end"])
        scores[turn["speaker"]] = scores.get(turn["speaker"], 0.0) + score
    ranked = sorted(((s, t) for s, t in scores.items() if t > 0), key=lambda x: -x[1])
    flags = []
    if not ranked:
        # ASR word timing can slightly precede/follow a detected speech boundary.
        distances = {}
        for turn in exclusive:
            distance = max(turn["start"] - b, a - turn["end"], 0.0)
            distances[turn["speaker"]] = min(distance, distances.get(turn["speaker"], float("inf")))
        near = sorted(distances.items(), key=lambda item: item[1])
        if near and near[0][1] <= 0.2 and (len(near) == 1 or near[1][1] - near[0][1] >= 0.05):
            return near[0][0], ["approximate_speaker_timing"]
        return None, ["speaker_unknown"]
    speaker, coverage = ranked[0]
    if coverage / (b - a) < 0.5 or (len(ranked) > 1 and ranked[1][1] > coverage * 0.5):
        flags.append("speaker_boundary")
    active = {t["speaker"] for t in overlapping if intersection(a, b, t["start"], t["end"]) > 0.02}
    if len(active) > 1:
        flags.append("overlapping_speech")
    return speaker, flags


def assemble(config, asr, diarization=None):
    words, issues = owned_words(asr)
    ordered_speakers = []
    if diarization:
        for t in sorted(diarization["turns"], key=lambda t: t["start"]):
            if t["speaker"] not in ordered_speakers:
                ordered_speakers.append(t["speaker"])
    speakers = {
        s: {
            "label": f"Speaker {letter(i)}",
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, config["input_sha256"] + s)),
        }
        for i, s in enumerate(ordered_speakers)
    }
    turns = []
    for word in words:
        speaker, flags = (
            assign(word, diarization["exclusive"], diarization["turns"])
            if diarization
            else (None, ["speaker_unknown"])
        )
        word["speaker_id"] = speakers.get(speaker, {}).get("id")
        word["flags"] += flags
        label = speakers.get(speaker, {}).get("label", "Speaker Unknown")
        # Preserve the source meaning; Swiss German is rendered in the model's Standard German.
        if word["language"] == "de":
            word["text"] = word["text"].replace("ß", "ss")
        if (
            turns
            and turns[-1]["speaker"] == label
            and turns[-1]["language"] == word["language"]
            and word["start"] - turns[-1]["end"] < 2.0
        ):
            turn = turns[-1]
            turn["end"] = max(turn["end"], word["end"])
            turn["text"] += word["text"]
            turn["words"].append(word)
            turn["flags"] = sorted(set(turn["flags"] + word["flags"]))
        else:
            turns.append(
                {
                    "id": fingerprint([config["input_sha256"], len(turns), word["start"]])[:24],
                    "speaker": label,
                    "speaker_id": word["speaker_id"],
                    "start": word["start"],
                    "end": word["end"],
                    "text": word["text"],
                    "language": word["language"],
                    "words": [word],
                    "flags": sorted(set(word["flags"])),
                    "reviewed": False,
                }
            )
    for turn in turns:
        turn["text"] = re.sub(r"\s+", " ", turn["text"]).strip()
    if diarization:
        for interval in diarization["exclusive"]:
            covered = sum(
                intersection(w["start"], w["end"], interval["start"], interval["end"])
                for w in words
            )
            if interval["end"] - interval["start"] > 0.7 and covered < 0.15:
                issues.append(
                    {
                        **interval,
                        "kind": "speech_without_text",
                        "message": "Detected speech has no matching transcript; review audio.",
                    }
                )
    return {
        "schema_version": 1,
        "job_id": config["job_id"],
        "source_sha256": config["input_sha256"],
        "source_path": config["input"],
        "diarized": diarization is not None,
        "speakers": list(speakers.values()),
        "turns": turns,
        "issues": issues,
        "models": config["models"],
        "language_policy": "de/fr/it; Swiss German rendered as Standard German",
        "timing_note": "Approximate word timings; dialect reformulation may change word order.",
    }
