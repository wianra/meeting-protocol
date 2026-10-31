"""Render the SVG app icon to a macOS .iconset. Usage: make_icon.py SVG ICONSET_DIR"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main(svg: Path, out: Path):
    app = QGuiApplication([])  # noqa: F841 -- required before painting
    renderer = QSvgRenderer(str(svg))
    out.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            image = QImage(px, px, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
            suffix = "@2x" if scale == 2 else ""
            image.save(str(out / f"icon_{size}x{size}{suffix}.png"))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
