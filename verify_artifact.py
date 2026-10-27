"""Read-only gate for a raw arm64 Image; does not prove device compatibility."""
import argparse, gzip, hashlib, json, re, struct
from pathlib import Path

REQUIRED = ("CONFIG_KSU=y", "CONFIG_KSU_SUSFS=y", "CONFIG_KPM=y", "CONFIG_KALLSYMS=y", "CONFIG_KALLSYMS_ALL=y", "CONFIG_ARM64_4K_PAGES=y", "CONFIG_MODVERSIONS=y")

def inspect(path):
    data = Path(path).read_bytes()
    if data[:8] == b"ANDROID!":
        raise ValueError("Expected raw Image, not boot.img")
    if len(data) < 64 or data[56:60] != b"ARM\x64":
        raise ValueError("Not an uncompressed ARM64 Linux Image")
    if ((struct.unpack_from("<Q", data, 24)[0] >> 1) & 3) != 1:
        raise ValueError("ARM64 header does not declare 4K pages")
    start = data.find(b"IKCFG_ST")
    end = data.find(b"IKCFG_ED", start + 8)
    if start < 0 or end < 0:
        raise ValueError("Embedded kernel config missing")
    config = gzip.decompress(data[start + 8:end]).decode()
    missing = [item for item in REQUIRED if item not in config.splitlines()]
    if missing:
        raise ValueError("Missing required config: " + ", ".join(missing))
    marker = data.find(b"Linux version ")
    if marker < 0:
        raise ValueError("Kernel version missing")
    version_end = data.find(b"\0", marker)
    if version_end < 0:
        raise ValueError("Unterminated kernel version")
    version = data[marker:version_end].decode(errors="replace")
    if not re.match(r"^Linux version 6\.6\.30-android15-8(?:-|\s|$)", version):
        raise ValueError("Unexpected kernel release: " + version)
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "version": version, "config_gate": "passed", "boot_tested": False, "kpm_runtime_tested": False, "vendor_abi_verified": False, "flash_authorized": False}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    args = parser.parse_args()
    print(json.dumps(inspect(args.image), indent=2))
