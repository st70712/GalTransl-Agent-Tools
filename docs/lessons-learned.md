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

## Unity 第二例：單檔 bundle／Mono／ScriptableObject 文本（RJ01657316，2026-09-12）

- **「有轉接器」不等於「這款能跑」**：同樣是 Unity 6，第二款遊戲的三個假設全部不同（散檔→單檔 `data.unity3d`、IL2CPP→Mono、
  JSON TextAsset→`TopicCatalog` ScriptableObject），`detect` 連目錄都不認。轉接器要把「容器」「文本來源」「腳本後端」三件事分開設計，
  每一層都用資料目錄的實際長相判斷，不要寫死檔名。
- **Mono 建置的 type tree 直接從 `Managed/*.dll` 產生**（TypeTreeGeneratorAPI），比 IL2CPP 的錨點法可靠得多：119 個 MonoBehaviour
  read→save 後 raw 全部相同，一次就過。IL2CPP 也能用（`GameAssembly.dll`＋`global-metadata.dat`），下次 Unity 先試 type tree 再想錨點。
  例外：少數類別（`ImageCatalog`／`AudioCatalog`）產生的 type tree 讀不到底（`read_str out of bounds`）——只讀規則涵蓋的類別，其他一律 raw 比對。
- **MonoScript 常在別的內部檔**（bundle 裡是 `globalgamemanagers.assets`），自己解 `m_Script` 指標會漏掉 external；交給 UnityPy 的 PPtr 解析，
  而且要在掛 type tree 產生器**之前**（或暫時拿掉）讀，否則 `obj.read()` 會走 type tree 而炸在那些讀不到底的類別。
- **bundle 解壓後比檔案大十倍**：164 MB 的 LZ4HC bundle 內含 1.7 GB 的 `resources.assets.resS`（未壓縮貼圖），UnityPy 全放記憶體；
  比對資源區塊要對 memoryview 做雜湊，不要複製 bytes。LZ4 重存約 40 秒、165 MB；UnityPy 沒有 LZ4HC 編碼器，`packer="original"` 會撞 NotImplemented，
  明確用 `"lz4"`（同一種區塊格式，Unity 讀得懂——V0 變體實機存活 20 秒證實）。
- **ScriptableObject 裡「看起來像文字」的欄位大半是鍵**：`mPortrait`（立繪鍵）、`mVoice`（語音鍵）、`mJumpTo`、`mLabel`、`mIconName`，
  還有整個 `ImageCatalog`／`AudioCatalog`。規則用 `path` 明確指定要導出的葉節點，並用 `when`（`mType` 0/1）分出台詞與選項；
  `mType 2` 的 `mText` 是 `unlock:topic_001` 指令，`mType 3` 是演出列。導出後 grep 一次鍵名樣式（`シーン\d_`、`^[a-z]\d{2}_\d$`）當 G3 抽樣。
- **內嵌 Font 不一定有 CJK**：這款只內嵌 LiberationSans／PerfectDOSVGA437，三套日文 TMP 靜態圖集（7129 字＝JIS 一二級）對 Big5 常用字只有 81.7%
  （缺 你／她／嗎／說／溫／戶…）。對策改成「注入字型」：把別款遊戲抽出的 NotoSansJP OTF（`extract_font.py`）寫進 LiberationSans Font 物件的 `m_FontData`，
  Unity 內建的動態備援 `LiberationSans SDF - Fallback` 就變成 CJK 動態字型，再掛成 TMP Settings 全域備援；靜態圖集一個位元組都不動。
  這是比「靜態圖集動態化＋inline atlas（+32 MB）」小得多的單一變數。Noto 對 Big5 常用字 97.7%，剩下的 122 字（嗯／喔…）沿用 `charset_map.json` 替字。
- **Windows 上 UnityPy 開著的散檔不能 unlink**（PermissionError），暫存檔留給系統清；bundle 因為整檔讀進記憶體沒這問題。
- **一棒制在同機測試也要守**：實機端本地做「假譯文 smoke」（12 條含 你她嗎 的假譯文 + 字型注入）驗證管線與 bundle 可開，用的是 `script.json` 的副本，
  `exported/` 一個位元組都沒動，交接包裡的東西仍是翻譯端的。

- **程式碼會拿台詞原文當開關**（RJ01657316，2026-09-15）：翻完後整場黑畫面，二分證明 bundle 沒問題、只翻 `TopicCatalog` 就黑；
  DLL 裡 `mText.Contains("同じサークルに所属する")` 決定開場黑幕何時淡出。同款還有 speaker 分色用 `== "あなた"`、三句提示台詞直接寫死。
  對策是原地改 DLL 字串堆（`scan_dll_strings.py` 找、`patch_dll_strings.py` 覆蓋，新字串不能比原字串長），交付物多一個 DLL。
  **G3 抽樣清單要加一項：掃遊戲程式的字串常數，找拿顯示文字做比對的地方**——不是 Unity 專屬，Wolf／RPG Maker 事件腳本用字串比較分支也是同一類。
