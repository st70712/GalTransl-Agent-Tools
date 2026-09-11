#!/usr/bin/env python3
"""往返驗證骨架：解析每個資料檔 → 寫回 → 逐位元組比對。動任何文字前的硬性關卡。

    python roundtrip_test.py DATA
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def roundtrip_one(path: Path, out: Path) -> bytes:
    # TODO: 用你的解析器讀 path，再 dump 到 out，回傳 out 的位元組
    raise NotImplementedError("TODO: roundtrip_one")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path)
    args = ap.parse_args(argv)
    files = sorted(p for p in args.data.rglob("*") if p.is_file())   # TODO: 只挑有解析器的副檔名
    tmp = Path(tempfile.mkdtemp(prefix="roundtrip-"))
    ok = 0
    for path in files:
        produced = roundtrip_one(path, tmp / path.name)
        if produced == path.read_bytes():
            ok += 1
        else:
            print(f"DIFF {path}")
    print(f"{ok}/{len(files)} files reproduced byte for byte")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
