# projects/

每款遊戲一個目錄，整個 `projects/` 不進 git（只有這個說明檔）。

```
projects/<game>/
├── original/     # 使用者提供的原始遊戲（symlink／Windows junction）。任何步驟不得寫入。翻譯端骨架專案沒有這個目錄。
├── extracted/    # 可解析的資料樹（解包結果；RPG Maker／Unity 是指向 original 的連結）
├── exported/     # script.json、format_specification.json、.agt.json（sidecar）、untranslated.json、.agt_checkpoint.json
├── translated/   # 導入譯文後的資料樹（純衍生物，每次 import 前整個重建）
├── out/          # 交付物：補丁檔 + 安裝說明.txt
├── handoff/      # 兩站接力的交接包 <game>-NNN-to-<site>-<時間>.zip（agt handoff pack 產生）
├── variants/     # A/B 變體，每個只差一件事
├── logs/         # 每個步驟的執行紀錄（會隨交接包走，兩站只增不刪）
├── glossary.txt  # （選用）GPT 字典，格式 `原文->譯文 // 備註`
├── font_charset.txt / charset_map.json   # （選用）遊戲字型字元集與替字表，fix_text 自動用
├── HANDOFF.md    # 跨機／跨對話交接備忘（範本 docs/templates/HANDOFF.template.md）；專案完結後刪
└── agt.json      # 引擎辨識結果、關卡狀態、handoff（seq／持棒方）（agt status 可看）
```

建立：`python agt.py init <game> --original <遊戲目錄>`（有遊戲檔的站點）或 `python agt.py handoff unpack <交接包>`（翻譯端骨架）。
兩站的專案名必須相同。交接包只帶 agt.json、exported/、glossary、字型字元集、HANDOFF.md、logs；original/ extracted/ translated/ out/ 永遠留在實機端。
