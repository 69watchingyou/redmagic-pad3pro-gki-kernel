"""Compare offline vendor module requirements with candidate Module.symvers, never prove bootability."""
import argparse
import json
from pathlib import Path


def same_magic(module_magic, kernel_magic, has_crcs):
    # Exact kernel/module/version.c same_magic: skip through FIRST SPACE, not split whitespace.
    if has_crcs:
        module_magic = module_magic[module_magic.find(" "):] if " " in module_magic else ""
        kernel_magic = kernel_magic[kernel_magic.find(" "):] if " " in kernel_magic else ""
    return module_magic == kernel_magic


def parse_symvers(text):
    symbols = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 4:
            raise ValueError("Malformed Module.symvers row " + str(number))
        crc, name, provider, export = fields[:4]
        value = int(crc, 16)
        if not 0 <= value <= 0xffffffff:
            raise ValueError("CRC outside 32 bits")
        item = {"crc": value, "provider": provider, "export": export,
                "namespace": fields[4] if len(fields) > 4 else ""}
        if name in symbols and symbols[name] != item:
            raise ValueError("Conflicting symbol rows: " + name)
        symbols[name] = item
    return symbols


def compare(requirements, symvers, candidate_vermagic):
    if not candidate_vermagic or " " not in candidate_vermagic:
        raise ValueError("Complete candidate vermagic (not uname -r) required")
    failures = {}
    count = 0
    for name, module in requirements["modules"].items():
        count += 1
        issue = {"missing": [], "mismatch": [], "vermagic_match": same_magic(
            module["vermagic"], candidate_vermagic, module["has_crcs"])}
        for symbol, required in module["imports"].items():
            value = int(required, 16)
            if symbol not in symvers:
                issue["missing"].append(symbol)
            elif symvers[symbol]["crc"] != value:
                issue["mismatch"].append({"symbol": symbol, "required": f"0x{value:08x}",
                                          "candidate": f"0x{symvers[symbol]['crc']:08x}",
                                          "provider": symvers[symbol]["provider"]})
        if issue["missing"] or issue["mismatch"] or not issue["vermagic_match"]:
            failures[name] = issue
    return {"module_count": count, "modules_with_findings": len(failures), "findings": failures,
            "scope": requirements.get("scope", "unspecified"), "candidate_vermagic": candidate_vermagic,
            "offline_crc_and_vermagic_gate_passed": not failures and count > 0,
            "vendor_abi_verified": False, "runtime_verified": False, "flash_authorized": False,
            "limitations": ["Missing symbols may be exported by unchanged vendor modules omitted from candidate symvers; unresolved, not proof of kernel incompatibility.",
                            "CRC equality does not prove semantic ABI, layout, signature, namespace/license, CFI, or runtime safety.",
                            "Snapshot excludes modules outside documented scope; collect vendor_dlkm/system_dlkm for complete inventory."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--symvers", action="append", required=True)
    parser.add_argument("--candidate-vermagic", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    requirements = json.loads(Path(args.requirements).read_text(encoding="utf-8"))
    symbols = parse_symvers("\n".join(Path(p).read_text(encoding="utf-8") for p in args.symvers))
    report = compare(requirements, symbols, args.candidate_vermagic)
    output = Path(args.report)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print("Checked", report["module_count"], "modules; modules with findings:", report["modules_with_findings"])
    raise SystemExit(0 if report["offline_crc_and_vermagic_gate_passed"] else 1)


if __name__ == "__main__":
    main()
