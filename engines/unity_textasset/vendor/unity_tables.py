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

第二種來源（2026-09，RJ01657316）：文本在 **MonoBehaviour／ScriptableObject** 的欄位裡（例如 ``TopicCatalog.mTopics[i].mLines[j].mText``），
沒有 type tree 時用 ``TypeTreeGeneratorAPI`` 從 ``Managed/*.dll``（Mono）或 ``GameAssembly.dll``＋``global-metadata.dat``（IL2CPP）產生。
地址：``source_file = "<容器相對路徑>#<內部檔>/<類別>@<path_id>"``、``location = "mTopics[3].mLines[12].mText"``（具體欄位路徑）。
規則檔 ``monobehaviours`` 區塊用 ``path``（``[*]`` 代表陣列每個元素）指定要導出的欄位。

容器：``*_Data/`` 底下可能是散檔（``resources.assets``…）或單一 ``data.unity3d``（UnityFS bundle，內含所有 SerializedFile 與 .resS）。
bundle 一律以整個檔為單位載入／存回（``packer="lz4"``；原檔若是 LZ4HC，UnityPy 沒有 HC 編碼器，LZ4 標準格式 Unity 同樣能解）。
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
BUNDLE_NAME = "data.unity3d"          # Unity「壓縮建置」：所有 SerializedFile 包成一個 UnityFS
BUNDLE_PACKER = "lz4"


# -- 目錄 -----------------------------------------------------------------------

def _is_data_dir(d: Path) -> bool:
    return d.is_dir() and d.name.endswith("_Data") and ((d / "globalgamemanagers").exists() or (d / BUNDLE_NAME).exists())


def find_data_dir(root: Path) -> Path:
    root = Path(root)
    if _is_data_dir(root):
        return root
    for d in sorted(root.iterdir()):
        if _is_data_dir(d):
            return d
    for d in sorted(root.iterdir()):
        if d.is_dir():
            for sub in sorted(d.iterdir()):
                if _is_data_dir(sub):
                    return sub
    raise SystemExit(f"{root} 底下找不到 *_Data/globalgamemanagers 或 *_Data/{BUNDLE_NAME}（不是 Unity 遊戲目錄？）")


def is_bundle(path: Path) -> bool:
    """UnityFS bundle（開頭 ``UnityFS\0``）。"""
    try:
        with Path(path).open("rb") as f:
            return f.read(8) == b"UnityFS\x00"
    except OSError:
        return False


def container_kind(data_dir: Path) -> str:
    return "bundle" if (Path(data_dir) / BUNDLE_NAME).exists() else "loose"


def asset_files(data_dir: Path, names: tuple[str, ...] = DEFAULT_ASSET_FILES) -> list[Path]:
    """要處理的容器檔。散檔建置：names 裡存在的檔；bundle 建置：只有 data.unity3d（裡面已包含全部）。"""
    data_dir = Path(data_dir)
    if (data_dir / BUNDLE_NAME).exists():
        return [data_dir / BUNDLE_NAME]
    return [data_dir / n for n in names if (data_dir / n).exists()]


def unity_version(data_dir: Path) -> str:
    """從 globalgamemanagers 或 bundle 標頭抓版本字串（如 6000.4.1f1）。"""
    for name in ("globalgamemanagers", BUNDLE_NAME):
        p = Path(data_dir) / name
        if p.exists():
            with p.open("rb") as f:
                head = f.read(64)
            m = re.search(rb"\d+\.\d+\.\d+[a-z]\d+", head)
            if m:
                return m.group(0).decode()
    return ""


def scripting_backend(data_dir: Path) -> str:
    data_dir = Path(data_dir)
    if (data_dir.parent / "GameAssembly.dll").exists():
        return "il2cpp"
    if (data_dir / "Managed").exists():
        return "mono"
    return ""


def load_env(path: Path):
    import UnityPy  # 延遲載入：只有 .venv-unity 才有
    return UnityPy.load(str(path))


def env_is_bundle(env) -> bool:
    return type(env.file).__name__ in ("BundleFile", "WebFile")


def save_env(env) -> bytes:
    """存回整個容器：SerializedFile 原樣；bundle 用 LZ4（見模組說明）。"""
    if env_is_bundle(env):
        return env.file.save(packer=BUNDLE_PACKER)
    return env.file.save()


def inner_name(obj) -> str:
    """物件所在的 SerializedFile 名（bundle 內：resources.assets／level0…；散檔：檔名）。"""
    return getattr(obj.assets_file, "name", "") or ""


def serialized_files(env) -> list:
    """容器裡的所有 SerializedFile（bundle 展開；散檔就是 env.file 本身）。"""
    if env_is_bundle(env):
        return [f for f in env.file.files.values() if type(f).__name__ == "SerializedFile"]
    return [env.file]


def resource_digests(env) -> dict[str, tuple[int, str]]:
    """bundle 內的 .resS 等非 SerializedFile 條目：{名稱: (長度, sha256)}。
    不複製內容（RJ01657316 的 resources.assets.resS 解壓後 1.7 GB），直接對 memoryview 做雜湊。散檔回傳空字典。"""
    import hashlib
    out: dict[str, tuple[int, str]] = {}
    if not env_is_bundle(env):
        return out
    for name, f in env.file.files.items():
        if type(f).__name__ == "SerializedFile":
            continue
        view = getattr(f, "bytes", None)
        if view is None and hasattr(f, "Position") and hasattr(f, "Length"):
            pos = f.Position
            f.Position = 0
            view = f.read_bytes(f.Length)
            f.Position = pos
        if view is None:
            continue
        out[name] = (len(view), hashlib.sha256(view).hexdigest())
    return out


# -- type tree（MonoBehaviour 沒有 type tree 時） -----------------------------------

_GENERATORS: dict[tuple[str, str], Any] = {}


def typetree_generator(data_dir: Path, version: str = ""):
    """從遊戲的 Managed/*.dll（Mono）或 GameAssembly.dll＋global-metadata.dat（IL2CPP）產生 type tree。
    需要 TypeTreeGeneratorAPI（requirements.txt）；同一個資料目錄只建一次。"""
    data_dir = Path(data_dir)
    version = version or unity_version(data_dir)
    key = (str(data_dir), version)
    if key in _GENERATORS:
        return _GENERATORS[key]
    from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator  # 延遲載入
    gen = TypeTreeGenerator(version)
    managed = data_dir / "Managed"
    ga = data_dir.parent / "GameAssembly.dll"
    meta = data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    if managed.is_dir():
        gen.load_local_dll_folder(str(managed))
    elif ga.exists() and meta.exists():
        gen.load_il2cpp(ga.read_bytes(), meta.read_bytes())
    else:
        raise SystemExit(f"{data_dir}：沒有 Managed/ 也沒有 GameAssembly.dll＋global-metadata.dat，無法產生 type tree")
    _GENERATORS[key] = gen
    return gen


def attach_generator(env, data_dir: Path) -> None:
    if getattr(env, "typetree_generator", None) is None:
        env.typetree_generator = typetree_generator(data_dir)


def script_classes(env) -> dict[tuple[str, int], str]:
    """每個 MonoBehaviour 的類別名：{(內部檔名, path_id): ClassName}。
    暫時拿掉 type tree 產生器，用 UnityPy 的基底解析（m_GameObject／m_Enabled／m_Script）跟著 PPtr 找 MonoScript；
    MonoScript 常在別的內部檔（bundle 裡是 globalgamemanagers.assets），交給 UnityPy 解 external。"""
    out: dict[tuple[str, int], str] = {}
    gen = getattr(env, "typetree_generator", None)
    env.typetree_generator = None
    try:
        for sf in serialized_files(env):
            for pid, o in sf.objects.items():
                if o.type.name != "MonoBehaviour":
                    continue
                try:
                    ms = o.read(check_read=False).m_Script.read()
                    out[(sf.name, pid)] = ms.m_ClassName
                except Exception:  # noqa: BLE001 — 讀不到就當沒有
                    continue
    finally:
        env.typetree_generator = gen
    return out


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
    monobehaviours: dict[str, list["MBRule"]] = field(default_factory=dict)   # 類別名 → 規則（見檔尾）
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
    for cname, specs in (raw.get("monobehaviours") or {}).items():
        lst2 = []
        for s in specs:
            if str(s.get("path", "")).startswith("_"):
                continue
            lst2.append(MBRule(
                cls=cname, path=s["path"], context=s.get("context", rules.default_context),
                speaker_from=s.get("speaker_from"), when=s.get("when"), skip=bool(s.get("skip", False)),
            ))
        rules.monobehaviours[cname] = lst2
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


# -- MonoBehaviour 欄位（type tree 路徑） -----------------------------------------

MB_SOURCE_RE = re.compile(r"^(?P<rel>[^#]+)#(?:(?P<inner>.+)/)?(?P<cls>[^/@]+)@(?P<pid>-?\d+)$")


@dataclass
class MBRule:
    cls: str
    path: str                              # "mTopics[*].mLines[*].mText"；[*] = 陣列每個元素
    context: str
    speaker_from: str | None = None        # 同一層的欄位名（例如 mSpeaker）
    when: dict[str, list[Any]] | None = None   # 同一層欄位值的條件，例如 {"mType": [0]}
    skip: bool = False

    def applies(self, parent: Any) -> bool:
        if not self.when:
            return True
        if not isinstance(parent, dict):
            return False
        return all(parent.get(k) in allowed for k, allowed in self.when.items())

    def regex(self) -> re.Pattern:
        return re.compile("^" + re.escape(self.path).replace(r"\[\*\]", r"\[\d+\]") + "$")


@dataclass
class MBObject:
    obj: Any            # UnityPy ObjectReader
    cls: str
    inner: str          # 所在的 SerializedFile 名
    tree: dict

    @property
    def path_id(self) -> int:
        return self.obj.path_id

    def save(self) -> None:
        self.obj.save_typetree(self.tree)


def mb_source(rel: str, inner: str | None, cls: str, pid: int) -> str:
    return f"{rel}#{inner}/{cls}@{pid}" if inner else f"{rel}#{cls}@{pid}"


def parse_mb_source(source_file: str) -> tuple[str, str | None, str, int] | None:
    m = MB_SOURCE_RE.match(source_file)
    if not m:
        return None
    return m.group("rel"), m.group("inner"), m.group("cls"), int(m.group("pid"))


def is_mb_source(source_file: str) -> bool:
    return MB_SOURCE_RE.match(source_file) is not None


def table_source(rel: str, inner: str | None, name: str) -> str:
    """JSON 表格的 source_file：散檔 ``resources.assets#Data_Event``；bundle ``data.unity3d#resources.assets/Data_Event``。"""
    return f"{rel}#{inner}/{name}" if inner else f"{rel}#{name}"


_SEG_RE = re.compile(r"^(\w+)(\[\*\])?$")
_LOC_SEG_RE = re.compile(r"^(\w+)((?:\[\d+\])*)$")


def walk_path(tree: Any, path: str) -> Iterator[tuple[str, Any, Any]]:
    """依規則路徑走訪：yield (具體 location, 父容器, 鍵)。父容器是 dict 時鍵為欄位名，是 list 時鍵為索引。"""
    segs = path.split(".")

    def rec(node: Any, i: int, prefix: str) -> Iterator[tuple[str, Any, Any]]:
        m = _SEG_RE.match(segs[i])
        if not m or not isinstance(node, dict) or m.group(1) not in node:
            return
        name, star = m.group(1), bool(m.group(2))
        last = i == len(segs) - 1
        if not star:
            if last:
                yield prefix + name, node, name
            else:
                yield from rec(node[name], i + 1, prefix + name + ".")
            return
        child = node[name]
        if not isinstance(child, list):
            return
        for idx, item in enumerate(child):
            loc = f"{prefix}{name}[{idx}]"
            if last:
                yield loc, child, idx
            else:
                yield from rec(item, i + 1, loc + ".")

    yield from rec(tree, 0, "")


def resolve_location(tree: Any, loc: str) -> tuple[Any, Any]:
    """具體 location（``mTopics[3].mLines[12].mText``）→ (父容器, 鍵)。找不到就 raise KeyError／IndexError。"""
    node, parent, key = tree, None, None
    for seg in loc.split("."):
        m = _LOC_SEG_RE.match(seg)
        if not m:
            raise KeyError(f"看不懂的 location 片段 {seg!r}")
        name = m.group(1)
        if not isinstance(node, dict) or name not in node:
            raise KeyError(f"{loc}: 沒有欄位 {name}")
        parent, key, node = node, name, node[name]
        for idx in re.findall(r"\[(\d+)\]", m.group(2)):
            i = int(idx)
            if not isinstance(node, list) or i >= len(node):
                raise IndexError(f"{loc}: 索引 {name}[{i}] 超出範圍")
            parent, key, node = node, i, node[i]
    if parent is None:
        raise KeyError(f"空的 location {loc!r}")
    return parent, key


def iter_monobehaviours(env, rules: "Rules", data_dir: Path, classes: dict[tuple[str, int], str] | None = None) -> Iterator[MBObject]:
    """規則涵蓋的 MonoBehaviour（依 type tree 讀成 dict）。需要 TypeTreeGeneratorAPI。"""
    wanted = set(rules.monobehaviours)
    if not wanted:
        return
    classes = classes if classes is not None else script_classes(env)
    attach_generator(env, data_dir)
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        cls = classes.get((inner_name(obj), obj.path_id))
        if cls not in wanted:
            continue
        yield MBObject(obj=obj, cls=cls, inner=inner_name(obj), tree=obj.read_typetree())


def entries_for_mb(source_file: str, mbo: MBObject, rules: "Rules") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in rules.monobehaviours.get(mbo.cls, []):
        if rule.skip:
            continue
        for loc, parent, key in walk_path(mbo.tree, rule.path):
            value = parent[key]
            if not isinstance(value, str) or not value or not JP.search(value) or loc in seen:
                continue
            if not rule.applies(parent):
                continue
            speaker = ""
            if rule.speaker_from and isinstance(parent, dict):
                speaker = str(parent.get(rule.speaker_from, "") or "")
            seen.add(loc)
            out.append({"source_file": source_file, "location": loc, "original": value, "translated": "",
                        "context": rule.context, "speaker": speaker, "code": 0})
    return out


def apply_mb_entry(mbo: MBObject, loc: str, translated: str) -> tuple[bool, str]:
    try:
        parent, key = resolve_location(mbo.tree, loc)
    except (KeyError, IndexError) as e:
        return False, str(e)
    cur = parent[key]
    if not isinstance(cur, str):
        return False, f"{loc} 不是字串欄位"
    if cur == translated:
        return False, ""
    parent[key] = translated
    return True, ""


def tree_diff(a: Any, b: Any, loc: str = "") -> list[tuple[str, Any, Any]]:
    """兩棵 type tree dict 的葉節點差異：[(location, 原值, 新值)]。結構（鍵集合／陣列長度）不同也算一筆。"""
    out: list[tuple[str, Any, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a.keys()) != list(b.keys()):
            out.append((loc or "<root>", f"欄位 {list(a.keys())}", f"欄位 {list(b.keys())}"))
            return out
        for k in a:
            out.extend(tree_diff(a[k], b[k], f"{loc}.{k}" if loc else k))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((loc or "<root>", f"長度 {len(a)}", f"長度 {len(b)}"))
            return out
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out.extend(tree_diff(x, y, f"{loc}[{i}]"))
        return out
    if a != b or type(a) is not type(b):
        out.append((loc or "<root>", a, b))
    return out
