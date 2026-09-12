"""站點偵測（``agt env``）：這台機器是實機端（workstation）還是翻譯端（translator）。

- 實機端：有遊戲檔、能開遊戲（Windows），沒有模型。做 G0–G5、import/verify/package、playtest、交付。
- 翻譯端：有 Sakura 模型（llama-server）。做 translate/fix_text/check_codes/validate。
  翻譯端的專案若有 ``original/``（遊戲搬得過來），就是現行的單機完整流程，不需要交接。
站點由 ``config.local.yaml`` 的 ``site`` 決定；沒設就依機器能力推薦。
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import REPO_ROOT, config

SITES = ("workstation", "translator")
SITE_LABELS = {
    "workstation": "實機端（有遊戲檔、能開遊戲、無模型）",
    "translator": "翻譯端（有模型；專案有 original/ 時即單機完整流程）",
    "unknown": "未知：請在 config.local.yaml 設 site: workstation | translator",
}


@dataclass
class SiteReport:
    host: str
    system: str
    python: str
    config_files: list[str]
    site_configured: str
    site_recommended: str
    caps: dict[str, bool] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    engine_envs: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def site(self) -> str:
        return self.site_configured if self.site_configured in SITES else self.site_recommended

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["site"] = self.site
        return d


def _symlink_ok() -> bool:
    tmp = Path(tempfile.mkdtemp(prefix="agt-symlink-"))
    try:
        (tmp / "t").mkdir()
        (tmp / "l").symlink_to(tmp / "t", target_is_directory=True)
        return True
    except OSError:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def git_head() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def probe() -> SiteReport:
    cfg = config.load_config()
    details: dict[str, str] = {}
    caps: dict[str, bool] = {}

    galtransl = Path(cfg["galtransl_root"])
    llama = Path(cfg["llama_server_bin"])
    model = Path(cfg["model_gguf"])
    details["galtransl_root"] = str(galtransl)
    details["llama_server_bin"] = str(llama)
    details["model_gguf"] = str(model)
    caps["can_translate"] = galtransl.is_dir() and llama.exists() and model.exists()
    caps["python_nllb_ok"] = Path(cfg["python_nllb"]).exists()
    details["python_nllb"] = cfg["python_nllb"]
    caps["can_run_game"] = os.name == "nt"
    uv = shutil.which("uv")
    caps["uv"] = uv is not None
    details["uv"] = uv or "（找不到；Windows: pip install uv）"
    caps["symlink_ok"] = _symlink_ok()
    hd = cfg.get("handoff_dir", "")
    caps["handoff_dir_set"] = bool(hd)
    caps["handoff_dir_exists"] = bool(hd) and Path(hd).is_dir()
    details["handoff_dir"] = hd or "（未設：交接包留在 projects/<game>/handoff/，由使用者手動搬）"
    head = git_head()
    caps["git_ok"] = head is not None
    details["git_head"] = (head or "?")[:12]

    engine_envs: dict[str, dict[str, Any]] = {}
    try:
        from . import registry
        from .profile import load_profile
        for name in registry.engine_names():
            vp = load_profile(name).venv_python()
            if vp is not None:
                engine_envs[name] = {"venv": str(vp), "exists": vp.exists()}
    except Exception as e:  # 站點偵測不該因某個引擎壞掉而失敗
        details["engine_envs_error"] = repr(e)

    configured = cfg.get("site", "").strip()
    if configured in SITES:
        recommended = configured
    elif os.name == "nt":
        recommended = "workstation"
    elif caps["can_translate"]:
        recommended = "translator"
    else:
        recommended = "unknown"
    return SiteReport(
        host=socket.gethostname(), system=f"{platform.system()} {platform.release()}",
        python=f"{platform.python_version()} ({sys.executable})",
        config_files=[str(p) for p in config.config_sources()],
        site_configured=configured, site_recommended=recommended,
        caps=caps, details=details, engine_envs=engine_envs,
    )


def format_report(r: SiteReport) -> str:
    def yn(b: bool) -> str:
        return "✓" if b else "✗"
    lines = [
        f"主機: {r.host}  ({r.system})",
        f"Python: {r.python}",
        f"設定檔: {', '.join(r.config_files) or '（無）'}",
        f"站點: {r.site}  — {SITE_LABELS.get(r.site, r.site)}"
        + ("" if r.site_configured else "  （未設 site，依能力推薦）"),
        "能力:",
        f"  {yn(r.caps['can_translate'])} can_translate   galtransl_root={r.details['galtransl_root']}",
        f"      llama_server_bin={r.details['llama_server_bin']}",
        f"      model_gguf={r.details['model_gguf']}",
        f"  {yn(r.caps['python_nllb_ok'])} python_nllb     {r.details['python_nllb']}",
        f"  {yn(r.caps['can_run_game'])} can_run_game    （Windows 才能開遊戲）",
        f"  {yn(r.caps['uv'])} uv              {r.details['uv']}",
        f"  {yn(r.caps['symlink_ok'])} symlink_ok      （✗ 時 init/prepare 退回 junction）",
        f"  {yn(r.caps['handoff_dir_exists'])} handoff_dir     {r.details['handoff_dir']}",
        f"  {yn(r.caps['git_ok'])} git             HEAD {r.details['git_head']}",
    ]
    if r.engine_envs:
        lines.append("引擎專用環境:")
        for name, info in r.engine_envs.items():
            lines.append(f"  {yn(info['exists'])} {name:<18} {info['venv']}"
                         + ("" if info["exists"] else f"   ← bash tools/setup_env.sh {name}"))
    if "engine_envs_error" in r.details:
        lines.append(f"  ! 引擎載入失敗: {r.details['engine_envs_error']}")
    if r.site == "workstation":
        lines.append("此站做：detect/init/gates → 填 HANDOFF.md → agt handoff pack；收到回包後 import/verify/package/playtest。")
    elif r.site == "translator":
        lines.append("此站做：agt detect <來料> → handoff unpack → translate/fix_text/check-codes/validate → handoff pack。")
    return "\n".join(lines)


def current_site() -> str:
    """config 指定的站點；沒設就用推薦值（可能是 unknown）。"""
    s = config.site()
    return s if s in SITES else probe().site_recommended


def other_site(site: str) -> str | None:
    return {"workstation": "translator", "translator": "workstation"}.get(site)
