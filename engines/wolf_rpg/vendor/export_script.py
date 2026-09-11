#!/usr/bin/env python3
"""Export translatable text from a Wolf RPG Editor game to JSON.

The JSON layout matches GalTransl-RPGmaker's ``script.json`` so the same
translation workflow and tooling applies:

    {"info": {...}, "strings": [{"index", "original", "translated", ...}]}

Usage
-----
    python export_script.py Data -o exported
    python export_script.py Data -o exported -s      # one file per source
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wolfrpg.textio import CONTEXTS, RISKY_CONTEXTS, WolfProject

FORMAT_SPEC = {
    "format": "GalTransl-Wolf script.json",
    "version": "1.0",
    "engine": "WOLF RPG Editor 2.x",
    "file_structure": {
        "info": "Metadata about the source game and this export.",
        "strings": "Flat array of translatable strings, in export order.",
    },
    "strings_array_fields": {
        "index": "Sequence number. Do not change; the importer matches on it.",
        "source_file": "Data-relative path of the file the string came from.",
        "location": "Address inside that file. Do not change.",
        "original": "Source text, decoded from the game's codepage.",
        "translated": "Put the translation here. Empty means untranslated.",
        "context": "What kind of text this is; see context_types.",
        "speaker": "Speaker name when the game marks one. This game does not.",
        "code": "Wolf event command ID, or -1 for database/system strings.",
    },
    "context_types": {
        "dialog": "Show Message (cmd 101) - the main script.",
        "choice": "Show Choices (cmd 102) - branch options.",
        "picture_text": "Show Picture in text mode (cmd 150) - on-screen UI text.",
        "call_arg": "String argument passed into a common event call (cmd 210/300). "
                    "The speaker name plate above the message box is one of these.",
        "string_var": "Set String (cmd 122) with a non-path value.",
        "condition": "String comparison operand (cmd 112).",
        "debug": "Debug-only message (cmd 106); never shown to players.",
        "database": "Database string column - item/skill/weapon names and descriptions.",
        "game_title": "Window title from Game.dat.",
    },
    "risky_contexts": {
        "contexts": list(RISKY_CONTEXTS),
        "why": (
            "'condition' strings are compared at runtime against values assigned "
            "by 'string_var' strings. If a matching pair is translated "
            "inconsistently, the comparison stops matching and a branch silently "
            "never fires. Translate both sides identically, or neither. "
            "`import_script.py validate` cross-checks this for you."
        ),
    },
    "control_codes": {
        "\\E": "Wait for keypress / end of message block. Keep it at the start.",
        "\\n or a literal newline": "Line break inside a message.",
        "\\c[n]": "Switch to colour n.",
        "\\f[n]": "Switch to font size n.",
        "\\cself[n]": "Insert the value of self-variable n.",
        "\\v[n]": "Insert the value of variable n.",
        "\\sp[n]": "Insert n spaces.",
        "note": "Control codes must be preserved exactly, including the backslash.",
    },
    "ai_agent_guidelines": [
        "Fill in 'translated'; never edit 'index', 'location' or 'source_file'.",
        "Preserve every control code exactly as it appears in 'original'.",
        "Preserve line-break structure; Wolf message boxes are fixed height.",
        "Leave 'translated' empty for anything you choose not to translate.",
        "Translations must be encodable in the target codepage "
        "(see info.encoding); run import_script.py validate to check.",
    ],
}


def build_entries(project: WolfProject) -> list[dict]:
    entries = []
    for slot in project.slots():
        entries.append({
            "index": len(entries),
            "source_file": slot.source_file,
            "location": slot.location,
            "original": slot.raw.decode(project.encoding, errors="replace"),
            "translated": "",
            "context": slot.context,
            "speaker": "",
            "code": slot.code,
        })
    return entries


def merge_translations(entries: list[dict], previous: Path) -> tuple[int, int]:
    """Carry translations over from an earlier export.

    ``index`` shifts whenever the exporter starts covering more strings, but
    ``(source_file, location)`` addresses a fixed slot in the game data, so it
    survives. Only entries whose source text still matches are carried over --
    anything else is left untranslated rather than silently mismatched.

    Returns ``(carried_over, dropped)``.
    """
    payload = json.loads(previous.read_text(encoding="utf-8"))
    old = {}
    for entry in payload.get("strings", []):
        if entry.get("translated"):
            old[(entry["source_file"], entry["location"])] = entry

    carried = 0
    dropped = 0
    for entry in entries:
        match = old.pop((entry["source_file"], entry["location"]), None)
        if match is None:
            continue
        if match["original"] != entry["original"]:
            dropped += 1
            continue
        entry["translated"] = match["translated"]
        carried += 1
    return carried, dropped + len(old)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Export translatable text from a Wolf RPG game to JSON.")
    ap.add_argument("data", type=Path,
                    help="extracted Data/ directory (contains BasicData/ and MapData/)")
    ap.add_argument("-o", "--output", type=Path, default=Path("exported"),
                    help="output directory (default: exported)")
    ap.add_argument("-s", "--split", action="store_true",
                    help="write one JSON per source file instead of one script.json")
    ap.add_argument("-e", "--encoding", default="cp932",
                    help="codepage the game's strings are stored in (default: cp932)")
    ap.add_argument("-m", "--merge", type=Path, default=None,
                    help="carry translations over from an earlier export "
                         "(matched by source_file+location, not by index)")
    args = ap.parse_args(argv)

    if not args.data.is_dir():
        print(f"error: {args.data} is not a directory", file=sys.stderr)
        return 1

    project = WolfProject(str(args.data), encoding=args.encoding)
    for err in project.errors:
        print(f"warning: could not load {err}", file=sys.stderr)

    entries = build_entries(project)
    if args.merge is not None:
        if not args.merge.is_file():
            print(f"error: {args.merge} not found", file=sys.stderr)
            return 1
        carried, dropped = merge_translations(entries, args.merge)
        print(f"Merged {carried} translation(s) from {args.merge}")
        if dropped:
            print(f"  ({dropped} could not be carried over: the slot is gone or "
                  f"its source text changed)")
    if not entries:
        print("error: no translatable text found. Is this an extracted Data/ "
              "directory?", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True, exist_ok=True)

    title = ""
    if project.game_dat is not None:
        title = project.game_dat.title.decode(args.encoding, errors="replace")

    info = {
        "game_title": title,
        "engine": "WOLF RPG Editor",
        "encoding": args.encoding,
        "version": "1.0",
        "source_dir": str(args.data),
        "string_count": len(entries),
    }

    if args.split:
        by_file: dict[str, list[dict]] = collections.defaultdict(list)
        for entry in entries:
            by_file[entry["source_file"]].append(entry)
        for source_file, group in by_file.items():
            name = source_file.replace("/", "_").rsplit(".", 1)[0] + ".json"
            payload = {"info": {**info, "string_count": len(group),
                                "source_file": source_file},
                       "strings": group}
            (args.output / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {len(by_file)} file(s) to {args.output}/")
    else:
        payload = {"info": info, "strings": entries}
        (args.output / "script.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {args.output / 'script.json'}")

    (args.output / "format_specification.json").write_text(
        json.dumps(FORMAT_SPEC, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary
    by_context = collections.Counter(e["context"] for e in entries)
    by_source = collections.Counter(e["source_file"] for e in entries)
    print(f"\nGame    : {title}")
    print(f"Strings : {len(entries)}")
    print("\nBy context:")
    for context in CONTEXTS:
        if by_context[context]:
            flag = "  (behaviour-sensitive)" if context in RISKY_CONTEXTS else ""
            print(f"  {context:14s} {by_context[context]:6d}{flag}")
    print("\nBy file:")
    for source_file, count in by_source.most_common():
        print(f"  {source_file:34s} {count:6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
