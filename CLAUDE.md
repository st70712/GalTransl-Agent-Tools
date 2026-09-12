# GalTransl-Agent-Tools — 遊戲中文化補丁工具箱（Claude Code 操作手冊）

## 1. 這是什麼

把日文遊戲做成繁體中文補丁的工具箱。**你（Claude）就是代理**：辨識引擎 → 沿用或新寫引擎轉接器 →
導出文本 → 驅動本機 Sakura 模型翻譯 → 整理／檢查譯文 → 導入 → 打包 → 交付給使用者實機驗收。
遊戲引擎五花八門，「修改既有工具／新增引擎」是常態路徑，不是例外。
翻譯模型伺服器（llama-server + Sakura-GalTransl-14B）在 `/raid/home/jimhsieh/GalTransl`，本專案只驅動它。
對使用者一律用繁體中文回覆。

## 2. 環境規則

| 用途 | 直譯器（見 `config.yaml`） |
|---|---|
| `agt.py`、`core/`、`engines/**`、`tools/check_codes.py`、`tests/` | `python_stdlib` = `/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python`（3.11，純標準庫） |
| `tools/translate.py`（非 `--dry-run`）、`tools/fix_text.py`（用 opencc） | `python_nllb` = `/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python`（openai/httpx/opencc） |
| 有宣告 `python_env` 的引擎（目前：`unity_textasset` → `.venv-unity`，UnityPy） | 該引擎 `profile.json` 的 `python_env.venv`；`bash tools/setup_env.sh <engine>` 建立，轉接器自動使用 |

```bash
PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python
PYT=/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python
```

- GalTransl 框架位置：環境變數 `GALTRANSL_ROOT` 或 `config.yaml` 的 `galtransl_root`（`/raid/home/jimhsieh/GalTransl`）。
- **環境政策**：核心（`core/`、`agt.py`、`tools/check_codes.py`、`tests/`）只用標準庫。引擎的 vendor 腳本若需要第三方套件
  （UnityPy、fonttools…），**允許建立該引擎專用的虛擬環境**，但必須把依賴宣告清楚：`profile.json` 的
  `"python_env": {"venv": ".venv-<x>", "requirements": "requirements.txt", "python": "3.12"}` + `engines/<x>/requirements.txt`，
  用 `bash tools/setup_env.sh <x>` 建（uv，venv 放 repo 根目錄、已 gitignore）。**不動 conda 環境、不 pip install 進 conda env**；
  `translate.py`／`fix_text.py` 的第三方 import 放函式內延遲載入。
- **可攜性**：`config.yaml` 裡是這台機器的絕對路徑（conda、GalTransl、模型、llama-server）。搬到別的機器：改 `config.yaml`
  （或用 `AGT_*`／`GALTRANSL_ROOT` 環境變數覆蓋）→ 對每個要用的引擎跑 `setup_env.sh` → `agt engines` 確認能載入。
  引擎目錄自己要能說清楚「我需要什麼」，不要依賴機器上剛好有的套件。
- **`engines/*/vendor/**` 不得修改**（原樣搬入的既有工具，md5 記在各引擎的 `VENDOR.md`）。要改行為改 `adapter.py` 或 `profile.json`。
- `ruff check .` 已排除 vendor；新程式碼要過 ruff。測試：`$PY -m unittest discover -s tests`。

## 3. 目錄地圖

```
agt.py              薄 CLI：把步驟分派到引擎轉接器，記錄關卡狀態
core/               純標準庫：script_json / profile / codes（控制碼把關）/ merge / roundtrip / adapter / registry / state
engines/<name>/     adapter.py + profile.json（單一宣告來源）+ NOTES.md（坑）+ VENDOR.md + vendor/（原工具）
engines/_template/  新引擎骨架；engines/bishop_bsx/ 只有指標
tools/              translate.py / fix_text.py / check_codes.py / llama_server.sh
docs/               workflow、engines（引擎知識庫）、script-json、profile-schema、new-adapter、translation-quality、lessons-learned
projects/<game>/    每款遊戲的工作目錄（不進 git）：original/ extracted/ exported/ translated/ out/ logs/ glossary.txt agt.json
```

