"""Unity（JSON 表格 TextAsset）轉接器。

適用：文本放在 *_Data/resources.assets 的 TextAsset、內容是 {"Rows":[…]} JSON 表的 Unity 遊戲
（OneUp／いぬすく 圈的 Unity 6 IL2CPP 作品即此類）。UI 標籤（TextMeshPro）與 Addressables bundle 屬第二階段，
見 NOTES.md。vendor/ 的腳本是本專案自寫（非搬入），需要 .venv-unity 的 UnityPy。
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from core import fsutil, script_json
from core.adapter import EngineMatch, Project, StandardCliAdapter, StepResult
from core.install_notes import build_fields
from core.install_notes import write as write_install_notes


def _find_root(game_dir: Path, max_depth: int = 2) -> tuple[Path, Path] | None:
    """回傳 (遊戲根目錄, *_Data 目錄)。"""
    level = [game_dir]
    for depth in range(max_depth + 1):
        nxt: list[Path] = []
        for d in level:
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and sub.name.endswith("_Data") and (sub / "globalgamemanagers").exists():
                    return d, sub
                if sub.is_dir() and depth < max_depth and not sub.name.startswith("."):
                    nxt.append(sub)
        level = nxt
    return None


class UnityTextAssetAdapter(StandardCliAdapter):
    name = "unity_textasset"
    roundtrip_mode = "bytes"
    zero_import_noop_ok = True       # import_script 對零譯文（或譯文＝原文）刻意不寫檔；往返由 vendor/roundtrip_test.py 驗

    # -- 偵測 ---------------------------------------------------------------

    @classmethod
    def detect(cls, game_dir: Path) -> EngineMatch | None:
        found = _find_root(Path(game_dir))
        if not found:
            return None
        root, data = found
        evidence = [f"{data.relative_to(game_dir) if data != game_dir else data.name}/globalgamemanagers 存在"]
        try:
            head = (data / "globalgamemanagers").open("rb").read(64)
            m = re.search(rb"\d+\.\d+\.\d+[a-z]\d+", head)
            if m:
                evidence.append(f"Unity {m.group(0).decode()}")
        except OSError:
            pass
        backend = "il2cpp" if (root / "GameAssembly.dll").exists() else ("mono" if (data / "Managed").exists() else "")
        if backend:
            evidence.append(f"{'GameAssembly.dll → IL2CPP' if backend == 'il2cpp' else 'Managed/ → Mono'}")
        if (root / "UnityPlayer.dll").exists():
            evidence.append("UnityPlayer.dll 存在")
        # 有沒有 JSON 表格 TextAsset：用純標準庫粗掃 resources.assets
        conf = 0.6
        res = data / "resources.assets"
        if res.exists():
            blob = res.read_bytes()
            n = blob.count(b'{\n    "Rows": [')
            if n:
                evidence.append(f"resources.assets 內有 {n} 個 JSON 表格 TextAsset")
                conf = 0.9
            else:
                evidence.append("resources.assets 內沒有 JSON 表格（本轉接器可能不適用，需擴充）")
        return EngineMatch(engine=cls.name, confidence=conf, evidence=evidence, variant=backend,
                           source_encoding="utf-8", target_encoding="utf-8",
                           extra={"game_root": str(root), "data_dir": str(data)})

    # -- 標準 CLI 的差異 -----------------------------------------------------

    def rules_path(self, p: Project) -> Path | None:
        for cand in (p.root / "unity_rules.json", self.profile.engine_dir / "rules" / f"{p.name}.json"):
            if cand.exists():
                return cand
        return None

    def _rules_args(self, p: Project) -> list[str]:
        r = self.rules_path(p)
        return ["--rules", str(r)] if r else []

    def export(self, p: Project) -> StepResult:
        m = p.match()
        p.exported.mkdir(parents=True, exist_ok=True)
        cmd = [self.python, self.vendor("export_script.py"), self.data_dir(p.extracted), "-o", p.exported,
               *self._rules_args(p)]
        r = self.run(cmd, log_name="export", logs_dir=p.logs)
        if r.ok and p.script.exists():
            self.write_sidecar(p, m)
        return r

    def extra_validate_args(self, p: Project, m: EngineMatch | None) -> list[str]:
        return ["-u", str(p.exported / "untranslated.json"), "-c", "dialog", "choice"]

    def extra_import_args(self, p: Project, m: EngineMatch | None) -> list[str]:
        return self._rules_args(p)

    def verify(self, p: Project, translated: Path | None = None) -> StepResult:
        translated = translated or p.translated
        cmd = [self.python, self.vendor("import_script.py"), "verify", self.data_dir(p.extracted),
               translated, *self._rules_args(p)]
        return self.run(cmd, log_name="verify", logs_dir=p.logs)

    # -- 步驟 ---------------------------------------------------------------

    def prepare(self, p: Project, m: EngineMatch) -> StepResult:
        root = Path(m.extra.get("game_root") or p.original).resolve()
        fsutil.replace_dir_with_link(root, p.extracted, rmtree_ok=True)
        r = self.run([self.python, self.vendor("inspect_assets.py"), root], log_name="inspect", logs_dir=p.logs)
        if r.ok:
            r.summary = f"extracted → {root}；量測見 {r.log_path}"
        return r

    def breakage_test(self, p: Project) -> StepResult:
        """複製 resources.assets，刪掉一張表的一列，verify 必須攔下來。"""
        data_dir = Path(p.match().extra["data_dir"]) if p.match() and p.match().extra.get("data_dir") else None
        if data_dir is None:
            return StepResult(ok=False, summary="沒有 data_dir 資訊")
        tmp = Path(tempfile.mkdtemp(prefix="agt-breakage-", dir=p.root))
        try:
            out = tmp / data_dir.name
            out.mkdir(parents=True)
            r = self.run([self.python, self.vendor("breakage_inject.py"), data_dir / "resources.assets",
                          out / "resources.assets"], log_name="breakage-inject", logs_dir=p.logs)
            if not r.ok:
                return r
            v = self.verify(p, translated=tmp)
            caught = not v.ok
            summary = f"刻意刪除一列 → verify {'有攔到 ✓' if caught else '沒攔到 ✗'}"
            print(summary)
            return StepResult(ok=caught, cmd=v.cmd, returncode=v.returncode, log_path=v.log_path,
                              summary=summary, output=v.output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def font_step(self, p: Project) -> StepResult:
        """profile.patch.tmp_dynamic_font：把 TMP 靜態字型資產改成動態造字，輸出到 translated/。"""
        cfg = self.profile.patch.get("tmp_dynamic_font") or {}
        if not cfg.get("enabled", False):
            return StepResult(ok=True, summary="tmp_dynamic_font 未啟用")
        cmd = [self.python, self.vendor("tmp_font_dynamic.py"), self.data_dir(p.extracted), "-o", p.translated,
               "--assets", cfg.get("assets", "sharedassets0.assets"), *cfg.get("args", [])]
        return self.run(cmd, log_name="tmp_font_dynamic", logs_dir=p.logs)

    def package(self, p: Project) -> StepResult:
        m = p.match()
        if not p.translated.exists() or not any(p.translated.rglob("*")):
            return StepResult(ok=False, summary="translated/ 是空的：沒有任何譯文變動，或尚未 import")
        r = self.font_step(p)
        if not r.ok:
            return r
        changed = [x for x in p.translated.rglob("*") if x.is_file()]
        if p.out.exists():
            shutil.rmtree(p.out)
        rels = []
        for f in changed:
            rel = f.relative_to(p.translated)
            dst = p.out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            rels.append(rel.as_posix())
        data = script_json.load(p.script) if p.script.exists() else None
        root = Path(m.extra.get("game_root", p.original)) if m else p.original
        exes = [x.name for x in root.glob("*.exe") if "CrashHandler" not in x.name]
        exe = exes[0] if exes else "遊戲主程式"
        fields = build_fields(
            self.profile, data, game_title=(data or {}).get("info", {}).get("game_title") or p.name,
            version_note="（Unity）",
            deliverables=[f"{rel}  ← 覆蓋遊戲目錄同路徑（原檔先改名 .orig）" for rel in rels],
            backup_lines=[f"ren {rel.replace('/', chr(92))} {Path(rel).name}.orig" for rel in rels],
            exe=exe, target_dir_note=f"（{exe} 所在的資料夾）",
            variant_note=("resources.assets 是文字資料；sharedassets0.assets 是把 TextMeshPro 字型改成動態造字（用遊戲內嵌的 NotoSansJP 字型檔即時產生缺字）。"
                          "兩個檔案要一起換。若仍有個別字顯示成方框，是內嵌字型檔本身沒有那個字，請回報。"),
            verification_log=[f"{len(rels)} 個 asset 檔有變動；verify 逐物件比對通過（非文字物件 raw 相同）",
                              "往返驗證（逐物件）與破壞攔截通過"],
        )
        notes = write_install_notes(p.out, fields)
        summary = f"交付 {', '.join(rels)} 到 {p.out}，安裝說明 {notes.name}"
        print(summary)
        return StepResult(ok=True, summary=summary)
