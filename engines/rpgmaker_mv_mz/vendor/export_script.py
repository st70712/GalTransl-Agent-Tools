#!/usr/bin/env python3
"""
RPG Maker MV/MZ Text Exporter
Exports translatable text from RPG Maker game data to JSON format for translation

Supports:
- Map events (Map*.json) - Dialogues and event commands
- Common events (CommonEvents.json)
- System data (System.json) - Terms, menu texts
- Actors, Items, Skills, Enemies, etc.

Author: GalTransl-RPGmaker Project
"""

import json
import argparse
import re
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional


# RPG Maker event command codes for text
TEXT_CODES = {
    101: "show_text_options",   # Show Text (顯示對話設定)
    102: "show_choices",        # Show Choices (顯示選項)
    401: "show_text_content",   # Text content (對話內容)
    402: "choice_branch",       # When [Choice]
    405: "scroll_text_content", # Scroll Text content
    108: "comment",             # Comment
    408: "comment_content",     # Comment content
    355: "script",              # Script
    655: "script_content",      # Script content
    320: "change_name",         # Change Name
    324: "change_nickname",     # Change Nickname
    231: "show_picture",        # Show Picture (圖片名稱可能需要翻譯)
    356: "plugin_command",      # Plugin Command (MV style, single string)
    357: "plugin_command_mz",   # Plugin Command (MZ style, args dict in params[3])
    657: "plugin_command_arg",  # Plugin Command argument echo (editor display)
}


@dataclass
class TextEntry:
    """Represents a translatable text entry"""
    index: int
    source_file: str
    location: str  # e.g., "Map001/Event1/Page1/Command5"
    original: str
    translated: str = ""
    context: str = ""  # dialog, choice, name, description, etc.
    speaker: str = ""  # Speaker name if available
    code: int = 0  # Event command code


@dataclass
class ExportInfo:
    """Export metadata"""
    game_title: str = ""
    version: str = "1.0"
    total_strings: int = 0
    source_files: List[str] = field(default_factory=list)


@dataclass
class ContextTypeInfo:
    """Defines a context type for translation"""
    description: str
    priority: str  # 高, 中, 低, 最低
    style: str
    note: str = ""


# Centralized context type definitions
CONTEXT_TYPES: Dict[str, ContextTypeInfo] = {
    "dialog": ContextTypeInfo("對話文本", "高", "自然口語化"),
    "choice": ContextTypeInfo("選項文本", "高", "簡潔明確", "可能包含 if(s[xxx]) 條件需保留"),
    "scroll_text": ContextTypeInfo("滾動文字", "高", "文學性較強"),
    "picture_name": ContextTypeInfo("圖片名稱", "低", "通常不需翻譯"),
    "map_name": ContextTypeInfo("地圖名稱", "中", "簡短地點名稱"),
    "event_name": ContextTypeInfo("事件名稱", "低", "開發者參考用"),
    "common_event_name": ContextTypeInfo("公共事件名稱", "低", "開發者參考用"),
    "game_title": ContextTypeInfo("遊戲標題", "高", "精心翻譯"),
    "term": ContextTypeInfo("術語", "中", "業界通用翻譯"),
    "command": ContextTypeInfo("選單指令", "高", "簡潔動詞/名詞"),
    "param": ContextTypeInfo("參數名", "中", "業界通用翻譯"),
    "message": ContextTypeInfo("系統訊息", "中", "保留 %1 %2 佔位符"),
    "actor": ContextTypeInfo("角色資料", "高", "名稱可音譯或意譯"),
    "skill": ContextTypeInfo("技能資料", "中", "有遊戲感"),
    "item": ContextTypeInfo("道具資料", "中", "有遊戲感"),
    "weapon": ContextTypeInfo("武器資料", "中", "有遊戲感"),
    "armor": ContextTypeInfo("防具資料", "中", "有遊戲感"),
    "enemy": ContextTypeInfo("敵人資料", "中", "有威脅感"),
    "state": ContextTypeInfo("狀態資料", "中", "簡潔明確"),
    "type_name": ContextTypeInfo("類型名稱", "低", "通用類型名稱"),
    "debug_name": ContextTypeInfo("除錯名稱", "最低", "可跳過不翻譯"),
    "class": ContextTypeInfo("職業資料", "中", "符合遊戲風格"),
    "plugin_command": ContextTypeInfo("插件指令", "低", "通常不需翻譯"),
    "currency": ContextTypeInfo("貨幣單位", "中", "簡短名稱"),
}

