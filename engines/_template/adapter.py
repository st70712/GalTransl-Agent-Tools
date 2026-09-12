"""<引擎名> 轉接器骨架。複製整個 engines/_template/ 成 engines/<engine_name>/ 後：

1. 把 profile.json 的 name 改成目錄名，填 detection / contexts / control_codes
2. 在 vendor/ 放（或寫）三支標準形狀的腳本：
       export_script.py DATA -o OUT [-e ENC]
       import_script.py validate SCRIPT | import DATA SCRIPT -o OUT | verify DATA OUT
       roundtrip_test.py DATA            # 選用；沒有就用零翻譯導入代替
3. 實作下面四個方法；export/validate/import/verify/roundtrip 由 StandardCliAdapter 提供
4. 依 docs/new-adapter.md 的順序驗收：roundtrip → export → zero-import → verify → breakage → smoke build
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from core.adapter import EngineMatch, Project, StandardCliAdapter, StepResult
from core.install_notes import write as write_install_notes


class TemplateAdapter(StandardCliAdapter):
    name = "_template"                 # TODO: 改成目錄名（與 profile.json 的 name 相同）
    roundtrip_mode = "bytes"           # 二進位格式用 bytes；JSON/文字格式重新序列化會變就用 json

    @classmethod
    def detect(cls, game_dir: Path) -> EngineMatch | None:
        """看目錄裡有什麼決定是不是這個引擎。回傳 None 代表不是。

        建議：檢查代表性檔案（exe、封包、資料目錄）＋讀開頭幾個 bytes 的 magic；
        把每一項證據寫進 evidence，讓人看得出為什麼。信心 >= 0.5 才會被自動採用。
        """
        game_dir = Path(game_dir)
        evidence: list[str] = []
        # TODO: 例如
        # if (game_dir / "game.exe").exists(): evidence.append("game.exe 存在")
        if not evidence:
            return None
        return EngineMatch(engine=cls.name, confidence=0.9, evidence=evidence, variant="",
                           source_encoding="utf-8", target_encoding="utf-8",
                           extra={"game_root": str(game_dir)})

    def data_dir(self, root: Path) -> Path:
        """資料樹在 extracted/translated 下的位置；解包後若多一層就在這裡指定。"""
        return root

    def encoding_args(self, m: EngineMatch | None, which: str) -> list[str]:
        """vendored 腳本需要 -e 時回傳 ["-e", 編碼]；which 是 "source" 或 "target"。"""
        return []

    def prepare(self, p: Project, m: EngineMatch) -> StepResult:
        """解包／定位資料樹到 p.extracted。原始遊戲在 p.original，任何步驟不得寫入。"""
        # TODO: 二進位封包 → 呼叫 vendor 的解包腳本；純檔案 → 連結即可（symlink，Windows 沒權限時退回 junction）：
        #   from core import fsutil
        #   fsutil.replace_dir_with_link(Path(m.extra["game_root"]).resolve(), p.extracted, rmtree_ok=True)
        return StepResult(ok=False, summary="TODO: prepare 尚未實作")

    def breakage_test(self, p: Project) -> StepResult:
        """複製資料樹、刻意弄壞一個「絕不能翻」的東西（標籤、檔名、事件名），verify 必須攔下來。
        回傳 ok=True 代表「有攔到」。"""
        src = self.data_dir(p.extracted)
        tmp = Path(tempfile.mkdtemp(prefix="agt-breakage-", dir=p.root))
        try:
            broken = self.data_dir(tmp)
            shutil.copytree(src, broken)
            # TODO: 修改 broken 裡的一個結構性字串
            r = self.verify(p, translated=tmp)
            caught = not r.ok
            return StepResult(ok=caught, cmd=r.cmd, returncode=r.returncode, log_path=r.log_path,
                              summary=f"刻意破壞 → verify {'有攔到 ✓' if caught else '沒攔到 ✗'}", output=r.output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def package(self, p: Project) -> StepResult:
        """p.translated → p.out/。只交付有變動的檔案；封包類引擎永遠從 p.original 的原始封包重新打包。"""
        changed = self.changed_files(self.data_dir(p.extracted), self.data_dir(p.translated))
        if not changed:
            return StepResult(ok=False, summary="沒有變動的檔案")
        if p.out.exists():
            shutil.rmtree(p.out)
        for rel in changed:
            dst = p.out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.data_dir(p.translated) / rel, dst)
        write_install_notes(p.out, {"game_title": p.name, "engine": self.profile.display_name,
                                    "deliverables": "\n".join(f"  {r}" for r in changed)})
        return StepResult(ok=True, summary=f"交付 {len(changed)} 個檔案到 {p.out}")
