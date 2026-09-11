#!/usr/bin/env python3
"""導入前的控制碼硬關卡（純標準庫）。

    python tools/check_codes.py exported/script.json [--engine wolf_rpg] [--json report.json]

只讀不寫。任何「必須處理」的問題（帶值控制碼遺失／多出、認不得的反斜線序列、佔位符遺失、
字面 \\n）→ exit 1；只有警告（表現碼遺失、行數差）→ exit 0 但會列出。
判定規則見 core/codes.py 與 docs/translation-quality.md。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import codes, script_json  # noqa: E402
from core.profile import load_profile  # noqa: E402


def resolve_profile(script: Path, engine: str | None):
    if engine:
        return load_profile(engine)
    side = script_json.load_sidecar(script)
    if side and side.get("engine"):
        return load_profile(side["engine"])
    data = json.loads(script.read_text(encoding="utf-8"))
    eng = (data.get("info") or {}).get("engine")
    if eng:
        try:
            return load_profile(eng)
        except FileNotFoundError:
            pass
    raise SystemExit("無法決定引擎：請加 --engine，或確認 exported/.agt.json sidecar 存在")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", type=Path)
    ap.add_argument("--engine", help="引擎名（預設從 sidecar / info.engine 推斷）")
    ap.add_argument("--json", type=Path, help="把完整報告（含所有問題條目）寫成 JSON")
    ap.add_argument("--examples", type=int, default=5, help="每類問題印幾個例子（預設 5）")
    args = ap.parse_args(argv)

    profile = resolve_profile(args.script, args.engine)
    data = script_json.load(args.script)
    summary = codes.report(profile, data["strings"], max_examples=10 ** 6 if args.json else 10)
    print(f"引擎 profile: {profile.name}   檔案: {args.script}")
    print(codes.format_summary(summary, show_examples=args.examples))
    if args.json:
        payload = {"engine": profile.name, "script": str(args.script), "checked": summary.checked,
                   "fatal": summary.fatal, "warned": summary.warned, "counts": dict(summary.counts),
                   "examples": summary.examples}
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"報告已寫到 {args.json}")
    if summary.fatal:
        print(f"\n✗ {summary.fatal} 條必須處理（跑 tools/fix_text.py 退回原文，或人工修正）")
        return 1
    print("\n✓ 沒有必須處理的控制碼問題")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
