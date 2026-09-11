"""產生 ``out/安裝說明.txt``：套 ``docs/templates/安裝說明.template.txt``，缺的欄位原樣保留。

範本的佔位符：game_title version_note translated total percent untranslated visible_untranslated
target_dir_note backup_lines deliverable_lines exe variant_note untranslated_reasons known_defects
acceptance_checklist verification_log。:func:`build_fields` 會從 script.json 與 profile 算出大部分欄位，
轉接器只需補引擎特有的幾項（deliverables、exe、target_dir_note、variant_note、verification_log）。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import REPO_ROOT, codes, jp
from .profile import EngineProfile

TEMPLATE = REPO_ROOT / "docs" / "templates" / "安裝說明.template.txt"

FALLBACK = """{game_title}　繁體中文補丁{version_note}

翻譯 {translated}/{total} 條（{percent}%）。玩家看得到的日文剩 {visible_untranslated} 條。

安裝
1. 進到遊戲目錄{target_dir_note}
2. 備份原始檔案：
{backup_lines}
3. 複製下列檔案進去：
{deliverable_lines}
4. 執行 {exe}
{variant_note}

刻意保留日文
{untranslated_reasons}

已知的小瑕疵
{known_defects}

請幫忙留意
{acceptance_checklist}

本機已驗證
{verification_log}
"""


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(fields: dict[str, Any], template: Path | None = None) -> str:
    template = template or TEMPLATE
    text = template.read_text(encoding="utf-8") if template.exists() else FALLBACK
    base = {"date": datetime.now().strftime("%Y-%m-%d")}
    base.update(fields)
    return text.format_map(_Safe(base))


def write(out_dir: Path, fields: dict[str, Any], name: str = "安裝說明.txt") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(render(fields), encoding="utf-8")
    return path


def build_fields(profile: EngineProfile, data: dict[str, Any] | None, *, game_title: str = "",
                 version_note: str = "", deliverables: list[str], backup_lines: list[str],
                 exe: str, target_dir_note: str = "", variant_note: str = "",
                 verification_log: list[str], known_defects: list[str] | None = None) -> dict[str, Any]:
    """從 script.json 算翻譯率、玩家看得到的未翻條目、控制碼瑕疵，配上轉接器給的引擎特有欄位。"""
    strings = (data or {}).get("strings") or []
    total = len(strings)
    translated = sum(1 for e in strings if e.get("translated"))
    untranslated = total - translated
    skip = profile.default_skip_contexts()
    visible: list[dict[str, Any]] = []
    for e in strings:
        if e.get("translated") or e.get("context") in skip:
            continue
        if jp.is_japanese_text(e.get("original", ""), profile.codes.any_re):
            visible.append(e)
    by_ctx = Counter(e.get("context", "?") for e in visible)
    reasons = [f"- {ctx}：{n} 條" for ctx, n in by_ctx.most_common()] or ["- 無"]
    if visible:
        reasons.append("（請依實際情況補上保留的原因，例如：翻了會改變遊戲行為、純符號、玩家看不到）")

    defects = list(known_defects or [])
    if strings:
        summary = codes.report(profile, strings)
        style_lost = summary.counts.get("表現控制碼遺失", 0)
        if style_lost:
            defects.append(f"- {style_lost} 條譯文少了純表現的控制碼（顏色／字級／等待），只影響格式不影響內容")
        if summary.fatal:
            defects.append(f"- ⚠️ 仍有 {summary.fatal} 條控制碼問題未處理（應先跑 fix_text / check_codes）")
    if not defects:
        defects = ["- 目前沒有已知瑕疵"]

    return {
        "game_title": game_title or (data or {}).get("info", {}).get("game_title", ""),
        "version_note": version_note,
        "translated": translated, "total": total,
        "percent": f"{translated / total * 100:.1f}" if total else "0",
        "untranslated": untranslated, "visible_untranslated": len(visible),
        "target_dir_note": target_dir_note,
        "backup_lines": "\n".join(f"   {b}" for b in backup_lines),
        "deliverable_lines": "\n".join(f"   {d}" for d in deliverables),
        "exe": exe, "variant_note": variant_note,
        "untranslated_reasons": "\n".join(reasons),
        "known_defects": "\n".join(defects),
        "acceptance_checklist": "\n".join(f"- [ ] {c}" for c in profile.acceptance_checklist),
        "verification_log": "\n".join(f"- {v}" for v in verification_log),
    }
