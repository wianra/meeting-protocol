"""Builds dist/MeetingProtocol and dist/MeetingProtocol-VERSION-windows-x64.zip.

Runs on Windows in a Visual Studio developer environment (cl and rc on PATH), with uv and
an authenticated gh. The folder holds a standalone Python with the locked Windows
dependencies, Meeting Protocol.exe, ffmpeg/ffprobe, the speaker model and the Visual C++
runtime; the speech model downloads on first launch. Packages the last commit (HEAD).
"""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BUILD = ROOT / "build" / "windows"
APP = ROOT / "dist" / "MeetingProtocol"
REPO = "wianra/meeting-protocol"
# Mirrored in the never-published "build-inputs" draft release; BtbN prunes old builds.
INPUTS = {
    "ffmpeg": (
        "ffmpeg-n9.0.2-39-g7adfbe40dc-win64-lgpl-9.0.zip",
        "9d37c564e0d01c18cde184a079fa6ef04d7d2783ada41da81d04165cc8f1a650",
    ),
    "diarization": (
        "diarization-community-1-3533c8cf.tar.gz",
        "ec18920ae979eb32a3cf9a339691ae9370308789412ec31b670588018187a493",
    ),
}
QT_MODULES = ["QtCore", "QtGui", "QtWidgets", "QtMultimedia", "QtNetwork", "QtSvg"]
QT_PLUGINS = {
    "platforms": ["qwindows.dll", "qoffscreen.dll", "qminimal.dll"],
    "styles": ["qmodernwindowsstyle.dll"],
    "imageformats": ["qsvg.dll", "qico.dll", "qjpeg.dll"],
    "iconengines": ["qsvgicon.dll"],
    "multimedia": ["ffmpegmediaplugin.dll", "windowsmediaplugin.dll"],
}
MAX_PATH_IN_ZIP = 150  # Explorer's unzip fails beyond MAX_PATH once nested in Downloads


