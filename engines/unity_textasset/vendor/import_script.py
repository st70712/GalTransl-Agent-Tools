#!/usr/bin/env python3
"""Unity 譯文檢查／導入／結構驗證（需 .venv-unity 的 UnityPy；MonoBehaviour 另需 TypeTreeGeneratorAPI）。

    python import_script.py validate exported/script.json
    python import_script.py import   <遊戲根目錄> exported/script.json -o translated [--rules R.json]
    python import_script.py verify   <遊戲根目錄> translated [--rules R.json]

import：只重寫「有譯文變動」的容器檔（散檔 *_Data/resources.assets，或整個 *_Data/data.unity3d），寫到 OUT/<*_Data>/…；
        沒有任何變動就不產生檔案。JSON 表用 dump 寫回 TextAsset；MonoBehaviour 用 type tree 寫回；其他物件原樣保留。
verify：OUT 裡每個容器檔與原檔逐物件比對（bundle 展開到內部檔）：非文字物件 raw 必須相同；表格 TextAsset 的列數、
        ID 順序、非規則欄位、複合欄位的子鍵序列、<param#…> 佔位符都必須一致；規則涵蓋的 MonoBehaviour 只有規則路徑
        上的字串葉節點可以不同（結構、其他欄位一律相同）；bundle 的 .resS 資源區塊逐位元組相同。任何錯誤 → exit 1。
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
    JP, Rules, apply_entry, apply_mb_entry, asset_files, entries_for_mb, entries_for_table, env_is_bundle,
    find_data_dir, inner_name, is_mb_source, iter_monobehaviours, iter_tables, load_env, load_rules,
    mb_source, parse_location, resource_digests, save_env, script_classes, serialized_files, split_kv,
    table_source, tree_diff,
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
        sub = None
        if not is_mb_source(e["source_file"]):
            _, _, sub = parse_location(loc)
        if sub is not None and ("," in t or "=" in t):
            hard.append(f"[{e['index']}] {loc} 複合欄位譯文含半形逗號／等號（import 會改成全形）: {t[:40]!r}")
        if collections.Counter(PLACEHOLDER_RE.findall(o)) != collections.Counter(PLACEHOLDER_RE.findall(t)):
            hard.append(f"[{e['index']}] {loc} 佔位符不一致: {PLACEHOLDER_RE.findall(o)} → {PLACEHOLDER_RE.findall(t)}")
        if collections.Counter(TAG_RE.findall(o)) != collections.Counter(TAG_RE.findall(t)):
            soft.append(f"[{e['index']}] {loc} 富文本標籤不一致: {TAG_RE.findall(o)} → {TAG_RE.findall(t)}")
        if o.count("\n") != t.count("\n"):
            soft.append(f"[{e['index']}] {loc} 行數 {o.count(chr(10)) + 1}→{t.count(chr(10)) + 1}")
        if "\r\n" in o and "\n" in t and "\r\n" not in t:
            soft.append(f"[{e['index']}] {loc} 原文用 \\r\\n 換行、譯文只有 \\n（import 會照譯文寫入）")
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
    rules = load_rules(args.rules)
    script = _load_script(args.translation)
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for e in script["strings"]:
        if e.get("translated"):
            by_source[e["source_file"]].append(e)
    if not by_source:
        print("沒有任何譯文，不產生檔案")
        return 0
    out_root = args.output / data_dir.name
    applied = changed_objs = stale = 0
    warnings: list[str] = []
    written: list[Path] = []
    wanted_assets = sorted({s.split("#", 1)[0] for s in by_source})
    for rel in wanted_assets:
        path = data_dir / rel
        if not path.exists():
            print(f"✗ 找不到 {path}")
            return 1
        env = load_env(path)
        bundle = env_is_bundle(env)
        file_changed = False
        for table in iter_tables(env):
            src = table_source(rel, inner_name(table.obj) if bundle else None, table.name)
            entries = by_source.get(src)
            if not entries:
                continue
            current = {e["location"]: e["original"] for e in entries_for_table(src, table, Rules(default_context="x"))}
            table_changed = False
            for e in entries:
                cur = current.get(e["location"])
                if cur is not None and cur != e["original"]:
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
                changed_objs += 1
                file_changed = True
        for mbo in iter_monobehaviours(env, rules, data_dir):
            src = mb_source(rel, mbo.inner if bundle else None, mbo.cls, mbo.path_id)
            entries = by_source.get(src)
            if not entries:
                continue
            current = {e["location"]: e["original"] for e in entries_for_mb(src, mbo, rules)}
            obj_changed = False
            for e in entries:
                cur = current.get(e["location"])
                if cur is not None and cur != e["original"]:
                    stale += 1
                    continue
                ok, warn = apply_mb_entry(mbo, e["location"], e["translated"])
                if warn:
                    warnings.append(f"{src} {warn}")
                if ok:
                    applied += 1
                    obj_changed = True
            if obj_changed:
                mbo.save()
                changed_objs += 1
                file_changed = True
        if file_changed:
            dst = out_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            print(f"存回 {rel}（{'bundle，LZ4 重新壓縮，需要幾十秒' if bundle else 'SerializedFile'}）…")
            dst.write_bytes(save_env(env))
            written.append(dst)
    print(f"套用 {applied} 條譯文到 {changed_objs} 個物件；原文已變、跳過 {stale} 條")
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
        try:
            out_root = find_data_dir(Path(args.patched))
        except SystemExit:
            print(f"✗ {args.patched} 裡沒有 {data_dir.name}")
            return 1
    rules = load_rules(args.rules)
    errors: list[str] = []
    warns: list[str] = []
    checked = 0
    known = {p.relative_to(data_dir).as_posix() for p in asset_files(data_dir)}
    for rel_path in sorted(out_root.rglob("*")):
        if not rel_path.is_file():
            continue
        rel = rel_path.relative_to(out_root).as_posix()
        orig_path = data_dir / rel
        if not orig_path.exists():
            errors.append(f"{rel}: 原始資料裡沒有這個檔案")
            continue
        if "/Managed/" in f"/{rel}" and rel.endswith(".dll"):
            continue  # package 的 dll_strings 步驟產物（patch_dll_strings.py 自己回讀驗證）
        if rel not in known and not rel.endswith((".assets", ".unity3d")):
            errors.append(f"{rel}: 不是本轉接器會產生的檔案")
            continue
        checked += 1
        a, b = load_env(orig_path), load_env(rel_path)
        _verify_container(rel, a, b, rules, data_dir, errors, warns)
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


def _verify_container(rel: str, a, b, rules: Rules, data_dir: Path, errors: list[str], warns: list[str]) -> None:
    sfa = {sf.name: sf for sf in serialized_files(a)}
    sfb = {sf.name: sf for sf in serialized_files(b)}
    if set(sfa) != set(sfb):
        errors.append(f"{rel}: 內部檔集合不同 {sorted(sfa)} vs {sorted(sfb)}")
        return
    ra, rb = resource_digests(a), resource_digests(b)
    if set(ra) != set(rb):
        errors.append(f"{rel}: 資源區塊集合不同 {sorted(ra)} vs {sorted(rb)}")
    else:
        for name in ra:
            if ra[name] != rb[name]:
                errors.append(f"{rel}: 資源區塊 {name} 內容改變（{ra[name][0]:,} → {rb[name][0]:,}）")
    ta = {(inner_name(t.obj), t.obj.path_id): t for t in iter_tables(a)}
    tb = {(inner_name(t.obj), t.obj.path_id): t for t in iter_tables(b)}
    mba = {(m.inner, m.path_id): m for m in iter_monobehaviours(a, rules, data_dir)}
    mbb = {(m.inner, m.path_id): m for m in iter_monobehaviours(b, rules, data_dir, classes=script_classes(b))}
    for name, fa in sfa.items():
        fb = sfb[name]
        oa, ob = fa.objects, fb.objects
        label = f"{rel}[{name}]" if len(sfa) > 1 else rel
        if set(oa) != set(ob):
            errors.append(f"{label}: 物件集合不同（原 {len(oa)}，後 {len(ob)}）")
            continue
        for pid, x in oa.items():
            y = ob[pid]
            if x.type.name != y.type.name:
                errors.append(f"{label}#{pid}: 型別 {x.type.name} → {y.type.name}")
                continue
            key = (name, pid)
            if key in ta:
                t2 = tb.get(key)
                if t2 is None:
                    errors.append(f"{label}#{ta[key].name}: 導入後不再是合法的 JSON 表")
                    continue
                _verify_table(label, ta[key], t2, _rule_fields(rules, ta[key]), errors, warns)
            elif key in mba:
                m2 = mbb.get(key)
                if m2 is None:
                    errors.append(f"{label}#{pid}: 導入後讀不到 {mba[key].cls}")
                    continue
                _verify_mb(label, mba[key], m2, rules, errors, warns)
            elif x.get_raw_data() != y.get_raw_data():
                errors.append(f"{label}#{pid} ({x.type.name}): 非文字物件的內容改變了")


def _verify_mb(label: str, m1, m2, rules: Rules, errors: list[str], warns: list[str]) -> None:
    allowed = [(r.regex(), r) for r in rules.monobehaviours.get(m1.cls, []) if not r.skip]
    diffs = tree_diff(m1.tree, m2.tree)   # 結構（鍵集合／陣列長度）壞掉時 tree_diff 只回一筆，下面會判成不在規則內；葉節點差異數不設上限（RJ01657316 合法差異 2774 條）
    for loc, v1, v2 in diffs:
        rules_here = [r for rx, r in allowed if rx.match(loc)]
        if not rules_here or not isinstance(v1, str) or not isinstance(v2, str):
            errors.append(f"{label}#{m1.path_id} {m1.cls} {loc}: 不在規則內的欄位被改了（{str(v1)[:30]!r} → {str(v2)[:30]!r}）")
            continue
        if collections.Counter(PLACEHOLDER_RE.findall(v1)) != collections.Counter(PLACEHOLDER_RE.findall(v2)):
            errors.append(f"{label}#{m1.path_id} {loc}: <param#…> 佔位符不一致")
        if collections.Counter(TAG_RE.findall(v1)) != collections.Counter(TAG_RE.findall(v2)):
            warns.append(f"{label}#{m1.path_id} {loc}: 富文本標籤不一致")


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
