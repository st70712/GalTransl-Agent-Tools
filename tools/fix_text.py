#!/usr/bin/env python3
"""翻譯後整理（母本 GalTransl-sister/fix_cp950.py，改為 profile 驅動）。

    # $PYT = 有 opencc 的直譯器（見 CLAUDE.md §3／`agt env`）
    $PYT tools/fix_text.py projects/<game>/exported/script.json [--engine X] [--target-encoding cp950]
    python tools/fix_text.py script.json --no-opencc --dry-run        # 純標準庫也能跑（不做簡繁轉換）

步驟：
1. 簡繁正規化（opencc s2twp，控制碼先遮蔽進私用區再轉）
2. 符號替換（profile.symbol_map；目標編碼是 UTF-8 時自動關閉，那張表是 Big5 缺字才要的代打）
3. 統一重複原文的譯法（排序偏好「控制碼完整」的版本，再看出現次數）
4. 字面 \\n：依 profile.literal_newline_policy（convert_if_original_lacks → 換成真換行；revert → 退回原文；keep）
5. 控制碼把關（core/codes.py）：認不得的反斜線序列／帶值碼遺失或多出／佔位符遺失 → 退回原文；表現碼遺失只報告
6. 目標編碼檢查
7. 字型字元集檢查（選用）：`--charset` 給遊戲字型的字元集檔（每個字一個字元，例如 projects/<game>/font_charset.txt，
   專案佈局下自動偵測）；不在字元集裡的字先查 `--charset-map`（JSON {"嗯":"恩"}，自動偵測 projects/<game>/charset_map.json），
   再試 opencc t2jp（繁→日文字形，例如 值→値、啟→啓），都不行的列出來給人決定。

寫檔前會先備份成 script.backup-<時間>.json（--no-backup 關閉）。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import codes, fsutil, script_json, state  # noqa: E402
from core.profile import EngineProfile, load_profile  # noqa: E402

_PLACEHOLDER_BASE = 0xE000   # 私用區，opencc 不會動到
LITERAL_NEWLINE_RE = re.compile(r"\\n(?!\[)")   # 排除 RPG Maker 的 \n[1]（角色名碼）


def convert_preserving_codes(converter, profile: EngineProfile, text: str) -> str:
    stash: list[str] = []

    def keep(m: re.Match) -> str:
        stash.append(m.group(0))
        return chr(_PLACEHOLDER_BASE + len(stash) - 1)

    masked = profile.codes.any_re.sub(keep, text)
    for ph in profile.placeholders:
        masked = ph.sub(keep, masked)
    converted = converter.convert(masked)
    for i, code in enumerate(stash):
        converted = converted.replace(chr(_PLACEHOLDER_BASE + i), code)
    return converted


def unencodable_chars(text: str, encoding: str) -> list[str]:
    bad = []
    for ch in text:
        try:
            ch.encode(encoding)
        except UnicodeEncodeError:
            bad.append(ch)
    return bad


def resolve_profile(script: Path, engine: str | None) -> tuple[EngineProfile, dict | None]:
    side = script_json.load_sidecar(script)
    if engine:
        return load_profile(engine), side
    if side and side.get("engine"):
        return load_profile(side["engine"]), side
    info = json.loads(script.read_text(encoding="utf-8")).get("info", {})
    if info.get("engine"):
        try:
            return load_profile(info["engine"]), side
        except FileNotFoundError:
            pass
    raise SystemExit("無法決定引擎：加 --engine，或確認 exported/.agt.json sidecar 存在")


def main(argv: list[str] | None = None) -> int:
    fsutil.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="輸出檔（預設覆蓋原檔）")
    ap.add_argument("--engine")
    ap.add_argument("--target-encoding", help="預設 sidecar / info.encoding / utf-8")
    ap.add_argument("--no-opencc", action="store_true", help="跳過簡繁正規化（不需要 opencc）")
    ap.add_argument("--opencc-config", default="s2twp")
    ap.add_argument("--no-symbol-map", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只報告，不寫檔")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--charset", type=Path, help="遊戲字型的字元集檔（預設自動找 projects/<game>/font_charset.txt）")
    ap.add_argument("--charset-map", type=Path, help="缺字替字表 JSON（預設自動找 projects/<game>/charset_map.json）")
    ap.add_argument("--no-charset", action="store_true", help="跳過字型字元集檢查")
    args = ap.parse_args(argv)

    profile, side = resolve_profile(args.script, args.engine)
    payload = script_json.load(args.script)
    encoding = args.target_encoding or (side or {}).get("target_encoding") \
        or payload["info"].get("encoding") or "utf-8"
    is_utf8 = encoding.lower().replace("_", "-").replace("-", "") == "utf8"
    if is_utf8:
        args.no_symbol_map = True
    entries = payload["strings"]
    translated = [e for e in entries if e.get("translated")]
    stats: collections.Counter = collections.Counter()
    print(f"引擎 profile: {profile.name}   目標編碼: {encoding}   譯文條目: {len(translated)}")

    # 1. 簡繁正規化
    if not args.no_opencc:
        try:
            import opencc  # type: ignore
        except ImportError:
            print("error: 需要 opencc（用 nllb-env 的 python），或加 --no-opencc", file=sys.stderr)
            return 1
        converter = opencc.OpenCC(args.opencc_config)
        for e in translated:
            new = convert_preserving_codes(converter, profile, e["translated"])
            if new != e["translated"]:
                e["translated"] = new
                stats["簡繁正規化"] += 1

    # 2. 符號替換
    if not args.no_symbol_map and profile.symbol_map:
        for e in translated:
            new = e["translated"]
            for src, dst in profile.symbol_map.items():
                new = new.replace(src, dst)
            if new != e["translated"]:
                e["translated"] = new
                stats["符號替換"] += 1

    # 3. 統一重複原文的譯法
    ci = profile.codes.case_insensitive
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for e in translated:
        votes[e["original"]][e["translated"]] += 1
    canonical: dict[str, str] = {}
    for original, counter in votes.items():
        if len(counter) <= 1:
            continue

        def rank(kv: tuple[str, int], original: str = original) -> tuple:
            text, count = kv
            lost = len(codes.lost(profile.codes.any_re, original, text, ci)) \
                + len(codes.lost(profile.codes.value_re, text, original, ci))
            return (lost, -count, len(text), text)

        canonical[original] = min(counter.items(), key=rank)[0]
    for e in translated:
        target = canonical.get(e["original"])
        if target and e["translated"] != target:
            e["translated"] = target
            stats["統一重複原文譯法"] += 1

    # 4. 字面 \n
    if profile.literal_newline_policy == "convert_if_original_lacks":
        for e in translated:
            if LITERAL_NEWLINE_RE.search(e["original"]):
                continue
            if LITERAL_NEWLINE_RE.search(e["translated"]):
                e["translated"] = LITERAL_NEWLINE_RE.sub("\n", e["translated"])
                stats["字面 \\n → 真換行"] += 1

    # 5. 控制碼把關
    reverted: list[tuple[dict, list[str]]] = []
    warned: list[tuple[dict, list[str]]] = []
    for e in translated:
        if not e["translated"]:
            continue
        rep = codes.check_entry(profile, e["original"], e["translated"])
        if rep.fatal:
            reverted.append((e, rep.problems))
            e["translated"] = ""
            for label in rep.problems:
                stats["退回：" + label.split(" ")[0]] += 1
        elif rep.warnings:
            warned.append((e, rep.warnings))
            stats["警告（保留）"] += 1

    # 6. 編碼檢查
    still_bad: list[tuple[dict, list[str]]] = []
    char_counter: collections.Counter = collections.Counter()
    for e in translated:
        if not e["translated"]:
            continue
        bad = unencodable_chars(e["translated"], encoding)
        if bad:
            still_bad.append((e, bad))
            char_counter.update(bad)

    # 7. 字型字元集檢查
    project_root = args.script.resolve().parent.parent
    charset_path = args.charset or (project_root / "font_charset.txt" if (project_root / "font_charset.txt").exists() else None)
    unresolved: collections.Counter = collections.Counter()
    unresolved_examples: dict[str, dict] = {}
    if charset_path and not args.no_charset:
        charset = set(charset_path.read_text(encoding="utf-8"))
        map_path = args.charset_map or (project_root / "charset_map.json" if (project_root / "charset_map.json").exists() else None)
        raw_map = json.loads(map_path.read_text(encoding="utf-8")) if map_path else {}
        cmap: dict[str, str] = {k: v for k, v in raw_map.items() if len(k) == 1 and not k.startswith("_")}
        word_map: dict[str, str] = {k: v for k, v in raw_map.items() if len(k) > 1 and not k.startswith("_")}
        t2jp = None
        if not args.no_opencc:
            try:
                import opencc  # type: ignore
                t2jp = opencc.OpenCC("t2jp")
            except Exception:
                t2jp = None
        auto_map: dict[str, str] = {}
        for e in translated:
            if not e["translated"]:
                continue
            for w, rep in sorted(word_map.items(), key=lambda kv: -len(kv[0])):   # 詞級先於字級
                if w in e["translated"]:
                    e["translated"] = e["translated"].replace(w, rep)
                    stats["缺字替換（詞）"] += 1
            out_chars = []
            for ch in e["translated"]:
                if ord(ch) < 0x2E80 or ch in charset:
                    out_chars.append(ch)
                    continue
                rep = cmap.get(ch)
                if rep is None and t2jp is not None:
                    cand = t2jp.convert(ch)
                    if cand != ch and all(c in charset for c in cand):
                        rep = cand
                        auto_map[ch] = cand
                if rep is not None:
                    out_chars.append(rep)
                    stats["缺字替換"] += 1
                else:
                    out_chars.append(ch)
                    unresolved[ch] += 1
                    unresolved_examples.setdefault(ch, e)
            new = "".join(out_chars)
            if new != e["translated"]:
                e["translated"] = new
        print(f"字型字元集: {charset_path}（{len(charset)} 字）  替字表: {map_path or '無'}  t2jp 自動: {len(auto_map)} 種 {''.join(f'{k}→{v}' for k, v in list(auto_map.items())[:12])}")

    print()
    for label, n in stats.most_common():
        print(f"  {label:<24}: {n}")
    print(f"  {encoding + ' 仍無法編碼':<24}: {len(still_bad)}")
    if reverted:
        print(f"\n退回原文的條目（{len(reverted)}）:")
        for e, problems in reverted[:15]:
            print(f"  [{e['index']}] {e.get('source_file')}:{e.get('location')}  {'; '.join(problems)}")
            print(f"      原: {e['original'][:60]!r}")
        if len(reverted) > 15:
            print(f"  ... 還有 {len(reverted) - 15} 條")
    if warned:
        print(f"\n只警告、已保留的條目（{len(warned)}），前 10 條:")
        for e, w in warned[:10]:
            print(f"  [{e['index']}] {'; '.join(w)}")
    if still_bad:
        print(f"\n仍無法以 {encoding} 編碼的字元（{len(char_counter)} 種）:")
        for ch, n in char_counter.most_common(30):
            print(f"  {ch!r}  U+{ord(ch):04X}  出現 {n} 次")
        print("  導入時可用 --skip-unencodable（Wolf）保留原文，或人工替換。")
    else:
        print(f"\n✅ 全部譯文都能以 {encoding} 寫回")

    if unresolved:
        print(f"\n字型沒有、也沒有替字的字（{len(unresolved)} 種，遊戲裡會是 □）— 加進 projects/<game>/charset_map.json 後重跑 fix_text：")
        for ch, n in unresolved.most_common(40):
            ex = unresolved_examples[ch]
            print(f"  {ch} U+{ord(ch):04X} ×{n}   例 [{ex['index']}] {ex['translated'][:40]!r}")

    if args.dry_run:
        print("\n（dry-run，未寫檔）")
        return 0
    out = args.output or args.script
    # 退回原文的條目也要從檢查點拿掉，否則下次 translate.py 會把壞譯文原封不動套回來
    ckpt = args.script.parent / ".agt_checkpoint.json"
    if reverted and out == args.script and ckpt.exists():
        try:
            data = json.loads(ckpt.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            removed = 0
            for e, _ in reverted:
                removed += entries.pop(f"{e['source_file']}\t{e['location']}", None) is not None
            ckpt.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"檢查點：移除 {removed} 條已退回的譯文（重跑 translate.py 會重新翻）")
        except (OSError, ValueError) as exc:
            print(f"⚠ 檢查點更新失敗：{exc}")
    if out == args.script and not args.no_backup:
        backup = args.script.with_name(f"{args.script.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}.json")
        backup.write_bytes(args.script.read_bytes())
        print(f"\n備份: {backup}")
    script_json.save(payload, out)
    print(f"已寫入 {out}")
    state_path = args.script.resolve().parent.parent / "agt.json"
    if state_path.exists() and out == args.script:
        state.mark_gate(state_path, "fix_text", True,
                        f"退回 {len(reverted)} 條，警告 {len(warned)} 條，{encoding} 無法編碼 {len(still_bad)} 條")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
