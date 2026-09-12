# 跨引擎的教訓

每一條都是實測撞出來的，多數曾讓遊戲整個開不起來或整畫面亂碼。引擎專屬的細節在各 `engines/<x>/NOTES.md`。

## 作業原則（使用者的 13 條）

1. **先辨識引擎，不信描述。** 上次的第一個請求說是 RPG Maker，資料是 Wolf。看 exe 字串、封包 magic、目錄。
2. **動任何文字前先做往返驗證**：解析→寫回逐位元組相同。格式理解只要有一處在猜，這一步就會抓到（Wolf 三個格式差異都是被它逼出來的）。
3. **零翻譯導入也要位元組相同。**
4. **刻意弄壞複本，確認 verify 攔得住。** 安全網本身也要測。
5. **先跑通整條管線再大量翻譯**：零或少量翻譯 → import → 補丁步驟 → 打包 → **使用者實機開啟**。20 分鐘省數小時。
6. **翻譯記憶從第一輪就開。**
7. **「絕不導出」清單** + 反向檢查「流程控制的參數可能是顯示文字」（名字牌漏了，人名全消失）。
8. **量測，不猜**：原封包儲存形式分布、字型 cmap 覆蓋率、去重比例、沿用覆蓋率。
9. **官方多語版本是最好的對照組**：找不到的欄位（語言標記）用 diff 一次解決，逆向找了很久找不到。
10. **模型跑時做準備工作**；等待用 `run_in_background` 的完成通知，不寫自製監控。
11. **改導出範圍前備份譯文檔；換範圍就換檢查點。**
12. **永遠從原始封包打包**；`.orig` 備份，不刪。
13. **使用者在實機測、給精確 A/B 回報**；照他的切分縮小範圍，並交付 `out/` + 安裝說明。

## 引擎會騙你的地方（從 Wolf 的 9 個坑一般化）

| 坑 | 一般化的教訓 |
|---|---|
| 散檔不生效，只讀封包 | 「解開後刪掉封包就好」的網路說法要實測。引擎是否讀散檔要看它有沒有呼叫對應 API |
| 新封包要用與原封包相同的儲存形式 | **規格允許 ≠ 這個 exe 支援**。先統計原封包的分布再照做 |
| `Game.dat` 長度不能變 | 找出所有**長度敏感檔**；只做不改長度的原地覆蓋（1 byte 直接覆寫、字串 NUL 補滿）；長度會變的欄位不翻 |
| 翻譯記憶中途才開 | 一開始就開，否則同句多譯法讓字串比較的分支永遠不觸發 |
| 統一譯法取最常見 | 要優先選**控制碼完整**的版本 |
| 未翻譯的文字也要轉碼 | 改了字碼頁後引擎用新編碼讀**全部**文字；未翻的也得轉，連純符號台詞都會變方框 |
| 流程指令的字串參數是顯示文字 | cid 210 的 Str1 是名字牌。排除指令前逐個參數看 |
| 改導出規則要 `--merge` | 位址 `(source_file, location)` 穩定，`index` 不穩定 |
| 官方漢化版是對照組 | 未知欄位先 diff 官方版本 |

## Unity／字型（RJ01483219，2026-09-11）

- **字型覆蓋率要在翻譯前量**。Wolf 是缺字（換 Yahei），Unity 是 TextMeshPro 靜態圖集只有 7131 字、繁中缺 256 種（你／她／嗎…）。
  兩次都是 smoke build 才看到 □。G1 現在把「字型覆蓋率」列為量測項目。
- **改旗標騙不過引擎**：把串流在 .resS 的圖集 `m_IsReadable` 改 1，TMP 的檢查過了，FontEngine 拿到 null 資料指標就崩
  （crash.dmp：UnityPlayer.dll 讀 0x0）。真正可讀的貼圖是內嵌在 .assets 裡的。
