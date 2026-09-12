#!/usr/bin/env python3
"""破壞攔截測試用：複製一份容器檔並刻意弄壞一處結構（verify 必須攔到）。

    python breakage_inject.py <原容器檔（resources.assets 或 data.unity3d）> <輸出路徑> [--rules R.json]

破壞法：有 JSON 表 → 刪掉第一張多列表格的最後一列；否則 → 規則涵蓋的第一個 MonoBehaviour，
沿第一條規則路徑找到最深的陣列，刪掉最後一個元素（例如 mTopics[0].mLines 少一行）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import find_data_dir, iter_monobehaviours, iter_tables, load_env, load_rules, resolve_location, save_env, walk_path  # noqa: E402


def _break_mb(env, rules, data_dir: Path) -> str | None:
    for mbo in iter_monobehaviours(env, rules, data_dir):
        for rule in rules.monobehaviours.get(mbo.cls, []):
            for loc, _parent, _key in walk_path(mbo.tree, rule.path):
                # 找 location 裡最後一個有索引的片段：那個陣列刪掉最後一個元素
                segs = loc.split(".")
                for i in range(len(segs) - 1, -1, -1):
                    m = re.match(r"^(\w+)((?:\[\d+\])*)$", segs[i])
                    if m and m.group(2):
                        arr_loc = ".".join(segs[:i] + [m.group(1)])
                        parent, key = resolve_location(mbo.tree, arr_loc)
                        arr = parent[key]
                        if isinstance(arr, list) and len(arr) > 1:
                            del arr[-1]
                            mbo.save()
                            return f"{mbo.cls}@{mbo.path_id} 的 {arr_loc} 刪掉最後一個元素（{len(arr) + 1} → {len(arr)}）"
                break
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--rules", type=Path, default=None)
    args = ap.parse_args(argv)
    env = load_env(args.src)
    done = None
    for t in iter_tables(env):
        if len(t.rows) > 1:
            del t.rows[-1]
            t.data.m_Script = t.dump()
            t.data.save()
            done = f"刪掉表 {t.name} 的最後一列"
            break
    if done is None:
        try:
            data_dir = find_data_dir(args.src.parent)
        except SystemExit:
            data_dir = args.src.parent
        done = _break_mb(env, load_rules(args.rules), data_dir)
    if done is None:
        print("沒有可破壞的表或 MonoBehaviour（規則檔沒涵蓋任何物件？）")
        return 1
    print(done)
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    args.dst.write_bytes(save_env(env))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
