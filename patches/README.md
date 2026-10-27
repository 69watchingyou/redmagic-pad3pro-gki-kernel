# Exact-source SukiSU/SUSFS integration

## Status and scope

Adapted common-tree patch passed `git apply --cached --check` against a freshly populated independent index for common `54dcbfbef792fe56756fa60d5f10395a958ac2f1`. `git diff --check` and `bash -n integrate.sh` passed. No compilation, ABI comparison, device boot, or KPM runtime test was performed in this adaptation task. A successful textual patch check is not proof of compile/runtime correctness.

`integrate.sh COMMON_DIR` is fail-fast and requires a clean tracked common tree at the exact commit. It fetches pinned dependencies, validates dependency HEAD/cleanliness, runs `git apply --check` before mutation, applies the adapted patch, copies pinned SUSFS payloads and links the SukiSU kernel directory into `drivers/kernelsu`. It adds corresponding Kconfig/Makefile entries. It does not compile, package, sign, or flash. Re-running against a modified tree is refused; begin with a clean checkout if a previous integration failed.

Pins:
- common: `54dcbfbef792fe56756fa60d5f10395a958ac2f1`
- SukiSU builtin: `0b666cad90f3a13cb4085f8c88e5144594e82030`
- SUSFS gki-android15-6.6: `c51cd8aad3f7e2f8c48bc3bda88cc68cf7d82895`

This patch REPLACES `50_add_susfs_in_gki-android15-6.6.patch`; do not apply both. It contains the SUSFS manual hook entry calls. `69_hide_stuff.patch` is an unrelated optional mapping-hiding modification and is deliberately not applied. No obsolete `CONFIG_KSU_MANUAL_HOOK` or `CONFIG_KSU_TRACEPOINT_HOOK` is introduced, and no kernel release number is changed.

## Adaptations

Original upstream patch dry-run failed against this older common in fs/exec.c, fs/namespace.c, fs/proc/base.c, fs/proc/task_mmu.c and mm/memory.c. Initial `--reject` was used ONLY in the isolated research worktree to expose mismatched hunks; production integration does not use partial/reject mode.

- Restored SUSFS includes/declarations at existing older include anchors rather than importing unrelated new-kernel headers.
- `show_smap()` uses this tree's `get_data_vma(v)`/`get_pad_vma(v)` layout. Added the hidden-map check before statistics; preserved existing padded-VMA flow.
- Follow-up after external Actions run 40550423998 failed with `fs/proc/task_mmu.c:298: undeclared function '__fold_filemap_fixup_entry'`: the newer redirect hook incorrectly imported a folding helper absent from this baseline. This tree's `show_map()` already obtains a data-only VMA with `get_data_vma()` and renders padding separately through `show_map_pad_vma()`. `get_data_vma()` trims `vm_end` but leaves padding flag bits intact, so applying `VMA_PAD_START()` again would subtract padding twice. The redirected branch now uses `vma->vm_end`, matching the original renderer, with no folding call or replacement stub. The existing `__VM_NO_COMPAT` early-return guard was moved ahead of both ordinary and redirected paths so neither can print a fixup VMA. This follow-up passed a new independent-index patch check; it has not yet passed a compiler run.
- smaps-rollup's Case 4 uses this older tree's single-statement branch. Wrapped the existing statistics call with the SUSFS filter without changing the original last_vma_end bookkeeping.
- SukiSU's `ksu_su_compat_enabled` is actually `bool`, despite stale `static_key_true` declarations in the SUSFS50 patch. Replaced those declarations and checks in exec/open/stat with bool plus `READ_ONCE`.
- `ksu_handle_sys_read` actually returns int and accepts `(unsigned int fd, char __user **buf_ptr, size_t *count_ptr)`; corrected the declaration and syscall invocation to pass all three arguments.
- Other init-rc, input, first-zygote static keys do exist under `KSU_COMPAT_USE_STATIC_KEY` (enabled for >=4.3). Exec/preinit/post-exec/reboot/setresuid signatures were inspected in implementations as well as headers.

## Actual compiler follow-ups

Run 40554085205 passed SELinux header generation and reached the builtin driver, then failed on `policy/allowlist.c:456` with Clang `-Werror,-Wimplicit-fallthrough`. The separate `sukisu-clang-fallthrough.patch` replaces the existing intentional fall-through comment with the kernel `fallthrough;` annotation. It preserves version-2 to version-3 profile migration; no break or warning suppression is added. Integration checks and applies this patch to the pinned SukiSU dependency and saves its exact diff next to the common tree. Compilation must still be re-run.

## Configuration

Required top-level integration options: `CONFIG_KSU=y`, `CONFIG_KSU_SUSFS=y`, `CONFIG_KPM=y`, 4K ARM64 pages, KALLSYMS and KALLSYMS_ALL, IKCONFIG. This pinned Kconfig defaults its SUSFS sub-options to y; KPM defaults n and must be explicitly enabled. Validate the final generated config after olddefconfig. KPM's KernelPatch ABI2 companion and image postprocessing are outside this patch and remain independently required.

## SHA256

- susfs-sukisu-6.6.30.patch: `0f15a502ff245497de55d01218a469ba4e5abe99ee392ffc0fe09b1bb03ff1d8`
- pinned fs/susfs.c: `7dfe2337f458a23351db7e1b5f23ec4cacb98a35bb59052bf286fb36e7c2510e`
- pinned include/linux/susfs.h: `31d5caa8313e66d8ab23e56cebfefc855541f2adffc0c95e1d21a289899cb154`
- pinned include/linux/susfs_def.h: `adb2b86a0124e85ac24e3ce83332f2c70a810aef02b894f05b046b58b128ac38`

The patch does not modify copied payload internals. Upstream payload logic and API compatibility still need real compiler validation, and any resulting errors must be fixed rather than suppressed. No assertion is made about successful boot or usable KPM.
