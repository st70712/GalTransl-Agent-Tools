# GalTransl-Wolf

WOLF RPG Editor（ウディタ）遊戲的文本導出／導入工具，用於製作中文補丁。

輸出格式與 [GalTransl-RPGmaker](../GalTransl-RPGmaker) 的 `script.json` 相同，
因此同一套翻譯流程與 AI 翻譯代理可以直接沿用。

## 為什麼需要另一套工具

本工作區的 `RJ338582_trial`（`妹！せいかつ ～ファンタジー～ 体験版3.0`，作者 いぬすく）
**不是 RPG Maker 遊戲**，而是 WOLF RPG Editor 製作的：

| | RPG Maker MV/MZ | WOLF RPG Editor |
|---|---|---|
| 資料格式 | `www/data/*.json`（純文字 JSON） | `Data.wolf`（DXA 加密封包）內的二進位 `.mps` / `.dat` |
| 文字編碼 | UTF-8 | CP932（Shift-JIS） |
| 事件結構 | JSON 陣列 | 自訂二進位指令流 |

`GalTransl-RPGmaker` 的 `export_script.py` / `import_script.py` 只能處理前者，
對本遊戲完全不適用，所以這裡重新實作了整條工具鏈。

## 環境需求

Python 3.10 以上，**只用標準函式庫**，不需要安裝任何套件。

```bash
conda activate galtransl   # 沿用既有環境即可，或用任何 Python 3.10+
```

## 檔案結構

```
GalTransl-sister/
├── extract_wolf.py     # Data.wolf 解包工具
├── export_script.py    # 文本導出工具
├── roundtrip_test.py   # 格式往返驗證（動文本前的硬性關卡）
├── merge_by_text.py    # 以原文為鍵接續舊版譯文（跨遊戲版本用）
├── translate_wolf.py   # 自動翻譯（本機 Sakura 模型）
├── fix_cp950.py        # 譯文整理：簡繁正規化／符號替換／控制碼把關
├── import_script.py    # 文本導入／驗證工具
├── repack_wolf.py      # 把翻譯後的檔案寫回 Data.wolf 封包
├── set_game_lang.py    # 設定 Game.dat 的語言標記（不改變長度）
├── set_font.py         # 更換 Game.dat 的字型（不改變長度）
├── wolfrpg/            # 格式解析函式庫
│   ├── dxa.py            # DXA v8 封包解密／解壓
│   ├── filecoder.py      # 二進位讀寫與 .dat 混淆處理
│   ├── command.py        # 事件指令 / 移動路線
│   ├── map.py            # .mps 地圖
│   ├── common_events.py  # CommonEvent.dat
│   ├── database.py       # DataBase / CDataBase / SysDatabase
│   ├── game_dat.py       # Game.dat
│   ├── textio.py         # 可翻譯文字的定位與定址
│   └── textnorm.py       # 日文字形→Big5 可編碼形式的正規化表
├── RJ338582_trial/     # 原始遊戲
├── Data/               # 解包後的遊戲資料
└── exported/           # 導出的翻譯檔
```

## 翻譯工作流程

### 步驟 1：解包 Data.wolf

```bash
python extract_wolf.py RJ338582_trial -o Data
```

只會取出含文字的 `BasicData/` 與 `MapData/`（約 4.7 MB）。
加 `--all` 可連圖片、音效、字型一起解出（約 400 MB），
加 `--list` 只列出封包內容不解壓。

金鑰會自動偵測；本遊戲用的是 `Wolf RPG v2.281`。
若遇到偵測失敗的遊戲，可用 `--key` 手動指定。

### 步驟 2：導出文本

```bash
python export_script.py Data -o exported
```

產生 `exported/script.json`（本遊戲 9224 條字串）與 `exported/format_specification.json`
（供 AI 翻譯代理閱讀的格式說明）。加 `-s` 可按來源檔案分開輸出。

改了導出規則之後要重新導出時，用 `--merge` 接續已有的譯文：

```bash
cp exported/script.json exported/script.prev.json
python export_script.py Data -o exported --merge exported/script.prev.json
```

### 步驟 3：翻譯

編輯 `script.json`，把譯文填進 `translated` 欄位：

