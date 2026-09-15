"""core/config：config.yaml ← config.local.yaml ← 環境變數 的疊加順序、~ 展開、site／handoff_dir 預設。"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import config  # noqa: E402


class ConfigLayering(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agt-test-config-"))
        self.base = self.tmp / "config.yaml"
        self.local = self.tmp / "config.local.yaml"
        self.base.write_text("endpoint: http://base:1\nsite: full\nhandoff_dir: ~/base-dir\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _load(self):
        return config.load_config(self.base, self.local)

    def test_defaults_and_base(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("AGT_SITE", "AGT_HANDOFF_DIR", "AGT_ENDPOINT"):
                os.environ.pop(k, None)
            cfg = self._load()
        self.assertEqual(cfg["endpoint"], "http://base:1")
        self.assertEqual(cfg["site"], "full")
        self.assertEqual(cfg["handoff_dir"], os.path.expanduser("~/base-dir"))
        self.assertEqual(cfg["llama_port"], "8080")

    def test_local_overrides_base(self):
        self.local.write_text("site: workstation\nhandoff_dir: G:/My Drive/x   # 註解\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("AGT_SITE", "AGT_HANDOFF_DIR"):
                os.environ.pop(k, None)
            cfg = self._load()
        self.assertEqual(cfg["site"], "workstation")
        self.assertEqual(cfg["handoff_dir"], "G:/My Drive/x")
        self.assertEqual(cfg["endpoint"], "http://base:1")

    def test_env_overrides_local(self):
        self.local.write_text("site: workstation\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"AGT_SITE": "translator", "AGT_HANDOFF_DIR": "/tmp/h"}):
            cfg = self._load()
        self.assertEqual(cfg["site"], "translator")
        self.assertEqual(cfg["handoff_dir"], "/tmp/h")

    def test_defaults_without_files(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("AGT_SITE", "AGT_HANDOFF_DIR"):
                os.environ.pop(k, None)
            cfg = config.load_config(self.tmp / "none.yaml", self.tmp / "none.local.yaml")
        self.assertEqual(cfg["site"], "")
        self.assertEqual(cfg["handoff_dir"], "")

    def test_helpers(self):
        with mock.patch.object(config, "CONFIG_PATH", self.base), \
             mock.patch.object(config, "LOCAL_CONFIG_PATH", self.local), \
             mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(self.tmp), "AGT_SITE": "translator"}):
            self.assertEqual(config.site(), "translator")
            self.assertEqual(config.handoff_dir(), self.tmp)
            self.assertEqual(config.config_sources(), [self.base])
        with mock.patch.object(config, "CONFIG_PATH", self.base), \
             mock.patch.object(config, "LOCAL_CONFIG_PATH", self.local), \
             mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(self.tmp / "missing")}):
            self.assertIsNone(config.handoff_dir())

    def test_peer_agent_layering(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGT_PEER_AGENT", None)
            self.assertEqual(self._load()["peer_agent"], "")          # 沒設 → 空字串
            self.local.write_text("peer_agent: agt-translator\n", encoding="utf-8")
            self.assertEqual(self._load()["peer_agent"], "agt-translator")
        with mock.patch.dict(os.environ, {"AGT_PEER_AGENT": "agt-translator-2"}):
            self.assertEqual(self._load()["peer_agent"], "agt-translator-2")   # 名字過期時的逃生口
        with mock.patch.object(config, "CONFIG_PATH", self.base), \
             mock.patch.object(config, "LOCAL_CONFIG_PATH", self.local), \
             mock.patch.dict(os.environ, {"AGT_PEER_AGENT": "  spaced  "}):
            self.assertEqual(config.peer_agent(), "spaced")

    def test_example_keys_are_in_defaults(self):
        """範例檔裡註解掉的每個鍵都要在 DEFAULTS 裡。

        AGT_* 覆蓋是對「DEFAULTS ∪ 設定檔已有的鍵」做迴圈：新鍵漏了 DEFAULTS，
        使用者沒寫進設定檔時 AGT_<KEY> 會被靜默忽略。把這條坑釘成回歸測試。
        """
        text = (REPO / "config.local.example.yaml").read_text(encoding="utf-8")
        keys = set(re.findall(r"^#\s*([a-z_]+):", text, re.MULTILINE))
        self.assertTrue(keys, "範例檔裡找不到任何鍵，正則可能失效了")
        self.assertEqual(keys - set(config.DEFAULTS), set())


if __name__ == "__main__":
    unittest.main()
