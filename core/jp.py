"""日文偵測（抽自 GalTransl-sister/translate_wolf.py:197-210）。"""

from __future__ import annotations

import re

# 平假名／片假名／半形片假名
KANA_RE = re.compile(r"[぀-ゟ゠-ヿ･-ﾟ]")
# 漢字（原文是日文時，只有漢字的字串也需要翻譯）
KANJI_RE = re.compile(r"[一-龯]")


def is_japanese_text(text: str, strip_re: re.Pattern[str] | None = None) -> bool:
    """字串（去掉控制碼後）是否含假名或漢字。"""
    if not text or not isinstance(text, str):
        return False
    clean = strip_re.sub("", text) if strip_re else text
    clean = clean.strip()
    if not clean:
        return False
    return bool(KANA_RE.search(clean) or KANJI_RE.search(clean))


def has_kana(text: str) -> bool:
    """只看假名——用來判斷「譯文裡是否還殘留日文」（中文譯文本來就有漢字）。"""
    return bool(text and KANA_RE.search(text))
