# Windows 實機端驗收清單（分支 `feat/two-site`）

> 給筆電端 Claude Code 的交接文件。**這次的任務是驗證，不是做遊戲中文化**：照下面的項目逐條跑、把結果填進第 5 節、
> 修掉能修的、commit 到同一分支、push 回 GitHub。dgxluna 端看完結果才 merge 進 main。
> 背景：`CLAUDE.md` 第 2、3、6 節與 `docs/two-site.md`（兩站接力：實機端 Windows ↔ 翻譯端 dgxluna）。
>
> **狀態：2026-09-12 筆電端驗收通過（§5），dgxluna 端跨機 unpack／dry-run／pack 回傳通過，已 merge 進 main。**
> 本檔留作日後 Windows 回歸清單；再跑一輪時把 §5 換成新紀錄。

## 0. 規則

- 分支 `feat/two-site`，不要動 main。所有修正 commit 到這個分支（Conventional Commits，繁中訊息）。
- `engines/*/vendor/**` 不得修改。要修就修 `core/`、`agt.py`、`tools/`、`engines/*/adapter.py`、文件。
- 每個項目記：**通過／失敗／略過**＋實際輸出（貼關鍵幾行，錯誤要整段）。不確定的先記下來，不要猜。
- 跑到一半卡住（權限、缺套件）先試文件寫的解法；解不了就記錄並跳下一項。
- 不要把遊戲檔、`projects/`、`.venv*`、`config.local.yaml` commit 進去（.gitignore 已排除；`git status` 確認）。

## 1. 首次設定（對應 `docs/two-site.md` §8）

| # | 步驟 | 指令 | 預期 |
|---|---|---|---|
| 1.1 | Python | `python --version` | ≥ 3.11；Git Bash 裡叫 `python`（`python3` 可能沒有） |
| 1.2 | uv | `pip install uv && uv --version` | 有版本號；`which uv` 找得到 |
| 1.3 | 本機設定 | `cp config.local.example.yaml config.local.yaml`，填 `site: workstation`、`handoff_dir:`（Google Drive 桌面版資料夾，例如 `G:/My Drive/GalTransl-Agent-Tools`；沒有就留空） | 檔案存在且 `git status` 看不到它 |
| 1.4 | UTF-8 | `setx PYTHONUTF8 1`，重開終端機 | `echo $PYTHONUTF8` 印 1 |
| 1.5 | env | `python agt.py env` | `站點: workstation`；`can_run_game ✓`、`uv ✓`、`git ✓`；記下 `symlink_ok` 是 ✓ 還是 ✗（✗ 代表沒開開發人員模式，之後會退回 junction，**這是要測的路徑之一**）；`handoff_dir` 有設就 ✓ |
| 1.6 | env --json | `python agt.py env --json` | 合法 JSON，`site` 為 `workstation` |
| 1.7 | 引擎 | `python agt.py engines` | 列出 rpgmaker_mv_mz、unity_textasset、wolf_rpg |

## 2. 純標準庫測試（跨平台的真正考驗）

| # | 指令 | 預期 | 看什麼 |
|---|---|---|---|
| 2.1 | `python -m unittest discover -s tests -v 2>&1 \| tail -40` | 全過（dgxluna 是 66 個） | 失敗的貼整段 traceback |
| 2.2 | 跑完 `git status --short` | 乾淨 | **重點**：`engines/rpgmaker_mv_mz/vendor/Game/` 還在（測試會對它建 symlink／junction 再 rmtree 暫存目錄；Python 3.8+ 的 rmtree 不會跟進 junction，但要親眼確認）。若消失：`git checkout -- engines/rpgmaker_mv_mz/vendor` 還原並回報 |
| 2.3 | `tests/test_fsutil.py` 的 `test_link_is_link_remove` 印的是哪種 | 在 Python 裡跑 `from core import fsutil; print(fsutil.link_dir(...))` 或看 2.4 的 init 輸出 | 記下是 `symlink` 還是 `junction` |
| 2.4 | 用示範遊戲建專案：`python agt.py init demo --original engines/rpgmaker_mv_mz/vendor/Game` | 印 `projects/demo/original → …（symlink）` 或 `（junction）`；引擎 rpgmaker_mv_mz MV | 沒開開發人員模式應是 junction；`ls -la projects/demo/` 看得到 original |
| 2.5 | 重跑 2.4 一次 | 不報「已存在且非空」，重建連結成功 | 這是 junction 不被 `is_symlink()` 認得的坑，已用 `fsutil.is_link` 處理 |
| 2.6 | `python agt.py gates demo` | 六關全綠 | prepare 印的 extracted 連結種類；每一步印的 `$ …` 命令列是 cmd 風格引號 |
| 2.7 | 把 2.6 印出的任一條 `$ "…python.exe" …` 貼回 Git Bash 執行 | 能跑 | 驗證命令列可複製（`list2cmdline` 的引號在 bash 裡是否還能用） |
| 2.8 | `python agt.py status demo` 在 **Git Bash**、再在 **PowerShell** 或 cmd 各跑一次 | 不炸 `UnicodeEncodeError`；中文與 ✓ 正常顯示（cmd 顯示成問號可接受，但不能 crash） | 沒設 `PYTHONUTF8` 也試一次（`env -u PYTHONUTF8 python agt.py status demo`） |
| 2.9 | `cat projects/demo/logs/export-*.log \| head` | UTF-8 可讀，vendored 腳本的輸出沒有亂碼 | 子行程 `PYTHONUTF8=1` 是否生效 |

