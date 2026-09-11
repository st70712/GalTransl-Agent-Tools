#!/usr/bin/env python3
"""
RPG Maker MV/MZ Text Importer
Imports translated text from JSON back into RPG Maker game data

Supports:
- Map events (Map*.json) - Dialogues and event commands
- Common events (CommonEvents.json)
- System data (System.json) - Terms, menu texts
- Actors, Items, Skills, Enemies, etc.

Author: GalTransl-RPGmaker Project
"""

import json
import argparse
import shutil
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


def load_translations(json_file: Path) -> Tuple[Dict, List[Dict]]:
    """
    Load translation data from JSON file.
    
    Returns:
        (info, translations_list)
    """
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    info = data.get("info", {})
    strings = data.get("strings", [])
    
    return info, strings


def load_all_translations(input_path: Path) -> Dict[str, List[Dict]]:
    """
    Load translations from a file or directory.
    Returns dict mapping source_file -> list of translation entries
    """
    translations_by_file = defaultdict(list)
    
    if input_path.is_file():
        # Single file
        info, strings = load_translations(input_path)
        for entry in strings:
            source = entry.get("source_file", "")
            translations_by_file[source].append(entry)
    else:
        # Directory with multiple files
        for json_file in input_path.glob("*_text.json"):
            info, strings = load_translations(json_file)
            for entry in strings:
                source = entry.get("source_file", "")
                translations_by_file[source].append(entry)
        
        # Also check for script.json
        script_file = input_path / "script.json"
        if script_file.exists():
            info, strings = load_translations(script_file)
            for entry in strings:
                source = entry.get("source_file", "")
                translations_by_file[source].append(entry)
    
    return translations_by_file


def build_translation_index(entries: List[Dict]) -> Dict[str, str]:
    """
    Build an index mapping location -> translated text
    """
    index = {}
    for entry in entries:
        location = entry.get("location", "")
        translated = entry.get("translated", "")

        # Only use if there's a translation
        if translated:
            index[location] = translated

    return index


# Regex matching Japanese kana/kanji (source language markers)
JP_REGEX = r'[぀-ゟ゠-ヿ一-鿿]'


def _has_jp(text) -> bool:
    """True if the value is a string containing Japanese characters."""
    return isinstance(text, str) and re.search(JP_REGEX, text) is not None


def _try_parse_json_container(s):
    """
    If s is a JSON-encoded array/object string, return the parsed structure,
    otherwise None. Mirror of the exporter so traversal stays in sync.
    """
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t or t[0] not in '[{':
        return None
    try:
        parsed = json.loads(t)
    except (ValueError, TypeError):
        return None
    if isinstance(parsed, (list, dict)):
        return parsed
    return None


def rebuild_json_leaves(node, get_next):
    """
    Depth-first rebuild of a nested structure, substituting each translatable
    (Japanese-containing) string leaf via get_next(original) -> replacement|None.
    String leaves that are themselves JSON containers are recursed into and
    re-serialized. Traversal order MUST match export's collect_json_leaves.
    """
    if isinstance(node, str):
        sub = _try_parse_json_container(node)
        if sub is not None:
            rebuilt = rebuild_json_leaves(sub, get_next)
            return json.dumps(rebuilt, ensure_ascii=False, separators=(',', ':'))
        elif _has_jp(node):
            rep = get_next(node)
            return rep if rep is not None else node
        else:
            return node
    elif isinstance(node, list):
        return [rebuild_json_leaves(x, get_next) for x in node]
    elif isinstance(node, dict):
        return {k: rebuild_json_leaves(v, get_next) for k, v in node.items()}
    else:
        return node


def sync_plugin_arg_echoes(commands: List[Dict], start_idx: int,
                           value_map: Dict[str, str]) -> None:
    """
    Update the code 657 argument-echo lines that follow a 357 command so their
    displayed values stay consistent with the translated 357 args. Matching is
    done by value ('key = value'), which sidesteps localized arg-key names.
    """
    j = start_idx + 1
    while j < len(commands) and commands[j].get("code") == 657:
        params = commands[j].get("parameters", [])
        if params and isinstance(params[0], str) and '=' in params[0]:
            key_part, _sep, val_part = params[0].partition('=')
            stripped = val_part.strip()
            for old_v, new_v in value_map.items():
                if stripped == old_v.strip():
                    commands[j]["parameters"][0] = f"{key_part}= {new_v}"
                    break
        j += 1