```json
{
  "index": 17,
  "source_file": "MapData/SampleMapA.mps",
  "location": "Ev3/Pg0/Cmd12/Str0",
  "original": "\\E冒険は順調だ…",
  "translated": "\\E冒險很順利…",
  "context": "dialog",
  "speaker": "",
  "code": 101
}
```

**不要修改** `index`、`location`、`source_file`——導入時要靠它們定位。

### 步驟 3.5：自動翻譯（選用）

`translate_wolf.py` 接上本機的 Sakura 模型自動翻譯，改寫自
`GalTransl/text/translate_rpgmaker.py`，針對 Wolf 做了必要調整。

```bash
conda activate nllb-env
python translate_wolf.py -i exported/script.json          # 翻對話／選項／UI／資料庫
python translate_wolf.py -i exported/script.json --include-optional  # 再加上選單字串變數
python translate_wolf.py -i exported/script.json --limit 20          # 小樣本試跑
```

與 RPG Maker 版的差異：

| 項目 | 說明 |
|---|---|
| context 優先級 | 換成 Wolf 的類型；`debug`（玩家看不到）與 `string_var`/`condition`（會改變行為）預設跳過 |
| 控制碼樣式 | 改用精確列舉，`\cself[8]` 不會被誤判成 `\c`、`\EBADEND` 不會把內文吃掉 |
| `\E` 前綴保護 | 開頭的控制碼在送模型前先摘除、翻完接回，不靠模型自己保留 |
| 翻譯記憶 | 相同原文只翻一次再擴散，省下約 40% 的量，並保證 `condition` 與其對應方譯法一致 |
| condition 規則 | 只翻譯「原文也出現在其他 context」的條件字串，找不到對應方的維持原文 |

翻譯有檢查點（`exported/.script_checkpoint.json`），中斷後重跑會接續。

### 步驟 3.6：整理譯文

```bash
python fix_cp950.py exported/script.json
```

1. **簡繁正規化** — opencc `s2twp` 轉台灣繁體。Big5 只收繁體字，模型偶爾漏出的
   簡體字靠這步救回。控制碼會先遮蔽再轉換。
2. **符號替換** — 日文符號 `ー`／`・`／`♪` 換成 Big5 有的 `～`／`‧`。
3. **控制碼把關** — 帶值的碼（`\cself[n]`、`\v[n]`、`\r[漢字,假名]`）遺失會讓內容
   不見，整條退回原文；純表現的碼（`\c[n]` 顏色、`\f[n]` 字級）遺失只掉格式，接受。
4. **雜訊反斜線序列** — 模型偶爾會在控制碼裡插雜字（`\EBADEND` → `\xEBADEND`，
   等於 `\E` 失效），或憑空生出字面的 `\n`。認不得的序列一律退回原文。
   判斷「認不得」時會扣掉**原文本身用過的**序列——這份遊戲資料就有 4 條台詞
   用字面 `\n` 換行，原文用得出來的寫法，譯文照著用當然沒問題。

目標編碼是 UTF-8 時，第 2 步（符號替換）會自動關閉：`SYMBOL_MAP` 整張表都是
「Big5 收不到這個字」才要的代打，UTF-8 下再換只會讓譯文平白偏離原文。

### 步驟 4：驗證

```bash
python import_script.py validate exported/script.json -e cp950
```

除了翻譯進度，還會執行三項檢查（見下方「安全檢查」）。
用 `-u untranslated.json` 可把未翻譯條目另存一份，`-c` 篩選 context。

### 步驟 5：導入

```bash
python import_script.py import Data exported/script.json -o Data_zh -e cp950
```

導入後會自動做結構驗證。輸出會列出**實際有變動的檔案**——
補丁只需要散佈這些檔案。

### 步驟 5.5：處理 Game.dat（不可省略）

`import_script.py` 產生的 `Data_zh/BasicData/Game.dat` 是**重新序列化**的，
只要視窗標題被翻譯，檔案長度就會改變，遊戲會無法啟動。

正確做法是拿**原始的** `Game.dat`，只做不改變長度的原地修改：

```bash
cp Data/BasicData/Game.dat Data_zh/BasicData/Game.dat        # 用回原始檔
python set_game_lang.py Data_zh/BasicData/Game.dat --lang zh-tw
python set_font.py Data_zh/BasicData/Game.dat --font "Microsoft Yahei UI Bold"
```

