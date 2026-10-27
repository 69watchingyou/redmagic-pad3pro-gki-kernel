import struct, tempfile, unittest
from pathlib import Path
from inspect_stock import inspect

class StockTests(unittest.TestCase):
    def check(self, b):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "boot.img"
            p.write_bytes(b)
            return inspect(p)
    def base(self):
        b = bytearray(4096)
        b[:8] = b"ANDROID!"
        struct.pack_into("<I", b, 20, 1584)
        struct.pack_into("<I", b, 40, 4)
        return b
    def test_valid_empty(self):
        self.assertEqual(self.check(self.base())["header_version"], 4)
    def test_short(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            self.check(b"ANDROID!")
    def test_bad_header(self):
        b = self.base()
        struct.pack_into("<I", b, 20, 0)
        with self.assertRaisesRegex(ValueError, "header size"):
            self.check(b)
    def test_payload_overflow(self):
        b = self.base()
        struct.pack_into("<I", b, 8, 1000000)
        with self.assertRaisesRegex(ValueError, "Payload"):
            self.check(b)
    def test_bad_footer(self):
        b = self.base()
        b[-64:-60] = b"AVBf"
        struct.pack_into(">IIQQQ", b, len(b)-60, 1, 0, 4096, 8192, 100)
        with self.assertRaisesRegex(ValueError, "AVB"):
            self.check(b)

if __name__ == "__main__":
    unittest.main()
