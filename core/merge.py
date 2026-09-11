"""把舊譯文接到新導出的 script.json。

* :func:`by_location` —— 同一份遊戲資料重新導出後用（改了導出規則、``index`` 會變但
  ``(source_file, location)`` 不變）。規則同 GalTransl-sister/export_script.py:105-132：
  地址對上且 ``original`` 相同才套用。
* :func:`by_text` —— 跨遊戲版本用（位置全變了，只能靠原文字串）。規則同
  GalTransl-sister/merge_by_text.py：原文完全相同、帶值控制碼不能少也不能多、
  ``requires_counterpart`` 的 context 要有對應方、預設不覆蓋已有譯文。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import codes as _codes
from .profile import EngineProfile
from .script_json import key


def by_location(entries: list[dict[str, Any]], previous: list[dict[str, Any]]) -> tuple[int, int]:
    """回傳 ``(carried, dropped)``；dropped 含原文已變與新檔找不到位置的舊譯文。"""
    old = {key(e): e for e in previous if e.get("translated")}
    carried = dropped = 0
    for entry in entries:
        match = old.pop(key(entry), None)
        if match is None:
            continue
        if match["original"] != entry["original"]:
            dropped += 1
            continue
        entry["translated"] = match["translated"]
        carried += 1
    return carried, dropped + len(old)


def by_text(target: list[dict[str, Any]], source: list[dict[str, Any]], profile: EngineProfile,
            overwrite: bool = False, skip_contexts: tuple[str, ...] = ("game_title",)) -> Counter:
    memory: dict[str, str] = {}
    clashes = 0
    for e in source:
        t = e.get("translated") or ""
        o = e.get("original") or ""
        if not t or t == o:
            continue
        if o in memory and memory[o] != t:
            clashes += 1
            continue
        memory[o] = t

    counterpart_ctx = profile.counterpart_contexts()
    shared = {e["original"] for e in target if e.get("context") not in counterpart_ctx}

    stats: Counter = Counter()
    stats["舊譯文種類"] = len(memory)
    stats["舊譯文多版譯法（跳過）"] = clashes
    ci = profile.codes.case_insensitive
    for e in target:
        o = e.get("original") or ""
        if e.get("context") in skip_contexts:
            continue
        if e.get("translated") and not overwrite:
            stats["已有譯文，跳過"] += 1
            continue
        cand = memory.get(o)
        if cand is None:
            continue
        if e.get("context") in counterpart_ctx and o not in shared:
            stats["孤兒條件字串，保留原文"] += 1
            continue
        if _codes.lost(profile.codes.value_re, o, cand, ci):
            stats["帶值控制碼遺失，跳過"] += 1
            continue
        if _codes.lost(profile.codes.value_re, cand, o, ci):
            stats["憑空多出帶值控制碼，跳過"] += 1
            continue
        if _codes.lost(profile.codes.style_re, o, cand, ci):
            stats["表現控制碼遺失，跳過"] += 1
            continue
        e["translated"] = cand
        stats["套用"] += 1
    return stats
