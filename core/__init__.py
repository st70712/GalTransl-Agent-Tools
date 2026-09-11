"""GalTransl-Agent-Tools 共用函式庫（純標準庫，Python 3.11+）。"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINES_DIR = REPO_ROOT / "engines"
PROJECTS_DIR = REPO_ROOT / "projects"
TOOLS_DIR = REPO_ROOT / "tools"

__all__ = ["REPO_ROOT", "ENGINES_DIR", "PROJECTS_DIR", "TOOLS_DIR"]
