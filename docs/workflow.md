# 工作流程（CLAUDE.md 第 5 節的長版）

每一關對應 `agt.py` 的一個子命令；狀態寫在 `projects/<game>/agt.json`，`agt status GAME` 可看。
所有步驟都印出底層 vendored 指令，可直接複製到 shell 重跑；輸出同時寫進 `projects/<game>/logs/`。

直譯器 `$PY`／`$PYT` 各站不同，見 `CLAUDE.md` 第 3 節或 `agt env`（dgxluna：conda 的 galtransl／nllb-env；Windows：`python`，沒有 `$PYT`）。
兩站接力（實機端 Windows ↔ 翻譯端 dgxluna）的協定與交接點見 `docs/two-site.md`；下面每關標「站點」：
**實機**＝實機端或單機，**翻譯**＝翻譯端或單機。

```bash
python agt.py env                                              # 開工第一件事：我是哪一站、能力齊不齊
bash tools/setup_env.sh <engine>                               # 引擎有宣告 python_env 時先建它的 venv（轉接器會自動用）
```

## G0 辨識引擎（站點：實機）

```bash
$PY agt.py detect <遊戲目錄|遊戲zip|交接包|資料夾>     # 來料判斷：遊戲目錄才跑引擎偵測；交接包→提示 unpack；遊戲 zip→提示解壓
$PY agt.py init <game> --original <遊戲目錄> [--engine NAME] [--variant V]
```

`detect` 對每個引擎跑 `adapter.detect()`，列出信心與證據；≥0.5 才算辨識成功。
第一個假設常常是錯的（使用者說 RPG Maker，資料是 Wolf），以資料為準。辨識不出來走 `/identify-engine`；沒有轉接器走 `/new-adapter`。
`init` 會把 `original/` 連到遊戲目錄（symlink；Windows 沒權限時退回 junction）。

## G1 prepare 後先量測（站點：實機）

```bash
$PY agt.py prepare <game>
```

解包或定位資料樹到 `extracted/`。**接著量測，不要猜**：
- 封包內各種儲存形式（未壓縮／Huffman／LZ）的分布——打包時要照原樣（Wolf 踩坑 2）
- 檔案數、含文字的檔案有哪些、字串總數
- 各 context 的分布；抽幾條看內容是不是玩家看得到的文字
- **字型覆蓋率**：找出遊戲實際用的字型與它的字元集（TTF/OTF 的 cmap、TMP 圖集的字元表、Big5 碼表），
  對一份繁中語料算缺字率（`GalTransl-sister/exported_full/script.json` 有 19 萬字譯文可當語料）。
  缺字率高就要在翻譯前決定對策（換字型／動態造字／替字表），不要等 smoke build 才看到 □。
- 兩站流程：數字與對策寫進 `HANDOFF.md`「專案摘要」；字元集存 `projects/<game>/font_charset.txt`（會進交接包，翻譯端的 fix_text 自動用）。

## G2 往返驗證（站點：實機）

```bash
$PY agt.py roundtrip <game>
```

解析 → 寫回 → 比對。二進位格式要逐位元組相同（Wolf 17/17）；JSON 格式用 `json.load` 相等（RPG Maker）。
**格式理解只要有一處在猜，這一步就會抓到。** 沒全過不准動文字。

工具鏈重新序列化本來就不會逐位元組相同時（UnityPy 存 SerializedFile 少 23 KB 對齊／標頭，物件內容全同），
關卡定義改為：**物件集合相同 + 每個物件 raw 相同 + 文字資產重新 dump 與原文相同**（`engines/unity_textasset/vendor/roundtrip_test.py`），
並在 NOTES 註明「遊戲吃不吃要靠 G6 實機確認」——RJ01483219 實測遊戲接受 UnityPy 重存的 resources.assets。

## G3 導出並抽樣（站點：實機）

```bash
$PY agt.py export <game> [--merge PREV.json]
```

產出 `exported/script.json`、`format_specification.json`、`.agt.json`（sidecar：引擎、variant、來源／目標編碼、字串數）。
抽樣核對 `CLAUDE.md` 第 9 節「絕不導出」清單，也反過來確認**顯示文字沒有漏**（名字牌、傳給公共事件的引數）。
改了導出規則要重新導出時，先備份 `script.json`，再用 `--merge` 以 `(source_file, location)` 接續舊譯文。
兩站流程：抽樣時順便決定 smoke 樣本的 `--filter` 正則（鎖定開場，例如 `Data_Event`），寫進 `HANDOFF.md`。

## G4 零翻譯導入 + verify（站點：實機）

`gates` 會自動跑：把 `translated` 全清空導入到暫存目錄，輸出必須與 `extracted/` 相同；再跑

```bash
$PY agt.py verify <game>
```

結構驗證只看「不該變的東西有沒有變」：指令數／ID／縮排／整數參數、標籤、檔名、選項數、地圖尺寸、資料庫欄位。

## G5 破壞攔截（站點：實機）

