# wolf_rpg — WOLF RPG Editor（ウディタ）

工具鏈來自 `GalTransl-sister`（`vendor/`），已在 RJ338582 試玩版（2.281）與正式版 1.4.5（3.173）通過實機驗證。
完整說明在 `vendor/README.md`；本檔是操作時要記得的重點。

## 辨識特徵

| | 2.x | 3.x |
|---|---|---|
| 執行檔 | `Game.exe`（DX Library；`strings` 有 `This game data is the %s version…`、`Chinese (Traditional)`） | `GamePro.exe` |
| 封包 | 單一 `Data.wolf`，DXA v8，開頭 `DX`，金鑰 `Wolf RPG v2.281` | `Data/` 下 ~20 個 `.wolf`（含文字的只有 `BasicData.wolf` 149 檔、`MapData.wolf` 9 檔），金鑰 `Wolf RPG v3.173` |
| 封包內路徑 | `BasicData/…`、`MapData/…` | **檔案在封包根目錄**，`extract_wolf.py` 的 `TEXT_DIRS` 前綴過濾會一條都不 match，要分兩包解並加 `--all` |
| 字串編碼 | CP932 | **UTF-8** |
| 補丁編碼 | CP950 + 語言標記 | UTF-8，語言標記不動 |

`extract_wolf.py --list` 會印出偵測到的金鑰版本；金鑰偵測失敗可 `--key` 指定。DXA Ver6（官方舊版漢化）只有解密邏輯。

## 資料格式

- `wolfrpg/`：自製解析器（移植自 WolfDec / wolftrans / WolfTL）。`filecoder.py` 字串保持 raw bytes，只在導出 decode、導入 encode；`textio.py` 的 `Slot` 游標讓導出與導入走同一個走訪，位址由構造保證一致。
- 位址：`Ev{i}/Pg{j}/Cmd{k}/Str{n}`（地圖）、`CEv{i}/Cmd{k}/Str{n}`（公共事件）、`Type{t}/Data{d}/Field{f}`（資料庫）、`title`（Game.dat）。
- 2.x/3.x 差異：magic 內的 `0x55` 版本標記、map `unknown2` 0x65→0x66、無圖塊地圖存 `ff ff ff ff` 哨兵、公共事件引數區「magic」其實是長度前綴（10→11）、DB 版本 0xC1→0xC2、`Game.dat` 設定陣列 22→35 格、版本字串後的 int 從檔案長度變固定 `0x14`。原則：**讀到什麼版本寫回什麼版本**（`verify_variant()`），不 fork。
- `SysDataBaseBasic.project` 不處理（格式不同、無玩家可見文字）；Wolf 3.5+ 的 `.mps/.dat` 另有壓縮層，工具會明確報錯。
- 往返：`roundtrip_test.py Data` 17/17（9 張 `.mps` + `CommonEvent.dat` + 3 組 DB `.project/.dat` + `Game.dat`）。

## 絕不導出

素材路徑（`looks_like_path()`）、`SetLabel/JumpLabel`（212/213）、`CommonEventByName`（300）的 **Str0**（事件名；Str1 之後是引數要翻）、地圖事件名／公共事件名、開發者註解（103）、資料庫非字串欄位、`SysDataBaseBasic`。
`game_title` 導出但**不翻**（改長度）。`FLOW_CRITICAL_ARGS = {212: all, 213: all, 300: Str0}`。

context：`dialog`(101) `choice`(102) `picture_text`(150, picture_type==2) `call_arg`(210/300) `database` `debug`(106) `game_title` | 會改變行為：`string_var`(122) `condition`(112)。

## 控制碼

帶值（少了整條退回）：`\cself[n] \self[n] \cdb[..] \udb[..] \sdb[..] \v[n] \r[漢字,假名]`。
純表現（少了只警告）：`\space[] \font[] \sp[n] \ax[] \ay[] \c[n] \f[n] \s[] \E` 與單字元 `\> \< \. \! \^ \- \|`。
精確列舉，多字母排前面（`\cself[8]` 不能被切成 `\c`、`\EBADEND` 不能把內文吃掉）。
4076/4164 條對話以 `\E` 開頭 → translate.py 摘除前綴再接回。訊息框高度固定，行數不能變多。
原文有 4 條台詞用字面 `\n`，所以「認不得的序列」要扣掉原文用過的。

## 補丁步驟（`agt package`，profile `patch.steps`）

