# 兩站接力：實機端（Windows 筆電）↔ 翻譯端（dgxluna）

`CLAUDE.md` 第 2、6 節的長版。遊戲原檔太大搬不到 dgxluna 時用這個流程；遊戲搬得過來就走原本的單機流程，不需要交接。

## 1. 為什麼分兩站

| | Windows 筆電 | dgxluna |
|---|---|---|
| 遊戲原檔 | 在本機，GB 級也沒關係 | 要經 Google Drive 搬，太大就搬不動 |
| 開遊戲實機測 | ✓（代理可自己啟動抓崩潰，使用者目視） | ✗ |
| Sakura 模型（llama-server） | ✗ | ✓ |
| 兩機互連 | ✗（筆電送不了 request 到 dgxluna） | ✗ |

所以：**碰遊戲檔的步驟在筆電，碰模型的步驟在 dgxluna**，中間只搬幾 MB 的文本（`script.json` 一般 1–6 MB）。

## 2. 站點定義

| 站點 | `config.local.yaml` | 能做 | 不能做 |
|---|---|---|---|
| 實機端 `workstation` | `site: workstation` | `detect / init / prepare / roundtrip / export / zero-import / verify / breakage / import / package`、`playtest`、改 `engines/<x>/adapter.py`、量字型覆蓋率、交付 `out/` | `translate.py`（非 `--dry-run`）、`fix_text.py`、`llama_server.sh` |
| 翻譯端 `translator` | `site: translator` | `translate.py / fix_text.py / check_codes.py`、`agt validate / check-codes / status / mark`、glossary | 任何要 `original/`／`extracted/` 的步驟（`agt.py` 會擋：「此步驟要在實機端跑」） |

翻譯端的專案由 `handoff unpack` 建立，是**骨架**：只有 `exported/`、`agt.json`、`glossary.txt`、`HANDOFF.md`、`logs/`，沒有 `original/`。
dgxluna 上若某個專案有 `original/`（遊戲搬得過來），那個專案就是單機完整流程，跟兩站接力無關。

`python agt.py env` 印出：主機、Python、設定檔、站點（設定值或推薦值）、能力旗標
（`can_translate`／`can_run_game`／`uv`／`symlink_ok`／`handoff_dir`／`git`）、每個引擎專用 venv 是否就緒。**每次開工先跑。**

## 3. 接力協定（一棒制）

1. **交替**：兩站嚴格輪流工作。`agt handoff pack` 把棒交出去；收到回傳包（`handoff unpack`）之前，本站不要再改 `exported/script.json`。
2. **誰能改什麼**：
   - `exported/script.json` 與 `.agt_checkpoint.json`：只有**持棒方**能改。實機端要手改幾條譯文，改完立刻 pack 回翻譯端（或寫進 HANDOFF.md 請翻譯端改）。
   - `agt.json`：兩站各記各的關卡；`unpack` 用 `state.merge_states` 合併（每個關卡取時間較新的，history 聯集，`handoff` 區塊取對方的）。
   - `original/ extracted/ translated/ out/ variants/`：只在實機端存在，永遠不進交接包。
3. **seq 只增不減**：每 pack 一次 `seq+1`，寫進 `agt.json.handoff` 與 zip 的 manifest；`unpack` 發現 seq 不比本地新就拒收（`--force` 才覆蓋，覆蓋前會備份 `script.backup-<ts>.json`、`agt.backup-<ts>.json`）。
4. **例外**：翻譯端 pack 出去後、還沒收到回包前，若使用者直接對翻譯端說「實機開得起來」，翻譯端可以自己 `agt mark <game> user_boot_ok` 繼續大量翻譯——因為實機端不會改 `script.json`。之後 pack 的 seq 照樣遞增，實機端 unpack 不會衝突。
5. **兩站專案名必須相同**（`unity_textasset` 用 `engines/unity_textasset/rules/<專案名>.json`）。`unpack --game` 改名會警告。
6. **程式碼同步走 git**：`pack` 前 commit + push（`pack` 發現有未提交變更會拒絕，`--allow-dirty` 才放行），`unpack` 前 `git pull`。manifest 記 `repo_head`，不一致會警告「兩站 repo 不同步」。其他時候仍不主動 push、不設新 remote。
7. **`HANDOFF.md`** 同時是跨機與跨對話的交接備忘（範本 `docs/templates/HANDOFF.template.md`）：每次 pack 前在「交接紀錄」最上方加一段（本站完成／請對方做／需要對方回答／實機回報）。翻譯端 smoke 樣本要用的 `--filter` 正則寫在這裡。

## 4. 各關卡的站點與交接點

