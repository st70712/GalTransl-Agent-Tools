# GalTransl-RPGmaker

RPG Maker MV/MZ 遊戲翻譯工具集，用於提取和導入 RPG Maker 遊戲的可翻譯文本。

## 環境設置

```bash
# 從 environment.yaml 建立 conda 虛擬環境（推薦）
conda env create -f environment.yaml
conda activate galtransl

# 或手動創建最小環境
conda create -n galtransl python=3.11 -y
conda activate galtransl
```

## 工具說明

### 1. 腳本文本導出工具 (`export_script.py`)

從 RPG Maker 遊戲資料夾導出所有可翻譯文本到 JSON 格式。

**支援的文件類型：**
- 地圖事件 (Map*.json) - 對話、選項、事件名稱
- 公共事件 (CommonEvents.json) - 公共事件對話和選項
- 系統資料 (System.json) - 術語、選單文字、訊息
- 角色資料 (Actors.json) - 角色名稱、暱稱、簡介
- 技能、道具、武器、防具、敵人等資料庫檔案

```bash
# 啟用環境
conda activate galtransl

# 導出到單一 JSON 檔案
python export_script.py Game -o exported

# 分檔導出（按來源檔案分開）
python export_script.py Game -o exported -s
```

**命令參數：**
- `Game` - 遊戲資料夾路徑（包含 www/data 子資料夾）
- `-o, --output` - 輸出目錄（預設：exported）
- `-s, --split` - 按來源檔案分開輸出

**輸出檔案：**
- `script.json` - 可翻譯文本檔案
- `format_specification.json` - JSON 格式說明文件（供 AI 翻譯代理參考）

**輸出格式：**
```json
{
  "info": {
    "game_title": "遊戲標題",
    "version": "1.0",
    "string_count": 1234
  },
  "strings": [
    {
      "index": 0,
      "source_file": "Map001.json",
      "location": "Event1/Page0/Cmd5",
      "original": "原文文本",
      "translated": "",
      "context": "dialog",
      "speaker": "角色名",
      "code": 101
    }
  ]
}
```

**欄位說明：**
- `index` - 文本序號
- `source_file` - 來源檔案名稱
- `location` - 在來源檔案中的位置
- `original` - 原始文本
- `translated` - 翻譯文本（編輯此欄位）
- `context` - 文本類型（dialog、choice、name 等）
- `speaker` - 說話者（如有）
- `code` - RPG Maker 事件指令代碼

### 2. 腳本文本導入工具 (`import_script.py`)

將翻譯後的 JSON 文本導入回遊戲資料。

```bash
# 啟用環境
conda activate galtransl

# 驗證翻譯進度
python import_script.py validate exported/script.json

# 驗證並將未翻譯文本（預設 dialog、choice）輸出為獨立 JSON
python import_script.py validate exported/script.json -u exported/untranslated.json

# 指定要輸出的 context 類型（可多個，空格分隔）
python import_script.py validate exported/script.json -u exported/untranslated.json -c dialog choice message

# 輸出所有 context 的未翻譯文本
python import_script.py validate exported/script.json -u exported/untranslated.json -c all

# 導入翻譯（會自動備份原始檔案到 Game/backup）
python import_script.py import Game exported/script.json

# 導入到新目錄（不修改原始遊戲）
python import_script.py import Game exported/script.json -o Game_translated

# 導入後跳過結構驗證
python import_script.py import Game exported/script.json -o Game_translated --no-verify

# 不創建備份（不建議）
python import_script.py import Game exported/script.json --no-backup

# 單獨執行結構驗證（比較原始與翻譯後的遊戲資料）
python import_script.py verify Game Game_translated
```

**validate 命令：**
驗證翻譯進度，顯示各類型和各檔案的翻譯完成度。

使用 `-u OUTPUT_JSON` 可將未翻譯的條目匯出為獨立 JSON 檔案，方便手動翻譯後再以 `import` 指令導入。搭配 `-c CONTEXT [CONTEXT ...]` 可篩選要匯出的文本類型，預設為 `dialog choice`；傳入 `all` 可匯出所有類型。

**validate 命令參數：**
- `translation` - 翻譯 JSON 檔案或目錄
- `-u, --output-untranslated OUTPUT_JSON` - 將未翻譯條目輸出至指定 JSON 檔案
- `-c, --context CONTEXT [CONTEXT ...]` - 篩選輸出的 context 類型（預設：`dialog choice`；傳入 `all` 表示不篩選）

**verify 命令：**
比對原始遊戲資料與翻譯後遊戲資料的結構完整性，檢查是否存在會影響遊戲運行的問題。

檢查項目包括：
- 事件指令順序與代碼是否一致
- Show Picture 圖片名稱是否被對話文字污染
- Show Choices 選項數量是否一致
- 資料庫檔案的不可翻譯欄位是否被意外修改
- System.json 結構完整性