兩支工具都會印出前後的檔案長度，必須顯示「✓ 未改變」。

### 步驟 6：重新打包並部署

**WOLF 的 `Game.exe` 只讀 `Data.wolf` 裡的檔案**，磁碟上的同名散檔會被忽略；
把封包移走則遊戲無法啟動。所以補丁必須做成新的 `Data.wolf`。

```bash
python repack_wolf.py <原始 Data.wolf 或遊戲目錄> Data_zh -o Data.wolf.new
```

打包策略刻意保守，把與原始封包的差異壓到最小：

| 項目 | 作法 |
|---|---|
| 未變動的檔案 | **原始位元組連同位移一起沿用**，不重新壓縮也不重新加密 |
| 被翻譯的檔案 | 以 **Huffman** 形式接在資料區尾端，與封包內其他檔案相同 |
| 標頭表 | 沿用原本那一份，只就地改掉那幾個檔案的位移與大小欄位 |
| 標頭壓縮 | 與原封包相同的 **LZ + Huffman** |

> DXA 的每檔金鑰只由「金鑰字串 + 大寫檔名 + 上層目錄名」決定，與檔案在封包裡的
> 位置無關，所以未變動檔案的加密位元組可以原封搬運。

打包後會自動重新解開逐檔比對，確認 2065 個檔案全部一致才算成功。
**每次打包都從原始封包出發**，不要拿上一次的產物再打包，否則資料區會累積孤兒資料。

部署時把原本的 `Data.wolf` 改名備份，再放上新封包：

```bash
mv "<遊戲目錄>/Data.wolf" "<遊戲目錄>/Data.wolf.orig"
mv Data.wolf.new "<遊戲目錄>/Data.wolf"
```

確認遊戲正常後才刪掉備份；出問題就改回來，即完全還原。

## 引擎版本：2.281 與 3.173

本工具鏈同時支援兩種引擎版本，讀到哪個版本就寫回哪個版本。

| | 試玩版 RJ338582 体験版3.0 | 正式版 RJ338582 1.4.5 |
|---|---|---|
| 引擎 | Wolf RPG **2.281**（`Game.exe`） | Wolf RPG **3.173**（`GamePro.exe`） |
| 封包 | 單一 `Data.wolf` | `Data/` 下 **20 個 .wolf**，皆 DXA v8 |
| 封包內路徑 | `BasicData/…`、`MapData/…` | **檔案在封包根目錄**，沒有目錄前綴 |
| 字串編碼 | CP932 | **UTF-8** |
| 導出字串 | 9224 | 22768 |

含文字的資料只在 `BasicData.wolf`（149 檔）與 `MapData.wolf`（9 檔）裡，
其餘 18 包全是圖／音／字型。因為檔案在封包根目錄，`extract_wolf.py` 的
`TEXT_DIRS` 前綴過濾會一條都不 match，正式版要分兩次解、並加 `--all`：

```bash
G=$(ls -d RJ338582/*/)
python extract_wolf.py "${G}Data/BasicData.wolf" -o Data_full/BasicData --all
python extract_wolf.py "${G}Data/MapData.wolf"   -o Data_full/MapData   --all
```

解出來的 `Data_full/{BasicData,MapData}/` 正是 `WolfProject` 期望的結構，
後面的導出／導入／驗證流程完全不用改，只要把編碼從 `cp932` 換成 `utf-8`。

### 3.173 的格式差異

`0x55` 是 Wolf 3.x 蓋在 magic 裡的版本標記，2.x 該位置是 `0x00`。
`FileCoder.verify_variant()` 負責「比對時忽略、寫回時原樣照抄」。

| 位置 | 2.281 | 3.173 |
|---|---|---|
| `map.MAGIC_NUMBER[16]` | `0x00` | `0x55` |
| `map` 的 `unknown2` | `0x65` | `0x66` |
| `map` 圖塊陣列 | 一定內嵌 | 沒有圖塊的地圖改存 `ff ff ff ff` 哨兵 |
| `common_events.MAGIC_NUMBER[6]` | `0x00` | `0x55` |
| `common_events` 版本 | `0x8F` | `0xC9` |
| 每個公共事件的四段引數區長度 | 固定 10 | 引數名稱那段變 **11** |
| `database.DAT_MAGIC_NUMBER[5]` | `0x00` | `0x55` |
| 資料庫格式版本／終結位元組 | `0xC1` | `0xC2` |
| `game_dat` MAGIC 第 9 byte | `0x00` | `0x55` |
| `Game.dat` 設定陣列 | 22 格 | **35 格**（前 22 格值相同） |
| `Game.dat` 版本字串後的 int | 檔案長度 − 1 | 固定 `0x14`，與長度無關 |

