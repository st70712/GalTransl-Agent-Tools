---
name: new-adapter
description: 遇到沒有轉接器的遊戲引擎時，從 engines/_template 依固定順序建立新的 export/import 工具與 adapter，每一步都用 agt 關卡驗收。
---

# /new-adapter

## 觸發
`/identify-engine` 確認引擎不在 `engines/` 裡，或既有轉接器對這款遊戲無法沿用且差異太大。**在有遊戲檔的站點做**（實機端或單機）。

## 輸入
- 引擎名（小寫底線，如 `kirikiri`）、一款樣本遊戲的專案（`projects/<game>/`）。

## 步驟（順序不能跳，詳見 `docs/new-adapter.md`）
```bash
cp -r engines/_template engines/<engine>     # adapter.py / profile.json / NOTES.md / vendor/ 骨架；$PY 見 CLAUDE.md §3
```
1. **解包**：能把封包解成檔案樹，並用檔頭 magic 驗證每個檔案；記下儲存形式分布。
2. **解析**：寫格式解析器，字串以 raw bytes 保留，只在導出時 decode。
3. **往返驗證**：`vendor/roundtrip_test.py DATA` 解析→寫回逐位元組相同。**沒全過不准往下。**
4. **導出**：`vendor/export_script.py DATA -o OUT [-e ENC]` 產出 `script.json`＋`format_specification.json`；一個共用的 slot 走訪讓導出與導入位址一致。
5. **零翻譯導入**：`vendor/import_script.py import DATA SCRIPT -o OUT` 輸出必須與原資料相同。
6. **verify + 破壞攔截**：`import_script.py verify DATA OUT`；在 `adapter.breakage_test` 刻意弄壞（標籤、檔名、選項數），verify 必須失敗。
7. **profile.json**：contexts 優先級／預設政策、控制碼 value/style/leading 正則、never_export、patch 步驟；需要第三方套件就宣告 `python_env` + `requirements.txt`（`setup_env.sh` 建，Windows 也要能建）。
8. **adapter.py**：繼承 `StandardCliAdapter`，實作 `detect / prepare / package / breakage_test`；資料樹不在根目錄就覆寫 `data_dir()`，要傳編碼就覆寫 `encoding_args()`；`prepare` 建連結用 `core.fsutil.replace_dir_with_link`（別直接 `symlink_to`，Windows 會炸）。
9. `$PY agt.py gates <game>` 全綠 → smoke build 交使用者實機 → 才大量翻譯。兩站流程：**新 adapter 要 commit + push 才 `/handoff`**，翻譯端 pull 後 validate／check-codes 才用得到新 profile。
10. 寫 `NOTES.md`（固定標題）、`VENDOR.md`（來源／md5）、把引擎加進 `docs/engines.md`。

## 輸出
- `engines/<engine>/` 完整，`tests/` 若有示範資料則加一個往返測試。

## 停下來問使用者
- 封包格式沒有公開資料、需要官方多語版本或原始遊戲不同版本來對照時。
- 每個 smoke build。
