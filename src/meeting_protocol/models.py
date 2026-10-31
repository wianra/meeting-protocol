"""Explicit provisioning; inference never resolves remote model identifiers."""

import getpass
import json
from pathlib import Path

from .privacy import home
from .storage import atomic_write, canonical, digest_file, fingerprint, lock

REPOSITORIES = {
    "asr": "mlx-community/whisper-large-v3-mlx",
    "diarization": "pyannote/speaker-diarization-community-1",
}


def login():
    from huggingface_hub import login as hf_login

    token = getpass.getpass("Hugging Face read token (hidden, stored only on this device): ")
    hf_login(token=token, add_to_git_credential=False)


def provision(name: str):
    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.errors import GatedRepoError

    repo = REPOSITORIES[name]
    folder = home() / "models" / name
    folder.mkdir(parents=True, exist_ok=True)
    with lock(folder / ".provision.lock"):
        try:
            revision = HfApi().model_info(repo).sha
            # No arbitrary remote Python code or training state is downloaded.
            patterns = (
                ["config.json", "weights.npz", "weights.safetensors", "README.md", "LICENSE*"]
                if name == "asr"
                else [
                    "*.yaml",
                    "*.yml",
                    "*.bin",
                    "*.safetensors",
                    "*.npz",
                    "*.npy",
                    "*.txt",
                    "*.json",
                    "*.md",
                    "LICENSE*",
                ]
            )
            path = Path(
                snapshot_download(
                    repo, revision=revision, local_dir=folder / revision, allow_patterns=patterns
                )
            )
        except GatedRepoError:
            raise RuntimeError(
                "Accept Community-1 conditions on Hugging Face, then run "
                "./diarize login and ./diarize provision diarization."
            ) from None
        files = {
            str(p.relative_to(path)): digest_file(p)
            for p in sorted(path.rglob("*"))
            if p.is_file() and ".cache" not in p.relative_to(path).parts
        }
        manifest = {"repository": repo, "revision": revision, "files": files, "path": str(path)}
        atomic_write(folder / "manifest.json", canonical(manifest))
    return {"name": name, "revision": revision, "files": len(files)}


def model_info(name: str, *, verify: bool = True) -> dict:
    manifest = home() / "models" / name / "manifest.json"
    if not manifest.exists():
        raise RuntimeError(f"Missing {name} model. Run ./diarize provision {name} first.")
    info = json.loads(manifest.read_text())
    path = Path(info["path"])
    if not path.is_dir():
        raise RuntimeError(f"Model directory missing; provision {name} again.")
    if verify:
        for relative, sha in info["files"].items():
            file = path / relative
            if not file.is_file() or digest_file(file) != sha:
                raise RuntimeError(f"Model integrity check failed; provision {name} again.")
    info["fingerprint"] = fingerprint({k: info[k] for k in ("repository", "revision", "files")})
    return info
