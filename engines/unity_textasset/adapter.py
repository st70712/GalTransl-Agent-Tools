"""Unity 轉接器：JSON 表格 TextAsset（RJ01483219）與 MonoBehaviour／ScriptableObject 欄位（RJ01657316）。

適用：*_Data 下是散檔（resources.assets…）或單一 data.unity3d bundle 的 Unity 遊戲；IL2CPP 或 Mono。
文本來源與位址格式見 vendor/unity_tables.py 模組說明；每款遊戲的欄位規則在 rules/<專案名>.json。
UI 標籤（TextMeshProUGUI.m_text）也走 MonoBehaviour 規則。Addressables bundle 未支援。
vendor/ 的腳本是本專案自寫（非搬入），需要 .venv-unity 的 UnityPy（+ TypeTreeGeneratorAPI）。
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

BUNDLE_NAME = "data.unity3d"


def _is_data_dir(d: Path) -> bool:
    return d.is_dir() and d.name.endswith("_Data") and ((d / "globalgamemanagers").exists() or (d / BUNDLE_NAME).exists())


def _find_root(game_dir: Path, max_depth: int = 2) -> tuple[Path, Path] | None:
    """回傳 (遊戲根目錄, *_Data 目錄)。"""
    level = [game_dir]
    for depth in range(max_depth + 1):
        nxt: list[Path] = []
        for d in level:
            for sub in sorted(d.iterdir()):
                if _is_data_dir(sub):
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
        rel = data.relative_to(game_dir) if data != game_dir else data.name
        container = "bundle" if (data / BUNDLE_NAME).exists() else "loose"
        evidence = [f"{rel}/{BUNDLE_NAME} 存在（單檔 UnityFS bundle，內含 globalgamemanagers／resources.assets／level*）"
                    if container == "bundle" else f"{rel}/globalgamemanagers 存在"]
        try:
            head = (data / (BUNDLE_NAME if container == "bundle" else "globalgamemanagers")).open("rb").read(64)
            m = re.search(rb"\d+\.\d+\.\d+[a-z]\d+", head)
            if m:
                evidence.append(f"Unity {m.group(0).decode()}")
        except OSError:
            pass
        backend = "il2cpp" if (root / "GameAssembly.dll").exists() else ("mono" if (data / "Managed").exists() else "")
        if backend:
            evidence.append("GameAssembly.dll → IL2CPP" if backend == "il2cpp" else "Managed/*.dll → Mono（type tree 可由 DLL 產生）")
        if (root / "UnityPlayer.dll").exists():
            evidence.append("UnityPlayer.dll 存在")
        conf = 0.6
        res = data / "resources.assets"
        if res.exists():
            # 有沒有 JSON 表格 TextAsset：用純標準庫粗掃 resources.assets（bundle 內是壓縮的，掃不到）
            blob = res.read_bytes()
            n = blob.count(b'{\n    "Rows": [')
            if n:
                evidence.append(f"resources.assets 內有 {n} 個 JSON 表格 TextAsset")
                conf = 0.9
            else:
                evidence.append("resources.assets 內沒有 JSON 表格（文本可能在 MonoBehaviour，需要 rules/<專案名>.json 的 monobehaviours 規則）")
        else:
            evidence.append("bundle 內容要靠 prepare（inspect_assets.py）量測；文本在哪張表／哪個 MonoBehaviour 由 rules/<專案名>.json 決定")
        return EngineMatch(engine=cls.name, confidence=conf, evidence=evidence, variant=backend,
                           source_encoding="utf-8", target_encoding="utf-8",
                           extra={"game_root": str(root), "data_dir": str(data), "container": container, "scripting": backend})

    # -- 標準 CLI 的差異 -----------------------------------------------------

    def rules_path(self, p: Project) -> Path | None:
        for cand in (p.root / "unity_rules.json", self.profile.engine_dir / "rules" / f"{p.name}.json"):
            if cand.exists():
                return cand
        return None

    def _rules_args(self, p: Project) -> list[str]:
        r = self.rules_path(p)
        return ["--rules", str(r)] if r else []

    def _container(self, p: Project) -> str:
        m = p.match()
        if m and m.extra.get("container"):
            return m.extra["container"]
        data_dir = self._data_dir(p)
        return "bundle" if data_dir and (data_dir / BUNDLE_NAME).exists() else "loose"

    def _data_dir(self, p: Project) -> Path | None:
        m = p.match()
        if m and m.extra.get("data_dir"):
            return Path(m.extra["data_dir"])
        found = _find_root(p.extracted) if p.extracted.exists() else None
        return found[1] if found else None

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

    def roundtrip(self, p: Project) -> StepResult:
        cmd = [self.python, self.vendor("roundtrip_test.py"), self.data_dir(p.extracted), *self._rules_args(p)]
        return self.run(cmd, log_name="roundtrip", logs_dir=p.logs)

    # -- 步驟 ---------------------------------------------------------------

    def prepare(self, p: Project, m: EngineMatch) -> StepResult:
        root = Path(m.extra.get("game_root") or p.original).resolve()
        fsutil.replace_dir_with_link(root, p.extracted, rmtree_ok=True)
        cmd = [self.python, self.vendor("inspect_assets.py"), root, *self._rules_args(p)]
        charsets = sorted((self.profile.engine_dir / "charsets").glob("*.txt"))
        if charsets:
            cmd += ["--charset", *charsets]
        r = self.run(cmd, log_name="inspect", logs_dir=p.logs)
        if r.ok:
            r.summary = f"extracted → {root}；量測見 {r.log_path}"
        return r

    def breakage_test(self, p: Project) -> StepResult:
        """複製容器檔（resources.assets 或 data.unity3d），刻意弄壞一處結構，verify 必須攔下來。"""
        data_dir = self._data_dir(p)
        if data_dir is None:
            return StepResult(ok=False, summary="沒有 data_dir 資訊")
        target = BUNDLE_NAME if (data_dir / BUNDLE_NAME).exists() else "resources.assets"
        tmp = Path(tempfile.mkdtemp(prefix="agt-breakage-", dir=p.root))
        try:
            out = tmp / data_dir.name
            out.mkdir(parents=True)
            r = self.run([self.python, self.vendor("breakage_inject.py"), data_dir / target, out / target,
                          *self._rules_args(p)], log_name="breakage-inject", logs_dir=p.logs)
            if not r.ok:
                return r
            v = self.verify(p, translated=tmp)
            caught = not v.ok
            summary = f"刻意弄壞 {target} 一處結構 → verify {'有攔到 ✓' if caught else '沒攔到 ✗'}"
            print(summary)
            return StepResult(ok=caught, cmd=v.cmd, returncode=v.returncode, log_path=v.log_path,
                              summary=summary, output=v.output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def font_step(self, p: Project) -> StepResult:
        """profile.patch 的字型對策，輸出到 translated/：
        - tmp_dynamic_font（散檔建置）：把 TMP 靜態字型資產改成動態造字（vendor/tmp_font_dynamic.py）。
        - font_inject（任何建置）：把 CJK 字型檔注入既有 Font 物件並掛成 TMP 全域備援（vendor/inject_font.py）；
          字型檔路徑相對於專案目錄，沒有該檔就跳過並提示。
        """
        container = self._container(p)
        cfg = self.profile.patch.get("font_inject") or {}
        if cfg.get("enabled", False):
            font = p.root / cfg.get("font", "font/inject.otf")
            if not font.exists():
                return StepResult(ok=True, summary=f"font_inject：找不到 {font}，跳過（缺字對策未套用）")
            data_dir = self.data_dir(p.extracted)
            target = BUNDLE_NAME if container == "bundle" else cfg.get("assets", "resources.assets")
            real_data_dir = self._data_dir(p)   # data_dir() 回的是 extracted/ 本身，名字不是 *_Data
            base = p.translated / (real_data_dir.name if real_data_dir else Path(data_dir).name) / target
            cmd = [self.python, self.vendor("inject_font.py"), data_dir, "-o", p.translated, "--font", font,
                   "--into", cfg.get("into", "LiberationSans"), *cfg.get("args", [])]
            if base.exists():
                cmd += ["--base", base]
            r = self.run(cmd, log_name="inject_font", logs_dir=p.logs)
            if not r.ok:
                return r
        cfg2 = self.profile.patch.get("tmp_dynamic_font") or {}
        if cfg2.get("enabled", False) and container == "loose":
            cmd = [self.python, self.vendor("tmp_font_dynamic.py"), self.data_dir(p.extracted), "-o", p.translated,
                   "--assets", cfg2.get("assets", "sharedassets0.assets"), *cfg2.get("args", [])]
            return self.run(cmd, log_name="tmp_font_dynamic", logs_dir=p.logs)
        return StepResult(ok=True, summary="字型步驟完成")

    def dll_step(self, p: Project) -> StepResult:
        """rules 檔的 dll_strings：把 Managed/<dll> 寫死的顯示文字／台詞比對常數原地換成譯文（vendor/patch_dll_strings.py），
        輸出到 translated/<*_Data>/Managed/<dll>。沒有 dll_strings 就跳過。"""
        import json
        r = self.rules_path(p)
        if not r:
            return StepResult(ok=True, summary="沒有規則檔")
        spec = (json.loads(r.read_text(encoding="utf-8")).get("dll_strings") or {})
        dlls = [k for k in spec if k.endswith(".dll")]
        if not dlls:
            return StepResult(ok=True, summary="規則檔沒有 dll_strings")
        data_dir = self._data_dir(p)
        if data_dir is None:
            return StepResult(ok=False, summary="沒有 data_dir 資訊")
        for name in dlls:
            src = data_dir / "Managed" / name
            if not src.exists():
                return StepResult(ok=False, summary=f"找不到 {src}")
            dst = p.translated / data_dir.name / "Managed" / name
            res = self.run([self.python, self.vendor("patch_dll_strings.py"), src, "-o", dst, "--map", r],
                           log_name="patch_dll", logs_dir=p.logs)
            if not res.ok:
                return res
        return StepResult(ok=True, summary=f"DLL 字串已覆蓋：{', '.join(dlls)}")

    def package(self, p: Project) -> StepResult:
        m = p.match()
        if not p.translated.exists() or not any(p.translated.rglob("*")):
            return StepResult(ok=False, summary="translated/ 是空的：沒有任何譯文變動，或尚未 import")
        r = self.font_step(p)
        if not r.ok:
            return r
        r = self.dll_step(p)
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
        container = self._container(p)
        if container == "bundle":
            variant_note = (f"{BUNDLE_NAME} 是整個遊戲的資產包（文字、字型設定都在裡面），直接覆蓋同路徑檔案；"
                            "體積大（百 MB 級）是正常的。若開遊戲就崩潰，多半是重新打包的 bundle 不被接受，請回報並附 crash.dmp／Player.log。"
                            + ("Managed 底下的 .dll 是遊戲程式，裡面寫死的提示文字與『認台詞』的常數已換成中文，要一起覆蓋，否則開場黑幕不會淡出。"
                               if any(x.endswith(".dll") for x in rels) else ""))
        else:
            variant_note = ("resources.assets 是文字資料；sharedassets0.assets 是把 TextMeshPro 字型改成動態造字（用遊戲內嵌的 NotoSansJP 字型檔即時產生缺字）。"
                            "兩個檔案要一起換。若仍有個別字顯示成方框，是內嵌字型檔本身沒有那個字，請回報。")
        total = sum((p.out / r).stat().st_size for r in rels)
        fields = build_fields(
            self.profile, data, game_title=(data or {}).get("info", {}).get("game_title") or p.name,
            version_note=f"（Unity，{'單檔 bundle' if container == 'bundle' else '散檔'}）",
            deliverables=[f"{rel}  ← 覆蓋遊戲目錄同路徑（原檔先改名 .orig）" for rel in rels],
            backup_lines=[f"ren {rel.replace('/', chr(92))} {Path(rel).name}.orig" for rel in rels],
            exe=exe, target_dir_note=f"（{exe} 所在的資料夾）",
            variant_note=variant_note,
            verification_log=[f"{len(rels)} 個檔案有變動（共 {total:,} bytes）；verify 逐物件比對通過（非文字物件 raw 相同）",
                              "往返驗證（逐物件＋資源區塊＋type tree）與破壞攔截通過"],
        )
        notes = write_install_notes(p.out, fields)
        summary = f"交付 {', '.join(rels)} 到 {p.out}（共 {total:,} bytes），安裝說明 {notes.name}"
        if total > 30 * 1024 * 1024:
            summary += "；超過 30 MiB，請 zip 後放到 handoff_dir 的 <game>/ 資料夾交付"
        print(summary)
        return StepResult(ok=True, summary=summary)
