"""Stage an experimental KPM Image; never authorizes flashing or proves runtime ABI."""
import argparse
import configparser
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from verify_artifact import inspect


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata(text, *, patched=False):
    """Parse actual tools/patch.c print_preset_info output, not invented ABI fields."""
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_file(io.StringIO(text))
    if not parser.has_section("kpimg"):
        raise ValueError("Missing [kpimg] metadata")
    kp = parser["kpimg"]
    if kp.get("arch") != "arm64" or kp.get("config", "").split(",")[0] != "android":
        raise ValueError("Expected Android ARM64 KP payload")
    if int(kp.get("version", "0"), 0) != 0xE00:
        raise ValueError("Expected audited KP version 0.14.0")
    for name in ("superkey", "root_superkey"):
        if kp.get(name) != "<redacted>":
            raise ValueError("KP metadata secrets are not redacted")
    if patched:
        if not parser.has_section("kernel") or parser["kernel"].get("patched") != "true":
            raise ValueError("Output metadata does not confirm patched=true")
        if not parser["kernel"].get("banner", "").startswith("Linux version 6.6.30-android15-8"):
            raise ValueError("Output metadata kernel baseline mismatch")
    return {"version": kp["version"], "arch": kp["arch"], "config": kp["config"]}


def postprocess(image, kpimg, kptools, output):
    image, kpimg, kptools = (Path(p).resolve(strict=True) for p in (image, kpimg, kptools))
    output = Path(output).absolute()
    if not output.parent.is_dir():
        raise ValueError("Output parent must already exist")
    output = output.parent.resolve() / output.name
    report_path = output.with_name(output.name + ".report.json")
    for path in (image, kpimg, kptools):
        if not path.is_file():
            raise ValueError("Inputs must be regular files")
        if output == path or report_path == path:
            raise ValueError("Output must not alias an input")
    for path in (output, report_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError("Refusing to overwrite existing output or report")
    before = inspect(image)
    hashes = {"input": sha256(image), "kpimg": sha256(kpimg), "kptools": sha256(kptools)}
    owned = []
    try:
        with tempfile.TemporaryDirectory(prefix="kpm-stage-", dir=output.parent) as directory:
            work = Path(directory)
            staged_input, staged_payload = work / "Image.before", work / "kpimg"
            staged_output = work / "Image.after"
            shutil.copyfile(image, staged_input)
            shutil.copyfile(kpimg, staged_payload)
            # stdin is an anonymous protected temporary file, not an argv secret.
            # TemporaryFile is mode 0600 on POSIX and closed on every exit path.
            key = secrets.token_hex(24).encode("ascii")
            payload_info = subprocess.run([str(kptools), "-l", "-k", str(staged_payload)], check=True,
                                          capture_output=True, text=True)
            metadata(payload_info.stdout)
            with tempfile.TemporaryFile(mode="w+b") as secret:
                if os.name == "posix":
                    os.fchmod(secret.fileno(), 0o600)
                secret.write(key + b"\n")
                secret.seek(0)
                subprocess.run([str(kptools), "-p", "-i", str(staged_input), "-k", str(staged_payload),
                                "-o", str(staged_output), "--skey-fd", "0"], stdin=secret,
                               check=True, capture_output=True)
            after = inspect(staged_output)
            if sha256(staged_input) != hashes["input"]:
                raise ValueError("Tool modified staged input")
            if after["sha256"] == before["sha256"]:
                raise ValueError("Postprocessor did not change Image")
            result = subprocess.run([str(kptools), "-l", "-i", str(staged_output)], check=True,
                                    capture_output=True, text=True)
            # Never retain raw text if it contains the temporary key.
            if key.decode() in result.stdout:
                raise ValueError("Tool disclosed key in metadata")
            parsed = metadata(result.stdout, patched=True)
            if parsed != metadata(payload_info.stdout):
                raise ValueError("Patched payload metadata differs from supplied kpimg")
            if before["config_sha256"] != after["config_sha256"]:
                raise ValueError("Postprocessor changed embedded kernel config")
            if before["version"] != after["version"]:
                raise ValueError("Postprocessor changed kernel release")
            for path, name in ((image, "input"), (kpimg, "kpimg"), (kptools, "kptools")):
                if sha256(path) != hashes[name]:
                    raise ValueError("Original input changed during processing")
            report = {"before": before, "after": after, "component_sha256": hashes,
                      "kp_metadata": parsed, "kp_metadata_text": result.stdout,
                      "expected_bridge_abi": 2, "bridge_abi_verified": False,
                      "runtime_verified": False, "flash_authorized": False,
                      "note": "KP listing has no bridge ABI field; metadata does not prove ABI2 or runtime support."}
            staged_report = work / "report.json"
            staged_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            # Same-filesystem hard links publish exclusively; no replace/overwrite race.
            os.link(staged_output, output)
            owned.append(output)
            os.link(staged_report, report_path)
            owned.append(report_path)
        return report
    except BaseException:
        for path in reversed(owned):
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "kpimg", "kptools", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        postprocess(args.image, args.kpimg, args.kptools, args.output)
    except (OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
        # Tool output and command lines are deliberately not printed on failure.
        parser.exit(1, "KPM postprocess failed (" + type(error).__name__ + "); no artifact accepted.\n")
    print("Experimental Image and report created; runtime/bridge ABI NOT verified; do not flash automatically.")


if __name__ == "__main__":
    main()
