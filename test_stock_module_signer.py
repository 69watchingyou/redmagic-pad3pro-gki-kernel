import base64
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
PIN = '46a87b2eeaf96989c0e9a59b5f26e133a1cdf984bac30f874a3266756f2974b3'

class StockSignerTests(unittest.TestCase):
    def test_pinned_public_certificate(self):
        pem = (ROOT / 'configs/stock-module-signing.pem').read_text()
        self.assertNotIn('PRIVATE KEY', pem)
        der = base64.b64decode(''.join(pem.splitlines()[1:-1]), validate=True)
        self.assertEqual(hashlib.sha256(der).hexdigest(), PIN)

    def test_build_keeps_protection_and_checks_trust(self):
        script = (ROOT / 'build_kernel_candidate.sh').read_text()
        self.assertIn(PIN, script)
        self.assertIn('--set-str SYSTEM_TRUSTED_KEYS "$stock_cert"', script)
        self.assertIn("'CONFIG_MODULE_SIG_PROTECT'", script)
        self.assertNotIn('--disable MODULE_SIG_PROTECT', script)
        self.assertLess(script.index('--set-str SYSTEM_TRUSTED_KEYS'), script.index('make "${make_args[@]}" olddefconfig'))

if __name__ == '__main__':
    unittest.main()
