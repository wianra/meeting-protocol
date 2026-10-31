"""CLI and desktop entry point. No transcript text is printed in progress logs."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .privacy import configure, enter_sandbox, home, network_is_denied


def parser():
    p = argparse.ArgumentParser(description="Offline meeting transcription for Apple Silicon")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local tools, models and network isolation")
    sub.add_parser("login", help="Enter a Hugging Face download token locally")
    provision = sub.add_parser("provision", help="Download a model (no audio processing)")
    provision.add_argument("model", choices=["asr", "diarization"])
    provision.add_argument("--tested", action="store_true", help="Use the tested revision")
    sub.add_parser("app", help="Packaged app entry: first-run setup, then the desktop app")
    run = sub.add_parser("transcribe", help="Create or resume a local job")
    run.add_argument("audio", type=Path)
    run.add_argument("--language", choices=["auto", "de", "fr", "it"], default="auto")
    run.add_argument("--min-speakers", type=int, default=2)
    run.add_argument("--max-speakers", type=int, default=10)
    run.add_argument("--channel", type=int, help="Zero-based channel; default is mono downmix")
    run.add_argument("--window-seconds", type=float, default=20.0)
    run.add_argument("--glossary", default="", help="Optional names/terms, used only locally")
    run.add_argument("--asr-only", action="store_true", help="Explicitly omit speaker analysis")
    resume = sub.add_parser("resume", help="Reuse a job's validated checkpoints")
    resume.add_argument("job")
    resume.add_argument(
        "--add-speakers",
        action="store_true",
        help="Add diarisation to an earlier ASR-only job without repeating ASR",
    )
    status = sub.add_parser("status", help="Show a job's saved progress")
    status.add_argument("job")
    sub.add_parser("jobs", help="List local jobs without displaying their transcripts")
    gui = sub.add_parser("gui", help="Open the desktop app")
    gui.add_argument("job", nargs="?")
    classic = sub.add_parser("gui-classic", help="Open the first, classic desktop window")
    classic.add_argument("job", nargs="?")
    simple = sub.add_parser("gui-simple", help="Open the simple edit, review and export window")
    simple.add_argument("job", nargs="?")
    export = sub.add_parser("export", help="Regenerate exports with saved corrections")
    export.add_argument("job")
    export.add_argument("--output", type=Path, help="Save corrected .docx, .txt, .json or .html")
    worker = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("job")
    worker.add_argument("stage")
    return p


def main():
    args = parser().parse_args()
    # `app` only installs models before re-entering as the sandboxed `gui`.
    online = args.command in ("login", "provision", "app")
    configure(offline=not online)
    try:
        if not online:
            enter_sandbox()
        if args.command == "login":
            from .models import login

            login()
        elif args.command == "provision":
            from .models import TESTED, provision

            revision = TESTED.get(args.model) if args.tested else None
            print(json.dumps(provision(args.model, revision)))
        elif args.command == "app":
            from .models import bundled_models, install_bundled, is_installed

            if bundled_models() and not is_installed("diarization"):
                install_bundled("diarization")
            if not is_installed("asr"):
                from .gui.setup import run_setup

                if not run_setup():
                    return 0
            os.execv(sys.executable, [sys.executable, "-m", "meeting_protocol.cli", "gui"])
        elif args.command == "doctor":
            from .jobs import runtime_versions

            print(
                json.dumps(
                    {
                        "version": __version__,
                        "data_directory": str(home()),
                        "network_denied": network_is_denied(),
                        "ffmpeg": shutil.which("ffmpeg"),
                        "ffprobe": shutil.which("ffprobe"),
                        "models": {
                            n: (home() / "models" / n / "manifest.json").exists()
                            for n in ("asr", "diarization")
                        },
                        "runtime": runtime_versions(),
                    },
                    indent=2,
                )
            )
        elif args.command == "transcribe":
            from .jobs import create_job, install_cancel_handler, run_job

            install_cancel_handler()
            root = create_job(
                args.audio,
                language=args.language,
                min_speakers=args.min_speakers,
                max_speakers=args.max_speakers,
                channel=args.channel,
                window_seconds=args.window_seconds,
                glossary=args.glossary,
                asr_only=args.asr_only,
            )
            run_job(root)
        elif args.command == "resume":
            from .jobs import install_cancel_handler, resolve_job, run_job

            install_cancel_handler()
            run_job(resolve_job(args.job), add_speakers=args.add_speakers)
        elif args.command == "_worker":
            from .jobs import resolve_job, worker

            worker(resolve_job(args.job), args.stage)
        elif args.command in ("status", "export"):
            from .jobs import resolve_job
            from .storage import Store, lock

            root = resolve_job(args.job)
            store = Store(root)
            try:
                if args.command == "status":
                    print(json.dumps(store.summary(), indent=2))
                else:
                    from .export import export_to_file, export_transcript

                    with lock(root / ".lock"):
                        raw = json.loads((root / "transcript.raw.json").read_text())
                        if args.output:
                            export_to_file(store, raw, args.output)
                        else:
                            export_transcript(store, raw)
                    print(str(args.output.resolve() if args.output else root / "exports"))
            finally:
                store.close()
        elif args.command == "jobs":
            for file in sorted((home() / "jobs").glob("*/job.json")):
                config = json.loads(file.read_text())
                print(
                    json.dumps(
                        {
                            "id": config["job_id"],
                            "audio": Path(config["input"]).name,
                            "has_export": (file.parent / "exports/transcript.json").exists(),
                        }
                    )
                )
        elif args.command == "gui":
            from .gui.main import launch

            launch(args.job)
        elif args.command == "gui-classic":
            from .gui.classic import launch

            launch(args.job)
        elif args.command == "gui-simple":
            from .gui.simple import launch

            launch(args.job)
        return 0
    except KeyboardInterrupt:
        print("Paused. Completed checkpoints are saved; use resume to continue.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 -- CLI boundary: retain checkpoints and show an error.
        # Errors can include local paths, but never deliberately include model outputs or secrets.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
