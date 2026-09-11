#!/usr/bin/env python3
"""把翻譯後的檔案寫回 ``Data.wolf`` 封包。

WOLF 的 ``Game.exe`` 只讀封包裡的檔案，磁碟上的同名散檔會被忽略；
沒有封包則無法啟動。所以補丁必須做成新的 ``Data.wolf``。

作法刻意保守，把與原始封包的差異壓到最小：

* 未變動的檔案**連原始位元組帶位移一起沿用**——不重新壓縮、不重新加密，
  連在檔案裡的位置都不動。DXA 的每檔金鑰只跟檔名與大小有關、與位移無關，
  所以原封搬運是安全的。
* 只有被翻譯過的檔案重寫，以未壓縮形式接在資料區尾端。
* 標頭表沿用原本解出來的那一份，只就地改掉那幾個檔案的位移與大小欄位，
  因此檔名表、目錄表、其餘所有位移都保持原狀。
* 標頭表以 ``DXA_FLAG_NO_HEAD_PRESS`` 未壓縮寫入（DX Library 的解包與執行期
  兩條路徑都支援），這樣就不需要實作 Huffman／LZ 壓縮器。

用法::

    python repack_wolf.py <遊戲目錄> Data_zh -o Data.wolf.new
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wolfrpg.dxa import (
    NO_PRESS, DXArchive, DXArchiveError, huffman_encode, key_conv,
    lz_encode_stored,
)

CHUNK = 1 << 22  # 4 MiB


def encode_file_huffman(data: bytes, huffman_encode_kb: int,
                        key: bytes | None) -> tuple[bytes, int]:
    """Store one file the way this archive stores every other file.

    The original ``Data.wolf`` contains no fully-uncompressed entries -- every
    file is Huffman-packed, and large ones only have their first and last
    ``huffman_encode_kb`` KiB packed with the middle left raw.  Reproducing that
    exact shape keeps the rebuilt archive inside the range of layouts the engine
    is known to accept.

    Returns ``(stored_bytes, huff_press_data_size)``.
    """
    head_tail = huffman_encode_kb * 1024 * 2
    if huffman_encode_kb != 0xFF and len(data) > head_tail:
        edge = huffman_encode_kb * 1024
        packed = huffman_encode(data[:edge] + data[-edge:])
        middle = data[edge:len(data) - edge]
        stored = (key_conv(packed, len(data), key)
                  + key_conv(middle, len(data) + len(packed), key))
        return stored, len(packed)

    packed = huffman_encode(data)
    return key_conv(packed, len(data), key), len(packed)


def find_archive(target: Path) -> Path:
    if target.is_file():
        return target
    for name in ("Data.wolf", "Data.wolf.bak", "data.wolf"):
        candidate = target / name
        if candidate.is_file():
            return candidate
    matches = sorted(target.glob("**/Data.wolf")) or sorted(target.glob("**/Data.wolf.bak"))
    if matches:
        return matches[0]
    raise SystemExit(f"error: 在 {target} 底下找不到 Data.wolf")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="把翻譯後的檔案寫回 Data.wolf 封包")
    ap.add_argument("game", type=Path, help="遊戲目錄，或 Data.wolf 的路徑")
    ap.add_argument("replacements", type=Path,
                    help="含替換檔案的目錄（例如 import 產生的 Data_zh）")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="輸出的封包路徑（預設：<原檔>.new）")
    ap.add_argument("--key", default=None, help="封包金鑰字串（通常可自動偵測）")
    ap.add_argument("--verify", action="store_true", default=True,
                    help="寫出後重新解包驗證（預設開啟）")
    ap.add_argument("--no-verify", dest="verify", action="store_false")
    args = ap.parse_args(argv)

    archive_path = find_archive(args.game)
    output = args.output or archive_path.with_suffix(archive_path.suffix + ".new")

    try:
        archive = DXArchive(str(archive_path),
                            key_string=args.key.encode("ascii") if args.key else None)
    except DXArchiveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    head = archive.header
    if head.no_key:
        print("note: 這個封包沒有加密")

    print(f"原始封包 : {archive_path}")
    print(f"金鑰     : {getattr(archive, 'detected_key_name', '指定值')}")
    print(f"檔案數   : {len(archive.entries)}")

    # 1. 找出資料區的結尾，順便驗證我們對「每個檔案佔多少位元組」的理解無誤
    data_end = 0
    for entry in archive.entries:
        end = entry.data_address + entry.stored_size(head.huffman_encode_kb)
        data_end = max(data_end, end)
    absolute_data_end = head.data_start + data_end
    if absolute_data_end > head.name_table_start:
        print(f"error: 算出的資料區結尾 {absolute_data_end} 超過標頭表起點 "
              f"{head.name_table_start}，格式理解有誤，中止", file=sys.stderr)
        return 1
    slack = head.name_table_start - absolute_data_end
    print(f"資料區   : {head.data_start} .. {absolute_data_end} (尾端空隙 {slack} bytes)")

    # 2. 收集要替換的檔案
    replacements: dict[str, Path] = {}
    for root, _dirs, files in os.walk(args.replacements):
        for name in files:
            path = Path(root) / name
            rel = str(path.relative_to(args.replacements)).replace(os.sep, "/")
            replacements[rel] = path

    by_path = {e.path: e for e in archive.entries}
    changed = []
    unknown = []
    for rel, path in sorted(replacements.items()):
        entry = by_path.get(rel)
        if entry is None:
            unknown.append(rel)
            continue
        new_bytes = path.read_bytes()
        if new_bytes != archive.read(entry):
            changed.append((entry, new_bytes))

    for rel in unknown:
        print(f"warning: {rel} 不在原封包內，已略過", file=sys.stderr)
    if not changed:
        print("沒有任何檔案與原封包不同，不需要重新打包")
        archive.close()
        return 0

    print(f"要替換   : {len(changed)} 個檔案")
    for entry, new_bytes in changed:
        print(f"   {entry.path}  {entry.data_size} -> {len(new_bytes)} bytes")

    # 3. 寫出新封包
    head_buffer = bytearray(archive._head_buffer)
    file_table = head.file_table_start

    with open(archive_path, "rb") as src, open(output, "wb") as dst:
        # 3a. 原始標頭 + 整段資料區，原封搬運
        src.seek(0)
        remaining = absolute_data_end
        while remaining > 0:
            block = src.read(min(CHUNK, remaining))
            if not block:
                break
            dst.write(block)
            remaining -= len(block)

        # 3b. 被替換的檔案接在資料區尾端，用與其他檔案相同的 Huffman 形式
        for entry, new_bytes in changed:
            new_address = dst.tell() - head.data_start
            stored, huff_size = encode_file_huffman(
                new_bytes, head.huffman_encode_kb,
                None if head.no_key else entry._key)
            dst.write(stored)

            off = file_table + entry.header_offset
            # DARC_FILEHEAD: name, attributes, 3x time, dataAddress, dataSize,
            #                pressDataSize, huffPressDataSize
            struct.pack_into("<Q", head_buffer, off + 8 * 5, new_address)
            struct.pack_into("<Q", head_buffer, off + 8 * 6, len(new_bytes))
            struct.pack_into("<Q", head_buffer, off + 8 * 7, NO_PRESS)
            struct.pack_into("<Q", head_buffer, off + 8 * 8, huff_size)

        # 3c. 標頭表：與原封包一樣先 LZ 再 Huffman，最後以封包金鑰從位置 0 起 XOR。
        # 解包端是用「檔案結尾 - FileNameTableStartAddress」推算壓縮後長度的，
        # 所以標頭表必須是檔案裡的最後一段資料。
        name_table_start = dst.tell()
        compressed = huffman_encode(lz_encode_stored(bytes(head_buffer)))
        dst.write(key_conv(compressed, 0, None if head.no_key else archive.key))

        # 3d. 回頭改寫檔頭中的標頭表位址與大小。旗標維持原值——標頭一樣是壓縮的。
        # DARC_HEAD 版面："<HHIQQQQIIB15s" → HeadSize@4, FileNameTable@16,
        # FileTable@24, DirectoryTable@32, CharCodeFormat@40, Flags@44,
        # HuffmanEncodeKB@48
        src.seek(0)
        raw_head = bytearray(src.read(64))
        struct.pack_into("<I", raw_head, 4, len(head_buffer))
        struct.pack_into("<Q", raw_head, 16, name_table_start)
        dst.seek(0)
        dst.write(raw_head)

    archive.close()
    size = output.stat().st_size
    print(f"\n已寫出 : {output}  ({size / 1024 / 1024:.1f} MiB)")

    # 4. 驗證：重新解包，逐檔比對
    if not args.verify:
        return 0

    print("\n=== 驗證：重新解開新封包並逐檔比對 ===")
    try:
        rebuilt = DXArchive(str(output))
    except DXArchiveError as exc:
        print(f"error: 新封包無法解析: {exc}", file=sys.stderr)
        return 1

    original = DXArchive(str(archive_path))
    orig_by_path = {e.path: e for e in original.entries}
    replaced = {e.path: b for e, b in changed}

    if len(rebuilt.entries) != len(original.entries):
        print(f"error: 檔案數不符 {len(rebuilt.entries)} != {len(original.entries)}",
              file=sys.stderr)
        return 1

    mismatch = 0
    for entry in rebuilt.entries:
        got = rebuilt.read(entry)
        want = replaced.get(entry.path)
        if want is None:
            want = original.read(orig_by_path[entry.path])
        if got != want:
            mismatch += 1
            print(f"   不符: {entry.path} ({len(got)} vs {len(want)} bytes)")

    rebuilt.close()
    original.close()
    if mismatch:
        print(f"\n✗ {mismatch} 個檔案內容不符，不要使用這個封包", file=sys.stderr)
        return 1
    print(f"✓ {len(rebuilt.entries)} 個檔案全部一致"
          f"（其中 {len(changed)} 個是翻譯後的版本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