**verify 命令參數：**
- `Game` - 原始遊戲資料夾
- `Game_translated` - 翻譯後的遊戲資料夾

**import 命令參數：**
- `Game` - 原始遊戲資料夾
- `exported/script.json` - 翻譯 JSON 檔案或目錄
- `-o, --output` - 輸出到新目錄（預設：覆蓋原始檔案）
- `--no-backup` - 不創建備份
- `--no-verify` - 導入後跳過結構驗證（預設會自動驗證）

### 3. Demo 資料生成工具 (`make_demo_data.py`)

將 `Game/www/data/` 下的所有 JSON 遊戲資料中的實際文本替換為展示用範例文本，僅保留 RPG Maker 的資料結構，用於生成可公開發布的示範資料集。

```bash
conda activate galtransl
python make_demo_data.py
```

執行後會直接覆寫 `Game/www/data/` 中所有 JSON 檔案，因此**請務必在執行前先備份原始資料**。

**替換範圍：**

| 來源 | 替換內容 |
|------|----------|
| 地圖事件對話 (code 401) | `[Demo Dialog N] Hello, traveler. This is a sample line.` |
| 選項文字 (code 102) | `Choice 1`, `Choice 2`, ... |
| Show Picture 圖片名 (code 231) | `demo_picture` |
| Plugin Command 參數 (code 356) | 保留指令前綴，參數改為 `demo_arg` |
| 開發者備注 (code 108/408) | `[demo comment]` |
| `System.json` 遊戲標題 / 術語 / 選單 | 標準英文名稱 (Demo Game / HP / Fight / ...) |
| `System.json` 變數 / 開關名稱 | `Variable001`, `Switch001`, ... |
| `Actors.json` 角色名 / 暱稱 / 簡介 | Hero, Heroine, Warrior, Mage, ... |
| 資料庫 (武器/防具/技能/道具/敵人等) | `Weapon 1`, `Skill 1`, `Demo description for ...` |
| `MapInfos.json` 地圖名稱 | `Map001`, `Map002`, ... |
| `Animations.json` / `Tilesets.json` | 純技術資料，不含文字，略過 |

執行完畢後建議重新執行 `export_script.py` 以讓 `exported/script.json` 與 demo 資料同步：

```bash
conda activate galtransl && python export_script.py Game -o exported
```

## 翻譯工作流程

### 步驟 1：導出文本

```bash
conda activate galtransl
python export_script.py Game -o translation
```

這會在 `translation` 資料夾中生成 `script.json` 檔案。

### 步驟 2：翻譯

編輯 `translation/script.json`，在每個條目的 `translated` 欄位填入翻譯文本：

```json
{
  "index": 0,
  "source_file": "Map001.json",
  "location": "Event1/Page0/Cmd5",
  "original": "こんにちは、旅の人よ。",
  "translated": "你好，旅人。",  // ← 填入翻譯
  "context": "dialog",
  "speaker": "村人A"
}
```

**翻譯提示：**
- 保留控制碼（如 `\n`、`\\N[1]`、`\\V[2]` 等）
- 對於選項 (choice)，可能包含條件判斷（如 `if(s[xxx])`），翻譯時保留這些條件
- 多行對話以 `\n` 分隔

### 步驟 3：驗證進度

```bash
python import_script.py validate translation/script.json
```

輸出範例：
```
=== Translation Validation ===
Total strings: 1234
Translated: 567
Untranslated: 667
Progress: 45.9%

By context:
  dialog: 400/800 (50.0%)
  choice: 100/200 (50.0%)
  name: 50/100 (50.0%)
  ...

By file:
  Map001.json: 200/400 (50.0%)
  CommonEvents.json: 150/300 (50.0%)
  ...

已將 500 條未翻譯文本輸出至: exported/untranslated.json
  (context 篩選: dialog、choice)
請填寫各條目的 translated 欄位後，使用 import 指令導入。
```

匯出的 `untranslated.json` 結構與 `script.json` 相同，填妥 `translated` 欄位後可直接呼叫 `import` 指令合併回遊戲。

### 步驟 4：導入翻譯

```bash
# 覆蓋原始遊戲（自動備份）
python import_script.py import Game translation/script.json

# 或輸出到新目錄
python import_script.py import Game translation/script.json -o Game_CN
```

導入完成後會自動執行結構驗證，確保翻譯後的資料不會導致遊戲運行錯誤。如果驗證發現問題，會顯示詳細的錯誤報告。

### 步驟 5：結構驗證（可選）

如需單獨對已翻譯的遊戲資料進行結構驗證：

```bash
python import_script.py verify Game Game_CN
```