wolftrans 把那四段引數區長度當成 magic number（因為 2.x 一直是 10），
3.x 才看得出來它其實是**長度前綴**。現在照讀到的值跑迴圈，兩版都能過。

`Game.dat` 位移 31 的語言標記在 3.173 仍在原位（設定陣列變長是往後加的），
但 3.x 的資料本來就是 UTF-8，**多半不需要設**——沒有字碼頁要選了。

### 往返驗證

`roundtrip_test.py` 是動任何文本之前的硬性關卡：解析 → 寫回 → 逐位元組比對。

```bash
python roundtrip_test.py Data_full   # 正式版 17/17
python roundtrip_test.py Data        # 試玩版 17/17（回歸測試）
```

格式理解只要有一處在猜，這一步就會抓到。上表裡「圖塊哨兵」「引數區長度」
「`Game.dat` 的 int」三條都是被它逼出來的。

## 文字編碼與語言標記

遊戲原始資料是 **CP932（Shift-JIS）**，該編碼不含大多數中文字。中文補丁要做兩件事：

1. 用 **CP950（Big5）** 導入譯文
2. 把 `Game.dat` 的**語言標記**設成繁體中文，否則引擎仍以 CP932 解讀，畫面全是亂碼

```bash
python import_script.py import Data exported/script.json -o Data_zh -e cp950
python set_game_lang.py Data_zh/BasicData/Game.dat --lang zh-tw
```

### 語言標記在哪

`Game.dat` 開頭那個 22 bytes 設定陣列的**第 17 格**（檔案位移 **31**）：

| 值 | 語言 |
|---|---|
| 1 | 日文 |
| 2 | 韓文 |
| **3** | **繁體中文** |
| 4 | 簡體中文 |

`Game.exe:0x6e6e0` 的分支是把這個位元組 `+1` 之後查跳躍表（`3+1=4` → `Chinese (Traditional)`）。

這是拿**官方繁中版 RJ352237 的 `Game.dat`** 跟日文版逐欄比對出來的——22 格裡只有
第 17 格（1→3）和第 20 格（0→1）不同。只設第 17 格就足以讓中文正常顯示。

> 官方版的封包是更舊的 **DXA Ver6**，WolfDec 的已知金鑰都解不開。金鑰是用已知明文
> 反推的：檔頭必定是 `'DX'` + 版本 6、`DataStartAddress` 必定是結構大小 0x30、
> `CodePage` 必定是 932，據此解出 12 bytes 金鑰
> `c7 05 ca 7d 8d e3 de f1 d9 0c 85 f4`（週期一致性檢查通過）。

### 未翻譯的文字也必須轉碼

設定語言標記後，引擎會用 **Big5 解讀所有文字**，不只是翻譯過的那些。
如果未翻譯的字串維持原本的 CP932 位元組，在遊戲裡就是亂碼——
連「……。」這種**純符號的台詞**也會變成方框。

好消息是 Big5 本身收錄了平假名、片假名與大量漢字，所以多數日文原文
**可以原樣轉碼**、在遊戲裡顯示成正常的日文。`import_script.py import` 預設會對
未翻譯的字串做這件事（`--no-transcode` 可關閉）。

轉不過去的部分由 `wolfrpg/textnorm.py` 的對照表處理：

| 類型 | 例 | 處理 |
|---|---|---|
| 半形片假名 | `ｽﾃｰﾀｽ` | NFKC 折成全形 `ステータス` |
| Big5 沒有的符號 | `ー` `・` `♪` `［］` | 換成 `～` `‧` `～` `〔〕` |
| 日文新字體 | `撃` `気` `戦` `発` | 換成正體字 `擊` `氣` `戰` `發` |
| 日本國字 | `込` `匂` `畑` `働` `笹` `凪` | 中文沒有對應字形，取字義最接近的常用字 |

本遊戲套用後，**未翻譯字串裡會變亂碼的條目降到 0 條**（導入時轉碼了 1144 條）。

