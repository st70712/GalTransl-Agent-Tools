#!/usr/bin/env python3
"""<引擎名> 文本導入／驗證工具骨架（標準 CLI 形狀）：

    python import_script.py validate SCRIPT [-e ENC]
    python import_script.py import   DATA SCRIPT -o OUT [-e ENC]
    python import_script.py verify   DATA OUT [-e ENC]

import：以 (source_file, location) 定位，original 不同就拒絕（stale），translated 為空就跳過。
verify：比對原始與導入後的資料樹，任何「不該變的東西變了」→ 非零退出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_validate(args) -> int:
    data = json.loads(Path(args.translation).read_text(encoding="utf-8"))
    done = sum(1 for e in data["strings"] if e.get("translated"))
    print(f"{done}/{len(data['strings'])} translated")
    # TODO: 編碼檢查、控制碼檢查、條件一致性…
    return 0


def cmd_import(args) -> int:
    raise NotImplementedError("TODO: import")


def cmd_verify(args) -> int:
    raise NotImplementedError("TODO: verify")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate"); p.add_argument("translation", type=Path); p.add_argument("-e", "--encoding", default="utf-8")
    p = sub.add_parser("import"); p.add_argument("data", type=Path); p.add_argument("translation", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True); p.add_argument("-e", "--encoding", default="utf-8")
    p = sub.add_parser("verify"); p.add_argument("original", type=Path); p.add_argument("patched", type=Path)
    p.add_argument("-e", "--encoding", default="utf-8")
    args = ap.parse_args(argv)
    return {"validate": cmd_validate, "import": cmd_import, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
