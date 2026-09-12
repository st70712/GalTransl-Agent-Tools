"""``script.json`` 的載入、存檔、schema 檢查與統計。

格式（與 GalTransl-RPGmaker / GalTransl-sister 完全相同）::

    {"info": {"game_title": ..., "engine"?: ..., "encoding"?: ..., "version": ..., "string_count": N},
     "strings": [{"index", "source_file", "location", "original", "translated", "context", "speaker", "code"}]}

對應鍵是 ``(source_file, location)``；``index`` 只是顯示序號，重新導出後會變。
``translated`` 為空字串代表「未翻譯／導入時跳過」。
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("index", "source_file", "location", "original", "translated", "context")
SIDECAR_NAME = ".agt.json"


def load(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = check_schema(data)
    if problems:
        raise ValueError(f"{path}: 不是合法的 script.json：" + "; ".join(problems[:5]))
    return data


def save(data: dict[str, Any], path: Path | str, indent: int = 2) -> None:
    """原子寫入（先寫 .tmp 再 replace），避免中斷留下半截檔案。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)


def check_schema(data: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["頂層不是物件"]
    if "info" not in data or not isinstance(data["info"], dict):
        problems.append("缺少 info")
    if "strings" not in data or not isinstance(data["strings"], list):
        problems.append("缺少 strings")
        return problems
    for i, entry in enumerate(data["strings"]):
        if not isinstance(entry, dict):
            problems.append(f"strings[{i}] 不是物件")
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            problems.append(f"strings[{i}] 缺少 {missing}")
        if len(problems) > 20:
            problems.append("...")
            break
    count = data.get("info", {}).get("string_count")
    if isinstance(count, int) and count != len(data["strings"]):
        problems.append(f"info.string_count={count} 但 strings 有 {len(data['strings'])} 條")
    return problems


def key(entry: dict[str, Any]) -> tuple[str, str]:
    return (entry["source_file"], entry["location"])


def index_by_key(entries: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {key(e): e for e in entries}


def blank_translations(data: dict[str, Any]) -> dict[str, Any]:
    """回傳把所有 translated 清空的深拷貝（零翻譯導入用）。"""
    out = copy.deepcopy(data)
    for e in out["strings"]:
        e["translated"] = ""
    return out


def identity_translations(data: dict[str, Any]) -> dict[str, Any]:
    """回傳把所有 translated 設成 original 的深拷貝（往返驗證用：導入後應與原檔相同）。"""
    out = copy.deepcopy(data)
    for e in out["strings"]:
        e["translated"] = e["original"]
    return out


def stats(data: dict[str, Any]) -> dict[str, Any]:
    total = Counter()
    done = Counter()
    for e in data["strings"]:
        ctx = e.get("context", "?")
        total[ctx] += 1
        if e.get("translated"):
            done[ctx] += 1
    return {
        "total": len(data["strings"]),
        "translated": sum(done.values()),
        "by_context": {c: {"total": total[c], "translated": done[c]} for c in sorted(total)},
    }


def format_stats(data: dict[str, Any]) -> str:
    s = stats(data)
    lines = [f"總計 {s['translated']}/{s['total']} 已翻譯"]
    for ctx, c in s["by_context"].items():
        lines.append(f"  {ctx:<20} {c['translated']:>6}/{c['total']:<6}")
    return "\n".join(lines)


def sidecar_path(script_path: Path | str) -> Path:
    return Path(script_path).parent / SIDECAR_NAME


def load_sidecar(script_path: Path | str) -> dict[str, Any] | None:
    p = sidecar_path(script_path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_sidecar(script_path: Path | str, payload: dict[str, Any]) -> Path:
    p = sidecar_path(script_path)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
