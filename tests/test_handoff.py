"""兩站接力：pack → unpack 往返、seq 拒收、agt.json 合併、logs 只增不刪、翻譯端骨架守門。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import handoff, script_json, state  # noqa: E402
from core.adapter import Project  # noqa: E402

PY = sys.executable
DEMO = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "Game"
EXPORT = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "export_script.py"


def _make_project(root: Path, name: str) -> Project:
    """用示範語料組一個「實機端」專案：original/ 指向示範遊戲，exported/ 有 script.json + sidecar。"""
    p = Project(root / name)
    p.ensure_dirs()
    shutil.copytree(DEMO, p.original)
    r = subprocess.run([PY, str(EXPORT), str(DEMO), "-o", str(p.exported)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    script_json.save_sidecar(p.script, {"engine": "rpgmaker_mv_mz", "variant": "MV",
                                        "source_encoding": "utf-8", "target_encoding": "utf-8"})
    state.set_engine(p.state_path, {"engine": "rpgmaker_mv_mz", "confidence": 1.0, "evidence": [],
                                    "variant": "MV", "source_encoding": "utf-8", "target_encoding": "utf-8",
                                    "extra": {"game_root": str(p.original)}})
    state.mark_gate(p.state_path, "prepare", True, "ok")
    (p.logs / "export-1.log").write_text("ws log", encoding="utf-8")
    (p.root / "glossary.txt").write_text("彼女->她\n", encoding="utf-8")
    (p.exported / "script.backup-20260101-000000.json").write_text("{}", encoding="utf-8")
    return p


class HandoffRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="agt-test-handoff-"))
        cls.ws_projects = cls.tmp / "ws"
        cls.tr_projects = cls.tmp / "tr"
        cls.ws = _make_project(cls.ws_projects, "demo")
        cls.repo_patch = mock.patch.object(handoff, "repo_info", lambda: {"head": "abc123", "dirty": False})
        cls.repo_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.repo_patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_01_pack_from_workstation(self):
        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""}):
            r = handoff.pack(self.ws, "translator", from_site="workstation")
        self.assertEqual(r.seq, 1)
        self.assertTrue(r.bundle.exists())
        self.assertIsNone(r.copied_to)
        self.assertTrue(any("HANDOFF.md" in w for w in r.warnings), r.warnings)
        with zipfile.ZipFile(r.bundle) as zf:
            names = set(zf.namelist())
            man = json.loads(zf.read(handoff.MANIFEST))
        for rel in handoff.REQUIRED:
            self.assertIn(rel, names)
        self.assertIn("HANDOFF.md", names)
        self.assertIn("glossary.txt", names)
        self.assertIn("logs/export-1.log", names)
        self.assertFalse(any("backup" in n for n in names))
        self.assertFalse(any(n.startswith("original/") for n in names))
        self.assertEqual(man["game"], "demo")
        self.assertEqual(man["seq"], 1)
        self.assertEqual(man["to_site"], "translator")
        self.assertEqual(man["engine"], "rpgmaker_mv_mz")
        self.assertIn("exported/script.json", man["files"])
        ho = state.handoff_info(self.ws.state_path)
        self.assertEqual((ho["seq"], ho["holder"]), (1, "translator"))
        type(self).bundle1 = r.bundle

    def test_02_classify(self):
        it = handoff.classify(self.bundle1)
        self.assertEqual(it.kind, "bundle_zip")
        self.assertEqual(it.manifest["game"], "demo")
        self.assertEqual(handoff.classify(self.bundle1.parent).kind, "bundle_pool")
        self.assertEqual(handoff.classify(DEMO).kind, "game_dir")
        self.assertEqual(handoff.classify(self.tmp / "nope").kind, "missing")
        gz = self.tmp / "game.zip"
        with zipfile.ZipFile(gz, "w") as zf:
            zf.writestr("Game/Data.wolf", b"DX")
        it = handoff.classify(gz)
        self.assertEqual(it.kind, "game_zip")
        self.assertTrue(any("WOLF" in h for h in it.hints))

    def test_03_unpack_on_translator_creates_skeleton(self):
        r = handoff.unpack(self.bundle1, self.tr_projects)
        p = r.project
        self.assertTrue(r.created)
        self.assertEqual(p.name, "demo")
        self.assertFalse(p.original.exists())
        self.assertTrue(p.script.exists())
        self.assertTrue((p.root / "glossary.txt").exists())
        self.assertTrue((p.logs / "export-1.log").exists())
        self.assertFalse((p.exported / "script.backup-20260101-000000.json").exists())
        self.assertEqual(state.handoff_info(p.state_path)["seq"], 1)
        self.assertTrue(state.gate_ok(p.state_path, "prepare"))
        self.assertTrue(any("original/" in w for w in r.warnings))
        type(self).tr = p

    def test_04_unpack_refuses_same_seq_unless_force(self):
        with self.assertRaises(handoff.HandoffError):
            handoff.unpack(self.bundle1, self.tr_projects)
        r = handoff.unpack(self.bundle1, self.tr_projects, force=True)
        self.assertEqual(r.seq, 1)
        self.assertTrue(any(b.name.startswith("script.backup-") for b in r.backups))

    def test_05_translator_edits_and_packs_back(self):
        data = script_json.load(self.tr.script)
        data["strings"][0]["translated"] = "測試譯文"
        script_json.save(data, self.tr.script)
        (self.tr.exported / ".agt_checkpoint.json").write_text('{"entries": {}}', encoding="utf-8")
        (self.tr.logs / "translate-1.log").write_text("tr log", encoding="utf-8")
        state.mark_gate(self.tr.state_path, "translate", True, "limit=20")
        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""}):
            r = handoff.pack(self.tr, "workstation", from_site="translator")
        self.assertEqual(r.seq, 2)
        type(self).bundle2 = r.bundle

    def test_06_unpack_back_on_workstation_merges(self):
        state.mark_gate(self.ws.state_path, "import", True, "ws import")
        (self.ws.logs / "export-1.log").write_text("ws log CHANGED", encoding="utf-8")
        r = handoff.unpack(self.bundle2, self.ws_projects)
        p = r.project
        self.assertEqual(p.root, self.ws.root)
        self.assertFalse(r.created)
        self.assertEqual(script_json.load(p.script)["strings"][0]["translated"], "測試譯文")
        self.assertTrue((p.exported / ".agt_checkpoint.json").exists())
        self.assertTrue(any(b.name.startswith("script.backup-") for b in r.backups))
        self.assertTrue(any(b.name.startswith("agt.backup-") for b in r.backups))
        st = state.load_state(p.state_path)
        self.assertTrue(st["gates"]["translate"]["ok"])       # 翻譯端的關卡進來了
        self.assertTrue(st["gates"]["import"]["ok"])          # 實機端自己的關卡沒被蓋掉
        self.assertEqual(st["handoff"]["seq"], 2)
        self.assertEqual(st["handoff"]["holder"], "workstation")
        self.assertEqual((p.logs / "export-1.log").read_text(encoding="utf-8"), "ws log CHANGED")  # logs 不覆蓋
        self.assertTrue((p.logs / "translate-1.log").exists())                                   # 新 log 進來
        self.assertTrue(p.original.exists())

    def test_07_unpack_from_pool_and_game_rename_warning(self):
        pool = self.tmp / "pool"
        pool.mkdir()
        shutil.copy2(self.bundle1, pool / self.bundle1.name)
        shutil.copy2(self.bundle2, pool / self.bundle2.name)
        other = self.tmp / "other"
        r = handoff.unpack(pool, other, game="renamed", site="workstation")
        self.assertEqual(r.seq, 2)
        self.assertEqual(r.project.name, "renamed")
        self.assertTrue(any("專案名" in w for w in r.warnings))

    def test_08_repo_mismatch_warning(self):
        with mock.patch.object(handoff, "repo_info", lambda: {"head": "fff999", "dirty": False}):
            r = handoff.unpack(self.bundle2, self.tmp / "third")
        self.assertTrue(any("repo 不同步" in w for w in r.warnings), r.warnings)

    def test_09_pack_refuses_dirty_repo(self):
        with mock.patch.object(handoff, "repo_info", lambda: {"head": "abc", "dirty": True}):
            with self.assertRaises(handoff.HandoffError):
                handoff.pack(self.ws, "translator", from_site="workstation")
            with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""}):
                r = handoff.pack(self.ws, "translator", from_site="workstation", allow_dirty=True)
        self.assertEqual(r.seq, 3)

    def test_10_pack_copies_to_handoff_dir(self):
        shared = self.tmp / "shared"
        shared.mkdir()
        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(shared)}):
            r = handoff.pack(self.ws, "translator", from_site="workstation")
        self.assertIsNotNone(r.copied_to)
        self.assertTrue(r.copied_to.exists())
        self.assertEqual(r.copied_to.parent, shared / "demo" / "handoff")


class MergeStates(unittest.TestCase):
    def test_merge_prefers_newer_gate_and_unions_history(self):
        local = {"engine": {"engine": "x"}, "gates": {"a": {"ok": True, "at": "2026-01-01 10:00:00", "summary": "L"},
                                                     "b": {"ok": False, "at": "2026-01-01 09:00:00", "summary": "L"}},
                 "history": [{"gate": "a", "ok": True, "at": "2026-01-01 10:00:00", "summary": "L"}]}
        incoming = {"engine": {"engine": "x"}, "gates": {"b": {"ok": True, "at": "2026-01-02 09:00:00", "summary": "I"},
                                                        "c": {"ok": True, "at": "2026-01-02 09:30:00", "summary": "I"}},
                    "history": [{"gate": "b", "ok": True, "at": "2026-01-02 09:00:00", "summary": "I"},
                                {"gate": "a", "ok": True, "at": "2026-01-01 10:00:00", "summary": "L"}],
                    "handoff": {"seq": 2, "holder": "workstation"}}
        m = state.merge_states(local, incoming)
        self.assertEqual(m["gates"]["a"]["summary"], "L")
        self.assertEqual(m["gates"]["b"]["summary"], "I")
        self.assertEqual(m["gates"]["c"]["summary"], "I")
        self.assertEqual(len(m["history"]), 2)
        self.assertEqual(m["handoff"]["seq"], 2)


class AgtCli(unittest.TestCase):
    """agt.py detect 對交接包的來料判斷、翻譯端骨架專案的守門（子行程，PROJECTS_DIR 改到 tmp）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="agt-test-cli-"))
        cls.ws = _make_project(cls.tmp / "ws", "demo")
        with mock.patch.object(handoff, "repo_info", lambda: {"head": "abc", "dirty": False}), \
             mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""}):
            cls.bundle = handoff.pack(cls.ws, "translator", from_site="workstation").bundle
        cls.tr = handoff.unpack(cls.bundle, cls.tmp / "tr").project

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _agt(self, *args: str) -> subprocess.CompletedProcess:
        code = (f"import sys; sys.path.insert(0, {str(REPO)!r}); import core; from pathlib import Path; "
                f"core.PROJECTS_DIR = Path({str(self.tmp / 'tr')!r}); import core.adapter as A; "
                f"A.PROJECTS_DIR = core.PROJECTS_DIR; import agt; sys.exit(agt.main({list(args)!r}))")
        env = {**os.environ, "AGT_SITE": "translator", "AGT_HANDOFF_DIR": ""}
        return subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=REPO, env=env)

    def test_detect_bundle(self):
        r = self._agt("detect", str(self.bundle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("交接包", r.stdout)
        self.assertIn("handoff unpack", r.stdout)

    def test_detect_pool(self):
        r = self._agt("detect", str(self.bundle.parent))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("交接包", r.stdout)

    def test_import_refused_without_original(self):
        r = self._agt("import", "demo")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("實機端", r.stdout + r.stderr)

    def test_check_codes_and_validate_allowed(self):
        r = self._agt("check-codes", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self._agt("status", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("交接: #1", r.stdout)

    def test_env(self):
        r = self._agt("env")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("站點: translator", r.stdout)
        r = self._agt("env", "--json")
        self.assertEqual(json.loads(r.stdout)["site"], "translator")


if __name__ == "__main__":
    unittest.main()
