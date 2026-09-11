#!/usr/bin/env python3
"""Extract a Wolf RPG Editor ``Data.wolf`` archive to a loose ``Data/`` folder.

The Wolf engine opens a real file on disk in preference to the copy inside
Data.wolf, so a translation patch never needs to repack the archive: dropping a
``Data/`` folder next to ``Game.exe`` is enough.

Usage
-----
    python extract_wolf.py <game_dir_or_Data.wolf> -o Data
    python extract_wolf.py <game_dir> -o Data --all          # include art/audio
    python extract_wolf.py <game_dir> --list                 # just list contents
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wolfrpg.dxa import DXA_KEYS, DXArchive, DXArchiveError

# Directories that can contain translatable text.  Everything else is art,
# audio or fonts, which a text patch does not touch.
TEXT_DIRS = ("BasicData/", "MapData/")


def find_archive(target: Path) -> Path:
    """Accept either the archive itself or a folder containing it."""
    if target.is_file():
        return target
    for name in ("Data.wolf", "data.wolf"):
        candidate = target / name
        if candidate.is_file():
            return candidate
    # Some releases bury Game.exe one level down in a Japanese-named folder.
    matches = sorted(target.glob("**/Data.wolf"))
    if matches:
        return matches[0]
    raise SystemExit(f"error: no Data.wolf found under {target}")


def wanted(path: str, extract_all: bool) -> bool:
    if extract_all:
        return True
    return path.startswith(TEXT_DIRS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Extract Wolf RPG Data.wolf into a loose Data/ folder.",
    )
    ap.add_argument("game", type=Path,
                    help="game folder, or the path to Data.wolf itself")
    ap.add_argument("-o", "--output", type=Path, default=Path("Data"),
                    help="output directory (default: Data)")
    ap.add_argument("-a", "--all", action="store_true",
                    help="extract every file, not just the text-bearing ones")
    ap.add_argument("-l", "--list", action="store_true",
                    help="list archive contents and exit")
    ap.add_argument("--key", default=None,
                    help="archive key string, if auto-detection fails "
                         f"(known: {', '.join(DXA_KEYS)})")
    args = ap.parse_args(argv)

    archive_path = find_archive(args.game)
    key = args.key.encode("ascii") if args.key else None

    try:
        archive = DXArchive(str(archive_path), key_string=key)
    except DXArchiveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    detected = getattr(archive, "detected_key_name", "explicit key")
    print(f"Archive : {archive_path}")
    print(f"Key     : {detected}")
    print(f"Encoding: codepage {archive.header.char_code_format}")
    print(f"Files   : {len(archive.entries)}")

    if args.list:
        for entry in archive.entries:
            print(f"  {entry.data_size:>10}  {entry.path}")
        archive.close()
        return 0

    targets = [e for e in archive.entries if wanted(e.path, args.all)]
    if not targets:
        print("error: nothing matched the extraction filter", file=sys.stderr)
        archive.close()
        return 1

    print(f"Extracting {len(targets)} file(s) to {args.output}/\n")
    written = 0
    total_bytes = 0
    for entry in targets:
        dest = args.output / entry.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = archive.read(entry)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"  !! {entry.path}: {exc}", file=sys.stderr)
            continue
        if len(data) != entry.data_size:
            print(f"  !! {entry.path}: size mismatch "
                  f"({len(data)} != {entry.data_size})", file=sys.stderr)
            continue
        dest.write_bytes(data)
        written += 1
        total_bytes += len(data)
        if written % 100 == 0 or len(targets) < 50:
            print(f"  {entry.path}")

    archive.close()
    print(f"\nDone: {written}/{len(targets)} files, "
          f"{total_bytes / 1024 / 1024:.1f} MiB")
    if not args.all:
        print("(art and audio were skipped; pass --all to extract everything)")
    return 0 if written == len(targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
