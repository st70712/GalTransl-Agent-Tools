#!/usr/bin/env python3
"""G1 量測（需 UnityPy）：容器形式、Unity 版本、腳本後端、內部檔與物件統計、JSON 表、含日文的 MonoBehaviour 類別、
TextMeshPro 字型（字元數、動態／靜態、來源字型、備援）、內嵌 Font、字型覆蓋率（對 Big5 常用字與指定字元集）。

    python inspect_assets.py <遊戲根目錄或 *_Data> [--rules R.json] [--charset 字元集檔 ...] [--write-charset OUT.txt]

--charset  額外對照的字元集檔（每行或整檔任意字元；例如 engines/unity_textasset/charsets/NotoSansJP-Regular.txt），
           印出「遊戲靜態圖集」與「該字元集」各自對 Big5 常用字的覆蓋率，決定字型對策。
--write-charset  把遊戲所有 TMP 靜態圖集的字元聯集寫成檔案（可當 projects/<game>/font_charset.txt）。
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import (  # noqa: E402
    JP, asset_files, attach_generator, container_kind, find_data_dir, inner_name, iter_monobehaviours, iter_tables,
    load_env, load_rules, resource_digests, script_classes, scripting_backend, serialized_files, unity_version,
)


def big5_common() -> set[str]:
    """Big5 常用字（0xA440–0xC67E，5401 字）：純標準庫從 cp950 算出。"""
    out: set[str] = set()
    for hi in range(0xA4, 0xC7):
        for lo in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            if hi == 0xC6 and lo > 0x7E:
                break
            try:
                out.add(bytes([hi, lo]).decode("cp950"))
            except UnicodeDecodeError:
                pass
    return out


def big5_rare() -> set[str]:
    """Big5 次常用字（0xC940–0xF9D5，7652 字）。"""
    out: set[str] = set()
    for hi in range(0xC9, 0xFA):
        for lo in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            if hi == 0xF9 and lo > 0xD5:
                break
            try:
                out.add(bytes([hi, lo]).decode("cp950"))
            except UnicodeDecodeError:
                pass
    return out


def coverage(have: set[str], want: set[str]) -> str:
    miss = [c for c in sorted(want) if c not in have]
    pct = 100.0 * (len(want) - len(miss)) / len(want) if want else 0.0
    return f"{pct:5.1f}%（缺 {len(miss)}/{len(want)}）" + (f"  例：{''.join(miss[:40])}" if miss else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("--rules", type=Path, default=None)
    ap.add_argument("--charset", type=Path, nargs="*", default=[])
    ap.add_argument("--write-charset", type=Path, default=None)
    args = ap.parse_args(argv)
    data_dir = find_data_dir(args.data)
    rules = load_rules(args.rules)
    print(f"Unity {unity_version(data_dir) or '?'}  {scripting_backend(data_dir) or '?'}  容器 {container_kind(data_dir)}  資料目錄 {data_dir.name}")
    for p in asset_files(data_dir):
        print(f"  {p.name:<24} {p.stat().st_size:>13,} bytes")
    for name in ("sharedassets0.assets", "level0", "level1", "level2", "level3"):
        p = data_dir / name
        if p.exists():
            print(f"  {name:<24} {p.stat().st_size:>13,} bytes")
    bundles = sorted(data_dir.glob("StreamingAssets/aa/*/*.bundle"))
    if bundles:
        print(f"  Addressables bundle {len(bundles)} 個，共 {sum(b.stat().st_size for b in bundles):,} bytes")

    atlas_chars: set[str] = set()
    for path in asset_files(data_dir):
        env = load_env(path)
        print(f"\n== {path.name} ==")
        sfs = serialized_files(env)
        for sf in sfs:
            types = collections.Counter(o.type.name for o in sf.objects.values())
            print(f"  {sf.name:<28} 物件 {len(sf.objects):>5}  {dict(types.most_common(5))}")
        for name, (size, _) in resource_digests(env).items():
            print(f"  {name:<28} 資源區塊 {size:>13,} bytes（解壓後）")

        tables = list(iter_tables(env))
        if tables:
            print("  JSON 表格 TextAsset：")
            total = 0
            for t in tables:
                jpf: collections.Counter = collections.Counter()
                for r in t.rows:
                    for k, v in r.items():
                        if isinstance(v, str) and JP.search(v):
                            jpf[k] += 1
                total += sum(jpf.values())
                print(f"    {inner_name(t.obj)}/{t.name:<24} {len(t.rows):>5} rows  含日文欄位 {dict(jpf) or '-'}")
            print(f"    合計含日文的欄位值 {total}")
        else:
            print("  JSON 表格 TextAsset：無")

        classes = script_classes(env)
        jp_cls: collections.Counter = collections.Counter()
        cnt_cls: collections.Counter = collections.Counter()
        for sf in sfs:
            for pid, o in sf.objects.items():
                if o.type.name != "MonoBehaviour":
                    continue
                cls = classes.get((sf.name, pid), "?")
                cnt_cls[cls] += 1
                n = len(JP.findall(o.get_raw_data().decode("utf-8", "ignore")))
                if n:
                    jp_cls[cls] += n
        print("  含日文的 MonoBehaviour 類別（日文字元數；哪些是顯示文字要看規則檔）：")
        for cls, n in jp_cls.most_common(15):
            print(f"    {cls:<32} {cnt_cls[cls]:>4} 個物件  日文 {n:>6}")

        # 規則涵蓋的 MonoBehaviour：條目數
        if rules.monobehaviours:
            try:
                per: collections.Counter = collections.Counter()
                from unity_tables import entries_for_mb
                for mbo in iter_monobehaviours(env, rules, data_dir, classes=classes):
                    for e in entries_for_mb("x", mbo, rules):
                        per[(mbo.cls, e["context"])] += 1
                print("  規則涵蓋的 MonoBehaviour 條目：")
                for (cls, ctx), n in sorted(per.items()):
                    print(f"    {cls:<24} {ctx:<10} {n}")
            except SystemExit as e:
                print(f"  （type tree 不可用：{e}）")

        # TMP 字型與內嵌 Font
        fonts = [(sf.name, pid, o) for sf in sfs for pid, o in sf.objects.items() if o.type.name == "Font"]
        if fonts:
            print("  內嵌 Font（動態造字的來源候選）：")
            for name, pid, o in fonts:
                d = o.read()
                fd = getattr(d, "m_FontData", None)
                print(f"    {name}#{pid} {d.m_Name:<28} {len(bytes(fd)) if fd is not None else 0:>10,} bytes  {list(getattr(d, 'm_FontNames', []) or [])}")
        tmp = [(sf.name, pid) for sf in sfs for pid in sf.objects if classes.get((sf.name, pid)) == "TMP_FontAsset"]
        if tmp:
            try:
                attach_generator(env, data_dir)
                have_tt = True
            except SystemExit as e:
                have_tt = False
                print(f"  （TMP 字型細節需要 type tree：{e}）")
            print("  TextMeshPro 字型資產：")
            objs = {(sf.name, pid): o for sf in sfs for pid, o in sf.objects.items()}
            settings = [(sf.name, pid) for sf in sfs for pid in sf.objects if classes.get((sf.name, pid)) == "TMP_Settings"]
            for key in tmp:
                o = objs[key]
                if not have_tt:
                    print(f"    {key[0]}#{key[1]} raw {len(o.get_raw_data()):,} bytes")
                    continue
                t = o.read_typetree()
                chars = {chr(c["m_Unicode"]) for c in t.get("m_CharacterTable", []) if 0 < c.get("m_Unicode", 0) < 0x110000}
                mode = "動態" if t.get("m_AtlasPopulationMode") == 1 else "靜態"
                src = t.get("m_SourceFontFile", {})
                fb = t.get("m_FallbackFontAssetTable", [])
                print(f"    {key[0]}#{key[1]} {t.get('m_Name'):<32} {mode}  字元 {len(chars):>5}  圖集 {t.get('m_AtlasWidth')}x{t.get('m_AtlasHeight')}  "
                      f"來源 Font ({src.get('m_FileID')},{src.get('m_PathID')})  備援 {[(f.get('m_FileID'), f.get('m_PathID')) for f in fb]}  多圖集 {t.get('m_IsMultiAtlasTexturesEnabled')}")
                if mode == "靜態" and len(chars) > 500:
                    atlas_chars |= chars
            for key in settings:
                t = objs[key].read_typetree()
                d = t.get("m_defaultFontAsset", {})
                print(f"    TMP Settings {key[0]}#{key[1]}：預設字型 ({d.get('m_FileID')},{d.get('m_PathID')})  全域備援 "
                      f"{[(f.get('m_FileID'), f.get('m_PathID')) for f in t.get('m_fallbackFontAssets', [])]}")

    if atlas_chars:
        common, rare = big5_common(), big5_rare()
        print(f"\n字型覆蓋率（靜態圖集字元聯集 {len(atlas_chars)} 字）：")
        print(f"  對 Big5 常用字 5401：   {coverage(atlas_chars, common)}")
        print(f"  對 Big5 次常用字 7652： {coverage(atlas_chars, rare)}")
        for cs in args.charset:
            have = set(cs.read_text(encoding="utf-8").replace("\n", "").replace("\r", ""))
            print(f"  字元集 {cs.name}（{len(have)} 字）對 Big5 常用字： {coverage(have, common)}")
            print(f"  字元集 {cs.name}（{len(have)} 字）對 Big5 次常用字： {coverage(have, rare)}")
        if args.write_charset:
            args.write_charset.write_text("".join(sorted(atlas_chars)), encoding="utf-8")
            print(f"  靜態圖集字元集已寫到 {args.write_charset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
