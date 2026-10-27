import unittest
from check_vendor_abi import same_magic, parse_symvers, compare


class AbiTests(unittest.TestCase):
    def requirements(self):
        return {"modules": {"a.ko": {"has_crcs": True, "vermagic": "stock-dirty SMP preempt modversions aarch64", "imports": {"module_layout": "0x1234", "foo": "0xabcd"}}}}

    def test_modversions_ignores_release(self):
        self.assertTrue(same_magic("stock-dirty SMP preempt", "new-release SMP preempt", True))
        self.assertFalse(same_magic("stock-dirty SMP preempt", "new-release SMP preempt", False))

    def test_modversions_preserves_config_suffix(self):
        self.assertFalse(same_magic("a SMP preempt", "a SMP", True))
        self.assertFalse(same_magic("a  SMP", "a SMP", True))

    def test_loader_no_space_case(self):
        self.assertTrue(same_magic("a", "b", True))

    def test_pass_is_not_compatibility_certification(self):
        rows = parse_symvers("0x1234 module_layout vmlinux EXPORT_SYMBOL\n0xabcd foo vendor_mod EXPORT_SYMBOL_GPL")
        result = compare(self.requirements(), rows, "new SMP preempt modversions aarch64")
        self.assertTrue(result["offline_crc_and_vermagic_gate_passed"])
        self.assertFalse(result["vendor_abi_verified"])
        self.assertFalse(result["runtime_verified"])

    def test_missing(self):
        result = compare(self.requirements(), {}, "new SMP preempt modversions aarch64")
        self.assertEqual(result["findings"]["a.ko"]["missing"], ["module_layout", "foo"])

    def test_mismatch(self):
        rows = parse_symvers("0x1234 module_layout vmlinux EXPORT_SYMBOL\n0xffff foo vmlinux EXPORT_SYMBOL")
        result = compare(self.requirements(), rows, "new SMP preempt modversions aarch64")
        self.assertEqual(result["findings"]["a.ko"]["mismatch"][0]["symbol"], "foo")

    def test_conflicting_rows_rejected(self):
        with self.assertRaises(ValueError):
            parse_symvers("0x1234 foo vmlinux EXPORT_SYMBOL\n0x5678 foo vmlinux EXPORT_SYMBOL")

    def test_bad_rows_rejected(self):
        with self.assertRaises(ValueError):
            parse_symvers("0x1234 foo")

    def test_full_vermagic_required(self):
        with self.assertRaises(ValueError):
            compare(self.requirements(), {}, "6.6.30")

    def test_empty_requirements_not_pass(self):
        self.assertFalse(compare({"modules": {}}, {}, "6.6 SMP")["offline_crc_and_vermagic_gate_passed"])


if __name__ == "__main__":
    unittest.main()
