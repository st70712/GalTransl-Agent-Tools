#!/usr/bin/env python3
"""把 TextMeshPro 靜態字型資產改成動態模式，讓缺字由遊戲用內嵌字型檔即時造字（需 UnityPy）。

    python tmp_font_dynamic.py <遊戲根目錄或 *_Data> -o OUT [--fonts NAME ...] [--dry-run]

做的事（每個目標 TMP_FontAsset）：
  m_SourceFontFile   → 指向內嵌的 Font 物件（同 family；必要時在 .assets 加一筆 external 參照）
  m_AtlasPopulationMode → 1（Dynamic）
  m_IsMultiAtlasTexturesEnabled → true（圖集塞滿時自動開新圖集）
  圖集 Texture2D 的 m_IsReadable → true（TMP 動態加字需要可讀圖集）
TMP_FontAsset 沒有 type tree，欄位位置用「錨點」定位：先找 m_GlyphTable（count + 52-byte Glyph 記錄），
往回推 m_StyleNameHashCode / m_FamilyNameHashCode / InternalDynamicOS / m_AtlasPopulationMode / m_SourceFontFilePath / m_SourceFontFile，
往後推 m_CharacterTable / m_AtlasTextures / m_AtlasTextureIndex / 三個 bool / m_AtlasWidth…；每一步都有合理性檢查，不合就中止。
版面來源：il2cpp global-metadata 的欄位宣告順序（見 NOTES.md）。
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unity_tables import find_data_dir, load_env  # noqa: E402

GLYPH_SIZE = 52          # uint index + 5 float metrics + 4 int rect + float scale + int atlasIndex + int classDef
CHAR_SIZE = 16           # int elementType(=1) + uint unicode + uint glyphIndex + float scale


@dataclass
class Layout:
    name: str
    family: str
    style: str
    source_pptr_off: int
    source_pptr: tuple[int, int]
    mode_off: int
    mode: int
    glyph_off: int
    glyph_count: int
    char_off: int
    char_count: int
    atlas_pptrs: list[tuple[int, int]] = field(default_factory=list)
    multi_atlas_off: int = -1
    multi_atlas: int = -1
    atlas_size: tuple[int, int] = (0, 0)


def _str(raw: bytes, off: int) -> tuple[str, int]:
    ln = struct.unpack_from("<I", raw, off)[0]
    if ln > 4096:
        raise ValueError(f"字串長度不合理 {ln} @{off}")
    s = raw[off + 4:off + 4 + ln].decode("utf-8", "replace")
    return s, off + 4 + ((ln + 3) // 4) * 4


def _plausible_glyph(raw: bytes, off: int) -> bool:
    idx, w, h, bx, by, adv, rx, ry, rw, rh, scale, atlas, cdef = struct.unpack_from("<IfffffiiiifiI", raw, off)
    return (idx < 70000 and 0 <= w <= 2000 and 0 <= h <= 2000 and abs(bx) < 2000 and abs(by) < 2000
            and 0 <= adv <= 4000 and 0 <= rx <= 16384 and 0 <= ry <= 16384 and 0 <= rw <= 4096 and 0 <= rh <= 4096
            and scale == 1.0 and 0 <= atlas <= 16 and cdef <= 4)


def parse(raw: bytes) -> Layout:
    off = 28
    name, off = _str(raw, off)
    version, off = _str(raw, off)
    if not version.startswith("1."):
        raise ValueError(f"{name}: m_Version={version!r} 不是預期的 1.x")
    off += 4                                   # FaceInfo.m_FaceIndex
    family, off = _str(raw, off)
    style, off = _str(raw, off)
    off += 18 * 4                              # FaceInfo 其餘 18 個數值欄位
    off += 12                                  # TMP_Asset.m_Material PPtr
    guid, off = _str(raw, off)                 # m_SourceFontFileGUID
    search_from = off
    # 錨點 1：m_CharacterTable（count + {1, unicode, glyphIndex, 1.0} 記錄，unicode 遞增）
    char_off = -1
    for o in range(search_from, len(raw) - 4 * CHAR_SIZE, 4):
        count = struct.unpack_from("<I", raw, o)[0]
        if not (50 <= count <= 70000) or o + 4 + count * CHAR_SIZE > len(raw):
            continue
        ok = True
        last = -1
        for k in range(count):                     # 整張表逐筆檢查，避免在 glyph 資料裡誤中
            et, uni, gi, sc = struct.unpack_from("<IIIf", raw, o + 4 + k * CHAR_SIZE)
            if et != 1 or sc != 1.0 or not (0x20 <= uni <= 0x2FFFF) or uni <= last or gi > 70000:
                ok = False
                break
            last = uni
        if ok:
            char_off = o
            break
    if char_off < 0:
        raise ValueError(f"{name}: 找不到 m_CharacterTable")
    char_count = struct.unpack_from("<I", raw, char_off)[0]
    # 錨點 2：m_GlyphTable 緊接在字元表前：glyph_off + 4 + N*52 == char_off，且 raw[glyph_off] == N
    glyph_off = -1
    for n in range(1, 70000):
        g = char_off - 4 - n * GLYPH_SIZE
        if g < search_from:
            break
        if struct.unpack_from("<I", raw, g)[0] == n and all(_plausible_glyph(raw, g + 4 + k * GLYPH_SIZE) for k in range(n)):
            glyph_off = g
            break
    if glyph_off < 0:
        raise ValueError(f"{name}: 找不到 m_GlyphTable")
    glyph_count = struct.unpack_from("<I", raw, glyph_off)[0]
    # 往回（glyph 表之前的版面，經實測）：… renderMode(4) includeFontFeatures(1+3)
    #   m_SourceFontFile PPtr(12) m_SourceFontFilePath(str) m_AtlasPopulationMode(4) InternalDynamicOS(1+3) | m_GlyphTable
    dyn_os = raw[glyph_off - 4]
    mode_off = glyph_off - 8
    mode = struct.unpack_from("<i", raw, mode_off)[0]
    if mode not in (0, 1, 2) or dyn_os not in (0, 1):
        raise ValueError(f"{name}: m_AtlasPopulationMode={mode} / InternalDynamicOS={dyn_os} 不合理，版面判斷失敗")
    path_len_off = mode_off - 4
    path_len = struct.unpack_from("<I", raw, path_len_off)[0]
    if path_len:
        cand = mode_off - 4 - ((path_len + 3) // 4) * 4 - 4
        if not (0 <= cand < path_len_off) or struct.unpack_from("<I", raw, cand)[0] != path_len:
            raise ValueError(f"{name}: m_SourceFontFilePath 反推失敗（len={path_len}）")
        path_len_off = cand
    source_pptr_off = path_len_off - 12
    fid, pid = struct.unpack_from("<iq", raw, source_pptr_off)
    if not (0 <= fid <= 64) or pid < 0:
        raise ValueError(f"{name}: m_SourceFontFile PPtr=({fid},{pid}) 不合理")
    include_ff = raw[source_pptr_off - 4]
    render_mode = struct.unpack_from("<I", raw, source_pptr_off - 8)[0]
    if include_ff not in (0, 1) or not (render_mode & 0x4000 or render_mode == 0):
        raise ValueError(f"{name}: renderMode={render_mode:#x} / includeFontFeatures={include_ff} 不合理")
    o = char_off + 4 + char_count * CHAR_SIZE
    n_atlas = struct.unpack_from("<I", raw, o)[0]
    if not (1 <= n_atlas <= 16):
        raise ValueError(f"{name}: m_AtlasTextures count={n_atlas} 不合理")
    o += 4
    atlas = []
    for _ in range(n_atlas):
        atlas.append(struct.unpack_from("<iq", raw, o))
        o += 12
    o += 4                                    # m_AtlasTextureIndex
    multi_off = o                             # m_IsMultiAtlasTexturesEnabled / m_GetFontFeatures / m_ClearDynamicDataOnBuild，各佔 4 bytes
    bools = bytes((raw[o], raw[o + 4], raw[o + 8]))
    o += 12
    aw, ah, pad, rmode = struct.unpack_from("<iiii", raw, o)
    if aw not in (256, 512, 1024, 2048, 4096, 8192) or ah not in (256, 512, 1024, 2048, 4096, 8192):
        raise ValueError(f"{name}: m_AtlasWidth/Height={aw}x{ah} 不合理（bool 對齊判斷可能錯）")
    if any(b not in (0, 1) for b in bools):
        raise ValueError(f"{name}: bool 欄位值不合理 {list(bools)}")
    return Layout(name=name, family=family, style=style, source_pptr_off=source_pptr_off, source_pptr=(fid, pid),
                  mode_off=mode_off, mode=mode, glyph_off=glyph_off, glyph_count=glyph_count,
                  char_off=char_off, char_count=char_count, atlas_pptrs=atlas,
                  multi_atlas_off=multi_off, multi_atlas=bools[0], atlas_size=(aw, ah))


def find_font_objects(data_dir: Path) -> dict[str, tuple[str, int, int]]:
    """{Font 名稱: (asset 相對路徑, path_id, 字型資料大小)}。"""
    out = {}
    for name in ("resources.assets", "sharedassets0.assets"):
        p = data_dir / name
        if not p.exists():
            continue
        env = load_env(p)
        for o in env.objects:
            if o.type.name == "Font":
                d = o.read()
                out[d.m_Name] = (name, o.path_id, len(d.m_FontData))
    return out


def match_font(family: str, fonts: dict[str, tuple[str, int, int]]) -> str | None:
    key = family.replace(" ", "").lower()
    for fname, (_, _, size) in fonts.items():
        if size > 100_000 and fname.replace(" ", "").replace("-", "").lower().startswith(key.replace("-", "")):
            return fname
    return None


def ensure_external(sf, path: str) -> int:
    """回傳 fileID（externals 1-based）；沒有就加。"""
    for i, e in enumerate(sf.externals):
        if e.path == path:
            return i + 1
    from UnityPy.files.SerializedFile import FileIdentifier

    fi = FileIdentifier.__new__(FileIdentifier)   # attrs slots 類別：跳過 __init__（它要讀 reader）
    fi.temp_empty = ""
    fi.guid = b"\x00" * 16
    fi.type = 0
    fi.path = path
    sf.externals.append(fi)
    return len(sf.externals)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True, help="輸出根目錄（會寫 OUT/<*_Data>/sharedassets0.assets）")
    ap.add_argument("--assets", default="sharedassets0.assets", help="TMP_FontAsset 所在的 asset 檔")
    ap.add_argument("--fonts", nargs="*", help="要改的 TMP_FontAsset 名稱（預設：family 在內嵌 Font 裡找得到的全部）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    data_dir = find_data_dir(args.data)
    fonts = find_font_objects(data_dir)
    print("內嵌 Font 物件:", {k: f"{v[0]}#{v[1]} {v[2]:,}B" for k, v in fonts.items()})
    env = load_env(data_dir / args.assets)
    sf = env.file
    targets = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        if len(raw) < 50_000:
            continue
        try:
            lay = parse(raw)
        except ValueError:
            continue
        targets.append((o, raw, lay))
    if not targets:
        print("✗ 找不到任何 TMP_FontAsset")
        return 1
    patched = 0
    atlas_ids: set[int] = set()
    for o, raw, lay in targets:
        font_name = match_font(lay.family, fonts)
        wanted = (args.fonts is None and font_name is not None) or (args.fonts and lay.name in args.fonts)
        print(f"\n[{lay.name}] family={lay.family!r} style={lay.style!r} glyphs={lay.glyph_count} chars={lay.char_count} "
              f"atlas={lay.atlas_size} mode={lay.mode} multi={lay.multi_atlas} source={lay.source_pptr} "
              f"atlases={lay.atlas_pptrs}  → 內嵌字型 {font_name!r}  {'改' if wanted else '略過'}")
        if not wanted:
            continue
        if font_name is None:
            print("   ✗ 沒有對應的內嵌 Font，無法動態化")
            continue
        asset_rel, font_pid, _ = fonts[font_name]
        fid = 0 if asset_rel == args.assets else ensure_external(sf, asset_rel)
        new = bytearray(raw)
        struct.pack_into("<iq", new, lay.source_pptr_off, fid, font_pid)
        struct.pack_into("<i", new, lay.mode_off, 1)
        new[lay.multi_atlas_off] = 1
        print(f"   m_SourceFontFile → ({fid}, {font_pid})  m_AtlasPopulationMode 0→1  multiAtlas → 1")
        if not args.dry_run:
            o.set_raw_data(bytes(new))
        for f_id, pid in lay.atlas_pptrs:
            if f_id == 0:
                atlas_ids.add(pid)
        patched += 1
    # 圖集可讀
    for o in env.objects:
        if o.type.name == "Texture2D" and o.path_id in atlas_ids:
            tt = o.read_typetree()
            print(f"   Texture2D #{o.path_id} {tt.get('m_Name')!r} {tt.get('m_Width')}x{tt.get('m_Height')} readable {tt.get('m_IsReadable')} → True")
            if not args.dry_run:
                tt["m_IsReadable"] = True
                o.save_typetree(tt)
    if args.dry_run:
        print(f"\n（dry-run）會修改 {patched} 個字型資產、{len(atlas_ids)} 張圖集；未寫檔")
        return 0
    if not patched:
        return 1
    out = args.output / data_dir.name / args.assets
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(sf.save())
    print(f"\n已寫出 {out} ({out.stat().st_size:,} bytes)；externals = {[e.path for e in sf.externals]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