```bash
$PY agt.py breakage <game>
```

刻意弄壞一份複本（圖片檔名塞日文、刪一個選項、改一個跳躍標籤），verify **必須失敗**。這是在測安全網本身。

**兩站流程的第一個交接點**：
```bash
# 實機端：填 HANDOFF.md（量測、字型對策、smoke --filter）→ git commit + push →
$PY agt.py handoff pack <game>                       # #1 → 翻譯端；有 handoff_dir 會自動複製到共用資料夾
```

## G6 Smoke build → 等實機

翻譯端（或單機）：
```bash
git pull && $PY agt.py detect <交接包或資料夾> && $PY agt.py handoff unpack <交接包或資料夾>   # 兩站流程才需要
$PYT tools/translate.py -i projects/<game>/exported/script.json --limit 20 --filter <HANDOFF.md 給的正則>
$PYT tools/fix_text.py   projects/<game>/exported/script.json
$PY  tools/check_codes.py projects/<game>/exported/script.json
$PY  agt.py validate <game>
$PY  agt.py handoff pack <game>                      # #2 → 實機端（兩站流程）
```
實機端（或單機）：
```bash
$PY  agt.py handoff unpack <交接包>                  # 兩站流程
$PY  agt.py import  <game>
$PY  agt.py verify  <game>
$PY  agt.py package <game>
# 照 out/安裝說明.txt 把補丁裝進遊戲（原檔改 .orig）
$PY  agt.py playtest <game> [--wait 20]              # 實機端：啟動、等、列 crash.dmp／Player.log；目視仍是使用者
```

交 `out/`（或已裝好的遊戲）給使用者實機開啟。他回報 OK 後：`$PY agt.py mark <game> user_boot_ok`，兩站流程再 `handoff pack`（#3 → 翻譯端）。
上一次幾乎每個坑都是「翻完才發現」；這 20 分鐘的 smoke build 能省下數小時。

- 樣本要落在一開遊戲就看得到的地方：`--filter Data_Event`（Unity）之類鎖定開場，不要讓 `--limit` 抓到冷門表。
- 樣本要含原字型字元集以外的字（戶／溫／另／你／她…），smoke build 同時就是字型測試。
- 要改引擎資產（字型資產、圖集、旗標）時**一次只改一件事**，產「單變數變體」放 `projects/<game>/variants/<字母>/`，
  讓使用者二分；崩潰就要 crash.dmp（`%LOCALAPPDATA%\Temp\<公司>\<遊戲>\Crashes\`）或 Player.log
  （`%USERPROFILE%\AppData\LocalLow\<公司>\<遊戲>\`；不一定存在），用 `.venv-unity` 的 `minidump` 解析例外位址落在哪個模組。
  `playtest` 會自動列出啟動後新出現的這些檔案。
- 交付超過 30 MiB 的檔案：zip，或放到 `~/gdrive/GalTransl-Agent-Tools/<game>/`（rclone 掛載）。

## G7 大量翻譯（站點：翻譯）

```bash
$PYT tools/translate.py -i projects/<game>/exported/script.json --log projects/<game>/logs/translate.log
```

用 `run_in_background` 跑，等完成通知。翻譯記憶預設開著（同原文只翻一次再擴散，保證 condition 兩邊一致）。
沒有 `user_boot_ok` 又沒 `--limit`，translate.py 會拒絕。兩站流程：`user_boot_ok` 隨 #3 交接包過來；
使用者直接對翻譯端說「開得起來」也可以自己 `mark`（實機端不會改 script.json，見 `docs/two-site.md` §3 例外）。

## G8 收尾

翻譯端（或單機）：
```bash
$PYT tools/fix_text.py    projects/<game>/exported/script.json
$PY  agt.py validate      <game>
$PY  agt.py check-codes   <game>       # 0 條 fatal
$PY  agt.py handoff pack  <game>       # #4 → 實機端（兩站流程）
```
實機端（或單機）：
```bash
$PY  agt.py handoff unpack <交接包>    # 兩站流程
$PY  agt.py import        <game>
$PY  agt.py verify        <game>
$PY  agt.py package       <game>       # 永遠從 original/ 的原始封包出發
```

## G9 交付（站點：實機）

`out/` + `安裝說明.txt`（範本 `docs/templates/安裝說明.template.txt`）：備份優先的安裝步驟、翻譯率、
刻意保留日文的條目與原因、已知瑕疵、實機驗收清單、本機已驗證項目。不確定就出 A/B 兩個變體。
等回報後 `mark <game> user_final_ok`。

## G10 回寫（兩站各自）

`engines/<x>/NOTES.md`（固定標題；實機端寫辨識／格式／補丁步驟／實機驗收）、`docs/lessons-learned.md`（翻譯端寫翻譯坑）、memory。
確認沒有殘留背景行程。最後一次 `handoff pack` 讓兩邊 `agt.json`／`HANDOFF.md` 同步；專案完結後刪 `HANDOFF.md`。
