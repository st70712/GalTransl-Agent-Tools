#!/usr/bin/env python3
"""
將 Game/www/data/ 下的所有 JSON 遊戲內容替換為展示用範例文本。
保留所有 RPG Maker 結構（ID、code、數值參數等），只替換可見文字。
"""

import json
import re
from pathlib import Path
from itertools import count

DATA_DIR = Path("Game/www/data")

# ── 計數器，讓每行 demo 文本都有唯一編號 ──────────────────────────
_dialog_ctr  = count(1)
_choice_ctr  = count(1)
_scroll_ctr  = count(1)

def next_dialog():  return f"[Demo Dialog {next(_dialog_ctr)}] Hello, traveler. This is a sample line."
def next_choice():  return f"Choice {next(_choice_ctr)}"
def next_scroll():  return f"[Scroll Text {next(_scroll_ctr)}] Once upon a time in a faraway land..."


# ══════════════════════════════════════════════════════════════════
#  事件指令列表處理（Map*.json / CommonEvents.json 共用）
# ══════════════════════════════════════════════════════════════════
def sanitize_event_list(cmd_list: list) -> list:
    """替換 list[] 中所有含文字的指令，其餘保持不變。"""
    new_list = []
    i = 0
    while i < len(cmd_list):
        cmd = cmd_list[i]
        code = cmd.get("code", 0)
        params = cmd.get("parameters", [])
        new_cmd = dict(cmd)

        # ── 101: Show Text（顯示說話者資訊）──────────────────────
        if code == 101:
            # params: [faceName, faceIndex, background, position, speakerName?]
            new_params = list(params)
            new_params[0] = ""          # faceName → 清空（圖片不存在）
            if len(new_params) >= 5:
                # RPG Maker MZ speakerName (index 4)
                new_params[4] = "NPC" if new_params[4] else ""
            new_cmd["parameters"] = new_params
            new_list.append(new_cmd)
            i += 1
            # 緊接著收集 401 行，改為 demo 文本
            while i < len(cmd_list) and cmd_list[i]["code"] == 401:
                line_cmd = dict(cmd_list[i])
                line_cmd["parameters"] = [next_dialog()]
                new_list.append(line_cmd)
                i += 1
            continue

        # ── 102: Show Choices ─────────────────────────────────────
        elif code == 102:
            # params[0] = choices list
            new_params = list(params)
            choices = new_params[0]
            new_params[0] = [next_choice() for _ in choices]
            new_cmd["parameters"] = new_params
            new_list.append(new_cmd)

        # ── 405: Scroll Text content ──────────────────────────────
        elif code == 405:
            new_cmd["parameters"] = [next_scroll()]
            new_list.append(new_cmd)

        # ── 320/324: Change Name / Change Nickname ────────────────
        elif code in (320, 324):
            new_params = list(params)
            if len(new_params) >= 2:
                new_params[1] = "DemoName"
            new_cmd["parameters"] = new_params
            new_list.append(new_cmd)

        # ── 108/408: Comment（開發者備注，避免洩露劇情） ──────────
        elif code in (108, 408):
            new_cmd["parameters"] = ["[demo comment]"]
            new_list.append(new_cmd)

        # ── 231: Show Picture（圖片名稱可能包含日文/劇情資訊）────
        elif code == 231:
            new_params = list(params)
            # params[1] = picture name (string)
            if len(new_params) >= 2 and isinstance(new_params[1], str):
                new_params[1] = "demo_picture"
            new_cmd["parameters"] = new_params
            new_list.append(new_cmd)

        # ── 356: Plugin Command（可能含檔案名等敏感資訊）───────────
        elif code == 356:
            new_params = list(params)
            if new_params and isinstance(new_params[0], str):
                # 保留插件名稱前綴（第一個空白前的部分），清空參數
                parts = new_params[0].split(" ", 1)
                new_params[0] = parts[0] + (" demo_arg" if len(parts) > 1 else "")
            new_cmd["parameters"] = new_params
            new_list.append(new_cmd)

        else:
            new_list.append(new_cmd)

        i += 1
    return new_list


# ══════════════════════════════════════════════════════════════════
#  各 JSON 檔案的處理函數
# ══════════════════════════════════════════════════════════════════

def process_map(data: dict, filename: str) -> dict:
    data["displayName"] = f"Demo Map ({filename})"
    for ev in (data.get("events") or []):
        if not ev:
            continue
        ev["name"] = f"EV{ev['id']:03d}"
        for page in (ev.get("pages") or []):
            page["list"] = sanitize_event_list(page.get("list", []))
    return data


def process_common_events(data: list) -> list:
    result = []
    for ev in data:
        if not ev:
            result.append(ev)
            continue
        ev["name"] = f"CommonEvent{ev['id']:03d}"
        ev["list"] = sanitize_event_list(ev.get("list", []))
        result.append(ev)
    return result


def process_map_infos(data: list) -> list:
    result = []
    for entry in data:
        if not entry:
            result.append(entry)
            continue
        entry["name"] = f"Map{entry['id']:03d}"
        result.append(entry)
    return result


