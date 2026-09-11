#!/usr/bin/env python3
"""Unity JSON 表格 TextAsset 文本導出（需 .venv-unity 的 UnityPy）。

    python export_script.py <遊戲根目錄或 *_Data> -o exported [--rules unity_rules.json]

輸出 exported/script.json（格式同其他引擎）與 format_specification.json。
規則檔決定每張表的哪些欄位是玩家看得到的文字、屬於哪個 context、複合欄位怎麼拆；
沒有規則檔時，所有含日文的字串欄位都當作 context=text（Memo/Comment 除外）。
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import DEFAULT_ASSET_FILES, asset_files, entries_for_table, find_data_dir, iter_tables, load_env, load_rules  # noqa: E402

FORMAT_SPEC = {
    "engine": "Unity (JSON table TextAsset)",
    "fields": {
        "source_file": "<asset 檔相對於 *_Data 的路徑>#<TextAsset 名稱>，導入時定位用，不要改",
        "location": "Rows[<ID>]/<欄位> 或 Rows[<ID>]/<欄位>/<子鍵>（複合欄位 k=v,k=v），不要改",
        "original": "原文；含真正的換行；<param#her_name> 之類是執行期替換的佔位符，必須原樣保留",
        "translated": "填入譯文；留空代表不翻",
        "context": "dialog / choice / system / database / speaker / ui / memo…（見 profile.json）",
        "speaker": "說話者（DrawMessageWindow 的 Name=），只供翻譯參考",
    },
    "control_codes": {
        "<param#xxx>": "佔位符，執行期換成名字等，必須保留",
        "<size=N>…</size>": "TextMeshPro 富文本標籤，成對保留",
        "\\n": "少數欄位用字面 \\n 換行（原文有才保留）",
    },
    "ai_agent_guidelines": [
        "只填 translated；不要動 index / source_file / location",
        "複合欄位（location 有第三段，如 /Name、/Choice1、/Message）的譯文不能含半形逗號或等號",
        "保留 <param#…> 佔位符與成對的富文本標籤",
        "保留換行結構；訊息視窗高度固定",
    ],
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, help="遊戲根目錄（含 *_Data）或 *_Data 本身")
    ap.add_argument("-o", "--output", type=Path, default=Path("exported"))
    ap.add_argument("-e", "--encoding", default="utf-8", help="（相容參數，Unity 一律 UTF-8）")
    ap.add_argument("--rules", type=Path, default=None, help="欄位規則 JSON")
    ap.add_argument("--assets", nargs="*", default=list(DEFAULT_ASSET_FILES), help="要掃的 asset 檔（相對 *_Data）")
    args = ap.parse_args(argv)

    data_dir = find_data_dir(args.data)
    rules = load_rules(args.rules)
    print(f"資料目錄: {data_dir}")
    print(f"規則檔  : {args.rules if args.rules and args.rules.exists() else '（無，使用預設：含日文的字串欄位 → text）'}")

    entries: list[dict] = []
    per_table: collections.Counter = collections.Counter()
    for path in asset_files(data_dir, tuple(args.assets)):
        env = load_env(path)
        rel = path.relative_to(data_dir).as_posix()
        for table in iter_tables(env):
            got = entries_for_table(f"{rel}#{table.name}", table, rules)
            per_table[table.name] += len(got)
            entries.extend(got)

    for i, e in enumerate(entries):
        e["index"] = i
    entries = [{"index": e["index"], "source_file": e["source_file"], "location": e["location"],
                "original": e["original"], "translated": e["translated"], "context": e["context"],
                "speaker": e["speaker"], "code": e["code"]} for e in entries]
    payload = {
        "info": {"game_title": data_dir.name.removesuffix("_Data"), "engine": "unity_textasset",
                 "encoding": "utf-8", "version": "1.0", "source_dir": str(args.data),
                 "string_count": len(entries)},
        "strings": entries,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "script.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "format_specification.json").write_text(json.dumps(FORMAT_SPEC, ensure_ascii=False, indent=2), encoding="utf-8")

    by_ctx = collections.Counter(e["context"] for e in entries)
    print(f"\n導出 {len(entries)} 條 → {args.output / 'script.json'}")
    print("  依 context:")
    for c, n in by_ctx.most_common():
        print(f"    {c:<14} {n}")
    print("  依表:")
    for t, n in per_table.most_common():
        print(f"    {t:<24} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
