#!/usr/bin/env python3
"""Parse every data file under a ``Data/`` folder, write it back, compare bytes.

This is the gate that has to pass before any translation work starts: if the
parser understands a file completely it can reproduce it byte for byte, and if
it cannot, the difference is somewhere the parser is guessing.

    python roundtrip_test.py Data_full
    python roundtrip_test.py Data          # the 2.281 trial data, as a regression
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wolfrpg.common_events import CommonEvents
from wolfrpg.database import Database
from wolfrpg.filecoder import WolfFormatError
from wolfrpg.game_dat import GameDat
from wolfrpg.map import Map

DATABASES = ("DataBase", "CDataBase", "SysDatabase")


def diff_note(original: bytes, produced: bytes) -> str:
    if len(original) != len(produced):
        note = f"length {len(original)} -> {len(produced)}"
    else:
        note = f"length {len(original)} (same)"
    for i, (a, b) in enumerate(zip(original, produced)):
        if a != b:
            lo = max(0, i - 8)
            return (f"{note}, first difference at byte {i}: "
                    f"{original[lo:i + 8].hex(' ')} -> {produced[lo:i + 8].hex(' ')}")
    return note


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path, help="解包後的 Data 目錄")
    args = ap.parse_args(argv)

    basic = args.data / "BasicData"
    maps = args.data / "MapData"
    tmp = Path(tempfile.mkdtemp(prefix="wolf-roundtrip-"))

    checks: list[tuple[str, list[Path], callable]] = []

    for path in sorted(maps.glob("*.mps")):
        checks.append((
            f"MapData/{path.name}", [path],
            lambda p=path, out=tmp / path.name: (Map(str(p)).dump(str(out)), [out])[1],
        ))

    ce = basic / "CommonEvent.dat"
    if ce.is_file():
        checks.append((
            "BasicData/CommonEvent.dat", [ce],
            lambda p=ce, out=tmp / "CommonEvent.dat":
                (CommonEvents(str(p)).dump(str(out)), [out])[1],
        ))

    for name in DATABASES:
        project, dat = basic / f"{name}.project", basic / f"{name}.dat"
        if not (project.is_file() and dat.is_file()):
            continue
        checks.append((
            f"BasicData/{name}.[project+dat]", [project, dat],
            lambda pr=project, dt=dat, o1=tmp / f"{name}.project", o2=tmp / f"{name}.dat":
                (Database(str(pr), str(dt)).dump(str(o1), str(o2)), [o1, o2])[1],
        ))

    game = basic / "Game.dat"
    if game.is_file():
        checks.append((
            "BasicData/Game.dat", [game],
            lambda p=game, out=tmp / "Game.dat":
                (GameDat(str(p)).dump(str(out)), [out])[1],
        ))

    failed = 0
    for label, sources, run in checks:
        try:
            outputs = run()
        except (WolfFormatError, Exception) as exc:  # noqa: B014 - report anything
            print(f"  FAIL  {label}: {type(exc).__name__}: {exc}")
            failed += 1
            continue
        for src, out in zip(sources, outputs):
            original, produced = src.read_bytes(), out.read_bytes()
            if original == produced:
                print(f"  ok    {label} [{src.name}] {len(original)} bytes")
            else:
                print(f"  FAIL  {label} [{src.name}]: {diff_note(original, produced)}")
                failed += 1

    total = sum(len(s) for _, s, _ in checks)
    print(f"\n{total - failed}/{total} files reproduced byte for byte")
    for leftover in tmp.iterdir():
        leftover.unlink()
    os.rmdir(tmp)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
