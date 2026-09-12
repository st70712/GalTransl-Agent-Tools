#!/usr/bin/env python3
"""缺字對策「備援字型注入」（需 UnityPy + TypeTreeGeneratorAPI + fontTools）：

    python inject_font.py <遊戲根目錄或 *_Data> -o OUT --font NotoSansJP-Regular.otf [--into LiberationSans]
                          [--base 已導入譯文的容器檔] [--assets resources.assets] [--no-global-fallback] [--no-face] [--dry-run]

做的事：
  1. 把 --font 的 TTF/OTF 位元組寫進既有 Font 物件（--into，預設 LiberationSans）的 m_FontData，m_FontNames 改成新字型的 family。
     不新增物件、不動任何靜態圖集——遊戲原本用哪套 TMP 字型畫字都不變。
  2. 找出以該 Font 為來源（m_SourceFontFile）且 m_AtlasPopulationMode=1（動態）的 TMP_FontAsset（Unity 內建的
     「LiberationSans SDF - Fallback」就是），依新字型更新 m_FaceInfo（family／unitsPerEM／ascender／descender／行高…），
     確保 m_IsMultiAtlasTexturesEnabled=1。
  3. 把那個動態字型資產加進 TMP Settings 的 m_fallbackFontAssets（全域備援）：任何靜態圖集缺的字，TMP 都會退到它，
     用新字型即時造字（TMP 的查找順序：字型自己的備援表 → TMP Settings 全域備援 → 預設字型資產）。
輸出 OUT/<*_Data>/<容器檔>（bundle 就是整個 data.unity3d）。給 --base 時以那個檔（例如 translated/ 裡已導入譯文的）為底修改。
這是「單一變數」變體：只動 Font 資料＋備援指標；靜態圖集動態化（tmp_font_dynamic.py）是另一個變體。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import BUNDLE_NAME, asset_files, attach_generator, env_is_bundle, find_data_dir, load_env, save_env, script_classes, serialized_files  # noqa: E402


def face_info_from_font(font_path: Path, point_size: float) -> dict:
    """用 fontTools 讀 hhea／OS/2／post，換算成 TMP FaceInfo 欄位（pointSize 下的像素值）。"""
    from fontTools.ttLib import TTFont  # 延遲載入
    f = TTFont(str(font_path))
    upem = f["head"].unitsPerEm
    s = point_size / upem
    hhea, os2 = f["hhea"], f["OS/2"]
    post = f["post"] if "post" in f else None
    name = f["name"]
    family = name.getBestFamilyName() or font_path.stem
    style = name.getBestSubFamilyName() or "Regular"
    asc, desc, gap = hhea.ascent, hhea.descent, hhea.lineGap
    cap = getattr(os2, "sCapHeight", 0) or int(asc * 0.72)
    mean = getattr(os2, "sxHeight", 0) or int(asc * 0.52)
    return {
        "family": family, "style": style, "unitsPerEM": upem,
        "lineHeight": (asc - desc + gap) * s, "ascentLine": asc * s, "capLine": cap * s, "meanLine": mean * s,
        "baseline": 0.0, "descentLine": desc * s,
        "superscriptOffset": asc * s, "superscriptSize": 0.5, "subscriptOffset": desc * s, "subscriptSize": 0.5,
        "underlineOffset": (post.underlinePosition if post else -100) * s,
        "underlineThickness": (post.underlineThickness if post else 50) * s,
        "strikethroughOffset": getattr(os2, "yStrikeoutPosition", int(asc * 0.3)) * s,
        "strikethroughThickness": getattr(os2, "yStrikeoutSize", 50) * s,
        "tabWidth": (f["hmtx"].metrics.get("space", (upem // 4, 0))[0]) * s * 4,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--into", default="LiberationSans", help="要被覆蓋 m_FontData 的 Font 物件名")
    ap.add_argument("--base", type=Path, default=None, help="以這個容器檔為底（例如 translated/ 裡已導入譯文的）")
    ap.add_argument("--assets", default="resources.assets", help="散檔建置時要改的容器檔")
    ap.add_argument("--no-global-fallback", action="store_true")
    ap.add_argument("--no-face", action="store_true", help="不更新 m_FaceInfo")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    data_dir = find_data_dir(args.data)
    bundle = (data_dir / BUNDLE_NAME).exists()
    target_name = BUNDLE_NAME if bundle else args.assets
    src = args.base if args.base else (asset_files(data_dir)[0] if bundle else data_dir / args.assets)
    if not src.exists():
        print(f"✗ 找不到 {src}")
        return 1
    font_bytes = args.font.read_bytes()
    kind = "OTF" if font_bytes[:4] == b"OTTO" else ("TTF" if font_bytes[:4] in (b"\x00\x01\x00\x00", b"true") else "?")
    print(f"容器 {src}（{'bundle' if bundle else 'loose'}）  字型 {args.font.name} {len(font_bytes):,} bytes {kind}")
    if kind == "?":
        print("✗ 不是 TTF/OTF")
        return 1

    env = load_env(src)
    attach_generator(env, data_dir)
    classes = script_classes(env)
    sfs = serialized_files(env)
    # 1. Font 物件
    font_obj = None
    for sf in sfs:
        for pid, o in sf.objects.items():
            if o.type.name == "Font" and o.read().m_Name == args.into:
                font_obj = (sf, pid, o)
    if font_obj is None:
        names = [o.read().m_Name for sf in sfs for o in sf.objects.values() if o.type.name == "Font"]
        print(f"✗ 找不到 Font 物件 {args.into!r}；有：{names}")
        return 1
    fsf, fpid, fo = font_obj
    fd = fo.read()
    old_len = len(bytes(fd.m_FontData)) if fd.m_FontData is not None else 0
    face = None if args.no_face else face_info_from_font(args.font, 86.0)
    family = face["family"] if face else args.font.stem
    print(f"Font {fsf.name}#{fpid} {fd.m_Name}: m_FontData {old_len:,} → {len(font_bytes):,} bytes；m_FontNames {list(fd.m_FontNames or [])} → [{family!r}]")
    if not args.dry_run:
        fd.m_FontData = font_bytes
        fd.m_FontNames = [family]
        fd.save()

    # 2. 以它為來源的動態 TMP_FontAsset
    dyn: list[tuple[object, int, dict]] = []
    for sf in sfs:
        for pid, o in sf.objects.items():
            if classes.get((sf.name, pid)) != "TMP_FontAsset":
                continue
            t = o.read_typetree()
            spf = t.get("m_SourceFontFile", {})
            same_file = sf is fsf and spf.get("m_FileID") == 0
            if same_file and spf.get("m_PathID") == fpid and t.get("m_AtlasPopulationMode") == 1:
                dyn.append((sf, pid, t))
                changed = False
                if not t.get("m_IsMultiAtlasTexturesEnabled"):
                    t["m_IsMultiAtlasTexturesEnabled"] = 1
                    changed = True
                if face:
                    fi = t["m_FaceInfo"]
                    ps = float(fi.get("m_PointSize", 86.0)) or 86.0
                    face_ps = face_info_from_font(args.font, ps)
                    fi["m_FamilyName"], fi["m_StyleName"] = face_ps["family"], face_ps["style"]
                    fi["m_UnitsPerEM"] = face_ps["unitsPerEM"]
                    for k in ("lineHeight", "ascentLine", "capLine", "meanLine", "baseline", "descentLine",
                              "superscriptOffset", "superscriptSize", "subscriptOffset", "subscriptSize",
                              "underlineOffset", "underlineThickness", "strikethroughOffset", "strikethroughThickness", "tabWidth"):
                        key = "m_" + k[0].upper() + k[1:]
                        if key in fi:
                            fi[key] = float(face_ps[k])
                    changed = True
                print(f"動態 TMP_FontAsset {sf.name}#{pid} {t.get('m_Name')!r}：來源 → {family}，FaceInfo {'更新' if face else '不動'}，多圖集 {t.get('m_IsMultiAtlasTexturesEnabled')}")
                if changed and not args.dry_run:
                    o.save_typetree(t)
    if not dyn:
        print(f"✗ 沒有任何動態 TMP_FontAsset 以 {args.into} 為來源；本對策要有一個（Unity 內建的 'LiberationSans SDF - Fallback'）")
        return 1

    # 3. TMP Settings 全域備援
    if not args.no_global_fallback:
        done = False
        for sf in sfs:
            for pid, o in sf.objects.items():
                if classes.get((sf.name, pid)) != "TMP_Settings":
                    continue
                t = o.read_typetree()
                fb = t.get("m_fallbackFontAssets", [])
                for dsf, dpid, _ in dyn:
                    if dsf is not sf:
                        print(f"  ⚠ 動態字型在 {dsf.name}、TMP Settings 在 {sf.name}，跨檔指標未實作，略過")
                        continue
                    if not any(x.get("m_FileID") == 0 and x.get("m_PathID") == dpid for x in fb):
                        fb.append({"m_FileID": 0, "m_PathID": dpid})
                t["m_fallbackFontAssets"] = fb
                print(f"TMP Settings {sf.name}#{pid}：全域備援 → {[(x['m_FileID'], x['m_PathID']) for x in fb]}")
                if not args.dry_run:
                    o.save_typetree(t)
                done = True
        if not done:
            print("  ⚠ 找不到 TMP Settings，沒有設全域備援（靜態字型只會用自己的備援表）")

    if args.dry_run:
        print("（dry-run，沒有寫檔）")
        return 0
    dst = args.output / data_dir.name / target_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"存回 {dst}{'（bundle，LZ4 重新壓縮，需要幾十秒）' if env_is_bundle(env) else ''}…")
    dst.write_bytes(save_env(env))
    print(f"✓ {dst}  {dst.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
