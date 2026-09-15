#!/usr/bin/env python3
"""原地改寫 Mono DLL 的 #US 字串堆（需 dnfile，.venv-unity）：

    python patch_dll_strings.py <Managed/X.dll> -o OUT.dll --map mapping.json [--dry-run]

mapping.json：``{"原字串": "新字串", ...}``（也接受 rules 檔裡 ``dll_strings`` 區塊的內層 dict）。
規則：#US 的字串靠**偏移**索引，所以每個 blob 只能原地覆蓋：新字串的 UTF-16 位元組數 ≤ 原字串才行，
多出來的位元組補 0（未被引用的垃圾，安全）；長度前綴的位元組數也必須不變（<128 位元組是 1 byte，
128–16383 是 2 bytes）。超過就報錯，請縮短譯文。每個 blob 只覆蓋一次；同一個字串常數被多個方法共用時全部一起變。
用途：遊戲程式碼拿台詞原文做比對（`Contains("同じサークルに所属する")` 決定黑幕淡出）、或寫死顯示文字
（`ShowStaticLine("あなた", "（さて… 何を注文しようかな？）")`）時，讓譯文與程式碼一致。先用 scan_dll_strings.py 找。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def us_blobs(data: bytes) -> list[tuple[int, int, int, str]]:
    """[(blob 起點, 前綴長度, 內容長度含終端位元組, 字串)]。"""
    out = []
    i = 1
    while i < len(data):
        b0 = data[i]
        if b0 & 0x80 == 0:
            ln, hdr = b0, 1
        elif b0 & 0xC0 == 0x80:
            ln, hdr = ((b0 & 0x3F) << 8) | data[i + 1], 2
        else:
            ln, hdr = ((b0 & 0x1F) << 24) | (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3], 4
        s = data[i + hdr:i + hdr + ln - 1].decode("utf-16le", "replace") if ln > 1 else ""
        out.append((i, hdr, ln, s))
        i += hdr + ln
    return out


def encode_len(n: int, hdr: int) -> bytes:
    if hdr == 1:
        if n >= 0x80:
            raise ValueError("長度前綴 1 byte 放不下")
        return bytes([n])
    if hdr == 2:
        return bytes([0x80 | (n >> 8), n & 0xFF])
    return bytes([0xC0 | (n >> 24), (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dll", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    import dnfile  # 延遲載入

    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    if "dll_strings" in mapping:  # rules 檔
        mapping = mapping["dll_strings"].get(args.dll.name) or next(iter(mapping["dll_strings"].values()))
    pe = dnfile.dnPE(str(args.dll))
    us = pe.net.user_strings
    base = us.rva  # stream 的 RVA
    file_off = pe.get_offset_from_rva(base)
    data = bytearray(args.dll.read_bytes())
    blob_data = bytes(us.__data__)
    blobs = us_blobs(blob_data)
    by_str: dict[str, list[tuple[int, int, int]]] = {}
    for start, hdr, ln, s in blobs:
        by_str.setdefault(s, []).append((start, hdr, ln))
    errors = 0
    done = 0
    for old, new in mapping.items():
        if old not in by_str:
            print(f"  ✗ 找不到字串常數 {old!r}")
            errors += 1
            continue
        new_b = new.encode("utf-16le")
        for start, hdr, ln in by_str[old]:
            room = ln - 1  # 扣掉終端位元組
            if len(new_b) > room:
                print(f"  ✗ {old!r} → {new!r}：{len(new_b)} bytes 放不進 {room} bytes（縮短譯文，最多 {room // 2} 字）")
                errors += 1
                continue
            new_ln = len(new_b) + 1
            try:
                prefix = encode_len(new_ln, hdr)
            except ValueError as e:
                print(f"  ✗ {old!r}：{e}")
                errors += 1
                continue
            # 終端位元組：原本的最後一個 byte（0 或 1，表示有無需要特別處理的字元），保留
            term = blob_data[start + hdr + ln - 1]
            patch = prefix + new_b + bytes([term]) + b"\x00" * (room - len(new_b))
            assert len(patch) == hdr + ln
            off = file_off + start
            if not args.dry_run:
                data[off:off + len(patch)] = patch
            print(f"  ✓ {old!r} → {new!r}  (@#US+{start:#x}, {len(new_b)}/{room} bytes)")
            done += 1
    if errors:
        print(f"✗ {errors} 個錯誤，未寫檔")
        return 1
    if args.dry_run:
        print(f"（dry-run）{done} 個 blob 可覆蓋")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bytes(data))
    # 回讀驗證
    pe2 = dnfile.dnPE(str(args.output))
    got = {s for _, _, _, s in us_blobs(bytes(pe2.net.user_strings.__data__))}
    missing = [new for new in mapping.values() if new not in got]
    if missing:
        print(f"✗ 回讀後找不到：{missing}")
        return 1
    print(f"✓ {args.output}：{done} 個字串常數已覆蓋，回讀驗證通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
