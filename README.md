# GalTransl-Agent-Tools

Agent 驅動的遊戲中文化補丁工具箱。在 Claude Code 裡照 `CLAUDE.md` 操作：辨識引擎 → 沿用或新寫引擎轉接器 →
導出文本 → 本機 Sakura 模型翻譯 → 整理／檢查譯文 → 導入 → 打包 → 使用者實機驗收。

已支援：RPG Maker MV/MZ、WOLF RPG 2.x/3.x、Unity（JSON 表格 TextAsset，含 TextMeshPro 動態字型）。其他引擎（Bishop、TyranoScript、KiriKiri、Ren'Py…）有線索與接入指引，見 `docs/engines.md`。

## 兩站接力

遊戲原檔太大搬不到模型機時，工作分兩站：**實機端**（Windows 筆電：有遊戲檔、能開遊戲）做辨識／解包／導出／導入／打包／實機驗收，
**翻譯端**（dgxluna：有 Sakura 模型）做翻譯與文本檢查；中間只搬幾 MB 的交接包（`agt handoff pack / unpack`，經 Google Drive 或手動）。
`python agt.py env` 告訴你自己在哪一站。協定與 Windows 首次設定見 `docs/two-site.md`。遊戲搬得過來就走單機流程，不需要交接。

## 引擎專用環境

核心只用標準庫。需要第三方套件的引擎在 `profile.json` 宣告 `python_env`，用 `bash tools/setup_env.sh <engine>` 建 venv（uv；Windows 先 `pip install uv`）。
每台機器的路徑寫在 `config.local.yaml`（不進 git，範例 `config.local.example.yaml`）。

## 快速開始

```bash
PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python      # 純標準庫工具（Windows: PY=python）
PYT=/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python      # 翻譯／opencc（只有 dgxluna 有）

$PY agt.py env                                        # 我是哪一站、能力齊不齊
$PY agt.py detect <遊戲目錄|遊戲zip|交接包>              # 來料判斷／辨識引擎
$PY agt.py init  mygame --original <遊戲目錄>          # 建 projects/mygame/
$PY agt.py gates mygame                               # prepare → roundtrip → export → 零翻譯導入 → verify → breakage
```

單機（遊戲在 dgxluna）：
```bash
bash tools/llama_server.sh start                      # 起本機模型（llama-server + Sakura-GalTransl-14B）
$PYT tools/translate.py -i projects/mygame/exported/script.json --limit 20   # 小樣本
$PYT tools/fix_text.py    projects/mygame/exported/script.json
$PY  tools/check_codes.py projects/mygame/exported/script.json
$PY  agt.py import  mygame && $PY agt.py package mygame                       # smoke build → 交使用者實機開啟
$PY  agt.py mark    mygame user_boot_ok                                       # 實機 OK 後

$PYT tools/translate.py -i projects/mygame/exported/script.json              # 大量翻譯（背景跑）
$PYT tools/fix_text.py … && $PY agt.py validate mygame && $PY agt.py check-codes mygame
$PY  agt.py import mygame && $PY agt.py verify mygame && $PY agt.py package mygame
ls projects/mygame/out/                               # 補丁 + 安裝說明.txt
```

兩站接力（實機端 Windows ↔ 翻譯端 dgxluna）：
```bash
# 實機端：gates 全綠 → 填 projects/mygame/HANDOFF.md → git commit && git push
python agt.py handoff pack mygame                     # #1 → 翻譯端（有 handoff_dir 會自動放進共用資料夾）
# 翻譯端：
git pull && $PY agt.py handoff unpack <交接包或資料夾>
$PYT tools/translate.py -i projects/mygame/exported/script.json --limit 20 --filter <開場>  # 之後 fix_text / check_codes / validate
$PY  agt.py handoff pack mygame                       # #2 → 實機端
# 實機端：unpack → import → verify → package → 裝進遊戲 → python agt.py playtest mygame → 使用者目視 → mark user_boot_ok → pack #3
# 翻譯端：大量翻譯 → fix_text → validate → check-codes → pack #4 → 實機端 import/verify/package → 交付
```

## 目錄

```
CLAUDE.md            Claude Code 操作手冊（站點與角色、環境規則、硬性關卡、交接協定、引擎辨識、決策樹、絕不導出清單）
agt.py               薄 CLI：env | engines | detect | init | prepare | roundtrip | export | validate | check-codes |
                     import | verify | breakage | package | gates | mark | status | handoff pack/unpack | playtest
core/                純標準庫共用函式庫（script.json、profile、控制碼把關、merge、roundtrip、adapter、registry、state、fsutil、site、handoff）
engines/<name>/      adapter.py、profile.json、NOTES.md、VENDOR.md、vendor/（原工具，不得修改）
engines/_template/   新引擎骨架；engines/bishop_bsx/ 只有指標
tools/               translate.py、fix_text.py、check_codes.py、playtest.py、llama_server.sh、setup_env.sh
docs/                workflow、two-site、engines、script-json、profile-schema、new-adapter、translation-quality、lessons-learned、templates/
config.yaml          dgxluna 的路徑（進 git）；config.local.yaml 每台機器自己的（不進 git）
projects/<game>/     每款遊戲的工作目錄（不進 git）
tests/               unittest（純標準庫）：$PY -m unittest discover -s tests
.claude/skills/      /new-game /identify-engine /new-adapter /start-translator /translate /deliver-patch /handoff
```

## 設定

`config.yaml`：GalTransl 位置、兩個直譯器路徑、llama-server 與模型路徑、endpoint、ctx／並行數／GPU。
`config.local.yaml`（不進 git）：這台機器的 `site`（workstation／translator）、`handoff_dir`（兩站共用的交接資料夾）、要覆蓋的路徑。環境變數 `GALTRANSL_ROOT`、`AGT_*` 再覆蓋。
不動 conda 環境；引擎需要套件時在 profile.json 宣告 `python_env` 並用 `tools/setup_env.sh <engine>` 建專用 venv；`engines/*/vendor/**` 不修改。

## 文件

- `CLAUDE.md` — 手冊
- `docs/workflow.md` — 關卡流程長版
- `docs/two-site.md` — 兩站接力：協定、交接包格式、Windows 首次設定、playtest
- `docs/engines.md` — 引擎知識庫
- `docs/script-json.md` — 共用文本格式
- `docs/profile-schema.md` — 引擎 profile 欄位
- `docs/new-adapter.md` — 新增引擎
- `docs/translation-quality.md` — 翻譯器會犯的錯與對策
- `docs/lessons-learned.md` — 跨引擎教訓
