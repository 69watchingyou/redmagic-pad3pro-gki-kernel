#!/usr/bin/env bash
# Experimental raw Image/modules build. No downloading, patching, packaging or flashing.
# Patches and KPM implementation must be integrated and reviewed by the caller first.
set -euo pipefail
export LC_ALL=C
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || fail 'Linux x86_64 build host required'
[[ $(uname -m) == x86_64 ]] || fail 'Android pinned prebuilts require x86_64'
: "${COMMON_DIR:?absolute path to patched common checkout required}"
: "${CLANG_DIR:?absolute path to clang-r510928 required}"
: "${STOCK_CONFIG:?absolute path to extracted stock.config required}"
: "${OUT_DIR:?absolute path to NEW empty output directory required}"
: "${PATCH_REVIEW_ACK:?set to experimental-not-flashable after reviewing the applied patches}"
[[ $PATCH_REVIEW_ACK == experimental-not-flashable ]] || fail 'patch review acknowledgement invalid'
COMMON_SHA=54dcbfbef792fe56756fa60d5f10395a958ac2f1
CLANG_REPO_SHA=7061673283909f372f4938e45149d23bd10cbd40
RUST_REPO_SHA=442511af884f074018466f85b4daadd4b0ac0050
COMMON_DIR=$(realpath "$COMMON_DIR")
CLANG_DIR=$(realpath "$CLANG_DIR")
STOCK_CONFIG=$(realpath "$STOCK_CONFIG")
OUT_DIR=$(realpath -m "$OUT_DIR")
[[ $(git -C "$COMMON_DIR" rev-parse HEAD) == "$COMMON_SHA" ]] || fail 'common HEAD not stock base; apply patches without replacing HEAD'
[[ $(git -C "$CLANG_DIR" rev-parse HEAD) == "$CLANG_REPO_SHA" ]] || fail 'clang repository not pinned snapshot'
[[ $CLANG_DIR == */clang-r510928 ]] || fail 'select clang-r510928 subdirectory'
[[ -x $CLANG_DIR/bin/clang ]] || fail 'clang missing'
"$CLANG_DIR/bin/clang" --version | tee /dev/stderr | grep -q 'based on r510928' || fail 'clang revision banner mismatch'
for cmd in make python3 perl bc bison flex openssl pahole rsync; do command -v "$cmd" >/dev/null || fail "missing host prerequisite: $cmd"; done
[[ -z ${KCFLAGS:-} && -z ${KCPPFLAGS:-} && -z ${KBUILD_EXTRA_SYMBOLS:-} ]] || fail 'unexpected externally injected compile/ABI flags'
[[ ! -e $OUT_DIR || -z $(ls -A "$OUT_DIR") ]] || fail 'OUT_DIR must be empty'
[[ $OUT_DIR != "$COMMON_DIR" && $OUT_DIR != "$COMMON_DIR/"* ]] || fail 'output must be outside source checkout'
mkdir -p "$OUT_DIR/evidence"
cp "$STOCK_CONFIG" "$OUT_DIR/evidence/stock.config"
git -C "$COMMON_DIR" diff --binary HEAD > "$OUT_DIR/evidence/applied.patch"
git -C "$COMMON_DIR" status --porcelain=v1 > "$OUT_DIR/evidence/source-status.txt"
git -C "$COMMON_DIR" ls-files --others --exclude-standard > "$OUT_DIR/evidence/untracked-files.txt"
# Source status is not a complete patch lock: caller must archive/hash linked SukiSU etc.
export PATH="$CLANG_DIR/bin:$PATH"
if [[ -n ${RUST_DIR:-} ]]; then
  RUST_DIR=$(realpath "$RUST_DIR")
  [[ $(git -C "$RUST_DIR" rev-parse HEAD) == "$RUST_REPO_SHA" ]] || fail 'rust repository not pinned snapshot'
  [[ $RUST_DIR == */1.73.0b ]] || fail 'select rust linux-x86/1.73.0b directory'
  export PATH="$RUST_DIR/bin:$PATH"
fi
# Stock CONFIG_RUST is disabled. The pinned Rust compiler is only mandatory if enabled.
export ARCH=arm64
export LLVM=1
export LLVM_IAS=1
export KCFLAGS=-D__ANDROID_COMMON_KERNEL__
export LOCALVERSION=''
# Keep patch identity honest: never forge original -ab12368803 certification banner.
cp "$STOCK_CONFIG" "$OUT_DIR/.config"
"$COMMON_DIR/scripts/config" --file "$OUT_DIR/.config" \
  --set-str LOCALVERSION '-android15-8-candidate-4k' --enable LOCALVERSION_AUTO
# Flatten ONLY the symbol-list inputs explicitly present in this stock BUILD.bazel.
# This approximates Kleaf's list preparation; the raw make path does NOT run ABI checks.
python3 - "$COMMON_DIR" "$OUT_DIR/abi_symbollist.raw" <<'PY'
import pathlib, re, sys
source = pathlib.Path(sys.argv[1])
build = (source / 'BUILD.bazel').read_text()
section = build.split('name = "aarch64_additional_kmi_symbol_lists",', 1)[1].split('visibility =', 1)[0]
paths = ['android/abi_gki_aarch64'] + re.findall(r'"(android/abi_gki_aarch64_[^"]+)"', section)
symbols = set()
for name in paths:
    for line in (source / name).read_text().splitlines():
        text = line.split('#', 1)[0].strip()
        if text and not text.startswith('['):
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', text):
                raise SystemExit('Unrecognized symbol-list syntax: ' + text)
            symbols.add(text)
