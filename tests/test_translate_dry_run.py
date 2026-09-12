"""tools/ 三支腳本在純標準庫環境下的可執行性：translate --dry-run、fix_text --no-opencc、check_codes。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
DEMO = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "Game"
EXPORT = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "export_script.py"


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, "PYTHONUTF8": "1"}  # 子行程與解碼都走 UTF-8（Windows 主控台預設 cp950）
    if env:
        e.update(env)
    return subprocess.run([PY, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=e, cwd=REPO)


class ToolsStdlib(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="agt-test-tools-"))
        r = run(str(EXPORT), str(DEMO), "-o", str(cls.tmp))
        assert r.returncode == 0, r.stdout + r.stderr
        cls.script = cls.tmp / "script.json"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_translate_dry_run_without_galtransl(self):
        # GALTRANSL_ROOT 指到不存在的地方：dry-run 不該碰 GalTransl，也不該連線
        r = run("tools/translate.py", "-i", str(self.script), "--engine", "rpgmaker_mv_mz",
                "--dry-run", "--limit", "5", env={"GALTRANSL_ROOT": "/nonexistent/galtransl"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DRY-RUN", r.stdout)
        self.assertIn("實際送模型", r.stdout)
        self.assertFalse((self.tmp / ".galtransl").exists())

    def test_translate_refuses_legacy_checkpoint(self):
        legacy = self.tmp / ".script_checkpoint.json"
        legacy.write_text("{}", encoding="utf-8")
        try:
            r = run("tools/translate.py", "-i", str(self.script), "--engine", "rpgmaker_mv_mz", "--dry-run")
            self.assertEqual(r.returncode, 3)
            self.assertIn("舊式檢查點", r.stdout)
            r = run("tools/translate.py", "-i", str(self.script), "--engine", "rpgmaker_mv_mz",
                    "--dry-run", "--ignore-legacy-checkpoint")
            self.assertEqual(r.returncode, 0)
        finally:
            legacy.unlink()

    def test_check_codes_and_fix_text(self):
        data = json.loads(self.script.read_text(encoding="utf-8"))
        for e in data["strings"]:
            e["translated"] = e["original"]
        # 弄壞兩條：憑空多出帶值控制碼 \V[99]（extra value）、加字面 \n
        victims = [e for e in data["strings"] if e["context"] == "dialog"]
        self.assertTrue(victims)
        victims[0]["translated"] = "\\V[99]" + victims[0]["translated"]
        plain = next(e for e in data["strings"] if "\n" in e["original"] and "\\" not in e["original"])
        plain["translated"] = plain["original"].replace("\n", "\\n", 1)
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        r = run("tools/check_codes.py", str(bad), "--engine", "rpgmaker_mv_mz", "--json", str(self.tmp / "rep.json"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        rep = json.loads((self.tmp / "rep.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["fatal"], 2)

        r = run("tools/fix_text.py", str(bad), "--engine", "rpgmaker_mv_mz", "--no-opencc", "--no-backup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("退回", r.stdout)
        fixed = json.loads(bad.read_text(encoding="utf-8"))
        by_key = {(e["source_file"], e["location"]): e for e in fixed["strings"]}
        self.assertEqual(by_key[(victims[0]["source_file"], victims[0]["location"])]["translated"], "")
        self.assertEqual(by_key[(plain["source_file"], plain["location"])]["translated"], "")

        r = run("tools/check_codes.py", str(bad), "--engine", "rpgmaker_mv_mz")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
