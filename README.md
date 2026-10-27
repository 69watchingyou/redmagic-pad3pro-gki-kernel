# RedMagic Pad3Pro kernel preparation — NOT BUILD READY

Target: stock android15-6.6.30, KMI 8, 4K pages, built-in SukiSU + SUSFS + KPM.

User-designated remote: https://github.com/69watchingyou/redmagic-pad3pro-gki-kernel.git

## Status

No kernel has been compiled or boot tested. No flashable boot image is supplied. The included workflow is a preflight only and intentionally fails while required source/integration pins are unresolved. Do not interpret unit-test success as kernel compatibility.

Verified common source: `54dcbfbef792fe56756fa60d5f10395a958ac2f1`, tag `android15-6.6-2024-07_r29`, build `12368803`. Full manifest and toolchain pin remain unresolved. KPM needs a verified implementation/postprocessor, not just CONFIG_KPM=y. No automatic flashing commands are included.

## Local checks

```sh
python3 -m unittest discover -s . -p "test_*.py" -v
python3 preflight.py
python3 inspect_stock.py /path/to/original-firmware
python3 verify_artifact.py /path/to/raw/Image
```

Preflight currently exits 2 by design. Artifact config checks do not establish KPM runtime operation, vendor ABI compatibility, or AVB acceptance. Stock image inspector is read-only and does not verify AVB cryptographic signatures.

## Reference scripts

`scripts/` contains unmodified audit reference downloads from ShirkNeko/GKI_KernelSU_SUSFS commit `814c5c22afbaa707c50a7573ec4edc338e80004a`. These scripts are NOT invoked by the workflow and are NOT the build recipe: they ignore several command failures, use moving dependencies, skip 6.6 KPM postprocessing and use generic packaging parameters. Do not run them as a validated device build.

Original firmware images and private keys must never be committed. Preserve original boot/init_boot/vendor_boot separately. Before migration preserve the currently working patched init_boot as well; no such device partition backup has yet been made.
