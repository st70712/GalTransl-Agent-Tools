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

from core import fsutil, handoff, script_json, state  # noqa: E402
from core.adapter import Project  # noqa: E402

fsutil.utf8_stdio()  # Windows 主控台 cp950：adapter 印 ✓／中文不能炸
PY = sys.executable
UTF8 = {"text": True, "encoding": "utf-8", "errors": "replace"}  # 子行程輸出一律 UTF-8 解碼
DEMO = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "Game"
EXPORT = REPO / "engines" / "rpgmaker_mv_mz" / "vendor" / "export_script.py"


def _make_project(root: Path, name: str) -> Project:
    """用示範語料組一個「實機端」專案：original/ 指向示範遊戲，exported/ 有 script.json + sidecar。"""
    p = Project(root / name)
    p.ensure_dirs()
    shutil.copytree(DEMO, p.original)
    r = subprocess.run([PY, str(EXPORT), str(DEMO), "-o", str(p.exported)], capture_output=True,
                       env={**os.environ, "PYTHONUTF8": "1"}, **UTF8)
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
        # 當層沒有就往下找一層：pack 是複製到 <handoff_dir>/<game>/handoff/，
        # 使用者通常指到 <handoff_dir>/<game>（CLAUDE.md 第 6 節）
        drive = self.tmp / "drive" / "demo"
        (drive / "handoff").mkdir(parents=True)
        shutil.copy2(self.bundle1, drive / "handoff" / self.bundle1.name)
        it = handoff.classify(drive)
        self.assertEqual(it.kind, "bundle_pool")
        self.assertEqual([c.name for c in it.candidates], [self.bundle1.name])
        # 目錄本身就是交接包／專案時，仍然優先當它自己，不去掃子目錄
        self.assertEqual(handoff.classify(self.bundle1.parent.parent).kind, "bundle_dir")
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

    def test_11_pack_records_bundle_digest(self):
        shared = self.tmp / "shared11"
        shared.mkdir()
        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(shared)}):
            r = handoff.pack(self.ws, "translator", from_site="workstation")
        self.assertEqual(r.size, r.bundle.stat().st_size)
        self.assertEqual(r.sha256, fsutil.sha256_file(r.bundle))
        self.assertTrue(r.copy_verified)
        self.assertIsNotNone(r.sidecar)
        self.assertEqual(r.sidecar.read_text(encoding="utf-8"), f"{r.sha256}  {r.bundle.name}\n")
        # 整包 digest 只能活在 zip 外面：記進本機 agt.json 讓 notify 之後還拿得到
        info = state.handoff_info(self.ws.state_path)
        self.assertEqual((info["bundle_sha256"], info["bundle_size"]), (r.sha256, r.size))

    def test_12_pack_detects_bad_drive_copy(self):
        shared = self.tmp / "shared12"
        shared.mkdir()

        def half_copy(src, dst, *a, **kw):          # Drive 只寫進去一半
            Path(dst).write_bytes(Path(src).read_bytes()[:100])
            return dst

        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(shared)}), \
             mock.patch.object(handoff.shutil, "copy2", half_copy):
            r = handoff.pack(self.ws, "translator", from_site="workstation")
        self.assertFalse(r.copy_verified)           # pack 不拋例外，只回報
        self.assertIsNone(r.sidecar)                # 驗不過就不寫旁檔，免得對方以為可以收
        self.assertTrue(any("與本機不符" in w for w in r.warnings), r.warnings)

    def test_13_pack_survives_copy_oserror(self):
        shared = self.tmp / "shared13"
        shared.mkdir()

        def boom(*a, **kw):
            raise OSError("磁碟已滿")

        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(shared)}), \
             mock.patch.object(handoff.shutil, "copy2", boom):
            r = handoff.pack(self.ws, "translator", from_site="workstation")
        # seq 已經消耗掉了，複製失敗絕不能拋例外（否則使用者重跑會跳號）
        self.assertTrue(r.bundle.exists())
        self.assertIsNone(r.copied_to)
        self.assertTrue(any("請手動搬" in w for w in r.warnings), r.warnings)


