"""找出 ``engines/*/adapter.py``，提供偵測與取得轉接器。"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from . import ENGINES_DIR, REPO_ROOT
from .adapter import EngineAdapter, EngineMatch

MIN_CONFIDENCE = 0.5


def engine_dirs() -> list[Path]:
    return sorted(d for d in ENGINES_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith("_") and (d / "adapter.py").exists())


def engine_names() -> list[str]:
    return [d.name for d in engine_dirs()]


def load_adapter_class(name: str) -> type[EngineAdapter]:
    path = ENGINES_DIR / name / "adapter.py"
    if not path.exists():
        raise FileNotFoundError(f"沒有引擎 {name!r}（{path} 不存在）；已知：{engine_names()}")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    modname = f"agt_engines.{name}"
    if modname in sys.modules:
        module = sys.modules[modname]
    else:
        spec = importlib.util.spec_from_file_location(modname, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[modname] = module
        spec.loader.exec_module(module)
    candidates = [obj for _, obj in inspect.getmembers(module, inspect.isclass)
                  if issubclass(obj, EngineAdapter) and obj.name == name]
    if not candidates:
        raise RuntimeError(f"{path} 裡沒有 name == {name!r} 的 EngineAdapter 子類")
    return candidates[0]


def all_adapter_classes() -> dict[str, type[EngineAdapter]]:
    return {name: load_adapter_class(name) for name in engine_names()}


def detect(game_dir: Path) -> list[EngineMatch]:
    """對每個引擎跑 detect，依 confidence 由高到低回傳（包含低於門檻的，讓人看證據）。"""
    game_dir = Path(game_dir)
    matches: list[EngineMatch] = []
    for name, cls in all_adapter_classes().items():
        try:
            m = cls.detect(game_dir)
        except Exception as e:  # 一個引擎壞掉不該擋住其他引擎
            m = EngineMatch(engine=name, confidence=0.0, evidence=[f"detect 例外: {e!r}"])
        if m is not None:
            matches.append(m)
    return sorted(matches, key=lambda m: -m.confidence)


def best(game_dir: Path) -> EngineMatch | None:
    ms = detect(game_dir)
    if ms and ms[0].confidence >= MIN_CONFIDENCE:
        return ms[0]
    return None


def get(name: str, python: str | None = None) -> EngineAdapter:
    return load_adapter_class(name)(python)
