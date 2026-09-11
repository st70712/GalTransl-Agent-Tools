#!/usr/bin/env python3
"""Unity JSON 表格 TextAsset 的譯文檢查／導入／結構驗證（需 .venv-unity 的 UnityPy）。

    python import_script.py validate exported/script.json
    python import_script.py import   <遊戲根目錄> exported/script.json -o translated [--rules R.json]
    python import_script.py verify   <遊戲根目錄> translated [--rules R.json]

import：只重寫「有譯文變動」的 asset 檔（例如 *_Data/resources.assets），寫到 OUT/<*_Data>/…；
        沒有任何變動就不產生檔案。TextAsset 以外的物件原樣保留。
verify：OUT 裡每個 asset 檔與原檔逐物件比對：非 TextAsset 物件 raw 必須相同；表格 TextAsset 的列數、
        ID 順序、非規則欄位、複合欄位的子鍵序列、<param#…> 佔位符都必須一致。任何錯誤 → exit 1。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import (  # noqa: E402
    JP, Rules, asset_files, entries_for_table, apply_entry, find_data_dir, iter_tables, load_env,
    load_rules, parse_location, split_kv,
)

PLACEHOLDER_RE = re.compile(r"<param#[^>]+>")
TAG_RE = re.compile(r"</?([a-zA-Z-]+)(?:=[^>]*)?>")


def _load_script(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- validate -------------------------------------------------------------------

def cmd_validate(args) -> int:
    data = _load_script(args.translation)
    strings = data["strings"]
    total = len(strings)
    done = [e for e in strings if e.get("translated")]
    by_ctx = collections.Counter(e["context"] for e in strings)
    done_ctx = collections.Counter(e["context"] for e in done)
    print(f"翻譯進度 {len(done)}/{total} ({len(done) / total:.1%})" if total else "空檔")
    for c in sorted(by_ctx, key=lambda c: -by_ctx[c]):
        print(f"   {c:<14} {done_ctx[c]:>6}/{by_ctx[c]:<6}")

    hard: list[str] = []
    soft: list[str] = []
    for e in done:
        o, t, loc = e["original"], e["translated"], e["location"]
        _, _, sub = parse_location(loc)
        if sub is not None and ("," in t or "=" in t):
            hard.append(f"[{e['index']}] {loc} 複合欄位譯文含半形逗號／等號（import 會改成全形）: {t[:40]!r}")
        if collections.Counter(PLACEHOLDER_RE.findall(o)) != collections.Counter(PLACEHOLDER_RE.findall(t)):
            hard.append(f"[{e['index']}] {loc} 佔位符不一致: {PLACEHOLDER_RE.findall(o)} → {PLACEHOLDER_RE.findall(t)}")
        if collections.Counter(TAG_RE.findall(o)) != collections.Counter(TAG_RE.findall(t)):
            soft.append(f"[{e['index']}] {loc} 富文本標籤不一致: {TAG_RE.findall(o)} → {TAG_RE.findall(t)}")
        if o.count("\n") != t.count("\n"):
            soft.append(f"[{e['index']}] {loc} 行數 {o.count(chr(10)) + 1}→{t.count(chr(10)) + 1}")
    visible = [e for e in strings if not e.get("translated") and e["context"] not in ("memo", "label_memo")
               and JP.search(e["original"])]
    print(f"\n檢查：{len(hard)} 個必須處理、{len(soft)} 個警告；玩家看得到但仍是日文 {len(visible)} 條")
    for line in hard[:20]:
        print("  ✗", line)
    for line in soft[:10]:
        print("  ⚠", line)
    if args.output_untranslated:
        want = set(args.contexts) if args.contexts and "all" not in args.contexts else None
        subset = [e for e in visible if want is None or e["context"] in want]
        out = {"info": {**data["info"], "string_count": len(subset), "note": "未翻譯條目；填好後可直接 import"},
               "strings": subset}
        args.output_untranslated.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"未翻譯條目已輸出 {len(subset)} 條 → {args.output_untranslated}")
    return 1 if hard else 0


# -- import ---------------------------------------------------------------------

def cmd_import(args) -> int:
    data_dir = find_data_dir(args.data)
    script = _load_script(args.translation)
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for e in script["strings"]:
        if e.get("translated"):
            by_source[e["source_file"]].append(e)
    if not by_source:
        print("沒有任何譯文，不產生檔案")
        return 0
    out_root = args.output / data_dir.name
    applied = changed_tables = 0
    stale = 0
    warnings: list[str] = []
    written: list[Path] = []
    wanted_assets = sorted({s.split("#", 1)[0] for s in by_source})
    for rel in wanted_assets:
        path = data_dir / rel
        if not path.exists():
            print(f"✗ 找不到 {path}")
            return 1
        env = load_env(path)
        file_changed = False
        for table in iter_tables(env):
            entries = by_source.get(f"{rel}#{table.name}")
            if not entries:
                continue
            # 原文必須仍然對得上（stale 檢查）：重新導出這張表的 original 對照
            current = {e["location"]: e["original"] for e in entries_for_table(f"{rel}#{table.name}", table, Rules(default_context="x"))}
            table_changed = False
            for e in entries:
                cur = current.get(e["location"])
                if cur is None:
                    # 規則可能不同（例如 memo 沒被預設規則抓到），直接用 apply 的比對
                    pass
                elif cur != e["original"]:
                    stale += 1
                    continue
                ok, warn = apply_entry(table, e["location"], e["translated"])
                if warn:
                    warnings.append(warn)
                if ok:
                    applied += 1
                    table_changed = True
            if table_changed:
                table.data.m_Script = table.dump()
                table.data.save()
                changed_tables += 1
                file_changed = True
        if file_changed:
            dst = out_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(env.file.save())
            written.append(dst)
    print(f"套用 {applied} 條譯文到 {changed_tables} 張表；原文已變、跳過 {stale} 條")
    for w in warnings[:20]:
        print("  ⚠", w)
    if len(warnings) > 20:
        print(f"  … 還有 {len(warnings) - 20} 個警告")
    print("實際有變動、需散佈的檔案:")
    for p in written:
        print(f"   {p.relative_to(args.output)}  ({p.stat().st_size:,} bytes)")
    if not args.no_verify and written:
        print("\n=== 導入後結構驗證 ===")
        return cmd_verify(argparse.Namespace(data=args.data, patched=args.output, rules=args.rules))
    return 0


# -- verify ---------------------------------------------------------------------

def _rule_fields(rules: Rules, table) -> dict[str, list]:
    """每個欄位允許變動的方式：{'Arg2': [Rule…]}。"""
    out: dict[str, list] = collections.defaultdict(list)
    for r in rules.for_table(table):
        out[r.field].append(r)
    return out


def cmd_verify(args) -> int:
    data_dir = find_data_dir(args.data)
    out_root = Path(args.patched) / data_dir.name
    if not out_root.exists():
        files = [x for x in Path(args.patched).rglob("*") if x.is_file()] if Path(args.patched).exists() else []
        if not files:
            print("輸出目錄沒有任何檔案（沒有變動），無需驗證 ✓")
            return 0
        # 也接受直接給 *_Data 或其父層
        try:
            out_root = find_data_dir(Path(args.patched))
        except SystemExit:
            print(f"✗ {args.patched} 裡沒有 {data_dir.name}")
            return 1
    rules = load_rules(args.rules)
    errors: list[str] = []
    warns: list[str] = []
    checked = 0
    for rel_path in sorted(out_root.rglob("*")):
        if not rel_path.is_file():
            continue
        rel = rel_path.relative_to(out_root).as_posix()
        orig_path = data_dir / rel
        if not orig_path.exists():
            errors.append(f"{rel}: 原始資料裡沒有這個檔案")
            continue
        checked += 1
        a, b = load_env(orig_path), load_env(rel_path)
        oa = {o.path_id: o for o in a.objects}
        ob = {o.path_id: o for o in b.objects}
        if set(oa) != set(ob):
            errors.append(f"{rel}: 物件集合不同（原 {len(oa)}，後 {len(ob)}）")
            continue
        ta = {t.obj.path_id: t for t in iter_tables(a)}
        tb = {t.obj.path_id: t for t in iter_tables(b)}
        for pid, x in oa.items():
            y = ob[pid]
            if x.type.name != y.type.name:
                errors.append(f"{rel}#{pid}: 型別 {x.type.name} → {y.type.name}")
                continue
            if pid in ta:
                t1, t2 = ta[pid], tb.get(pid)
                if t2 is None:
                    errors.append(f"{rel}#{t1.name}: 導入後不再是合法的 JSON 表")
                    continue
                _verify_table(rel, t1, t2, _rule_fields(rules, t1), errors, warns)
            elif x.get_raw_data() != y.get_raw_data():
                errors.append(f"{rel}#{pid} ({x.type.name}): 非文字物件的內容改變了")
    print(f"檢查 {checked} 個檔案：{len(errors)} 個錯誤，{len(warns)} 個警告")
    for e in errors[:30]:
        print("  ✗", e)
    for w in warns[:15]:
        print("  ⚠", w)
    if errors:
        print("✗ 結構驗證失敗，補丁不安全")
        return 1
    print("✓ 沒有結構性問題")
    return 0


def _verify_table(rel: str, t1, t2, allowed: dict[str, list], errors: list[str], warns: list[str]) -> None:
    label = f"{rel}#{t1.name}"
    if len(t1.rows) != len(t2.rows):
        errors.append(f"{label}: 列數 {len(t1.rows)} → {len(t2.rows)}")
        return
    if t1.has_bom != t2.has_bom:
        errors.append(f"{label}: BOM 狀態改變")
    for i, (r1, r2) in enumerate(zip(t1.rows, t2.rows, strict=True)):
        if list(r1.keys()) != list(r2.keys()):
            errors.append(f"{label} 列 {i}: 欄位集合改變")
            continue
        for k, v1 in r1.items():
            v2 = r2[k]
            if v1 == v2:
                continue
            if not isinstance(v1, str) or not isinstance(v2, str):
                errors.append(f"{label} Rows[{t1.row_keys[i]}]/{k}: 非字串欄位改變 {v1!r} → {v2!r}")
                continue
            rules_here = [r for r in allowed.get(k, []) if r.matches(r1) and not r.skip]
            if not rules_here:
                errors.append(f"{label} Rows[{t1.row_keys[i]}]/{k}: 不在規則內的欄位被改了")
                continue
            if any(r.parse == "kv" for r in rules_here):
                k1 = [p[0] for p in split_kv(v1)]
                k2 = [p[0] for p in split_kv(v2)]
                if k1 != k2:
                    errors.append(f"{label} Rows[{t1.row_keys[i]}]/{k}: 複合欄位的子鍵序列改變 {k1} → {k2}")
                    continue
            if collections.Counter(PLACEHOLDER_RE.findall(v1)) != collections.Counter(PLACEHOLDER_RE.findall(v2)):
                errors.append(f"{label} Rows[{t1.row_keys[i]}]/{k}: <param#…> 佔位符不一致")
            if collections.Counter(TAG_RE.findall(v1)) != collections.Counter(TAG_RE.findall(v2)):
                warns.append(f"{label} Rows[{t1.row_keys[i]}]/{k}: 富文本標籤不一致")


# -- 入口 -----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate")
    p.add_argument("translation", type=Path)
    p.add_argument("-e", "--encoding", default="utf-8")
    p.add_argument("-u", "--output-untranslated", type=Path, default=None)
    p.add_argument("-c", "--context", nargs="+", dest="contexts", default=["dialog", "choice"])
    p = sub.add_parser("import")
    p.add_argument("data", type=Path)
    p.add_argument("translation", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("-e", "--encoding", default="utf-8")
    p.add_argument("--rules", type=Path, default=None)
    p.add_argument("--no-verify", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("data", type=Path)
    p.add_argument("patched", type=Path)
    p.add_argument("-e", "--encoding", default="utf-8")
    p.add_argument("--rules", type=Path, default=None)
    args = ap.parse_args(argv)
    return {"validate": cmd_validate, "import": cmd_import, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
