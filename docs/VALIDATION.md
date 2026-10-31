# Validation — 31 October 2026

Environment: Apple M4 Pro, 24 GB RAM, macOS. Python 3.12.8; pinned dependencies in `uv.lock`. All sample inference ran under the application's macOS network-denial profile. No recording or transcript text was sent to a cloud model for assessment.

## Completed checks

| Check | Result |
| --- | --- |
| Input inspection | `audio.m4a`: mono AAC, 48 kHz, approximately 28.2 seconds. |
| Local ASR | Whisper large-v3/MLX completed two windows and detected German/French. Text was saved locally. |
| Speaker analysis | Community-1 completed and inferred two speakers. |
| Sample compute timing | Initial ASR batches: 10.10 seconds total, 8.28 seconds maximum. Speaker segmentation batches: 0.46 seconds total; embedding batches: 6.27 seconds total, about 1 second maximum. These exclude model loading, verification and first-run setup. |
| Unmodified pipeline comparison | Original pyannote output exactly matched the resumable adapter's regular and exclusive speaker intervals on this sample. Baseline pipeline call took 7.34 seconds in that check. |
| Feature-cache resume | Reused all 12 saved neural batches with zero new neural batches; final result matched. |
| Real ASR crash | Killed a test worker with SIGKILL after a committed window, resumed, verified the original checkpoint was unchanged and results matched uninterrupted inference. |
| Real diarisation crash | Killed a test worker after a committed embedding batch, resumed, verified checkpoint reuse and identical final output. |
| Unit tests | 18 passing tests: durability after process death, corrupt artifacts, cache invalidation, locking, correction retention, two-hour window coverage, speaker attribution, overlap/uncertainty and plain/HTML export. |
| Desktop | Rendered with synthetic text; tested explicit meeting selection, selecting a turn, editing, review marking and export. Fixed initial selection incorrectly overriding an explicitly opened meeting. |
| Network isolation | Runtime loopback connection was denied by the OS. ASR and speaker analysis both completed with networking denied. |

The full local sample job is `ef3ced2601ae83e6`. Its exports and review app remain on this machine. Validation scripts and machine-readable integration results are under `work/` and are not committed by default.

## What these checks do not prove

- There is no human-reviewed reference transcript yet. No WER, DER or accuracy percentage is claimed.
- The sample does not establish Italian accuracy, coverage of Swiss dialects, 2–10-speaker meeting quality or handling of persistent overlap.
- Two-hour window-coverage tests validate scheduling boundaries, not two-hour model quality or end-to-end memory consumption.
- No real hour-long meeting has completed the full pipeline yet. Global clustering and reconstruction do not have intra-step checkpoints; the three-minute computation-loss requirement remains an acceptance target for long-recording validation.
- The sample's approximate word timings required conservative nearest-speech attribution for two short gaps; these assignments are flagged for review. Swiss German reformulation can make word alignment approximate more generally.
- GUI playback controls and media loading are present; the automated test used generated silence and did not assess the user's listening experience or audio output device.
- The current desktop launcher uses the project environment. It is not a signed/notarised standalone Mac installer.

## Correction export update

Added an Export save dialog and Open export folder button, plus an editable Word format generated locally without additional dependencies. The UI saves pending editor changes before export; plain-text content/format remains unchanged. CLI export also accepts `--output`.

All 22 tests pass, including latest-correction export, Word XML escaping and Unicode, no embedded private metadata or external resources, immutable export history, extension selection, cancelled dialogs, protected internal job files and disabled export during processing. A synthetic German/French/Italian document was rendered to two pages and both page images inspected; wrapping and long-turn pagination were clean. No private meeting text was used in the visual preview.

Next useful validation: review the sample locally, then run a representative hour-long meeting and annotate several excerpts covering each language, returning speakers, overlap and important names/numbers. Use those results to decide whether a Swiss German specialist or second ASR model is worthwhile.
