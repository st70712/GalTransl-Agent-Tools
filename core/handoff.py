"""兩站接力的交接包（docs/two-site.md）：``pack`` 打包、``unpack`` 收包、``classify`` 判斷來料是什麼。

交接包 = 一個 zip：根目錄 ``handoff.json``（manifest）+ 專案裡幾 MB 的可攜衍生物（agt.json、exported/ 的文本與檢查點、
glossary、字型字元集、HANDOFF.md、logs）。絕不放 original/、extracted/、translated/、out/、variants/。
``seq`` 每 pack 一次 +1、只增不減；``unpack`` 拒收 seq 不大於本地的包（``--force`` 越過）。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import PROJECTS_DIR, REPO_ROOT, config, state
from .adapter import Project

FORMAT = 1
MANIFEST = "handoff.json"
REQUIRED = ("agt.json", "exported/script.json", "exported/.agt.json")
OPTIONAL = ("HANDOFF.md", "exported/format_specification.json", "exported/untranslated.json",
            "exported/.agt_checkpoint.json", "glossary.txt", "font_charset.txt", "charset_map.json",
            "unity_rules.json")
LOG_GLOB = "logs/*.log"
LOG_MAX_BYTES = 2_000_000
TEMPLATE = REPO_ROOT / "docs" / "templates" / "HANDOFF.template.md"
BUNDLE_RE = re.compile(r"^(?P<game>.+)-(?P<seq>\d{3})-to-(?P<to>[a-z]+)-(?P<ts>\d{8}-\d{4})\.zip$")
# zip 內出現這些路徑尾巴 → 這是完整遊戲，不是交接包
GAME_MARKERS = (
    ("Data.wolf", "WOLF RPG 2.x"), ("Data/BasicData.wolf", "WOLF RPG 3.x"),
    ("www/data/System.json", "RPG Maker MV"), ("data/System.json", "RPG Maker MZ"),
    ("_Data/globalgamemanagers", "Unity"), ("_Data/data.unity3d", "Unity（單檔 bundle）"), ("Game.rgss3a", "RPG Maker VX Ace"),
)


class HandoffError(Exception):
    pass


@dataclass
class Intake:
    kind: str                                   # bundle_zip | bundle_dir | bundle_pool | project_dir | game_zip | game_dir | missing | unknown
    path: Path
    manifest: dict[str, Any] | None = None
    hints: list[str] = field(default_factory=list)
    candidates: list[Path] = field(default_factory=list)


@dataclass
class PackResult:
    bundle: Path
    seq: int
    to: str
    files: list[str]
    copied_to: Path | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class UnpackResult:
    project: Project
    seq: int
    manifest: dict[str, Any]
    created: bool
    files: list[str]
    backups: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# -- 共用 ---------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo_info() -> dict[str, Any]:
    """本機 repo 的 HEAD 與是否有未提交變更（git 不可用時都是 None）。"""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True)
    except OSError:
        return {"head": None, "dirty": None}
    if head.returncode != 0 or status.returncode != 0:
        return {"head": None, "dirty": None}
    return {"head": head.stdout.strip(), "dirty": bool(status.stdout.strip())}


def bundle_name(game: str, seq: int, to: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    return f"{game}-{seq:03d}-to-{to}-{when:%Y%m%d-%H%M}.zip"


def parse_bundle_name(name: str) -> dict[str, Any] | None:
    m = BUNDLE_RE.match(name)
    if not m:
        return None
    return {"game": m["game"], "seq": int(m["seq"]), "to_site": m["to"], "ts": m["ts"]}


def collect(p: Project, include_logs: bool = True) -> list[tuple[Path, str]]:
    """要進包的 (絕對路徑, 包內路徑)；REQUIRED 缺一就報錯。"""
    files: list[tuple[Path, str]] = []
    for rel in REQUIRED:
        f = p.root / rel
        if not f.exists():
            raise HandoffError(f"交接包必要檔案不存在：{f}（先 agt export）")
        files.append((f, rel))
    for rel in OPTIONAL:
        f = p.root / rel
        if f.exists():
            files.append((f, rel))
    if include_logs:
        for f in sorted(p.root.glob(LOG_GLOB)):
            if f.is_file() and f.stat().st_size <= LOG_MAX_BYTES:
                files.append((f, f.relative_to(p.root).as_posix()))
    return files


def ensure_handoff_md(p: Project) -> bool:
    """沒有 HANDOFF.md 就從範本產生；回傳是否新建。"""
    dst = p.root / "HANDOFF.md"
    if dst.exists():
        return False
    text = TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.exists() else "# HANDOFF — {game}\n"
    dst.write_text(text.replace("{game}", p.name), encoding="utf-8")
    return True


# -- pack ---------------------------------------------------------------------

def pack(p: Project, to: str, *, from_site: str, out_dir: Path | None = None,
         include_logs: bool = True, allow_dirty: bool = False) -> PackResult:
    warnings: list[str] = []
    if not p.script.exists():
        raise HandoffError(f"{p.script} 不存在：先 agt export")
    info = repo_info()
    if info["dirty"] and not allow_dirty:
        raise HandoffError("repo 有未提交的變更。接力協定：pack 前先 commit + push（讓對方 pull 到同一版程式碼）；"
                           "確定不需要就加 --allow-dirty")
    if info["dirty"] is None:
        warnings.append("git 不可用，manifest 不含 repo 版本；請自行確認兩站程式碼一致")
    if ensure_handoff_md(p):
        warnings.append("HANDOFF.md 是剛從範本產生的空檔——請先填「本站完成／請對方做」再重新 pack")

    seq = int(state.handoff_info(p.state_path).get("seq", 0)) + 1
    now = datetime.now()
    name = bundle_name(p.name, seq, to, now)
    state.set_handoff(p.state_path, {
        "seq": seq, "holder": to, "from_site": from_site, "packed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "packed_by": socket.gethostname(), "bundle": name,
    })
    files = collect(p, include_logs=include_logs)
    eng = (state.load_state(p.state_path).get("engine") or {}).get("engine", "")
    manifest: dict[str, Any] = {
        "format": FORMAT, "game": p.name, "seq": seq, "from_site": from_site, "to_site": to,
        "packed_at": now.strftime("%Y-%m-%d %H:%M:%S"), "host": socket.gethostname(), "engine": eng,
        "repo_head": info["head"], "repo_dirty": info["dirty"], "files": {},
    }
    out_dir = out_dir or (p.root / "handoff")
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / name
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arc in files:
            data = abs_path.read_bytes()
            manifest["files"][arc] = {"size": len(data), "sha256": _sha256(data)}
            zf.writestr(arc, data)
        zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))

    copied_to: Path | None = None
    cfg_dir = config.load_config().get("handoff_dir", "").strip()
    if cfg_dir:
        shared = config.handoff_dir()
        if shared is None:
            warnings.append(f"handoff_dir={cfg_dir} 不存在（Drive 沒掛載？）；交接包只留在本機，請手動搬")
        else:
            dst_dir = shared / p.name / "handoff"
            dst_dir.mkdir(parents=True, exist_ok=True)
            copied_to = dst_dir / name
            shutil.copy2(bundle, copied_to)
    return PackResult(bundle=bundle, seq=seq, to=to, files=[arc for _, arc in files],
                      copied_to=copied_to, warnings=warnings)


# -- classify / unpack ----------------------------------------------------------

def _zip_manifest(zf: zipfile.ZipFile) -> dict[str, Any] | None:
    names = set(zf.namelist())
    if MANIFEST in names:
        return json.loads(zf.read(MANIFEST).decode("utf-8"))
    if "agt.json" in names and "exported/script.json" in names:
        st = json.loads(zf.read("agt.json").decode("utf-8"))
        return {"format": 0, "game": "", "seq": int((st.get("handoff") or {}).get("seq", 0))}
    return None


def _dir_manifest(d: Path) -> dict[str, Any] | None:
    if (d / MANIFEST).exists():
        return json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    if (d / "agt.json").exists() and (d / "exported" / "script.json").exists():
        st = json.loads((d / "agt.json").read_text(encoding="utf-8"))
        return {"format": 0, "game": "", "seq": int((st.get("handoff") or {}).get("seq", 0))}
    return None


def _game_hints(names: list[str]) -> list[str]:
    hints: list[str] = []
    for marker, label in GAME_MARKERS:
        if any(n.endswith(marker) for n in names):
            hints.append(f"{marker} → {label}")
    return hints


def pick_latest(d: Path, to_site: str | None = None) -> list[Path]:
    """目錄裡的交接包，依 seq 由新到舊；給了 to_site 就只留寄給該站的。"""
    found: list[tuple[int, str, Path]] = []
    for f in d.glob("*.zip"):
        info = parse_bundle_name(f.name)
        if info is None:
            continue
        if to_site and info["to_site"] != to_site:
            continue
        found.append((info["seq"], info["ts"], f))
    return [f for _, _, f in sorted(found, reverse=True)]


def classify(path: Path) -> Intake:
    """判斷使用者給的是什麼：交接包（zip／目錄／一堆 zip 的資料夾）、既有專案、完整遊戲（zip／目錄）。"""
    path = Path(path)
    if not path.exists():
        return Intake(kind="missing", path=path)
    if path.is_file():
        if not zipfile.is_zipfile(path):
            return Intake(kind="unknown", path=path, hints=["不是 zip；交接包是 .zip，完整遊戲請解壓後給目錄"])
        with zipfile.ZipFile(path) as zf:
            man = _zip_manifest(zf)
            if man is not None:
                if not man.get("game"):
                    man["game"] = (parse_bundle_name(path.name) or {}).get("game", path.stem)
                return Intake(kind="bundle_zip", path=path, manifest=man)
            return Intake(kind="game_zip", path=path, hints=_game_hints(zf.namelist()))
    man = _dir_manifest(path)
    if man is not None:
        try:
            inside_projects = path.resolve().parent == PROJECTS_DIR.resolve()
        except OSError:
            inside_projects = False
        return Intake(kind="project_dir" if inside_projects else "bundle_dir", path=path, manifest=man)
    zips = pick_latest(path)
    if zips:
        return Intake(kind="bundle_pool", path=path, candidates=zips)
    hints = _game_hints([q.relative_to(path).as_posix() for q in path.rglob("*") if q.is_file()][:20000])
    return Intake(kind="game_dir", path=path, hints=hints)


def _safe_member(name: str) -> str | None:
    """zip 成員名淨化：拒絕絕對路徑、磁碟機、``..``。"""
    pp = PurePosixPath(name.replace("\\", "/"))
    if pp.is_absolute() or ".." in pp.parts or (pp.parts and ":" in pp.parts[0]):
        return None
    return pp.as_posix()


def _read_bundle(src: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """讀整個交接包到記憶體（只有幾 MB）；回傳 (manifest, {包內路徑: bytes})。"""
    members: dict[str, bytes] = {}
    if src.is_file():
        with zipfile.ZipFile(src) as zf:
            man = _zip_manifest(zf)
            if man is None:
                raise HandoffError(f"{src} 不是交接包（沒有 {MANIFEST}，也沒有 agt.json + exported/script.json）")
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                safe = _safe_member(name)
                if safe is None:
                    raise HandoffError(f"交接包內有可疑路徑：{name}")
                members[safe] = zf.read(name)
    else:
        man = _dir_manifest(src)
        if man is None:
            raise HandoffError(f"{src} 不是交接包目錄")
        for f in src.rglob("*"):
            if f.is_file():
                members[f.relative_to(src).as_posix()] = f.read_bytes()
    if not man.get("game"):
        man["game"] = (parse_bundle_name(src.name) or {}).get("game", "")
    members.pop(MANIFEST, None)
    return man, members


def unpack(src: Path, projects_dir: Path | None = None, *, game: str | None = None,
           force: bool = False, site: str | None = None) -> UnpackResult:
    src = Path(src)
    projects_dir = projects_dir or PROJECTS_DIR
    warnings: list[str] = []
    if src.is_dir() and _dir_manifest(src) is None:
        cands = pick_latest(src, site)
        if not cands:
            raise HandoffError(f"{src} 裡沒有交接包（*.zip，檔名 <game>-NNN-to-<site>-<時間>.zip）")
        if len(cands) > 1:
            warnings.append("目錄裡有多個交接包，取 seq 最大的：" + ", ".join(c.name for c in cands[:5]))
        src = cands[0]
    manifest, members = _read_bundle(src)
    for rel in REQUIRED:
        if rel not in members:
            raise HandoffError(f"交接包缺少 {rel}")

    name = game or manifest.get("game") or ""
    if not name:
        raise HandoffError("無法決定專案名：交接包沒有 manifest，請加 --game")
    if game and manifest.get("game") and game != manifest["game"]:
        warnings.append(f"專案名 {game} 與交接包的 {manifest['game']} 不同——兩站專案名應一致（Unity 規則檔靠名字對應）")
    p = Project(projects_dir / name)
    created = not p.root.exists()
    p.ensure_dirs()

    incoming_state = json.loads(members["agt.json"].decode("utf-8"))
    incoming_seq = int((incoming_state.get("handoff") or {}).get("seq") or manifest.get("seq") or 0)
    local_seq = int(state.handoff_info(p.state_path).get("seq", 0))
    if incoming_seq <= local_seq and not force:
        raise HandoffError(f"交接包 seq #{incoming_seq} 不比本地 #{local_seq} 新，拒收（舊包或已收過）；確定要覆蓋加 --force")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    if p.script.exists():
        b = p.exported / f"script.backup-{ts}.json"
        shutil.copy2(p.script, b)
        backups.append(b)
    if p.state_path.exists():
        b = p.root / f"agt.backup-{ts}.json"
        shutil.copy2(p.state_path, b)
        backups.append(b)

    written: list[str] = []
    for rel, data in members.items():
        expect = (manifest.get("files") or {}).get(rel, {}).get("sha256")
        if expect and expect != _sha256(data):
            raise HandoffError(f"{rel} 的 sha256 與 manifest 不符，交接包可能傳輸不完整")
        dst = p.root / rel
        if rel == "agt.json":
            merged = state.merge_states(state.load_state(p.state_path), incoming_state)
            state.save_state(p.state_path, merged)
            written.append(rel)
            continue
        if rel.startswith("logs/") and dst.exists():
            continue                       # logs 只增不刪、不覆蓋
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        written.append(rel)

    local = repo_info()
    if manifest.get("repo_head") and local["head"] and manifest["repo_head"] != local["head"]:
        warnings.append(f"兩站 repo 不同步：對方 HEAD {manifest['repo_head'][:12]}，本機 {local['head'][:12]}——先 git pull 再繼續")
    if manifest.get("repo_dirty"):
        warnings.append("對方 pack 時 repo 有未提交變更，程式碼可能沒同步到這邊")
    if not p.original.exists():
        warnings.append("此專案沒有 original/（翻譯端骨架）：只能跑 translate / fix_text / check-codes / validate")
    return UnpackResult(project=p, seq=incoming_seq, manifest=manifest, created=created,
                        files=written, backups=backups, warnings=warnings)
