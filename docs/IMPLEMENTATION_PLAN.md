# Local multilingual meeting transcription — research and implementation plan

Research date: 31 October 2026. The plan below records the original research. Implementation has begun; see the project README.md and docs/VALIDATION.md for the delivered baseline, measured tests and remaining work. Confirmed preferences: Apple Silicon Mac, Swiss German rendered as Standard German, typically 2–10 speakers.

## 1. Recommendation

Build a local application around a resumable Python processing engine, with separate transcription and speaker diarisation components. Start by benchmarking **Whisper large-v3**, a Swiss German fine-tune, and **Qwen3-ASR** on representative local excerpts. Use **pyannote Community-1** as the initial diarisation baseline. Select the production models from those results, rather than assuming that a specialised model always wins.

For the first implementation, target the available **MacBook Pro, Apple M4 Pro, 24 GB unified memory**. Use MLX for compatible speech recognition models; start pyannote on CPU, with Apple GPU execution only if the compatibility spike validates it. Run large models sequentially to control memory usage. Keep backend interfaces portable for a later Windows/Linux version.

The hardest engineering requirement is durable progress during diarisation while maintaining consistent speaker identities across the entire meeting. Solve and test this early, before building a polished interface.

This document is the requested research and plan, not an implemented application. The original planning folder contained no audio sample. The working project folder is where `audio.m4a` is available for a future local spike. During the original research no audio was uploaded and no weights were downloaded. The subsequent implementation has downloaded models using a locally configured credential and processed the sample offline; see VALIDATION.md.

## 2. Requirements and provisional decisions

| Item | Proposed behaviour |
| --- | --- |
| Languages | German, Swiss German, French and Italian, including switches during one meeting and within a speaker's turn. |
| Swiss German output | Provisionally, readable Standard German. Dialect-preserving spelling would be a separate requirement and benchmark. |
| Other languages | Preserve the spoken language. Do not translate French or Italian into German by default. |
| Meaning of “protocol” | A complete speaker-attributed transcript. Summarised minutes and action items are optional later outputs. |
| Speakers | Anonymous, meeting-wide identities: Speaker A, Speaker B, etc. Optional manual names; no automatic real-person identification. |
| Duration | At least 60–120 minutes; bounded processing and storage should allow longer recordings. |
| Privacy | Audio, transcripts, voice embeddings and derived content stay on the device. Separate online model provisioning from offline processing. |
| Recovery | Target at most three minutes of lost computation after a crash on the supported machine. This is a measured release criterion, not a property implied by chunk length. |
| Speed | Prioritise accuracy and resumability. Report measured processing speed; no advance promise of real-time execution. |
| Interface | CLI first for testing and recovery; then a local desktop review interface. |

Confirmed by the user: target Apple Silicon Macs like this M4 Pro, render Swiss German as Standard German, and expect roughly 2–10 meeting participants.

## 3. What the research supports

### Candidate models and runtimes

