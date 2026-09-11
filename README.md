# GalTransl-Agent-Tools

Agent 驅動的遊戲中文化補丁工具箱。在 Claude Code 裡照 `CLAUDE.md` 操作：辨識引擎 → 沿用或新寫引擎轉接器 →
導出文本 → 本機 Sakura 模型翻譯 → 整理／檢查譯文 → 導入 → 打包 → 使用者實機驗收。

已支援：**RPG Maker MV/MZ**、**WOLF RPG Editor 2.x/3.x**（兩套工具原樣搬入自 GalTransl-RPGmaker 與 GalTransl-sister，通過實機驗證）。
其他引擎（Bishop、TyranoScript、KiriKiri、Unity、Ren'Py…）有線索與接入指引，見 `docs/engines.md`。

## 快速開始

```bash
PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python      # 純標準庫工具
PYT=/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python      # 翻譯／opencc

$PY agt.py detect <遊戲目錄>                          # 辨識引擎
$PY agt.py init  mygame --original <遊戲目錄>          # 建 projects/mygame/
$PY agt.py gates mygame                               # prepare → roundtrip → export → 零翻譯導入 → verify → breakage

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

## 目錄

```
CLAUDE.md            Claude Code 操作手冊（環境規則、硬性關卡、引擎辨識、決策樹、絕不導出清單）
agt.py               薄 CLI：engines | detect | init | prepare | roundtrip | export | validate | check-codes |
                     import | verify | breakage | package | gates | mark | status
core/                純標準庫共用函式庫（script.json、profile、控制碼把關、merge、roundtrip、adapter、registry、state）
engines/<name>/      adapter.py、profile.json、NOTES.md、VENDOR.md、vendor/（原工具，不得修改）
engines/_template/   新引擎骨架；engines/bishop_bsx/ 只有指標
tools/               translate.py、fix_text.py、check_codes.py、llama_server.sh
docs/                workflow、engines、script-json、profile-schema、new-adapter、translation-quality、lessons-learned、templates/
projects/<game>/     每款遊戲的工作目錄（不進 git）
tests/               unittest（純標準庫）：$PY -m unittest discover -s tests
.claude/skills/      /new-game /identify-engine /new-adapter /start-translator /translate /deliver-patch
```

## 設定

`config.yaml`：GalTransl 位置、兩個直譯器路徑、llama-server 與模型路徑、endpoint、ctx／並行數／GPU。環境變數 `GALTRANSL_ROOT`、`AGT_*` 可覆蓋。
不新建 conda 環境、不 pip install；`engines/*/vendor/**` 不修改。

## 文件

- `CLAUDE.md` — 手冊
- `docs/workflow.md` — 關卡流程長版
- `docs/engines.md` — 引擎知識庫
- `docs/script-json.md` — 共用文本格式
- `docs/profile-schema.md` — 引擎 profile 欄位
- `docs/new-adapter.md` — 新增引擎
- `docs/translation-quality.md` — 翻譯器會犯的錯與對策
- `docs/lessons-learned.md` — 跨引擎教訓
