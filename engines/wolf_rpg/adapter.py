"""WOLF RPG Editor（ウディタ）轉接器：包住 vendor/ 的 GalTransl-sister 腳本。

支援 2.x（Game.exe、單一 Data.wolf、CP932→Big5）與 3.x（GamePro.exe、Data/*.wolf、UTF-8）。
版本差異、語言標記、字型、封包形式等坑見 NOTES.md 與 vendor/README.md。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from core import script_json
from core.adapter import EngineMatch, Project, StandardCliAdapter, StepResult
from core.install_notes import build_fields
from core.install_notes import write as write_install_notes
from core.profile import load_profile

DX_MAGIC = b"DX"
TEXT_ARCHIVES = ("BasicData", "MapData")     # 3.x 只有這兩包含文字


def _is_dxa(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(2) == DX_MAGIC
    except OSError:
        return False


def _find_archives(game_dir: Path, max_depth: int = 2) -> tuple[Path | None, dict[str, Path], str]:
    """回傳 (遊戲根目錄, {封包名: 路徑}, 變體)。最多往下找兩層（發行檔常多包一層日文資料夾）。"""
    level = [game_dir]
    for depth in range(max_depth):
        nxt: list[Path] = []
        for d in level:
            if (d / "Data.wolf").is_file():
                return d, {"Data.wolf": d / "Data.wolf"}, "2.x"
            if (d / "Data" / "BasicData.wolf").is_file():
                archives = {x.name: x for x in sorted((d / "Data").glob("*.wolf"))}
                return d, archives, "3.x"
            if depth < max_depth - 1:
                nxt.extend(x for x in sorted(d.iterdir()) if x.is_dir() and not x.name.startswith("."))
        level = nxt
    return None, {}, ""


class WolfAdapter(StandardCliAdapter):
    name = "wolf_rpg"
    roundtrip_mode = "bytes"

    # -- 偵測 ---------------------------------------------------------------

    @classmethod
    def detect(cls, game_dir: Path) -> EngineMatch | None:
        game_dir = Path(game_dir)
        if (game_dir / "www" / "data" / "System.json").exists():
            return None
        root, archives, variant = _find_archives(game_dir)
        if root is None:
            return None
        rel = root.relative_to(game_dir) if root != game_dir else Path(".")
        evidence: list[str] = []
        dxa_ok = False
        for name, path in archives.items():
            if variant == "3.x" and name not in ("BasicData.wolf", "MapData.wolf"):
                continue
            magic = _is_dxa(path)
            dxa_ok = dxa_ok or magic
            evidence.append(f"{rel}/{path.relative_to(root)} 存在（magic {'DX ✓' if magic else '不是 DX ✗'}）")
        for exe, v in (("GamePro.exe", "3.x"), ("Game.exe", "2.x")):
            if (root / exe).exists():
                evidence.append(f"{exe} 存在 → {v}")
                if exe == "GamePro.exe":
                    variant = "3.x"
        v = load_profile(cls.name).variant(variant)
        return EngineMatch(
            engine=cls.name, confidence=0.95 if dxa_ok else 0.6, evidence=evidence, variant=variant,
            source_encoding=v.get("source_encoding", "utf-8"), target_encoding=v.get("target_encoding", "utf-8"),
            extra={"game_root": str(root), "archives": {k: str(p) for k, p in archives.items()}},
        )

    # -- 標準 CLI 的差異 -----------------------------------------------------

    def data_dir(self, root: Path) -> Path:
        return root / "Data"

    def encoding_args(self, m: EngineMatch | None, which: str) -> list[str]:
        if m is None:
            return []
        return ["-e", m.source_encoding if which == "source" else m.target_encoding]

    def extra_import_args(self, p: Project, m: EngineMatch | None) -> list[str]:
        # 來源與目標都是 UTF-8 時不要套 Big5 轉碼表（會把 ー／・ 無謂換掉）
        if m and m.target_encoding.lower().replace("-", "") == "utf8":
            return ["--no-transcode"]
        return []

    def _archives(self, m: EngineMatch) -> dict[str, Path]:
        return {k: Path(v) for k, v in (m.extra.get("archives") or {}).items()}

    # -- 步驟 ---------------------------------------------------------------

    def prepare(self, p: Project, m: EngineMatch) -> StepResult:
        archives = self._archives(m)
        out = self.data_dir(p.extracted)
        if out.exists():
            shutil.rmtree(out)
        extract = self.vendor("extract_wolf.py")
        if m.variant == "2.x":
            if "Data.wolf" not in archives:
                return StepResult(ok=False, summary="找不到 Data.wolf")
            r = self.run([self.python, extract, archives["Data.wolf"], "-o", out], log_name="extract", logs_dir=p.logs)
            if not r.ok:
                return r
        else:
            for name in TEXT_ARCHIVES:
                arc = archives.get(f"{name}.wolf")
                if arc is None:
                    return StepResult(ok=False, summary=f"找不到 Data/{name}.wolf")
                # 3.x 的檔案在封包根目錄、沒有目錄前綴，TEXT_DIRS 過濾會一條都不 match，必須 --all
                r = self.run([self.python, extract, arc, "-o", out / name, "--all"], log_name=f"extract-{name}", logs_dir=p.logs)
                if not r.ok:
                    return r
        counts = {ext: len(list(out.rglob(f"*{ext}"))) for ext in (".mps", ".dat", ".project")}
        summary = f"解包到 {out}：{counts['.mps']} 張地圖、{counts['.dat']} 個 .dat、{counts['.project']} 個 .project"
        print(summary)
        return StepResult(ok=True, summary=summary)

    def breakage_test(self, p: Project) -> StepResult:
        """複製資料樹，把一個 SetLabel/JumpLabel 的字串改掉，verify 必須攔下來。"""
        src = self.data_dir(p.extracted)
        tmp = Path(tempfile.mkdtemp(prefix="agt-breakage-", dir=p.root))
        try:
            broken = self.data_dir(tmp)
            shutil.copytree(src, broken)
            if str(self.vendor_dir) not in sys.path:
                sys.path.insert(0, str(self.vendor_dir))
            from wolfrpg.common_events import CommonEvents  # type: ignore
            from wolfrpg.map import Map  # type: ignore

            injected = ""
            for mps in sorted((broken / "MapData").glob("*.mps")):
                wm = Map(str(mps))
                for ev in wm.events:
                    for page in ev.pages:
                        for cmd in page.commands:
                            if cmd.cid in (212, 213) and cmd.string_args:
                                cmd.string_args[0] = b"AGT_BROKEN_LABEL"
                                injected = f"{mps.name} cid {cmd.cid}"
                                break
                        if injected:
                            break
                    if injected:
                        break
                if injected:
                    wm.dump(str(mps))
                    break
            if not injected:
                ce_path = broken / "BasicData" / "CommonEvent.dat"
                if ce_path.exists():
                    ce = CommonEvents(str(ce_path))
                    for ev in ce.events:
                        for cmd in ev.commands:
                            if cmd.cid in (212, 213) and cmd.string_args:
                                cmd.string_args[0] = b"AGT_BROKEN_LABEL"
                                injected = f"CommonEvent.dat cid {cmd.cid}"
                                break
                        if injected:
                            break
                    if injected:
                        ce.dump(str(ce_path))
            if not injected:
                return StepResult(ok=False, summary="資料裡沒有 SetLabel/JumpLabel 可供破壞測試")
            r = self.verify(p, translated=tmp)
            caught = not r.ok
            summary = f"刻意破壞 {injected} → verify {'有攔到 ✓' if caught else '沒攔到 ✗'}"
            print(summary)
            return StepResult(ok=caught, cmd=r.cmd, returncode=r.returncode, log_path=r.log_path,
                              summary=summary, output=r.output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def package(self, p: Project) -> StepResult:
        m = p.match()
        if m is None:
            return StepResult(ok=False, summary="沒有引擎辨識結果")
        archives = self._archives(m)
        edata, tdata = self.data_dir(p.extracted), self.data_dir(p.translated)
        if not tdata.exists():
            return StepResult(ok=False, summary="translated/Data 不存在，先 agt import")
        v = self.profile.variant(m.variant)
        steps_log: list[str] = []

        # 1. Game.dat 用回原始檔：import 重新序列化的版本長度可能改變，遊戲會開不起來
        gd_src, gd_dst = edata / "BasicData" / "Game.dat", tdata / "BasicData" / "Game.dat"
        if gd_src.exists():
            shutil.copy2(gd_src, gd_dst)
            size0 = gd_dst.stat().st_size
            steps_log.append(f"Game.dat 用回原始檔（{size0} bytes）")
            # 2. 語言標記（只有 2.x 需要；不改長度）
            if v.get("language_marker"):
                r = self.run([self.python, self.vendor("set_game_lang.py"), gd_dst, "--lang", v["language_marker"]],
                             log_name="set_game_lang", logs_dir=p.logs)
                if not r.ok:
                    return r
                steps_log.append(f"語言標記 → {v['language_marker']}")
            # 3. 字型（NUL 補滿原欄位，不改長度）
            font = self.profile.patch.get("font")
            if font:
                r = self.run([self.python, self.vendor("set_font.py"), gd_dst, "--font", font, "-e", m.source_encoding],
                             log_name="set_font", logs_dir=p.logs)
                if not r.ok:
                    return r
                steps_log.append(f"字型 → {font}")
            if gd_dst.stat().st_size != size0:
                return StepResult(ok=False, summary=f"Game.dat 長度改變了（{size0} → {gd_dst.stat().st_size}），遊戲會開不起來，中止")

        # 4. 重新打包：永遠從原始封包出發
        if p.out.exists():
            shutil.rmtree(p.out)
        p.out.mkdir(parents=True)
        repack = self.vendor("repack_wolf.py")
        deliverables: list[str] = []
        if m.variant == "2.x":
            r = self.run([self.python, repack, archives["Data.wolf"], tdata, "-o", p.out / "Data.wolf"],
                         log_name="repack", logs_dir=p.logs)
            if not r.ok:
                return r
            deliverables.append("Data.wolf  ← 放到遊戲根目錄（原檔先改名 Data.wolf.orig）")
        else:
            for name in TEXT_ARCHIVES:
                r = self.run([self.python, repack, archives[f"{name}.wolf"], tdata / name, "-o", p.out / f"{name}.wolf"],
                             log_name=f"repack-{name}", logs_dir=p.logs)
                if not r.ok:
                    return r
                deliverables.append(f"{name}.wolf  ← 放到遊戲的 Data/（原檔先改名 {name}.wolf.orig）")

        # 5. 安裝說明
        changed = self.changed_files(edata, tdata)
        data = script_json.load(p.script) if p.script.exists() else None
        exe = v.get("exe", "Game.exe")
        if m.variant == "2.x":
            target_dir_note = f"（{exe} 所在的資料夾）"
            backup_lines = ["ren Data.wolf Data.wolf.orig"]
            variant_note = ("本補丁已把 Game.dat 的語言標記設為繁體中文（Big5）並換用系統字型；"
                            "若對話變成方框，請確認系統有「" + str(self.profile.patch.get("font", "")) + "」字型。")
        else:
            target_dir_note = f"（{exe} 所在的資料夾）底下的 Data\\ 子目錄"
            backup_lines = [f"ren Data\\{n}.wolf {n}.wolf.orig" for n in TEXT_ARCHIVES]
            variant_note = "本補丁沒有動 Game.dat 的語言標記（3.x 是 UTF-8，不需要）。"
        fields = build_fields(
            self.profile, data, game_title=(data or {}).get("info", {}).get("game_title") or p.name,
            version_note=f"（Wolf RPG {m.variant}）", deliverables=deliverables, backup_lines=backup_lines,
            exe=exe, target_dir_note=target_dir_note, variant_note=variant_note,
            verification_log=steps_log + [f"封包內 {len(changed)} 個檔案有變動；repack 已自動解開逐檔比對",
                                          "往返驗證與零翻譯導入逐位元組相同；刻意破壞測試有被攔下"],
        )
        notes = write_install_notes(p.out, fields)
        summary = f"交付 {', '.join(d.split()[0] for d in deliverables)} 到 {p.out}，安裝說明 {notes.name}"
        print(summary)
        return StepResult(ok=True, summary=summary)