> 表格在載入時會自我檢查：每一組對應的目標字都必須能以 cp950 編碼，
> 否則直接拋錯，避免表格寫錯卻沒人發現。

### 附帶一提

Shift-JIS 與中文編碼有部分漢字重疊，所以少數中文字在 CP932 下也能編碼成功。
**不要依賴這點**——它會產生「大部分字正常、少數變亂碼」的結果，比整體失敗更難察覺。
`validate` 會逐字檢查並列出所有無法編碼的字元。

## 字型

遊戲內建的日文字型不一定收錄所有中文字。本遊戲的實測覆蓋率：

| 字型 | 譯文漢字缺字 |
|---|---|
| `07やさしさゴシックボールド`（內建主字型） | 39/1314 (3.0%)，含 `說 內 黃 每 步 晚 戶 產` 等常用字 |
| `GenJyuuGothicXPB`（內建副字型） | 17/1314 (1.3%) |

官方繁中版的做法是把主字型換成系統中文字型 `Microsoft Yahei UI Bold`：

```bash
python set_font.py Data_zh/BasicData/Game.dat --font "Microsoft Yahei UI Bold"
```

實測 `Microsoft Yahei UI Bold`（23 bytes）與 `Microsoft JhengHei UI Bold`
（微軟正黑體，剛好 26 bytes）都可正常運作。

## 文字類型（context）

| context | 說明 | 數量 | 安全性 |
|---|---|---|---|
| `dialog` | 對話訊息（指令 101） | 4164 | 安全 |
| `choice` | 選項（指令 102） | 671 | 安全 |
| `picture_text` | 文字模式的圖片顯示（指令 150） | 1773 | 安全 |
| `call_arg` | 傳給公共事件呼叫的字串引數（指令 210／300） | 1068 | 安全 |
| `database` | 資料庫字串欄位（道具／技能／武器名稱與說明） | 713 | 安全 |
| `debug` | 除錯訊息（指令 106），玩家看不到 | 75 | 安全 |
| `game_title` | `Game.dat` 的視窗標題 | 1 | **不要翻**（會改變長度） |
| `string_var` | 字串變數指派（指令 122） | 671 | **會影響行為** |
| `condition` | 字串比較的運算元（指令 112） | 88 | **會影響行為** |

`call_arg` 很容易被忽略：呼叫公共事件的指令看起來只是流程控制，但它的字串引數
會被顯示出來——**對話框上方的說話者名字牌就是靠這個傳進去的**。
漏掉它的話，遊戲裡的人名會整個消失（名字牌變成空的）。

`condition` 的字串會在執行期與別處指派的值比對。
若只翻譯其中一邊、或兩邊譯法不同，比較就不再成立，分支會**無聲地永遠不執行**。
`validate` 會替你交叉檢查這件事。

## 絕不導出的內容

以下字串即使是日文也**不會**出現在 `script.json`，因為翻譯它們會直接弄壞遊戲：

| 內容 | 原因 |
|---|---|
| 素材路徑（圖片／音效／字型／存檔） | 檔案載入會失敗 |
| `SetLabel` / `JumpLabel`（指令 212/213） | 跳躍目標對不上 |
| `CommonEventByName`（指令 300）的**第一個**字串參數 | 那是事件名，改了呼叫會失敗；第二個之後是引數，可以翻 |
| 地圖事件名稱、公共事件名稱 | 僅編輯器內部使用，且被名稱呼叫 |
| 開發者註解（指令 103，9257 條） | 玩家看不到 |
| 資料庫中非「字串」型別的欄位 | 檔名／資料庫參照 |

## 安全檢查

### `validate` 的五項檢查

1. **編碼檢查**——逐條確認譯文能以目標編碼寫入，列出無法編碼的字元
2. **控制碼檢查**——比對原文與譯文的控制碼是否一致
3. **條件一致性檢查**——找出被當作 `condition` 比對、但各處譯法不一致的字串
4. **未翻譯但玩家看得到**——列出仍含日文、且不是 `debug` 的條目。這些在遊戲裡
   會顯示成日文（不是亂碼），但仍是補丁的缺口，出貨前該逐條確認
5. **會變亂碼**——列出未翻譯且連轉碼都轉不過去的條目。這些在遊戲裡是方框，
   必須翻譯，或把缺的字補進 `wolfrpg/textnorm.py`