`projects/<game>/`：`original/` 唯讀（可為 symlink）；`exported/` 放 `script.json`、`format_specification.json`、`.agt.json`（sidecar，記引擎／編碼）、`untranslated.json`；
`translated/` 每次 import 整個重建；`out/` 是交付物 + `安裝說明.txt`；`glossary.txt`（選用）格式 `原文->譯文 // 備註`。

## 4. 硬性關卡（順序不可調，任一失敗就停）

每一關都印出底層 vendored 指令，可直接複製重跑；狀態記在 `agt.json`（`$PY agt.py status GAME`）。

- [ ] **G0 辨識引擎** `$PY agt.py detect DIR` → `init GAME --original DIR`。第一個假設常常是錯的（上次「RPG Maker」其實是 Wolf）。
- [ ] **G1 prepare 後先量測** `prepare GAME`；統計封包儲存形式分布、檔案數、字串數、各 context 分布，**以及字型覆蓋率**：
      找出遊戲實際用的字型（內建 TTF/OTF、TMP 圖集、Big5 碼表…），把它的字元集對一份繁中語料
      （例如 `GalTransl-sister/exported_full/script.json` 的 19 萬字譯文）算缺字率；缺字要在翻譯前就有對策（換字型／動態造字／替字表）。用數字，不用猜。
- [ ] **G2 往返驗證** `roundtrip GAME`：解析→寫回逐位元組（二進位）或 JSON 相等。**動任何文字前的硬關卡**。
      若工具鏈重新序列化本來就不會逐位元組相同（UnityPy 存 SerializedFile 會少掉對齊／標頭），關卡改為
      「物件集合相同 + 每個物件內容相同 + 文字資產重新 dump 與原文相同」，並在 `NOTES.md` 註明「遊戲吃不吃要靠 G6 實機確認」。
- [ ] **G3 導出並抽樣** `export GAME`：看各 context 樣本，核對第 7 節「絕不導出」清單；名字牌之類的顯示文字有沒有漏。
- [ ] **G4 零翻譯導入** 由 `gates` 自動跑：清空譯文導入後輸出必須與 extracted 相同；`verify GAME` 0 錯誤。
- [ ] **G5 破壞攔截** `breakage GAME`：刻意弄壞一份複本，verify 必須攔下來。
- [ ] **G6 Smoke build → 停下來等實機** `$PYT tools/translate.py -i … --limit 20 [--filter 開場]` → `fix_text` → `check_codes` → `import GAME` → `package GAME`。
      樣本要落在**一開遊戲就看得到**的地方（用 `--filter` 鎖定開場），並包含原字型字元集**以外**的字（戶／溫／另／你／她…）來測缺字。
      **交付 `out/` 給使用者實機開啟，等回報後 `mark GAME user_boot_ok`。這 20 分鐘能省下數小時。**
      若要改引擎資產（字型、圖集、旗標）：**一次只改一件事**，出「單變數變體」讓使用者二分；崩潰就索取 crash.dmp／Player.log
      （`.venv-unity` 有 `minidump` 可解析例外位址與模組），不要靠猜。
- [ ] **G7 大量翻譯**（翻譯記憶預設開；`--dict`；用 `run_in_background` 跑；沒有 `user_boot_ok` 時 translate.py 會拒絕，`--force` 才越過）。
- [ ] **G8 收尾** `fix_text` → `validate GAME` 全過 → `check-codes GAME` 0 條 fatal → `import GAME` → `verify GAME` → `package GAME`（**永遠從 `original/` 的原始封包出發**）。
- [ ] **G9 交付** `out/` + `安裝說明.txt`（翻譯率、刻意保留日文清單、已知瑕疵、驗收清單）；等使用者 A/B 回報，`mark GAME user_final_ok`。
- [ ] **G10 回寫** `engines/<x>/NOTES.md`、`docs/lessons-learned.md`、memory。

