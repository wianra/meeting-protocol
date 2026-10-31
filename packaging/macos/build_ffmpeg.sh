#!/bin/sh
# Builds minimal, static, LGPL-only ffmpeg and ffprobe for decoding meeting audio.
# No network protocols, no GPL parts, no external libraries; native audio decoders only.
set -eu
VERSION=9.0.2
SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK="$ROOT/build/ffmpeg"
OUT="$WORK/bin"
if [ -x "$OUT/ffmpeg" ] && [ -x "$OUT/ffprobe" ]; then
  echo "ffmpeg already built in $OUT"
  exit 0
fi
mkdir -p "$WORK"
cd "$WORK"
[ -f "ffmpeg-$VERSION.tar.xz" ] || curl -fL -o "ffmpeg-$VERSION.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
echo "$SHA256  ffmpeg-$VERSION.tar.xz" | shasum -a 256 -c -
rm -rf "ffmpeg-$VERSION" && tar xf "ffmpeg-$VERSION.tar.xz"
cd "ffmpeg-$VERSION"
CONFIGURE="--prefix=$WORK/install --cc=/usr/bin/clang --arch=arm64 --target-os=darwin \
  --extra-cflags=-mmacosx-version-min=13.0 --extra-ldflags=-mmacosx-version-min=13.0 \
  --enable-static --disable-shared --disable-gpl --disable-nonfree --disable-network \
  --disable-autodetect --disable-doc --disable-debug --disable-ffplay \
  --disable-everything --enable-ffmpeg --enable-ffprobe --enable-protocol=file,pipe \
  --enable-demuxer=mov,mp3,wav,flac,ogg,matroska,aac,aiff,w64,caf \
  --enable-decoder=aac,aac_latm,alac,mp3,mp3float,flac,opus,vorbis,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_s16be,pcm_s24be,pcm_f32be,pcm_u8,pcm_alaw,pcm_mulaw \
  --enable-parser=aac,mpegaudio,flac,opus,vorbis \
  --enable-filter=aresample,aformat,pan,anull \
  --enable-encoder=pcm_s16le --enable-muxer=pcm_s16le,wav \
  --enable-swresample"
# shellcheck disable=SC2086
./configure $CONFIGURE
make -j"$(sysctl -n hw.ncpu)"
mkdir -p "$OUT"
cp ffmpeg ffprobe "$OUT/"
cp COPYING.LGPLv2.1 "$WORK/COPYING.LGPLv2.1"
printf 'FFmpeg %s, built from https://ffmpeg.org/releases/ffmpeg-%s.tar.xz\nconfigure %s\n' \
  "$VERSION" "$VERSION" "$CONFIGURE" > "$WORK/BUILD-INFO.txt"
"$OUT/ffmpeg" -hide_banner -version | head -1
