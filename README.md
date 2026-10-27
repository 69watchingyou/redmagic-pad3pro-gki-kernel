# RedMagic Pad3Pro experimental kernel build

Target: stock android15-6.6.30, KMI 8, 4K pages, built-in SukiSU + SUSFS + KPM.

User-designated remote: https://github.com/69watchingyou/redmagic-pad3pro-gki-kernel.git

## Status

Main kernel compilation is experimental and has not yet succeeded or been boot tested. No flashable boot image is supplied. The new kernel-candidate workflow attempts a raw Image/modules build from the exact stock source and adapted SukiSU/SUSFS hooks. The preflight workflow still intentionally fails while integration validation is unresolved. A separate KPM component workflow has successfully compiled its payload and host tools. Do not interpret unit-test or patch-application success as kernel compatibility.

Verified common source: `54dcbfbef792fe56756fa60d5f10395a958ac2f1`, tag `android15-6.6-2024-07_r29`, build `12368803`. A matched historical superproject snapshot now pins all 34 dependencies; this is not proof of the original CI full manifest. New KPM ABI v2 components have successfully built separately from pinned source with a checksum-verified ARM compiler. A successful component build is not a compiled kernel or a device compatibility result. No automatic flashing commands are included.

## Local checks

```sh
python3 -m unittest discover -s . -p "test_*.py" -v
python3 preflight.py
python3 inspect_stock.py /path/to/original-firmware
python3 verify_artifact.py /path/to/raw/Image
```

Preflight currently exits 2 by design. Artifact config checks do not establish KPM runtime operation, vendor ABI compatibility, or AVB acceptance. Stock image inspector is read-only and does not verify AVB cryptographic signatures.

## Offline vendor module check

`check_vendor_abi.py` accepts a separately preserved requirements JSON, one or more `--symvers` files, the complete actual candidate module `--candidate-vermagic`, and an exclusive new `--report` path. It compares imported CRCs and follows the exact MODVERSIONS first-space vermagic rule. A release suffix difference alone is not a failure when the module has CRCs. Missing symbols remain unresolved because some may be supplied by unchanged vendor modules. Even a passing limited check does not certify vendor ABI, CFI, signatures, boot or runtime behavior. Original firmware payloads are not included in this repository.

## Reference scripts

The previously audited ShirkNeko/GKI_KernelSU_SUSFS scripts are deliberately not shipped here. They ignore several command failures, use moving dependencies, skip 6.6 KPM postprocessing and use generic packaging parameters. The KPM component workflow builds native tools and payload only; its artifacts are NOT boot images.

Original firmware images and private keys must never be committed. Preserve original boot/init_boot/vendor_boot separately. Before migration preserve the currently working patched init_boot as well; no such device partition backup has yet been made.
