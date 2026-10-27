"""Regression guards for exact-source VMA patch adaptation, not compiler substitutes."""
from pathlib import Path
import unittest

class PatchRegressionTests(unittest.TestCase):
    def test_older_vma_flow(self):
        patch = Path(__file__).with_name("patches").joinpath("susfs-sukisu-6.6.30.patch").read_text()
        section = patch.split("diff --git a/fs/proc/task_mmu.c", 1)[1].split("diff --git", 1)[0]
        additions = "\n".join(line[1:] for line in section.splitlines() if line.startswith("+") and not line.startswith("+++"))
        self.assertNotIn("__fold_filemap_fixup_entry", additions)
        self.assertNotIn("end = VMA_PAD_START(vma)", additions)
        self.assertIn("end = vma->vm_end;", additions)
        self.assertLess(additions.index("if (flags & __VM_NO_COMPAT)"), additions.index("if (SUSFS_IS_INODE_OPEN_REDIRECT"))

if __name__ == "__main__":
    unittest.main()