def apply_event_commands_translation(commands: List[Dict], 
                                     trans_index: Dict[str, str],
                                     location_prefix: str) -> int:
    """
    Apply translations to event commands.
    Returns number of translations applied.
    
    Uses an offset to track inserted/removed 401 commands so that
    location lookups always use the original command index.
    """
    applied = 0
    i = 0
    offset = 0  # tracks cumulative shift from inserted/removed 401 commands
    
    while i < len(commands):
        cmd = commands[i]
        code = cmd.get("code", 0)
        params = cmd.get("parameters", [])
        original_i = i - offset  # the index in the original (unmodified) command list
        
        # Show Text (code 101) - collect and translate following 401 commands
        if code == 101:
            # Check if there's a translation for this dialog block
            location = f"{location_prefix}/Cmd{original_i}"
            
            if location in trans_index:
                translated = trans_index[location]
                translated_lines = translated.split("\n")
                
                # Count original 401 commands
                j = i + 1
                orig_401_count = 0
                while j + orig_401_count < len(commands) and commands[j + orig_401_count].get("code") == 401:
                    orig_401_count += 1
                
                # Update existing 401 commands
                line_idx = 0
                k = j
                while k < j + orig_401_count and line_idx < len(translated_lines):
                    commands[k]["parameters"][0] = translated_lines[line_idx]
                    k += 1
                    line_idx += 1
                
                # If translation has fewer lines, blank out remaining 401 commands
                while k < j + orig_401_count:
                    commands[k]["parameters"][0] = ""
                    k += 1
                
                # If translation has more lines than original, insert new 401 commands
                inserted = 0
                while line_idx < len(translated_lines):
                    new_cmd = {
                        "code": 401,
                        "indent": cmd.get("indent", 0),
                        "parameters": [translated_lines[line_idx]]
                    }
                    commands.insert(k, new_cmd)
                    k += 1
                    line_idx += 1
                    inserted += 1
                
                offset += inserted
                applied += 1
                i = k
                continue
        
        # Show Choices (code 102)
        elif code == 102:
            if params and isinstance(params[0], list):
                modified = False
                for choice_idx in range(len(params[0])):
                    location = f"{location_prefix}/Cmd{original_i}/Choice{choice_idx}"
                    if location in trans_index:
                        translated_choice = trans_index[location]
                        original = params[0][choice_idx]
                        
                        # Check if original has conditional suffix like " if(s[xxx])"
                        condition_match = re.search(r'(\s*if\(s\[\d+\]\))$', original)
                        
                        if condition_match:
                            condition = condition_match.group(1)
                            # Check if translation already contains the condition
                            if condition in translated_choice:
                                # Translation already has condition, use as-is
                                params[0][choice_idx] = translated_choice
                            else:
                                # Translation doesn't have condition, append it
                                params[0][choice_idx] = translated_choice + condition
                        else:
                            # No condition in original, use translation as-is
                            params[0][choice_idx] = translated_choice
                        
                        modified = True
                
                if modified:
                    applied += 1
        
        # Scroll Text content (code 405)
        elif code == 405:
            location = f"{location_prefix}/Cmd{original_i}"
            if location in trans_index and params:
                params[0] = trans_index[location]
                applied += 1
        
        # Show Picture (code 231) - picture name
        elif code == 231:
            location = f"{location_prefix}/Cmd{original_i}"
            if location in trans_index and len(params) >= 2:
                params[1] = trans_index[location]
                applied += 1
        
        # Plugin Command (code 356)
        elif code == 356:
            location = f"{location_prefix}/Cmd{original_i}"
            if location in trans_index and params:
                params[0] = trans_index[location]
                applied += 1

        # Plugin Command MZ (code 357) - args in params[3] dict; sync 657 echoes
        elif code == 357:
            if len(params) >= 4 and isinstance(params[3], dict):
                arg_dict = params[3]
                value_map: Dict[str, str] = {}  # original arg value -> new value
                cmd_applied = False
                for arg_key in list(arg_dict.keys()):
                    arg_val = arg_dict[arg_key]
                    if not isinstance(arg_val, str):
                        continue
                    nested = _try_parse_json_container(arg_val)
                    if nested is not None:
                        prefix = f"{location_prefix}/Cmd{original_i}/PArg:{arg_key}/N"
                        state = {"n": 0, "changed": False}

                        def get_next(_orig, _prefix=prefix, _state=state):
                            loc = f"{_prefix}{_state['n']}"
                            _state["n"] += 1
                            if loc in trans_index:
                                _state["changed"] = True
                                return trans_index[loc]
                            return None

                        rebuilt = rebuild_json_leaves(nested, get_next)
                        if state["changed"]:
                            new_val = json.dumps(rebuilt, ensure_ascii=False,
                                                 separators=(',', ':'))
                            if new_val != arg_val:
                                value_map[arg_val] = new_val
                                arg_dict[arg_key] = new_val
                                cmd_applied = True
                    else:
                        loc = f"{location_prefix}/Cmd{original_i}/PArg:{arg_key}"
                        if loc in trans_index:
                            new_val = trans_index[loc]
                            if new_val != arg_val:
                                value_map[arg_val] = new_val
                            arg_dict[arg_key] = new_val
                            cmd_applied = True
                if value_map:
                    sync_plugin_arg_echoes(commands, i, value_map)
                if cmd_applied:
                    applied += 1

        i += 1
    
    return applied


