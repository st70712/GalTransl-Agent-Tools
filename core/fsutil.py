"""跨平台檔案系統小工具（純標準庫）：venv 直譯器路徑、目錄連結（symlink／Windows junction）、UTF-8 標準輸出。

Windows 上建 symlink 需要開發人員模式或系統管理員；沒有的話退回 NTFS junction（``mklink /J``，不需權限，
但 ``Path.is_symlink()`` 認不得 junction），所以這裡統一用 :func:`is_link` / :func:`remove_link` 處理兩種連結。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

_JUNCTION_TAG = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)

SYMLINK_HINT = ("Windows 建立符號連結需要開發人員模式（設定 → 隱私權與安全性 → 開發人員專用 → 開發人員模式）"
                "或以系統管理員執行")


def venv_python(venv_dir: Path, os_name: str | None = None) -> Path:
    """venv 內的直譯器：Windows 是 ``Scripts/python.exe``，其他平台是 ``bin/python``。"""
    if (os_name or os.name) == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def is_link(path: Path) -> bool:
    """symlink 或 NTFS junction 都算連結。"""
    path = Path(path)
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", 0) == _JUNCTION_TAG


def remove_link(path: Path) -> None:
    """移除連結本身，不動目標。symlink → unlink；junction → rmdir。"""
    path = Path(path)
    if path.is_symlink():
        path.unlink()
    elif is_link(path):
        os.rmdir(path)


def link_dir(target: Path, link: Path) -> str:
    """把 ``link`` 指到目錄 ``target``；回傳 ``"symlink"`` 或 ``"junction"``。

    先試 symlink；Windows 沒權限時退回 junction（目標必須是本機磁碟的絕對路徑）。
    """
    target = Path(target).resolve()
    link = Path(link)
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except OSError as e:
        if os.name != "nt":
            raise
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True, errors="replace")
        if r.returncode == 0 and is_link(link):
            return "junction"
        raise OSError(f"無法建立目錄連結 {link} → {target}：symlink 失敗（{e}），junction 也失敗（{r.stderr.strip() or r.stdout.strip()}）。"
                      f"{SYMLINK_HINT}") from e


def replace_dir_with_link(target: Path, link: Path, *, rmtree_ok: bool) -> str:
    """讓 ``link`` 變成指向 ``target`` 的連結；既有的連結先移除，既有的實體目錄依 ``rmtree_ok`` 決定刪除或拒絕。"""
    link = Path(link)
    if is_link(link):
        remove_link(link)
    elif link.is_dir():
        if any(link.iterdir()):
            if not rmtree_ok:
                raise FileExistsError(f"{link} 已存在且非空，不覆蓋")
            shutil.rmtree(link)
        else:
            link.rmdir()
    elif link.exists():
        raise FileExistsError(f"{link} 已存在且不是目錄")
    return link_dir(target, link)


def utf8_stdio() -> None:
    """把 stdout／stderr 切成 UTF-8（Windows 主控台預設 cp950，印中文會炸）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
