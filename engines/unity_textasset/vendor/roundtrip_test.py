#!/usr/bin/env python3
"""往返驗證（需 UnityPy）：每個容器檔載入 → 不改任何東西存回 → 重新載入，逐物件比對。

UnityPy 重新序列化的 SerializedFile **不會**逐位元組相同（標頭／對齊會變；bundle 的 LZ4HC 也會變成 LZ4），所以這裡的關卡是：
  - 物件集合（內部檔名、path_id、型別）相同、每個物件的 raw 內容相同
  - bundle 內的 .resS 等資源區塊逐位元組相同
  - 每張 JSON 表重新 dump 後與原文相同
  - 規則涵蓋的 MonoBehaviour：read_typetree → save_typetree 後 raw 與原本相同（證明 type tree 正確）
遊戲吃不吃重新序列化的檔案，要靠 smoke build 實機確認（見 NOTES.md）。

    python roundtrip_test.py <遊戲根目錄或 *_Data> [--rules R.json]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import (  # noqa: E402
    DEFAULT_ASSET_FILES, asset_files, find_data_dir, iter_monobehaviours, iter_tables, load_env, load_rules,
    resource_digests, save_env, serialized_files,
)


def _objects(env) -> dict[tuple[str, int], object]:
    return {(sf.name, pid): o for sf in serialized_files(env) for pid, o in sf.objects.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("--assets", nargs="*", default=list(DEFAULT_ASSET_FILES))
    ap.add_argument("--rules", type=Path, default=None)
    args = ap.parse_args(argv)
    data_dir = find_data_dir(args.data)
    rules = load_rules(args.rules)
    files = asset_files(data_dir, tuple(args.assets))
    ok = 0
    tmp = Path(tempfile.mkdtemp(prefix="agt-unity-rt-"))
    for path in files:
        env = load_env(path)
        problems: list[str] = []

        # 1. type tree 往返（在存回容器前做：save_typetree 只改記憶體內的物件 raw）
        mb_total = mb_bad = 0
        for mbo in iter_monobehaviours(env, rules, data_dir):
            before = mbo.obj.get_raw_data()
            mbo.save()
            mb_total += 1
            if mbo.obj.get_raw_data() != before:
                mb_bad += 1
                problems.append(f"{mbo.inner}#{mbo.path_id} {mbo.cls}: type tree 重存後 raw 不同（type tree 不對）")

        # 2. 容器往返
        saved = save_env(env)
        out = tmp / path.name
        out.write_bytes(saved)
        env2 = load_env(out)
        a, b = _objects(env), _objects(env2)
        if set(a) != set(b):
            problems.append(f"物件集合不同 {len(a)} vs {len(b)}")
        else:
            for key, x in a.items():
                y = b[key]
                if x.type.name != y.type.name:
                    problems.append(f"{key[0]}#{key[1]} 型別 {x.type.name}→{y.type.name}")
                elif x.get_raw_data() != y.get_raw_data():
                    problems.append(f"{key[0]}#{key[1]} ({x.type.name}) raw 不同")
                if len(problems) > 5:
                    break
        ra, rb = resource_digests(env), resource_digests(env2)
        if set(ra) != set(rb):
            problems.append(f"資源區塊集合不同 {sorted(ra)} vs {sorted(rb)}")
        else:
            for name in ra:
                if ra[name] != rb[name]:
                    problems.append(f"資源區塊 {name} 內容不同（{ra[name][0]:,} → {rb[name][0]:,}）")

        # 3. JSON 表
        tables = list(iter_tables(env))
        tables_bad = [t.name for t in tables if t.dump() != t.text]
        same_bytes = saved == path.read_bytes()
        status = "OK " if not problems and not tables_bad else "FAIL"
        print(f"{status} {path.relative_to(data_dir)}  物件 {len(a)}  資源區塊 {len(ra)}  "
              f"bytes {'相同' if same_bytes else f'不同（{path.stat().st_size:,} → {len(saved):,}）'}  "
              f"JSON 表 dump 相同: {len(tables) - len(tables_bad)}/{len(tables)}  "
              f"MonoBehaviour type tree 往返: {mb_total - mb_bad}/{mb_total}")
        for p in problems:
            print("     ", p)
        for name in tables_bad:
            print(f"      表 {name} 重新 dump 後與原文不同（import 仍可用，但零翻譯導入不會逐位元組相同）")
        if not problems and not tables_bad:
            ok += 1
        # 不刪 out：UnityPy 對散檔保持開啟的檔案控制代碼，Windows 上 unlink 會 PermissionError；暫存目錄由系統清
    print(f"{ok}/{len(files)} files reproduced (object-level)")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
