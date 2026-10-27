import gzip, importlib.util, struct, tempfile, unittest
from pathlib import Path
from verify_artifact import inspect, REQUIRED

class VerifyTests(unittest.TestCase):
    def image(self, config=None, flags=2, version=b"Linux version 6.6.30-android15-8-test"):
        b = bytearray(64)
        b[56:60] = b"ARM\x64"
        struct.pack_into("<Q", b, 24, flags)
        return bytes(b) + version + b"\0IKCFG_ST" + gzip.compress((config if config is not None else "\n".join(REQUIRED)).encode()) + b"IKCFG_ED"
    def check(self, data):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Image"
            p.write_bytes(data)
            return inspect(p)
    def test_complete(self):
        self.assertEqual(self.check(self.image())["config_gate"], "passed")
    def test_missing_kpm(self):
        with self.assertRaisesRegex(ValueError, "CONFIG_KPM=y"):
            self.check(self.image(config="\n".join(x for x in REQUIRED if x != "CONFIG_KPM=y")))
    def test_wrong_pages(self):
        with self.assertRaisesRegex(ValueError, "4K"):
            self.check(self.image(flags=4))
    def test_wrong_release(self):
        with self.assertRaisesRegex(ValueError, "release"):
            self.check(self.image(version=b"Linux version 6.6.98-android15-8"))
    def test_boot_rejected(self):
        with self.assertRaisesRegex(ValueError, "raw Image"):
            self.check(b"ANDROID!" + bytes(64))

if __name__ == "__main__":
    unittest.main()