### `verify` 的結構檢查

```bash
python import_script.py verify Data Data_zh
```

比對原始與翻譯後的資料，攔截會導致遊戲出錯的結構性問題：

- 指令數量、指令 ID、縮排、整數參數是否改變
- 圖片檔名是否被對話文字污染（會造成載入錯誤）
- 標籤／公共事件名稱是否被翻譯
- 選項數量是否改變
- 地圖尺寸、圖塊資料、事件／頁數是否改變
- 資料庫的數值欄位、列數、欄數是否改變

`import` 預設在導入後自動執行此驗證，`--no-verify` 可跳過。

## 控制碼

翻譯時必須原樣保留：

| 控制碼 | 說明 |
|---|---|
| `\E` | 等待按鍵／訊息段落結束（本遊戲 4164 條對話中有 4076 條以此開頭） |
| `\c[n]` | 切換顏色 |
| `\f[n]` | 切換字級 |
| `\cself[n]` | 插入自身變數 n 的值 |
| `\v[n]` | 插入變數 n 的值 |
| `\sp[n]` | 插入 n 個空白 |

換行請保留原有結構——Wolf 的訊息框高度固定，行數變多會被截掉。

## 關於 `speaker` 欄位

為了與 GalTransl 格式相容而保留，但**本遊戲一律為空字串**。
這款遊戲的對話沒有說話者標記（4164 條中只有 14 條以「開頭），
說話者是靠立繪與上下文表達的。

## 正式版 1.4.5 的翻譯成果

`妹！せいかつ ～ファンタジー～` 正式版（RJ338582 v1.4.5，Wolf 3.173），**已通過實機測試**。

| 項目 | 數值 |
|---|---|
| 導出字串 | 22768 |
| 已翻譯 | 19082（83.8%） |
| **玩家看得到的未翻日文** | **22 條** |
| 沿用試玩版譯文（以原文為鍵） | 10250 |
| 模型新翻不重複原文 | 5907 |
| 翻譯記憶擴散 | 2910 |
| **統一重複原文譯法** | **0 條** |
| 帶值控制碼遺失→退回原文 | 3 |
| 雜訊控制碼→退回原文 | 2 |
| 表現控制碼遺失（僅掉顏色） | 7 |
| 結構驗證 | 0 錯誤 |
| 封包實際變動檔案 | 8 個（7 個資料檔 + `Game.dat` 換字型） |

「統一重複原文譯法 0 條」是試玩版第 4 條踩坑的直接對照：翻譯記憶從第一輪就
開著，就不會出現同一句話多種譯法，事後也沒得統一。

編碼相關的檢查全部歸零——UTF-8 下沒有無法編碼的字，也沒有亂碼條目，
`textnorm.py` 的轉碼表完全用不到。

## 試玩版的翻譯成果

`妹！せいかつ ～ファンタジー～ 体験版3.0`（RJ338582），**已通過實機測試**。

| 項目 | 數值 |
|---|---|
| 導出字串 | 9224 |
| 已翻譯 | 7363（79.8%） |
| **玩家看得到的未翻日文** | **13 條**（見下方說明） |
| **會顯示成亂碼的條目** | **0 條** |
| 未翻譯但已轉碼（可正常顯示） | 1144 條 |
| 統一重複原文譯法 | 1123 條 |
| 帶值控制碼遺失→退回原文 | 8 條 |
| 表現控制碼遺失（僅掉格式） | 3 條 |
| 結構驗證 | 0 錯誤 |
| 封包實際變動檔案 | 8 個 |

「已翻譯 79.8%」不代表有兩成日文沒翻。未翻的 1861 條裡：

| 內容 | 數量 |
|---|---|
| 純符號（`……。` `★` `▼`） | 1031 |
| 純 ASCII（數字、`message`／`system` 這類代號） | 472 |
| 純控制碼／空白 | 275 |
| 含日文 | 83（其中 70 條是玩家看不到的 `debug`） |

**刻意保留日文的 13 條**：

* 8 條翻譯後會弄壞帶值控制碼（`\r[漢字,假名]` 假名標註、`\v[n]` 變數），
  自動退回原文——寧可留日文也不讓變數壞掉