輸出範例：
```
=== Structural Verification ===
Files checked: 5
Errors: 0
Warnings: 0

✓ No structural issues found. Translation is safe for gameplay.
```

### 步驟 6：測試遊戲

將 `Game_translated/www/data/` 中的翻譯後 JSON 檔案複製回完整的遊戲安裝目錄，啟動遊戲進行測試，確認翻譯正確顯示。

> **注意**：本 repository 中的 `Game/` 資料夾為**功能展示用的最小範例**，僅包含 `www/data/` 遊戲資料 JSON，不含遊戲執行檔及素材資源，無法直接執行遊戲。

## 文本類型說明

| Context | 說明 | 範例 |
|---------|------|------|
| dialog | 對話文本 | NPC 對話、劇情文字 |
| choice | 選項文本 | 選擇分支選項 |
| scroll_text | 滾動文字 | 序章、結局等滾動文字 |
| map_name | 地圖名稱 | 地圖顯示名稱 |
| event_name | 事件名稱 | 事件編輯器中的名稱 |
| common_event_name | 公共事件名稱 | 公共事件名稱 |
| game_title | 遊戲標題 | 標題畫面顯示 |
| term | 術語 | 等級、HP、MP 等 |
| command | 指令 | 戰鬥、道具、裝備等選單 |
| message | 訊息 | 系統訊息模板 |
| actor | 角色 | 角色名稱、暱稱、簡介 |
| skill | 技能 | 技能名稱、說明 |
| item | 道具 | 道具名稱、說明 |
| weapon | 武器 | 武器名稱、說明 |
| armor | 防具 | 防具名稱、說明 |
| enemy | 敵人 | 敵人名稱 |
| state | 狀態 | 狀態名稱、訊息 |

## 注意事項

1. **備份原始遊戲**：對真實遊戲進行導入時，建議手動複製一份原始 `data/` 目錄作為備份。本 repository 的 `Game/` 為展示用最小範例，只含 `www/data/`，不包含遊戲執行檔。

2. **字元編碼**：確保使用 UTF-8 編碼編輯 JSON 檔案。

3. **JSON 格式**：編輯時注意保持有效的 JSON 格式，建議使用支援 JSON 的編輯器。

4. **特殊字元**：
   - `\\` - 反斜線（跳脫字元）
   - `\n` - 換行
   - `\\N[n]` - 第 n 號角色名稱
   - `\\V[n]` - 第 n 號變數值
   - `\\G` - 貨幣單位
   - `\\C[n]` - 顏色代碼

5. **翻譯長度**：注意翻譯後的文字長度，過長可能導致顯示問題。

## 目錄結構

```
GalTransl-RPGmaker/
├── export_script.py    # 文本導出工具
├── import_script.py    # 文本導入工具
├── make_demo_data.py   # 展示用 Demo 資料生成工具
├── environment.yaml    # Conda 環境定義檔
├── README.md           # 本說明文件
├── Game/               # 範例遊戲資料（僅含 www/data/，供功能展示用）
│   └── www/
│       └── data/       # 遊戲資料 JSON 檔案
│           ├── Map001.json
│           ├── CommonEvents.json
│           ├── System.json
│           └── ...
├── exported/           # 導出的翻譯檔案
│   ├── script.json              # 可翻譯文本
│   └── format_specification.json # 格式說明（AI 代理參考）
└── Game_translated/    # 導入翻譯後的輸出目錄
    └── www/
        └── data/       # 翻譯後的遊戲資料 JSON 檔案
```

## 格式說明文件

導出時會自動生成 `format_specification.json`，內容包含：

- **file_structure** - 檔案結構說明
- **strings_array_fields** - 每個欄位的詳細定義
- **translation_examples** - 翻譯範例
- **ai_agent_guidelines** - AI 翻譯代理指南

此文件可供 AI 翻譯代理讀取，以了解如何正確處理翻譯任務。

## 常見問題

### Q: 導出時沒有任何文本？
A: 確認遊戲資料夾結構正確，應包含 `www/data` 子目錄。

### Q: 導入後遊戲無法啟動？
A: 檢查 JSON 檔案格式是否正確。可以使用 `Game/backup` 中的備份還原。也可執行 `python import_script.py verify Game Game_translated` 檢查結構問題。

### Q: 遊戲顯示「Loading Error Failed to load: img/pictures/...」？
A: 可能是翻譯文字被錯誤寫入了圖片名稱欄位。執行 `python import_script.py verify Game Game_translated` 可以檢測此類問題。導入時的自動結構驗證也會攔截此錯誤。

### Q: 某些文本沒有被導出？
A: 工具會過濾純控制碼和系統字串。如需翻譯特定內容，可修改 `is_translatable_text()` 函數。

### Q: 如何只翻譯特定檔案？
A: 使用 `-s` 參數分檔導出，然後只翻譯需要的檔案。