# Source file descriptions
SOURCE_FILES: Dict[str, str] = {
    "System.json": "系統設定、術語、選單文字",
    "CommonEvents.json": "公共事件（對話、劇情）",
    "Map*.json": "地圖事件",
    "Actors.json": "角色資料",
    "Skills.json": "技能資料",
    "Items.json": "道具資料",
    "Weapons.json": "武器資料",
    "Armors.json": "防具資料",
    "Enemies.json": "敵人資料",
    "States.json": "狀態資料",
    "Classes.json": "職業資料",
}

# RPG Maker control codes
CONTROL_CODES: Dict[str, str] = {
    "\\n": "換行符號，多行對話會用此分隔",
    "\\\\N[n]": "遊戲中會顯示第 n 號角色的名稱",
    "\\\\V[n]": "遊戲中會顯示第 n 號變數的值",
    "\\\\C[n]": "文字顏色代碼",
    "\\\\G": "貨幣單位",
    "\\\\I[n]": "顯示第 n 號圖標",
    "\\\\{": "放大文字",
    "\\\\}": "縮小文字",
    "\\\\!": "等待按鍵",
    "\\\\.": "等待 1/4 秒",
    "\\\\|": "等待 1 秒",
}

# Event command code descriptions
EVENT_COMMAND_CODES: Dict[int, str] = {
    0: "無特定代碼（資料庫條目）",
    101: "顯示文字指令（對話開始）",
    102: "顯示選項指令",
    231: "顯示圖片指令",
    356: "插件指令",
    401: "文字內容（對話正文）",
    405: "滾動文字內容",
}


