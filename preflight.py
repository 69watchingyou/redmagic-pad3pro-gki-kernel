"""Report unresolved requirements. This is NOT a kernel compiler."""
import json, sys
from pathlib import Path

lock = json.loads((Path(__file__).parent / "source-lock.json").read_text())
print(json.dumps(lock, indent=2))
missing = []
if not lock["kernel"]["manifest_commit"]:
    missing.append("Verified stock manifest/toolchain pin is missing")
for key, value in lock["integration"].items():
    if not value:
        missing.append("Unverified integration: " + key)
if missing:
    for reason in missing:
        print("NOT BUILD READY: " + reason, file=sys.stderr)
    sys.exit(2)
raise SystemExit("Pins present; manual integration review still required. No compiler is invoked.")
