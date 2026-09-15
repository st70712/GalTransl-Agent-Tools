# 引擎知識庫

「支援」= 本 repo 有轉接器；「指標」= 只有線索與外部工具位置，接入要走 `docs/new-adapter.md`。

## 辨識方法

1. 執行檔：`strings -n 8 Game.exe | grep -iE "version|rpg|wolf|dxlib|unity|kirikiri|tyrano"`。
   Wolf 的 exe 有 `This game data is the %s version…` 與 `Korean / Chinese (Traditional)…` 字串，代表引擎原生支援多語字碼頁。
2. 封包 magic：`xxd -l 16 <file>`。
3. 目錄長相：見下表。
4. 版本：同一引擎不同版本格式會變（Wolf 2.281 vs 3.173 差了十幾處），一定要記下來。

## 特徵表

| 引擎 | 執行檔／目錄 | 封包與 magic | 文字所在 | 編碼 | 狀態 |
|---|---|---|---|---|---|
| RPG Maker MV | `www/index.html`、`www/js/rpg_core.js`、`Game.exe`（NW.js） | 無封包（或 `package.nw`） | `www/data/*.json`（Map*、CommonEvents、System、資料庫） | UTF-8 | **支援** `rpgmaker_mv_mz` |
| RPG Maker MZ | `js/rmmz_core.js`、`index.html` | 無 | `data/*.json` | UTF-8 | **支援** `rpgmaker_mv_mz` |
| WOLF RPG 2.x | `Game.exe`（DX Library） | 單一 `Data.wolf`，DXA v8，開頭 `DX` | 封包內 `BasicData/*.dat`、`MapData/*.mps` | CP932 → 補丁用 CP950 + 語言標記 | **支援** `wolf_rpg` |
| WOLF RPG 3.x | `GamePro.exe` | `Data/*.wolf`（BasicData、MapData…共 ~20 包），檔案在封包根目錄 | 同上 | UTF-8 | **支援** `wolf_rpg` |
| RPG Maker VX Ace | `Game.exe`、`Game.ini`（`RGSS301.dll`） | `Game.rgss3a` | `Data/*.rvdata2`（Ruby Marshal） | UTF-8 | 指標 |
| RPG Maker VX / XP | `RGSS2xx.dll` / `RGSS1xx.dll` | `Game.rgss2a` / `Game.rgssad` | `Data/*.rvdata` / `*.rxdata` | UTF-8 | 指標 |
| Bishop（BSXScript） | `*.exe` + `*.bsa` | `BSArc` 簽章（v1–3） | `bsxx.dat`（BSXScript 3.1，UTF-16LE） | UTF-16LE | 指標 → `engines/bishop_bsx/README.md` |
| TyranoScript | `tyrano/`、`data/scenario/*.ks`、`index.html` | 無（或 Electron asar） | `data/scenario/*.ks` | UTF-8 | 指標；翻譯驅動 `/raid/home/jimhsieh/GalTransl/text/translate_tyranoscript.py` |
| KiriKiri / KAG | `*.exe`（krkr）、`*.xp3` | `XP3\r\n\x1a` | `*.ks`（多半在 xp3 內，可能加密） | Shift-JIS / UTF-16 | 指標 |
| Unity | `UnityPlayer.dll`、`*_Data/globalgamemanagers`（散檔）或 `*_Data/data.unity3d`（單檔 UnityFS bundle）；`GameAssembly.dll`＝IL2CPP、`*_Data/Managed/*.dll`＝Mono | 散檔 `resources.assets`／`sharedassets*.assets`／`level*`，或全部包在 `data.unity3d`（LZ4/LZ4HC） | JSON 表格 TextAsset（`{"Rows":[…]}`，RJ01483219）或 MonoBehaviour／ScriptableObject 欄位（`TopicCatalog.mTopics[].mLines[].mText`，RJ01657316）＋ `TextMeshProUGUI.m_text` UI 標籤 | UTF-8 | **支援** `engines/unity_textasset`（需 `.venv-unity`：UnityPy + TypeTreeGeneratorAPI；Addressables bundle 未支援） |
| Ren'Py | `game/`、`renpy/`、`lib/` | `game/*.rpa` | `*.rpy` / `*.rpyc` | UTF-8 | 指標（官方有翻譯機制 `game/tl/`） |
| NScripter | `nscript.dat`、`arc.nsa` | `arc.nsa` / `arc.sar` | `nscript.dat`（XOR 0x84） | Shift-JIS | 指標 |

## 已支援引擎的重點

### RPG Maker MV/MZ（`engines/rpgmaker_mv_mz`）
- 純 JSON，導入後重新序列化為 minified；往返用 JSON 相等而非位元組。
- 對話 = 101 + 連續 401 合併；導入時行數可多可少（插入／清空 401，追蹤 offset）。
- 導入自動 verify：非 401 指令逐一比對、圖片檔名污染（`Failed to load: img/pictures/…`）、選項數。
- 詳見 `engines/rpgmaker_mv_mz/NOTES.md`。

### WOLF RPG（`engines/wolf_rpg`）
- 二進位 `.mps/.dat`，自製解析器（`wolfrpg/`），字串 raw bytes 端到端；往返逐位元組。
- 散檔不生效，一定要重新打包成 `.wolf`，且儲存形式要與原封包一致。
- `Game.dat` 長度不能變；2.x 要設語言標記（位移 31 = 3）與 Big5 轉碼；3.x 直接 UTF-8。
- 詳見 `engines/wolf_rpg/NOTES.md`。

### Unity（`engines/unity_textasset`）
- 每款遊戲一份 `rules/<專案名>.json`：`tables`（JSON 表格的欄位／複合欄位規則）與 `monobehaviours`（type tree 路徑規則，`[*]` 代表陣列每個元素，`when` 限制同層欄位值）。
- 散檔或單檔 `data.unity3d` 自動判斷；bundle 整包載入、整包存回（LZ4）。往返關卡是逐物件＋資源區塊＋type tree 重存 raw 相同，不是逐位元組。
- 沒有 type tree 的 MonoBehaviour：Mono 用 `Managed/*.dll`、IL2CPP 用 `GameAssembly.dll`＋`global-metadata.dat` 產生（TypeTreeGeneratorAPI）。
- 字型：TextMeshPro 靜態圖集缺字 → `font_inject`（把 CJK 字型檔注入既有 Font 物件、掛成 TMP 全域備援）或 `tmp_dynamic_font`（靜態圖集動態化，散檔建置）。
- 詳見 `engines/unity_textasset/NOTES.md`。

## 新增引擎

把新引擎加進上表，並照 `docs/new-adapter.md` 建 `engines/<name>/`。


## 引擎專用環境

有宣告 `python_env` 的引擎（目前 `unity_textasset`）要先 `bash tools/setup_env.sh <engine>`；`bash tools/setup_env.sh <engine> --check` 可確認套件齊全。
