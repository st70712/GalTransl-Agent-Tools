"""控制碼把關：比對原文與譯文的控制碼，決定「退回原文」或「只警告」。

判定順序與 GalTransl-sister/fix_cp950.py:196-222 相同，再加上 merge_by_text.py:89-93 的
「憑空多出帶值控制碼」規則：

1. stray   —— 譯文出現原文沒有、也不是已知控制碼的反斜線序列（模型在碼裡插雜字、憑空造 ``\\n``）
2. lost value  —— 帶值的碼（``\\v[n]``、``\\cself[n]``、``\\N[n]``…）少了：內容或變數不見
3. extra value —— 帶值的碼多了：翻譯記憶擴散可能把別句的變數帶進來
4. lost placeholder —— ``%1`` 之類的佔位符少了
5. lost style  —— 純表現的碼（顏色、字級、等待）少了：只掉格式，警告即可
6. literal newline / line count —— 依 profile 政策

1–4 為 fatal（導入前必須處理：退回原文或人工修），5–6 為 warning。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .profile import EngineProfile

LITERAL_NEWLINE = "\\n"


def _norm(codes: Iterable[str], case_insensitive: bool) -> Counter:
    return Counter(c.lower() if case_insensitive else c for c in codes)


def canon(text: str, pattern: re.Pattern[str], case_insensitive: bool = False) -> Counter:
    """文字裡所有匹配 pattern 的控制碼計數（可忽略大小寫）。"""
    return _norm(pattern.findall(text or ""), case_insensitive)


def lost(pattern: re.Pattern[str], original: str, translated: str, case_insensitive: bool = False) -> list[str]:
    """original 有、translated 少掉的碼（同 fix_cp950.lost_codes 語意，含次數）。"""
    a = canon(original, pattern, case_insensitive)
    b = canon(translated, pattern, case_insensitive)
    out: list[str] = []
    for code, n in a.items():
        if b.get(code, 0) < n:
            out.extend([code] * (n - b.get(code, 0)))
    return out


def stray_escapes(profile: EngineProfile, original: str, translated: str) -> list[str]:
    """譯文中認不得的反斜線序列，扣掉原文本身用過的（原文寫得出來的寫法，譯文照用當然可以）。"""
    codes = profile.codes
    def strays(text: str) -> set[str]:
        stripped = codes.any_re.sub("", text or "")
        for ph in profile.placeholders:
            stripped = ph.sub("", stripped)
        found = set(codes.stray_re.findall(stripped))
        found.discard(LITERAL_NEWLINE)  # literal \n 另有政策
        return {s.lower() for s in found} if codes.case_insensitive else found
    return sorted(strays(translated) - strays(original))


def literal_newline_issue(profile: EngineProfile, original: str, translated: str) -> bool:
    """譯文有字面 ``\\n`` 而原文沒有（且不是已知控制碼的一部分）。"""
    codes = profile.codes
    def has_literal(text: str) -> bool:
        return LITERAL_NEWLINE in codes.any_re.sub("", text or "")
    return has_literal(translated) and not has_literal(original)


@dataclass
class CodeReport:
    stray: list[str] = field(default_factory=list)
    lost_value: list[str] = field(default_factory=list)
    extra_value: list[str] = field(default_factory=list)
    lost_placeholder: list[str] = field(default_factory=list)
    lost_style: list[str] = field(default_factory=list)
    literal_newline: bool = False
    line_count: tuple[int, int] | None = None   # (原文行數, 譯文行數)，不同時才有值

    @property
    def fatal(self) -> bool:
        return bool(self.stray or self.lost_value or self.extra_value or self.lost_placeholder
                    or self.literal_newline_fatal)

    literal_newline_fatal: bool = False
    line_count_fatal: bool = False

    @property
    def warnings(self) -> list[str]:
        out = []
        if self.lost_style:
            out.append(f"表現控制碼遺失 {self.lost_style}")
        if self.literal_newline and not self.literal_newline_fatal:
            out.append("譯文出現字面 \\n")
        if self.line_count and not self.line_count_fatal:
            out.append(f"行數 {self.line_count[0]}→{self.line_count[1]}")
        return out

    @property
    def problems(self) -> list[str]:
        out = []
        if self.stray:
            out.append(f"認不得的反斜線序列 {self.stray}")
        if self.lost_value:
            out.append(f"帶值控制碼遺失 {self.lost_value}")
        if self.extra_value:
            out.append(f"憑空多出帶值控制碼 {self.extra_value}")
        if self.lost_placeholder:
            out.append(f"佔位符遺失 {self.lost_placeholder}")
        if self.literal_newline_fatal:
            out.append("譯文出現字面 \\n（原文沒有）")
        if self.line_count_fatal:
            out.append(f"行數 {self.line_count[0]}→{self.line_count[1]}")
        return out

    @property
    def clean(self) -> bool:
        return not self.fatal and not self.warnings


def check_entry(profile: EngineProfile, original: str, translated: str) -> CodeReport:
    """比對單一條目；translated 為空時視為乾淨（未翻譯）。"""
    rep = CodeReport()
    if not translated:
        return rep
    codes = profile.codes
    ci = codes.case_insensitive
    rep.stray = stray_escapes(profile, original, translated)
    rep.lost_value = lost(codes.value_re, original, translated, ci)
    rep.extra_value = lost(codes.value_re, translated, original, ci)
    for ph in profile.placeholders:
        rep.lost_placeholder.extend(lost(ph, original, translated, ci))
    rep.lost_style = lost(codes.style_re, original, translated, ci)
    if literal_newline_issue(profile, original, translated):
        rep.literal_newline = True
        rep.literal_newline_fatal = profile.literal_newline_policy == "revert"
    lo, lt = original.count("\n") + 1, translated.count("\n") + 1
    if lo != lt and profile.line_count_policy != "ignore":
        rep.line_count = (lo, lt)
        rep.line_count_fatal = profile.line_count_policy == "fatal"
    return rep


@dataclass
class Summary:
    checked: int = 0
    fatal: int = 0
    warned: int = 0
    counts: Counter = field(default_factory=Counter)
    examples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def add(self, entry: dict[str, Any], rep: CodeReport, max_examples: int = 10) -> None:
        self.checked += 1
        if rep.fatal:
            self.fatal += 1
        elif rep.warnings:
            self.warned += 1
        for label in rep.problems + rep.warnings:
            kind = label.split(" ")[0]
            self.counts[kind] += 1
            bucket = self.examples.setdefault(kind, [])
            if len(bucket) < max_examples:
                bucket.append({
                    "index": entry.get("index"), "context": entry.get("context"),
                    "location": f"{entry.get('source_file')}:{entry.get('location')}",
                    "detail": label, "original": entry.get("original", ""),
                    "translated": entry.get("translated", ""),
                })


def report(profile: EngineProfile, entries: Iterable[dict[str, Any]], max_examples: int = 10) -> Summary:
    s = Summary()
    for e in entries:
        if not e.get("translated"):
            continue
        s.add(e, check_entry(profile, e.get("original", ""), e.get("translated", "")), max_examples)
    return s


def format_summary(s: Summary, show_examples: int = 5) -> str:
    lines = [f"控制碼檢查：{s.checked} 條已翻譯，{s.fatal} 條必須處理，{s.warned} 條僅警告"]
    for kind, n in s.counts.most_common():
        lines.append(f"  {kind:<12} {n}")
        for ex in s.examples.get(kind, [])[:show_examples]:
            lines.append(f"      [{ex['index']}] {ex['context']} {ex['location']}")
            lines.append(f"        原: {ex['original']!r}")
            lines.append(f"        譯: {ex['translated']!r}")
    return "\n".join(lines)