class MergeStates(unittest.TestCase):
    def test_pick_latest_one_level_down_and_shallow_wins(self):
        tmp = Path(tempfile.mkdtemp(prefix="agt-test-pick-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "handoff").mkdir()
        deep = tmp / "handoff" / "demo-003-to-translator-20260101-0101.zip"
        deep.write_bytes(b"x")
        # 當層沒有 → 往下一層找到
        self.assertEqual([f.name for f in handoff.pick_latest(tmp)], [deep.name])
        # to_site 過濾在下一層也要生效
        self.assertEqual(handoff.pick_latest(tmp, "workstation"), [])
        self.assertEqual([f.name for f in handoff.pick_latest(tmp, "translator")], [deep.name])
        # 當層有就只看當層，不再往下（避免撈到舊的）
        shallow = tmp / "demo-002-to-translator-20260101-0202.zip"
        shallow.write_bytes(b"x")
        self.assertEqual([f.name for f in handoff.pick_latest(tmp)], [shallow.name])
        # 檔名不合規的 zip 不算交接包
        other = Path(tempfile.mkdtemp(prefix="agt-test-pick2-"))
        self.addCleanup(shutil.rmtree, other, True)
        (other / "sub").mkdir()
        (other / "sub" / "random.zip").write_bytes(b"x")
        self.assertEqual(handoff.pick_latest(other), [])

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


def _rewrite_zip(src: Path, dst: Path, changes: dict[str, bytes]) -> Path:
    """複製一個 zip，換掉指定成員的內容（manifest 不動 → 模擬「內容與 manifest 對不上」）。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            zout.writestr(name, changes.get(name, zin.read(name)))
    return dst


class BundleIntegrity(unittest.TestCase):
    """Drive／rclone 半同步的防線：整包 digest、成員 pre-flight、--force 不得略過完整性。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="agt-test-integrity-"))
        cls.ws = _make_project(cls.tmp / "ws", "demo")
        with mock.patch.object(handoff, "repo_info", lambda: {"head": "abc", "dirty": False}), \
             mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""}):
            cls.packed = handoff.pack(cls.ws, "translator", from_site="workstation")
        cls.bundle = cls.packed.bundle
        cls.tr_projects = cls.tmp / "tr"
        cls.tr = handoff.unpack(cls.bundle, cls.tr_projects).project

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_check_ok(self):
        c = handoff.check_bundle(self.bundle)
        self.assertTrue(c.ok, c.problems)
        self.assertEqual((c.digest.size, c.digest.sha256), (self.packed.size, self.packed.sha256))

    def test_check_expect_mismatch_says_not_same_bundle(self):
        c = handoff.check_bundle(self.bundle, expect_sha256="0" * 64, expect_size=self.packed.size)
        self.assertFalse(c.ok)
        self.assertTrue(any("不是同一包" in q for q in c.problems), c.problems)
        msg = handoff.integrity_message(self.bundle, c.problems, 1)
        self.assertIn("--force", msg)          # 訊息要主動把人推離 --force
        self.assertIn("晚點再收", msg)          # 並直接寫好該回報對方的話

    def test_check_expect_smaller_says_still_transferring(self):
        c = handoff.check_bundle(self.bundle, expect_size=self.packed.size + 10_000)
        self.assertFalse(c.ok)
        self.assertTrue(any("還在傳" in q for q in c.problems), c.problems)

    def test_truncated_zip_reads_as_sync_error(self):
        half = self.tmp / "half.zip"
        half.write_bytes(self.bundle.read_bytes()[: self.packed.size // 2])
        for call in (lambda: handoff.check_bundle(half),
                     lambda: handoff.unpack(half, self.tr_projects)):
            with self.assertRaises(handoff.HandoffError) as cm:
                call()
            self.assertIn("同步", str(cm.exception))      # 不是 BadZipFile traceback

    def test_unpack_preflight_does_not_write(self):
        tampered = _rewrite_zip(self.bundle, self.tmp / "tampered.zip",
                                {"exported/script.json": b'{"broken": true}'})
        before = self.tr.script.read_bytes()
        backups = sorted(q.name for q in self.tr.exported.glob("script.backup-*.json"))
        with self.assertRaises(handoff.HandoffError) as cm:
            handoff.unpack(tampered, self.tr_projects)
        self.assertIn("exported/script.json", str(cm.exception))
        self.assertEqual(self.tr.script.read_bytes(), before)
        # 備份發生在寫入前：沒有新備份，就證明真的在落地前就攔下了
        self.assertEqual(sorted(q.name for q in self.tr.exported.glob("script.backup-*.json")), backups)

    def test_force_does_not_bypass_integrity(self):
        tampered = _rewrite_zip(self.bundle, self.tmp / "tampered2.zip",
                                {"exported/script.json": b'{"broken": true}'})
        with self.assertRaises(handoff.HandoffError):
            handoff.unpack(tampered, self.tr_projects, force=True)

    def test_missing_hash_is_warning_not_error(self):
        with zipfile.ZipFile(self.bundle) as zf:
            man = json.loads(zf.read(handoff.MANIFEST))
        man["files"].pop("glossary.txt", None)
        loose = _rewrite_zip(self.bundle, self.tmp / "loose.zip",
                             {handoff.MANIFEST: json.dumps(man, ensure_ascii=False).encode("utf-8")})
        c = handoff.check_bundle(loose)
        self.assertTrue(c.ok, c.problems)                  # format: 0 的舊包要收得進來
        self.assertTrue(any("glossary.txt" in w for w in c.warnings), c.warnings)

    def test_resolve_by_game_name_finds_shared_dir(self):
        shared = self.tmp / "drive"
        (shared / "demo" / "handoff").mkdir(parents=True)
        dst = shutil.copy2(self.bundle, shared / "demo" / "handoff" / self.bundle.name)
        with mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": str(shared)}):
            self.assertEqual(handoff.resolve_bundle("demo", site="translator"), Path(dst))
            # 沒有寄給本站的包 → 不篩站點再找一次，仍找得到
            self.assertEqual(handoff.resolve_bundle("demo", site="workstation"), Path(dst))


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
        env = {**os.environ, "AGT_SITE": "translator", "AGT_HANDOFF_DIR": "", "PYTHONUTF8": "1"}
        return subprocess.run([PY, "-c", code], capture_output=True, cwd=REPO, env=env, **UTF8)

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

    def test_handoff_check_cli(self):
        r = self._agt("handoff", "check", str(self.bundle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("完整性驗證通過", r.stdout)
        r = self._agt("handoff", "check", str(self.bundle), "--expect-sha256", "0" * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不要用", r.stdout + r.stderr)      # 要把對方推離 --force

    def test_env(self):
        r = self._agt("env")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("站點: translator", r.stdout)
        r = self._agt("env", "--json")
        self.assertEqual(json.loads(r.stdout)["site"], "translator")


if __name__ == "__main__":
    unittest.main()