def import_map_data(map_file: Path, trans_index: Dict[str, str], 
                    output_file: Path) -> int:
    """
    Import translations into a map file.
    Returns number of translations applied.
    """
    with open(map_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    applied = 0
    
    # Translate displayName
    if "displayName" in trans_index:
        data["displayName"] = trans_index["displayName"]
        applied += 1
    
    # Translate events
    events = data.get("events", [])
    for event in events:
        if event is None:
            continue
        
        event_id = event.get("id", 0)
        
        # Translate event name
        name_location = f"Event{event_id}/name"
        if name_location in trans_index:
            event["name"] = trans_index[name_location]
            applied += 1
        
        # Translate event pages
        pages = event.get("pages", [])
        for page_idx, page in enumerate(pages):
            commands = page.get("list", [])
            location_prefix = f"Event{event_id}/Page{page_idx}"
            
            applied += apply_event_commands_translation(commands, trans_index, location_prefix)
    
    # Save output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    
    return applied


def import_common_events(ce_file: Path, trans_index: Dict[str, str],
                        output_file: Path) -> int:
    """
    Import translations into CommonEvents.json.
    Returns number of translations applied.
    """
    with open(ce_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    applied = 0
    
    for event in data:
        if event is None:
            continue
        
        event_id = event.get("id", 0)
        
        # Translate event name
        name_location = f"CE{event_id}/name"
        if name_location in trans_index:
            event["name"] = trans_index[name_location]
            applied += 1
        
        # Translate commands
        commands = event.get("list", [])
        location_prefix = f"CE{event_id}"
        
        applied += apply_event_commands_translation(commands, trans_index, location_prefix)
    
    # Save output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    
    return applied


def import_system_data(system_file: Path, trans_index: Dict[str, str],
                      output_file: Path) -> int:
    """
    Import translations into System.json.
    Returns number of translations applied.
    """
    with open(system_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    applied = 0
    
    # Game title
    if "gameTitle" in trans_index:
        data["gameTitle"] = trans_index["gameTitle"]
        applied += 1
    
    # Currency unit
    if "currencyUnit" in trans_index:
        data["currencyUnit"] = trans_index["currencyUnit"]
        applied += 1
    
    # Type arrays
    type_arrays = ["armorTypes", "equipTypes", "skillTypes", "weaponTypes", "elements"]
    for type_name in type_arrays:
        if type_name in data:
            for idx in range(len(data[type_name])):
                location = f"{type_name}/{idx}"
                if location in trans_index:
                    data[type_name][idx] = trans_index[location]
                    applied += 1
    
    # Switches and Variables
    for var_type in ["switches", "variables"]:
        if var_type in data:
            for idx in range(len(data[var_type])):
                location = f"{var_type}/{idx}"
                if location in trans_index:
                    data[var_type][idx] = trans_index[location]
                    applied += 1
    
    # Terms
    if "terms" in data:
        terms = data["terms"]
        
        if "basic" in terms:
            for idx in range(len(terms["basic"])):
                location = f"terms/basic/{idx}"
                if location in trans_index:
                    terms["basic"][idx] = trans_index[location]
                    applied += 1
        
        if "commands" in terms:
            for idx in range(len(terms["commands"])):
                location = f"terms/commands/{idx}"
                if location in trans_index:
                    terms["commands"][idx] = trans_index[location]
                    applied += 1
        
        if "params" in terms:
            for idx in range(len(terms["params"])):
                location = f"terms/params/{idx}"
                if location in trans_index:
                    terms["params"][idx] = trans_index[location]
                    applied += 1
        
        if "messages" in terms:
            for key in terms["messages"]:
                location = f"terms/messages/{key}"
                if location in trans_index:
                    terms["messages"][key] = trans_index[location]
                    applied += 1
    
    # Save output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    
    return applied


def import_database_entries(db_file: Path, trans_index: Dict[str, str],
                           output_file: Path, fields: List[str]) -> int:
    """
    Import translations into database files.
    Returns number of translations applied.
    """
    with open(db_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    applied = 0
    
    for item in data:
        if item is None:
            continue
        
        item_id = item.get("id", 0)
        
        for field_name in fields:
            location = f"ID{item_id}/{field_name}"
            if location in trans_index:
                item[field_name] = trans_index[location]
                applied += 1
    
    # Save output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    
    return applied


def export_untranslated(json_path: Path, output_path: Path,
                        contexts: Optional[List[str]] = None) -> int:
    """
    Export untranslated strings to a new JSON file for manual translation.
    The output file preserves the same structure as the input so it can be
    used directly with the import command after filling in the translations.

    Args:
        json_path:   Path to the source translation JSON file or directory.
        output_path: Destination JSON file path.
        contexts:    If given, only export entries whose ``context`` field is
                     in this list.  Pass ``None`` to export all contexts.

    Returns the number of untranslated strings exported.
    """
    # Normalise to a set for O(1) lookup; None means "all contexts"
    ctx_filter: Optional[set] = set(contexts) if contexts is not None else None

    # Load original info block (only available when input is a single file)
    info: Dict = {}
    if json_path.is_file():
        with open(json_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        info = dict(raw.get("info", {}))

    translations = load_all_translations(json_path)

    untranslated: List[Dict] = []
    for entries in translations.values():
        for entry in entries:
            if entry.get("translated"):
                continue
            if ctx_filter is not None and entry.get("context") not in ctx_filter:
                continue
            untranslated.append(entry)

    # Sort by original index so the file is easy to review in order
    untranslated.sort(key=lambda e: e.get("index", 0))

    ctx_desc = ("、".join(sorted(ctx_filter)) if ctx_filter is not None
                else "全部")
    info["string_count"] = len(untranslated)
    info["context_filter"] = list(sorted(ctx_filter)) if ctx_filter is not None else "all"
    info["note"] = (f"未翻譯文本 (context 篩選: {ctx_desc}) — "
                    "請填寫每個條目的 translated 欄位，完成後可直接用 import 指令導入")

    output_data = {"info": info, "strings": untranslated}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    return len(untranslated)


def validate_translations(json_path: Path) -> Dict:
    """
    Validate translation file and show progress.
    """
    translations = load_all_translations(json_path)
    
    total = 0
    translated = 0
    by_context = defaultdict(lambda: {"total": 0, "translated": 0})
    by_file = defaultdict(lambda: {"total": 0, "translated": 0})
    
    for source_file, entries in translations.items():
        for entry in entries:
            total += 1
            context = entry.get("context", "other")
            
            by_file[source_file]["total"] += 1
            by_context[context]["total"] += 1
            
            if entry.get("translated"):
                translated += 1
                by_file[source_file]["translated"] += 1
                by_context[context]["translated"] += 1
    
    return {
        "total": total,
        "translated": translated,
        "percentage": (translated / total * 100) if total > 0 else 0,
        "by_context": dict(by_context),
        "by_file": dict(by_file)
    }


# ---------- Structural verification ----------

# Command codes whose text content is allowed to differ between original and translated.
# These are text-carrying commands that the import process intentionally modifies.
TEXT_CONTENT_CODES = {401, 405}

# Command codes that carry translatable text in specific parameter slots.
TRANSLATABLE_CMD_CODES = {
    101,  # Show Text header (dialogue handled via 401)
    102,  # Show Choices (choice text in params[0] list)
    231,  # Show Picture (picture name in params[1])
    356,  # Plugin Command (params[0])
}

# All command codes that should never appear/disappear between original and translated.
# 401 commands may be inserted/removed, so they are excluded from structural comparison.
STRUCTURAL_SKIP_CODES = {401}


def _extract_structural_cmds(commands: List[Dict]) -> List[tuple]:
    """Extract non-401 commands as (original_index, code, parameters) tuples."""
    return [
        (i, cmd.get("code", 0), cmd.get("parameters", []))
        for i, cmd in enumerate(commands)
        if cmd.get("code", 0) not in STRUCTURAL_SKIP_CODES
    ]


def _verify_commands(orig_cmds: List[Dict], trans_cmds: List[Dict],
                     label: str) -> List[Dict]:
    """
    Compare two command lists structurally.
    Returns a list of issue dicts.
    """
    issues: List[Dict] = []

    orig_struct = _extract_structural_cmds(orig_cmds)
    trans_struct = _extract_structural_cmds(trans_cmds)

    if len(orig_struct) != len(trans_struct):
        issues.append({
            "level": "error",
            "location": label,
            "message": (f"結構性指令數量不一致: 原始={len(orig_struct)}, "
                        f"翻譯後={len(trans_struct)}"),
        })
        return issues  # further comparison unreliable

    for k, ((oi, oc, op), (ti, tc, tp)) in enumerate(zip(orig_struct, trans_struct)):
        if oc != tc:
            issues.append({
                "level": "error",
                "location": f"{label}/struct#{k}",
                "message": (f"指令代碼不一致: 原始[{oi}] code={oc} vs "
                            f"翻譯後[{ti}] code={tc}"),
            })
            break  # further comparison after mismatch is meaningless

        # --- per-code parameter checks ---

        # Show Picture (231): picture name must be a valid filename-like string
        if oc == 231 and len(op) >= 2 and len(tp) >= 2:
            orig_name = op[1]
            trans_name = tp[1]
            # Picture ID and other positional params should be identical
            if op[0] != tp[0]:
                issues.append({
                    "level": "error",
                    "location": f"{label}/orig[{oi}]",
                    "message": (f"Show Picture ID 不一致: "
                                f"原始={op[0]} vs 翻譯後={tp[0]}"),
                })
            for pi in range(2, min(len(op), len(tp))):
                if op[pi] != tp[pi]:
                    issues.append({
                        "level": "error",
                        "location": f"{label}/orig[{oi}]",
                        "message": (f"Show Picture 參數[{pi}] 不一致: "
                                    f"原始={op[pi]} vs 翻譯後={tp[pi]}"),
                    })
                    break
            # Detect dialogue text leaked into picture name
            if isinstance(trans_name, str) and isinstance(orig_name, str):
                if ('「' in trans_name or '」' in trans_name) and '「' not in orig_name:
                    issues.append({
                        "level": "error",
                        "location": f"{label}/orig[{oi}]",
                        "message": (f"Show Picture 圖片名稱被對話文字污染: "
                                    f"\"{trans_name}\" (原始: \"{orig_name}\")"),
                    })

        # Show Choices (102): number of choices should match
        if oc == 102 and len(op) >= 1 and len(tp) >= 1:
            if isinstance(op[0], list) and isinstance(tp[0], list):
                if len(op[0]) != len(tp[0]):
                    issues.append({
                        "level": "error",
                        "location": f"{label}/orig[{oi}]",
                        "message": (f"選項數量不一致: "
                                    f"原始={len(op[0])} vs 翻譯後={len(tp[0])}"),
                    })
            # Non-text params (like default, cancel type) should match
            for pi in range(1, min(len(op), len(tp))):
                if op[pi] != tp[pi]:
                    issues.append({
                        "level": "warning",
                        "location": f"{label}/orig[{oi}]",
                        "message": (f"Show Choices 參數[{pi}] 不一致: "
                                    f"原始={op[pi]} vs 翻譯後={tp[pi]}"),
                    })

        # Plugin Command (356): warn if text changed to something with CJK dialogue markers
        if oc == 356 and len(op) >= 1 and len(tp) >= 1:
            if isinstance(tp[0], str) and isinstance(op[0], str):
                if ('「' in tp[0] or '」' in tp[0]) and '「' not in op[0]:
                    issues.append({
                        "level": "warning",
                        "location": f"{label}/orig[{oi}]",
                        "message": (f"Plugin Command 可能被對話文字污染: "
                                    f"\"{tp[0][:40]}...\""),
                    })

        # Generic check: command indent should match
        if oi < len(orig_cmds) and ti < len(trans_cmds):
            o_indent = orig_cmds[oi].get("indent", 0)
            t_indent = trans_cmds[ti].get("indent", 0)
            if o_indent != t_indent:
                issues.append({
                    "level": "warning",
                    "location": f"{label}/orig[{oi}]",
                    "message": (f"指令縮排不一致 (code={oc}): "
                                f"原始={o_indent} vs 翻譯後={t_indent}"),
                })

    # Check that 401 count difference is reasonable (only additions, no removals)
    orig_401 = sum(1 for c in orig_cmds if c.get("code") == 401)
    trans_401 = sum(1 for c in trans_cmds if c.get("code") == 401)
    if trans_401 < orig_401:
        issues.append({
            "level": "warning",
            "location": label,
            "message": (f"翻譯後的 401 指令數量少於原始: "
                        f"原始={orig_401} vs 翻譯後={trans_401}"),
        })

    return issues


def verify_event_commands_file(orig_file: Path, trans_file: Path,
                               file_type: str) -> List[Dict]:
    """
    Verify structural integrity between original and translated event files.
    file_type: 'map', 'common_events'
    """
    with open(orig_file, 'r', encoding='utf-8') as f:
        orig_data = json.load(f)
    with open(trans_file, 'r', encoding='utf-8') as f:
        trans_data = json.load(f)

    issues: List[Dict] = []

    if file_type == "common_events":
        if len(orig_data) != len(trans_data):
            issues.append({
                "level": "error",
                "location": str(trans_file.name),
                "message": (f"公共事件數量不一致: "
                            f"原始={len(orig_data)} vs 翻譯後={len(trans_data)}"),
            })
            return issues

        for idx in range(len(orig_data)):
            if orig_data[idx] is None:
                if trans_data[idx] is not None:
                    issues.append({
                        "level": "error",
                        "location": f"CE{idx}",
                        "message": "原始為 null 但翻譯後不為 null",
                    })
                continue
            if trans_data[idx] is None:
                issues.append({
                    "level": "error",
                    "location": f"CE{idx}",
                    "message": "原始存在但翻譯後為 null",
                })
                continue

            eid = orig_data[idx].get("id", idx)
            orig_cmds = orig_data[idx].get("list", [])
            trans_cmds = trans_data[idx].get("list", [])
            issues.extend(_verify_commands(orig_cmds, trans_cmds, f"CE{eid}"))

    elif file_type == "map":
        # Verify events
        orig_events = orig_data.get("events", [])
        trans_events = trans_data.get("events", [])
        if len(orig_events) != len(trans_events):
            issues.append({
                "level": "error",
                "location": str(trans_file.name),
                "message": (f"地圖事件數量不一致: "
                            f"原始={len(orig_events)} vs 翻譯後={len(trans_events)}"),
            })
            return issues

        for idx in range(len(orig_events)):
            if orig_events[idx] is None:
                continue
            if trans_events[idx] is None:
                issues.append({
                    "level": "error",
                    "location": f"Event{idx}",
                    "message": "原始存在但翻譯後為 null",
                })
                continue

            eid = orig_events[idx].get("id", idx)
            orig_pages = orig_events[idx].get("pages", [])
            trans_pages = trans_events[idx].get("pages", [])
            if len(orig_pages) != len(trans_pages):
                issues.append({
                    "level": "error",
                    "location": f"Event{eid}",
                    "message": (f"頁面數量不一致: "
                                f"原始={len(orig_pages)} vs 翻譯後={len(trans_pages)}"),
                })
                continue

            for pi in range(len(orig_pages)):
                orig_cmds = orig_pages[pi].get("list", [])
                trans_cmds = trans_pages[pi].get("list", [])
                issues.extend(
                    _verify_commands(orig_cmds, trans_cmds,
                                     f"Event{eid}/Page{pi}")
                )

    return issues


def verify_database_file(orig_file: Path, trans_file: Path,
                         fields: List[str]) -> List[Dict]:
    """
    Verify structural integrity of database files (Actors, Items, etc.).
    Ensures non-translatable fields are not modified.
    """
    with open(orig_file, 'r', encoding='utf-8') as f:
        orig_data = json.load(f)
    with open(trans_file, 'r', encoding='utf-8') as f:
        trans_data = json.load(f)

    issues: List[Dict] = []

    if len(orig_data) != len(trans_data):
        issues.append({
            "level": "error",
            "location": str(trans_file.name),
            "message": (f"資料筆數不一致: "
                        f"原始={len(orig_data)} vs 翻譯後={len(trans_data)}"),
        })
        return issues

    translatable_fields = set(fields)

    for idx in range(len(orig_data)):
        if orig_data[idx] is None:
            continue
        if trans_data[idx] is None:
            issues.append({
                "level": "error",
                "location": f"ID{idx}",
                "message": "原始存在但翻譯後為 null",
            })
            continue

        item_id = orig_data[idx].get("id", idx)
        # Check that non-translatable fields are unchanged
        for key in orig_data[idx]:
            if key in translatable_fields:
                continue
            orig_val = orig_data[idx].get(key)
            trans_val = trans_data[idx].get(key)
            if orig_val != trans_val:
                issues.append({
                    "level": "error",
                    "location": f"ID{item_id}/{key}",
                    "message": (f"不可翻譯欄位被修改: "
                                f"原始={json.dumps(orig_val, ensure_ascii=False)[:60]} vs "
                                f"翻譯後={json.dumps(trans_val, ensure_ascii=False)[:60]}"),
                })

    return issues


def verify_system_file(orig_file: Path, trans_file: Path) -> List[Dict]:
    """
    Verify structural integrity of System.json.
    Ensures non-translatable fields are not modified.
    """
    with open(orig_file, 'r', encoding='utf-8') as f:
        orig_data = json.load(f)
    with open(trans_file, 'r', encoding='utf-8') as f:
        trans_data = json.load(f)

    issues: List[Dict] = []

    # Keys that may be translated
    translatable_keys = {
        "gameTitle", "currencyUnit",
        "armorTypes", "equipTypes", "skillTypes", "weaponTypes", "elements",
        "switches", "variables", "terms",
    }

    for key in orig_data:
        if key in translatable_keys:
            continue
        if orig_data.get(key) != trans_data.get(key):
            issues.append({
                "level": "error",
                "location": f"System/{key}",
                "message": "不可翻譯欄位被修改",
            })

    # Verify terms structure
    if "terms" in orig_data and "terms" in trans_data:
        orig_terms = orig_data["terms"]
        trans_terms = trans_data["terms"]
        for section in ["basic", "commands", "params"]:
            if section in orig_terms and section in trans_terms:
                if len(orig_terms[section]) != len(trans_terms[section]):
                    issues.append({
                        "level": "error",
                        "location": f"System/terms/{section}",
                        "message": (f"陣列長度不一致: "
                                    f"原始={len(orig_terms[section])} vs "
                                    f"翻譯後={len(trans_terms[section])}"),
                    })
        if "messages" in orig_terms and "messages" in trans_terms:
            orig_keys = set(orig_terms["messages"].keys())
            trans_keys = set(trans_terms["messages"].keys())
            if orig_keys != trans_keys:
                missing = orig_keys - trans_keys
                extra = trans_keys - orig_keys
                if missing:
                    issues.append({
                        "level": "error",
                        "location": "System/terms/messages",
                        "message": f"缺少鍵值: {missing}",
                    })
                if extra:
                    issues.append({
                        "level": "warning",
                        "location": "System/terms/messages",
                        "message": f"多出鍵值: {extra}",
                    })

    return issues


def verify_structure(game_dir: Path, output_dir: Path) -> Dict:
    """
    Perform full structural verification between original and translated game data.
    
    Args:
        game_dir: Original game directory
        output_dir: Translated output directory
    
    Returns:
        Dict with 'issues' list, 'errors' count, 'warnings' count, 'files_checked' count
    """
    # Locate data directories
    orig_data_dir = game_dir / "www" / "data"
    if not orig_data_dir.exists():
        orig_data_dir = game_dir / "data"

    trans_data_dir = output_dir / "www" / "data"
    if not trans_data_dir.exists():
        trans_data_dir = output_dir / "data"

    if not orig_data_dir.exists():
        return {"issues": [{"level": "error", "location": str(game_dir),
                            "message": "找不到原始 data 目錄"}],
                "errors": 1, "warnings": 0, "files_checked": 0}
    if not trans_data_dir.exists():
        return {"issues": [{"level": "error", "location": str(output_dir),
                            "message": "找不到翻譯後 data 目錄"}],
                "errors": 1, "warnings": 0, "files_checked": 0}

    all_issues: List[Dict] = []
    files_checked = 0

    # Database files and their translatable fields
    db_file_fields = {
        "Actors.json": ["name", "nickname", "profile"],
        "Classes.json": ["name"],
        "Skills.json": ["name", "description", "message1", "message2"],
        "Items.json": ["name", "description"],
        "Weapons.json": ["name", "description"],
        "Armors.json": ["name", "description"],
        "Enemies.json": ["name"],
        "States.json": ["name", "message1", "message2", "message3", "message4"],
    }

    # Check all translated files that exist
    for trans_file in sorted(trans_data_dir.glob("*.json")):
        fname = trans_file.name
        orig_file = orig_data_dir / fname
        if not orig_file.exists():
            all_issues.append({
                "level": "warning",
                "location": fname,
                "message": "翻譯後檔案在原始目錄中不存在",
            })
            continue

        files_checked += 1

        if fname == "CommonEvents.json":
            all_issues.extend(
                verify_event_commands_file(orig_file, trans_file, "common_events"))
        elif fname.startswith("Map") and fname.endswith(".json") and fname != "MapInfos.json":
            all_issues.extend(
                verify_event_commands_file(orig_file, trans_file, "map"))
        elif fname == "System.json":
            all_issues.extend(verify_system_file(orig_file, trans_file))
        elif fname in db_file_fields:
            all_issues.extend(
                verify_database_file(orig_file, trans_file, db_file_fields[fname]))

    errors = sum(1 for i in all_issues if i["level"] == "error")
    warnings = sum(1 for i in all_issues if i["level"] == "warning")

    return {
        "issues": all_issues,
        "errors": errors,
        "warnings": warnings,
        "files_checked": files_checked,
    }


def import_all(game_dir: Path, translation_path: Path, output_dir: Optional[Path] = None,
               backup: bool = True) -> Dict:
    """
    Import all translations into the game data.
    
    Args:
        game_dir: Original game directory
        translation_path: Path to translation JSON file or directory
        output_dir: Output directory (default: overwrites original with backup)
        backup: Create backup of original files
    
    Returns:
        Summary of applied translations
    """
    data_dir = game_dir / "www" / "data"
    
    if not data_dir.exists():
        data_dir = game_dir / "data"
        if not data_dir.exists():
            raise FileNotFoundError(f"Data directory not found in {game_dir}")
    
    # Determine output directory
    if output_dir is None:
        output_data_dir = data_dir
    else:
        output_data_dir = output_dir / "www" / "data"
        output_data_dir.mkdir(parents=True, exist_ok=True)
    
    # Load all translations
    translations = load_all_translations(translation_path)
    
    total_applied = 0
    results = {}
    
    # Create backup directory if needed
    if backup and output_dir is None:
        backup_dir = game_dir / "backup"
        backup_dir.mkdir(exist_ok=True)
    
    # Process each source file
    for source_file, entries in translations.items():
        if not source_file:
            continue
        
        original_file = data_dir / source_file
        if not original_file.exists():
            print(f"Warning: Source file not found: {source_file}")
            continue
        
        # Create backup
        if backup and output_dir is None:
            backup_file = backup_dir / source_file
            if not backup_file.exists():
                shutil.copy2(original_file, backup_file)
        
        # Build translation index for this file
        trans_index = build_translation_index(entries)
        
        if not trans_index:
            continue
        
        output_file = output_data_dir / source_file
        
        # Determine file type and process
        applied = 0
        
        if source_file == "System.json":
            applied = import_system_data(original_file, trans_index, output_file)
        elif source_file == "CommonEvents.json":
            applied = import_common_events(original_file, trans_index, output_file)
        elif source_file.startswith("Map") and source_file.endswith(".json"):
            applied = import_map_data(original_file, trans_index, output_file)
        elif source_file in ["Actors.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name", "nickname", "profile"])
        elif source_file in ["Classes.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name"])
        elif source_file in ["Skills.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name", "description", "message1", "message2"])
        elif source_file in ["Items.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name", "description"])
        elif source_file in ["Weapons.json", "Armors.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name", "description"])
        elif source_file in ["Enemies.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name"])
        elif source_file in ["States.json"]:
            applied = import_database_entries(original_file, trans_index, output_file,
                                             ["name", "message1", "message2", "message3", "message4"])
        
        if applied > 0:
            print(f"Processed: {source_file} ({applied} translations applied)")
            total_applied += applied
            results[source_file] = applied
    
    return {
        "total_applied": total_applied,
        "files_processed": len(results),
        "by_file": results
    }