```
實機端  G0 detect/init → G1 prepare+量測 → G2 roundtrip → G3 export+抽樣 → G4 零翻譯導入 → G5 breakage
        寫 HANDOFF.md（量測數字、字型對策、smoke --filter）→ commit+push → handoff pack ──#1──▶
翻譯端  git pull → detect → unpack → translate --limit 20 --filter <開場> → fix_text → check_codes → validate
        → HANDOFF.md → handoff pack ──#2──▶
實機端  git pull → unpack → import → verify → package → 照安裝說明裝進遊戲 → playtest（崩潰分流）→ 使用者目視
        → mark user_boot_ok → handoff pack ──#3──▶          （字型／圖集要改：一次一件事，出變體，記進 HANDOFF.md）
翻譯端  unpack → G7 translate（背景）→ G8 fix_text → validate → check-codes → handoff pack ──#4──▶
實機端  unpack → G8 import → verify → package → G9 out/ + 安裝說明.txt → 使用者驗收 → mark user_final_ok
兩站    G10 各自回寫：實機端寫 NOTES.md（辨識／格式／補丁步驟／實機驗收）；翻譯端寫翻譯坑、docs/lessons-learned.md
```

- 翻譯端 smoke 翻譯的 20 條要落在一開遊戲就看得到的地方，並含原字型字元集以外的字（戶／溫／另／你／她…）；`--filter` 由做過 G3 抽樣的實機端在 HANDOFF.md 指定。
- `translate.py` 沒有 `user_boot_ok` 會拒絕大量翻譯——這個 mark 隨交接包（#3）到翻譯端，或依第 3 節例外由翻譯端自己 mark。
- `package` 永遠從 `original/` 的原始封包出發，所以只能在實機端做。

## 5. 交接包格式

- 檔名：`<game>-<seq:03d>-to-<site>-<YYYYmmdd-HHMM>.zip`，例如 `RJ01483219-003-to-translator-20260912-1030.zip`。
- 落點：本機 `projects/<game>/handoff/`；有 `handoff_dir` 時再複製一份到 `<handoff_dir>/<game>/handoff/`。
- 根目錄 `handoff.json`（manifest）：
  ```json
  {"format": 1, "game": "RJ01483219", "seq": 3, "from_site": "workstation", "to_site": "translator",
   "packed_at": "2026-09-12 10:30:00", "host": "LAPTOP", "engine": "unity_textasset",
   "repo_head": "af6e525…", "repo_dirty": false,
   "files": {"agt.json": {"size": 14679, "sha256": "…"}, "exported/script.json": {"size": 1096954, "sha256": "…"}}}
  ```
- 必帶：`agt.json`、`exported/script.json`、`exported/.agt.json`；有就帶：`HANDOFF.md`、`exported/format_specification.json`、
  `exported/untranslated.json`、`exported/.agt_checkpoint.json`（**必須與 script.json 同行**，否則 fix_text 的檢查點修剪與 translate 的續跑會脫節）、
  `glossary.txt`、`font_charset.txt`、`charset_map.json`、`unity_rules.json`、`logs/*.log`（單檔 ≤ 2 MB；`--no-logs` 不帶）。
- 絕不進包：`original/ extracted/ translated/ out/ variants/ original_zip/ handoff/`、`exported/script.backup-*.json`、`exported/.galtransl/`、`*.zip`。
- `agt.json` 的 `handoff` 區塊：`{"seq", "holder", "from_site", "packed_at", "packed_by", "bundle"}`；`agt status` 印成 `交接: #N 持棒 …`。
- `unpack` 規則：拒收舊 seq；`logs/` 只增不刪不覆蓋；每個檔案核對 sha256；`agt.json` 合併而非覆蓋。

## 6. 傳輸

| 方式 | 設定 | 注意 |
|---|---|---|
| Google Drive 共用資料夾（建議） | 兩站 `config.local.yaml` 都設 `handoff_dir`：dgxluna `~/gdrive/GalTransl-Agent-Tools`，筆電例如 `G:/My Drive/GalTransl-Agent-Tools` | rclone 掛載與 Drive 桌面版都是**非同步上傳**：pack 後 `ls -la` 看大小一致、等同步圖示變勾，再告訴使用者「可以到另一站 unpack」。收方 `agt detect <handoff_dir>/<game>/handoff/` 會列出所有包並挑最新。 |
| 使用者手動搬 | 不設 `handoff_dir` | `pack` 印出 `projects/<game>/handoff/<zip>` 路徑，請使用者搬到另一站任意位置，`unpack <zip>` 即可。dgxluna 端可用 `SendUserFile`（≤ 30 MiB）。 |

交付物 `out/`（補丁本體）不走交接包：它在實機端產生，直接給使用者裝。

## 7. 來料判斷（翻譯端）

拿到東西先 `$PY agt.py detect <路徑>`：

