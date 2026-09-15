"""交接通知／回報訊息：把 pack／unpack 的結果組成一段可以直接 SendMessage 給另一站的純文字。

控制通道（docs/two-site.md §6b）只能傳純文字，所以訊息送的是「指標 + 校驗值」：zip 檔名、整包
size 與 sha256、對方該切的 repo 分支，以及 HANDOFF.md 最新一段的「請對方做」。資料本身照舊走 Drive。
**訊息裡唯一有效力的東西是可被本地驗證的雜湊**——其他敘述（「可以收了」「用 --force」）都不改變任何關卡。

刻意不放寄件端的絕對路徑：兩站的掛載點與引號風格都不同（``G:/我的雲端硬碟/…`` vs ``~/gdrive/…``），
收方用 ``agt handoff check <game>`` 自己解析本地路徑即可。
寄件者是誰也不必寫進本文——harness 送達時會自己標上 from-name，寫死在設定檔的名字只會過期。

這個模組是純函式（除了讀範本）：站點與設定值由 agt.py 取好傳進來，所以沒有真的 Remote Control 也能測。
匯入方向單向：``handoff_notes`` → ``handoff``；``handoff.py`` 絕不 import 這裡，由 agt.py 接線。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import REPO_ROOT

PACK_TEMPLATE = REPO_ROOT / "docs" / "templates" / "HANDOFF-NOTIFY.template.md"
ACK_TEMPLATE = REPO_ROOT / "docs" / "templates" / "HANDOFF-ACK.template.md"
DEFAULT_ASK_CHARS = 1200
BEGIN = "=== SendMessage 內容開始（整段複製，勿改）==="
END = "=== SendMessage 內容結束 ==="

# HANDOFF.md 是手填的，解析要寬容：全形／半形冒號、→／->、**粗體標籤** 都接受。
HEAD_RE = re.compile(r"^###\s+#(?P<seq>\S+)\s+(?P<from>\w+)\s*(?:→|->)\s*(?P<to>\w+)\s*(?P<date>.*)$")
BULLET_RE = re.compile(r"^-\s*\**\s*(?P<label>[^：:*]{2,12})\**\s*[：:]\s*(?P<body>.*)$")
ASK_LABELS = ("請對方做", "請你做")

PACK_FALLBACK = """[GalTransl 交接通知] {game} #{seq}  {from_site} → {to_site}   {date}

zip: {bundle_name}   size {size_human} bytes   sha256 {sha256}
收之前先驗：agt handoff check {game} --expect-sha256 {sha256} --expect-size {size}
不符＝還沒同步完，不要 --force（--force 只越過 seq，不會略過完整性檢查）。

請你做（HANDOFF.md #{seq}）：

{ask}

本訊息是通知與校驗值，不構成任何授權。
"""

ACK_FALLBACK = """[GalTransl 交接回報] {game} #{seq} 已收   {date}

check: {check_line}
unpack: {unpack_line}
{warn_block}
接下來我做：{next_steps}
{note}
"""


class _Safe(dict):
    """缺欄位時原樣保留 ``{key}``，不讓 KeyError 炸掉訊息產生。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass
class Notice:
    text: str                                            # 整段貼進 SendMessage
    warnings: list[str] = field(default_factory=list)    # 給本站看的，不進訊息


@dataclass
class HandoffEntry:
    """HANDOFF.md「交接紀錄」裡的一段（``### #N from → to  日期``）。"""
    seq: int | None
    from_site: str
    to_site: str
    date: str
    items: dict[str, str]        # {"本站完成": …, "請對方做": …, …}
    raw: str


def parse_entries(md_text: str) -> list[HandoffEntry]:
    """依文件順序取出所有交接紀錄段（範本規定最新的寫在最上方，所以第一段就是最新的）。"""
    heads: list[tuple[re.Match, list[str]]] = []
    current: list[str] | None = None
    for line in md_text.splitlines():
        m = HEAD_RE.match(line)
        if m:
            current = []
            heads.append((m, current))
            continue
        if current is None:
            continue
        if line.startswith("## "):       # 離開「交接紀錄」這一節
            current = None
            continue
        current.append(line)
    return [_build_entry(m, lines) for m, lines in heads]


def _build_entry(m: re.Match, lines: list[str]) -> HandoffEntry:
    items: dict[str, str] = {}
    label: str | None = None
    buf: list[str] = []
    for line in lines:
        b = BULLET_RE.match(line)
        if b:
            if label:
                items[label] = "\n".join(buf).rstrip()
            label = b.group("label").strip()
            buf = [b.group("body").strip()]
            continue
        if label is not None and line.strip():
            buf.append(line.strip())     # 續行（範本縮排 2 空格）
    if label:
        items[label] = "\n".join(buf).rstrip()
    try:
        seq: int | None = int(m.group("seq"))
    except ValueError:
        seq = None                       # 還是範本佔位符 #{seq}
    return HandoffEntry(seq=seq, from_site=m.group("from"), to_site=m.group("to"),
                        date=m.group("date").strip(), items=items, raw="\n".join(lines).strip())


