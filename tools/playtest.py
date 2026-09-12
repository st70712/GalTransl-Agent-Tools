#!/usr/bin/env python3
"""實機端（Windows）：啟動遊戲、等 N 秒、報告存活／exit code，列出比啟動時間新的 crash.dmp／Player.log。純標準庫。

    python tools/playtest.py <game> [--exe PATH] [--wait 20] [--kill] [--dry-run]
    python agt.py playtest <game> ...          # 同上（薄轉發）

只做「開得起來嗎、有沒有崩潰檔」的分流；補丁要先照 out/安裝說明.txt 複製進遊戲目錄（本工具不動遊戲檔）。
目視驗收（字有沒有出來、□、亂碼）仍是使用者的工作：結果記在 agt.json 的 playtest 關卡，user_boot_ok 只由使用者確認後 mark。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core import fsutil, state  # noqa: E402
from core.adapter import Project  # noqa: E402
from core.profile import load_profile  # noqa: E402

CRASH_GLOBS = (
    ("LOCALAPPDATA", "Temp/*/*/Crashes/**/crash.dmp"),        # Unity crash handler
    ("USERPROFILE", "AppData/LocalLow/*/*/Player.log"),        # Unity Player.log
    ("USERPROFILE", "AppData/LocalLow/*/*/Player-prev.log"),
)


def resolve_exe(p: Project, explicit: str | None) -> Path:
    if explicit:
        exe = Path(explicit)
        if not exe.exists():
            raise SystemExit(f"找不到 {exe}")
        return exe
    st = state.load_state(p.state_path)
    eng = st.get("engine") or {}
    root = Path((eng.get("extra") or {}).get("game_root") or p.original)
    if not root.exists():
        raise SystemExit(f"遊戲目錄不存在：{root}（實機端才有 original/；或用 --exe 指定）")
    candidates: list[Path] = []
    if eng.get("engine"):
        try:
            v = load_profile(eng["engine"]).variant(eng.get("variant"))
            if v.get("exe") and (root / v["exe"]).exists():
                candidates.append(root / v["exe"])
        except FileNotFoundError:
            pass
    for exe in sorted(root.glob("*.exe")):
        if (root / f"{exe.stem}_Data").is_dir():      # Unity：與 *_Data 同名的 exe
            candidates.insert(0, exe)
        elif exe.name.lower() in ("game.exe", "gamepro.exe"):
            candidates.append(exe)
    if not candidates:
        all_exe = sorted(root.glob("*.exe"))
        if len(all_exe) == 1:
            candidates = all_exe
        else:
            raise SystemExit(f"{root} 裡找不到明確的遊戲執行檔（{[e.name for e in all_exe]}），請用 --exe 指定")
    return candidates[0]


def scan_new_files(exe: Path, since: float) -> list[Path]:
    found: list[Path] = []
    for env_key, pattern in CRASH_GLOBS:
        base = os.environ.get(env_key)
        if not base:
            continue
        for f in Path(base).glob(pattern):
            try:
                if f.is_file() and f.stat().st_mtime >= since:
                    found.append(f)
            except OSError:
                pass
    for pattern in ("*.log", "*/*.log", "error*.txt"):          # 遊戲目錄自己寫的 log（Wolf／RPG Maker 沒有固定位置）
        for f in exe.parent.glob(pattern):
            try:
                if f.is_file() and f.stat().st_mtime >= since:
                    found.append(f)
            except OSError:
                pass
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    fsutil.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game")
    ap.add_argument("--exe", help="遊戲執行檔（預設從 agt.json 的 game_root + profile 的 exe 推斷）")
    ap.add_argument("--wait", type=float, default=20, help="啟動後觀察幾秒（預設 20）")
    ap.add_argument("--kill", action="store_true", help="觀察結束後把遊戲關掉（預設留著給使用者看）")
    ap.add_argument("--dry-run", action="store_true", help="只印出會啟動哪個 exe、掃哪些路徑，不啟動")
    args = ap.parse_args(argv)

    p = Project.from_name(args.game)
    if not p.root.exists():
        raise SystemExit(f"專案 {args.game} 不存在")
    exe = resolve_exe(p, args.exe)
    print(f"遊戲執行檔: {exe}")
    print("崩潰檔掃描: " + "; ".join(f"%{k}%/{g}" for k, g in CRASH_GLOBS) + f"; {exe.parent}/**/*.log")
    if args.dry_run:
        return 0
    if os.name != "nt":
        raise SystemExit("playtest 只在實機端（Windows）跑；這台開不了遊戲")

    t0 = time.time()
    print(f"[{datetime.now():%H:%M:%S}] 啟動，觀察 {args.wait:.0f} 秒…")
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    rc: int | None = None
    deadline = t0 + args.wait
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            break
        time.sleep(0.5)
    elapsed = time.time() - t0
    new_files = scan_new_files(exe, t0 - 1)

    if rc is None:
        alive = True
        print(f"[{datetime.now():%H:%M:%S}] ✓ 仍在執行（{elapsed:.0f} 秒）" + ("，依 --kill 關閉" if args.kill else "，留著給使用者目視"))
        if args.kill:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    else:
        alive = False
        print(f"[{datetime.now():%H:%M:%S}] ✗ 在 {elapsed:.1f} 秒後結束，exit code {rc}")
    if new_files:
        print("啟動後新出現／更新的檔案（崩潰分流用）：")
        for f in new_files:
            print(f"  {f}  ({f.stat().st_size} bytes)")
    else:
        print("沒有新的 crash.dmp / Player.log")
    ok = alive and not any(f.name.lower() == "crash.dmp" for f in new_files)
    summary = (f"exe={exe.name} " + ("存活" if alive else f"exit {rc}") + f" {elapsed:.0f}s"
               + (f"；新檔 {len(new_files)}" if new_files else ""))
    state.mark_gate(p.state_path, "playtest", ok, summary)
    print(f"→ 記錄 playtest {'✓' if ok else '✗'}：{summary}。目視確認後由使用者決定 `agt mark {p.name} user_boot_ok`")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