* 5 條是找不到比對對象的 `condition` 孤兒（`強運の`、`慈悲深い` 等），
  翻了可能讓分支永遠不觸發

## 踩過的坑（做正式版前務必先讀）

這幾條都是實測撞出來的，每一條都曾讓遊戲整個開不起來或全畫面亂碼。

### 1. 散檔不會生效，一定要重新打包

`Game.exe` **只讀 `Data.wolf` 裡的檔案**，磁碟上同路徑的散檔會被完全忽略；
把封包移走則遊戲直接無法啟動。

DX Library 要由程式主動呼叫 `SetDXArchivePriority` 才會改成資料夾優先，
而 Wolf 沒有呼叫它。網路上「解開封包後刪掉 .wolf 就好」的說法對這個版本不成立。

### 2. 新封包必須用與原封包相同的儲存形式

第一次打包時我用了「格式規格允許、但這個封包從來沒用過」的形式，遊戲開不起來：

| | 失敗的做法 | 原封包實際使用 |
|---|---|---|
| 檔案儲存 | 完全未壓縮 | **全部 Huffman**（2019 個 Huffman、46 個 LZ+Huffman、**0 個未壓縮**） |
| 標頭表 | 未壓縮（`DXA_FLAG_NO_HEAD_PRESS`） | LZ + Huffman |

**動手前先統計原封包各種儲存形式的分布，照著做。** 規格支援不等於這個 exe 支援。

### 3. `Game.dat` 的總長度絕對不能變

翻譯視窗標題讓 `Game.dat` 少了 10 bytes，遊戲就無法啟動——尾端那 29000 bytes
未知資料裡應該存有絕對位移。

所以 `Game.dat` 的任何修改都必須是**不改變長度的原地覆蓋**：

* 語言標記是固定長度陣列裡的 1 個位元組，直接覆蓋（`set_game_lang.py`）
* 字型名稱用 NUL 補滿原欄位，引擎取字串會停在第一個 NUL（`set_font.py`）
* **不要翻譯視窗標題**，它會改變長度

`import_script.py` 產生的 `Data_zh/BasicData/Game.dat` 是重新序列化的，
**打包時不要用它**，要用原始 `Game.dat` 加上上述兩支工具的原地修改。

### 4. 翻譯記憶要從第一輪就開著

第一輪跑到一半才補上翻譯記憶，結果 575 種原文被翻成多種版本（`はい` 有 4 種、
`いいえ` 有 5 種），影響 2350 條。這不只是品質問題：`condition` 字串會與別處的值
比對，兩邊譯法不同分支就**無聲地永遠不執行**。

`fix_cp950.py` 有事後統一的步驟，但一開始就開著更省事。

### 5. 統一譯法時要優先選「保留完整控制碼」的版本

單純取最常見的譯法，會把掉了 `\c[n]`／`\f[n]` 的版本擴散出去，控制碼遺失反而從
52 條變成 76 條。改成優先選控制碼完整的版本後降到 3 條。

### 6. 未翻譯的文字也要轉碼，不能原樣留著

一開始我只把「有翻譯」的字串重新編碼，未翻譯的保留原本的 CP932 位元組。
但遊戲已經改用 Big5 解讀，那些位元組全成了亂碼——連「……。」這種純符號的台詞
都變成方框。本遊戲有一千多條未翻譯字串因此壞掉。

正確做法是**對未翻譯的字串也做一次轉碼**（見「未翻譯的文字也必須轉碼」）。
Big5 收錄了假名與多數漢字，所以絕大多數日文原文可以原樣顯示。

### 7. 流程控制指令的字串參數可能是顯示文字

`CommonEvent`（指令 210）與 `CommonEventByName`（指令 300）看起來只是呼叫，
但它們的字串參數是**傳給公共事件的引數**，會被顯示出來。
本遊戲對話框上方的**說話者名字牌**就是用 cid 210 的 Str1 傳進去的（999 條）。

一開始我把這兩個指令整個排除，結果遊戲裡人名全部消失（名字牌變成空的）。
正確做法是：cid 300 只排除 Str0（事件名），其餘都要導出。

`verify` 的檢查也要跟著調整粒度——不能因為 cid 300 是流程指令就比對全部參數，
否則會把正常的翻譯誤判成錯誤。

### 8. 改了導出規則，要用 `--merge` 接續舊譯文

