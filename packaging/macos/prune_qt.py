"""Remove the parts of PySide6 the app never loads. Usage: prune_qt.py SITE_PACKAGES

Keeps the Python modules the app imports, plus every Qt framework and plugin they link
against (found with otool), and deletes the rest: WebEngine, QML, 3D, Designer and so on.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

MODULES = ["QtCore", "QtGui", "QtWidgets", "QtMultimedia", "QtNetwork", "QtSvg"]
PLUGINS = {
    "platforms": ["libqcocoa.dylib", "libqoffscreen.dylib", "libqminimal.dylib"],
    "imageformats": ["libqsvg.dylib", "libqico.dylib", "libqicns.dylib", "libqjpeg.dylib"],
    "iconengines": ["libqsvgicon.dylib"],
    "multimedia": ["libdarwinmediaplugin.dylib", "libffmpegmediaplugin.dylib"],
    "styles": ["libqmacstyle.dylib"],
}
LINK = re.compile(r"@(?:rpath|loader_path)/(?:\.\./)*(?:lib/)?(Qt\w+)\.framework")


def linked_frameworks(binary: Path) -> set[str]:
    if not binary.is_file():
        raise SystemExit(f"Cannot inspect {binary}")
    out = subprocess.run(
        ["otool", "-L", str(binary)], check=True, capture_output=True, text=True
    ).stdout
    return set(LINK.findall(out))


def main(site: Path):
    pyside = site / "PySide6"
    qt = pyside / "Qt"
    roots = [pyside / f"{m}.abi3.so" for m in MODULES]
    roots += [qt / "plugins" / kind / name for kind, names in PLUGINS.items() for name in names]
    roots = [r for r in roots if r.exists()]
    needed: set[str] = set()
    queue = [linked_frameworks(r) for r in roots]
    while queue:
        for name in queue.pop() - needed:
            needed.add(name)
            queue.append(
                linked_frameworks(qt / "lib" / f"{name}.framework" / "Versions" / "A" / name)
            )

    removed = 0
    for framework in (qt / "lib").glob("*.framework"):
        if framework.stem not in needed:
            shutil.rmtree(framework)
            removed += 1
    for module in pyside.glob("Qt*.abi3.so"):
        if module.name.split(".")[0] not in MODULES:
            module.unlink()
            module.with_name(module.name.split(".")[0] + ".pyi").unlink(missing_ok=True)
    for kind in (qt / "plugins").iterdir():
        keep = PLUGINS.get(kind.name)
        if keep is None:
            shutil.rmtree(kind)
            continue
        for plugin in kind.iterdir():
            if plugin.name not in keep:
                plugin.unlink()
    for name in [
        "qml",
        "translations",
        "metatypes",
        "libexec",
    ]:
        shutil.rmtree(qt / name, ignore_errors=True)
    for name in [
        "Assistant.app",
        "Designer.app",
        "Linguist.app",
        "include",
        "typesystems",
        "glue",
        "doc",
        "examples",
        "scripts",
        "QtAsyncio",
        "libpyside6qml.abi3.6.12.dylib",
    ]:
        path = pyside / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for tool in pyside.iterdir():
        if tool.is_file() and not tool.suffix and tool.name != "py.typed":
            tool.unlink()  # command-line tools: balsam, lrelease, qmlls, ...
    print(f"Kept Qt frameworks: {', '.join(sorted(needed))}; removed {removed}.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
