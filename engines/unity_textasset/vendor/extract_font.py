#!/usr/bin/env python3
"""從 Unity 遊戲抽出內嵌的 Font 物件（m_FontData：TTF／OTF 原始位元組），供其他遊戲的 inject_font.py 用（需 UnityPy）。

    python extract_font.py <遊戲根目錄或 *_Data> --list
    python extract_font.py <遊戲根目錄或 *_Data> --name NotoSansJP-Regular -o projects/<game>/font/NotoSansJP-Regular.otf

例：RJ01483219（秘密のシェアハウスせいかつ）內嵌 NotoSansJP-Regular（16,734 字），是目前驗證過能在 TMP 動態造字的 CJK 字型檔。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import asset_files, find_data_dir, inner_name, load_env  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--name", default=None, help="Font 物件的 m_Name")
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--assets", nargs="*", default=["resources.assets", "sharedassets0.assets", "sharedassets1.assets"])
    args = ap.parse_args(argv)
    data_dir = find_data_dir(args.data)
    found = []
    for path in asset_files(data_dir, tuple(args.assets)):
        env = load_env(path)
        for obj in env.objects:
            if obj.type.name != "Font":
                continue
            d = obj.read()
            fd = getattr(d, "m_FontData", None)
            raw = bytes(fd) if fd is not None else b""
            kind = "OTF" if raw[:4] == b"OTTO" else ("TTF" if raw[:4] in (b"\x00\x01\x00\x00", b"true") else "?")
            found.append((path.name, inner_name(obj), obj.path_id, d.m_Name, raw, kind))
    if args.list or not args.name:
        for f in found:
            print(f"{f[0]}[{f[1]}]#{f[2]}  {f[3]:<30} {len(f[4]):>10,} bytes  {f[5]}")
        return 0
    for f in found:
        if f[3] == args.name:
            out = args.output or Path(f"{args.name}.{'otf' if f[5] == 'OTF' else 'ttf'}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f[4])
            print(f"寫出 {out}（{len(f[4]):,} bytes，{f[5]}）")
            return 0
    print(f"找不到 Font 物件 {args.name!r}；可用：{[f[3] for f in found]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
