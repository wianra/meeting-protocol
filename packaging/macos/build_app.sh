#!/bin/sh
# Builds dist/Meeting Protocol.app and a drag-to-Applications DMG for Apple Silicon.
#
# The app contains a standalone Python with the locked dependencies, static LGPL ffmpeg
# and ffprobe, and the speaker model. The speech model (3.1 GB) downloads on first launch.
#
# Prerequisites: ./setup.sh, packaging/macos/build_ffmpeg.sh, and a provisioned speaker
# model (./diarize provision diarization). Packages the last commit (HEAD), not uncommitted
# edits. Set SIGN_IDENTITY to a "Developer ID Application" certificate to sign for
# distribution; the default is ad-hoc.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
cd "$ROOT"
export UV_CACHE_DIR="$ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/.python"
NAME="Meeting Protocol"
VERSION=$(git show HEAD:src/meeting_protocol/__init__.py | sed -n 's/^__version__ = "\(.*\)"/\1/p')
APP="$ROOT/dist/$NAME.app"
CONTENTS="$APP/Contents"
RES="$CONTENTS/Resources"
DATA="${DIARIZE_HOME:-$ROOT/.local}"
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
FFMPEG_DIR="${FFMPEG_DIR:-$ROOT/build/ffmpeg}"

[ -x "$FFMPEG_DIR/bin/ffmpeg" ] || { echo "Run packaging/macos/build_ffmpeg.sh first." >&2; exit 1; }
for tool in ffmpeg ffprobe; do
  # Only system libraries: anything else (e.g. Homebrew) would be missing on users' Macs.
  if otool -L "$FFMPEG_DIR/bin/$tool" | tail -n +2 | grep -v "^\s*/usr/lib/\|^\s*/System/Library/" | grep -q .; then
    echo "$FFMPEG_DIR/bin/$tool links non-system libraries; use packaging/macos/build_ffmpeg.sh." >&2
    exit 1
  fi
done
[ -f "$DATA/models/diarization/manifest.json" ] || {
  echo "Provision the speaker model first: ./diarize provision diarization" >&2; exit 1; }