## 3. 引擎專用環境（Unity）

| # | 指令 | 預期 |
|---|---|---|
| 3.1 | `bash tools/setup_env.sh unity_textasset` | uv 建 `.venv-unity`（會下載 Python 3.12 與 UnityPy，需網路）；最後印 `✓ .venv-unity 就緒：…/.venv-unity/Scripts/python.exe` 與 `✓ 套件齊全` |
| 3.2 | `bash tools/setup_env.sh unity_textasset --check` | `✓ 套件齊全` |
| 3.3 | `python agt.py env` | 引擎專用環境 `✓ unity_textasset …Scripts/python.exe` |
| 3.4 | 若 3.1 失敗 | 貼錯誤。可能的坑：Git Bash 把 `/c/Users/...` 傳給 uv 時的路徑轉換；`uv venv --python 3.12` 下載被擋。能修就修 `tools/setup_env.sh`，不要改 profile |

## 4. 兩站接力與實機端功能

| # | 指令 | 預期 |
|---|---|---|
| 4.1 | `python agt.py handoff pack demo --allow-dirty` | 產生 `projects/demo/handoff/demo-001-to-translator-<時間>.zip`；`HANDOFF.md` 從範本產生並警告要填；有 `handoff_dir` 時多印「已複製到共用資料夾」 |
| 4.2 | 若有 `handoff_dir` | 到 Google Drive（網頁或 dgxluna 的 `~/gdrive/GalTransl-Agent-Tools/demo/handoff/`）確認 zip 出現、大小一致；記下同步花多久 |
| 4.3 | `python agt.py detect projects/demo/handoff/` | 「這個資料夾裡有 1 個交接包」 |
| 4.4 | `python agt.py detect projects/demo/handoff/demo-001-*.zip` | 「這是交接包 … → handoff unpack」 |
| 4.5 | `python agt.py handoff unpack projects/demo/handoff/demo-001-*.zip --game demo2` | 建 `projects/demo2/`（沒有 original/）、印專案名不一致警告、印關卡狀態 |
| 4.6 | `python agt.py import demo2` | 被擋：「此步驟要在實機端跑」（翻譯端骨架不能導入） |
| 4.7 | `python tools/translate.py -i projects/demo2/exported/script.json --dry-run --limit 5` | 純標準庫 dry-run 成功、「未寫入任何檔案」 |
| 4.8 | `python tools/check_codes.py projects/demo2/exported/script.json` | 0 條必須處理 |
| 4.9 | `python agt.py handoff unpack projects/demo/handoff/demo-001-*.zip --game demo2` 再跑一次 | 拒收（seq 不比本地新）；加 `--force` 通過並印備份路徑 |
| 4.10 | `python agt.py status demo` | 有 `交接: #1 持棒 translator …` 那行 |
| 4.11 | **playtest（實機端獨有，最重要）**：找一款筆電上有的遊戲（Wolf／RPG Maker／Unity 都可）：`python agt.py detect <遊戲目錄>` → `python agt.py init <game> --original <遊戲目錄>` → `python agt.py playtest <game> --dry-run` | dry-run 印出正確的 exe 路徑與掃描位置（Unity 應挑與 `*_Data` 同名的 exe；Wolf 3.x 是 GamePro.exe） |
| 4.12 | `python agt.py playtest <game> --wait 15 --kill` | 遊戲視窗開起來、15 秒後印「✓ 仍在執行」並關閉；`agt status` 多一行 `[✓] playtest`；沒有崩潰檔時印「沒有新的 crash.dmp / Player.log」 |
| 4.13 | 同上不加 `--kill` | 遊戲留著；訊息提醒目視 |
| 4.14 | 故意用 `--exe` 指一個會立刻結束的程式（例如 `--exe "C:/Windows/System32/whoami.exe"`） | 印「✗ 在 x 秒後結束，exit code 0」、`[✗] playtest`、rc 1 |
| 4.15 | 用真實遊戲跑 `python agt.py gates <game>`（有 Unity 就用 Unity，順便驗 3.x 的 venv 真的被轉接器用到） | 全綠或記下卡在哪一關 |
| 4.16 | 真實遊戲 `python agt.py handoff pack <game> --allow-dirty` 並放到 Drive | 這個包留給 dgxluna 端做跨機 unpack 驗證；把檔名寫進第 5 節 |