| `detect` 說 | 意思 | 下一步 |
|---|---|---|
| 這是交接包 | zip 內有 `handoff.json`（或 `agt.json` + `exported/script.json`） | `agt handoff unpack <zip>` |
| 這個資料夾裡有 N 個交接包 | 共用資料夾 | `agt handoff unpack <資料夾>`（取寄給本站、seq 最大的） |
| 這是既有專案 | `projects/<game>/` | `agt status <game>` 看誰持棒 |
| 這是完整遊戲的壓縮檔 | 內有 `Data.wolf`／`System.json`／`*_Data/globalgamemanagers`… | 解壓到 `projects/<game>/original_zip/`（`unzip -O cp932`）→ 對目錄 `detect`／`init` → 單機流程 |
| 引擎辨識結果 | 遊戲目錄 | 原本的 G0 |

## 8. Windows 實機端首次設定

在 Git Bash 裡開 Claude Code，依序：

1. `git clone git@github.com:st70712/GalTransl-Agent-Tools.git`（push 要用：先在筆電放 SSH key，或用 Git Credential Manager 走 https）。
2. `python --version` ≥ 3.11（官方安裝器；Git Bash 裡叫 `python`，沒有 `python3`）。
3. `pip install uv`（或 `winget install astral-sh.uv`）——`setup_env.sh` 在 Windows 不會自動裝。
4. `cp config.local.example.yaml config.local.yaml`，填 `site: workstation`、`handoff_dir`（Google Drive 桌面版的資料夾；沒有就留空）。
5. `setx PYTHONUTF8 1`（重開終端機生效；`agt.py` 與 vendored 腳本自己也會強制 UTF-8，這是保險）。
6. 需要 Unity 時：`bash tools/setup_env.sh unity_textasset`（venv 在 `.venv-unity/Scripts/python.exe`，轉接器自動用）。
7. `python agt.py env`：`can_run_game ✓`、`uv ✓`、引擎環境 ✓；`symlink_ok ✗` 也沒關係——`init`／`prepare` 會退回 junction（同一顆本機磁碟才行）。要 symlink 就開「設定 → 隱私權與安全性 → 開發人員專用 → 開發人員模式」。
8. `python agt.py engines`、`python -m unittest discover -s tests`（純標準庫測試應全過）。

Windows 上的路徑：`config.local.yaml` 可用正斜線；`agt.py` 印的指令用 cmd 風格引號，直接貼 Git Bash 也能跑。
`strings`／`xxd` 在 Git Bash 裡有（`/identify-engine` 用得到）。

## 9. 實機端啟動遊戲與崩潰分流

```bash
python agt.py playtest <game> [--exe PATH] [--wait 20] [--kill] [--dry-run]
```

- 先照 `out/安裝說明.txt` 把補丁裝進遊戲目錄（原檔改 `.orig`）；`playtest` 本身不動遊戲檔。
- 啟動 exe（從 `agt.json` 的 `game_root` + profile 的 `exe` 推斷；Unity 找與 `*_Data` 同名的 exe）、等 N 秒、印「仍在執行」或 exit code，
  列出比啟動時間新的 `%LOCALAPPDATA%\Temp\<公司>\<遊戲>\Crashes\**\crash.dmp`、`%USERPROFILE%\AppData\LocalLow\<公司>\<遊戲>\Player.log`、遊戲目錄下的 `*.log`。
- 結果記在 `agt.json` 的 `playtest` 關卡；**`user_boot_ok` 只由使用者目視後 mark**（字有沒有出來、□、亂碼，代理看不到畫面）。
- 崩潰：把 `crash.dmp` 路徑寫進 HANDOFF.md；`.venv-unity` 有 `minidump` 可解析例外位址落在哪個模組。改字型／圖集／旗標一次只改一件事，出 `variants/<字母>/` 讓使用者二分。

## 10. FAQ

- **seq 衝突（unpack 說不比本地新）**：對方沒收到你上一包就又 pack 了，或你 unpack 過同一包。先 `agt status` 兩邊比 `交接:` 那行；確定要用對方的就 `--force`（有備份）。
- **兩邊都改了 script.json**：違反一棒制。救法：用 `script.backup-*.json` 找回一邊，另一邊當 PREV，`agt export <game> --merge PREV.json` 以 `(source_file, location)` 接回譯文（只能在實機端做，因為要重新 export）。
- **repo 不同步警告**：`git pull` 後重跑；實機端改了 adapter 沒 push 的話，翻譯端的 validate／check-codes 用的 profile 可能不一樣。
- **翻譯端 `import` 被擋**：正常。翻譯端沒有 `original/`，導入／打包在實機端做。
- **翻譯端想先看看導入結果**：不行，也不需要——`validate` + `check-codes` 已經涵蓋文本層的檢查；結構驗證（verify）在實機端 import 後跑。
- **Junction 與 symlink 混用**：`core/fsutil.is_link` 兩種都認得；`init`／`prepare` 重跑會先移除舊連結再建新的。