- **單變數變體二分 + crash.dmp**：三個各改一項的變體都不崩、只有全改的崩，一次就定位到「畫字那一步」；
  Player.log 不一定存在，`%LOCALAPPDATA%\Temp\<公司>\<遊戲>\Crashes\` 的 crash.dmp 用 `minidump` 套件可讀例外位址與模組。
- **沒有 typetree 的 MonoBehaviour 可以用錨點解析**：先找結構規律明確的表（字元表 `{1, unicode, glyph, 1.0}`），再前後推；
  欄位宣告順序可從 `global-metadata.dat` 的字串表附近讀出。每一步都要有合理性檢查，不合就中止。
- **第三方函式庫重存不逐位元組相同**（UnityPy 少 23 KB）→ 往返關卡改為逐物件；遊戲吃不吃靠實機（本例接受）。
- **交付檔案有 30 MiB 上限**；43 MB 的 assets 要 zip 或放 rclone 掛載的 Google Drive。
- **退回原文的譯文要一併從檢查點刪掉**：fix_text 退回 5 條後重跑 translate.py，檢查點把同樣的壞譯文原封套回。fix_text 現在會清檢查點。
- **「看起來像參數的名字」先當顯示文字做單變數變體驗證**：Unity 的 `Name=みなみ` 實測只是名字牌文字（v1b 立繪正常）；Wolf 的 cid 210 Str1 也是名字牌。名字用固定對照填、不交給模型，才與對話內譯名一致。
- **環境依賴要在第一版就宣告**：UnityPy 一開始是臨時裝的，後來才補 `python_env` + `requirements.txt` + `setup_env.sh`。
  新引擎需要套件時，從一開始就走宣告路線，專案才搬得到別的機器。

## 兩站接力（實機端 Windows ↔ 翻譯端 dgxluna，2026-09-12）

- **碰遊戲檔的步驟與碰模型的步驟可以完全分開**：translate／fix_text／check_codes／validate 只讀 `exported/` + sidecar + profile，
  import 以後才要 `original/`。所以交接包只需要幾 MB；GB 級的遊戲永遠留在筆電。
- **Windows 的 junction 不被 `Path.is_symlink()` 認得**：symlink 沒權限退回 junction 之後，「is_symlink→unlink，否則 rmtree」的邏輯會把 junction 當實體目錄 rmtree。
  用 `core/fsutil.is_link`／`remove_link` 統一處理；新 adapter 建連結一律走 `fsutil.replace_dir_with_link`。
- **venv 直譯器路徑不能寫死 `bin/python`**：Windows 是 `Scripts/python.exe`（`fsutil.venv_python`）。
- **檢查點必須與 script.json 同行**：fix_text 退回時會修剪 `.agt_checkpoint.json`，translate 續跑時會讀它；分開搬就脫節。交接包兩個一起帶。
- **兩站的 agt.json 要合併不是覆蓋**：實機端記 import／package／playtest，翻譯端記 translate／fix_text；覆蓋會丟一邊。每關取時間較新的，history 聯集。
- **交接包要帶 manifest 記專案名**：`agt.json` 沒有 name 欄位，zip 檔名又可能被改；Unity 規則檔靠專案名對應，兩站名字必須一致。
- **程式碼不會跟著交接包走**：實機端在 G1–G5 改的 adapter／profile／rules 要 commit + push，翻譯端 pull；manifest 記 HEAD，不一致要警告。
- **主控台編碼**：Windows 預設 cp950，`agt.py` 與 vendored 子行程印日文／中文會炸；入口 `utf8_stdio()` + 子行程 `PYTHONUTF8=1`。
  測試用 `subprocess.run(text=True)` 讀子行程輸出也要指定 `encoding="utf-8"`，否則依 locale 用 cp950 解碼直接 `UnicodeDecodeError`。
- **關卡要確認「真的比到東西」**（Windows 驗收 2026-09-12 抓到）：RPG Maker 的零翻譯導入一直是空轉——vendored 匯入略過沒譯文的檔案，
  `0 個相同、0 個不同` 也判 ✓。安全網本身要有「比對集合非空」的檢查；RPG Maker 改 identity 譯文，Unity 明確宣告 noop 並由 roundtrip_test 涵蓋。
- **Windows 環境的細節**：Microsoft Store 版 Python 的 `pip install uv` 裝進 `…\LocalCache\local-packages\Python311\Scripts`，不在 PATH
  （用 `uv.find_uv_bin()` 找）；`platform.release()` 在 Win11 仍印 10；`core.autocrlf=true` 會把 `.sh` 檢出成 CRLF（`.gitattributes` 固定 LF）；
  `list2cmdline` 印的 `C:\Users\…` 沒引號，貼回 Git Bash 反斜線會被吃掉（含反斜線／空白的參數一律雙引號）。
- **測試不能碰真實設定**：`mock.patch.dict(os.environ, {"AGT_HANDOFF_DIR": ""})` 原本無效（空字串不覆蓋），測試交接包真的被複製到 Google Drive。
  環境變數設成空字串現在也算覆蓋。

## 工具鏈事故

- **檢查點以位置序號為鍵**（GalTransl-Angle，2026-07-15）：導出範圍從 1520 變 1816 條後沒刪 `.script_checkpoint.json`，545 條譯文靜默錯位（`防御バフ_自分` 變「攻擊增益_塞拉」）。
  對策：本專案的檢查點以 `(source_file, location)` 為鍵並記原文；看到舊式檔案一律刪。若已寫壞，用位址建立舊→新 index 映射可完整還原（前提是有備份）。
- **翻譯器破壞控制碼，結構驗證抓不到**：`\v[n]` 被刪／改字母／寫死數字，8683 條中 188 條中招。對策：`tools/check_codes.py` 是導入前硬關卡。
- **失敗哨兵比對錯**：`translate_wolf.py` 用 `!= "failed"`，但 GalTransl 寫的是 `"galtransl-v3(Failed)"`，失敗句會被當譯文存進去。本專案已修。

## Claude Code 自己的事故

- **`pgrep -f` match 到自己的命令列**：監控迴圈永遠不結束，翻譯其實 5 小時前就完成了。→ 用 `run_in_background` 的完成通知。
- **等待條件綁在之後被移動的檔案上**：`until [ -f /tmp/Data.wolf.v2 ] …` 空轉 1 小時 4 分，因為另一個指令把檔案移走了。→ 要等就等行程；不要對會移動的檔案輪詢。
- **`pgrep -f` 看不到 Claude Code 的指令**（前面有 snapshot 前綴）：要找行程掃 `/proc/*/cmdline`。
- **收工前的「沒有殘留行程」要真的查**：使用者貼了 Shell 面板證明還在跑。
- **記憶檔要回讀**：正式版一開始用了 JhengHei，回讀 memory 才想起使用者偏好 Yahei。
