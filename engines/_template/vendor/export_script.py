#!/usr/bin/env python3
"""<引擎名> 文本導出工具骨架（標準 CLI 形狀）：

    python export_script.py DATA -o OUT [-e ENC]

輸出 OUT/script.json（格式見 docs/script-json.md）與 OUT/format_specification.json。
只用標準庫。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_entries(data: Path, encoding: str) -> list[dict]:
    # TODO: 走訪資料樹，對每一個玩家看得到、翻了不會壞的字串產生一條 entry。
    # location 必須能讓 import_script.py 唯一定位到同一個字串。
    raise NotImplementedError("TODO: build_entries")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("exported"))
    ap.add_argument("-e", "--encoding", default="utf-8")
    args = ap.parse_args(argv)

    entries = build_entries(args.data, args.encoding)
    for i, e in enumerate(entries):
        e["index"] = i
    payload = {
        "info": {"game_title": "", "engine": "TODO", "encoding": args.encoding,
                 "version": "1.0", "source_dir": str(args.data), "string_count": len(entries)},
        "strings": entries,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "script.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entries)} strings -> {args.output / 'script.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