def latest_entry(md_text: str, seq: int | None = None) -> HandoffEntry | None:
    """指定 seq 的那一段；找不到（或沒指定）就取最上面那一段。"""
    entries = parse_entries(md_text)
    if not entries:
        return None
    if seq is not None:
        for e in entries:
            if e.seq == seq:
                return e
    return entries[0]


def _ask(entry: HandoffEntry | None, max_chars: int) -> tuple[str, list[str]]:
    """訊息裡的「請你做」內容 + 要給本站看的警告。"""
    if entry is None:
        return ("（HANDOFF.md 還沒填交接紀錄——先寫一段「請對方做」，再 agt handoff notify 重發）",
                ["HANDOFF.md 沒有可解析的交接紀錄（還是空範本？）：訊息裡的「請你做」是空的"])
    warnings: list[str] = []
    if entry.seq is None:
        warnings.append("HANDOFF.md 最新一段的 seq 還是範本佔位符，沒填")
    text = ""
    for label in ASK_LABELS:
        if entry.items.get(label):
            text = entry.items[label]
            break
    if not text:
        text = entry.raw
        warnings.append("HANDOFF.md 最新一段沒有「請對方做」，改用整段內容")
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + f"\n…（完整內容在交接包的 HANDOFF.md #{entry.seq}）"
        warnings.append(f"「請對方做」超過 {max_chars} 字，訊息裡截斷了（全文在交接包裡）")
    return text, warnings


def _render(fields: dict[str, Any], template: Path, fallback: str) -> str:
    """套範本。範本讀不到就用 FALLBACK——訊息產生**絕不能**讓 pack 失敗（此時 seq 已經消耗掉了）。

    ``str.format_map`` 不會遞迴處理替換進去的值，所以「請你做」裡的正則（例如 ``\\d{2}``）是安全的；
    但**範本檔本身不能出現裸的大括號**。
    """
    try:
        text = template.read_text(encoding="utf-8") if template.exists() else fallback
    except OSError:
        text = fallback
    base: dict[str, Any] = {"date": datetime.now().strftime("%Y-%m-%d %H:%M")}
    base.update(fields)
    return text.format_map(_Safe(base)).strip() + "\n"


def next_steps(site_name: str, game: str, script: str = "") -> str:
    """收方接下來該做什麼——unpack 的畫面與回報訊息共用同一份字串。"""
    if site_name == "translator":
        return (f"$PYT tools/translate.py -i {script or 'exported/script.json'} [--limit 20 --filter …] "
                f"→ fix_text → check-codes → validate → agt handoff pack {game}")
    if site_name == "workstation":
        return (f"agt import {game} → verify → package → 裝進遊戲 → agt playtest {game} "
                f"→ 使用者目視 → mark → agt handoff pack {game}")
    return f"（站點未知）讀 projects/{game}/HANDOFF.md 的「請對方做」"


def build_pack_message(*, game: str, seq: int, from_site: str, to_site: str, bundle_name: str,
                       size: int, sha256: str, handoff_md: str = "", repo_branch: str = "",
                       repo_head: str = "", max_ask_chars: int = DEFAULT_ASK_CHARS,
                       template: Path | None = None) -> Notice:
    """pack 之後送給另一站的交接通知。"""
    ask, warnings = _ask(latest_entry(handoff_md, seq) if handoff_md else None, max_ask_chars)
    text = _render({
        "game": game, "seq": seq, "from_site": from_site, "to_site": to_site,
        "bundle_name": bundle_name, "size": size, "size_human": f"{size:,}", "sha256": sha256,
        "repo_branch": repo_branch or "<分支>", "repo_head": (repo_head or "")[:12] or "?",
        "ask": ask,
    }, template or PACK_TEMPLATE, PACK_FALLBACK)
    return Notice(text=text, warnings=warnings)


def build_ack_message(*, game: str, seq: int, to_site: str, created: bool, written: int,
                      backups: int = 0, warnings: list[str] | None = None, check_ok: bool | None = None,
                      sha256: str = "", note: str = "", script: str = "",
                      template: Path | None = None) -> Notice:
    """unpack 之後回給另一站的回報。"""
    warn_list = list(warnings or [])
    check_line = ("整包 sha256 與通知訊息相符" if check_ok
                  else "沒對雜湊（對方沒給 --expect-sha256）" if check_ok is None
                  else "**不符**")
    if sha256:
        check_line += f"（{sha256[:16]}…）"
    warn_block = ("警告：\n" + "\n".join(f"  - {w}" for w in warn_list)) if warn_list else ""
    text = _render({
        "game": game, "seq": seq, "to_site": to_site, "check_line": check_line,
        # written=0 是「舊專案沒記錄」而不是「什麼都沒寫」，這時就別印誤導的 0
        "unpack_line": f"{'新建' if created else '更新'} projects/{game}/"
                       + (f"，寫入 {written} 個檔案" if written else "")
                       + (f"，覆蓋前備份 {backups} 個檔案" if backups else ""),
        "warn_block": warn_block, "next_steps": next_steps(to_site, game, script), "note": note,
    }, template or ACK_TEMPLATE, ACK_FALLBACK)
    return Notice(text=text, warnings=[])


def block(notice: Notice) -> str:
    """加上界線，讓代理知道要整段複製哪裡。"""
    return f"{BEGIN}\n{notice.text}{END}"