echo "==> Clean"
rm -rf "$APP" build/app dist/*.dmg
mkdir -p "$CONTENTS/MacOS" "$RES/bin" "$RES/models" build/app

echo "==> Standalone Python"
uv python install 3.12
PYBIN=$(uv python find --managed-python 3.12)
PYDIR=$(CDPATH= cd -- "$(dirname -- "$PYBIN")/.." && pwd -P)
mkdir -p "$RES/python"
cp -R "$PYDIR/" "$RES/python/"
[ ! -L "$RES/python" ] && [ -f "$RES/python/bin/python3.12" ] || { echo "Python copy failed" >&2; exit 1; }
PY="$RES/python/bin/python3.12"
rm -rf "$RES/python/include" "$RES/python/share" "$RES/python/lib/pkgconfig" \
  "$RES/python/lib/python3.12/test" "$RES/python/lib/python3.12/idlelib" \
  "$RES/python/lib/python3.12/tkinter" "$RES/python/lib/python3.12/turtledemo" \
  "$RES/python/lib/python3.12/ensurepip" "$RES/python/lib/tcl"* "$RES/python/lib/tk"* \
  "$RES/python/lib/itcl"* "$RES/python/lib/thread"* "$RES/python/lib/python3.12/EXTERNALLY-MANAGED"
find "$RES/python/bin" -type f ! -name python3.12 -delete
find "$RES/python/bin" -type l -delete

echo "==> Locked dependencies and the app"
uv export --frozen --no-dev --no-emit-project --quiet -o build/app/requirements.txt
uv pip install --python "$PY" --require-hashes --no-deps -r build/app/requirements.txt
# Package the committed code, never uncommitted edits in the working tree.
mkdir -p build/app/source
git archive HEAD pyproject.toml README.md LICENSE src | tar -x -C build/app/source
(cd build/app/source && uv build --wheel --out-dir "$ROOT/build/app/wheel" --quiet)
uv pip install --python "$PY" --no-deps build/app/wheel/*.whl
SITE="$RES/python/lib/python3.12/site-packages"

echo "==> Trim"
"$ROOT/.venv/bin/python" "$HERE/prune_qt.py" "$SITE"
rm -rf "$SITE/torch/include" "$SITE/torch/share" "$SITE/torch/test" \
  "$SITE"/*/tests "$SITE"/*/test
find "$RES/python" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$RES/python" \( -name "*.a" -o -name "*.pyi" \) -delete
# Universal binaries carry an unused Intel copy.
find "$RES/python" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) | while read -r f; do
  if lipo -archs "$f" 2>/dev/null | grep -q "x86_64 arm64\|arm64 x86_64"; then
    lipo -thin arm64 "$f" -output "$f.thin" && mv "$f.thin" "$f"
  fi
done
find "$RES/python/lib/python3.12/site-packages/PySide6/Qt/lib" -name "*.framework" | while read -r fw; do
  bin="$fw/Versions/A/$(basename "$fw" .framework)"
  if lipo -archs "$bin" 2>/dev/null | grep -q x86_64; then
    lipo -thin arm64 "$bin" -output "$bin.thin" && mv "$bin.thin" "$bin"
  fi
done

echo "==> ffmpeg and the speaker model"
cp "$FFMPEG_DIR/bin/ffmpeg" "$FFMPEG_DIR/bin/ffprobe" "$RES/bin/"
REV=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['revision'])" \
  "$DATA/models/diarization/manifest.json")
mkdir -p "$RES/models/diarization"
cp -R "$DATA/models/diarization/$REV" "$RES/models/diarization/$REV"
rm -rf "$RES/models/diarization/$REV/.cache"
"$PY" -c "import json,sys;m=json.load(open(sys.argv[1]));m.pop('path');print(json.dumps(m))" \
  "$DATA/models/diarization/manifest.json" > "$RES/models/diarization/manifest.json"

echo "==> Licences"
mkdir -p "$RES/licenses"
cp LICENSE "$RES/licenses/Meeting-Protocol-MIT.txt"
cp "$FFMPEG_DIR/COPYING.LGPLv2.1" "$FFMPEG_DIR/BUILD-INFO.txt" "$RES/licenses/"
cp "$HERE/NOTICES.txt" "$RES/licenses/NOTICES.txt"

echo "==> Launcher, Info.plist and icon"
# A small native launcher embeds Python, so macOS treats the process as the app itself:
# the Dock and menu bar show "Meeting Protocol" and its icon, not Python.
install_name_tool -id @rpath/libpython3.12.dylib "$RES/python/lib/libpython3.12.dylib"
/usr/bin/clang -O2 -mmacosx-version-min=14.0 -arch arm64 -I "$PYDIR/include/python3.12" \
  "$HERE/launcher.c" -L "$RES/python/lib" -lpython3.12 \
  -Wl,-rpath,@executable_path/../Resources/python/lib -o "$CONTENTS/MacOS/$NAME"
rm "$PY"
sed "s/__VERSION__/$VERSION/g" "$HERE/Info.plist" > "$CONTENTS/Info.plist"
"$ROOT/.venv/bin/python" "$HERE/make_icon.py" src/meeting_protocol/gui/assets/app-icon.svg build/app/AppIcon.iconset
iconutil -c icns build/app/AppIcon.iconset -o "$RES/AppIcon.icns"

echo "==> Precompile (the signed bundle must stay unchanged at run time)"
"$CONTENTS/MacOS/$NAME" -m compileall -q -j0 \
  --invalidation-mode unchecked-hash "$RES/python/lib/python3.12" || true

echo "==> Smoke test: every entry point imports from the bundle alone"
env -i HOME="$HOME" QT_QPA_PLATFORM=offscreen "$CONTENTS/MacOS/$NAME" -c "
import sys, os
assert sys.executable.endswith('MacOS/$NAME'), sys.executable
assert os.environ['PYTHONHOME'].endswith('Resources/python')
import meeting_protocol.cli, meeting_protocol.gui.main, meeting_protocol.gui.setup
import meeting_protocol.gui.classic, meeting_protocol.gui.simple
import mlx_whisper, pyannote.audio, torch
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
app = QApplication([])
assert not meeting_protocol.gui.common.QIcon(str(meeting_protocol.gui.common.ICON)).isNull()
print('imports ok')
"

echo "==> Sign ($SIGN_IDENTITY)"
FLAGS="--force --sign $SIGN_IDENTITY"
[ "$SIGN_IDENTITY" = "-" ] || FLAGS="$FLAGS --timestamp --options runtime --entitlements $HERE/entitlements.plist"
find "$RES" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) | while read -r f; do
  if file "$f" | grep -q "Mach-O"; then
    # shellcheck disable=SC2086
    codesign $FLAGS "$f" 2>/dev/null || codesign $FLAGS "$f"
  fi
done
find "$RES" -name "*.framework" -type d -prune | while read -r fw; do
  # shellcheck disable=SC2086
  codesign $FLAGS "$fw"
done
# shellcheck disable=SC2086
codesign $FLAGS "$APP"
codesign --verify --strict "$APP"

echo "==> DMG"
STAGE=build/app/dmg
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/MeetingProtocol-$VERSION-arm64.dmg"
hdiutil create -quiet -volname "$NAME" -srcfolder "$STAGE" -fs HFS+ -format ULFO -ov "$DMG"
du -sh "$APP" "$DMG"
