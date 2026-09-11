"""往返／零翻譯導入的目錄比對。

``mode="bytes"``：逐位元組相同（Wolf 這類二進位格式）。
``mode="json"``：``json.load`` 後相等（RPG Maker 這類 JSON，重新序列化空白必然不同）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def diff_note(original: bytes, produced: bytes) -> str:
    """第一個不同位元組的位置與前後 8 bytes（抽自 GalTransl-sister/roundtrip_test.py:31-41）。"""
    if len(original) != len(produced):
        note = f"length {len(original)} -> {len(produced)}"
    else:
        note = f"length {len(original)} (same)"
    for i, (a, b) in enumerate(zip(original, produced, strict=False)):
        if a != b:
            lo = max(0, i - 8)
            return (f"{note}, first difference at byte {i}: "
                    f"{original[lo:i + 8].hex(' ')} -> {produced[lo:i + 8].hex(' ')}")
    return note


@dataclass
class TreeDiff:
    same: list[str] = field(default_factory=list)
    different: list[tuple[str, str]] = field(default_factory=list)
    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.different and not self.only_b

    def summary(self, label_a: str = "A", label_b: str = "B") -> str:
        lines = [f"{len(self.same)} 個檔案相同，{len(self.different)} 個不同，"
                 f"只在 {label_a}: {len(self.only_a)}，只在 {label_b}: {len(self.only_b)}"]
        for rel, note in self.different[:20]:
            lines.append(f"  DIFF {rel}: {note}")
        for rel in self.only_b[:20]:
            lines.append(f"  只在 {label_b}: {rel}")
        return "\n".join(lines)


def compare_file(a: Path, b: Path, mode: str = "bytes") -> str | None:
    """相同回傳 None，否則回傳說明。"""
    da, db = a.read_bytes(), b.read_bytes()
    if da == db:
        return None
    if mode == "json":
        try:
            if json.loads(da.decode("utf-8-sig")) == json.loads(db.decode("utf-8-sig")):
                return None
            return "JSON 內容不同"
        except (ValueError, UnicodeDecodeError) as e:
            return f"JSON 解析失敗: {e}"
    return diff_note(da, db)


def compare_trees(a: Path, b: Path, mode: str = "bytes", pattern: str = "**/*") -> TreeDiff:
    """以 b 為主：b 裡的每個檔案都必須在 a 裡且相同；a 多出來的只記錄不算錯。"""
    a, b = Path(a), Path(b)
    files_a = {p.relative_to(a).as_posix() for p in a.glob(pattern) if p.is_file()}
    files_b = {p.relative_to(b).as_posix() for p in b.glob(pattern) if p.is_file()}
    d = TreeDiff()
    for rel in sorted(files_b):
        if rel not in files_a:
            d.only_b.append(rel)
            continue
        note = compare_file(a / rel, b / rel, mode)
        if note is None:
            d.same.append(rel)
        else:
            d.different.append((rel, note))
    d.only_a = sorted(files_a - files_b)
    return d