`$PY agt.py gates GAME` 會依序跑 prepare→roundtrip→export→零翻譯導入→verify→breakage，遇錯即停。

## 5. 引擎辨識

先看：執行檔字串（`strings Game.exe | grep -i version`）、封包 magic（前幾個 bytes）、資料目錄長相。詳表在 `docs/engines.md`。

| 引擎 | 特徵 | 狀態 |
|---|---|---|
| RPG Maker MV | `www/data/System.json`、`www/js/rpg_core.js` | **支援** `engines/rpgmaker_mv_mz` |
| RPG Maker MZ | `data/System.json`、`js/rmmz_core.js` | **支援**（同上） |
| WOLF RPG 2.x | `Game.exe` + 單一 `Data.wolf`（開頭 `DX`），字串 CP932 | **支援** `engines/wolf_rpg`（目標 cp950 + 語言標記） |
| WOLF RPG 3.x | `GamePro.exe` + `Data/*.wolf`（BasicData/MapData…），字串 UTF-8 | **支援**（同上，utf-8） |
| RPG Maker VX Ace | `Game.rgss3a`、`Data/*.rvdata2`（Ruby Marshal） | 指標 |
| Bishop / BSXScript | `*.bsa` 封包、`bsxx.dat`（UTF-16LE） | 指標 → `engines/bishop_bsx/README.md`、https://github.com/st70712/GalTransl-BISO |
| TyranoScript | `data/scenario/*.ks`、`tyrano/` | 指標（翻譯驅動在 `/raid/home/jimhsieh/GalTransl/text/translate_tyranoscript.py`，本專案無導出／導入工具） |
| KiriKiri | `*.xp3`、`*.ks` | 指標 |
| Unity（JSON 表格 TextAsset） | `UnityPlayer.dll`、`*_Data/globalgamemanagers`、`resources.assets` 內有 `{"Rows":[…]}` TextAsset | **支援** `engines/unity_textasset`（需 `.venv-unity` 的 UnityPy；UI 標籤／bundle 為第二階段） |
| Ren'Py | `game/*.rpa`、`*.rpyc` | 指標 |

## 6. 決策樹

1. **有轉接器且能跑** → 直接用，走第 4 節關卡。
2. **有轉接器但這款遊戲跑不過**（版本差異、新指令 ID…）→ 先改 `adapter.py`／`profile.json`；真的要動 `vendor/` 時，
   先用 vendor 內示範資料或原專案資料做回歸（見 `VENDOR.md`），改完更新 md5，並把差異寫進 `NOTES.md`。
3. **沒有轉接器** → 依 `/new-adapter`（`docs/new-adapter.md`）：複製 `engines/_template/`，**依序**
   解包 → 解析 → 往返驗證 → 導出 → 零翻譯導入 → verify + 破壞攔截 → 寫 profile → smoke build 給使用者 → 大量翻譯。
   順序不能跳：往返沒過就不准導出，實機沒開過就不准大量翻譯。

## 7. 絕不導出 checklist

- 素材路徑（png/jpg/ogg/mp3/wav/ttf/sav…）——載入會失敗
- 跳躍標籤、事件名稱、被名稱呼叫的公共事件名——控制流會斷
- 呼叫指令的「第一個」名稱參數（Wolf cid 300 的 Str0）——但**後面的字串引數可能是顯示文字**（說話者名字牌就是 cid 210 的 Str1，漏了人名全消失）
- 開發者註解、除錯訊息——玩家看不到，翻了只是浪費模型時間
- 資料庫非字串型欄位（檔名／參照）
- 會改變檔案長度的長度敏感欄位（Wolf `Game.dat` 視窗標題）

反過來：任何「看起來像流程控制」的字串參數，都要先確認它不是顯示文字。