| Candidate | Why include it | Limitations and decision |
| --- | --- | --- |
| Whisper large-v3 | Established multilingual baseline covering de/fr/it; useful starting point for Swiss German. | Swiss German output often becomes Standard German. Evaluate hallucinations, switches and names on actual meeting audio. First baseline. [Model card](https://huggingface.co/openai/whisper-large-v3), [Swiss German evaluation paper](https://arxiv.org/abs/2404.19310). |
| MLX Whisper | Apple Silicon implementation with local model loading and word timestamps. | Runtime, not a distinct recognition model. Conversion, precision and decoding settings need reproducible validation. Preferred initial Mac backend. [Maintainer documentation](https://github.com/ml-explore/mlx-examples/tree/main/whisper). |
| gcoli/whisper-large-v3-swiss-german-mit | Swiss German → Standard German fine-tune; model card declares MIT and reports comparisons with its base model. | Author-reported results, not a meeting benchmark. Mac conversion and preservation of other languages need testing. First specialised challenger. [Model card](https://huggingface.co/gcoli/whisper-large-v3-swiss-german-mit). |
| Flix-AI/flix-swissgerman-full | Another Swiss German → Standard German large-v3 fine-tune; card declares Apache-2.0. | Subtitle-derived training can favour editorial wording. Reserve challenger if the first specialist disappoints; inspect provenance before bundling. [Model card](https://huggingface.co/Flix-AI/flix-swissgerman-full). |
| Flurin17/whisper-large-v3-turbo-swiss-german | Accessible Swiss German specialist worth knowing about. | Current card declares **CC BY-NC 4.0**. Do not make this the default for work/commercial meetings. No assumption that “Swiss German” in its name implies superior accuracy. [Model card](https://huggingface.co/Flurin17/whisper-large-v3-turbo-swiss-german?library=transformers). |
| Qwen3-ASR-1.7B | Independent multilingual challenger; explicitly lists German, French and Italian. Apache-2.0 model card. | Swiss German is not explicitly validated by the listed language support. Test recognition and language switches; evaluate the separate forced aligner only on text that corresponds to the speech. [Model card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), [official implementation](https://github.com/QwenLM/Qwen3-ASR). |
| Parakeet TDT 0.6B v3 | Smaller multilingual alternative with word/segment timestamps and de/fr/it support; card declares CC BY 4.0. | No established Swiss German meeting accuracy from this research. Optional second-round comparison; speed alone is not a reason to prefer it. [Model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3). |
| pyannote speaker-diarization-community-1 | Local diarisation with overlap-aware and exclusive outputs, optional speaker-count hints and documented offline loading. | Gated initial download and CC BY 4.0 attribution. Speaker assignment remains fallible. Progress callbacks do not provide durable recovery. Initial diarisation baseline. [Model card](https://huggingface.co/pyannote/speaker-diarization-community-1). |

MLX Audio currently documents Qwen3-ASR, its aligner and Parakeet support. These are useful Mac integration paths, but community ports and converted weights must be pinned and compared with their upstream behaviour. [MLX Audio repository](https://github.com/Blaizzy/mlx-audio).

For portability, keep **faster-whisper** as the CPU/NVIDIA backend and **whisper.cpp** as another Apple Silicon option. Do not design around CUDA on this Mac or assume faster-whisper supplies a Metal backend. [faster-whisper documentation](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp documentation](https://github.com/ggml-org/whisper.cpp).

### Why not simply wrap an existing all-in-one pipeline?

WhisperX is useful as a comparison implementation, but its documented limitations include imperfect diarisation, overlapping speech and language-specific alignment models. It does not by itself establish the required multilingual routing and crash-recovery behaviour. [WhisperX limitations](https://github.com/m-bain/whisperX#limitations-).

Newer joint models deserve a bounded comparison: **MOSS-Transcribe-Diarize 0.9B** advertises multilingual speaker-attributed transcription of up to 90 minutes, and **VibeVoice-ASR 9B** advertises up to 60 minutes with code-switching. Those are model-author capabilities, not verified results on this machine. A single long inference call is a poor default for this project's recovery requirement; chopping it up reintroduces cross-chunk identity reconciliation. MOSS is the more practical optional joint-model spike; VibeVoice also has a larger memory burden. [MOSS model card](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize), [VibeVoice model card](https://huggingface.co/microsoft/VibeVoice-ASR).

**noScribe** already combines a GUI with Whisper and pyannote and is a useful usability/baseline reference. A custom engine is justified here by the explicit recovery, model-comparison and multilingual requirements; do not infer that the existing app meets them without testing. [noScribe repository](https://github.com/kaixxx/noScribe).

### Swiss German accuracy needs its own definition

Dialect speech rendered in Standard German is partly a translation task. Valid differences in wording and word order can inflate word error rate, and word timestamps may not correspond literally to the spoken dialect. Research supports evaluating both automatic scores and human judgments of meaning. [Swiss German Whisper evaluation](https://arxiv.org/abs/2404.19310).

Consequently:

- Assess omissions, negations, numbers, names and commitments separately from stylistic differences.
- Preserve source timing internally, but use turn-level timing when Standard German reformulation makes word alignment unreliable.
- Do not assume a Standard German forced aligner validates Swiss German speech paired with reformulated text.
- Do not label normalised Standard German as a literal dialect transcript.
- Treat published model-card scores as hypotheses to test. Different datasets, splits and scoring conventions prevent direct ranking from those numbers alone.

## 4. Proposed application architecture

```text
Local recording
    |
    v
Inspect, fingerprint and decode -> durable PCM blocks and time map
    |
    +--> segmentation + speaker embeddings -> durable feature batches
    |                                           |
    |                                           v
    |                                  meeting-wide clustering
    |                                           |
    |                                           v
    |                                  speaker turns + overlaps
    |
    +--> speech windows + language hypotheses -> transcription candidates
                                                |
                                                v
                             alignment, boundary reconciliation, attribution
                                                |
                                                v
                              local review, corrections and versioned exports
```

### Engine and desktop interface

Use a Python package with isolated inference workers, SQLite for job state, and ordinary immutable files for large arrays and results. Start with CLI commands for provision, inspect, transcribe, resume, status and export. Suggested implementation modules:

```text
src/meeting_protocol/
  cli.py                 # commands and progress
  jobs.py                # scheduler, pause/resume, dependency invalidation
  storage.py             # SQLite transactions and artifact validation
  audio.py               # decoding, channels, samples and source-time mapping
  models.py              # local registry, pinned revisions and provisioning
  diarization/           # feature extraction, global clustering, identities
  transcription/         # backend adapters, windowing and language routing
  alignment.py           # timing and speaker assignment
  review.py              # flags and durable human corrections
  export.py              # TXT, JSON, optional subtitles
  desktop/               # later PySide6 review interface
```

A PySide6 desktop interface avoids hosted services and can reuse the engine directly. Keep it out of inference processes so closing or crashing the interface does not corrupt a job. Provide file selection, speaker-count hints, progress by stage, pause/resume, local playback, transcript editing, speaker merge/split/rename and exports. Review controls should focus on uncertain passages rather than model internals.

### Ingest and audio preparation

1. Inspect duration, channels, sample rate and codec; hash the original file. Support WAV, FLAC, MP3 and M4A through a pinned local decoder.
2. Keep the original unchanged. Preserve separate microphone tracks if present; do not blindly average independent speaker channels or phase-cancelling stereo.
3. Create sample-indexed 16 kHz analysis audio in bounded blocks with exact source offsets. Decode sequentially so compressed seek inaccuracies do not create missing or duplicated samples. Persist block completion.
4. Use conservative speech detection to propose processing regions. Keep padding and retain the source timeline, including silence; quiet speech and short acknowledgments must not be discarded casually.
5. Do not enable aggressive denoising by default. Compare it only on recordings where it demonstrably improves recognition without harming speaker features.

### Diarisation and consistent speaker labels

Extract local segmentation scores and speaker embeddings in bounded batches, then cluster across the **whole meeting**. A person returning after twenty minutes should retain the same identity. Language changes must not create a new speaker automatically.

Community-1's implementation has separate segmentation, embedding and clustering stages. Its cache paths shown in the source are training-oriented; they are not a ready-made persistent resume API. Implement a small, version-pinned adapter that persists inference artifacts and resumes batch extraction, then validate it against the unmodified full pipeline on short fixtures. [Pipeline source](https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/pipelines/speaker_diarization.py).

Preserve the model's sliding-window origin, overlap and window metadata across extraction blocks. Persist segmentation scores, speaker masks, embeddings and validity masks, not just final local labels. Reject the tempting implementation that independently diarises every few minutes and concatenates its Speaker A/B labels.

Retain both simultaneous-speaker intervals and an exclusive assignment for convenient text attribution. Exclusive output is a presentation aid; it does not recover both voices from overlapping speech. Prefer original individual tracks when available. Flag ambiguous overlaps for review; source separation is a later optional experiment.

Give internal speakers stable UUIDs and map final clusters to display letters in first-appearance order. Mark early labels provisional until global reconciliation finishes. Keep manual identity edits separate from model outputs, with explicit remapping when reclustering changes the result.

### Multilingual transcription and specialist routing

Start with roughly 15–30-second speech windows, adjusted to pauses and likely turn boundaries, with 1–3 seconds of contextual overlap. These are initial tuning values, not fixed promises.

Use transcription mode, not translation-to-English mode. Detect language per region rather than once for the entire file. Short utterances have weak language evidence: preserve multiple hypotheses, consider neighbouring audio and allow a manual override. A German label does not reliably distinguish Standard German from Swiss German.

Baseline pass: the general multilingual model on every region. Challenger pass during evaluation: Swiss specialist on candidate Swiss/German regions and Qwen on the same benchmark excerpts. In production, enable an extra pass only where measured improvements justify it. Preserve alternative text when models disagree; do not compare raw confidence numbers from different models as though they were calibrated probabilities.

For switches within a window, reprocess smaller regions when timing and acoustic evidence support a split. Test both natural and abrupt switches. Avoid carrying a German prompt into a French passage. Keep prompt context bounded and record it as a dependency for recovery.

Use conservative repetition and no-speech checks; flag suspicious output rather than silently deleting potentially real repetition. A user-provided glossary can help names and terminology but must not become invented meeting content. No generative “cleanup” model should silently rewrite the canonical transcript.

### Text, timestamps and speakers

Attach words to speaker intervals using time overlap when word timing is credible. Split text at speaker changes; avoid assigning an entire multi-speaker ASR window to its majority speaker. Where timing or identity is ambiguous, retain uncertainty in the structured output and review queue.

For dialect-to-Standard-German output, prefer speaker-pure turns and conservative turn-level attribution over fabricated word precision. For actual de/fr/it verbatim text, test optional language-specific forced alignment on difficult boundaries.

Reconcile overlapping ASR windows using timestamps and token alignment in the shared boundary region. Do not remove repeated words globally: “yes, yes” can be real speech. Preserve competing boundary hypotheses when they cannot be resolved reliably.

## 5. Checkpoint and recovery design

### Recovery contract

The target is **no more than three minutes of lost completed computation**, excluding model reload/startup time, after interruption on the tested configuration. Report both lost computation and time to resume. Two minutes of audio can take much longer than two minutes to process, so an audio-duration chunk alone does not satisfy this contract.

Start with single-worker inference and checkpoints after every ASR window and small diarisation batch. Benchmark wall-clock duration and reduce batch/window sizes to target commits every 30–120 seconds. Model execution units that still exceed three minutes require a smaller unit, backend changes or an explicitly disclosed limitation. Do not claim the recovery target before crash tests pass.

### Persistent job data

Store:

- `job.sqlite`: input fingerprint, configuration, stage dependencies, task states, errors and correction history.
- `audio/`: decoded blocks and source sample offsets.
- `features/`: segmentation and embedding arrays with window metadata.
- `asr/`: immutable candidates, timing, language hypotheses and decoding context per region.
- `diarization/`: global assignments and revisioned speaker mappings.
- `exports/`: versioned user outputs; partial results clearly identified by filename and job status.

Every task key includes input/block hash, sample range, model revision, conversion/precision, decoding settings and algorithm/schema version. Include preceding context where it affects decoding. Reuse only artifacts with matching dependencies. Changing speaker names should require no inference; changing the ASR model must not invalidate unrelated audio preparation or speaker features.

### Commit protocol

Write an artifact to a temporary file in the same filesystem, validate it, flush it and atomically rename it. Then commit its checksum and completed state in SQLite. Use durable SQLite settings; account for filesystem durability in the implementation. A crash between rename and database commit leaves an orphan that can be validated and adopted or discarded safely.

On restart, acquire the job lock, validate completed artifacts, reset stale running tasks and schedule only missing or invalid work. Make retries idempotent. Store user corrections transactionally and apply them as a separate layer, so retrying inference cannot erase them.

### Global steps are part of the requirement

Saving ASR alone is insufficient. Persist segmentation/embedding work before global clustering. Measure clustering and final reconciliation on 60–120-minute recordings. If either exceeds the recovery budget, add resumable iterations/block operations with full state, or choose a validated alternative clustering method. This is a feasibility gate: stock Community-1 does not provide a demonstrated arbitrary mid-clustering disk resume in the sources reviewed.

A short whole-file pyannote invocation is acceptable for the initial accuracy baseline. It is **not** sufficient for the shipping long-file recovery contract. If the adapter cannot preserve baseline quality and recovery, bring that concrete tradeoff back to the user before locking the architecture.

Progress should show stage, completed units, saved-through audio range, elapsed time, estimated remaining time and warnings. Pause at a safe unit boundary. Graceful cancellation preserves completed work; forced termination loses only the in-flight unit if durability checks pass.

## 6. Offline execution and provisioning

Provide separate modes:

1. **Provision models:** download pinned files and dependencies; record repository revisions, hashes, licenses and notices. This phase has no access to meeting input directories. Allow importing an existing model bundle for an air-gapped machine.
2. **Process meetings:** load only verified local paths, with no cloud fallbacks, hosted inference endpoints, remote logging or automatic downloads. A missing model causes an actionable local error before processing begins.

Disable pyannote telemetry with `PYANNOTE_METRICS_ENABLED=0` before import. Set `HF_HUB_OFFLINE=1` and `HF_HUB_DISABLE_TELEMETRY=1` for the processing environment. These settings help, but they are not an operating-system network boundary. [pyannote telemetry implementation](https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/telemetry/metrics.py), [Hugging Face environment documentation](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).

For the Mac package, validate a worker sandbox that denies outbound networking while allowing required local files, libraries and Metal access. The platform mechanism and GPU compatibility belong in the first technical spike. Verify processing with networking disabled and monitor attempted connections; test missing-weight and error paths too. Do not claim network isolation from environment variables alone.

Use a dedicated local data directory outside cloud-synchronised folders, with private file permissions. Audio-derived embeddings and transcripts receive the same handling as audio. Logs should contain task IDs and diagnostic codes rather than transcript excerpts. Provide deletion of job artifacts and explain which original files are untouched. Application privacy cannot override unrelated system backup/sync software, so the chosen storage directory matters.

The Community-1 model gate requires the user to accept its conditions using their Hugging Face account. A scoped read/download token may be needed for provisioning; it is not an inference API token and is unnecessary at runtime once weights are cached. Use local credential entry or Keychain, never pasted credentials in chat, source control or logs. No paid inference credits are needed for the proposed local pipeline. [Access and offline setup](https://huggingface.co/pyannote/speaker-diarization-community-1).

## 7. Outputs

### Required plain transcript

`transcript.txt`, UTF-8, contains only speaker-prefixed quoted turns, without a heading, timestamps, confidence values, language annotations or footnotes:

```text
Speaker A: "Wir beginnen mit dem ersten Punkt."
Speaker B: "Oui, je peux présenter les résultats."
Speaker A: "Danke. Danach besprechen wir die nächsten Schritte."
```

Merge adjacent same-speaker fragments when no other speaker intervenes. Preserve real interruptions and turn order. Normalise internal line breaks so each turn occupies one line. Define escaping for embedded quotation marks and use the same deterministic formatter every time. Labels continue A…Z, AA… if needed.

Do not invent missing words or speaker identities to make this output look complete. Keep uncertainty and completeness status in the companion review output. Unresolved attribution can use `Speaker Unknown` in a draft; a final export restricted to lettered speakers requires review or an explicit assignment. Never silently omit unrecognised speech. If a passage is unintelligible, the user must choose a reviewed textual placeholder or leave the export marked incomplete outside the transcript body.

### Companion outputs

| File | Purpose |
| --- | --- |
| `transcript.json` | Canonical machine-readable turns, source intervals, optional word timings, internal speaker IDs, language hypotheses, alternatives, model provenance and review status. |
| `review.html` | Self-contained local report with timestamps, uncertainty markers and links to local playback where supported; no external fonts/scripts. |
| `transcript.srt` / `.vtt` | Optional subtitles when timing quality is sufficient. |
| `minutes.md` | Optional later summary, clearly separate from the transcript and traceable to source turns. Requires a separately evaluated local summarisation model. |

Store raw model output, selected text and human-corrected text separately. All exports derive from a selected immutable revision plus correction history.

## 8. Evaluation and acceptance

### Representative local material

The tiny sample is useful for a smoke test, but cannot establish meeting-wide identity stability, language coverage or failure recovery. Request a **local filesystem path**, rather than uploading sensitive audio to a service.

Prepare 15–30 minutes of local annotated excerpts, covering de, multiple Swiss German dialects if relevant, fr, it, language switches, quiet speakers, short acknowledgments, names/numbers, room noise and overlaps. Include the same person speaking more than one language. Use a separate 60–120-minute recording for endurance and recovery, with returning speakers and silence near chunk boundaries.

The user supplies or reviews reference text and speaker turns locally. Keep a held-out portion that is not used to tune routing, thresholds or prompts. If a language or acoustic condition is absent, label it unvalidated rather than extrapolating.

### Measurements

| Area | Measurement |
| --- | --- |
| Recognition | WER/CER per language with documented normalisation; Swiss German also gets human semantic review against the agreed output convention. |
| Important content | Errors in names, numbers, negations, decisions and commitments; distinguish omissions from substitutions. |
| Diarisation | DER with stated overlap/collar settings, speaker count, returning-speaker consistency and speaker-attributed word error. |
| Switching | Language preservation and accidental translation, especially at window boundaries and within turns. |
| Usability | Human correction minutes per audio minute and usefulness of review flags. |
| Resources | Peak memory, disk usage, elapsed time per stage and processing/audio-duration ratio on this Mac. |
| Recovery | Recomputed wall-clock work, time to resume, unchanged completed-artifact hashes and preservation of manual edits. |
| Privacy | Successful offline run, no outbound attempts from processing workers, and failure without downloads when dependencies are missing. |

“Fairly accurate” is not yet a numeric acceptance threshold. After the first benchmark, propose thresholds based on actual error categories and the user's correction tolerance. Do not promise a generic 95% accuracy: speaker errors and changed negations can matter much more than punctuation.

### Required release checks

- Complete a 60–120-minute meeting with bounded memory and no missing/duplicated speech at processing boundaries.
- Force termination during decoding, segmentation, embeddings, ASR, clustering and export; verify recovery and the three-minute computation-loss target.
- Simulate disk-full and corrupt artifacts; recover without treating incomplete data as complete.
- Change model/configuration and verify correct cache invalidation; renaming a speaker must not rerun ASR.
- Confirm language switches and long absences do not systematically change speaker identity.
- Check silence for hallucinations and overlaps for explicitly retained uncertainty.
- Verify plain-text formatting exactly and keep all metadata in companion files.
- Run all processing and review with external networking disabled.

## 9. Implementation sequence and decision points

| Phase | Work and deliverable | Exit condition / user involvement |
| --- | --- | --- |
| 0. Inputs | Confirm target hardware/output convention; locate local sample; inspect format and channels. | User supplies sample path and preferences. No model-quality claim yet. |
| 1. Feasibility spikes | Provision baseline models; run short ASR and diarisation comparisons; test MLX conversion, memory and network isolation. Prototype persisted feature extraction and global clustering recovery. | User handles the model access gate locally. Produce a comparison report and a clear recovery feasibility result. |
| 2. Durable CLI | Implement job database, audio blocks, artifact commits, worker scheduling and resume. Add selected ASR/diarisation adapters. | Interrupted long jobs recover correctly; dependencies and model revisions are pinned. |
| 3. Attribution and exports | Language routing, boundary reconciliation, speaker mapping, review flags, TXT/JSON and optional subtitles. | Representative held-out results and required export format pass. |
| 4. Desktop review | Local playback, corrections, speaker edits, glossary and pause/resume. | User can correct an actual meeting without rerunning valid inference. |
| 5. Packaging | Reproducible Mac installer/model bundle, offline preflight, attribution notices, endurance/crash/privacy tests. | Ready for local use; document measured limits and unresolved accuracy cases. |

The first useful milestone is an end-to-end **CLI result on a short local sample plus a recovery test**, not the full desktop app. The first spike should stay bounded: baseline Whisper, one Swiss specialist, Qwen, and Community-1; expand to additional models only if a specific failure justifies it. MOSS can be a second-round alternative if it offers enough accuracy benefit to warrant a different recovery strategy.

No fine-tuning is planned initially. If existing models fail on recurring dialect/domain errors, assess adaptation only after collecting enough consented local reference material and checking its training suitability.

## 10. What is needed next

1. **Local sample path — available.** `audio.m4a` in the project folder (not committed). The file has now been processed locally by the baseline pipeline; see VALIDATION.md. Human accuracy evaluation is still needed.
2. **Swiss German output preference.** Standard German is the proposed default. Dialect-preserving output or both versions changes model selection and evaluation.
3. **Target machine.** This M4 Pro/24 GB Mac is the proposed first target; another OS or machine changes the runtime and packaging plan.
4. **When provisioning begins:** accept the Community-1 model gate and configure a local download credential if required. No token is needed to review this plan.
5. **Before judging accuracy:** approximate participant count, recording setup and representative excerpts, followed by a short user review of the initial results.

All links above are primary model cards, maintainer repositories or research papers inspected during planning. Capabilities and license labels are observations as of the research date; exact dependency versions, model revisions and runtime compatibility must be pinned during the spike. Architectural choices, recovery targets and acceptance gates are this project's proposed design, not claims that the upstream tools already implement them.
