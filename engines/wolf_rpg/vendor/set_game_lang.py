#!/usr/bin/env python3
"""設定 ``Game.dat`` 的資料語言標記，用「不改變檔案長度」的方式。

WOLF RPG Editor 2.2x 的 ``Game.dat`` 有一個位元組記錄這份遊戲資料是用哪種語言
編碼的，引擎會據此決定文字要用哪個字碼頁解讀。它位在開頭那個 22 bytes 設定
陣列的第 17 格。

對照官方繁中版（RJ352237）與日文版（RJ338582）的 ``Game.dat``，其餘 21 格
完全相同，只有這一格從 1 變成 3；而 ``Game.exe`` 裡的分支是
``(byte + 1)`` 再查表，3+1=4 正好對應 "Chinese (Traditional)"。

**為什麼要原地改而不是重新序列化**：把 ``Game.dat`` 重新寫出來（例如翻譯了
視窗標題）會改變檔案長度，實測會讓遊戲無法啟動——尾端那 29000 bytes 的未知
資料裡應該存有絕對位移。這支工具只覆蓋一個位元組，長度完全不變。

用法::

    python set_game_lang.py Data/BasicData/Game.dat            # 查看目前設定
    python set_game_lang.py Data/BasicData/Game.dat --lang zh-tw
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

# 語言標記：Game.exe 讀出來會 +1 再查跳躍表
LANG_VALUES = {
    "ja": 1,       # +1=2，落在預設分支 → Japanese
    "ko": 2,       # +1=3 → Korean
    "zh-tw": 3,    # +1=4 → Chinese (Traditional)
    "zh-cn": 4,    # +1=5 → Chinese (Simplified)
}
LANG_NAMES = {v: k for k, v in LANG_VALUES.items()}

MAGIC = bytes([0x57, 0x00, 0x00, 0x4F, 0x4C, 0x00, 0x46, 0x4D, 0x00])
# 最後一個 byte 在 Wolf 2.x 是 0x00，Wolf 3.x 是 0x55。
MAGIC_VARIABLE = {8: frozenset({0x00, 0x55})}
LANG_INDEX = 17


def locate(raw: bytes) -> int:
    """回傳語言標記在檔案中的位元組位移。"""
    if raw[0] == 0:
        base = 1            # 未加密的 Game.dat 開頭有一個 0x00 標記
    else:
        raise SystemExit("error: 這個 Game.dat 有加密，本工具不支援")
    got = raw[base:base + len(MAGIC)]
    if len(got) != len(MAGIC) or any(
        (have != want) if i not in MAGIC_VARIABLE else (have not in MAGIC_VARIABLE[i])
        for i, (want, have) in enumerate(zip(MAGIC, got))
    ):
        raise SystemExit("error: Game.dat 的識別碼不符，可能不是 WOLF 的格式")
    count_at = base + len(MAGIC)
    count = struct.unpack_from("<i", raw, count_at)[0]
    if not 0 < count <= 256:
        raise SystemExit(f"error: 設定陣列長度異常 ({count})")
    if count <= LANG_INDEX:
        raise SystemExit(f"error: 設定陣列只有 {count} 格，沒有第 {LANG_INDEX} 格")
    return count_at + 4 + LANG_INDEX


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="設定 Game.dat 的資料語言標記（不改變檔案長度）")
    ap.add_argument("game_dat", type=Path)
    ap.add_argument("--lang", choices=sorted(LANG_VALUES),
                    help="要設定的語言；省略則只顯示目前設定")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="輸出檔（預設覆蓋原檔）")
    args = ap.parse_args(argv)

    raw = bytearray(args.game_dat.read_bytes())
    offset = locate(raw)
    current = raw[offset]
    print(f"檔案       : {args.game_dat}")
    print(f"標記位移   : {offset} (0x{offset:x})")
    print(f"目前值     : {current}"
          f"  ({LANG_NAMES.get(current, '未知')})")

    if args.lang is None:
        return 0

    target = LANG_VALUES[args.lang]
    if current == target:
        print(f"已經是 {args.lang}，不需要更動")
        return 0

    raw[offset] = target
    out = args.output or args.game_dat
    before = args.game_dat.stat().st_size
    out.write_bytes(bytes(raw))
    after = out.stat().st_size
    print(f"已設定為   : {target} ({args.lang})")
    print(f"檔案長度   : {before} -> {after}"
          f"  {'✓ 未改變' if before == after else '✗ 改變了，有問題'}")
    return 0 if before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