導出規則一改，`index` 全部位移，直接重跑 `export_script.py` 會把已翻的部分清空。
`--merge` 用 `(source_file, location)` 對應——那是遊戲資料裡的固定位置，不隨導出
範圍改變——所以能安全接續：

```bash
cp exported/script.json exported/script.prev.json
python export_script.py Data -o exported --merge exported/script.prev.json
```

原文對不上的條目會留白而不是硬套，避免譯文接到錯的位置。
本次補上 `call_arg` 時，6351 條舊譯文全部接續成功。

### 9. 官方漢化版是最好的對照組

語言標記找了很久（純靜態分析只能定位到 `Game.exe` 的分支，找不到它在
`Game.dat` 的哪一格），最後是把官方繁中版的 `Game.dat` 挖出來逐欄比對才確定的。
**下次遇到未知欄位，先找同引擎的官方多語版本來 diff。**

## 正式版的建議作業順序

這次幾乎每個坑都是「翻完才發現」，回頭補救花的時間比翻譯本身還多。
下次照這個順序做可以省掉大部分：

1. **先解包、先導出、先看清楚**——統計原封包的儲存形式分布（第 2 條）、
   掃一遍各 context 的字串樣本，確認導出範圍沒漏（第 7 條）
2. **先跑通整條管線**：拿零翻譯或少量翻譯的結果走完
   `import → set_game_lang → set_font → repack → 實機開啟`，
   確認遊戲能開、中文能顯示。**這一步花 20 分鐘，能省下數小時**
3. 確認管線沒問題後才開始大量翻譯（翻譯記憶從第一輪就開著）
4. `fix_cp950` → `validate` 五項檢查全過 → `import` → `repack`
5. 實機驗收：對話、選項、**說話者名字**、純符號台詞、字型缺字、
   會做字串比對的分支（難度選擇／裝備／道具使用）

## 已驗證的行為

本工具鏈在本遊戲上通過以下測試：

* **解包**：2065 個檔案，大小與封包宣告完全吻合；2042 個 PNG/JPG/OGG/MP3/WAV/TTF
  檔頭全部正確
* **格式往返**：14 個資料檔讀出後再寫回**位元組完全相同**
* **零翻譯導入**：輸出與原始資料位元組完全相同
* **破壞攔截**：刻意竄改圖片檔名、跳躍標籤、公共事件名稱，`verify` 三項全數攔截
* **重新打包**：新封包與原版結構一致（`Flags`／`HeadSize`／`CodePage`／`HuffKB`
  皆不變，426 MB 原始資料區逐位元組相同），解開後 2065 個檔案全部一致
* **實機測試通過**：對話與選項正常顯示中文；說話者名字牌正常（`父親`／`妹妹`／
  `悠香梨`）；純符號台詞（`……。`）不再是方框；`Microsoft Yahei UI Bold` 無缺字；
  難度選擇、裝備、道具使用等會做字串比對的分支功能正常

## 已知限制

* **只支援 WOLF RPG Editor 2.x 的 DXA v8 封包**。Wolf 3.5 之後的 `.mps` / `.dat`
  另有壓縮層，工具會明確報錯而非產生錯誤結果。官方漢化版 RJ352237 用的
  **DXA Ver6 目前只有解密邏輯，沒有完整的解包器**（見「文字編碼與語言標記」）。
* **打包時被替換的檔案不做 LZ 壓縮**，只做 Huffman，因此新封包會略大於原始封包
  （本遊戲 407 → 411 MiB）。
* **`SysDataBaseBasic.project` 不處理**。它的每個 type 在 description 後就結束，
  沒有欄位中繼資料區；內容是編輯器用的地圖／BGM／SE 清單，不含玩家可見文字。
  參考實作 WolfTL 基於同樣理由排除此檔。
* **不翻譯視窗標題**，因為會改變 `Game.dat` 的長度（見「踩過的坑」第 3 條）。

## 致謝

格式解析參考了以下開源實作：

- [WolfDec](https://github.com/Sinflower/WolfDec) — DXA 封包格式與金鑰表
- [Wolf Trans](https://github.com/elizagamedev/wolftrans) — Wolf 資料格式解析
- [WolfTL](https://github.com/Sinflower/WolfTL) — 較新版本的格式差異處理
- 指令 ID 對照表源自 vgperson 的逆向筆記
