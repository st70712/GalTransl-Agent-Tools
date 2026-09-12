# 翻譯品質：翻譯器會犯的錯與對策

本機模型是 `Sakura-GalTransl-14B-v3.8`（llama-server，`http://127.0.0.1:8080/v1`，模型型別 `galtransl-v3`），
透過 GalTransl 框架的 `CSakuraTranslate` 呼叫（`GALTRANSL_ROOT`）。它翻得不錯，但會**系統性**破壞控制碼；
結構驗證（verify）抓不到這類問題，所以導入前一定要過 `tools/check_codes.py`。

## 失敗類型與對策

| 型態 | 例 | 誰抓 | 對策 |
|---|---|---|---|
| 帶值碼整個消失 | `セラに\v[61]ダメージ！` → `對塞拉造成了傷害！` | check_codes `lost_value` | fix_text 整條退回原文（寧可留日文也不讓變數壞掉） |
| 字母被改 | `\V[74]` → `\N[74]`（變數值→角色名） | `lost_value` + `extra_value` | 同上；RPG Maker 大小寫不分，所以 `\n[74]` 也是合法碼，靠「少一個 v、多一個 n」抓 |
| 數值寫死 | `\V[75]級` → `75級` | `lost_value` | 同上 |
| 碼裡插雜字 | `\EBADEND` → `\xEBADEND`（`\E` 失效） | `stray` | 退回原文；「認不得」會扣掉原文本身用過的序列（有 4 條台詞原文就用字面 `\n`） |
| 憑空造字面 `\n` | 原文真換行，譯文變 `\n` | `literal_newline` | 依 profile：RPG Maker `revert`；Wolf `convert_if_original_lacks`（換成真換行） |
| 行數不一致 | 兩行變一行／三行 | `line_count` | 警告；Wolf 訊息框高度固定，行數變多會被截掉 |
| 純表現碼遺失 | 掉 `\c[n]` 顏色 | `lost_style` | 只警告，接受（文字完整，少了強調色）；寫進安裝說明「已知小瑕疵」 |
| 翻譯記憶擴散帶進別句的變數 | `はい` → `\cself[9]是` | `extra_value` | 退回／跳過（merge_by_text 也擋） |
| 專有名詞不統一 | セラ → 塞拉／賽拉／賽菈／瑟拉 | 人工／統計 | 見下「術語一致性」 |
| 行數對不上（模型輸出） | 批次回傳行數 ≠ 輸入 | GalTransl 內建 | 自動縮批重試；5 次仍失敗留空（translate.py 會正確判斷 `(Failed)` 哨兵，不寫進譯文） |

## `tools/fix_text.py` 做什麼（順序固定）

1. opencc `s2twp` 簡→台灣繁體（控制碼先遮蔽進私用區再轉）
2. 符號表（profile `symbol_map`）：只在目標編碼是 Big5 時；utf-8 自動關閉
3. 統一重複原文的譯法：**優先選控制碼完整的版本**，不是最常見的（單純取最常見會把掉碼的版本擴散出去，52→76 條）
4. 字面 `\n` 政策
5. stray 退回原文
6. 帶值碼少了或多了 → 退回原文
7. 純表現碼少了 → 只報
8. 目標編碼可寫性檢查

寫檔前備份 `script.backup-<ts>.json`；`--dry-run` 只報不寫。

## 翻譯記憶（translate.py 預設開）

同一段原文只送模型一次，翻完擴散到所有相同原文的條目。省 ~40% 的量，更重要的是保證
Wolf `condition` 與其對應方（`string_var`／`database`／`choice`）被翻成完全相同的字串，比較才不會失效。
**從第一輪就要開**：中途才開會留下 575 種原文多版譯法（`はい` 4 種），事後統一還會踩到掉碼版本。

## 術語表（glossary）

- `projects/<game>/glossary.txt` 存在就自動載入（**只在專案佈局下**：`-i projects/<game>/exported/script.json`）；
  或 `--dict FILE...`。格式：
  ```
  さくら->櫻#女主角
  白鷺学園->白鷺學園
  ```