def run(*cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def output(*cmd):
    return run(*cmd, capture_output=True, encoding="utf-8").stdout.strip()


def fetch(name):
    file, sha = INPUTS[name]
    target = BUILD / file
    if not target.exists():
        releases = json.loads(output("gh", "api", f"repos/{REPO}/releases?per_page=100"))
        asset = next(
            a
            for r in releases
            if r["name"].startswith("build-inputs")
            for a in r["assets"]
            if a["name"] == file
        )
        with target.open("wb") as out:
            run(
                "gh",
                "api",
                "-H",
                "Accept: application/octet-stream",
                f"repos/{REPO}/releases/assets/{asset['id']}",
                stdout=out,
            )
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != sha:
        sys.exit(f"{file}: checksum {digest} does not match the pinned {sha}")
    return target


def pe_imports(path: Path) -> list[str]:
    """Names of the DLLs a Windows binary imports (PE import table)."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    import_rva = struct.unpack_from("<I", data, directories + 8)[0]
    table = optional + optional_size
    spans = [struct.unpack_from("<8xIIII", data, table + 40 * i) for i in range(sections)]

    def offset(rva):
        for size, address, raw_size, raw in spans:
            if address <= rva < address + max(size, raw_size):
                return rva - address + raw
        raise ValueError(rva)

    names, cursor = [], offset(import_rva) if import_rva else None
    while cursor is not None:
        name_rva = struct.unpack_from("<I", data, cursor + 12)[0]
        if not name_rva:
            break
        start = offset(name_rva)
        names.append(data[start : data.index(b"\0", start)].decode())
        cursor += 20
    return names


def prune_qt(site: Path):
    pyside = site / "PySide6"
    roots = [pyside / f"{m}.pyd" for m in QT_MODULES]
    roots += [pyside / "plugins" / k / n for k, names in QT_PLUGINS.items() for n in names]
    needed, queue = set(), [r for r in roots if r.exists()]
    while queue:
        for name in pe_imports(queue.pop()):
            if name.lower().startswith("qt6") and name.lower() not in needed:
                needed.add(name.lower())
                if (pyside / name).exists():
                    queue.append(pyside / name)
    for dll in pyside.glob("Qt6*.dll"):
        if dll.name.lower() not in needed:
            dll.unlink()
    for module in pyside.glob("Qt*.pyd"):
        if module.stem not in QT_MODULES:
            module.unlink()
            module.with_suffix(".pyi").unlink(missing_ok=True)
    for kind in (pyside / "plugins").iterdir():
        keep = QT_PLUGINS.get(kind.name)
        if keep is None:
            shutil.rmtree(kind)
            continue
        for plugin in kind.iterdir():
            if plugin.name not in keep:
                plugin.unlink()
    for name in [
        "qml",
        "translations",
        "resources",
        "examples",
        "include",
        "typesystems",
        "glue",
        "doc",
        "scripts",
        "metatypes",
        "QtAsyncio",
    ]:
        shutil.rmtree(pyside / name, ignore_errors=True)
    for tool in pyside.glob("*.exe"):
        tool.unlink()
    print("Kept Qt DLLs:", ", ".join(sorted(needed)))


def main():
    os.chdir(ROOT)
    version = output("git", "show", "HEAD:src/meeting_protocol/__init__.py").split('"')[1]
    shutil.rmtree(APP, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    print("==> Standalone Python")
    run("uv", "python", "install", "3.12")
    python_home = Path(output("uv", "python", "find", "--managed-python", "3.12")).parent
    shutil.copytree(python_home, APP)
    for name in [
        "Lib/test",
        "Lib/idlelib",
        "Lib/tkinter",
        "Lib/turtledemo",
        "Lib/ensurepip",
        "tcl",
        "Scripts",
        "Lib/EXTERNALLY-MANAGED",
        "pythonw.exe",
    ]:
        path = APP / name
        shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
    py = APP / "python.exe"

    print("==> Locked dependencies and the app (from HEAD)")
    requirements = BUILD / "requirements.txt"
    run("uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--quiet", "-o", requirements)
    run("uv", "pip", "install", "--python", py, "--require-hashes", "--no-deps", "-r", requirements)
    source = BUILD / "source"
    shutil.rmtree(source, ignore_errors=True)
    source.mkdir()
    archive = BUILD / "source.tar"
    run("git", "archive", "-o", archive, "HEAD", "pyproject.toml", "README.md", "LICENSE", "src")
    with tarfile.open(archive) as tar:
        tar.extractall(source, filter="data")
    wheels = BUILD / "wheel"
    shutil.rmtree(wheels, ignore_errors=True)
    run("uv", "build", "--wheel", "--out-dir", wheels, source)
    run("uv", "pip", "install", "--python", py, "--no-deps", *wheels.glob("*.whl"))
    site = APP / "Lib" / "site-packages"

    print("==> Trim")
    prune_qt(site)
    for name in ["torch/include", "torch/share", "torch/test"]:
        shutil.rmtree(site / name, ignore_errors=True)
    for path in [*site.rglob("*.lib"), *site.rglob("*.pyi"), *APP.rglob("*.pdb")]:
        path.unlink()
    for cache in list(APP.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)

    print("==> ffmpeg, speaker model, licences")
    (APP / "bin").mkdir()
    licenses = APP / "licenses"
    licenses.mkdir()
    with zipfile.ZipFile(fetch("ffmpeg")) as z:
        for member in z.namelist():
            name = Path(member).name
            if member.endswith(("/bin/ffmpeg.exe", "/bin/ffprobe.exe")):
                (APP / "bin" / name).write_bytes(z.read(member))
            elif member.endswith("/LICENSE.txt"):
                (licenses / "FFmpeg-LICENSE.txt").write_bytes(z.read(member))
    (APP / "models").mkdir()
    with tarfile.open(fetch("diarization")) as tar:
        tar.extractall(APP / "models", filter="data")
    shutil.copy(ROOT / "LICENSE", licenses / "Meeting-Protocol-MIT.txt")
    shutil.copy(HERE / "NOTICES.txt", licenses / "NOTICES.txt")
    # App-local Visual C++ runtime: many PCs lack it, and the build machine hides that.
    crt = next(Path(os.environ["VCToolsRedistDir"]).glob("x64/Microsoft.VC14*.CRT"))
    for dll in crt.glob("*.dll"):
        shutil.copy(dll, APP)

    print("==> Launcher")
    icon = BUILD / "app.ico"
    env = {**os.environ, "PYTHONHOME": str(APP), "QT_QPA_PLATFORM": "offscreen"}
    run(
        py,
        HERE / "make_ico.py",
        ROOT / "src/meeting_protocol/gui/assets/app-icon.svg",
        icon,
        env=env,
    )
    numbers = ",".join((version.split(".") + ["0", "0", "0"])[:4])
    (BUILD / "version.h").write_text(
        f'#define VERSION_COMMAS {numbers}\n#define VERSION_TEXT "{version}"\n'
    )
    run("rc", "/nologo", "/i", BUILD, "/fo", BUILD / "app.res", HERE / "app.rc")
    exe = APP / "Meeting Protocol.exe"
    run(
        "cl",
        "/nologo",
        "/O2",
        "/W3",
        "/DUNICODE",
        "/D_UNICODE",
        "/I",
        APP / "include",
        HERE / "launcher.c",
        f"/Fe{exe}",
        f"/Fo{BUILD}\\",
        "/link",
        "/SUBSYSTEM:WINDOWS",
        f"/LIBPATH:{APP / 'libs'}",
        BUILD / "app.res",
    )
    shutil.rmtree(APP / "include")
    shutil.rmtree(APP / "libs")

    print("==> Precompile")
    # Some packages ship files that are not valid Python 3.12; compile everything else.
    run(
        exe,
        "-m",
        "compileall",
        "-q",
        "-j0",
        "--invalidation-mode",
        "unchecked-hash",
        APP / "Lib",
        check=False,
    )

    print("==> Smoke test with a minimal PATH")
    system = os.environ["SystemRoot"]
    clean = {k: os.environ[k] for k in ("SystemRoot", "SystemDrive", "TEMP", "TMP", "USERPROFILE")}
    clean["PATH"] = f"{system}\\System32;{system}"
    clean["LOCALAPPDATA"] = str(BUILD / "localappdata")
    result = run(
        exe,
        HERE / "smoke.py",
        env=clean,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print(result.stdout, result.stderr[-4000:], sep="\n")
    if result.returncode != 0 or "smoke ok" not in result.stdout:
        sys.exit("Smoke test failed")

    print("==> Zip")
    too_long = [p for p in APP.rglob("*") if len(str(p.relative_to(APP.parent))) > MAX_PATH_IN_ZIP]
    if too_long:
        sys.exit(f"{len(too_long)} paths are too long for Explorer, e.g. {too_long[0]}")
    target = ROOT / "dist" / f"MeetingProtocol-{version}-windows-x64.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(APP.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(APP.parent))
    size = sum(p.stat().st_size for p in APP.rglob("*") if p.is_file())
    print(f"Folder {size / 1e9:.2f} GB, zip {target.stat().st_size / 1e9:.2f} GB: {target}")


if __name__ == "__main__":
    main()
