"""共用：找 Unity 資料目錄、載入 SerializedFile 裡的 JSON 表格 TextAsset、規則檔、地址與複合欄位解析。

JSON 表格的長相（本引擎針對的格式）::

    ﻿{
        "Rows": [
            {"ID": 1, "Command": "DrawMessageWindow", "Arg1": "Name=みなみ,Anim=Sway", "Arg2": "台詞…", ...},
            ...
        ]
    }

地址：``source_file = "<asset 相對路徑>#<TextAsset 名>"``、``location = "Rows[<ID>]/<欄位>[/<子鍵>]"``。
複合欄位（``k=v,k=v``）用 ``parse: "kv"`` 規則拆出子鍵（``Name``、``Choice1``、``Message``…）。
需要 UnityPy（.venv-unity）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

BOM = "﻿"
JP = re.compile(r"[぀-ゟ゠-ヿ一-龯]")
DEFAULT_ASSET_FILES = ("resources.assets",)
DEFAULT_SKIP_FIELDS = ("Memo", "Comment", "ID")


# -- 目錄 -----------------------------------------------------------------------

def find_data_dir(root: Path) -> Path:
    root = Path(root)
    if root.name.endswith("_Data") and (root / "globalgamemanagers").exists():
        return root
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name.endswith("_Data") and (d / "globalgamemanagers").exists():
            return d
    for d in sorted(root.iterdir()):
        if d.is_dir():
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and sub.name.endswith("_Data") and (sub / "globalgamemanagers").exists():
                    return sub
    raise SystemExit(f"{root} 底下找不到 *_Data/globalgamemanagers（不是 Unity 遊戲目錄？）")


def asset_files(data_dir: Path, names: tuple[str, ...] = DEFAULT_ASSET_FILES) -> list[Path]:
    return [data_dir / n for n in names if (data_dir / n).exists()]


def load_env(path: Path):
    import UnityPy  # 延遲載入：只有 .venv-unity 才有
    return UnityPy.load(str(path))


# -- 表格 -----------------------------------------------------------------------

@dataclass
class Table:
    obj: Any                    # UnityPy ObjectReader
    data: Any                   # 讀出的 TextAsset
    name: str
    text: str                   # 原始 m_Script（含 BOM）
    rows: list[dict[str, Any]]
    has_bom: bool
    row_keys: list[str]         # 每列的地址鍵（ID 唯一時用 ID，否則用序號）

    def dump(self) -> str:
        """以原始樣式（4 空白縮排、保留非 ASCII、浮點數用原始字面）重新序列化。"""
        return (BOM if self.has_bom else "") + dump_json({"Rows": self.rows})


class FloatText(float):
    """保留 JSON 原始字面的浮點數：C# 會印 0.20000000298023225，Python repr 是 …224，同一個 double。"""

    text: str

    def __new__(cls, text: str):
        obj = super().__new__(cls, text)
        obj.text = text
        return obj


def _enc(v: Any, ind: int) -> str:
    sp = " " * (ind + 4)
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = ",\n".join(f"{sp}{json.dumps(str(k), ensure_ascii=False)}: {_enc(x, ind + 4)}" for k, x in v.items())
        return "{\n" + items + "\n" + " " * ind + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        items = ",\n".join(f"{sp}{_enc(x, ind + 4)}" for x in v)
        return "[\n" + items + "\n" + " " * ind + "]"
    if isinstance(v, FloatText):
        return v.text
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float, str)):
        return json.dumps(v, ensure_ascii=False)
    raise TypeError(f"無法序列化 {type(v).__name__}")


def dump_json(obj: Any) -> str:
    """等同 json.dumps(obj, ensure_ascii=False, indent=4)，但浮點數用載入時的原始字面。"""
    return _enc(obj, 0)


def _row_keys(rows: list[dict[str, Any]]) -> list[str]:
    ids = [r.get("ID") for r in rows]
    if ids and all(isinstance(i, int) for i in ids) and len(set(ids)) == len(ids):
        return [str(i) for i in ids]
    return [f"#{i}" for i in range(len(rows))]


def iter_tables(env) -> Iterator[Table]:
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        data = obj.read()
        script = data.m_Script
        if isinstance(script, (bytes, bytearray)):
            try:
                script = bytes(script).decode("utf-8")
            except UnicodeDecodeError:
                continue
        has_bom = script.startswith(BOM)
        body = script[1:] if has_bom else script
        if not body.lstrip().startswith("{") or '"Rows"' not in body:
            continue
        try:
            rows = json.loads(body, parse_float=FloatText)["Rows"]
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(rows, list):
            continue
        yield Table(obj=obj, data=data, name=data.m_Name, text=script, rows=rows,
                    has_bom=has_bom, row_keys=_row_keys(rows))


# -- 規則 -----------------------------------------------------------------------

@dataclass
class Rule:
    table: str
    field: str
    context: str
    when_command: list[str] | None = None      # Command 欄位等於其中之一才套用
    when_command_prefix: str | None = None     # Command 以此開頭才套用（例如 "*" 標籤列）
    parse: str = "plain"                       # plain | kv
    key: str | None = None                     # kv：只取這個子鍵
    key_prefix: str | None = None              # kv：取所有以此開頭的子鍵（Choice1, Choice2…）
    speaker_from: str | None = None            # "Arg1:Name" 或 "SpeachCharaName"
    skip: bool = False

    def matches(self, row: dict[str, Any]) -> bool:
        cmd = str(row.get("Command", ""))
        if self.when_command is not None and cmd not in self.when_command:
            return False
        if self.when_command_prefix is not None and not cmd.startswith(self.when_command_prefix):
            return False
        return True


