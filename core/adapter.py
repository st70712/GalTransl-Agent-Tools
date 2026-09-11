"""引擎轉接器的共用介面。

每個 ``engines/<name>/adapter.py`` 定義一個 :class:`EngineAdapter` 子類（通常繼承
:class:`StandardCliAdapter`）。轉接器**不重寫**既有工具，只把 ``vendor/`` 裡的腳本用
``subprocess`` 接到統一的步驟名稱上；每一步都印出完整指令，可以直接複製到 shell 重跑。
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import PROJECTS_DIR, config, script_json, state
from .profile import EngineProfile, load_profile
from .roundtrip import compare_trees


@dataclass
class EngineMatch:
    engine: str
    confidence: float                      # 0–1；registry 取最高且 >= 0.5
    evidence: list[str] = field(default_factory=list)
    variant: str = ""                      # "MV"/"MZ"、"2.x"/"3.x"…
    source_encoding: str = "utf-8"
    target_encoding: str = "utf-8"
    extra: dict[str, Any] = field(default_factory=dict)   # 例如找到的封包路徑

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EngineMatch:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Project:
    """``projects/<game>/`` 的固定佈局；所有步驟只吃這個物件。"""

    root: Path

    @classmethod
    def from_name(cls, name: str) -> Project:
        return cls(PROJECTS_DIR / name)

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def original(self) -> Path:      # 使用者放的原始遊戲，任何步驟不得寫入
        return self.root / "original"

    @property
    def extracted(self) -> Path:     # 可解析的資料樹
        return self.root / "extracted"

    @property
    def exported(self) -> Path:
        return self.root / "exported"

    @property
    def translated(self) -> Path:    # 導入後的資料樹（純衍生物）
        return self.root / "translated"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def state_path(self) -> Path:
        return self.root / "agt.json"

    @property
    def script(self) -> Path:
        return self.exported / "script.json"

    @property
    def glossary(self) -> Path:
        return self.root / "glossary.txt"

    def ensure_dirs(self) -> None:
        for d in (self.root, self.extracted, self.exported, self.translated, self.out, self.logs):
            d.mkdir(parents=True, exist_ok=True)

    def match(self) -> EngineMatch | None:
        eng = state.load_state(self.state_path).get("engine")
        return EngineMatch.from_dict(eng) if eng else None


@dataclass
class StepResult:
    ok: bool
    cmd: list[str] = field(default_factory=list)
    returncode: int = 0
    log_path: Path | None = None
    summary: str = ""
    output: str = ""

    def __bool__(self) -> bool:
        return self.ok

    @property
    def cmdline(self) -> str:
        return shlex.join(self.cmd)


class EngineAdapter(ABC):
    """所有引擎轉接器的基底。子類至少要設定 ``name`` 並實作八個步驟。"""

    name: str = ""

    def __init__(self, python: str | None = None) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} 沒有設定 name")
        self.profile: EngineProfile = load_profile(self.name)
        self.vendor_dir: Path = self.profile.engine_dir / "vendor"
        venv = self.profile.venv_python()
        if venv is not None:
            if not venv.exists():
                raise SystemExit(f"引擎 {self.name} 需要專用環境 {venv.parent.parent.name}，尚未建立：\n"
                                 f"  bash tools/setup_env.sh {self.name}")
            self.python = str(venv)          # profile 宣告了 python_env → 一律用它跑 vendor 腳本
        else:
            self.python = python or config.python_stdlib()

    # -- 偵測 ---------------------------------------------------------------

    @classmethod
    @abstractmethod
    def detect(cls, game_dir: Path) -> EngineMatch | None:
        """看目錄內容判斷是不是這個引擎；不是就回 None。"""

    # -- 八個步驟 -----------------------------------------------------------

    @abstractmethod
    def prepare(self, p: Project, m: EngineMatch) -> StepResult:
        """解包／定位資料樹到 ``p.extracted``。"""

    @abstractmethod
    def roundtrip(self, p: Project) -> StepResult:
        """解析→寫回→比對。動任何文字前的硬性關卡。"""

    @abstractmethod
    def export(self, p: Project) -> StepResult:
        """寫出 ``p.exported/script.json`` 與 sidecar。"""

    @abstractmethod
    def validate(self, p: Project, script: Path) -> StepResult:
        """譯文檢查（進度、編碼、控制碼…），不寫入遊戲資料。"""

    @abstractmethod
    def import_(self, p: Project, script: Path, out: Path | None = None) -> StepResult:
        """``p.extracted`` + 譯文 → ``p.translated``（先整個重建）。"""

    @abstractmethod
    def verify(self, p: Project, translated: Path | None = None) -> StepResult:
        """結構驗證：``p.extracted`` vs ``p.translated``。"""

    @abstractmethod
    def breakage_test(self, p: Project) -> StepResult:
        """刻意破壞一份複本，確認 verify 會攔下來（ok=True 代表「有攔到」）。"""

    @abstractmethod
    def package(self, p: Project) -> StepResult:
        """``p.translated`` → ``p.out/``（永遠從 ``p.original`` 的原始封包出發）。"""

    # -- 共用工具 -----------------------------------------------------------

    def data_dir(self, root: Path) -> Path:
        """資料樹根目錄在 root 下的位置（Wolf 是 root/Data；RPG Maker 就是 root）。"""
        return root

    def encoding_args(self, m: EngineMatch | None, which: str) -> list[str]:
        """要傳給 vendored 腳本的編碼參數；which 是 "source" 或 "target"。預設不傳。"""
        return []

    def run(self, cmd: list[str | Path], cwd: Path | None = None, log_name: str = "step",
            logs_dir: Path | None = None, env: dict[str, str] | None = None,
            quiet: bool = False) -> StepResult:
        """執行指令：印出完整命令列、串流輸出到終端與 log 檔，回傳 StepResult。"""
        cmd = [str(c) for c in cmd]
        log_path = None
        if logs_dir is not None:
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / f"{log_name}-{datetime.now():%Y%m%d-%H%M%S}.log"
        print(f"$ {shlex.join(cmd)}" + (f"   # cwd={cwd}" if cwd else ""), flush=True)
        lines: list[str] = []
        with (log_path.open("w", encoding="utf-8") if log_path else _NullFile()) as log:
            log.write(f"$ {shlex.join(cmd)}\n")
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace")
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line)
                log.write(line)
                if not quiet:
                    sys.stdout.write(line)
            rc = proc.wait()
        output = "".join(lines)
        non_empty = [ln.strip() for ln in lines if ln.strip()]
        tail = non_empty[-1] if non_empty else f"exit {rc}"
        return StepResult(ok=rc == 0, cmd=cmd, returncode=rc, log_path=log_path,
                          summary=tail, output=output)

    def vendor(self, script: str) -> Path:
        path = self.vendor_dir / script
        if not path.exists():
            raise FileNotFoundError(f"{self.name}: vendor 裡沒有 {script}")
        return path

    def changed_files(self, a: Path, b: Path, pattern: str = "**/*") -> list[str]:
        """b 裡與 a 不同（或 a 沒有）的檔案相對路徑——補丁只需要散佈這些。"""
        d = compare_trees(a, b, mode="bytes", pattern=pattern)
        return [rel for rel, _ in d.different] + d.only_b

    def write_sidecar(self, p: Project, m: EngineMatch | None, script: Path | None = None) -> Path:
        script = script or p.script
        data = script_json.load(script)
        payload = {
            "engine": self.name,
            "variant": m.variant if m else "",
            "source_encoding": m.source_encoding if m else "utf-8",
            "target_encoding": m.target_encoding if m else "utf-8",
            "data_root": str(self.data_dir(p.extracted)),
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "string_count": len(data["strings"]),
        }
        return script_json.save_sidecar(script, payload)


class _NullFile:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, _s: str) -> None:
        pass


class StandardCliAdapter(EngineAdapter):
    """vendor/ 內有「標準形狀」腳本時，export/validate/import/verify/roundtrip 不用再寫。

    標準形狀（GalTransl-RPGmaker 與 GalTransl-sister 皆如此）::

        export_script.py DATA -o OUT [-e ENC]
        import_script.py validate SCRIPT [-e ENC] [...]
        import_script.py import   DATA SCRIPT -o OUT [-e ENC] [...]
        import_script.py verify   DATA OUT [-e ENC]
        roundtrip_test.py DATA                     # 選用；沒有就用零翻譯導入代替

    子類只需實作 detect / prepare / package / breakage_test。
    """

    export_script = "export_script.py"
    import_script = "import_script.py"
    roundtrip_script = "roundtrip_test.py"
    roundtrip_mode = "bytes"                 # bytes | json

    def extra_validate_args(self, p: Project, m: EngineMatch | None) -> list[str]:
        return []

    def extra_import_args(self, p: Project, m: EngineMatch | None) -> list[str]:
        return []

    def export(self, p: Project) -> StepResult:
        m = p.match()
        p.exported.mkdir(parents=True, exist_ok=True)
        cmd = [self.python, self.vendor(self.export_script), self.data_dir(p.extracted),
               "-o", p.exported, *self.encoding_args(m, "source")]
        r = self.run(cmd, log_name="export", logs_dir=p.logs)
        if r.ok and p.script.exists():
            self.write_sidecar(p, m)
        return r

    def validate(self, p: Project, script: Path) -> StepResult:
        m = p.match()
        cmd = [self.python, self.vendor(self.import_script), "validate", script,
               *self.encoding_args(m, "target"), *self.extra_validate_args(p, m)]
        return self.run(cmd, log_name="validate", logs_dir=p.logs)

    def import_(self, p: Project, script: Path, out: Path | None = None) -> StepResult:
        m = p.match()
        out = out or p.translated
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        cmd = [self.python, self.vendor(self.import_script), "import",
               self.data_dir(p.extracted), script, "-o", self.data_dir(out),
               *self.encoding_args(m, "target"), *self.extra_import_args(p, m)]
        return self.run(cmd, log_name="import", logs_dir=p.logs)

    def verify(self, p: Project, translated: Path | None = None) -> StepResult:
        m = p.match()
        translated = translated or p.translated
        cmd = [self.python, self.vendor(self.import_script), "verify",
               self.data_dir(p.extracted), self.data_dir(translated),
               *self.encoding_args(m, "source")]
        return self.run(cmd, log_name="verify", logs_dir=p.logs)

    def roundtrip(self, p: Project) -> StepResult:
        script = self.vendor_dir / self.roundtrip_script
        if script.exists():
            cmd = [self.python, script, self.data_dir(p.extracted)]
            return self.run(cmd, log_name="roundtrip", logs_dir=p.logs)
        return self.zero_import(p, log_name="roundtrip")

    def zero_import(self, p: Project, log_name: str = "zero_import") -> StepResult:
        """把 translated 全清空後導入到暫存目錄，輸出必須與 extracted 相同。"""
        if not p.script.exists():
            r = self.export(p)
            if not r.ok:
                return r
        tmp = Path(tempfile.mkdtemp(prefix="agt-zero-", dir=p.root))
        try:
            blank = tmp / "zero.json"
            script_json.save(script_json.blank_translations(script_json.load(p.script)), blank)
            out = tmp / "out"
            r = self.import_(p, blank, out=out)
            if not r.ok:
                r.summary = "零翻譯導入失敗：" + r.summary
                return r
            d = compare_trees(self.data_dir(p.extracted), self.data_dir(out), mode=self.roundtrip_mode)
            summary = d.summary("extracted", "zero-import")
            print(summary)
            return StepResult(ok=d.ok, cmd=r.cmd, returncode=0 if d.ok else 1,
                              log_path=r.log_path, summary=summary, output=r.output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