def main():
    parser = argparse.ArgumentParser(
        description="RPG Maker MV/MZ Text Importer - Import translations back into game"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate translation progress")
    validate_parser.add_argument(
        "translation",
        type=Path,
        help="Path to translation JSON file or directory"
    )
    validate_parser.add_argument(
        "-u", "--output-untranslated",
        type=Path,
        default=None,
        metavar="OUTPUT_JSON",
        help="將未翻譯的條目輸出至指定 JSON 檔案，方便手動翻譯後再導入"
    )
    validate_parser.add_argument(
        "-c", "--context",
        nargs="+",
        default=["dialog", "choice"],
        metavar="CONTEXT",
        dest="contexts",
        help=("搭配 -u 使用：指定要輸出的 context 類型（可多個，空格分隔）。"
              "傳入 all 表示輸出所有類型。"
              "預設: dialog choice")
    )
    
    # Verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify structural integrity between original and translated game data"
    )
    verify_parser.add_argument(
        "game_dir",
        type=Path,
        help="Path to the original game directory"
    )
    verify_parser.add_argument(
        "output_dir",
        type=Path,
        help="Path to the translated game directory"
    )
    
    # Import command
    import_parser = subparsers.add_parser("import", help="Import translations into game")
    import_parser.add_argument(
        "game_dir",
        type=Path,
        help="Path to the game directory"
    )
    import_parser.add_argument(
        "translation",
        type=Path,
        help="Path to translation JSON file or directory"
    )
    import_parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output directory for translated game (default: overwrite original)"
    )
    import_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't create backup of original files"
    )
    import_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip structural verification after import"
    )
    
    args = parser.parse_args()
    
    if args.command == "validate":
        if not args.translation.exists():
            print(f"Error: Translation file/directory not found: {args.translation}")
            return 1
        
        result = validate_translations(args.translation)
        
        print("\n=== Translation Validation ===")
        print(f"Total strings: {result['total']}")
        print(f"Translated: {result['translated']}")
        print(f"Untranslated: {result['total'] - result['translated']}")
        print(f"Progress: {result['percentage']:.1f}%")
        
        print("\nBy context:")
        for ctx, counts in sorted(result['by_context'].items(), key=lambda x: -x[1]['total']):
            pct = (counts['translated'] / counts['total'] * 100) if counts['total'] > 0 else 0
            print(f"  {ctx}: {counts['translated']}/{counts['total']} ({pct:.1f}%)")
        
        print("\nBy file:")
        for filename, counts in sorted(result['by_file'].items(), key=lambda x: -x[1]['total']):
            pct = (counts['translated'] / counts['total'] * 100) if counts['total'] > 0 else 0
            print(f"  {filename}: {counts['translated']}/{counts['total']} ({pct:.1f}%)")
        
        if args.output_untranslated is not None:
            # -c all → pass None so every context is included
            ctx_list: Optional[List[str]] = (
                None if args.contexts == ["all"] else args.contexts
            )
            ctx_label = "全部" if ctx_list is None else "、".join(ctx_list)
            count = export_untranslated(args.translation, args.output_untranslated,
                                        contexts=ctx_list)
            if count > 0:
                print(f"\n已將 {count} 條未翻譯文本輸出至: {args.output_untranslated}")
                print(f"  (context 篩選: {ctx_label})")
                print("請填寫各條目的 translated 欄位後，使用 import 指令導入。")
            else:
                print(f"\n✓ 指定 context ({ctx_label}) 的文本均已翻譯，無需輸出未翻譯檔案。")
        
        return 0
    
    elif args.command == "verify":
        if not args.game_dir.exists():
            print(f"Error: Game directory not found: {args.game_dir}")
            return 1
        if not args.output_dir.exists():
            print(f"Error: Translated directory not found: {args.output_dir}")
            return 1
        
        return _run_verify(args.game_dir, args.output_dir)
    
    elif args.command == "import":
        if not args.game_dir.exists():
            print(f"Error: Game directory not found: {args.game_dir}")
            return 1
        
        if not args.translation.exists():
            print(f"Error: Translation file/directory not found: {args.translation}")
            return 1
        
        try:
            result = import_all(
                args.game_dir,
                args.translation,
                args.output,
                backup=not args.no_backup
            )
            
            print("\n=== Import Summary ===")
            print(f"Total translations applied: {result['total_applied']}")
            print(f"Files processed: {result['files_processed']}")
            
            if args.output:
                print(f"Output directory: {args.output}")
            else:
                print(f"Modified: {args.game_dir}/www/data (backup created)")
            
            # Auto-verify after import unless --no-verify
            if not args.no_verify:
                verify_target = args.output if args.output else args.game_dir
                verify_ret = _run_verify(args.game_dir, verify_target)
                if verify_ret != 0:
                    return verify_ret
            
            return 0
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    else:
        parser.print_help()
        return 1


