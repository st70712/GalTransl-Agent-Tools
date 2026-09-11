"""RPG Maker MV / MZ 轉接器：包住 vendor/ 的 GalTransl-RPGmaker 腳本。"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from core import script_json
from core.adapter import EngineMatch, Project, StandardCliAdapter, StepResult
from core.install_notes import build_fields
from core.install_notes import write as write_install_notes

DATA_SUBDIRS = ("www/data", "data")


def _find_game_root(game_dir: Path, max_depth: int = 2) -> tuple[Path, str] | None:
    """找含 System.json 的資料目錄；回傳 (遊戲根目錄, 'www/data' 或 'data')。最多往下找兩層。"""
    candidates = [game_dir]
    for depth in range(max_depth):
        next_level = []
        for d in candidates:
            for sub in DATA_SUBDIRS:
                if (d / sub / "System.json").is_file():
                    return d, sub
            if depth < max_depth - 1:
                next_level.extend(x for x in sorted(d.iterdir()) if x.is_dir() and not x.name.startswith("."))
        candidates = next_level
    return None


class RpgMakerAdapter(StandardCliAdapter):
    name = "rpgmaker_mv_mz"
    roundtrip_mode = "json"          # JSON 重新序列化後空白不同，用 json.load 相等比對

    # -- 偵測 ---------------------------------------------------------------

    @classmethod
    def detect(cls, game_dir: Path) -> EngineMatch | None:
        game_dir = Path(game_dir)
        if any((game_dir / n).exists() for n in ("Data.wolf", "Game.rgss3a")):
            return None
        found = _find_game_root(game_dir)
        if not found:
            return None
        root, sub = found
        evidence = [f"{root.relative_to(game_dir) if root != game_dir else '.'}/{sub}/System.json 存在"]
        variant = "MV" if sub == "www/data" else "MZ"
        for rel, v in (("www/js/rpg_core.js", "MV"), ("js/rpg_core.js", "MV"), ("js/rmmz_core.js", "MZ")):
            if (root / rel).exists():
                evidence.append(f"{rel} 存在 → {v}")
                variant = v
        for rel in ("www/index.html", "package.json", "Game.exe", "nw.exe"):
            if (root / rel).exists():
                evidence.append(f"{rel} 存在")
        return EngineMatch(engine=cls.name, confidence=0.95, evidence=evidence, variant=variant,
                           source_encoding="utf-8", target_encoding="utf-8",
                           extra={"game_root": str(root), "data_subdir": sub})

    # -- 步驟 ---------------------------------------------------------------

    def prepare(self, p: Project, m: EngineMatch) -> StepResult:
        root = Path(m.extra.get("game_root") or p.original).resolve()
        found = _find_game_root(root, max_depth=1)
        if not found:
            return StepResult(ok=False, summary=f"{root} 底下找不到 www/data/System.json 或 data/System.json")
        if p.extracted.is_symlink() or p.extracted.exists():
            if p.extracted.is_symlink():
                p.extracted.unlink()
            else:
                shutil.rmtree(p.extracted)
        p.extracted.symlink_to(root)
        n = len(list((root / found[1]).glob("*.json")))
        summary = f"extracted → {root}（{found[1]}，{n} 個 JSON）"
        print(summary)
        return StepResult(ok=True, summary=summary)

    def data_subdir(self, root: Path) -> str:
        for sub in DATA_SUBDIRS:
            if (root / sub).is_dir():
                return sub
        return DATA_SUBDIRS[0]

    def extra_validate_args(self, p: Project, m: EngineMatch | None) -> list[str]:
        return ["-u", str(p.exported / "untranslated.json"), "-c", "dialog", "choice"]

    def breakage_test(self, p: Project) -> StepResult:
        """複製資料樹、把對話文字污染進一個圖片檔名並刪掉一個選項，verify 必須攔下來。

        vendored verify 的規則（import_script.py）：231 的圖片名多出「」→ error；102 選項數改變 → error。
        """
        src_root = p.extracted.resolve()
        sub = self.data_subdir(src_root)
        tmp = Path(tempfile.mkdtemp(prefix="agt-breakage-", dir=p.root))
        try:
            broken = tmp / "broken"
            shutil.copytree(src_root / sub, broken / sub)
            injected: list[str] = []

            def inject(cmds: list[dict]) -> bool:
                changed = False
                for cmd in cmds or []:
                    code = cmd.get("code")
                    if code == 231 and "picture" not in injected and len(cmd.get("parameters", [])) > 1:
                        cmd["parameters"][1] = "「テスト」"      # 對話文字污染圖片檔名
                        injected.append("picture")
                        changed = True
                    elif code == 102 and "choice" not in injected and len(cmd.get("parameters", [[]])[0]) > 1:
                        cmd["parameters"][0] = cmd["parameters"][0][:-1]   # 選項數量改變
                        injected.append("choice")
                        changed = True
                    if len(injected) == 2:
                        break
                return changed

            for path in sorted((broken / sub).glob("*.json")):
                if not (path.name.startswith("Map") or path.name == "CommonEvents.json") or path.name == "MapInfos.json":
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                changed = False
                if path.name == "CommonEvents.json":
                    for ev in data:
                        if ev and inject(ev.get("list")):
                            changed = True
                        if len(injected) == 2:
                            break
                else:
                    for ev in data.get("events") or []:
                        for page in (ev or {}).get("pages") or []:
                            if inject(page.get("list")):
                                changed = True
                            if len(injected) == 2:
                                break
                        if len(injected) == 2:
                            break
                if changed:
                    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                if len(injected) == 2:
                    break
            if not injected:
                return StepResult(ok=False, summary="資料裡沒有 231／102 指令可供破壞測試")
            r = self.verify(p, translated=broken)
            caught = not r.ok
            summary = f"刻意破壞 {injected} → verify {'有攔到 ✓' if caught else '沒攔到 ✗'}"
            print(summary)
            return StepResult(ok=caught, cmd=r.cmd, returncode=r.returncode, log_path=r.log_path,
                              summary=summary, output=r.output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def package(self, p: Project) -> StepResult:
        m = p.match()
        src_root = p.extracted.resolve()
        sub = self.data_subdir(src_root)
        changed = self.changed_files(src_root / sub, p.translated / sub, pattern="*.json")
        if not changed:
            return StepResult(ok=False, summary="translated 與 extracted 沒有任何差異，沒東西可交付")
        if p.out.exists():
            shutil.rmtree(p.out)
        (p.out / sub).mkdir(parents=True)
        for rel in changed:
            shutil.copy2(p.translated / sub / rel, p.out / sub / rel)
        data = script_json.load(p.script) if p.script.exists() else None
        exe = "Game.exe" if (src_root / "Game.exe").exists() else ("index.html" if (src_root / "index.html").exists() else "遊戲主程式")
        fields = build_fields(
            self.profile, data, game_title=(data or {}).get("info", {}).get("game_title") or p.name,
            version_note=f"（RPG Maker {m.variant}）" if m else "",
            deliverables=[f"{sub}/{rel}" for rel in changed],
            backup_lines=[f"{sub}/ 整個資料夾複製一份改名 {Path(sub).name}.orig（或用本補丁附的清單逐檔備份）"],
            exe=exe, target_dir_note=f"（{exe} 所在的資料夾）",
            verification_log=[f"{len(changed)} 個 JSON 有變動，import 後 verify 0 錯誤",
                              "零翻譯導入與原始資料 JSON 相等；刻意破壞測試有被攔下"],
        )
        notes = write_install_notes(p.out, fields)
        summary = f"交付 {len(changed)} 個 JSON 到 {p.out / sub}，安裝說明 {notes.name}"
        print(summary)
        return StepResult(ok=True, summary=summary)
