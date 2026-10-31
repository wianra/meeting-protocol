#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
exec ./diarize gui-simple
