import gzip
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from postprocess_kpm import postprocess, metadata
from verify_artifact import REQUIRED

KP = "[kpimg]\nversion=0xe00\ncompile_time=test\nconfig=android,release\narch=arm64\nsuperkey=<redacted>\nroot_superkey=<redacted>\n[additional]\n"
LISTING = "[kernel]\nbanner=Linux version 6.6.30-android15-8-test\npatched=true\n" + KP


class PostprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "Image"
        b = bytearray(64)
        b[56:60] = b"ARM\x64"
        struct.pack_into("<Q", b, 24, 2)
        self.image.write_bytes(bytes(b) + b"Linux version 6.6.30-android15-8-test\0IKCFG_ST" + gzip.compress("\n".join(REQUIRED).encode()) + b"IKCFG_ED")
        self.payload, self.tool, self.output = (self.root / n for n in ("kpimg", "kptools", "Image.kp"))
        self.payload.write_bytes(b"payload")
        self.tool.write_bytes(b"not executable: mocked only")
        self.original = self.image.read_bytes()
        self.calls = []

    def fake(self, args, **kwargs):
        self.assertTrue(kwargs["check"])
        self.calls.append(args)
        if "-p" in args:
            self.assertEqual(args[-2:], ["--skey-fd", "0"])
            secret = kwargs["stdin"].read()
            self.assertEqual(len(secret.strip()), 48)
            self.assertFalse(any(secret.strip().decode() in a for a in args))
            Path(args[args.index("-o") + 1]).write_bytes(self.original + b"patched")
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return subprocess.CompletedProcess(args, 0, LISTING if "-i" in args else KP, "")

    def run_case(self, fake=None):
        with patch("postprocess_kpm.subprocess.run", side_effect=fake or self.fake):
            return postprocess(self.image, self.payload, self.tool, self.output)

    def assert_no_output(self):
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name("Image.kp.report.json").exists())
        self.assertEqual(self.image.read_bytes(), self.original)

    def test_success_report_and_original_preserved(self):
        report = self.run_case()
        self.assertEqual(self.image.read_bytes(), self.original)
        self.assertNotEqual(report["before"]["sha256"], report["after"]["sha256"])
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["bridge_abi_verified"])
        self.assertFalse(report["flash_authorized"])
        saved = json.loads(self.output.with_name("Image.kp.report.json").read_text())
        self.assertEqual(saved["expected_bridge_abi"], 2)
        self.assertEqual(len(self.calls), 3)

    def test_existing_output_not_overwritten(self):
        self.output.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.assertEqual(self.output.read_bytes(), b"preserve")
        self.assertFalse(self.calls)

    def test_existing_report_not_overwritten(self):
        self.output.with_name("Image.kp.report.json").write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.assertFalse(self.output.exists())

    def test_input_alias_rejected(self):
        with patch("postprocess_kpm.subprocess.run") as mock:
            with self.assertRaises(ValueError):
                postprocess(self.image, self.payload, self.tool, self.image)
            mock.assert_not_called()
        self.assertEqual(self.image.read_bytes(), self.original)

    def test_missing_parent_rejected(self):
        with self.assertRaises(ValueError):
            postprocess(self.image, self.payload, self.tool, self.root / "missing" / "Image")

    def test_patch_failure_propagates(self):
        def fake(args, **kwargs):
            if "-p" in args:
                raise subprocess.CalledProcessError(3, args)
            return self.fake(args, **kwargs)
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_case(fake)
        self.assert_no_output()

    def test_listing_failure_propagates(self):
        def fake(args, **kwargs):
            if "-i" in args and "-l" in args:
                raise subprocess.CalledProcessError(4, args)
            return self.fake(args, **kwargs)
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_case(fake)
        self.assert_no_output()

    def test_no_patched_metadata_rejected(self):
        def fake(args, **kwargs):
            result = self.fake(args, **kwargs)
            if "-l" in args and "-i" in args:
                result.stdout = LISTING.replace("patched=true", "patched=false")
            return result
        with self.assertRaises(ValueError):
            self.run_case(fake)
        self.assert_no_output()

    def test_secret_metadata_rejected(self):
        with self.assertRaises(ValueError):
            metadata(KP.replace("superkey=<redacted>", "superkey=123"))

    def test_missing_metadata_rejected(self):
        with self.assertRaises(ValueError):
            metadata("[kernel]\npatched=true\n")

    def test_wrong_payload_version_rejected(self):
        with self.assertRaises(ValueError):
            metadata(KP.replace("version=0xe00", "version=0xd05"))

    def test_report_publish_failure_removes_output(self):
        import os
        real_link = os.link
        def link(source, destination):
            if str(destination).endswith(".report.json"):
                raise OSError("mock report publish failure")
            return real_link(source, destination)
        with patch("postprocess_kpm.os.link", side_effect=link):
            with self.assertRaises(OSError):
                self.run_case()
        self.assert_no_output()

    def test_wrong_arch_rejected(self):
        with self.assertRaises(ValueError):
            metadata(KP.replace("arch=arm64", "arch=x86_64"))

    def test_no_change_rejected(self):
        def fake(args, **kwargs):
            result = self.fake(args, **kwargs)
            if "-p" in args:
                Path(args[args.index("-o") + 1]).write_bytes(self.original)
            return result
        with self.assertRaises(ValueError):
            self.run_case(fake)
        self.assert_no_output()


if __name__ == "__main__":
    unittest.main()
