#!/usr/bin/env bash
# Exact-source experimental integration. No compilation, packaging, or flashing.
set -euo pipefail
COMMON_DIR="${1:-${COMMON_DIR:?COMMON_DIR is required}}"
COMMON_DIR="$(cd "$COMMON_DIR" && pwd)"
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_COMMON=54dcbfbef792fe56756fa60d5f10395a958ac2f1
KSU_SHA=0b666cad90f3a13cb4085f8c88e5144594e82030
SUSFS_SHA=c51cd8aad3f7e2f8c48bc3bda88cc68cf7d82895
[[ "$(git -C "$COMMON_DIR" rev-parse HEAD)" == "$EXPECTED_COMMON" ]] || { echo 'Wrong common source' >&2; exit 1; }
[[ -z "$(git -C "$COMMON_DIR" status --porcelain --untracked-files=no)" ]] || { echo 'Tracked common tree is dirty; refusing partial/repeated integration' >&2; exit 1; }
fetch_pin() {
  local url="$1" sha="$2" dest="$3"
  if [[ ! -d "$dest/.git" ]]; then
    mkdir -p "$dest"
    git -C "$dest" init
    git -C "$dest" remote add origin "$url"
    git -C "$dest" fetch --depth=1 origin "$sha"
    git -C "$dest" checkout --detach FETCH_HEAD
  fi
  [[ "$(git -C "$dest" rev-parse HEAD)" == "$sha" ]] || { echo "Wrong dependency HEAD: $dest" >&2; exit 1; }
  [[ -z "$(git -C "$dest" status --porcelain)" ]] || { echo "Dirty dependency: $dest" >&2; exit 1; }
}
KSU_DIR="${KSU_DIR:-$(dirname "$COMMON_DIR")/sukisu-pinned}"
SUSFS_DIR="${SUSFS_DIR:-$(dirname "$COMMON_DIR")/susfs-pinned}"
fetch_pin https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$KSU_SHA" "$KSU_DIR"
fetch_pin https://github.com/ShirkNeko/susfs4ksu.git "$SUSFS_SHA" "$SUSFS_DIR"
KSU_DIR="$(cd "$KSU_DIR" && pwd)"
SUSFS_DIR="$(cd "$SUSFS_DIR" && pwd)"
# This is an adapted replacement for the upstream 50 patch. Do NOT apply both.
git -C "$COMMON_DIR" apply --check "$PATCH_DIR/susfs-sukisu-6.6.30.patch"
for file in fs/susfs.c include/linux/susfs.h include/linux/susfs_def.h; do
  [[ ! -e "$COMMON_DIR/$file" ]] || { echo "Refusing existing payload: $file" >&2; exit 1; }
done
[[ ! -e "$COMMON_DIR/drivers/kernelsu" && ! -L "$COMMON_DIR/drivers/kernelsu" ]] || { echo 'kernelsu already exists' >&2; exit 1; }
# Preserve intentional profile v2 -> v3 migration with a Clang-recognized annotation.
git -C "$KSU_DIR" apply --check "$PATCH_DIR/sukisu-clang-fallthrough.patch"
git -C "$KSU_DIR" apply "$PATCH_DIR/sukisu-clang-fallthrough.patch"
git -C "$KSU_DIR" diff --check
git -C "$KSU_DIR" diff --binary HEAD > "$(dirname "$COMMON_DIR")/sukisu-applied.patch"
git -C "$COMMON_DIR" apply "$PATCH_DIR/susfs-sukisu-6.6.30.patch"
cp "$SUSFS_DIR/kernel_patches/fs/susfs.c" "$COMMON_DIR/fs/susfs.c"
cp "$SUSFS_DIR/kernel_patches/include/linux/susfs.h" "$COMMON_DIR/include/linux/susfs.h"
cp "$SUSFS_DIR/kernel_patches/include/linux/susfs_def.h" "$COMMON_DIR/include/linux/susfs_def.h"
ln -s "$KSU_DIR/kernel" "$COMMON_DIR/drivers/kernelsu"
printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> "$COMMON_DIR/drivers/Makefile"
printf '\nsource "drivers/kernelsu/Kconfig"\n' >> "$COMMON_DIR/drivers/Kconfig"
# No old CONFIG_KSU_MANUAL_HOOK / TRACEPOINT_HOOK symbols, no version spoofing.
git -C "$COMMON_DIR" diff --check
rejected="$(find "$COMMON_DIR" -name '*.rej' -print -quit)"
if [[ -n "$rejected" ]]; then
  echo "Reject file exists: $rejected" >&2
  exit 1
fi
printf '%s\n' 'Integration applied; compilation, ABI checks, and boot/KPM tests remain required.'
