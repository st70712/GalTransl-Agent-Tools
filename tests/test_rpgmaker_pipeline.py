"""用 vendor/Game 示範語料跑完整關卡：prepare → export → roundtrip → 填譯文 → validate → import → verify → breakage → package。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import fsutil, registry, script_json, state  # noqa: E402
from core.adapter import Project  # noqa: E402

DEMO = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "Game"
fsutil.utf8_stdio()  # Windows 主控台 cp950：adapter 印 ✓／中文不能炸


class RpgMakerPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="agt-test-rpgmaker-"))
        cls.p = Project(cls.tmp / "demo")
        cls.p.ensure_dirs()
        fsutil.link_dir(DEMO.resolve(), cls.p.original)
        cls.ad = registry.get("rpgmaker_mv_mz")
        m = cls.ad.detect(cls.p.original)
        assert m is not None and m.variant == "MV", m
        state.set_engine(cls.p.state_path, m.to_dict())
        cls.m = m

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_00_detect_negative(self):
        self.assertIsNone(self.ad.detect(self.tmp))

    def test_01_prepare(self):
        self.assertTrue(self.ad.prepare(self.p, self.m))
        self.assertTrue((self.p.extracted / "www" / "data" / "System.json").exists())

    def test_02_export(self):
        r = self.ad.export(self.p)
        self.assertTrue(r, r.summary)
        data = script_json.load(self.p.script)
        self.assertEqual(data["info"]["string_count"], len(data["strings"]))
        self.assertGreater(len(data["strings"]), 100)
        side = script_json.load_sidecar(self.p.script)
        self.assertEqual(side["engine"], "rpgmaker_mv_mz")
        self.assertEqual(side["variant"], "MV")

    def test_03_roundtrip_zero_import(self):
        r = self.ad.roundtrip(self.p)
        self.assertTrue(r, r.summary)

    def test_04_fill_validate_import_verify(self):
        data = script_json.load(self.p.script)
        for e in data["strings"]:
            e["translated"] = e["original"]
        script_json.save(data, self.p.script)
        self.assertTrue(self.ad.validate(self.p, self.p.script))
        self.assertTrue(self.ad.import_(self.p, self.p.script))
        self.assertTrue((self.p.translated / "www" / "data" / "Map001.json").exists())
        self.assertTrue(self.ad.verify(self.p))

    def test_05_breakage_is_caught(self):
        r = self.ad.breakage_test(self.p)
        self.assertTrue(r, r.summary)

    def test_06_package(self):
        # 改一條譯文讓 translated 與 extracted 有差異
        data = script_json.load(self.p.script)
        data["strings"][0]["translated"] = "【測試譯文】"
        script_json.save(data, self.p.script)
        self.assertTrue(self.ad.import_(self.p, self.p.script))
        r = self.ad.package(self.p)
        self.assertTrue(r, r.summary)
        self.assertTrue((self.p.out / "安裝說明.txt").exists())
        delivered = list((self.p.out / "www" / "data").glob("*.json"))
        self.assertGreaterEqual(len(delivered), 1)
        for f in delivered:
            json.loads(f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
