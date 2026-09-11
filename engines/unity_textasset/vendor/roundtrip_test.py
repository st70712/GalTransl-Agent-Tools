#!/usr/bin/env python3
"""往返驗證（需 UnityPy）：每個 asset 檔載入 → 不改任何東西存回 → 重新載入，逐物件比對。

UnityPy 重新序列化的 SerializedFile **不會**逐位元組相同（標頭／對齊會變），所以這裡的關卡是：
物件集合（path_id、型別）相同、每個物件的 raw 內容相同、每張 JSON 表重新 dump 後與原文相同。
遊戲吃不吃重新序列化的檔案，要靠 smoke build 實機確認（見 NOTES.md）。

    python roundtrip_test.py <遊戲根目錄或 *_Data>
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import DEFAULT_ASSET_FILES, asset_files, find_data_dir, iter_tables, load_env  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path)
    ap.add_argument("--assets", nargs="*", default=list(DEFAULT_ASSET_FILES))
    args = ap.parse_args(argv)
    data_dir = find_data_dir(args.data)
    files = asset_files(data_dir, tuple(args.assets))
    ok = 0
    tmp = Path(tempfile.mkdtemp(prefix="agt-unity-rt-"))
    for path in files:
        env = load_env(path)
        saved = env.file.save()
        out = tmp / path.name
        out.write_bytes(saved)
        env2 = load_env(out)
        a = {o.path_id: o for o in env.objects}
        b = {o.path_id: o for o in env2.objects}
        problems: list[str] = []
        if set(a) != set(b):
            problems.append(f"物件集合不同 {len(a)} vs {len(b)}")
        else:
            for pid, x in a.items():
                y = b[pid]
                if x.type.name != y.type.name:
                    problems.append(f"#{pid} 型別 {x.type.name}→{y.type.name}")
                elif x.get_raw_data() != y.get_raw_data():
                    problems.append(f"#{pid} ({x.type.name}) raw 不同")
                if len(problems) > 5:
                    break
        tables_bad = []
        for t in iter_tables(env):
            if t.dump() != t.text:
                tables_bad.append(t.name)
        same_bytes = saved == path.read_bytes()
        status = "OK " if not problems and not tables_bad else "FAIL"
        print(f"{status} {path.relative_to(data_dir)}  物件 {len(a)}  bytes {'相同' if same_bytes else f'不同（{len(path.read_bytes()):,} → {len(saved):,}）'}  "
              f"JSON 重新 dump 與原文相同: {len(list(iter_tables(env))) - len(tables_bad)}/{len(list(iter_tables(env)))}")
        for p in problems:
            print("     ", p)
        for name in tables_bad:
            print(f"      表 {name} 重新 dump 後與原文不同（import 仍可用，但零翻譯導入不會逐位元組相同）")
        if not problems and not tables_bad:
            ok += 1
    print(f"{ok}/{len(files)} files reproduced (object-level)")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
