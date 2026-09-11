#!/usr/bin/env python3
"""翻譯後的整理步驟：讓譯文能安全地以 Big5(CP950) 寫回遊戲。

依序做四件事：

1. **簡繁正規化** — 用 opencc `s2twp` 把譯文轉成台灣繁體。Big5 只收錄繁體字，
   模型偶爾漏出的簡體字會編碼失敗，這一步把它們救回來。控制碼在轉換前先遮蔽，
   不會被動到。

2. **符號替換** — 原文裡的日文符號（ー・♪）Big5 沒有，換成語意最接近的
   Big5 字元（～‧）；另有少數模型愛用但不在 Big5 的口語字（嘞吡咔）。

3. **統一重複原文的譯法** — 同一段原文只保留一種譯文。這是 correctness 需求：
   `condition` 字串會與別處的值比對，兩邊譯法不同分支就永遠不觸發；
   順帶讓重複出現的選項與訊息在遊戲裡用字一致。

4. **控制碼把關** — 區分兩類碼：
   - *帶值的碼*（\\cself[n]、\\v[n]、\\cdb[..]、\\r[漢字,假名]）會在執行期插入
     實際內容，遺失就是內容不見或變數壞掉 → 整條退回原文，不冒險。
   - *純表現的碼*（\\c[n] 顏色、\\f[n] 字級、\\ax/\\ay 位置）遺失只是掉格式
     → 接受，僅回報。

用法:
    python fix_cp950.py exported/script.json
    python fix_cp950.py exported/script.json --dry-run
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

try:
    import opencc
except ImportError:
    print("error: 需要 opencc（conda activate nllb-env）", file=sys.stderr)
    raise SystemExit(1)

# 帶值的控制碼：遺失代表內容或變數不見了
VALUE_CODE_RE = re.compile(
    r'\\(?:cself\[[^\]]*\]|self\[[^\]]*\]|cdb\[[^\]]*\]|udb\[[^\]]*\]|'
    r'sdb\[[^\]]*\]|v\[[^\]]*\]|r\[[^\]]*\])'
)
# 純表現的控制碼：遺失只是掉格式。
# 尾端的 \> \< \. \! \^ \- \| 是 Wolf 的單字元碼（換行控制、等待、置中等）。
STYLE_CODE_RE = re.compile(
    r'\\(?:space\[[^\]]*\]|font\[[^\]]*\]|sp\[[^\]]*\]|ax\[[^\]]*\]|ay\[[^\]]*\]|'
    r'c\[[^\]]*\]|f\[[^\]]*\]|s\[[^\]]*\]|E|[><.!^|-])'
)
ANY_CODE_RE = re.compile(f"(?:{VALUE_CODE_RE.pattern}|{STYLE_CODE_RE.pattern})")

# 日文符號 → Big5 可編碼的近義字元
SYMBOL_MAP = {
    '\u30fc': '～',   # ー 長音記號 → 全形波浪（中文表拉長音的慣例）
    '\u30fb': '‧',   # ・ 中黑點 → 中文間隔號
    '\u266a': '～',   # ♪ 音符（Big5 沒有）→ 波浪，保留語氣
    '\u301c': '～',   # 〜 波浪號 → 全形波浪
    '\uff70': '～',   # ｰ 半形長音
    # 模型愛用、但不在 Big5 的口語字，換成 Big5 內的標準寫法。
    # 每一條都經人工確認語意等價，不是機械替換。
    '\u561e': '\u5566',   # 嘞 語氣助詞：好嘞 → 好啦
    '\u5421': '\u55f6',   # 吡 狀聲詞：吡嚕 → 嗶嚕
    '\u5494': '\u5580',   # 咔 狀聲詞：咔嚓 → 喀嚓
}

_PLACEHOLDER_BASE = 0xE000  # 私用區，opencc 不會動到


def convert_preserving_codes(converter, text: str) -> str:
    """簡繁轉換，但不碰控制碼。"""
    codes: list[str] = []

    def stash(match: re.Match) -> str:
        codes.append(match.group(0))
        return chr(_PLACEHOLDER_BASE + len(codes) - 1)

    masked = ANY_CODE_RE.sub(stash, text)
    converted = converter.convert(masked)
    for i, code in enumerate(codes):
        converted = converted.replace(chr(_PLACEHOLDER_BASE + i), code)
    return converted


def apply_symbol_map(text: str) -> str:
    for src, dst in SYMBOL_MAP.items():
        text = text.replace(src, dst)
    return text


# 模型偶爾會吐出「看起來像控制碼、但 Wolf 不認得」的反斜線序列。
# 常見兩種：字面的 \n（模型以為要用逃脫字元換行，Wolf 其實吃真正的換行），
# 以及在既有控制碼裡插進雜字（\EBADEND → \xEBADEND）。
LITERAL_NEWLINE_RE = re.compile(r'\\n')
STRAY_ESCAPE_RE = re.compile(r'\\[a-zA-Z]')


def stray_escapes(original: str, translated: str) -> list[str]:
    """回傳譯文裡不屬於任何已知 Wolf 控制碼的反斜線序列。

    原文本身用過的序列不算——這份遊戲資料就有 4 條台詞用字面 ``\\n`` 換行，
    原文用得出來的寫法，譯文照著用當然也沒問題。
    """
    known = set(STRAY_ESCAPE_RE.findall(ANY_CODE_RE.sub("", original)))
    return [e for e in STRAY_ESCAPE_RE.findall(ANY_CODE_RE.sub("", translated))
            if e not in known]


def unencodable_chars(text: str, encoding: str) -> list[str]:
    bad = []
    for ch in text:
        try:
            ch.encode(encoding)
        except UnicodeEncodeError:
            bad.append(ch)
    return bad


def lost_codes(pattern: re.Pattern, original: str, translated: str) -> list[str]:
    before = collections.Counter(pattern.findall(original))
    after = collections.Counter(pattern.findall(translated))
    return sorted((before - after).elements())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="翻譯後整理：正規化並確保可寫回遊戲")
    ap.add_argument("script", type=Path, help="翻譯後的 script.json")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="輸出檔（預設覆蓋原檔）")
    ap.add_argument("--encoding", default="cp950", help="目標編碼 (default: cp950)")
    ap.add_argument("--config", default="s2twp",
                    help="opencc 設定 (default: s2twp)")
    ap.add_argument("--no-symbol-map", action="store_true",
                    help="不做符號替換。SYMBOL_MAP 整張表都是 Big5 收不到字才要的"
                         "代打（ー→～、・→‧、嘞→啦…），目標編碼是 UTF-8 時"
                         "換掉只會讓譯文偏離原文")
    ap.add_argument("--dry-run", action="store_true", help="只報告，不寫檔")
    args = ap.parse_args(argv)
    if args.encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        args.no_symbol_map = True

    payload = json.loads(args.script.read_text(encoding="utf-8"))
    entries = payload["strings"]
    converter = opencc.OpenCC(args.config)

    translated = [e for e in entries if e["translated"]]
    stats = collections.Counter()

    # 1+2. 簡繁正規化與符號替換
    for entry in translated:
        new = convert_preserving_codes(converter, entry["translated"])
        if not args.no_symbol_map:
            new = apply_symbol_map(new)
        if new != entry["translated"]:
            stats["normalised"] += 1
            entry["translated"] = new

    # 3. 一致性：同一段原文只保留一種譯法
    #    correctness 上這是必要的——condition 字串會與別處的值比對，兩邊譯法不同
    #    分支就永遠不觸發；順帶讓重複出現的選項／訊息在遊戲裡用字一致。
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for entry in translated:
        votes[entry["original"]][entry["translated"]] += 1
    canonical = {}
    for original, counter in votes.items():
        if len(counter) <= 1:
            continue
        # 先排除掉控制碼的版本——統一時若選到殘缺的那個，等於把損失擴散出去。
        # 其後看出現次數，同票時取較短、再取字典序，確保結果可重現。
        def rank(kv: tuple[str, int]) -> tuple:
            text, count = kv
            lost = len(lost_codes(ANY_CODE_RE, original, text))
            return (lost, -count, len(text), text)

        canonical[original] = min(counter.items(), key=rank)[0]
    for entry in translated:
        target = canonical.get(entry["original"])
        if target and entry["translated"] != target:
            entry["translated"] = target
            stats["unified"] += 1

    # 3.5 模型自己生出來的字面 \n 換成真正的換行。
    #     遊戲資料本身有 4 條也用字面 \n，所以不能一律替換——原文有用的就照著用，
    #     維持與原文相同的結構；只有「原文沒有、譯文憑空多出來」的才換掉，
    #     因為絕大多數台詞都是用真正的換行，那是確定會斷行的寫法。
    for entry in translated:
        if LITERAL_NEWLINE_RE.search(entry["original"]):
            continue
        if LITERAL_NEWLINE_RE.search(entry["translated"]):
            entry["translated"] = LITERAL_NEWLINE_RE.sub("\n", entry["translated"])
            stats["literal_newline"] += 1

    # 4. 控制碼把關
    reverted = []
    style_lost = []
    stray = []
    for entry in translated:
        # 認不得的反斜線序列一律退回原文：它可能是被插了雜字的控制碼
        # （\EBADEND → \xEBADEND，等於 \E 失效），修不修得回無法確定，
        # 寧可留日文也不要送一段壞掉的控制碼進遊戲。
        found = stray_escapes(entry["original"], entry["translated"])
        if found:
            stray.append((entry, found))
            entry["translated"] = ""
            stats["stray_escape"] += 1
            continue
    for entry in translated:
        if not entry["translated"]:
            continue
        missing_value = lost_codes(VALUE_CODE_RE, entry["original"], entry["translated"])
        if missing_value:
            reverted.append((entry, missing_value))
            entry["translated"] = ""       # 退回原文，導入時保留日文
            stats["reverted"] += 1
            continue
        missing_style = lost_codes(STYLE_CODE_RE, entry["original"], entry["translated"])
        if missing_style:
            style_lost.append((entry, missing_style))
            stats["style_lost"] += 1

    # 5. 編碼檢查
    still_bad = []
    char_counter: collections.Counter = collections.Counter()
    for entry in translated:
        if not entry["translated"]:
            continue
        bad = unencodable_chars(entry["translated"], args.encoding)
        if bad:
            still_bad.append((entry, bad))
            char_counter.update(bad)

    print(f"譯文條目            : {len(translated)}")
    print(f"簡繁{'正規化' if args.no_symbol_map else '／符號正規化'}"
          f"{'        ' if args.no_symbol_map else '    '}: {stats['normalised']}"
          + ("（符號替換已關閉）" if args.no_symbol_map else ""))
    print(f"統一重複原文譯法    : {stats['unified']}")
    print(f"字面 \\n → 真換行     : {stats['literal_newline']}")
    print(f"雜訊控制碼→退回原文  : {stats['stray_escape']}")
    print(f"帶值控制碼遺失→退回 : {stats['reverted']}")
    print(f"表現控制碼遺失(容許) : {stats['style_lost']}")
    print(f"{args.encoding} 仍無法編碼     : {len(still_bad)}")

    if stray:
        print(f"\n退回原文的條目（含 Wolf 認不得的反斜線序列）:")
        for entry, codes in stray[:10]:
            print(f"  [{entry['index']}] {entry['source_file']} 出現 {', '.join(sorted(set(codes)))}")
        if len(stray) > 10:
            print(f"  ... 還有 {len(stray) - 10} 條")

    if reverted:
        print(f"\n退回原文的條目（帶值控制碼遺失，避免內容不見）:")
        for entry, codes in reverted[:10]:
            print(f"  [{entry['index']}] {entry['source_file']} 遺失 {', '.join(codes)}")
        if len(reverted) > 10:
            print(f"  ... 還有 {len(reverted) - 10} 條")

    if still_bad:
        print(f"\n仍無法編碼的字元（共 {len(char_counter)} 種）:")
        for ch, count in char_counter.most_common():
            print(f"  {ch!r}  U+{ord(ch):04X}  出現 {count} 次")
        print(f"\n受影響條目:")
        for entry, bad in still_bad[:15]:
            print(f"  [{entry['index']}] {''.join(bad)!r} : "
                  f"{entry['translated'][:55]!r}")
        if len(still_bad) > 15:
            print(f"  ... 還有 {len(still_bad) - 15} 條")
        print(f"\n導入時加 --skip-unencodable，這些條目會保留日文原文。")
    else:
        print(f"\n✅ 全部譯文都能以 {args.encoding} 寫回遊戲")

    if not args.dry_run:
        out = args.output or args.script
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\n已寫入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