@dataclass
class Rules:
    tables: dict[str, list[Rule]] = field(default_factory=dict)
    default_context: str = "text"
    skip_fields: tuple[str, ...] = DEFAULT_SKIP_FIELDS
    skip_tables: tuple[str, ...] = ()

    def for_table(self, table: Table) -> list[Rule]:
        if table.name in self.skip_tables:
            return []
        if table.name in self.tables:
            return self.tables[table.name]
        # 沒寫規則的表：每個含日文的字串欄位都當 default_context
        fields: list[str] = []
        for r in table.rows:
            for k, v in r.items():
                if k in self.skip_fields or k in fields:
                    continue
                if isinstance(v, str) and JP.search(v):
                    fields.append(k)
        return [Rule(table=table.name, field=f, context=self.default_context) for f in fields]


def load_rules(path: Path | None) -> Rules:
    if path is None or not Path(path).exists():
        return Rules()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = Rules(
        default_context=raw.get("default", {}).get("context", "text"),
        skip_fields=tuple(raw.get("default", {}).get("skip_fields", DEFAULT_SKIP_FIELDS)),
        skip_tables=tuple(raw.get("skip_tables", ())),
    )
    for tname, specs in (raw.get("tables") or {}).items():
        lst = []
        for s in specs:
            if str(s.get("field", "")).startswith("_"):
                continue
            lst.append(Rule(
                table=tname, field=s["field"], context=s.get("context", rules.default_context),
                when_command=s.get("when_command"), when_command_prefix=s.get("when_command_prefix"),
                parse=s.get("parse", "plain"), key=s.get("key"), key_prefix=s.get("key_prefix"),
                speaker_from=s.get("speaker_from"), skip=bool(s.get("skip", False)),
            ))
        rules.tables[tname] = lst
    return rules


# -- 複合欄位 -------------------------------------------------------------------

def split_kv(value: str) -> list[tuple[str | None, str]]:
    """``"Name=みなみ,Anim=Sway"`` → ``[("Name","みなみ"),("Anim","Sway")]``；沒有 ``=`` 的片段 key 為 None。"""
    out: list[tuple[str | None, str]] = []
    for part in value.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out.append((k, v))
        else:
            out.append((None, part))
    return out


def join_kv(pairs: list[tuple[str | None, str]]) -> str:
    return ",".join(v if k is None else f"{k}={v}" for k, v in pairs)


def sanitize_kv_value(text: str) -> tuple[str, bool]:
    """複合欄位的值不能含半形逗號／等號（會破壞解析）；換成全形並回報是否有改。"""
    new = text.replace(",", "，").replace("=", "＝")
    return new, new != text


def speaker_of(row: dict[str, Any], spec: str | None) -> str:
    if not spec:
        return ""
    if ":" in spec:
        fld, key = spec.split(":", 1)
        for k, v in split_kv(str(row.get(fld, ""))):
            if k == key:
                return v
        return ""
    return str(row.get(spec, "") or "")


# -- 地址 -----------------------------------------------------------------------

def location(row_key: str, fld: str, sub: str | None = None) -> str:
    return f"Rows[{row_key}]/{fld}" + (f"/{sub}" if sub else "")


def parse_location(loc: str) -> tuple[str, str, str | None]:
    m = re.match(r"Rows\[(.+?)\]/([^/]+)(?:/(.+))?$", loc)
    if not m:
        raise ValueError(f"看不懂的 location: {loc}")
    return m.group(1), m.group(2), m.group(3)


def entries_for_table(source_file: str, table: Table, rules: Rules) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row, rkey in zip(table.rows, table.row_keys, strict=True):
        for rule in rules.for_table(table):
            if rule.skip or not rule.matches(row):
                continue
            value = row.get(rule.field)
            if not isinstance(value, str) or not value:
                continue
            speaker = speaker_of(row, rule.speaker_from)
            if rule.parse == "kv":
                for k, v in split_kv(value):
                    if k is None or not v:
                        continue
                    if rule.key is not None and k != rule.key:
                        continue
                    if rule.key_prefix is not None and not k.startswith(rule.key_prefix):
                        continue
                    if rule.key is None and rule.key_prefix is None:
                        continue
                    if not JP.search(v):
                        continue
                    out.append({"source_file": source_file, "location": location(rkey, rule.field, k),
                                "original": v, "translated": "", "context": rule.context,
                                "speaker": speaker, "code": 0})
            else:
                if not JP.search(value):
                    continue
                out.append({"source_file": source_file, "location": location(rkey, rule.field),
                            "original": value, "translated": "", "context": rule.context,
                            "speaker": speaker, "code": 0})
    return out


def apply_entry(table: Table, loc: str, translated: str) -> tuple[bool, str]:
    """把譯文寫回表格；回傳 (是否有變動, 警告訊息)。"""
    rkey, fld, sub = parse_location(loc)
    try:
        idx = table.row_keys.index(rkey)
    except ValueError:
        return False, f"找不到列 {rkey}"
    row = table.rows[idx]
    cur = row.get(fld)
    if not isinstance(cur, str):
        return False, f"{loc} 不是字串欄位"
    warn = ""
    if sub is None:
        if cur == translated:
            return False, ""
        row[fld] = translated
        return True, ""
    pairs = split_kv(cur)
    new_val, changed = sanitize_kv_value(translated)
    if changed:
        warn = f"{loc}: 譯文含半形逗號／等號，已換成全形"
    hit = False
    for i, (k, v) in enumerate(pairs):
        if k == sub:
            pairs[i] = (k, new_val)
            hit = True
    if not hit:
        return False, f"{loc}: 找不到子鍵 {sub}"
    new = join_kv(pairs)
    if new == cur:
        return False, warn
    row[fld] = new
    return True, warn
