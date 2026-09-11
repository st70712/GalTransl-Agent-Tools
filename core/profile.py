"""引擎 profile（``engines/<name>/profile.json``）：單一宣告來源。

``tools/translate.py``、``tools/fix_text.py``、``tools/check_codes.py`` 與 adapter 都從這裡拿
context 優先級／預設政策、控制碼正則、佔位符、符號表、補丁步驟。
JSON 裡任何以 ``_`` 開頭的鍵（例如 ``_doc``）都是註解，載入時忽略。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ENGINES_DIR

DEFAULT_PRIORITY = 50
VALID_DEFAULTS = ("translate", "optional", "skip")


@dataclass
class ContextPolicy:
    name: str
    priority: int = DEFAULT_PRIORITY
    default: str = "translate"        # translate | optional | skip
    risky: bool = False               # 翻錯會改變遊戲行為（不只是顯示）
    requires_counterpart: bool = False  # 只有同一原文也出現在其他 context 才翻（Wolf condition）
    description: str = ""
    reason: str = ""


@dataclass
class ControlCodes:
    case_insensitive: bool
    value_pattern: str
    style_pattern: str
    leading_pattern: str
    stray_pattern: str
    value_re: re.Pattern[str] = field(repr=False)
    style_re: re.Pattern[str] = field(repr=False)
    any_re: re.Pattern[str] = field(repr=False)
    leading_re: re.Pattern[str] = field(repr=False)
    stray_re: re.Pattern[str] = field(repr=False)

    @classmethod
    def build(cls, raw: dict[str, Any]) -> ControlCodes:
        flags = re.IGNORECASE if raw.get("case_insensitive") else 0
        value = raw.get("value_codes") or r"(?!x)x"      # 永不匹配
        style = raw.get("style_codes") or r"(?!x)x"
        leading = raw.get("leading_codes") or r"^(?!x)x"
        stray = raw.get("stray_escape") or r"\\[A-Za-z]"
        return cls(
            case_insensitive=bool(raw.get("case_insensitive")),
            value_pattern=value,
            style_pattern=style,
            leading_pattern=leading,
            stray_pattern=stray,
            value_re=re.compile(value, flags),
            style_re=re.compile(style, flags),
            any_re=re.compile(f"(?:{value}|{style})", flags),
            leading_re=re.compile(leading, flags),
            stray_re=re.compile(stray, flags),
        )


@dataclass
class EngineProfile:
    name: str
    display_name: str
    aliases: list[str]
    variants: dict[str, dict[str, Any]]
    detection: dict[str, Any]
    contexts: dict[str, ContextPolicy]
    codes: ControlCodes
    placeholders: list[re.Pattern[str]]
    placeholder_patterns: list[str]
    symbol_map: dict[str, str]
    literal_newline_policy: str          # revert | convert_if_original_lacks | keep
    line_count_policy: str               # warn | fatal | ignore
    never_export: list[str]
    patch: dict[str, Any]
    acceptance_checklist: list[str]
    docs: list[str]
    path: Path
    python_env: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    # -- context 政策 -------------------------------------------------------

    def policy(self, context: str) -> ContextPolicy:
        return self.contexts.get(context) or ContextPolicy(name=context)

    def priority(self, context: str) -> int:
        return self.policy(context).priority

    def default_skip_contexts(self) -> set[str]:
        return {c for c, p in self.contexts.items() if p.default == "skip"}

    def optional_contexts(self) -> set[str]:
        return {c for c, p in self.contexts.items() if p.default == "optional"}

    def counterpart_contexts(self) -> set[str]:
        return {c for c, p in self.contexts.items() if p.requires_counterpart}

    def ordered_contexts(self) -> list[str]:
        return sorted(self.contexts, key=lambda c: (self.contexts[c].priority, c))

    # -- 變體 ---------------------------------------------------------------

    def variant(self, name: str | None) -> dict[str, Any]:
        if name and name in self.variants:
            return self.variants[name]
        if len(self.variants) == 1:
            return next(iter(self.variants.values()))
        return {}

    @property
    def engine_dir(self) -> Path:
        return self.path.parent

    def venv_python(self) -> Path | None:
        """profile 宣告的專用 venv 直譯器（相對 repo 根目錄）；沒宣告回傳 None。"""
        venv = (self.python_env or {}).get("venv")
        if not venv:
            return None
        from . import REPO_ROOT
        return REPO_ROOT / venv / "bin" / "python"


def _strip_doc(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_doc(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_strip_doc(v) for v in obj]
    return obj


def _parse(raw: dict[str, Any], path: Path) -> EngineProfile:
    raw = _strip_doc(raw)
    contexts: dict[str, ContextPolicy] = {}
    for name, spec in (raw.get("contexts") or {}).items():
        if isinstance(spec, int):
            spec = {"priority": spec}
        default = spec.get("default", "translate")
        if default not in VALID_DEFAULTS:
            raise ValueError(f"{path}: context {name!r} 的 default={default!r} 不合法")
        contexts[name] = ContextPolicy(
            name=name,
            priority=int(spec.get("priority", DEFAULT_PRIORITY)),
            default=default,
            risky=bool(spec.get("risky", False)),
            requires_counterpart=bool(spec.get("requires_counterpart", False)),
            description=spec.get("description", ""),
            reason=spec.get("reason", ""),
        )
    codes = ControlCodes.build(raw.get("control_codes") or {})
    flags = re.IGNORECASE if codes.case_insensitive else 0
    placeholder_patterns = list(raw.get("placeholders") or [])
    return EngineProfile(
        name=raw["name"],
        display_name=raw.get("display_name", raw["name"]),
        aliases=list(raw.get("aliases") or []),
        variants=dict(raw.get("variants") or {}),
        detection=dict(raw.get("detection") or {}),
        contexts=contexts,
        codes=codes,
        placeholders=[re.compile(p, flags) for p in placeholder_patterns],
        placeholder_patterns=placeholder_patterns,
        symbol_map=dict(raw.get("symbol_map") or {}),
        literal_newline_policy=raw.get("literal_newline_policy", "revert"),
        line_count_policy=raw.get("line_count_policy", "warn"),
        never_export=list(raw.get("never_export") or []),
        patch=dict(raw.get("patch") or {}),
        acceptance_checklist=list(raw.get("acceptance_checklist") or []),
        docs=list(raw.get("docs") or []),
        path=path,
        python_env=dict(raw.get("python_env") or {}),
        raw=raw,
    )


def list_profiles() -> list[Path]:
    return sorted(p for p in ENGINES_DIR.glob("*/profile.json") if not p.parent.name.startswith("_"))


def load_profile(name_or_path: str | Path) -> EngineProfile:
    """依引擎名（含別名）或檔案路徑載入 profile。"""
    p = Path(name_or_path)
    if p.suffix == ".json" and p.exists():
        return _parse(json.loads(p.read_text(encoding="utf-8")), p.resolve())
    direct = ENGINES_DIR / str(name_or_path) / "profile.json"
    if direct.exists():
        return _parse(json.loads(direct.read_text(encoding="utf-8")), direct)
    wanted = str(name_or_path).lower()
    for path in list_profiles():
        raw = json.loads(path.read_text(encoding="utf-8"))
        names = {raw.get("name", "").lower(), *[a.lower() for a in raw.get("aliases", [])]}
        if wanted in names:
            return _parse(raw, path)
    raise FileNotFoundError(f"找不到引擎 profile：{name_or_path}（已知：{[p.parent.name for p in list_profiles()]}）")
