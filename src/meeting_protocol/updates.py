"""Optional check for a newer release. Never runs inside the network sandbox.

The packaged app starts `_updates` as a separate process just before it enters the
sandbox, and only when the user has agreed. That process asks GitHub for the latest
release and writes the answer to `update.json`; the sandboxed window only reads files.
Nothing about recordings or transcripts is sent: GitHub sees the request, not its data.
"""

import json
import os
import re
import subprocess
import sys
import time

from . import __version__
from .privacy import home
from .storage import atomic_write, canonical

REPOSITORY = "wianra/meeting-protocol"
LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES = f"https://github.com/{REPOSITORY}/releases/"
# Set by the packaged launcher so the window offers update notices; source checkouts use git.
ENABLED = "DIARIZE_UPDATE_NOTICES"


def settings_path():
    return home() / "settings.json"


def result_path():
    return home() / "update.json"


def allowed():
    """True or False once the user has decided; None while they have not been asked."""
    try:
        value = json.loads(settings_path().read_text()).get("check_updates")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, bool) else None


def set_allowed(value):
    try:
        settings = json.loads(settings_path().read_text())
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}
    settings["check_updates"] = bool(value)
    atomic_write(settings_path(), canonical(settings))


def parse(version):
    """'v0.2.0' -> (0, 2, 0); None for anything else, such as a test tag."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def newer(latest, current=__version__):
    a, b = parse(latest or ""), parse(current)
    return bool(a and b and a > b)


def available():
    """The saved notice, if it names a version newer than this app; otherwise None."""
    try:
        data = json.loads(result_path().read_text())
        version, url = data["version"], data["url"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(url, str) or not url.startswith(RELEASES) or not newer(version):
        return None
    return {"version": version, "url": url}


def fetch(timeout=10):
    import ssl
    import urllib.request

    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    request = urllib.request.Request(
        LATEST,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MeetingProtocol/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        release = json.load(response)
    return {"version": release["tag_name"].lstrip("v"), "url": release["html_url"]}


def check():
    """The `_updates` process: ask GitHub once and save the answer. Failures stay silent."""
    if allowed() is not True:
        return
    try:
        latest = fetch()
    except Exception:  # noqa: BLE001 -- offline, rate-limited or changed API: no notice.
        return
    atomic_write(result_path(), canonical({**latest, "checked": time.time()}))


def start_check():
    """Called by the packaged launcher before the sandbox; returns immediately."""
    os.environ[ENABLED] = "1"
    if allowed() is not True:
        return
    from .compat import hidden

    try:
        subprocess.Popen(
            [sys.executable, "-m", "meeting_protocol.cli", "_updates"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden(),
        )
    except OSError:
        pass