class FormatSpecificationBuilder:
    """Builder class for generating format specification document"""
    
    def __init__(self, version: str = "1.0"):
        self.version = version
    
    def _build_file_structure(self) -> Dict[str, Any]:
        """Build file structure section"""
        return {
            "info": {
                "description": "翻譯檔案的元數據資訊",
                "fields": {
                    "game_title": {"type": "string", "description": "遊戲原始標題"},
                    "version": {"type": "string", "description": "翻譯檔案版本"},
                    "string_count": {"type": "integer", "description": "總字串數量"}
                }
            },
            "strings": {
                "description": "可翻譯字串陣列，每個元素代表一個需要翻譯的文本條目",
                "type": "array"
            }
        }
    
    def _build_field_spec(self, name: str, field_type: str, description: str, 
                          extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build a single field specification"""
        spec = {
            "type": field_type,
            "description": description,
        }
        if extra:
            spec.update(extra)
        return spec
    
    def _build_strings_fields(self) -> Dict[str, Any]:
        """Build strings array fields specification"""
        return {
            "index": self._build_field_spec(
                "index", "integer",
                "字串在陣列中的唯一索引編號，從 0 開始遞增",
                {"translation_note": "此欄位僅供定位用途，翻譯時不需修改"}
            ),
            "source_file": self._build_field_spec(
                "source_file", "string",
                "此文本來源的 RPG Maker 資料檔案名稱",
                {
                    "possible_values": [f"{k} - {v}" for k, v in SOURCE_FILES.items()],
                    "translation_note": "此欄位僅供參考，翻譯時不需修改"
                }
            ),
            "location": self._build_field_spec(
                "location", "string",
                "文本在來源檔案中的精確位置路徑",
                {
                    "format_examples": {
                        "event_dialog": "Event1/Page0/Cmd5 - 地圖事件1/頁面0/指令5",
                        "common_event_dialog": "CE100/Cmd258 - 公共事件100/指令258",
                        "choice": "CE84/Cmd18/Choice0 - 公共事件84/指令18/選項0",
                        "event_name": "Event1/name - 事件名稱",
                        "system_term": "terms/messages/actionFailure - 系統術語",
                        "database_entry": "ID1/name - 資料庫項目1的名稱欄位"
                    },
                    "translation_note": "此欄位僅供定位用途，翻譯時不需修改"
                }
            ),
            "original": self._build_field_spec(
                "original", "string",
                "原始日文文本，這是需要被翻譯的內容",
                {
                    "special_characters": CONTROL_CODES,
                    "translation_note": "翻譯時必須保留所有特殊控制碼，僅翻譯可見文字部分"
                }
            ),
            "translated": self._build_field_spec(
                "translated", "string",
                "翻譯後的文本，AI 翻譯代理需要填入此欄位",
                {
                    "default": "",
                    "translation_rules": [
                        "將 original 欄位的日文翻譯成目標語言",
                        "保留所有 \\\\N[n]、\\\\V[n]、\\\\C[n] 等控制碼不變",
                        "保留 \\n 換行符號的位置（可適當調整以配合翻譯）",
                        "對於選項類型(choice)，如包含條件判斷 if(s[xxx])，需保留條件部分",
                        "注意翻譯長度，過長可能導致遊戲顯示問題",
                        "空字串表示尚未翻譯"
                    ]
                }
            ),
            "context": self._build_field_spec(
                "context", "string",
                "文本的類型分類，用於判斷翻譯策略和風格",
                {"possible_values": self._build_context_values()}
            ),
            "speaker": self._build_field_spec(
                "speaker", "string",
                "說話者名稱（如果有的話）",
                {
                    "translation_note": "此欄位可幫助理解對話語境和說話風格",
                    "usage": ["判斷說話者性格以調整翻譯語氣", "保持同一角色的用語一致性"]
                }
            ),
            "code": self._build_field_spec(
                "code", "integer",
                "RPG Maker 事件指令代碼",
                {
                    "common_values": {str(k): v for k, v in EVENT_COMMAND_CODES.items()},
                    "translation_note": "此欄位僅供參考，翻譯時不需修改"
                }
            ),
        }
    
    def _build_context_values(self) -> Dict[str, Dict[str, str]]:
        """Build context possible values from CONTEXT_TYPES"""
        result = {}
        for ctx_name, ctx_info in CONTEXT_TYPES.items():
            value = {
                "description": ctx_info.description,
                "priority": ctx_info.priority,
                "style": ctx_info.style,
            }
            if ctx_info.note:
                value["note"] = ctx_info.note
            result[ctx_name] = value
        return result
    
    def _build_translation_examples(self) -> List[Dict[str, Any]]:
        """Build translation examples"""
        examples = [
            ("基本對話翻譯", 
             "目を覚ますと、見慣れない白い天井。", 
             "醒來後，映入眼簾的是陌生的白色天花板。"),
            ("多行對話（保留換行）", 
             "こんにちは。\n元気ですか？", 
             "你好。\n你還好嗎？"),
            ("帶條件的選項（保留條件）", 
             "1日目 if(s[211])", 
             "第一天 if(s[211])"),
            ("系統訊息（保留佔位符）", 
             "%1は %2 のダメージを受けた！", 
             "%1 受到了 %2 點傷害！"),
            ("控制碼（保留控制碼）", 
             "\\C[2]重要\\C[0]な情報です。", 
             "這是\\C[2]重要\\C[0]的情報。"),
        ]
        return [
            {
                "description": desc,
                "before": {"original": orig, "translated": ""},
                "after": {"original": orig, "translated": trans}
            }
            for desc, orig, trans in examples
        ]
    
    def _build_priority_order(self) -> List[str]:
        """Build priority order based on CONTEXT_TYPES"""
        priority_groups = {
            "高": [],
            "中": [],
            "低": [],
            "最低": [],
        }
        for ctx_name, ctx_info in CONTEXT_TYPES.items():
            priority_groups[ctx_info.priority].append(ctx_name)
        
        order = []
        priority_labels = {
            "高": "最優先",
            "中": "",
            "低": "可選翻譯",
            "最低": "可跳過",
        }
        
        idx = 1
        for priority in ["高", "中", "低", "最低"]:
            if priority_groups[priority]:
                items = " / ".join(priority_groups[priority])
                label = priority_labels[priority]
                suffix = f"（{label}）" if label else ""
                order.append(f"{idx}. {items}{suffix}")
                idx += 1
        
        return order
    
    def _build_ai_guidelines(self) -> Dict[str, Any]:
        """Build AI agent guidelines"""
        return {
            "workflow": [
                "1. 讀取翻譯 JSON 檔案",
                "2. 遍歷 strings 陣列中的每個條目",
                "3. 根據 context 欄位判斷翻譯策略",
                "4. 翻譯 original 欄位的內容",
                "5. 將翻譯結果寫入 translated 欄位",
                "6. 保存修改後的 JSON 檔案"
            ],
            "priority_order": self._build_priority_order(),
            "quality_checks": [
                "確保所有控制碼（\\\\N[n], \\\\V[n] 等）被保留",
                "確保佔位符（%1, %2 等）被保留",
                "確保條件判斷（if(s[xxx])）被保留",
                "檢查翻譯長度是否合理",
                "保持同一角色用語風格一致"
            ],
            "skip_conditions": [
                f"context 為 '{ctx}' 的條目可跳過"
                for ctx, info in CONTEXT_TYPES.items()
                if info.priority == "最低"
            ] + [
                "context 為 'plugin_command' 且不含日文顯示文字的可跳過",
                "context 為 'picture_name' 且為純檔名的可跳過"
            ]
        }
    
    def build(self) -> Dict[str, Any]:
        """Build the complete format specification"""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "GalTransl-RPGmaker Translation File Format",
            "description": "RPG Maker MV/MZ 遊戲翻譯檔案格式說明，供 AI 翻譯代理參考",
            "version": self.version,
            "file_structure": self._build_file_structure(),
            "strings_array_fields": self._build_strings_fields(),
            "translation_examples": self._build_translation_examples(),
            "ai_agent_guidelines": self._build_ai_guidelines(),
        }


def generate_format_specification(version: str = "1.0") -> Dict[str, Any]:
    """
    Generate JSON format specification document for AI translation agents.
    
    Uses FormatSpecificationBuilder to create a modular, maintainable specification
    based on centralized definitions (CONTEXT_TYPES, SOURCE_FILES, etc.)
    
    Args:
        version: Version string for the specification document
    
    Returns:
        Complete format specification dictionary
    """
    builder = FormatSpecificationBuilder(version=version)
    return builder.build()


def is_translatable_text(text: str) -> bool:
    """
    Check if a string contains translatable content.
    Filter out control-only strings, empty strings, etc.
    """
    if not text or not isinstance(text, str):
        return False
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    if not text:
        return False
    
    # Skip if it's just a file path or resource name
    if text.endswith(('.png', '.jpg', '.ogg', '.m4a', '.wav', '.mp3')):
        return False
    
    # Skip if it's just numbers
    if text.isdigit():
        return False
    
    # Skip if it's a plugin command that doesn't need translation
    plugin_skip_patterns = [
        r'^[A-Z_]+\s+\d+',  # PLUGIN_NAME 123
        r'^P_CALL_CE',
        r'^MSGSE\s+',
        r'^Choicelist_offset',
        r'^createFilter',
        r'^setFilter',
        r'^eraseAllFilter',
    ]
    for pattern in plugin_skip_patterns:
        if re.match(pattern, text):
            return False
    
    # Check if contains Japanese/Chinese/Korean characters (likely needs translation)
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]', text):
        return True
    
    # Check if contains meaningful alphabetic text (at least 2 letters)
    if re.search(r'[a-zA-Z]{2,}', text):
        # Skip common non-translatable patterns
        skip_patterns = [
            r'^[A-Z]+\d*$',  # ALL_CAPS_VAR
            r'^if\(s\[',     # if(s[xxx])
            r'^\d+[a-z]$',   # 1a, 2b, etc.
        ]
        for pattern in skip_patterns:
            if re.match(pattern, text):
                return False
        return True
    
    return False


# Regex matching Japanese kana/kanji (source language markers)
JP_REGEX = r'[぀-ゟ゠-ヿ一-鿿]'


def _has_jp(text: Any) -> bool:
    """True if the value is a string containing Japanese characters."""
    return isinstance(text, str) and re.search(JP_REGEX, text) is not None


def _try_parse_json_container(s: Any) -> Optional[Any]:
    """
    If s is a JSON-encoded array/object string, return the parsed structure.
    Otherwise return None. Used to descend into plugin args whose values are
    themselves serialized JSON (e.g. choice lists).
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


def collect_json_leaves(node: Any, out: List[str]) -> None:
    """
    Depth-first collect translatable (Japanese-containing) string leaves from a
    nested structure. String leaves that are themselves JSON containers are
    recursed into. Traversal order MUST match rebuild_json_leaves so that the
    N-th leaf lines up on import.
    """
    if isinstance(node, str):
        sub = _try_parse_json_container(node)
        if sub is not None:
            collect_json_leaves(sub, out)
        elif _has_jp(node) and is_translatable_text(node):
            out.append(node)
    elif isinstance(node, list):
        for item in node:
            collect_json_leaves(item, out)
    elif isinstance(node, dict):
        for val in node.values():
            collect_json_leaves(val, out)


def plugin_arg_context(arg_key: str) -> str:
    """Classify a plugin-command argument key into a translation context."""
    key = arg_key.lower()
    if 'choice' in key:
        return 'choice'
    return 'dialog'


def extract_event_commands(commands: List[Dict],
                          source_file: str, 
                          location_prefix: str) -> List[TextEntry]:
    """
    Extract translatable text from event command list.
    """
    entries = []
    index = 0
    current_speaker = ""
    
    i = 0
    while i < len(commands):
        cmd = commands[i]
        code = cmd.get("code", 0)
        params = cmd.get("parameters", [])
        
        # Show Text Options (code 101)
        # parameters: [face_name, face_index, background, position]
        # Next commands with code 401 are the actual text
        if code == 101:
            if len(params) >= 1:
                current_speaker = params[0] if params[0] else ""
            
            # Collect all following 401 commands
            text_parts = []
            j = i + 1
            while j < len(commands) and commands[j].get("code") == 401:
                text_params = commands[j].get("parameters", [])
                if text_params and isinstance(text_params[0], str):
                    text_parts.append(text_params[0])
                j += 1
            
            full_text = "\n".join(text_parts)
            if is_translatable_text(full_text):
                entries.append(TextEntry(
                    index=index,
                    source_file=source_file,
                    location=f"{location_prefix}/Cmd{i}",
                    original=full_text,
                    context="dialog",
                    speaker=current_speaker,
                    code=code
                ))
                index += 1
            
            i = j
            continue
        
        # Show Choices (code 102)
        # parameters: [choices_array, cancel_type, default_type, position_type, background]
        elif code == 102:
            if params and isinstance(params[0], list):
                for choice_idx, choice in enumerate(params[0]):
                    # Filter out conditional choices like "朝 if(s[240])"
                    clean_choice = re.sub(r'\s*if\(s\[\d+\]\)', '', str(choice)).strip()
                    if is_translatable_text(clean_choice):
                        entries.append(TextEntry(
                            index=index,
                            source_file=source_file,
                            location=f"{location_prefix}/Cmd{i}/Choice{choice_idx}",
                            original=choice,
                            context="choice",
                            code=code
                        ))
                        index += 1
        
        # Scroll Text content (code 405)
        elif code == 405:
            if params and isinstance(params[0], str) and is_translatable_text(params[0]):
                entries.append(TextEntry(
                    index=index,
                    source_file=source_file,
                    location=f"{location_prefix}/Cmd{i}",
                    original=params[0],
                    context="scroll_text",
                    code=code
                ))
                index += 1
        
        # Show Picture (code 231) - picture name might contain text
        elif code == 231:
            if params and len(params) >= 2 and isinstance(params[1], str):
                pic_name = params[1]
                # Only include if it contains Japanese text (likely needs translation)
                if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', pic_name):
                    entries.append(TextEntry(
                        index=index,
                        source_file=source_file,
                        location=f"{location_prefix}/Cmd{i}",
                        original=pic_name,
                        context="picture_name",
                        code=code
                    ))
                    index += 1
        
        # Plugin Command (code 356)
        elif code == 356:
            if params and isinstance(params[0], str):
                plugin_text = params[0]
                # Check if contains translatable text within plugin command
                if is_translatable_text(plugin_text) and re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', plugin_text):
                    entries.append(TextEntry(
                        index=index,
                        source_file=source_file,
                        location=f"{location_prefix}/Cmd{i}",
                        original=plugin_text,
                        context="plugin_command",
                        code=code
                    ))
                    index += 1

        # Plugin Command MZ (code 357) - arguments stored in params[3] dict.
        # Many MZ plugins (e.g. LogMessage, choice plugins) render on-screen text
        # from these args; the runtime reads params[3], while the following 657
        # commands are editor-only echoes.
        elif code == 357:
            if len(params) >= 4 and isinstance(params[3], dict):
                for arg_key, arg_val in params[3].items():
                    if not isinstance(arg_val, str):
                        continue
                    nested = _try_parse_json_container(arg_val)
                    if nested is not None:
                        # Nested JSON arg (e.g. choice list) - one entry per leaf.
                        leaves: List[str] = []
                        collect_json_leaves(nested, leaves)
                        for leaf_idx, leaf_val in enumerate(leaves):
                            entries.append(TextEntry(
                                index=index,
                                source_file=source_file,
                                location=f"{location_prefix}/Cmd{i}/PArg:{arg_key}/N{leaf_idx}",
                                original=leaf_val,
                                context=plugin_arg_context(arg_key),
                                code=code
                            ))
                            index += 1
                    elif _has_jp(arg_val) and is_translatable_text(arg_val):
                        entries.append(TextEntry(
                            index=index,
                            source_file=source_file,
                            location=f"{location_prefix}/Cmd{i}/PArg:{arg_key}",
                            original=arg_val,
                            context=plugin_arg_context(arg_key),
                            code=code
                        ))
                        index += 1

        i += 1
    
    return entries


def extract_map_data(map_file: Path) -> List[TextEntry]:
    """
    Extract translatable text from a map file.
    """
    entries = []
    
    with open(map_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    source_file = map_file.name
    
    # Extract displayName if present
    if data.get("displayName") and is_translatable_text(data["displayName"]):
        entries.append(TextEntry(
            index=0,
            source_file=source_file,
            location="displayName",
            original=data["displayName"],
            context="map_name"
        ))
    
    # Extract from events
    events = data.get("events", [])
    for event in events:
        if event is None:
            continue
        
        event_id = event.get("id", 0)
        event_name = event.get("name", "")
        
        # Extract event name if translatable
        if is_translatable_text(event_name):
            entries.append(TextEntry(
                index=len(entries),
                source_file=source_file,
                location=f"Event{event_id}/name",
                original=event_name,
                context="event_name"
            ))
        
        # Extract from event pages
        pages = event.get("pages", [])
        for page_idx, page in enumerate(pages):
            commands = page.get("list", [])
            location_prefix = f"Event{event_id}/Page{page_idx}"
            
            page_entries = extract_event_commands(commands, source_file, location_prefix)
            for entry in page_entries:
                entry.index = len(entries)
                entries.append(entry)
    
    return entries


def extract_common_events(ce_file: Path) -> List[TextEntry]:
    """
    Extract translatable text from CommonEvents.json.
    """
    entries = []
    
    with open(ce_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    source_file = ce_file.name
    
    for event in data:
        if event is None:
            continue
        
        event_id = event.get("id", 0)
        event_name = event.get("name", "")
        
        # Extract event name if translatable
        if is_translatable_text(event_name):
            entries.append(TextEntry(
                index=len(entries),
                source_file=source_file,
                location=f"CE{event_id}/name",
                original=event_name,
                context="common_event_name"
            ))
        
        # Extract from command list
        commands = event.get("list", [])
        location_prefix = f"CE{event_id}"
        
        cmd_entries = extract_event_commands(commands, source_file, location_prefix)
        for entry in cmd_entries:
            entry.index = len(entries)
            entries.append(entry)
    
    return entries


def extract_system_data(system_file: Path) -> List[TextEntry]:
    """
    Extract translatable text from System.json.
    """
    entries = []
    
    with open(system_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    source_file = system_file.name
    
    # Game title
    if data.get("gameTitle") and is_translatable_text(data["gameTitle"]):
        entries.append(TextEntry(
            index=len(entries),
            source_file=source_file,
            location="gameTitle",
            original=data["gameTitle"],
            context="game_title"
        ))
    
    # Currency unit
    if data.get("currencyUnit") and is_translatable_text(data["currencyUnit"]):
        entries.append(TextEntry(
            index=len(entries),
            source_file=source_file,
            location="currencyUnit",
            original=data["currencyUnit"],
            context="currency"
        ))
    
    # Type names (armor types, skill types, etc.)
    type_arrays = ["armorTypes", "equipTypes", "skillTypes", "weaponTypes", "elements"]
    for type_name in type_arrays:
        if type_name in data:
            for idx, value in enumerate(data[type_name]):
                if is_translatable_text(value):
                    entries.append(TextEntry(
                        index=len(entries),
                        source_file=source_file,
                        location=f"{type_name}/{idx}",
                        original=value,
                        context="type_name"
                    ))
    
    # Switches and Variables names
    for var_type in ["switches", "variables"]:
        if var_type in data:
            for idx, value in enumerate(data[var_type]):
                if is_translatable_text(value):
                    entries.append(TextEntry(
                        index=len(entries),
                        source_file=source_file,
                        location=f"{var_type}/{idx}",
                        original=value,
                        context="debug_name"
                    ))
    
    # Terms
    if "terms" in data:
        terms = data["terms"]
        
        # Basic terms
        if "basic" in terms:
            for idx, term in enumerate(terms["basic"]):
                if is_translatable_text(term):
                    entries.append(TextEntry(
                        index=len(entries),
                        source_file=source_file,
                        location=f"terms/basic/{idx}",
                        original=term,
                        context="term"
                    ))
        
        # Command terms
        if "commands" in terms:
            for idx, term in enumerate(terms["commands"]):
                if term and is_translatable_text(term):
                    entries.append(TextEntry(
                        index=len(entries),
                        source_file=source_file,
                        location=f"terms/commands/{idx}",
                        original=term,
                        context="command"
                    ))
        
        # Params
        if "params" in terms:
            for idx, term in enumerate(terms["params"]):
                if is_translatable_text(term):
                    entries.append(TextEntry(
                        index=len(entries),
                        source_file=source_file,
                        location=f"terms/params/{idx}",
                        original=term,
                        context="param"
                    ))
        
        # Messages
        if "messages" in terms:
            for key, msg in terms["messages"].items():
                if is_translatable_text(msg):
                    entries.append(TextEntry(
                        index=len(entries),
                        source_file=source_file,
                        location=f"terms/messages/{key}",
                        original=msg,
                        context="message"
                    ))
    
    return entries


def extract_database_entries(db_file: Path, fields: List[str], context: str) -> List[TextEntry]:
    """
    Extract translatable text from database files (Actors, Items, Skills, etc.)
    """
    entries = []
    
    with open(db_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    source_file = db_file.name
    
    for item in data:
        if item is None:
            continue
        
        item_id = item.get("id", 0)
        
        for field_name in fields:
            if field_name in item and is_translatable_text(item[field_name]):
                entries.append(TextEntry(
                    index=len(entries),
                    source_file=source_file,
                    location=f"ID{item_id}/{field_name}",
                    original=item[field_name],
                    context=context
                ))
    
    return entries


def export_all(game_dir: Path, output_dir: Path, split_by_file: bool = False):
    """
    Export all translatable text from the game data directory.
    """
    data_dir = game_dir / "www" / "data"
    
    if not data_dir.exists():
        # Try alternative structure (direct www folder)
        data_dir = game_dir / "data"
        if not data_dir.exists():
            raise FileNotFoundError(f"Data directory not found in {game_dir}")
    
    all_entries = []
    source_files = []
    game_title = ""
    
    # Extract System.json first to get game title
    system_file = data_dir / "System.json"
    if system_file.exists():
        with open(system_file, 'r', encoding='utf-8') as f:
            system_data = json.load(f)
        game_title = system_data.get("gameTitle", "Unknown")
        
        print(f"Processing: {system_file.name}")
        entries = extract_system_data(system_file)
        if entries:
            all_entries.extend(entries)
            source_files.append(system_file.name)
    
    # Extract CommonEvents.json
    ce_file = data_dir / "CommonEvents.json"
    if ce_file.exists():
        print(f"Processing: {ce_file.name}")
        entries = extract_common_events(ce_file)
        if entries:
            all_entries.extend(entries)
            source_files.append(ce_file.name)
    
    # Extract Map files
    map_files = sorted(data_dir.glob("Map*.json"))
    for map_file in map_files:
        if map_file.name == "MapInfos.json":
            continue
        print(f"Processing: {map_file.name}")
        entries = extract_map_data(map_file)
        if entries:
            all_entries.extend(entries)
            source_files.append(map_file.name)
    
    # Extract database files
    db_configs = [
        ("Actors.json", ["name", "nickname", "profile"], "actor"),
        ("Classes.json", ["name"], "class"),
        ("Skills.json", ["name", "description", "message1", "message2"], "skill"),
        ("Items.json", ["name", "description"], "item"),
        ("Weapons.json", ["name", "description"], "weapon"),
        ("Armors.json", ["name", "description"], "armor"),
        ("Enemies.json", ["name"], "enemy"),
        ("States.json", ["name", "message1", "message2", "message3", "message4"], "state"),
    ]
    
    for filename, fields, context in db_configs:
        db_file = data_dir / filename
        if db_file.exists():
            print(f"Processing: {filename}")
            entries = extract_database_entries(db_file, fields, context)
            if entries:
                all_entries.extend(entries)
                source_files.append(filename)
    
    # Reassign indices
    for idx, entry in enumerate(all_entries):
        entry.index = idx
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare output data
    info = {
        "game_title": game_title,
        "version": "1.0",
        "string_count": len(all_entries)
    }
    
    if split_by_file:
        # Split by source file
        by_file = {}
        for entry in all_entries:
            if entry.source_file not in by_file:
                by_file[entry.source_file] = []
            by_file[entry.source_file].append(entry)
        
        for source_file, entries in by_file.items():
            # Reassign indices within each file
            for idx, entry in enumerate(entries):
                entry.index = idx
            
            output_data = {
                "info": {
                    "game_title": game_title,
                    "source_file": source_file,
                    "string_count": len(entries)
                },
                "strings": [asdict(e) for e in entries]
            }
            
            # Use source file name as output name
            output_name = source_file.replace('.json', '_text.json')
            output_file = output_dir / output_name
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f"Exported: {output_file} ({len(entries)} strings)")
    else:
        # Single output file
        output_data = {
            "info": info,
            "strings": [asdict(e) for e in all_entries]
        }
        
        output_file = output_dir / "script.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"\nExported: {output_file}")
    
    # Generate and save format specification
    format_spec = generate_format_specification()
    format_spec_file = output_dir / "format_specification.json"
    with open(format_spec_file, 'w', encoding='utf-8') as f:
        json.dump(format_spec, f, ensure_ascii=False, indent=2)
    print(f"Generated: {format_spec_file}")
    
    print("\n=== Export Summary ===")
    print(f"Game Title: {game_title}")
    print(f"Total strings: {len(all_entries)}")
    print(f"Source files: {len(source_files)}")
    
    # Print breakdown by context
    context_counts = {}
    for entry in all_entries:
        context_counts[entry.context] = context_counts.get(entry.context, 0) + 1
    
    print("\nBy context:")
    for ctx, count in sorted(context_counts.items(), key=lambda x: -x[1]):
        print(f"  {ctx}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="RPG Maker MV/MZ Text Exporter - Export game text for translation"
    )
    parser.add_argument(
        "game_dir",
        type=Path,
        help="Path to the game directory (containing www/data folder)"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("exported"),
        help="Output directory for JSON files (default: exported)"
    )
    parser.add_argument(
        "-s", "--split",
        action="store_true",
        help="Split output by source file"
    )
    
    args = parser.parse_args()
    
    if not args.game_dir.exists():
        print(f"Error: Game directory not found: {args.game_dir}")
        return 1
    
    try:
        export_all(args.game_dir, args.output, args.split)
        return 0
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
