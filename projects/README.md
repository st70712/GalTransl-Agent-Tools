# projects/

每款遊戲一個目錄，整個 `projects/` 不進 git（只有這個說明檔）。

```
projects/<game>/
├── original/     # 使用者提供的原始遊戲（可為 symlink）。任何步驟不得寫入。
├── extracted/    # 可解析的資料樹（解包結果；RPG Maker 是指向 original 的 symlink）
├── exported/     # script.json、format_specification.json、.agt.json（sidecar）、untranslated.json
├── translated/   # 導入譯文後的資料樹（純衍生物，每次 import 前整個重建）
├── out/          # 交付物：補丁檔 + 安裝說明.txt
├── logs/         # 每個步驟的執行紀錄
├── glossary.txt  # （選用）GPT 字典，格式 `原文->譯文 // 備註`
└── agt.json      # 引擎辨識結果與關卡狀態（agt status 可看）
```

建立：`python agt.py init <game> --original <遊戲目錄>`