## 5. 驗證紀錄（筆電端填）

驗證日期 2026-09-12，主機 pochen-pc。
環境：Windows 11 家用版 10.0.26200；Python 3.11.9（**Microsoft Store 版**，`C:\Users\st707\AppData\Local\Microsoft\WindowsApps\…\python.exe`）；
uv 0.12.13（`pip install uv`）；開發人員模式＝**關**；Git Bash＝git 2.55.0.windows.5；Google Drive 桌面版＝有，路徑 `G:/我的雲端硬碟/GalTransl-Agent-Tools`（磁碟機名是中文，不是 `My Drive`）。

| # | 結果 | 備註（關鍵輸出、錯誤、修了什麼） |
|---|---|---|
| 1.1–1.7 | 通過（1.2 部分） | 1.2：`pip install uv` 成功但 `which uv` 找不到——Store 版 Python 把 `uv.exe` 裝進 `…\LocalCache\local-packages\Python311\Scripts`，不在 PATH。修：`core/site.find_uv` 與 `setup_env.sh` 用 pip 套件 `uv.find_uv_bin()` 找，`agt env` 印 `✓ uv …（不在 PATH；setup_env.sh 會自己找到）`。1.4：`setx PYTHONUTF8 1` 已執行（本對話的 shell 仍未生效，所以下面所有項目都是在**沒有** `PYTHONUTF8` 下跑的，等於順便驗了 2.8 的 `env -u`）。1.5：`站點: workstation`、`can_run_game ✓`、`uv ✓`、`git ✓`、`symlink_ok ✗`、`handoff_dir ✓`；另 `platform.release()` 在 Win11 印 `Windows 10`，改印 `Windows 11 (build 26200)`。1.6 JSON 合法、site=workstation。1.7 列出三個引擎。 |
| 2.1 | 修後通過 | 修前：66 個測試 **2 失敗 + 19 錯誤**。三個根因：(a) `mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""})` 沒作用——`config.load_config` 只在環境變數非空時覆蓋，測試讀到真實 `config.local.yaml` 的 `handoff_dir`，**測試交接包被複製到 Google Drive**（`demo-001/002-to-translator-*.zip`，已刪）、seq 與 `copied_to` 斷言失敗、後續 8 個測試因 `bundle1` 缺失連鎖錯誤；(b) 測試用 `subprocess.run(text=True)` 依 locale cp950 解碼子行程的 UTF-8 輸出 → `UnicodeDecodeError: 'cp950' codec can't decode byte 0xe6`（AgtCli／ToolsStdlib 共 8 個）；(c) `core/adapter.run` 把子行程的 `✓` 轉印到 cp950 stdout → `UnicodeEncodeError`（RpgMakerPipeline 4 個）。修後 `env -u PYTHONUTF8` 與 `PYTHONUTF8=1` 各跑一次都 `Ran 66 tests … OK`。 |
| 2.2 | 通過 | `git status --short` 乾淨；`engines/rpgmaker_mv_mz/vendor/Game/www` 完好（rmtree 沒跟進 junction）。 |
| 2.3–2.5 | 通過 | `fsutil.link_dir` 回 `junction`；`is_link=True`、`Path.is_symlink()=False`；`remove_link` 只拆連結、目標仍在。`init demo` 印 `projects/demo/original → …vendor\Game（junction）`，引擎 rpgmaker_mv_mz MV；重跑一次不報「已存在且非空」。 |
| 2.6–2.7 | 修後通過 | 六關全綠，但第一次 roundtrip／zero_import 印 **`0 個檔案相同，0 個不同，只在 extracted: 17`** 仍判 ✓——vendored `import_script.py` 對沒有譯文的檔案 `continue`，空譯文導入一個檔案都不寫，比對集合是空的、關卡空轉（dgxluna 上應該一樣）。修：`zero_import` 比不到任何檔案就判失敗；`rpgmaker_mv_mz` 改 `zero_import_fill = "identity"`（譯文＝原文），現在印 `13 個檔案相同，0 個不同，只在 extracted: 4`（4 個是沒字串的 JSON）。2.7：`list2cmdline` 印的 `C:\Users\…` 沒引號，貼回 Git Bash 反斜線被吃掉（`can't open file '…\Usersst707Desktop…'`）。修：Windows 上含反斜線／空白的參數一律雙引號，貼回 Git Bash 實測可跑（cmd／PowerShell 也接受雙引號）。 |
| 2.8–2.9 | 通過 | `status demo` 在 Git Bash（`env -u PYTHONUTF8`）、PowerShell、cmd 各跑一次都不炸，中文與 ✓ 正常（本機 chcp 65001）。2.9：log 是 UTF-8 可讀；原本每行 CRLF（Windows 文字模式），改 `newline="\n"` 固定 LF。 |
| 3.1–3.4 | 修後通過 | `setup_env.sh unity_textasset` 用 uv 下載 Python 3.12.14 + UnityPy 1.25.3 等 11 個套件成功；但最後的 `--check` 印 `✓` 時 `UnicodeEncodeError: 'cp950'`（venv 的 python 沒繼承 UTF-8）。修：腳本開頭 `export PYTHONUTF8=1 PYTHONIOENCODING=utf-8`；`--check` 印 `✓ 套件齊全` rc 0；`agt env` 印 `✓ unity_textasset …\.venv-unity\Scripts\python.exe`。Git Bash 傳路徑給 uv 沒有轉換問題。 |
| 4.1–4.10 | 通過 | pack → `demo-001-to-translator-20260912-1129.zip`（14 個檔案），HANDOFF.md 從範本產生並警告要填，印「已複製到共用資料夾 G:\…」；`detect` 資料夾→「有 1 個交接包」、zip→「這是交接包 … seq #1」；`unpack --game demo2` 建骨架、印專案名不一致與沒有 original/ 警告；`import demo2` 被擋「此步驟要在實機端跑」rc 1；`translate.py --dry-run --limit 5` 成功「未寫入任何檔案」（`待處理 0` 是因為 demo 語料是英文，`is_japanese_text` 全濾掉，正常）；`check_codes` 0 條必須處理；再 unpack 拒收「seq #1 不比本地 #1 新」，`--force` 通過並印兩個備份路徑；`status demo` 有 `交接: #1 持棒 translator`。4.2：本機 `G:` 立刻出現、大小一致（40680）；雲端是否上傳完成無法從這台確認（Drive 連接器搜不到該檔，可能是不同帳號），請 dgxluna 端看 `~/gdrive/…` 時記時間。 |
| 4.11–4.14 | 通過 | 用 Unity 遊戲 **RJ01483219 秘密のシェアハウスせいかつ v1.0.7**（`C:\Users\st707\Downloads\秘密のシェアハウスせいかつ_v107`，Unity 6000.0.58f2 IL2CPP，15 個 JSON TextAsset）。`playtest --dry-run` 挑到 `秘密のシェアハウスせいかつ.exe`（與 `_Data` 同名）並列出 Crashes／LocalLow／遊戲目錄掃描位置。`--wait 15 --kill`：`✓ 仍在執行（15 秒）`、「沒有新的 crash.dmp / Player.log」、`[✓] playtest`。不加 `--kill`：`留著給使用者目視`，遊戲確實留著（驗完由代理關閉）。`--exe C:/Windows/System32/whoami.exe`：`✗ 在 0.5 秒後結束，exit code 0`、`[✗] playtest`、rc 1。另 MZ 遊戲 `天使の早漏治療クリニック_v3/Game` detect 為 RPG Maker MZ 0.95。 |
| 4.15–4.16 | 修後通過 | `gates RJ01483219`：prepare 量測 5710 物件、roundtrip `OK resources.assets 物件 5710 bytes 相同 JSON 重新 dump 15/15`、export 3701 條、verify、breakage 全綠，命令列用的是 `.venv-unity\Scripts\python.exe`（venv 真的被轉接器用到）。第一次 zero_import 被新加的空轉偵測擋下：Unity 的 import_script 對零譯文與「譯文＝原文」都刻意不寫檔（`套用 0 條譯文到 0 張表`），identity 也救不了；改為轉接器宣告 `zero_import_noop_ok = True`（摘要註明「往返由 roundtrip_test.py 涵蓋」），未宣告的引擎仍會被擋。4.16 交接包：**`RJ01483219-001-to-translator-20260912-1134.zip`**（17 個檔案，90409 bytes），已在 `G:\我的雲端硬碟\GalTransl-Agent-Tools\RJ01483219\handoff\`；HANDOFF.md 已寫明「只驗流程、unpack 會覆蓋 script.json 請靠備份」。 |

本分支上做的修正（commit 清單）：

- `7509ff3` fix(windows): 測試隔離 handoff_dir、子行程 UTF-8 解碼、uv 不在 PATH 也找得到（`core/config.py` 環境變數空字串也覆蓋；`core/site.py` find_uv／Win11 標籤；`core/adapter.py` `_safe_write`；三個測試檔 UTF-8；`tools/setup_env.sh` find_uv_bin）
- `6c5c0e5` fix: 零翻譯導入空轉偵測、RPG Maker 改 identity 往返、命令列可貼回 Git Bash（`core/adapter.py` `_cmdline` 雙引號、log LF、`zero_import_fill`；`core/script_json.identity_translations`；`engines/rpgmaker_mv_mz/adapter.py`；`setup_env.sh` PYTHONUTF8）
- `6d6a7a8` fix(unity): 零翻譯導入不寫檔宣告為正常（`zero_import_noop_ok`）
- 本次 docs commit：本節紀錄、`docs/two-site.md` §8 補 Store 版 Python 的 uv 位置

沒解掉的問題：

- `agt detect` 對資料夾印的提示 `$PY agt.py handoff unpack projects\demo\handoff` 反斜線沒加引號，貼回 Git Bash 會被吃掉（只影響提示文字，`_cmdline` 那條已修；agt.py 裡零散的提示字串未統一處理）。
- Google Drive 雲端上傳完成時間無法從筆電端確認（Drive 桌面版是非同步上傳；Drive 連接器帳號似乎看不到這個資料夾）。請 dgxluna 端 unpack 時回報 zip 出現的時間。
- `roundtrip`／`zero_import` 對 RPG Maker 從「空譯文」改成「identity」是行為變更（dgxluna 端請確認 `test_rpgmaker_pipeline` 仍過，理論上 json 模式比對一定過）。
- 這台的 `git` 沒有全域身分，本 repo 以 `git config user.name "Jim Hsieh"`、`user.email st70712@gmail.com`（repo-local）提交；要改請自行 `git config`。
- `.sh` 在 `core.autocrlf=true` 下 checkout 成 CRLF（`tools/llama_server.sh`），實測 Git Bash 能跑 CRLF 腳本，暫不加 `.gitattributes`。

## 6. 收尾（筆電端）

1. 清掉測試用專案：`rm -rf projects/demo projects/demo2`（真實遊戲的專案可留）。`git status --short` 應乾淨（除了本檔與你的修正）。
2. `git add -A && git commit -m "docs(windows): 實機端驗收紀錄" && git push origin feat/two-site`。
3. 告訴使用者：驗收紀錄已 push、交接包放在 Drive 哪裡、有沒有沒解掉的問題。

## 7. 回到 dgxluna 後（翻譯端做）

- `git fetch && git checkout feat/two-site && git pull`，看第 5 節與修正 commit。
- 用 4.16 的交接包做跨機 unpack：`agt detect ~/gdrive/GalTransl-Agent-Tools/<game>/handoff/` → `agt handoff unpack …` → `translate.py --dry-run` → `handoff pack` 回去。
- 全部合理才 `git checkout main && git merge --no-ff feat/two-site && git push`。本檔留著當日後 Windows 回歸清單；第 5 節的紀錄併進 `docs/lessons-learned.md` 後可清空。