1. `restore_pristine_game_dat`：`translated/Data/BasicData/Game.dat` **用回原始檔**（import 重新序列化的那份長度會變）。
2. `set_language_marker`：只有 2.x：`set_game_lang.py … --lang zh-tw`（位移 31 = 3；1 日／2 韓／3 繁／4 簡）。3.x 不動（UTF-8 沒字碼頁可選）。
3. `set_font`：`set_font.py … --font "Microsoft Yahei UI Bold"`（NUL 補滿原欄位；使用者偏好 Yahei，JhengHei 亦可）。內建字型缺 39～55 個常用漢字（說、內、每、戶、黃…）。**前後長度必須「未改變」**。
4. `repack_from_original`：`repack_wolf.py <原始封包> translated/Data -o out/<name>.wolf`，2.x 一包、3.x `BasicData.wolf` + `MapData.wolf` 各一。未變動檔案原位元組連位移照抄，變動檔案 Huffman，標頭 LZ+Huffman，與原封包一致；打包後自動解開逐檔比對。**每次從原始封包出發。**
5. `write_install_notes`：`out/安裝說明.txt`。2.x 補丁還需要對未翻譯字串做 Big5 轉碼（import 預設做；`--no-transcode` 只給 3.x）。

驗證：`validate -e <enc>` 五項（可編碼、控制碼、condition 一致性、未翻譯但玩家看得到、會變亂碼）；`verify` 結構（指令數／ID／縮排／整數參數、圖片檔名污染、標籤、選項數、地圖尺寸、DB 欄位）。

## 踩過的坑

1. **散檔不生效，一定要重新打包**。`Game.exe` 只讀 `Data.wolf`，封包移走無法啟動；Wolf 沒呼叫 `SetDXArchivePriority`。
2. **新封包要用與原封包相同的儲存形式**。原封包 2019 Huffman + 46 LZ+Huffman + 0 未壓縮；用了未壓縮＋`NO_HEAD_PRESS` 遊戲開不起來。先統計再做。
3. **`Game.dat` 總長度絕對不能變**。翻視窗標題少 10 bytes 就開不起來。所有修改都是不改長度的原地覆蓋；不要用 import 重新序列化的 `Game.dat`。
4. **翻譯記憶從第一輪就開**。中途才開留下 575 種原文多譯法（`はい` 4 種），`condition` 兩邊不同 → 分支永遠不觸發。
5. **統一譯法優先選控制碼完整的版本**（取最常見會讓掉碼從 52 變 76 條；改後 3 條）。
6. **未翻譯的文字也要轉碼**（2.x）。設了語言標記後引擎用 Big5 讀全部文字，連「……。」都變方框；`textnorm.py` 處理半形假名、Big5 缺字、新字體→正體、國字近義。
7. **流程控制指令的字串參數可能是顯示文字**。名字牌是 cid 210 的 Str1（999 條）；整個排除會讓人名全消失。cid 300 只排除 Str0。`verify` 粒度也要跟著到參數層級。
8. **改了導出規則用 `--merge` 接續**（以 `(source_file, location)` 對應；本專案由 `agt export --merge` 做）。跨版本要用原文為鍵（`merge_by_text.py` / `core.merge.by_text`）。
9. **官方漢化版是最好的對照組**。語言標記是拿官方繁中版 RJ352237 的 `Game.dat` 逐欄 diff 出來的（DXA Ver6，金鑰用已知明文反推：`c7 05 ca 7d 8d e3 de f1 d9 0c 85 f4`）。
10. 3.x 下 `fix_cp950.py` 的符號表（`ー→～`）全是 Big5 代打，UTF-8 要關掉（fix_text 自動）。
11. 模型在 `\E` 裡插雜字（`\EBADEND`→`\xEBADEND`）；「認不得的序列一律退回」但要扣掉原文本身用的字面 `\n`。
12. 跨版本沿用譯文時，翻譯記憶擴散可能把 `\cself[9]` 帶進本來沒變數的句子——**多出來的帶值碼也要擋**。

## 實機驗收

- 遊戲開得起來（`GamePro.exe` + DXA 打包是 3.x 的最大未知數，smoke build 先驗）
- 對話、選項顯示中文不是方框；訊息框沒被撐爆
- **對話框上方名字牌有人名**（父親／妹妹／悠香梨）
- 純符號台詞（`……。`）正常
- 字型無缺字（Yahei）
- 會做字串比對的分支（難度選擇／裝備／道具使用）仍能觸發
- 不確定語言標記時出 A（不動）／B（設 3）兩版

成果：試玩版 7363/9224（79.8%）、0 亂碼、13 條刻意保留日文；正式版 19082/22768（83.8%）、22 條玩家可見未翻、0 條重複譯法需統一、封包變動 8 檔。