if not symbols:
    raise SystemExit('empty symbol whitelist')
pathlib.Path(sys.argv[2]).write_text('\n'.join(sorted(symbols)) + '\n')
PY
"$COMMON_DIR/scripts/config" --file "$OUT_DIR/.config" --set-str UNUSED_KSYMS_WHITELIST "$OUT_DIR/abi_symbollist.raw"
# Caller integrates only reviewed options. Do not silently claim KPM by setting a bool.
if [[ -n ${CONFIG_FRAGMENT:-} ]]; then
  [[ -f $CONFIG_FRAGMENT ]] || fail 'CONFIG_FRAGMENT missing'
  "$COMMON_DIR/scripts/kconfig/merge_config.sh" -m -O "$OUT_DIR" "$OUT_DIR/.config" "$CONFIG_FRAGMENT"
fi
make_args=(-C "$COMMON_DIR" O="$OUT_DIR" ARCH=arm64 LLVM=1 LLVM_IAS=1)
# Prevent upstream SukiSU Makefile's immediate shell network lookups. Pin identity
# through command-line make variables (ordinary := assignments cannot override them).
if [[ -e $COMMON_DIR/drivers/kernelsu/Makefile ]]; then
  : "${KSU_VERSION_PIN:?explicit reviewed numeric KSU_VERSION required}"
  : "${KSU_VERSION_FULL_PIN:?explicit reviewed SukiSU commit/version label required}"
  [[ $KSU_VERSION_PIN =~ ^[0-9]+$ ]] || fail 'invalid numeric KSU version'
  [[ $KSU_VERSION_FULL_PIN =~ ^[a-zA-Z0-9._@+-]+$ ]] || fail 'unsafe KSU version label'
  make_args+=(GIT_BIN=/bin/false CURL_BIN=/bin/false KSU_GITHUB_VER= GITHUB_COMMITS=
    "KSU_VERSION=$KSU_VERSION_PIN" "KSU_VERSION_FULL=$KSU_VERSION_FULL_PIN")
fi
make "${make_args[@]}" olddefconfig
if grep -qx 'CONFIG_RUST=y' "$OUT_DIR/.config"; then
  [[ -n ${RUST_DIR:-} ]] || fail 'CONFIG_RUST=y needs pinned RUST_DIR'
  "$RUST_DIR/bin/rustc" --version | tee "$OUT_DIR/evidence/rust-version.txt"
fi
# Fail if stock ABI/security-sensitive settings are lost during configuration.
python3 - "$STOCK_CONFIG" "$OUT_DIR/.config" <<'PY'
import pathlib, sys
stock, result = [set(pathlib.Path(p).read_text().splitlines()) for p in sys.argv[1:]]
for required in ('CONFIG_KSU=y', 'CONFIG_KSU_SUSFS=y', 'CONFIG_KPM=y', 'CONFIG_KALLSYMS=y', 'CONFIG_KALLSYMS_ALL=y', 'CONFIG_IKCONFIG=y'):
    if required not in result:
        raise SystemExit('Required integrated configuration missing: ' + required)
keys = ('CONFIG_ARM64_4K_PAGES', 'CONFIG_MODVERSIONS', 'CONFIG_MODULE_SIG', 'CONFIG_MODULE_SIG_PROTECT', 'CONFIG_CFI_CLANG', 'CONFIG_LTO_NONE', 'CONFIG_ANDROID_KABI_RESERVE', 'CONFIG_TRIM_UNUSED_KSYMS')
for key in keys:
    required = key + '=y'
    if required in stock and required not in result:
        raise SystemExit('ABI/security configuration changed: ' + key)
PY
cp "$OUT_DIR/.config" "$OUT_DIR/evidence/resolved.config"
"$CLANG_DIR/bin/clang" --version > "$OUT_DIR/evidence/clang-version.txt"
make "${make_args[@]}" -s kernelrelease > "$OUT_DIR/evidence/kernelrelease.txt"
# SukiSU checks usr/include at parse time: install UAPI before parsing Image build.
make "${make_args[@]}" INSTALL_HDR_PATH="$OUT_DIR/usr" headers_install
# Compile adapted integration surfaces first so API errors fail before a full build.
# These are real Kbuild targets with identical flags, not a substitute for the full link.
# SukiSU includes generated SELinux headers; build their owner before the driver.
make "${make_args[@]}" -j"${JOBS:-$(nproc)}" security/selinux/
make "${make_args[@]}" -j"${JOBS:-$(nproc)}" fs/proc/task_mmu.o fs/susfs.o drivers/kernelsu/
make "${make_args[@]}" -j"${JOBS:-$(nproc)}" Image modules
[[ -s $OUT_DIR/arch/arm64/boot/Image && -s $OUT_DIR/Module.symvers && -s $OUT_DIR/vmlinux ]] || fail 'required build outputs missing'
sha256sum "$OUT_DIR/arch/arm64/boot/Image" "$OUT_DIR/vmlinux" "$OUT_DIR/Module.symvers" > "$OUT_DIR/evidence/SHA256SUMS"
printf '%s\n' 'EXPERIMENTAL RAW BUILD ONLY' 'No vendor ABI comparison, no boot test, no KPM functional test.' 'Not the certified stock build. Do not package or flash automatically.' > "$OUT_DIR/evidence/STATUS.txt"
printf 'Candidate Image: %s\nEvidence: %s\n' "$OUT_DIR/arch/arm64/boot/Image" "$OUT_DIR/evidence"
