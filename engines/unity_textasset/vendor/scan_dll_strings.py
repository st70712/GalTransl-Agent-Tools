#!/usr/bin/env python3
"""掃 Mono 遊戲 DLL 的 IL：哪些方法用「含日文的字串常數」做事，以及緊接著呼叫了什麼（需 dnfile，.venv-unity）。

    python scan_dll_strings.py <Managed/ProjectRuntime.dll> [--grep 正則] [--all]

用途：找出程式碼拿**台詞原文**做比對的地方（例如 RJ01657316 的 `IsIntroBlackoutFadeLine` 用 `mText.StartsWith("同じサークルに所属する")`
決定開場黑幕何時淡出——台詞翻成中文就永遠對不上，畫面全黑）。這種字串必須：保留原文、或改譯文讓它仍符合、或連 DLL 一起改。
預設略過看起來像資產鍵／除錯訊息的字串（含 です／ません／シーン\\d_ …），--all 全印。
每行：<類別>::<方法>  '<字串>'  prev=<前一個呼叫/欄位>  next=[<後續三個呼叫>]；next 裡有 String::StartsWith／Contains／op_Equality 的就是比對點。
"""

from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

JP = re.compile(r"[぀-ヿ一-鿿]")
NOISE = re.compile(r"です|ません|ください|できません|スキップ|見つか|不正|重複|エントリ|カタログ|定義|遷移|ロード|プレハブ|割り当て|失敗|無効|設定|にしました|ルーティング|^シーン\d_|^\[")
CALL_OPS = (0x28, 0x6F)                     # call / callvirt
OPS_TOKEN = (0x72, 0x7B, 0x7C, 0x7D, 0x7E, 0x20, 0x8C, 0x74, 0x75, 0x8D, 0xA2, 0x70, 0x7F, 0x80, 0x81, 0xA4, 0xA5)
OPS_BYTE = (0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x1F, 0x0E, 0x10, 0x11, 0x12, 0x13)


def user_strings(us) -> dict[int, str]:
    out: dict[int, str] = {}
    data = us.__data__
    i = 1
    while i < len(data):
        b0 = data[i]
        if b0 & 0x80 == 0:
            ln, hdr = b0, 1
        elif b0 & 0xC0 == 0x80:
            ln, hdr = ((b0 & 0x3F) << 8) | data[i + 1], 2
        else:
            ln, hdr = ((b0 & 0x1F) << 24) | (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3], 4
        out[i] = data[i + hdr:i + hdr + ln - 1].decode("utf-16le", "replace") if ln > 1 else ""
        i += hdr + ln
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dll", type=Path)
    ap.add_argument("--grep", default=None, help="只印字串符合此正則的")
    ap.add_argument("--all", action="store_true", help="不過濾雜訊字串")
    args = ap.parse_args(argv)
    import dnfile  # 延遲載入

    pe = dnfile.dnPE(str(args.dll))
    md = pe.net.mdtables
    strings = user_strings(pe.net.user_strings)
    methods = list(md.MethodDef.rows)
    owner: dict[int, str] = {}
    for t in md.TypeDef.rows:
        for r in (t.MethodList if isinstance(t.MethodList, list) else []):
            owner[id(getattr(r, "row", r))] = t.TypeName

    def member_name(tok: int) -> str:
        tbl, idx = tok >> 24, tok & 0xFFFFFF
        try:
            if tbl == 0x0A:
                r = md.MemberRef.rows[idx - 1]
                cls = getattr(r.Class, "row", None)
                return f"{getattr(cls, 'TypeName', getattr(cls, 'Name', '?'))}::{r.Name}"
            if tbl == 0x06:
                r = methods[idx - 1]
                return f"{owner.get(id(r), '?')}::{r.Name}"
            if tbl == 0x04:
                return f"fld {md.Field.rows[idx - 1].Name}"
        except Exception:  # noqa: BLE001
            pass
        return f"tok{tok:08x}"

    def il_bytes(rva: int) -> bytes:
        off = pe.get_offset_from_rva(rva)
        b = pe.__data__
        hdr = b[off]
        if hdr & 3 == 2:
            return b[off + 1:off + 1 + (hdr >> 2)]
        flags = struct.unpack_from("<H", b, off)[0]
        hsz = (flags >> 12) * 4
        size = struct.unpack_from("<I", b, off + 4)[0]
        return b[off + hsz:off + hsz + size]

    want = re.compile(args.grep) if args.grep else None
    hits = 0
    for m in methods:
        if not m.Rva:
            continue
        try:
            il = il_bytes(m.Rva)
        except Exception:  # noqa: BLE001
            continue
        j = 0
        while j < len(il) - 5:
            if il[j] != 0x72:
                j += 1
                continue
            tok = struct.unpack_from("<I", il, j + 1)[0]
            s = strings.get(tok & 0xFFFFFF, "")
            ok = JP.search(s) and (args.all or not NOISE.search(s))
            if want is not None:
                ok = bool(want.search(s))
            if ok:
                nxt: list[str] = []
                k = j + 5
                while k < len(il) and len(nxt) < 3:
                    op = il[k]
                    if op in CALL_OPS:
                        nxt.append(member_name(struct.unpack_from("<I", il, k + 1)[0]))
                        k += 5
                    elif op in OPS_TOKEN:
                        k += 5
                    elif op in OPS_BYTE:
                        k += 2
                    elif op == 0xFE:
                        k += 2
                    else:
                        k += 1
                prev = ""
                for k2 in range(max(0, j - 6), j):
                    if il[k2] in (0x7B, 0x7E, 0x28, 0x6F):
                        prev = member_name(struct.unpack_from("<I", il, k2 + 1)[0])
                print(f"{owner.get(id(m), '?')}::{m.Name}  {s!r}  prev={prev}  next={nxt}")
                hits += 1
            j += 5
    print(f"hits {hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
