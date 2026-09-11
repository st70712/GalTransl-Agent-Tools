# 工作流程（CLAUDE.md 第 4 節的長版）

每一關對應 `agt.py` 的一個子命令；狀態寫在 `projects/<game>/agt.json`，`agt status GAME` 可看。
所有步驟都印出底層 vendored 指令，可直接複製到 shell 重跑；輸出同時寫進 `projects/<game>/logs/`。

```bash
PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python     # 純標準庫工具
PYT=/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python     # translate.py / fix_text.py
```

## G0 辨識引擎

```bash
$PY agt.py detect <遊戲目錄>
$PY agt.py init <game> --original <遊戲目錄> [--engine NAME] [--variant V]
```

`detect` 對每個引擎跑 `adapter.detect()`，列出信心與證據；≥0.5 才算辨識成功。
第一個假設常常是錯的（使用者說 RPG Maker，資料是 Wolf），以資料為準。辨識不出來走 `/identify-engine`；沒有轉接器走 `/new-adapter`。

## G1 prepare 後先量測

```bash
$PY agt.py prepare <game>
```

解包或定位資料樹到 `extracted/`。**接著量測，不要猜**：
- 封包內各種儲存形式（未壓縮／Huffman／LZ）的分布——打包時要照原樣（Wolf 踩坑 2）
- 檔案數、含文字的檔案有哪些、字串總數
- 各 context 的分布；抽幾條看內容是不是玩家看得到的文字

## G2 往返驗證

```bash
$PY agt.py roundtrip <game>
```

解析 → 寫回 → 比對。二進位格式要逐位元組相同（Wolf 17/17）；JSON 格式用 `json.load` 相等（RPG Maker）。
**格式理解只要有一處在猜，這一步就會抓到。** 沒全過不准動文字。

## G3 導出並抽樣

```bash
$PY agt.py export <game> [--merge PREV.json]
```

產出 `exported/script.json`、`format_specification.json`、`.agt.json`（sidecar：引擎、variant、來源／目標編碼、字串數）。
抽樣核對 `CLAUDE.md` 第 7 節「絕不導出」清單，也反過來確認**顯示文字沒有漏**（名字牌、傳給公共事件的引數）。
改了導出規則要重新導出時，先備份 `script.json`，再用 `--merge` 以 `(source_file, location)` 接續舊譯文。

## G4 零翻譯導入 + verify

`gates` 會自動跑：把 `translated` 全清空導入到暫存目錄，輸出必須與 `extracted/` 相同；再跑

```bash
$PY agt.py verify <game>
```

結構驗證只看「不該變的東西有沒有變」：指令數／ID／縮排／整數參數、標籤、檔名、選項數、地圖尺寸、資料庫欄位。

## G5 破壞攔截

```bash
$PY agt.py breakage <game>
```

刻意弄壞一份複本（圖片檔名塞日文、刪一個選項、改一個跳躍標籤），verify **必須失敗**。這是在測安全網本身。

## G6 Smoke build → 等實機

```bash
$PYT tools/translate.py -i projects/<game>/exported/script.json --limit 20
$PYT tools/fix_text.py   projects/<game>/exported/script.json
$PY  tools/check_codes.py projects/<game>/exported/script.json
$PY  agt.py import  <game>
$PY  agt.py package <game>
```

交 `out/` 給使用者實機開啟。他回報 OK 後：`$PY agt.py mark <game> user_boot_ok`。
上一次幾乎每個坑都是「翻完才發現」；這 20 分鐘的 smoke build 能省下數小時。

## G7 大量翻譯

```bash
$PYT tools/translate.py -i projects/<game>/exported/script.json --log projects/<game>/logs/translate.log
```

用 `run_in_background` 跑，等完成通知。翻譯記憶預設開著（同原文只翻一次再擴散，保證 condition 兩邊一致）。
沒有 `user_boot_ok` 又沒 `--limit`，translate.py 會拒絕。

## G8 收尾

```bash
$PYT tools/fix_text.py    projects/<game>/exported/script.json
$PY  agt.py validate      <game>
$PY  agt.py check-codes   <game>       # 0 條 fatal
$PY  agt.py import        <game>
$PY  agt.py verify        <game>
$PY  agt.py package       <game>       # 永遠從 original/ 的原始封包出發
```

## G9 交付

`out/` + `安裝說明.txt`（範本 `docs/templates/安裝說明.template.txt`）：備份優先的安裝步驟、翻譯率、
刻意保留日文的條目與原因、已知瑕疵、實機驗收清單、本機已驗證項目。不確定就出 A/B 兩個變體。
等回報後 `mark <game> user_final_ok`。

## G10 回寫

`engines/<x>/NOTES.md`（固定標題）、`docs/lessons-learned.md`、memory。確認沒有殘留背景行程。
