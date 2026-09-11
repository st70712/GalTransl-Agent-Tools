#!/usr/bin/env python3
"""把舊 script.json 的譯文接到新 script.json，以**原文字串**為對應鍵。

``export_script.py --merge`` 是用 ``(source_file, location)`` 對應，那在同一份
遊戲資料上很準，但**跨遊戲版本會全部錯位**——正式版多了幾千條指令，位置全變了。
這支工具改用原文字串對應，所以可以把試玩版翻好的譯文接到正式版上。

    python merge_by_text.py exported_full/script.json --from exported/script.json

安全規則：

* 原文必須**完全相同**才套用，不做模糊比對
* 套用後控制碼必須與原文一致（帶值的碼一個都不能少），否則跳過
* ``game_title`` 不套（翻了會改變 ``Game.dat`` 長度）
* ``condition`` 只在「同一段原文也出現在其他 context」時才套。條件字串會在執行期
  與別處指派的值比對，只翻一邊會讓分支無聲地永遠不執行；同一段原文在各處都套用
  同一份譯文，兩邊才會繼續相等。找不到對應方的孤兒維持原文。
* 預設不覆蓋新檔已有的譯文（``--overwrite`` 可改）
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fix_cp950 import VALUE_CODE_RE, STYLE_CODE_RE, lost_codes

SKIP_CONTEXTS = ("game_title",)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="以原文為鍵接續舊譯文")
    ap.add_argument("target", type=Path, help="要填入譯文的 script.json")
    ap.add_argument("--from", dest="source", type=Path, required=True,
                    help="舊版的 script.json（提供譯文）")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="輸出路徑（預設就地覆寫 target）")
    ap.add_argument("--overwrite", action="store_true",
                    help="連 target 已有的譯文也一併覆蓋")
    args = ap.parse_args(argv)

    target = load(args.target)
    source = load(args.source)

    memory: dict[str, str] = {}
    clashes = 0
    for entry in source["strings"]:
        translated = entry.get("translated") or ""
        original = entry.get("original") or ""
        if not translated or translated == original:
            continue
        if original in memory and memory[original] != translated:
            clashes += 1
            continue
        memory[original] = translated

    # 哪些原文有「非 condition」的對應方，決定 condition 能不能翻
    non_condition = {
        e["original"] for e in target["strings"]
        if e["context"] != "condition"
    }

    stats = collections.Counter()
    for entry in target["strings"]:
        original = entry.get("original") or ""
        if entry["context"] in SKIP_CONTEXTS:
            continue
        if entry.get("translated") and not args.overwrite:
            stats["已有譯文，跳過"] += 1
            continue
        candidate = memory.get(original)
        if candidate is None:
            continue
        if entry["context"] == "condition" and original not in non_condition:
            stats["condition 孤兒，保留原文"] += 1
            continue
        if lost_codes(VALUE_CODE_RE, original, candidate):
            stats["帶值控制碼遺失，跳過"] += 1
            continue
        # 多出來的帶值碼同樣危險：舊版的翻譯記憶擴散時，可能把別條原文的
        # \cself[n] 帶進一段本來沒有變數的字串，在遊戲裡就是插入一個無關的值。
        if lost_codes(VALUE_CODE_RE, candidate, original):
            stats["憑空多出帶值控制碼，跳過"] += 1
            continue
        if lost_codes(STYLE_CODE_RE, original, candidate):
            stats["表現控制碼遺失，跳過"] += 1
            continue
        entry["translated"] = candidate
        stats["套用"] += 1

    total = len(target["strings"])
    filled = sum(1 for e in target["strings"] if e.get("translated"))
    out = args.output or args.target
    out.write_text(json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"舊譯文     : {len(memory)} 種原文"
          + (f"（{clashes} 種有多版譯法，已跳過）" if clashes else ""))
    for label, count in stats.most_common():
        print(f"{label:<22}: {count}")
    print(f"\n已翻譯     : {filled}/{total} ({filled / total:.1%})")
    print(f"寫入       : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