def _print_verify_results(result: Dict) -> None:
    """Print structural verification results."""
    print("\n=== Structural Verification ===")
    print(f"Files checked: {result['files_checked']}")
    print(f"Errors: {result['errors']}")
    print(f"Warnings: {result['warnings']}")

    if not result['issues']:
        print("\n✓ No structural issues found. Translation is safe for gameplay.")
        return

    # Group issues by location prefix (file-level)
    from collections import OrderedDict
    grouped: Dict[str, List[Dict]] = OrderedDict()
    for issue in result['issues']:
        loc = issue['location']
        # Extract top-level key (e.g., "CE115", "Event3/Page0", "System/terms")
        top = loc.split('/')[0] if '/' in loc else loc
        grouped.setdefault(top, []).append(issue)

    errors_shown = 0
    warnings_shown = 0

    for group_key, group_issues in grouped.items():
        print(f"\n  [{group_key}]")
        for issue in group_issues:
            level_tag = "ERROR" if issue['level'] == 'error' else "WARN"
            symbol = "✗" if issue['level'] == 'error' else "⚠"
            loc = issue['location']
            print(f"    {symbol} [{level_tag}] {loc}: {issue['message']}")
            if issue['level'] == 'error':
                errors_shown += 1
            else:
                warnings_shown += 1

    print()
    if result['errors'] > 0:
        print(f"✗ Found {result['errors']} error(s) that may cause game runtime failures.")
    if result['warnings'] > 0:
        print(f"⚠ Found {result['warnings']} warning(s) worth reviewing.")


def _run_verify(game_dir: Path, output_dir: Path) -> int:
    """Execute structural verification and print results. Returns exit code."""
    result = verify_structure(game_dir, output_dir)
    _print_verify_results(result)
    return 1 if result['errors'] > 0 else 0


if __name__ == "__main__":
    exit(main())
