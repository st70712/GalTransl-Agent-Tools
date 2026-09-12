"""core/fsutil：venv 直譯器路徑、目錄連結（symlink／junction）、replace_dir_with_link 的拒絕規則。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import fsutil  # noqa: E402


class VenvPython(unittest.TestCase):
    def test_posix_layout(self):
        self.assertEqual(fsutil.venv_python(Path("/x/.venv"), "posix"), Path("/x/.venv/bin/python"))

    def test_windows_layout(self):
        self.assertEqual(fsutil.venv_python(Path("/x/.venv"), "nt"), Path("/x/.venv/Scripts/python.exe"))

    def test_default_follows_os(self):
        self.assertEqual(fsutil.venv_python(Path("/x/.venv")), fsutil.venv_python(Path("/x/.venv"), os.name))


class LinkDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agt-test-fsutil-"))
        self.target = self.tmp / "target"
        self.target.mkdir()
        (self.target / "a.txt").write_text("a", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_link_is_link_remove(self):
        link = self.tmp / "link"
        kind = fsutil.link_dir(self.target, link)
        self.assertIn(kind, ("symlink", "junction"))
        self.assertTrue(fsutil.is_link(link))
        self.assertTrue((link / "a.txt").exists())
        fsutil.remove_link(link)
        self.assertFalse(link.exists())
        self.assertTrue((self.target / "a.txt").exists(), "移除連結不得動到目標")

    def test_replace_existing_link(self):
        link = self.tmp / "link"
        other = self.tmp / "other"
        other.mkdir()
        fsutil.link_dir(other, link)
        fsutil.replace_dir_with_link(self.target, link, rmtree_ok=False)
        self.assertTrue((link / "a.txt").exists())

    def test_replace_refuses_non_empty_dir(self):
        link = self.tmp / "real"
        link.mkdir()
        (link / "keep").write_text("x", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            fsutil.replace_dir_with_link(self.target, link, rmtree_ok=False)
        self.assertTrue((link / "keep").exists())
        fsutil.replace_dir_with_link(self.target, link, rmtree_ok=True)
        self.assertTrue(fsutil.is_link(link))

    def test_replace_empty_dir(self):
        link = self.tmp / "empty"
        link.mkdir()
        fsutil.replace_dir_with_link(self.target, link, rmtree_ok=False)
        self.assertTrue(fsutil.is_link(link))

    def test_is_link_false_for_plain(self):
        self.assertFalse(fsutil.is_link(self.target))
        self.assertFalse(fsutil.is_link(self.tmp / "nope"))


if __name__ == "__main__":
    unittest.main()
