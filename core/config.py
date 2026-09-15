"""讀取工作區設定並套用環境變數覆蓋。

三層疊加：``DEFAULTS`` ← ``config.yaml``（進 git，這台開發機的路徑）← ``config.local.yaml``（不進 git，每台機器自己的
``site``／``handoff_dir``／直譯器路徑；Windows 可用正斜線）← 環境變數（``GALTRANSL_ROOT`` → ``galtransl_root``；
``AGT_<KEY大寫>`` → ``<key>``，設成空字串也會覆蓋，可用來暫時清掉設定檔的值）。設定檔只有一層 ``key: value``，刻意不依賴 pyyaml。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import REPO_ROOT, fsutil

CONFIG_PATH = REPO_ROOT / "config.yaml"
LOCAL_CONFIG_PATH = REPO_ROOT / "config.local.yaml"

DEFAULTS: dict[str, str] = {
    "galtransl_root": "/raid/home/jimhsieh/GalTransl",
    "python_stdlib": "/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python",
    "python_nllb": "/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python",
    "python_unity": str(fsutil.venv_python(REPO_ROOT / ".venv-unity")),
    "llama_server_bin": "/raid/home/jimhsieh/GalTransl/llama.cpp/build/bin/llama-server",
    "model_gguf": "/raid/home/jimhsieh/GalTransl/models/Sakura-GalTransl-14B-v3/Sakura-Galtransl-14B-v3.8.gguf",
    "endpoint": "http://127.0.0.1:8080",
    "llama_host": "127.0.0.1",
    "llama_port": "8080",
    "llama_ctx": "32768",
    "llama_np": "16",
    "llama_gpu": "auto",
    # 兩站接力（docs/two-site.md）：site = workstation | translator | full；handoff_dir = 兩站共用的交接資料夾（選用）
    "site": "",
    "handoff_dir": "",
    # 控制通道（docs/two-site.md §6b）：另一站 Claude 對話的可定址名字（ListAgents 看得到的那個）。
    # 新鍵一定要列在這裡：AGT_* 覆蓋是對 DEFAULTS ∪ 設定檔的鍵做迴圈，沒列就連 AGT_PEER_AGENT 都會被靜默忽略。
    "peer_agent": "",
}


def _parse_flat_yaml(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_config(path: Path | None = None, local_path: Path | None = None) -> dict[str, str]:
    """回傳合併後的設定：DEFAULTS ← config.yaml ← config.local.yaml ← 環境變數；``~`` 開頭的值會展開。"""
    cfg = dict(DEFAULTS)
    for p in (path or CONFIG_PATH, local_path or LOCAL_CONFIG_PATH):
        if p.exists():
            cfg.update(_parse_flat_yaml(p.read_text(encoding="utf-8")))
    if os.environ.get("GALTRANSL_ROOT"):
        cfg["galtransl_root"] = os.environ["GALTRANSL_ROOT"]
    for key in list(cfg):
        env = os.environ.get(f"AGT_{key.upper()}")
        if env is not None:  # 設成空字串也算覆蓋：AGT_HANDOFF_DIR="" 可暫時關掉 config.local.yaml 的 handoff_dir
            cfg[key] = env
    for key, value in cfg.items():
        if value.startswith("~"):
            cfg[key] = os.path.expanduser(value)
    return cfg


def config_sources() -> list[Path]:
    """實際存在的設定檔（給 ``agt env`` 印）。"""
    return [p for p in (CONFIG_PATH, LOCAL_CONFIG_PATH) if p.exists()]


def get(key: str, default: str | None = None) -> str | None:
    return load_config().get(key, default)


def site() -> str:
    """config 指定的站點（workstation／translator／full），沒設就回傳空字串。"""
    return load_config().get("site", "").strip()


def peer_agent() -> str:
    """另一站 Claude 對話的可定址名字；沒設就回傳空字串。

    這是**提示不是事實**：session resume／重連後名字會變（docs/two-site.md §6b）。
    送訊息前一律先 ListAgents 確認；過期時用 ``AGT_PEER_AGENT=新名字`` 臨時覆蓋，
    或請使用者改 config.local.yaml——代理不自己改設定檔。
    """
    return load_config().get("peer_agent", "").strip()


def handoff_dir() -> Path | None:
    """兩站共用的交接資料夾；沒設或不存在都回傳 None（呼叫端自行決定要不要警告）。"""
    d = load_config().get("handoff_dir", "").strip()
    if not d:
        return None
    p = Path(d)
    return p if p.is_dir() else None


def python_stdlib() -> str:
    """跑純標準庫工具（vendored 腳本、agt.py）的直譯器；不存在就退回目前的 python。"""
    p = load_config()["python_stdlib"]
    return p if Path(p).exists() else sys.executable


def python_nllb() -> str:
    p = load_config()["python_nllb"]
    return p if Path(p).exists() else sys.executable


def python_unity() -> str:
    """（相容用）Unity 轉接器的 venv；正式來源是 engines/unity_textasset/profile.json 的 python_env。"""
    p = load_config()["python_unity"]
    return p if Path(p).exists() else ""