def process_system(data: dict) -> dict:
    data["gameTitle"] = "Demo Game"
    data["locale"] = "en_US"

    # armorTypes / skillTypes / elements / equipTypes (index 0 = "" placeholder)
    for key, prefix in [
        ("armorTypes",  "Armor Type"),
        ("skillTypes",  "Skill Type"),
        ("elements",    "Element"),
        ("equipTypes",  "Equip Slot"),
        ("weaponTypes", "Weapon Type"),
    ]:
        if key in data and isinstance(data[key], list):
            data[key] = ["" if i == 0 else f"{prefix} {i}"
                         for i in range(len(data[key]))]

    # terms.basic  (HP, MP, ATK, ...)
    terms = data.get("terms", {})
    if "basic" in terms:
        labels = ["Max HP","Max MP","Attack","Defense",
                  "Magic Atk","Magic Def","Agility","Luck","Hit","Evasion"]
        terms["basic"] = [labels[i] if i < len(labels) else f"Param{i}"
                          for i in range(len(terms["basic"]))]

    # terms.commands (Fight, Escape, Attack, Skill, ...)
    if "commands" in terms:
        cmd_labels = ["Fight","Escape","Attack","Guard","Item","Skill","Equip",
                      "Status","Formation","Save","GameEnd","Options","Weapon",
                      "Armor","KeyItem","Buy","Sell"]
        terms["commands"] = [cmd_labels[i] if i < len(cmd_labels) else f"Cmd{i}"
                              for i in range(len(terms["commands"]))]

    # terms.params
    if "params" in terms:
        param_labels = ["Max HP","Max MP","Attack","Defense",
                        "Magic Atk","Magic Def","Agility","Luck"]
        terms["params"] = [param_labels[i] if i < len(param_labels) else f"Prm{i}"
                           for i in range(len(terms["params"]))]

    # terms.messages  (keep keys, replace values)
    if "messages" in terms:
        for k in terms["messages"]:
            terms["messages"][k] = f"[{k}]"

    data["terms"] = terms

    # variables / switches 名稱（debug_name context 的來源）
    if "variables" in data and isinstance(data["variables"], list):
        data["variables"] = [
            "" if (i == 0 or not v) else f"Variable{i:03d}"
            for i, v in enumerate(data["variables"])
        ]
    if "switches" in data and isinstance(data["switches"], list):
        data["switches"] = [
            "" if (i == 0 or not v) else f"Switch{i:03d}"
            for i, v in enumerate(data["switches"])
        ]

    return data


def process_actors(data: list) -> list:
    result = []
    names    = ["Hero", "Heroine", "Warrior", "Mage", "Cleric", "Rogue"]
    for entry in data:
        if not entry:
            result.append(entry)
            continue
        idx = entry["id"] - 1
        entry["name"]     = names[idx] if idx < len(names) else f"Actor{entry['id']}"
        entry["nickname"] = f"The {entry['name']}"
        entry["profile"]  = f"This is {entry['name']}'s demo profile text."
        entry["note"]     = ""
        result.append(entry)
    return result


def process_db_list(data: list, text_fields: list, prefix: str) -> list:
    result = []
    for entry in data:
        if not entry:
            result.append(entry)
            continue
        for field in text_fields:
            if field in entry:
                if isinstance(entry[field], str) and entry[field]:
                    if field == "name":
                        entry[field] = f"{prefix} {entry['id']}"
                    elif field in ("description", "profile", "message1",
                                   "message2", "message3", "message4"):
                        entry[field] = f"Demo {field} for {prefix} {entry['id']}."
                    else:
                        entry[field] = ""
        entry["note"] = ""
        result.append(entry)
    return result


def process_classes(data: list) -> list:
    return process_db_list(data, ["name", "description", "note"], "Class")

def process_skills(data: list) -> list:
    return process_db_list(data,
        ["name", "description", "message1", "message2"], "Skill")

def process_items(data: list) -> list:
    return process_db_list(data, ["name", "description"], "Item")

def process_weapons(data: list) -> list:
    return process_db_list(data, ["name", "description"], "Weapon")

def process_armors(data: list) -> list:
    return process_db_list(data, ["name", "description"], "Armor")

def process_enemies(data: list) -> list:
    return process_db_list(data, ["name"], "Enemy")

def process_states(data: list) -> list:
    return process_db_list(data,
        ["name", "message1", "message2", "message3", "message4"], "State")

def process_troops(data: list) -> list:
    result = []
    for entry in data:
        if not entry:
            result.append(entry)
            continue
        entry["name"] = f"Troop{entry['id']:02d}"
        # 清除 pages 中的 conditions 文字（一般沒有文字，保留結構）
        result.append(entry)
    return result


# ══════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════
PROCESSORS = {
    "System.json":        ("object",   process_system),
    "MapInfos.json":      ("array",    process_map_infos),
    "CommonEvents.json":  ("array",    process_common_events),
    "Actors.json":        ("array",    process_actors),
    "Classes.json":       ("array",    process_classes),
    "Skills.json":        ("array",    process_skills),
    "Items.json":         ("array",    process_items),
    "Weapons.json":       ("array",    process_weapons),
    "Armors.json":        ("array",    process_armors),
    "Enemies.json":       ("array",    process_enemies),
    "States.json":        ("array",    process_states),
    "Troops.json":        ("array",    process_troops),
    # Animations.json / Tilesets.json 純技術資料，不含可見文字，略過
}

def main():
    for path in sorted(DATA_DIR.glob("*.json")):
        fname = path.name

        # ── Map*.json ─────────────────────────────────────────────
        if re.match(r"Map\d+\.json$", fname):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = process_map(data, fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            print(f"  [Map]  {fname}")
            continue

        # ── 其他已登錄的檔案 ──────────────────────────────────────
        if fname in PROCESSORS:
            _, processor = PROCESSORS[fname]
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = processor(data)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            print(f"  [OK]   {fname}")
        else:
            print(f"  [skip] {fname}  (no text content, kept as-is)")

    print("\nDone. All actual game text replaced with demo content.")

if __name__ == "__main__":
    main()