- **備註符號是 `#`，不是 `//`。** 解析器（`GalTransl/Dictionary.py`）只做三件事：
  把四個空格換成 TAB、`->` 與 `#` 都換成 TAB、然後用 TAB 切開取前三欄（原文／譯文／備註）。所以：
  - `さくら->櫻 // 女主角` 的譯文會變成 `櫻 // 女主角`，整串註解被當成翻譯目標塞進 prompt。
  - `#` 前面不要留空格，否則譯文結尾多一個空格。
  - 少於兩欄的行會被跳過，所以 `#` 開頭的純註解行安全——但**該行不能含 `->`**，否則會被解析成
    一條 `search_word` 為空字串的條目，而空字串比對到任何文字，每個批次都會被塞進 prompt。
  - 寫完用 `CGptDict` 載入一次印出 `replace_word` 確認乾淨；RJ01657316 是第一個真的用到自動載入的專案，
    就是這樣踩到的。
- 透過 GalTransl 的 `CGptDict.gen_prompt(type="sakura")` 塞進 prompt 的 `[Glossary]`。
- 通用字典在 `/raid/home/jimhsieh/GalTransl/Dict/`（`GPT字典.txt`、`00通用字典_译前` 等），需要時挑用。
- 做法：先跑小樣本，把模型翻不穩的人名挑出來寫進 glossary，再大量翻。

## 術語一致性（事後統一）

1. 統計同一原文的譯法分布；同一個假名人名翻成多種時列出。
2. 取代前先確認來源沒有同形近似的其他角色名。
3. **注意中文跨詞邊界誤命中**：「比賽拉開序幕」含「賽拉」——全域取代要帶上下文檢查，或只在含該人名假名的原文對應的譯文裡取代。
4. 這類文本高度樣板化（188 條只有 9 種句型），依句型機械修復即可，不需重譯。

## 跨版本沿用譯文

`core/merge.by_text()`：以原文字串為鍵（位置會全變），原文完全相同才套、帶值碼不能少也不能多、`condition` 孤兒不套、`game_title` 不套。
上次試玩版→正式版接續 10250 條（45%），人名／道具名／選項因此與已實機驗證的版本一致。


## 字型缺字（fix_text 的字元集檢查）

遊戲字型的字元集存成 `projects/<game>/font_charset.txt`（每個字一個字元；Unity 用 fonttools 讀內嵌 OTF 的 cmap，
Wolf 用 cp950 可編碼集，TMP 靜態圖集用字元表），`tools/fix_text.py` 在專案佈局下會自動載入：
不在字元集裡的字 → 先查 `projects/<game>/charset_map.json`（人工替字，如 `嗯→恩`）→ 再試 opencc `t2jp`
（繁→日文字形：值→値、啟→啓、鄉→郷）→ 都不行就列出來（遊戲裡會是 □）給人補進替字表。
`--charset`／`--charset-map` 可手動指定，`--no-charset` 關閉。

**`t2jp` 這條退路在 dgxluna 上實際不會生效**：nllb-env 的 opencc 沒有 `t2jp.json`，
`tools/fix_text.py` 的 `except Exception` 把 `FileNotFoundError` 吃掉，所以一律印 `t2jp 自動: 0 種`。
缺字只能靠 `charset_map.json` 人工補（現成的 `engines/unity_textasset/charsets/NotoSansJP-Regular.map.json`
已經帶了 啟→啓／值→値／鄉→郷／查→査）。看到 `t2jp 自動: 0 種` 不代表沒缺字，要看下面那段清單。

## 換行（真換行與 `\r\n`）

模型看不到真正的換行。`GalTransl/Backend/SakuraTranslate.py` 送出前把 `\r\n` 與 `\n` 都攤平成
**字面兩字元 `\n`**，回來後依原文用哪一種還原（原文有 `\r\n` 就還原成 `\r\n`，否則還原成 `\n`）。
本 repo 自己完全不處理 `\r`——`tools/translate.py`、`tools/fix_text.py`、`core/codes.py`
與 vendor 的 `import_script.py` 都只比 `count("\n")`，所以 CRLF 與 LF 的「行數」相同、**不會有任何警告**。

RJ01657316（原文 805 條真 `\r\n`）實測 20 條 smoke：CRLF 保留 16/16、行數 20/20 相同、
結尾單獨 `\n` 的 UI 標籤也保住。結論：**這條路可靠，不需要額外補 `\r`**。
但仍要每個專案量一次，因為模型多吐或少吐一個 `\n` 標記就會變成多一行或少一行（`line_count` 只警告）。
