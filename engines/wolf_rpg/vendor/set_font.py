#!/usr/bin/env python3
"""查看或更換 ``Game.dat`` 指定的字型，用「不改變檔案長度」的方式。

遊戲內建的日文字型不一定收錄所有中文字。官方繁中版（RJ352237）就是把主字型
換成系統中文字型 ``Microsoft Yahei UI Bold`` 來解決這件事。

**為什麼要原地改而不是重新序列化**：``Game.dat`` 只要總長度變了，遊戲就無法
啟動（實測翻譯視窗標題讓檔案少 10 bytes 就開不起來，尾端那 29000 bytes 未知
資料裡應該存有絕對位移）。

字串在檔案裡是「4 bytes 長度 + 內容 + NUL」。這支工具把新名稱寫進原本的欄位，
不足的部分用 NUL 補滿——引擎取字串時會停在第一個 NUL，所以讀到的是正確名稱，
而長度前綴與整個檔案的長度都不變。因此**新名稱不能比原本的長**。

用法::

    python set_font.py Data/BasicData/Game.dat
    python set_font.py Data/BasicData/Game.dat --font "Microsoft Yahei UI Bold"

常見的中文系統字型（Windows 內建，不需另外散佈）::

    Microsoft JhengHei UI Bold   微軟正黑體  繁體中文，26 bytes
    Microsoft Yahei UI Bold      微軟雅黑    簡體中文字型但含繁體字，23 bytes
    PMingLiU                     新細明體    全版本都有
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MAGIC = bytes([0x57, 0x00, 0x00, 0x4F, 0x4C, 0x00, 0x46, 0x4D, 0x00])
# 最後一個 byte 在 Wolf 2.x 是 0x00，Wolf 3.x 是 0x55。
MAGIC_VARIABLE = {8: frozenset({0x00, 0x55})}
MAGIC_STRING = b"0000-0000"


class Field:
    """Game.dat 裡一個長度前綴字串欄位的位置。"""

    __slots__ = ("name", "offset", "capacity", "value")

    def __init__(self, name: str, offset: int, capacity: int, value: bytes):
        self.name = name          # 欄位用途
        self.offset = offset      # 內容的起始位移（長度前綴之後）
        self.capacity = capacity  # 內容可用的位元組數（不含結尾 NUL）
        self.value = value        # 目前的內容（切到第一個 NUL）


def parse(raw: bytes) -> dict[str, Field]:
    """走訪 Game.dat 的前段，回傳各字串欄位的位置。"""
    if raw[0] != 0:
        raise SystemExit("error: 這個 Game.dat 有加密，本工具不支援")
    pos = 1
    got = raw[pos:pos + len(MAGIC)]
    if len(got) != len(MAGIC) or any(
        (have != want) if i not in MAGIC_VARIABLE else (have not in MAGIC_VARIABLE[i])
        for i, (want, have) in enumerate(zip(MAGIC, got))
    ):
        raise SystemExit("error: Game.dat 識別碼不符，可能不是 WOLF 的格式")
    pos += len(MAGIC)

    count = struct.unpack_from("<i", raw, pos)[0]
    pos += 4 + count                      # unknown1
    file_version = struct.unpack_from("<i", raw, pos)[0]
    pos += 4

    fields: dict[str, Field] = {}

    def read_string(label: str | None) -> bytes:
        nonlocal pos
        size = struct.unpack_from("<i", raw, pos)[0]
        pos += 4
        body = raw[pos:pos + size - 1]
        if label is not None:
            fields[label] = Field(label, pos, size - 1, body.split(b"\0", 1)[0])
        pos += size
        return body

    read_string("title")
    magic_string = read_string(None)
    if magic_string.split(b"\0", 1)[0] != MAGIC_STRING:
        raise SystemExit(f"error: magic string 不符 (讀到 {magic_string!r})")

    count = struct.unpack_from("<i", raw, pos)[0]
    pos += 4 + count                      # unknown2

    read_string("font")
    for i in range(3):
        read_string(f"subfont{i + 1}")
    read_string("default_pc_graphic")
    if file_version >= 9:
        read_string("version")
    return fields


def show(fields: dict[str, Field], encoding: str) -> None:
    for field in fields.values():
        text = field.value.decode(encoding, errors="replace")
        print(f"  {field.name:18s} {text!r:34} "
              f"(位移 {field.offset}, 可用 {field.capacity} bytes, "
              f"目前用 {len(field.value)})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="查看或更換 Game.dat 的字型（不改變檔案長度）")
    ap.add_argument("game_dat", type=Path)
    ap.add_argument("--font", default=None, help="新的主字型名稱")
    ap.add_argument("--subfont1", default=None, help="新的第一副字型名稱")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="輸出檔（預設覆蓋原檔）")
    ap.add_argument("-e", "--encoding", default="cp932",
                    help="字型名稱的編碼 (default: cp932；ASCII 名稱不受影響)")
    args = ap.parse_args(argv)

    raw = bytearray(args.game_dat.read_bytes())
    fields = parse(bytes(raw))

    print(f"檔案: {args.game_dat}")
    show(fields, args.encoding)

    changes = [("font", args.font), ("subfont1", args.subfont1)]
    changes = [(k, v) for k, v in changes if v is not None]
    if not changes:
        return 0

    print()
    for key, new_name in changes:
        field = fields[key]
        try:
            encoded = new_name.encode(args.encoding)
        except UnicodeEncodeError:
            print(f"error: {new_name!r} 無法以 {args.encoding} 編碼", file=sys.stderr)
            return 1
        if len(encoded) > field.capacity:
            print(f"error: {key} 新名稱需要 {len(encoded)} bytes，"
                  f"但欄位只有 {field.capacity} bytes。"
                  f"改長會變動檔案長度而讓遊戲無法啟動，請換一個較短的名稱。",
                  file=sys.stderr)
            return 1
        # 寫入新名稱，剩餘空間補 NUL：引擎取字串時會停在第一個 NUL
        raw[field.offset:field.offset + field.capacity] = (
            encoded + b"\0" * (field.capacity - len(encoded))
        )
        print(f"  {key:18s} -> {new_name!r}  "
              f"({len(encoded)}/{field.capacity} bytes，其餘補 NUL)")

    out = args.output or args.game_dat
    before = args.game_dat.stat().st_size
    out.write_bytes(bytes(raw))
    after = out.stat().st_size
    print(f"\n檔案長度 {before} -> {after}  "
          f"{'✓ 未改變' if before == after else '✗ 改變了，有問題'}")
    return 0 if before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
