"""Inspect stock Android boot images read-only; never writes firmware."""
import argparse, gzip, hashlib, json, struct
from pathlib import Path

NAMES = ("boot.img", "init_boot.img", "vendor_boot.img")

def inspect(path):
    b = Path(path).read_bytes()
    result = {"name": Path(path).name, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    if len(b) < 64:
        raise ValueError("Truncated image")
    if b[:8] == b"ANDROID!":
        version = struct.unpack_from("<I", b, 40)[0]
        if version not in (3, 4):
            raise ValueError("Unsupported boot header")
        kernel_size, ramdisk_size, os_version, header_size = struct.unpack_from("<4I", b, 8)
        expected_header = 1584 if version == 4 else 1580
        if header_size != expected_header or len(b) < 4096:
            raise ValueError("Invalid header size")
        ramdisk_offset = 4096 + ((kernel_size + 4095) // 4096) * 4096
        signature_offset = ramdisk_offset + ((ramdisk_size + 4095) // 4096) * 4096
        signature_size = struct.unpack_from("<I", b, 1580)[0] if version == 4 else 0
        if signature_offset + signature_size > len(b):
            raise ValueError("Payload extends past image")
        result.update(header_version=version, kernel_size=kernel_size, ramdisk_size=ramdisk_size,
                      os_version_raw=os_version, header_size=header_size, signature_size=signature_size)
        if kernel_size:
            kernel = b[4096:4096 + kernel_size]
            result["kernel_sha256"] = hashlib.sha256(kernel).hexdigest()
            marker = kernel.find(b"Linux version ")
            if marker >= 0:
                end = kernel.find(b"\0", marker)
                result["kernel_version"] = kernel[marker:end if end >= 0 else marker+1024].decode(errors="replace")
            start = kernel.find(b"IKCFG_ST")
            end = kernel.find(b"IKCFG_ED", start + 8)
            if start >= 0 and end > start:
                config = gzip.decompress(kernel[start+8:end]).decode()
                result["config_sha256"] = hashlib.sha256(config.encode()).hexdigest()
                result["required_stock_flags"] = {key: key in config.splitlines() for key in (
                    "CONFIG_ARM64_4K_PAGES=y", "CONFIG_MODVERSIONS=y", "CONFIG_CFI_CLANG=y",
                    "CONFIG_MODULE_SIG_PROTECT=y", "CONFIG_LTO_NONE=y")}
    elif b[:8] == b"VNDRBOOT":
        version, pagesize = struct.unpack_from("<II", b, 8)
        if version not in (3, 4) or pagesize < 512 or pagesize & (pagesize-1):
            raise ValueError("Invalid vendor boot header")
        result.update(header_version=version, page_size=pagesize)
    else:
        raise ValueError("Unrecognized boot image")
    if b[-64:-60] == b"AVBf":
        major, minor, original_size, vbmeta_offset, vbmeta_size = struct.unpack_from(">IIQQQ", b, len(b)-60)
        if vbmeta_offset + vbmeta_size > len(b)-64 or original_size > len(b):
            raise ValueError("Invalid AVB footer bounds")
        result["avb_footer"] = {"version": [major, minor], "original_size": original_size,
                                "vbmeta_offset": vbmeta_offset, "vbmeta_size": vbmeta_size}
    else:
        result["avb_footer"] = None
    result["signature_verified"] = False
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_directory")
    parser.add_argument("--evidence", help="Existing JSON with expected image hashes")
    args = parser.parse_args()
    results = [inspect(Path(args.firmware_directory) / name) for name in NAMES]
    if args.evidence:
        evidence = json.loads(Path(args.evidence).read_text())
        expected = {Path(item["path"]).name: item["sha256"] for item in evidence["images"]}
        for result in results:
            if result["sha256"] != expected[result["name"]]:
                raise SystemExit("HASH MISMATCH: " + result["name"])
    print(json.dumps({"read_only": True, "hashes_match_evidence": bool(args.evidence), "images": results}, indent=2))
