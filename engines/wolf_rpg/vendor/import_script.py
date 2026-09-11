#!/usr/bin/env python3
"""Import translated JSON back into a Wolf RPG Editor game, and check the result.

Subcommands
-----------
    validate  translation.json [-u untranslated.json] [-c CONTEXT ...]
    import    Data translation.json -o Data_zh [-e cp950]
    verify    Data Data_zh

The Wolf engine opens a real file on disk before looking inside ``Data.wolf``,
so the patched ``Data/`` tree produced by ``import`` is dropped next to
``Game.exe`` as-is.  The archive is never rebuilt.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wolfrpg.textio import RISKY_CONTEXTS, WolfProject
from wolfrpg.textnorm import normalise, unencodable_chars

CONTROL_CODE_RE = re.compile(r"\\[a-zA-Z]+(?:\[[^\]]*\])?")

# String args that resolve control flow and must never differ between original
# and patched data.  For SetLabel/JumpLabel every arg is the label itself; for
# CommonEventByName only the first arg names the event -- the rest are arguments
# handed to it, and those legitimately carry on-screen text.
FLOW_CRITICAL_ARGS: dict[int, slice] = {
    212: slice(None),   # SetLabel
    213: slice(None),   # JumpLabel
    300: slice(0, 1),   # CommonEventByName - only the event name
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_translation(target: Path) -> tuple[dict, list[dict]]:
    """Load one JSON file or every ``*.json`` in a directory."""
    if target.is_dir():
        files = sorted(p for p in target.glob("*.json")
                       if p.name != "format_specification.json")
        if not files:
            raise SystemExit(f"error: no JSON files in {target}")
    else:
        files = [target]

    info: dict = {}
    entries: list[dict] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not info:
            info = payload.get("info", {})
        entries.extend(payload.get("strings", []))
    return info, entries


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def check_control_codes(entry: dict) -> str | None:
    original = collections.Counter(CONTROL_CODE_RE.findall(entry["original"]))
    translated = collections.Counter(CONTROL_CODE_RE.findall(entry["translated"]))
    if original == translated:
        return None
    missing = original - translated
    added = translated - original
    parts = []
    if missing:
        parts.append("dropped " + ", ".join(sorted(missing.elements())))
    if added:
        parts.append("added " + ", ".join(sorted(added.elements())))
    return "; ".join(parts)


def check_consistency(entries: list[dict]) -> list[str]:
    """Flag identical source strings that were translated inconsistently.

    A ``condition`` string is compared at runtime against a value that came from
    somewhere else -- a ``string_var`` assignment, a ``choice`` the player
    picked, or a ``database`` column such as a difficulty name.  Translating one
    side but not the other, or translating them differently, makes the
    comparison stop matching and silently kills the branch.  Every context is
    therefore considered, not just the obviously text-like ones.
    """
    by_original: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set))
    for entry in entries:
        by_original[entry["original"]][entry["context"]].add(entry["translated"])

    problems = []
    for original, contexts in by_original.items():
        if "condition" not in contexts:
            continue
        all_translations = set().union(*contexts.values())
        if len(all_translations) > 1:
            shown = ", ".join(repr(t) if t else "<untranslated>"
                              for t in sorted(all_translations))
            others = ", ".join(sorted(c for c in contexts if c != "condition"))
            problems.append(
                f"{original!r} is compared as a condition and also appears as "
                f"{others or 'another condition'}, but the translations differ: "
                f"{shown}"
            )
    return problems


def check_encoding(entries: list[dict], encoding: str) -> list[tuple[dict, str]]:
    failures = []
    for entry in entries:
        if not entry["translated"]:
            continue
        try:
            entry["translated"].encode(encoding)
        except UnicodeEncodeError as exc:
            bad = entry["translated"][exc.start:exc.end]
            failures.append((entry, bad))
    return failures


def encode_for_game(text: str, encoding: str) -> bytes | None:
    """把 ``text`` 編成遊戲用的位元組，必要時先做字形正規化。

    回傳 ``None`` 表示連正規化後都編不出來。
    """
    try:
        return text.encode(encoding)
    except UnicodeEncodeError:
        pass
    fixed = normalise(text)
    try:
        return fixed.encode(encoding)
    except UnicodeEncodeError:
        return None


JAPANESE_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")
ANY_CODE_RE = re.compile(r"\\[a-zA-Z]+(?:\[[^\]]*\])?|\\[><.!^|-]")

# Never shown to a player, so leaving them in Japanese costs nothing.
INVISIBLE_CONTEXTS = ("debug",)


def check_untranslated_visible(entries: list[dict]) -> list[dict]:
    """Untranslated strings a player will actually read.

    Once the data is switched to a Chinese codepage these still *display*
    (Big5 covers kana and most kanji), but they display as Japanese -- which
    for things like battle messages or item names is a real gap in the patch.
    Worth reviewing before shipping.
    """
    out = []
    for entry in entries:
        if entry["translated"] or entry["context"] in INVISIBLE_CONTEXTS:
            continue
        stripped = ANY_CODE_RE.sub("", entry["original"] or "")
        if JAPANESE_RE.search(stripped):
            out.append(entry)
    return out


def check_mojibake(entries: list[dict], encoding: str) -> list[dict]:
    """找出「不會被翻譯、也轉不了碼」因而會在遊戲裡變成亂碼的條目。

    把 Game.dat 的語言標記設成中文之後，引擎會用 Big5 解讀所有文字。未翻譯的
    日文多半能原樣轉碼並正常顯示，但只要含有 Big5 沒有的字元，整段就會變成
    亂碼方框——包括「……。」這種純符號的台詞。
    """
    doomed = []
    for entry in entries:
        if entry["translated"]:
            continue
        original = entry["original"]
        if not original or original.isascii():
            continue
        if encode_for_game(original, encoding) is None:
            doomed.append(entry)
    return doomed


def cmd_validate(args) -> int:
    info, entries = load_translation(args.translation)
    encoding = args.encoding or info.get("encoding", "cp932")

    total = len(entries)
    translated = [e for e in entries if e["translated"]]
    print("=== Translation Validation ===")
    print(f"Total strings: {total}")
    print(f"Translated:    {len(translated)}")
    print(f"Untranslated:  {total - len(translated)}")
    print(f"Progress:      {len(translated) / total * 100:.1f}%" if total else "")

    by_context = collections.defaultdict(lambda: [0, 0])
    by_file = collections.defaultdict(lambda: [0, 0])
    for entry in entries:
        for bucket in (by_context[entry["context"]], by_file[entry["source_file"]]):
            bucket[1] += 1
            if entry["translated"]:
                bucket[0] += 1

    print("\nBy context:")
    for context, (done, count) in sorted(by_context.items()):
        flag = "  (behaviour-sensitive)" if context in RISKY_CONTEXTS else ""
        print(f"  {context:14s} {done}/{count} ({done / count * 100:.1f}%){flag}")

    print("\nBy file:")
    for source_file, (done, count) in sorted(by_file.items()):
        print(f"  {source_file:34s} {done}/{count} ({done / count * 100:.1f}%)")

    problems = 0

    failures = check_encoding(entries, encoding)
    if failures:
        problems += len(failures)
        print(f"\n!! {len(failures)} translation(s) cannot be encoded as {encoding}:")
        for entry, bad in failures[:10]:
            print(f"   [{entry['index']}] {entry['source_file']} "
                  f"contains {bad!r}")
        if len(failures) > 10:
            print(f"   ... and {len(failures) - 10} more")
        print(f"   Pick a codepage that covers your target language "
              f"(-e cp950 for Traditional Chinese, -e cp936 for Simplified).")

    code_issues = [(e, msg) for e in translated
                   if (msg := check_control_codes(e)) is not None]
    if code_issues:
        problems += len(code_issues)
        print(f"\n!! {len(code_issues)} translation(s) changed control codes:")
        for entry, msg in code_issues[:10]:
            print(f"   [{entry['index']}] {entry['source_file']}: {msg}")
        if len(code_issues) > 10:
            print(f"   ... and {len(code_issues) - 10} more")

    visible = check_untranslated_visible(entries)
    if visible:
        problems += len(visible)
        by_ctx = collections.Counter(e["context"] for e in visible)
        print(f"\n!! {len(visible)} untranslated string(s) still contain Japanese "
              f"a player will read:")
        for context, count in by_ctx.most_common():
            print(f"   {context:14s} {count}")
        for entry in visible[:12]:
            print(f"   [{entry['index']}] {entry['context']}: "
                  f"{entry['original'][:50]!r}")
        if len(visible) > 12:
            print(f"   ... and {len(visible) - 12} more")
        print("   Re-run the translator, or accept them as untranslated.")

    doomed = check_mojibake(entries, encoding)
    if doomed:
        problems += len(doomed)
        by_ctx = collections.Counter(e["context"] for e in doomed)
        print(f"\n!! {len(doomed)} untranslated string(s) WILL render as garbage "
              f"in game (cannot be represented in {encoding}):")
        for context, count in by_ctx.most_common():
            note = "  <- players never see these" if context == "debug" else ""
            print(f"   {context:14s} {count}{note}")
        visible = [e for e in doomed if e["context"] != "debug"]
        for entry in visible[:10]:
            bad = "".join(unencodable_chars(normalise(entry["original"]), encoding))
            print(f"   [{entry['index']}] {entry['source_file']} {bad!r}: "
                  f"{entry['original'][:46]!r}")
        if len(visible) > 10:
            print(f"   ... and {len(visible) - 10} more visible ones")
        print("   Translate these, or add the characters to wolfrpg/textnorm.py.")

    consistency = check_consistency(entries)
    if consistency:
        problems += len(consistency)
        print(f"\n!! {len(consistency)} condition/assignment mismatch(es):")
        for msg in consistency[:10]:
            print(f"   {msg}")
        if len(consistency) > 10:
            print(f"   ... and {len(consistency) - 10} more")

    if not problems:
        print("\nNo issues found.")

    if args.output_untranslated:
        contexts = None if args.context == ["all"] else set(args.context)
        selected = [e for e in entries
                    if not e["translated"]
                    and (contexts is None or e["context"] in contexts)]
        payload = {"info": {**info, "string_count": len(selected)},
                   "strings": selected}
        args.output_untranslated.parent.mkdir(parents=True, exist_ok=True)
        args.output_untranslated.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        filt = "all" if contexts is None else "、".join(sorted(contexts))
        print(f"\nWrote {len(selected)} untranslated string(s) to "
              f"{args.output_untranslated}  (context filter: {filt})")

    return 1 if problems else 0


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def cmd_import(args) -> int:
    info, entries = load_translation(args.translation)
    encoding = args.encoding or info.get("encoding", "cp932")

    if not args.data.is_dir():
        print(f"error: {args.data} is not a directory", file=sys.stderr)
        return 1

    failures = check_encoding(entries, encoding)
    if failures and not args.skip_unencodable:
        print(f"error: {len(failures)} translation(s) cannot be encoded as "
              f"{encoding}. Examples:", file=sys.stderr)
        for entry, bad in failures[:5]:
            print(f"  [{entry['index']}] {entry['source_file']}: {bad!r} "
                  f"in {entry['translated'][:40]!r}", file=sys.stderr)
        print("\nEither pick a codepage that covers your language "
              "(-e cp950 / -e cp936), or pass --skip-unencodable to import "
              "the rest and leave these as the original text.", file=sys.stderr)
        return 1
    unencodable = {id(entry) for entry, _ in failures}

    project = WolfProject(str(args.data), encoding=info.get("encoding", "cp932"))
    for err in project.errors:
        print(f"warning: could not load {err}", file=sys.stderr)

    slots = list(project.slots())
    by_address = {(s.source_file, s.location): s for s in slots}

    applied = 0
    skipped_missing = 0
    skipped_stale = 0
    transcoded = 0
    left_as_is = 0
    for entry in entries:
        slot = by_address.get((entry["source_file"], entry["location"]))
        if slot is None:
            if entry["translated"]:
                skipped_missing += 1
            continue
        current = slot.raw.decode(project.encoding, errors="replace")
        if current != entry["original"]:
            if entry["translated"]:
                skipped_stale += 1
            continue

        if entry["translated"] and id(entry) not in unencodable:
            slot.write(entry["translated"].encode(encoding))
            applied += 1
            continue

        # 沒有譯文（或譯文編不出來）時，仍要把原文轉成目標編碼再寫回去。
        # 遊戲已改用中文字碼頁解讀，留著原本的 CP932 位元組就會是亂碼——
        # 連純符號的「……。」也不例外。
        if args.no_transcode:
            continue
        encoded = encode_for_game(entry["original"], encoding)
        if encoded is None:
            left_as_is += 1
            continue
        if encoded != slot.raw:
            slot.write(encoded)
            transcoded += 1

    out_dir = args.output or args.data
    if out_dir == args.data and not args.no_backup:
        backup = args.data.parent / f"{args.data.name}_backup"
        if backup.exists():
            print(f"warning: {backup} already exists; leaving it alone",
                  file=sys.stderr)
        else:
            shutil.copytree(args.data, backup)
            print(f"Backed up {args.data} -> {backup}")

    out_dir.mkdir(parents=True, exist_ok=True)
    written = project.save(str(out_dir))

    changed = []
    if out_dir != args.data:
        for rel in written:
            source = args.data / rel
            patched = out_dir / rel
            if source.is_file() and source.read_bytes() != patched.read_bytes():
                changed.append(rel)

    print(f"\n=== Import ===")
    print(f"Applied:  {applied} translation(s)")
    if transcoded:
        print(f"Transcoded: {transcoded} untranslated string(s) to {encoding} "
              f"(they would otherwise render as garbage)")
    if left_as_is:
        print(f"Mojibake: {left_as_is} untranslated string(s) contain characters "
              f"{encoding} has no room for and WILL render as garbage in game "
              f"(run `validate` to list them)")
    if skipped_missing:
        print(f"Skipped:  {skipped_missing} (address not found in the game data)")
    if skipped_stale:
        print(f"Skipped:  {skipped_stale} (source text no longer matches; "
              f"re-export after changing the game data)")
    if failures and args.skip_unencodable:
        print(f"Skipped:  {len(failures)} (not encodable as {encoding})")
    print(f"Wrote:    {len(written)} file(s) to {out_dir}/")

    if out_dir != args.data:
        if changed:
            print(f"\nOnly these {len(changed)} file(s) actually differ from the "
                  f"original; a patch needs to ship nothing else:")
            for rel in changed:
                print(f"  {rel}")
        else:
            print("\nNo file differs from the original - nothing was translated.")

    if args.no_verify:
        return 0
    print()
    return verify(args.data, out_dir, project.encoding)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def verify(original_dir: Path, patched_dir: Path, encoding: str = "cp932") -> int:
    """Structurally compare two Data/ trees, ignoring translated text."""
    errors: list[str] = []
    warnings: list[str] = []

    before = WolfProject(str(original_dir), encoding=encoding)
    after = WolfProject(str(patched_dir), encoding=encoding)

    if set(before.maps) != set(after.maps):
        errors.append(
            f"map set differs: only in original "
            f"{sorted(set(before.maps) - set(after.maps))}, only in patched "
            f"{sorted(set(after.maps) - set(before.maps))}")

    def compare_commands(label: str, cmds_a: list, cmds_b: list) -> None:
        if len(cmds_a) != len(cmds_b):
            errors.append(f"{label}: command count {len(cmds_a)} -> {len(cmds_b)}")
            return
        for i, (a, b) in enumerate(zip(cmds_a, cmds_b)):
            if a.cid != b.cid:
                errors.append(f"{label}/Cmd{i}: command ID {a.cid} -> {b.cid}")
                continue
            if a.indent != b.indent:
                errors.append(f"{label}/Cmd{i}: indent {a.indent} -> {b.indent}")
            if a.args != b.args:
                errors.append(f"{label}/Cmd{i} (cid {a.cid}): "
                              f"integer args changed")
            if len(a.string_args) != len(b.string_args):
                errors.append(f"{label}/Cmd{i} (cid {a.cid}): string arg count "
                              f"{len(a.string_args)} -> {len(b.string_args)}")
                continue
            critical = FLOW_CRITICAL_ARGS.get(a.cid)
            if critical is not None and a.string_args[critical] != b.string_args[critical]:
                errors.append(f"{label}/Cmd{i} (cid {a.cid}): a label or event "
                              f"name was translated; this breaks jumps/calls")
            if a.cid == 150 and a.picture_type != 2 and a.string_args != b.string_args:
                errors.append(f"{label}/Cmd{i}: Show Picture filename changed "
                              f"({a.string_args[0][:40]!r} -> "
                              f"{b.string_args[0][:40]!r}); the game will fail "
                              f"to load the image")
            if a.cid == 102 and len(a.string_args) != len(b.string_args):
                errors.append(f"{label}/Cmd{i}: choice count changed")

    files_checked = 0
    for rel in sorted(set(before.maps) & set(after.maps)):
        files_checked += 1
        map_a, map_b = before.maps[rel], after.maps[rel]
        if (map_a.width, map_a.height) != (map_b.width, map_b.height):
            errors.append(f"{rel}: map size changed")
        if map_a.tiles != map_b.tiles:
            errors.append(f"{rel}: tile data changed")
        if len(map_a.events) != len(map_b.events):
            errors.append(f"{rel}: event count "
                          f"{len(map_a.events)} -> {len(map_b.events)}")
            continue
        for ei, (ev_a, ev_b) in enumerate(zip(map_a.events, map_b.events)):
            if len(ev_a.pages) != len(ev_b.pages):
                errors.append(f"{rel}/Ev{ei}: page count changed")
                continue
            for pi, (pg_a, pg_b) in enumerate(zip(ev_a.pages, ev_b.pages)):
                compare_commands(f"{rel}/Ev{ei}/Pg{pi}", pg_a.commands, pg_b.commands)

    if (before.common_events is None) != (after.common_events is None):
        errors.append("CommonEvent.dat present in only one of the two trees")
    elif before.common_events is not None:
        files_checked += 1
        ce_a, ce_b = before.common_events, after.common_events
        if len(ce_a.events) != len(ce_b.events):
            errors.append(f"CommonEvent.dat: event count "
                          f"{len(ce_a.events)} -> {len(ce_b.events)}")
        else:
            for ei, (ev_a, ev_b) in enumerate(zip(ce_a.events, ce_b.events)):
                if ev_a.name != ev_b.name:
                    errors.append(f"CommonEvent.dat/CEv{ei}: common event name "
                                  f"was changed; CommonEventByName calls will "
                                  f"stop resolving")
                compare_commands(f"CommonEvent.dat/CEv{ei}",
                                 ev_a.commands, ev_b.commands)

    for name in sorted(set(before.databases) & set(after.databases)):
        files_checked += 1
        db_a, db_b = before.databases[name], after.databases[name]
        if len(db_a.types) != len(db_b.types):
            errors.append(f"{name}: type count changed")
            continue
        for ti, (type_a, type_b) in enumerate(zip(db_a.types, db_b.types)):
            if len(type_a.dat_data) != len(type_b.dat_data):
                errors.append(f"{name}/Type{ti}: row count changed")
                continue
            for di, (row_a, row_b) in enumerate(zip(type_a.dat_data, type_b.dat_data)):
                if row_a.int_values != row_b.int_values:
                    errors.append(f"{name}/Type{ti}/Data{di}: numeric values "
                                  f"changed")
                if len(row_a.string_values) != len(row_b.string_values):
                    errors.append(f"{name}/Type{ti}/Data{di}: string column "
                                  f"count changed")

    if before.game_dat is not None and after.game_dat is not None:
        files_checked += 1
        if before.game_dat.font != after.game_dat.font:
            warnings.append("Game.dat: the main font name was changed")
        if before.game_dat.file_version != after.game_dat.file_version:
            errors.append("Game.dat: file version changed")

    print("=== Structural Verification ===")
    print(f"Files checked: {files_checked}")
    print(f"Errors:        {len(errors)}")
    print(f"Warnings:      {len(warnings)}")
    for message in errors[:40]:
        print(f"  ERROR   {message}")
    if len(errors) > 40:
        print(f"  ... and {len(errors) - 40} more errors")
    for message in warnings[:20]:
        print(f"  WARNING {message}")

    if not errors:
        print("\nNo structural issues found. The patch is safe to run.")
    return 1 if errors else 0


def cmd_verify(args) -> int:
    return verify(args.original, args.patched, args.encoding or "cp932")


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Import translated JSON into a Wolf RPG game and verify it.")
    sub = ap.add_subparsers(dest="command", required=True)

    encoding_help = ("codepage to write translations in "
                     "(default: info.encoding from the JSON, else cp932). "
                     "Use cp950 for Traditional Chinese, cp936 for Simplified.")

    p = sub.add_parser("validate", help="report progress and check for problems")
    p.add_argument("-e", "--encoding", default=None, help=encoding_help)
    p.add_argument("translation", type=Path, help="JSON file or directory")
    p.add_argument("-u", "--output-untranslated", type=Path, default=None,
                   help="write untranslated entries to this JSON file")
    p.add_argument("-c", "--context", nargs="+", default=["dialog", "choice"],
                   help="contexts to include with -u ('all' for everything)")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("import", help="apply translations to the game data")
    p.add_argument("-e", "--encoding", default=None, help=encoding_help)
    p.add_argument("data", type=Path, help="extracted Data/ directory")
    p.add_argument("translation", type=Path, help="JSON file or directory")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="write the patched tree here (default: overwrite input)")
    p.add_argument("--no-backup", action="store_true",
                   help="do not back up before overwriting in place")
    p.add_argument("--no-verify", action="store_true",
                   help="skip the structural check after importing")
    p.add_argument("--skip-unencodable", action="store_true",
                   help="keep the original text for translations that do not "
                        "fit the target codepage instead of aborting")
    p.add_argument("--no-transcode", action="store_true",
                   help="leave untranslated strings as their original bytes. "
                        "Only useful when the game still reads the source "
                        "codepage; otherwise they render as garbage.")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("verify", help="structurally compare two Data/ trees")
    p.add_argument("-e", "--encoding", default=None, help=encoding_help)
    p.add_argument("original", type=Path)
    p.add_argument("patched", type=Path)
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