- **package 之後要驗交付檔內容，不是只驗 translated/**：font_inject 的 `--base` 路徑算錯，從原版注入字型蓋掉譯文，verify 早就過了、交付檔卻是日文。
  verify 綁在 import 後、字型／DLL 步驟在 package 時才跑，中間沒人再看一眼。

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

## 兩站控制通道（Remote Control，2026-09-15）

兩站的 Claude 對話可以直接傳訊。操作細節與八條實測限制在 `docs/two-site.md` §6b，這裡只放可以帶去別處的結論。

- **通道傳不了檔，所以驗證只能靠「走另一條路的雜湊」**。同一個檔案內部的自洽檢查（zip 的 EOCD、成員 CRC、
  manifest 裡的 per-file sha256）全都回答不了「這是不是對方送的那一包」——它們在半同步的檔案上一樣自洽。
  整包 digest 必須從檔案外面來：通知訊息、旁檔、或本機帳。
- **非同步雲端同步的正解不是輪詢，是「一次性、零副作用、可重跑的驗證指令 + 明確的回報話術」**。
  等就是人（或下一輪對話）再跑一次那道指令。呼應既有的「不要對之後會被移動的檔案輪詢」。
- **錯誤訊息要主動把下一個代理推離錯誤的補救動作**。`--force` 對「還沒同步完」完全無效卻很誘人，
  所以訊息裡直接寫「不要 --force，它只越過 seq」，並**把該回報對方的話寫好讓它照抄**——
  不然它會自由發揮成「請你重新打包」，浪費對方一個 seq。
- **斷線是靜默的**：整個遠端區段會從名單消失，看不出對方曾經在線。任何跨機通道都要有人工退路，不能當必要條件。
- **跨機的身分是會過期的**：只有人工命名過的 session 有可定址名字；系統給的 ref 是觀看端本地碼，不能跨機引用；
  resume 之後名字與 ref 都會換。所以名字要自報、可覆蓋、由使用者確認，不要寫死在流程裡。
- **peer 的一句話不是授權**：實機驗收、`--force`、改設定檔都不能因為另一台的代理說了而做。
  可以因為訊息去**驗證**，不可以因為訊息去**放行**。
- **失敗點要挑在最便宜的地方**：原本 sha256 是邊驗邊寫，第一個落地的偏偏是最不能半寫的 `exported/script.json`。
  改成 pre-flight 的成本幾乎是零（雜湊次數不變，只是提前），卻把「寫壞了再回滾」變成「根本沒動到」。

## 翻譯端（dgxluna，RJ01657316 首次兩站接力，2026-09-12）

- **glossary 的備註符號是 `#`，`//` 會被當成譯文**：GalTransl 的 `CGptDict` 把 `->` 與 `#` 一律換成 TAB 再切三欄，
  完全不認 `//`。`センパイ->學長 // 全篇統一` 解析出的譯文是 `學長 // 全篇統一`，整串註解被塞進 prompt 的 `[Glossary]`。
  本專案的文件（`CLAUDE.md`、`docs/translation-quality.md`）原本就寫錯 `//`，而 RJ01483219 沒有 glossary.txt，
  所以自動載入這條路是**第一次真的被走到**才爆出來。對策：寫完 glossary 一定用 `CGptDict` 載入印 `replace_word` 確認；
  純註解行用 `#` 開頭且**不能含 `->`**（含了會產生 `search_word` 為空字串的條目，空字串比對到任何文字，每個批次都被汙染）。
- **`fix_text` 的 opencc `t2jp` 退路在 dgxluna 上永遠不生效**：nllb-env 的 opencc 沒有 `t2jp.json`，
  `except Exception` 把 `FileNotFoundError` 吃掉，一律印 `t2jp 自動: 0 種`。繁→日字形（值→値、啟→啓）只能靠
  `charset_map.json` 人工帶。**「自動 0 種」不等於「沒缺字」**，要看後面的缺字清單。
- **`\r\n` 不是本 repo 在處理的**：`translate.py`／`fix_text.py`／`core/codes.py`／vendor `import_script.py` 全都只比
  `count("\n")`，CRLF 與 LF 行數相同，所以「原文 CRLF、譯文只有 LF」**不會有任何警告**（#1 交接包與 NOTES 原本都寫成
  「validate 會警告」，是錯的）。真正保住 CRLF 的是 `GalTransl/Backend/SakuraTranslate.py`：送出前把 `\r\n`／`\n`
  攤平成字面兩字元 `\n`，回來後依原文用哪一種還原。實測可靠，但每個專案還是要量一次（模型多吐／少吐一個標記就多一行少一行）。
- **只有 4 種原文的 1329 條名字牌不要送模型**：`context=speaker` 直接用固定對照填完，翻譯量從 2840 降到 1511，
  也消掉「名字牌與對話裡譯名不一致」的風險。profile 的 `speaker` context 說明本來就這樣建議。
- **`--limit` 是「去重後要送模型的條數」**，不是原始條數：套用順序是 `should_translate` → `--filter` → 翻譯記憶 → 去重 → `--limit`。
  先填好名字牌再下 `--filter`，篩出來的數字會跟著變（58 → 31）。
- **smoke 樣本要自己挑到涵蓋所有換行形狀**：HANDOFF 給的 `--limit 6 --filter 'level0/TextMeshProUGUI'` 只會拿到前 6 條，
  剛好漏掉唯一一條結尾單獨 `\n` 的 UI 標籤。改成列舉 path_id（`@(131|132|133|134|139|140)#`）才測得到。
- **訊息窗排版要量原文，不能只看 `line_count` 警告**：原文的「最多幾行、單行最寬幾個半形」是開發者自己排給訊息窗的，
  就是上限（RJ01657316：3 行／49 寬，235 條原文用滿 3 行）。模型會超——5 條吐成 4 行、6 條單行最寬 56。
  `line_count` 只比行數，**抓不到「行數沒變但某行變寬」**。對策：G8 量「最大行數」與「單行最大寬」兩個數字，
  超出的用標點優先重排壓回去（不改用詞就排得進：先依標點切塊、塊跟著標點留在塊尾，所以行首不會是逗號；
  塊本身超寬才硬切，且不在標點前切）。
- **opencc `s2twp` 會過度轉換，而且每次 `fix_text` 都會再犯一次**：`貞操觀念的` → `貞操觀唸的`
  （`貞操觀念` 單獨轉卻不會，看上下文）。事後手改沒用，下次跑 fix_text 又被轉回去。
  對策：放進 `charset_map.json` 的**詞級**鍵（多字元鍵），它跑在 step 7、opencc 在 step 1，擋得住。
  s2twp 也會**漏轉**：`想象` 沒變成 `想像`（9 條）。G8 要掃一份大陸用詞／過度轉換清單。
- **`fix_text` 的統計數字不是淨變更數**：`簡繁正規化 7`／`缺字替換 6` 是各步驟碰過的條目數；
  opencc 把 `恩` 轉成 `嗯`、替字表再換回 `恩`，一來一回淨變更 0。要確認有沒有真的變，就連跑兩次 diff
  （RJ01657316 實測第二次輸出逐位元組相同，已收斂）。
- **模型會留下日文敬稱**：`後輩ちゃん` 有 41 條翻成「學妹醬」、97 條翻成「學妹」。glossary 寫了 `後輩ちゃん->學妹`
  也只是建議，不是強制。G8 要統計同一原文的譯法分布之外，也要掃「醬／桑／君」這類殘留敬稱。
- **`agt detect <handoff_dir>/<game>` 找不到交接包**（已修）：`core/handoff.pick_latest` 原本用 `glob("*.zip")` 只看當層，
  但 `handoff pack` 是複製到 `<handoff_dir>/<game>/handoff/`，剛好差一層（同函式的 `_game_hints` 用的卻是 `rglob`，
  所以遊戲特徵找得到、交接包找不到）。CLAUDE.md 第 6 節寫「收方 `agt detect <那個資料夾>`」，是文件與行為不一致。
  修法：當層找不到才往下找一層。**只找一層**——`<handoff_dir>` 底下是多個遊戲，整棵 rglob 會把別款遊戲的包混進同一個候選清單，
  `unpack` 又是「取 seq 最大的」，混到別款就會收錯專案。目錄本身是交接包或專案時仍優先當它自己，不掃子目錄。
- **`unpack` 前先切好分支，repo 不同步警告就不會出現**：manifest 記的 `repo_head` 是實機端 pack 時的 HEAD
  （這次在 `feat/unity-bundle-mono`，不是 main）。在 main 上 unpack 會警告；先 `git fetch && git checkout <分支>` 再收就乾淨。
- **有些句子翻完就不再自由了**（2026-09-15 收尾補）：被程式碼 `Contains`／`==` 綁住的台詞，譯文成了程式的一部分。
  潤稿、重譯、換用詞之前先看 `engines/<x>/rules/<專案名>.json` 的 `dll_strings`：那裡列的句子改了，
  DLL 常數要一起改，而且**新字串的 UTF-16 長度不得超過日文原字串**（原地覆蓋字串堆，不能變長）。
  翻譯端改了這種句子而沒說，實機端不會發現——verify 過、import 過，遊戲卻在那一幕卡住。
  對策：把受約束的 index 寫進 `HANDOFF.md`，並在 `glossary.txt` 用註解行標記。

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
