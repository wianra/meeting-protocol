# Meeting Protocol

A local meeting transcription app for Apple Silicon Macs and Windows PCs. German and Swiss German speech are rendered as Standard German; French and Italian remain in their spoken language. The default speaker range is 2–10.

This is a working first version using **Whisper large-v3 through MLX** and **pyannote Community-1 on CPU**. It includes a desktop review app, a resumable CLI, persistent neural-batch checkpoints, and plain speaker-attributed transcripts. It has been tested on the supplied 28-second sample. Accuracy across dialects, Italian, heavy overlap and hour-long meetings still needs representative recordings; see `docs/VALIDATION.md`.

## Install the Mac app

Requires a Mac with Apple Silicon (M1 or later) and macOS 14 or later, plus about 6 GB of free space.

1. Download **MeetingProtocol-…-arm64.dmg** from the [latest release](https://github.com/wianra/meeting-protocol/releases/latest).
2. Open it and drag **Meeting Protocol** onto **Applications**.
3. Open Meeting Protocol from Applications. The first time, macOS says *“Apple could not verify ‘Meeting Protocol’ is free of malware…”*, because the app is not yet signed by a registered Apple developer. Click **Done** (not Move to Trash), open **System Settings → Privacy & Security**, scroll down to **Security** and click **Open Anyway** next to Meeting Protocol, then confirm. This is needed only once. If the button is missing, open the app once more and check again.
4. Click **Download** to fetch the speech model (3.1 GB, one time). Everything after that runs offline.

No Python, Homebrew, FFmpeg or Hugging Face account is needed. Meetings and models are stored in `~/Library/Application Support/Meeting Protocol`. To uninstall, delete the app and that folder.

## Install on Windows

Requires Windows 10 or 11 (64-bit) and about 6 GB of free space.

1. Download **MeetingProtocol-…-windows-x64.zip** from the [latest release](https://github.com/wianra/meeting-protocol/releases/latest).
2. Right-click it → **Extract All**, open the extracted **MeetingProtocol** folder and double-click **Meeting Protocol.exe**.
3. If Windows shows "Windows protected your PC", click **More info → Run anyway** (the app is not signed yet).
4. Click **Download** to fetch the speech model (3.1 GB, one time).

Meetings and models are stored in `%LOCALAPPDATA%\Meeting Protocol`. To uninstall, delete the extracted folder and that folder.

Differences from the Mac app: transcription runs on the CPU with faster-whisper, so expect roughly one to two times the meeting length; and networking is blocked by the app itself, not by the operating system (see Privacy).

## Open the app from source

From this folder:

```sh
./diarize gui
```

Or double-click **Open Meeting Protocol.command** in Finder. The launcher uses this project's installed environment. The sample job appears in the left sidebar.

The window lists meetings on the left and puts the player and the transcript in the middle. Click a time to play from there, click a turn's text to correct it, and use **To check** to see only the turns that still need a listen. With **Auto-play** on, clicking a turn plays it; with it off, use **Play this turn**. Click **+ New** to transcribe another recording. The earlier windows are still available with `./diarize gui-classic` and `./diarize gui-simple` (or the launchers in `launchers/`).

Choose a local recording, set the speaker range if known, and click **Transcribe recording**. Select a transcript row to seek to that passage, then use **Play / pause**. Edit the text or speaker label and save. Corrections regenerate the exports without running the models again. Changes are also saved when switching turns. Closing a running app pauses its processing and preserves checkpoints.

Speaker A/B labels are anonymous, consistent within the inferred meeting-wide clustering. They are not real-person identification. Uncertain words, overlaps and speaker transitions are flagged for listening. If a speaker cannot be assigned, a draft uses **Speaker Unknown**; assign it during review. The app never invents an identity to make the output look complete.

To use real names, click **Speakers…** and type a name next to each label, for example `Raphael Winkler` for Speaker A. The name replaces the label in every turn and in all exports, so the output reads `Raphael Winkler: I am great.` Giving two speakers the same name merges them. Unknown turns are assigned one by one.

### Delete a meeting

Hover a meeting in the sidebar, or open it, and click the bin icon (also next to **Open folder**). After you confirm, the meeting's folder — transcript, corrections, checkpoints and saved exports — moves to the macOS Trash, and **Undo** appears for a few seconds. Afterwards you can still use **Put Back** in the Trash. The original recording and files you exported elsewhere are never touched. Deleting is unavailable while processing runs, and a job that a terminal `./diarize` command is still using refuses to move.

### Export your corrected transcript

Click **Export…** below the transcript and choose **Word document (.docx)**, plain text, review HTML or structured JSON. Select the destination in the Save dialog. Any pending editor correction is saved before export. The Word file contains bold speaker labels followed by the text, with no timestamps, confidence labels or additional commentary.

**Open export folder** opens the meeting's saved outputs in Finder. Every saved correction updates `transcript.docx`, `transcript.txt`, `transcript.json` and `review.html`; previous revisions remain available. The exports always use the saved correction history, without rerunning transcription. To see these buttons after updating an already running app, save your edit and restart the app.

## Command line

```sh
# Tools, installed models and actual network-denial check
./diarize doctor

# Multilingual meeting; defaults to 2–10 speakers
./diarize transcribe /absolute/path/to/meeting.m4a

# Known number of speakers; optional single-language hint
./diarize transcribe /absolute/path/to/meeting.m4a --min-speakers 4 --max-speakers 4
./diarize transcribe /absolute/path/to/meeting.m4a --language de

# Available job IDs and progress, without printing meeting text
./diarize jobs
./diarize status JOB_ID

# Ctrl-C pauses. Resume reuses validated completed work.
./diarize resume JOB_ID

# Review a particular meeting
./diarize gui JOB_ID

# Rebuild exports from saved text and corrections
./diarize export JOB_ID

# List the speakers, then replace a label with a name in every turn and export
./diarize rename JOB_ID
./diarize rename JOB_ID "Speaker A" "Raphael Winkler"

# Save a corrected Word document to a chosen local destination
./diarize export JOB_ID --output /absolute/path/to/meeting-transcript.docx
```

Use `--channel 0` to select a particular input channel. Otherwise the first audio stream is downmixed to mono; independent microphone tracks are not yet handled as separate speaker channels. `--window-seconds 10` makes smaller transcription units if needed. The accepted range is 5–26 seconds. A glossary can be supplied using `--glossary 'Names, products, specialised terms'`; it is used locally.

An explicit `--asr-only` mode is available for transcription before the speaker model is installed. Such jobs have unknown speaker labels. After provisioning, add speaker analysis without repeating transcription:

```sh
./diarize resume JOB_ID --add-speakers
```

## Files and exports

By default, all model weights, credentials, caches and jobs are in **`.local/` inside this project**. Audio inputs are left unchanged. The `.local/`, `work/`, and common audio extensions are ignored by Git.

Each job contains:

```text
.local/jobs/JOB_ID/
  job.json                 Input fingerprint, settings, pinned model/runtime versions
  job.sqlite               Durable artifact journal and correction history
  artifacts/               Verified audio and neural-batch checkpoints
  audio.pcm                Rebuildable local PCM view
  asr.json                 Original model candidates and timing
  diarization.json         Meeting-wide speaker intervals, including overlap
  transcript.raw.json      Assembled transcript before human corrections
  exports/
    transcript.docx        Editable Word transcript with bold speaker labels
    transcript.txt         Speaker-prefixed text only
    transcript.json        Structured transcript with timing, flags and provenance
    review.html            Self-contained review report; no remote resources
    current.json           Pointer to the current immutable export revision
    revisions/             Previous export versions
```

The required plain export has exactly this structure, with no heading or timestamps:

```text
Speaker A: Wir beginnen mit dem ersten Punkt.
Speaker B: Oui, je peux présenter les résultats.
Speaker A: Danke.
```

Adjacent fragments from the same speaker are merged. Turn text is written as spoken, without surrounding quotes; internal line breaks become spaces. Draft/review information lives in the JSON and HTML companions. The latest immutable version is identified by `exports/current.json`; the top-level files are convenience copies.

## Privacy

Audio processing, review, status and export run inside a **macOS sandbox that denies networking**. The program verifies that a loopback connection is denied; it does not merely set an offline flag. Inference loads verified local model paths. Missing or corrupted model files fail locally rather than downloading during processing. Telemetry is disabled before ML imports.

Only `login` and `provision` use network access. They authenticate and download model files; those command paths do not read recordings. Credentials are stored locally under `.local/huggingface/` and are not written into jobs. Processing logs report stages and counts rather than transcript text.

The application cannot control system backups or another program's folder synchronisation. Keep the project/data directory outside iCloud, Dropbox or similar synced locations. To choose a different local data directory, set `DIARIZE_HOME` before every invocation, including provisioning. Changing it does not automatically move existing models or jobs.

On Windows there is no equivalent sandbox. There the app blocks networking itself: every Python socket connection and name lookup is refused in each processing process. That covers the model libraries' Python code but is weaker than the macOS sandbox, which the operating system enforces; `doctor` reports `network_isolation: app-level` on Windows.

The current Mac launcher relies on `/usr/bin/sandbox-exec`. It fails closed if the sandbox cannot be started. When launching from an already sandboxed development tool, an outer permission escalation may be needed to start the application's own sandbox; the audio worker itself still has networking denied.

## Install from source on another Apple Silicon Mac

Requirements: macOS, `uv`, FFmpeg/ffprobe, and enough free space for the environment, approximately 3 GB of ASR weights plus the speaker model, and local audio/checkpoints. Python 3.12 is selected by the setup script. The tested machine has 24 GB unified memory. CPU/GPU models run in separate worker processes to release memory between stages.

```sh
./setup.sh
./diarize provision asr
```

Accept the [Community-1 model conditions](https://huggingface.co/pyannote/speaker-diarization-community-1) using your Hugging Face account. Then, in your own terminal:

```sh
./diarize login
./diarize provision diarization
./diarize doctor
```

Use a download/read token with access to the gated repository. The login prompt hides the token. No paid inference API or cloud transcription service is required. This project already has both models provisioned on the development Mac.

`uv.lock` pins the tested dependency set. The pyannote caching adapter is deliberately restricted to version 4.0.7; update its compatibility tests before changing that version. Model provisioning records exact repository revisions and file hashes. Existing jobs retain their original model references.

## Build the Mac app

```sh
./setup.sh
./diarize provision diarization        # the speaker model is bundled into the app
packaging/macos/build_ffmpeg.sh        # static LGPL ffmpeg/ffprobe, built from verified source
packaging/macos/build_app.sh           # dist/Meeting Protocol.app and dist/MeetingProtocol-VERSION-arm64.dmg
```

The app contains a standalone Python with the locked dependencies, the minimal FFmpeg build, the speaker model (CC BY 4.0, attribution in `Contents/Resources/licenses`) and only the Qt modules the app uses. A small native launcher (`packaging/macos/launcher.c`) runs Python in-process, so macOS shows the app's name and icon. On first launch, before entering the network sandbox, the app copies the speaker model into its data folder and downloads the tested Whisper revision; it opens no recordings at that point.

The default build is ad-hoc signed. With an Apple Developer ID, set `SIGN_IDENTITY="Developer ID Application: …"` to sign with the hardened runtime, then notarise the DMG with `xcrun notarytool submit --wait` and `xcrun stapler staple`.

## Recovery and current limits

ASR saves each 15–20-second region (configurable), including contextual overlap. Speaker segmentation and embeddings save each small inference batch while preserving the upstream sliding-window grid. Final speaker clustering uses the entire recording, so independently processed chunks do not each reset Speaker A/B.

Atomic artifact writes precede SQLite completion records. Restart checks hashes, reuses valid work and recomputes missing/corrupt artifacts. Human corrections are kept separately. Single-writer locks prevent concurrent edits, and workers stop if their supervisor dies.

**The three-minute maximum-loss target is not yet certified for hour-long meetings.** Sample ASR batches took up to 8.3 seconds and speaker neural batches up to 1 second in the initial run. Global clustering/reconstruction is currently committed as a whole; a crash during that step recomputes it from saved neural features. Test it on an actual long recording before relying on a strict wall-clock recovery bound.

This version uses a baseline multilingual model, with language detection per window. Very short passages and language changes inside a window can be misrecognised or translated. Swiss German specialist comparisons, an independent Qwen pass, explicit language-region overrides, separate microphone processing, source separation, subtitles, summaries and a signed and notarised app remain later work. No automatic cleanup model rewrites the transcript.

## Project layout

```text
diarize, setup.sh                 Command-line launcher and installer
Open Meeting Protocol.command     Double-click launcher for the app
launchers/                        Launchers for the classic and simple windows
packaging/macos/                  Mac app build: ffmpeg, Qt trimming, launcher, icon, Info.plist
src/meeting_protocol/
  cli.py                          Commands and the network sandbox entry point
  audio, transcription, diarization, transcript, jobs, storage, export, word, models, privacy
  gui/
    main.py                       Default window (meetings, player, transcript)
    classic.py, simple.py         Earlier window layouts
    common.py                     App icon and move-to-Trash helpers
    setup.py                      First-run model download for the packaged app
    assets/app-icon.svg           App and Dock icon
tests/                            Unit and offscreen GUI tests
docs/                             Research plan and validation evidence
```

## Development checks

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

The suite covers durable writes, corruption recovery, batch-cache invalidation, input window coverage, attribution, overlap flags, correction retention and export formatting. Additional local integration tests compared the cache adapter to the original pyannote pipeline, killed and resumed real inference workers, and exercised the desktop UI with synthetic text. See `docs/VALIDATION.md` for evidence and remaining gaps.

Model/source acknowledgments: [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper), [Whisper large-v3 MLX weights](https://huggingface.co/mlx-community/whisper-large-v3-mlx), [pyannote.audio](https://github.com/pyannote/pyannote-audio), [Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1). Model cards/license information are retained with provisioned files. Community-1 is distributed under CC BY 4.0; redistribution should include its attribution. Dependency and model notices should be reviewed when preparing a distributable installer.
