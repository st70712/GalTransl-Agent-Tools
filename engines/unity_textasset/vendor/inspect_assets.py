#!/usr/bin/env python3
"""G1 量測（需 UnityPy）：Unity 版本、腳本後端、asset 檔、JSON 表與含日文欄位、TMP 字型、bundle 概況。

    python inspect_assets.py <遊戲根目錄或 *_Data>
"""

from __future__ import annotations

import argparse
import collections
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import JP, find_data_dir, iter_tables, load_env  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path)
    args = ap.parse_args(argv)
    data_dir = find_data_dir(args.data)
    root = data_dir.parent
    ver = ""
    with (data_dir / "globalgamemanagers").open("rb") as f:
        head = f.read(64)
    m = re.search(rb"\d+\.\d+\.\d+[a-z]\d+", head)
    ver = m.group(0).decode() if m else "?"
    backend = "IL2CPP" if (root / "GameAssembly.dll").exists() else ("Mono" if (data_dir / "Managed").exists() else "?")
    print(f"Unity {ver}  {backend}  資料目錄 {data_dir.name}")
    for name in ("resources.assets", "sharedassets0.assets", "level0", "level1", "level2", "level3"):
        p = data_dir / name
        if p.exists():
            print(f"  {name:<24} {p.stat().st_size:>12,} bytes")
    bundles = sorted(data_dir.glob("StreamingAssets/aa/*/*.bundle"))
    if bundles:
        print(f"  Addressables bundle {len(bundles)} 個，共 {sum(b.stat().st_size for b in bundles):,} bytes")

    env = load_env(data_dir / "resources.assets")
    types = collections.Counter(o.type.name for o in env.objects)
    print(f"\nresources.assets 物件 {len(env.objects)}：{dict(types.most_common(6))}")
    print("JSON 表格 TextAsset：")
    total = 0
    for t in iter_tables(env):
        jpf: collections.Counter = collections.Counter()
        for r in t.rows:
            for k, v in r.items():
                if isinstance(v, str) and JP.search(v):
                    jpf[k] += 1
        total += sum(jpf.values())
        print(f"  {t.name:<24} {len(t.rows):>5} rows  含日文欄位 {dict(jpf) or '-'}")
    print(f"  合計含日文的欄位值 {total}")

    sa = data_dir / "sharedassets0.assets"
    if sa.exists():
        env2 = load_env(sa)
        print("\nTMP 字型資產（缺字風險）：")
        for o in env2.objects:
            if o.type.name == "MonoBehaviour":
                raw = o.get_raw_data()
                if len(raw) > 300_000:
                    ln = struct.unpack("<I", raw[28:32])[0]
                    name = raw[32:32 + ln].decode("utf-8", "replace") if ln < 200 else "?"
                    print(f"  {name}  raw {len(raw):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
