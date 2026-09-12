#!/usr/bin/env python3
"""Unity 文本導出（需 .venv-unity 的 UnityPy；MonoBehaviour 文本另需 TypeTreeGeneratorAPI）。

    python export_script.py <遊戲根目錄或 *_Data> -o exported [--rules unity_rules.json]

來源兩種（都由規則檔決定；見 unity_tables.py 模組說明）：
  1. JSON 表格 TextAsset（{"Rows":[…]}）——規則檔 ``tables``；沒有規則時所有含日文的字串欄位都當 context=text。
  2. MonoBehaviour／ScriptableObject 的欄位——規則檔 ``monobehaviours``（沒寫就不導出任何 MonoBehaviour）。
容器：散檔 resources.assets… 或單一 data.unity3d bundle，自動判斷。
輸出 exported/script.json（格式同其他引擎）與 format_specification.json。
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import (  # noqa: E402
    DEFAULT_ASSET_FILES, asset_files, container_kind, entries_for_mb, entries_for_table, env_is_bundle,
    find_data_dir, inner_name, iter_monobehaviours, iter_tables, load_env, load_rules, mb_source, table_source,
)

FORMAT_SPEC = {
    "engine": "Unity (JSON table TextAsset / MonoBehaviour fields)",
    "fields": {
        "source_file": "<容器檔相對於 *_Data 的路徑>#<TextAsset 名> 或 …#<內部檔>/<類別>@<path_id>，導入時定位用，不要改",
        "location": "JSON 表：Rows[<ID>]/<欄位>[/<子鍵>]；MonoBehaviour：欄位路徑如 mTopics[3].mLines[12].mText，不要改",
        "original": "原文；含真正的換行（可能是 \\r\\n）；<param#her_name> 之類是執行期替換的佔位符，必須原樣保留",
        "translated": "填入譯文；留空代表不翻",
        "context": "dialog / choice / system / database / speaker / ui / memo…（見 profile.json）",
        "speaker": "說話者（名字牌欄位），只供翻譯參考",
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
        "保留換行結構（\\r\\n 就保持 \\r\\n）；訊息視窗高度固定",
    ],
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, help="遊戲根目錄（含 *_Data）或 *_Data 本身")
    ap.add_argument("-o", "--output", type=Path, default=Path("exported"))
    ap.add_argument("-e", "--encoding", default="utf-8", help="（相容參數，Unity 一律 UTF-8）")
    ap.add_argument("--rules", type=Path, default=None, help="欄位規則 JSON")
    ap.add_argument("--assets", nargs="*", default=list(DEFAULT_ASSET_FILES), help="要掃的 asset 檔（相對 *_Data；bundle 建置忽略）")
    args = ap.parse_args(argv)

    data_dir = find_data_dir(args.data)
    rules = load_rules(args.rules)
    print(f"資料目錄: {data_dir}  （{container_kind(data_dir)}）")
    print(f"規則檔  : {args.rules if args.rules and args.rules.exists() else '（無，使用預設：含日文的字串欄位 → text；不導出 MonoBehaviour）'}")

    entries: list[dict] = []
    per_source: collections.Counter = collections.Counter()
    for path in asset_files(data_dir, tuple(args.assets)):
        env = load_env(path)
        rel = path.relative_to(data_dir).as_posix()
        bundle = env_is_bundle(env)
        for table in iter_tables(env):
            src = table_source(rel, inner_name(table.obj) if bundle else None, table.name)
            got = entries_for_table(src, table, rules)
            per_source[table.name] += len(got)
            entries.extend(got)
        for mbo in iter_monobehaviours(env, rules, data_dir):
            src = mb_source(rel, mbo.inner if bundle else None, mbo.cls, mbo.path_id)
            got = entries_for_mb(src, mbo, rules)
            per_source[f"{mbo.cls}@{mbo.inner}"] += len(got)
            entries.extend(got)

    for i, e in enumerate(entries):
        e["index"] = i
    entries = [{"index": e["index"], "source_file": e["source_file"], "location": e["location"],
                "original": e["original"], "translated": e["translated"], "context": e["context"],
                "speaker": e["speaker"], "code": e["code"]} for e in entries]
    payload = {
        "info": {"game_title": data_dir.name.removesuffix("_Data"), "engine": "unity_textasset",
                 "encoding": "utf-8", "version": "1.0", "source_dir": str(args.data),
                 "container": container_kind(data_dir), "string_count": len(entries)},
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
    print("  依來源:")
    for t, n in per_source.most_common():
        if n:
            print(f"    {t:<40} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
