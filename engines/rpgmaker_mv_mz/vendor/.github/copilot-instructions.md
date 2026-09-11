# GitHub Copilot Instructions for GalTransl-RPGmaker

這個專案用於將 RPG Maker MV/MZ 遊戲中的文本提取和重新打包。以下是一些關於如何使用這個專案的指導說明。

## 環境要求

在此專案中執行任何 Python 命令之前，**必須**先啟動 `galtransl` conda 虛擬環境。

### 終端機命令規則

1. **在執行 Python 腳本前，務必先啟動環境：**
   ```bash
   conda activate galtransl
   ```

2. **或使用單行命令格式：**
   ```bash
   conda activate galtransl && python <script.py>
   ```
   這樣可以確保在執行 Python 腳本前，環境已經正確啟動。

3. **安裝新的 Python 套件後，必須同步更新 `environment.yaml`：**
   ```bash
   conda activate galtransl && conda env export --no-builds | grep -v '^prefix:' > environment.yaml
   ```
   任何透過 `conda install` 或 `pip install` 安裝的套件都必須執行此步驟，以確保環境定義檔保持最新。

## 主要工具

### 導出工具 (export_script.py)
```bash
conda activate galtransl && python export_script.py Game -o exported
```

### 導入工具 (import_script.py)
```bash
# 驗證翻譯進度
conda activate galtransl && python import_script.py validate exported/script.json

# 導入翻譯（導入後自動執行結構驗證）
conda activate galtransl && python import_script.py import Game exported/script.json -o Game_translated

# 導入翻譯（跳過結構驗證）
conda activate galtransl && python import_script.py import Game exported/script.json -o Game_translated --no-verify

# 單獨執行結構驗證（比較原始與翻譯後遊戲資料的結構完整性）
conda activate galtransl && python import_script.py verify Game Game_translated
```

### 輸出檔 JSON 結構
輸出檔的 JSON 結構如下所示：

```json
{
  "info": {
    "game_title": "遊戲標題",
    "version": "1.0",
    "string_count": 2449
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

### 文本類型 (context)
- `dialog` - 對話文本
- `choice` - 選項文本
- `picture_name` - 圖片名稱（可能包含文字）
- `common_event_name` - 公共事件名稱
- `game_title` - 遊戲標題
- `term` - 術語
- `command` - 選單指令
- `message` - 系統訊息
- `actor` / `skill` / `item` / `weapon` / `armor` / `enemy` / `state` - 資料庫項目