## 8. 何時停下來問使用者

- **實機測試**：你沒有 Windows，使用者有。每個 smoke build／最終補丁都要等他回報；他會給精確的 A/B 結果（「A 開得起來、B 不行」「對話亂碼、選單正常」），照著縮小範圍。
- 封包儲存形式不確定（規格允許 ≠ 這個 exe 支援）→ 先量原封包的分布再做，仍不確定就出兩個變體給使用者比。
- 長度敏感檔（`Game.dat` 類）要改長度 → 停。只做不改長度的原地覆蓋。
- 找不到語言標記／未知欄位 → 先請使用者提供同引擎的官方多語版本來 diff，比逆向快得多。
- 需要刪除、覆蓋使用者提供的檔案 → 一律先改名 `.orig`，不刪。
- 中文顯示成 □ → 是字型缺字，不是譯文壞掉。先量測（圖集字元表／cmap 覆蓋率），再決定換字型、動態造字或替字表；每個嘗試都是一個變體，實機驗證。
- 檔案交付：`SendUserFile` 上限 30 MiB，超過就 zip 或放到 `~/gdrive/GalTransl-Agent-Tools/<game>/`（rclone 掛載的 Google Drive）。

## 9. 背景工作禮儀

- 長工作（翻譯、解包大封包）用 Bash 的 `run_in_background`，等完成通知；**不要自己寫 pgrep 迴圈**（會 match 到自己，上次白等 5 小時）。
- **不要對「之後會被移動的檔案」輪詢**（上次 `until [ -f /tmp/x ]` 空轉 1 小時）。要等就等行程。
- 模型在跑時做準備工作：寫 fix/validate、量字型覆蓋率、備份、更新文件。
- 收工前確認沒有殘留行程；`bash tools/llama_server.sh status` 看模型伺服器。

## 10. 資料安全

- `original/` 唯讀；`translated/` 是衍生物可隨時重建；打包永遠從 `original/` 的原始封包出發，不拿上一次產物再打包。
- 改導出規則前先備份 `exported/script.json`；重新導出後用 `export GAME --merge PREV.json` 接續譯文（以 `(source_file, location)` 對應）。
- 檢查點 `.agt_checkpoint.json` 以 `(source_file, location)` 為鍵；看到舊式 `.script_checkpoint.json`（位置序號）一律刪掉再跑，它曾靜默錯位 545 條。
- 不把 GB 級遊戲資料放進 repo；`projects/` 整個不進 git；`.venv*` 也不進 git（用 `setup_env.sh` 重建）。
- A/B 變體放 `projects/<game>/variants/<字母>/`，每個變體只差一件事，差異與回報結果記在 `projects/<game>/HANDOFF.md`。
- `HANDOFF.md` 是**跨對話交接用**（context 不夠、要換新對話時寫），專案完結、教訓回寫 `NOTES.md`／`docs/lessons-learned.md` 後就刪除；它不進 git。
- 不 `git push`、不設 remote，除非使用者明說。

## 11. 收尾回寫

- `engines/<x>/NOTES.md` 固定標題：辨識特徵／資料格式／絕不導出／控制碼／補丁步驟／踩過的坑／實機驗收。
- 跨引擎的教訓寫 `docs/lessons-learned.md`；使用者偏好（字型、流程）寫 memory。
- 使用者常說「把採到的坑紀錄一下」——這不是可選項。
- 專案完結：確認 `HANDOFF.md` 的結論都已搬進 NOTES／docs，可重用的資料（規則檔、字型字元集、替字表）搬進 `engines/<x>/`，再刪 HANDOFF。

## 12. 風格

flat 動詞命名腳本（`export_script.py`）、argparse 子命令、pathlib、dataclass、型別提示、`print()` 不用 logging、
模組層 UPPER_CASE 常數放格式知識、繁體中文文件與訊息、寫檔前備份、`-o` 輸出到別處、Conventional Commits。
