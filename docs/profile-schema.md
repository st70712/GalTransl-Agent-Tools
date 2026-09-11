# `engines/<name>/profile.json` 欄位說明

profile 是每個引擎的**單一宣告來源**：`tools/translate.py`（優先級、跳過、前綴摘除）、`tools/fix_text.py`
（正則、符號表、換行政策）、`tools/check_codes.py`、`agt package`（補丁步驟）都從這裡讀。
任何以 `_` 開頭的鍵（`_doc`、`_symbol_map_doc`…）都是註解，`core/profile.py` 載入時忽略。
載入：`core.profile.load_profile("wolf_rpg")`（也接受別名與檔案路徑）。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | int | 目前 1 |
| `name` | str | 必須等於目錄名（`engines/<name>/`） |
| `display_name` | str | 顯示用 |
| `aliases` | list[str] | `load_profile()` 與 `--engine` 可用的別名（`wolf`、`rpgmaker`…） |
| `variants` | dict | 同引擎不同版本／分支。每個 variant 至少有 `source_encoding`、`target_encoding`；可加 `language_marker`、`exe`、`data_dir` 等引擎自訂鍵。`adapter.detect()` 決定 variant，寫進 `agt.json` 與 sidecar |
| `python_env` | dict | **選用**。vendor 腳本需要第三方套件時宣告：`venv`（相對 repo 根目錄，如 `.venv-unity`）、`requirements`（相對 `engines/<name>/`，預設 `requirements.txt`）、`python`（版本，uv 建 venv 用）。`bash tools/setup_env.sh <name>` 建立；`EngineAdapter` 看到就用該直譯器跑 vendor 腳本。沒宣告＝純標準庫，用 `config.yaml` 的 `python_stdlib` |
| `detection` | dict | 給 adapter 與文件參考的辨識線索：`files_any`（任一存在）、`globs_any`、`magic`（`{glob, offset, hex}`）、`negative_files`（存在就不是）、`evidence_files`（檔案→variant 提示）。adapter 可以只用其中一部分 |
| `contexts` | dict[str, obj] | 每個 context 一筆：`priority`（越小越先翻，預設 50）、`default`（`translate` 預設翻／`optional` 要 `--include-optional`／`skip` 不翻）、`risky`（翻錯會改變行為）、`requires_counterpart`（只有同原文也出現在其他 context 才翻，Wolf `condition`）、`description`、`reason`（為何 skip） |
| `control_codes.case_insensitive` | bool | RPG Maker 的 `\N[1]`／`\n[1]` 相同 → true |
| `control_codes.value_codes` | regex | **帶值**的碼（變數、角色名、Ruby 標註…）：少了或多了都 fatal，fix_text 會整條退回原文 |
| `control_codes.style_codes` | regex | **純表現**的碼（顏色、字級、等待、換行控制）：少了只警告 |
| `control_codes.leading_codes` | regex | 開頭連續控制碼；translate.py 送模型前摘除、翻完接回（Wolf 4076/4164 條對話以 `\E` 開頭）。RPG Maker 只摘 style 碼，`\N[1]` 是主詞不能摘 |
| `control_codes.stray_escape` | regex | 「反斜線序列」的長相，預設 `\\[A-Za-z]`；譯文裡出現原文沒有、又不是已知碼的序列 → fatal（`\EBADEND`→`\xEBADEND`） |
| `placeholders` | list[regex] | 執行期替換的佔位符（`%\d`），遺失視同帶值碼遺失 |
| `symbol_map` | dict[str,str] | 目標編碼收不到的字的替代（`ー→～`）。fix_text 在目標編碼是 utf-8 時自動關閉 |
| `literal_newline_policy` | enum | 譯文出現字面 `\n` 而原文沒有時：`revert`（fatal，退回）／`convert_if_original_lacks`（換成真換行，警告）／`keep` |
| `line_count_policy` | enum | 行數不同時：`warn`／`fatal`／`ignore`。Wolf 訊息框高度固定，行數變多會被截掉 |
| `japanese_detection` | str | 目前只有 `kana_or_kanji` |
| `never_export` | list[str] | 文件用：哪些字串即使是日文也不導出、為什麼。導出工具的規則要與此一致 |
| `patch.font` | str | 要換的字型名（Wolf：`Microsoft Yahei UI Bold`） |
| `patch.steps` | list[str] | `agt package` 的步驟名，由 adapter 解讀（Wolf：`restore_pristine_game_dat`、`set_language_marker`、`set_font`、`repack_from_original`、`write_install_notes`） |
| `patch.deliverables` | dict[variant, list] | 交付物清單，寫進安裝說明 |
| `acceptance_checklist` | list[str] | 實機驗收項目，寫進安裝說明 |
| `docs` | list[str] | 相關文件路徑 |

## 寫新 profile 的順序

1. 先從 `engines/_template/profile.json` 複製，每個欄位旁有 `_doc`。
2. `contexts`：先列導出工具實際會產生的 context 名稱；玩家看不到的設 `skip`，會改變行為的設 `optional` + `risky`。
3. `control_codes`：**精確列舉**，多字母碼排在單字母碼前（`cself` 在 `c` 前、`sp` 在 `s` 前），不要用 `\\[A-Za-z]+`。
   分清「帶值」與「純表現」——這決定 fix_text 退回還是只警告。
4. 用 `tests/test_core_codes.py` 的樣式寫幾個該引擎的案例：刪碼、改字母、寫死數字、雜字、字面 `\n`。
5. 若正則是從 vendored 腳本抄來的，在 `tests/test_profile.py` 加防漂移比對。
