#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

linux_target="x86_64-unknown-linux-gnu"
mac_target="aarch64-apple-darwin"

mkdir -p ops/bin

echo "[build] target=$linux_target"
cargo build --release --target "$linux_target"
install -m 755 "target/$linux_target/release/musikalisches" "ops/bin/musikalisches-linux-amd64"
install -m 755 "target/$linux_target/release/musikalisches" "ops/bin/musikalisches"
echo "[ok] ops/bin/musikalisches-linux-amd64"

can_build_macos=0
if [[ -n "${CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER:-}" ]]; then
  can_build_macos=1
elif command -v o64-clang >/dev/null 2>&1; then
  export CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER="${CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER:-o64-clang}"
  can_build_macos=1
fi

if [[ $can_build_macos -eq 0 ]]; then
  echo "[skip] target=$mac_target requires CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER or o64-clang plus a macOS SDK"
  exit 0
fi

echo "[build] target=$mac_target"
cargo build --release --target "$mac_target"
install -m 755 "target/$mac_target/release/musikalisches" "ops/bin/musikalisches-macos-arm64"
echo "[ok] ops/bin/musikalisches-macos-arm64"
