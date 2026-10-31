#!/bin/sh
set -eu
cd "$(dirname "$0")"
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.python"
uv sync --frozen --python 3.12 --extra dev
echo 'Installed. Run ./diarize doctor, then ./diarize provision asr.'
