#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
VERSION="${FFMPEG_VERSION:-8.1}"
SOURCE_URL="${FFMPEG_SOURCE_URL:-https://ffmpeg.org/releases/ffmpeg-${VERSION}.tar.xz}"
BUILD_ROOT="${FFMPEG_BUILD_ROOT:-${ROOT}/ops/out/ffmpeg-rtmps-build}"
SOURCE_DIR="${BUILD_ROOT}/src/ffmpeg-${VERSION}"
ARCHIVE_PATH="${BUILD_ROOT}/ffmpeg-${VERSION}.tar.xz"
PREFIX_DIR="${FFMPEG_PREFIX:-${ROOT}/ops/bin}"
JOBS="${FFMPEG_JOBS:-$(nproc)}"

mkdir -p "${BUILD_ROOT}/src" "${PREFIX_DIR}"

if [[ ! -f "${ARCHIVE_PATH}" ]]; then
  curl -L --fail --silent --show-error "${SOURCE_URL}" -o "${ARCHIVE_PATH}"
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
  tar -xf "${ARCHIVE_PATH}" -C "${BUILD_ROOT}/src"
fi

cd "${SOURCE_DIR}"
make distclean >/dev/null 2>&1 || true

PKG_CONFIG_PATH="${PKG_CONFIG_PATH:-}" ./configure \
  --prefix="${PREFIX_DIR}" \
  --pkg-config-flags="--static" \
  --extra-cflags="${CFLAGS:-}" \
  --extra-ldflags="${LDFLAGS:-}" \
  --extra-libs="-lpthread -lm" \
  --bindir="${PREFIX_DIR}" \
  --disable-debug \
  --disable-doc \
  --disable-ffplay \
  --enable-ffmpeg \
  --enable-ffprobe \
  --enable-gpl \
  --enable-libx264 \
  --enable-openssl \
  --enable-version3

make -j"${JOBS}"
make install

cat > "${PREFIX_DIR}/ffmpeg_rtmps_build_info.txt" <<EOF
ffmpeg_version=${VERSION}
source_url=${SOURCE_URL}
source_dir=${SOURCE_DIR}
prefix_dir=${PREFIX_DIR}
jobs=${JOBS}
built_at_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

printf '%s\n' "stage7 ffmpeg build complete"
printf '%s\n' "ffmpeg_bin=${PREFIX_DIR}/ffmpeg"
printf '%s\n' "ffprobe_bin=${PREFIX_DIR}/ffprobe"
