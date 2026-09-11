#!/usr/bin/env python3
"""破壞攔截測試用：複製一份 asset 檔並刪掉第一張多列表格的最後一列（verify 必須攔到）。

    python breakage_inject.py <原 resources.assets> <輸出路徑>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import iter_tables, load_env  # noqa: E402


def main(argv: list[str]) -> int:
    src, dst = Path(argv[1]), Path(argv[2])
    env = load_env(src)
    for t in iter_tables(env):
        if len(t.rows) > 1:
            del t.rows[-1]
            t.data.m_Script = t.dump()
            t.data.save()
            print(f"刪掉表 {t.name} 的最後一列")
            break
    else:
        print("沒有可破壞的表")
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(env.file.save())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
