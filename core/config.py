"""讀取工作區設定 ``config.yaml``（扁平 ``key: value``）並套用環境變數覆蓋。

刻意不依賴 pyyaml：設定檔只有一層，標準庫十行就能讀。
環境變數優先順序：``GALTRANSL_ROOT`` → ``galtransl_root``；``AGT_<KEY大寫>`` → ``<key>``。
"""

from __future__ import annotations

import os
from pathlib import Path

from . import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "config.yaml"

DEFAULTS: dict[str, str] = {
    "galtransl_root": "/raid/home/jimhsieh/GalTransl",
    "python_stdlib": "/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python",
    "python_nllb": "/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python",
    "python_unity": str(REPO_ROOT / ".venv-unity" / "bin" / "python"),
    "llama_server_bin": "/raid/home/jimhsieh/GalTransl/llama.cpp/build/bin/llama-server",
    "model_gguf": "/raid/home/jimhsieh/GalTransl/models/Sakura-GalTransl-14B-v3/Sakura-Galtransl-14B-v3.8.gguf",
    "endpoint": "http://127.0.0.1:8080",
    "llama_host": "127.0.0.1",
    "llama_port": "8080",
    "llama_ctx": "32768",
    "llama_np": "16",
    "llama_gpu": "auto",
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


def load_config(path: Path | None = None) -> dict[str, str]:
    """回傳合併後的設定：DEFAULTS ← config.yaml ← 環境變數。"""
    cfg = dict(DEFAULTS)
    path = path or CONFIG_PATH
    if path.exists():
        cfg.update(_parse_flat_yaml(path.read_text(encoding="utf-8")))
    if os.environ.get("GALTRANSL_ROOT"):
        cfg["galtransl_root"] = os.environ["GALTRANSL_ROOT"]
    for key in list(cfg):
        env = os.environ.get(f"AGT_{key.upper()}")
        if env:
            cfg[key] = env
    return cfg


def get(key: str, default: str | None = None) -> str | None:
    return load_config().get(key, default)


def python_stdlib() -> str:
    """跑純標準庫工具（vendored 腳本、agt.py）的直譯器；不存在就退回目前的 python。"""
    p = load_config()["python_stdlib"]
    return p if Path(p).exists() else os.sys.executable


def python_nllb() -> str:
    p = load_config()["python_nllb"]
    return p if Path(p).exists() else os.sys.executable


def python_unity() -> str:
    """（相容用）Unity 轉接器的 venv；正式來源是 engines/unity_textasset/profile.json 的 python_env。"""
    p = load_config()["python_unity"]
    return p if Path(p).exists() else ""
