# Windows 實機端驗收清單（分支 `feat/two-site`）

> 給筆電端 Claude Code 的交接文件。**這次的任務是驗證，不是做遊戲中文化**：照下面的項目逐條跑、把結果填進第 5 節、
> 修掉能修的、commit 到同一分支、push 回 GitHub。dgxluna 端看完結果才 merge 進 main。
> 背景：`CLAUDE.md` 第 2、3、6 節與 `docs/two-site.md`（兩站接力：實機端 Windows ↔ 翻譯端 dgxluna）。

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

環境：Windows 版本＝　　；Python＝　　；uv＝　　；開發人員模式＝開／關；Git Bash 版本＝　　；Google Drive 桌面版＝有／無，路徑＝　　

| # | 結果 | 備註（關鍵輸出、錯誤、修了什麼） |
|---|---|---|
| 1.1–1.7 | | |
| 2.1 | | 幾個測試、幾個失敗 |
| 2.2 | | vendor/Game 是否完好 |
| 2.4–2.5 | | symlink 還是 junction |
| 2.6–2.7 | | |
| 2.8–2.9 | | |
| 3.1–3.4 | | |
| 4.1–4.10 | | |
| 4.11–4.14 | | 用哪款遊戲、exe 路徑 |
| 4.15–4.16 | | 交接包檔名 |

本分支上做的修正（commit 清單）：

- 

沒解掉的問題：

- 

## 6. 收尾（筆電端）

1. 清掉測試用專案：`rm -rf projects/demo projects/demo2`（真實遊戲的專案可留）。`git status --short` 應乾淨（除了本檔與你的修正）。
2. `git add -A && git commit -m "docs(windows): 實機端驗收紀錄" && git push origin feat/two-site`。
3. 告訴使用者：驗收紀錄已 push、交接包放在 Drive 哪裡、有沒有沒解掉的問題。

## 7. 回到 dgxluna 後（翻譯端做）

- `git fetch && git checkout feat/two-site && git pull`，看第 5 節與修正 commit。
- 用 4.16 的交接包做跨機 unpack：`agt detect ~/gdrive/GalTransl-Agent-Tools/<game>/handoff/` → `agt handoff unpack …` → `translate.py --dry-run` → `handoff pack` 回去。
- 全部合理才 `git checkout main && git merge --no-ff feat/two-site && git push`。本檔留著當日後 Windows 回歸清單；第 5 節的紀錄併進 `docs/lessons-learned.md` 後可清空。
