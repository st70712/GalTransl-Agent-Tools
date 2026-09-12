# Unity（JSON 表格 TextAsset）NOTES

首例：RJ01483219《秘密のシェアハウスせいかつ》v1.07（OneUp／いぬすく圈，2026-09-11）——散檔、IL2CPP、JSON 表格 TextAsset。
第二例：RJ01657316《騙され呑みニケーション》v1.0.2（おうち開発室，2026-09-12）——單檔 data.unity3d、Mono、ScriptableObject 文本，見檔尾。
同作者的下一款很可能沿用同一套表格系統，`rules/RJ01483219.json` 可直接當範本。

## 辨識特徵
- `UnityPlayer.dll`、`<標題>_Data/globalgamemanagers`（開頭 64 bytes 內有版本字串，如 `6000.0.58f2`）
- `GameAssembly.dll` + `_Data/il2cpp_data/` → IL2CPP；`_Data/Managed/*.dll` → Mono
- `_Data/StreamingAssets/aa/` → Addressables（`*.bundle` = UnityFS，LZ4）
- 本轉接器適用的關鍵：`resources.assets` 內有 `{\n    "Rows": [` 開頭的 TextAsset（`agt detect` 會用標準庫粗掃並在 evidence 列出數量）

## 資料格式
- SerializedFile v22，**沒有 type tree**（IL2CPP 發行版常態）。TextAsset 不需要 type tree（`m_Name` + `m_Script`），
  MonoBehaviour（例如 TextMeshProUGUI 的 `m_text`）沒有 type tree 就只能拿 raw bytes。
- JSON 表：`﻿{"Rows":[{"ID":1,…},…]}`，BOM 開頭、4 空白縮排、非 ASCII 不轉義、字串內換行是 `\n` 逃脫。
  `json.dumps(indent=4, ensure_ascii=False)` 可逐字元重現，**除了浮點數**：C# 印 `0.20000000298023225`，
  Python repr 是 `…224`（同一個 double）→ `unity_tables.FloatText` 保留原始字面。
- 劇本表（`Data_Event`、`Data_Osawari`）欄位 `ID / Command / Command2 / Command3 / Arg1 / Arg2 / WaitType`：
  - `DrawMessageWindow`：`Arg1 = "Name=みなみ,Anim=Sway"`（說話者＋動畫參數），`Arg2` = 台詞（真換行）
  - `Choice`：`Arg1 = "Choice1=今日は寝る,Choice2=夜這いに行く"`
  - `Dialog`：`Arg1 = "Message=…\\n…"`（系統對話框，字面 `\n`）
  - `*ev_xxx`：標籤定義列，`Arg1` 是開發者給標籤的說明（不顯示）；`if / else if / else` 的 `Arg2` 是條件說明（不顯示）
  - `Command2` 是資產路徑（`Assets/…/Scene2_Voice.prefab`）
- 其他表：`Data_SystemMessage(Message)`、`Data_Item/Data_Collection(Name, Message)`、`Data_MySkill(Title, Explain)`、
  `Data_Dokyo(NextText)`、`Data_TotalEvent(TitleName＝話題選單；Comment＝備註)`、`Data_SkinshipMessage(Message, SpeachCharaName)`、
  `Data_ChatGroup(Message＝喘息；Memo＝備註)`、`Data_Lottery(Message)`。
- `Data_SystemMessage` 的 `ID` 不唯一 → 地址用序號 `Rows[#12]`。
- 佔位符 `<param#her_name>`（115 條台詞）執行期換成女主角名；富文本 `<size=…>…</size>`。

## 絕不導出
- `Command`（指令名／`*ev_` 標籤名）、`Command2/3`（資產路徑）、`Name=` 以外的複合子鍵（`Anim=`、`C1=…` 條件）
- `Memo`、`Comment`、`*ev_` 列的 `Arg1`、`if/else` 的 `Arg2`——開發者備註
- `ScenarioName`、`IconPath`、`GraphicPath`、`SystemMessage.Name`——鍵與路徑
- **複合欄位的譯文不能含半形逗號／等號**（會破壞 `k=v,k=v` 解析）；import 會自動換成全形並警告，validate 會列為必須處理

## 控制碼
- value：`<param#…>`（遺失＝名字不見，退回原文）；style：TextMeshPro 標籤（`<size>`、`<color>`…）
- `literal_newline_policy: keep`——`Dialog` 指令本來就用字面 `\n`
- `speaker`（`Name=みなみ／あなた／メシア`）：**實測只是名字牌顯示文字**（v1b：翻成 南／你／彌賽亞 後立繪、表情正常），profile 已改為預設翻譯。
  做法：用固定對照直接填（みなみ→南、あなた→你、メシア→彌賽亞、2人共→兩人），不交給模型，才會與對話內譯名一致

## 補丁步驟
- 交付物只有 `<標題>_Data/resources.assets`（覆蓋，原檔改 `.orig`）。
- **UnityPy 重新序列化的 SerializedFile 不逐位元組相同**（本例 10,407,440 → 10,384,064 bytes；標頭／對齊不同，
  5710 個物件 raw 全部相同）。G2 往返因此定義為「逐物件相同 + 15/15 表重新 dump 與原文相同」，
  遊戲吃不吃要靠 smoke build 實機確認。
- import 只重寫「有譯文變動」的 asset 檔；零翻譯導入（或譯文＝原文）不會產生任何檔案（verify 視為通過）。
  轉接器因此宣告 `zero_import_noop_ok = True`，G4 不算空轉；真正的往返由 `vendor/roundtrip_test.py`（逐物件 + 15/15 表 dump）負責。

## 踩過的坑
0. **TMP 動態字型化的正確組合**（RJ01483219 實測）：`m_AtlasPopulationMode=1`＋`m_SourceFontFile` 指到內嵌 Font（跨檔要加 external）
   ＋圖集 Texture2D `m_IsReadable=1`＋**`m_FreeGlyphRects` 清空**＋`m_IsMultiAtlasTexturesEnabled=1`。
   少了「清空空位」會崩：建置時不可讀的圖集沒有 CPU 像素副本，事後改可讀旗標只騙過 TMP 的檢查，
   `FontEngine.TryAddGlyphToTexture` 往舊圖集畫字時 null 指標存取（crash.dmp：UnityPlayer.dll 讀 0x0）。
   清空後 TMP 會另開執行期新建的圖集。三個單項變體（只可讀／只動態／動態＋來源）都不崩、字仍 □，是二分出來的。
   **更正（變體 F 仍崩，兩個 crash.dmp 例外位址與堆疊完全相同 UnityPlayer.dll+0xd982a3）**：清空空位沒有改變路徑，
   TMP 通過可讀檢查後第一次呼叫 `FontEngine.TryAddGlyphToTexture` 就拿舊圖集的 CPU 資料指標，串流在 .resS 的圖集沒有 CPU 副本 → null。
   結論：**只改 m_IsReadable 旗標不夠，圖集像素必須內嵌在 .assets 裡**（Unity 自己建置可讀貼圖時也是內嵌、不串流）。
   `tmp_font_dynamic.py --inline-atlas` 會把 .resS 的像素搬進 Texture2D 的 image data 並清空 m_StreamData（變體 H，.assets 變大 32 MB）。
   **變體 H 實機通過（2026-09-11 23:30）**：戶／溫／另 正常顯示，遊戲穩定。`agt package` 現在會自動跑這一步（profile `patch.tmp_dynamic_font`）。
   OTF 本身沒有的字（嗯 等 48 個）用 `projects/<game>/charset_map.json` 替字（fix_text 自動套用）。
   可重用：`charsets/NotoSansJP-Regular.txt`（內嵌 OTF 的 16,734 字字元集）與 `charsets/NotoSansJP-Regular.map.json`（已驗證的替字表），
   下一款同字型的遊戲直接複製到 `projects/<game>/font_charset.txt`、`charset_map.json`。
   備案 G（未用到）：清空 glyph／character 表、圖集換成 1×1 內嵌佔位，讓 TMP 走「width<=1 → Reinitialize + ResetAtlasTexture」全動態路徑。
1. `str.lstrip()` 不會去掉 BOM `﻿` → 判斷 JSON 開頭要先剝 BOM（一開始 0 張表被認出來）。
2. 浮點數字面（見上）→ 15 張表有 1 張 dump 不一致，靠 `FloatText` 解決。
3. `Name=` 不只出現在對話：`PlaySE`／`DrawBG` 的 `Arg1` 也是 `Name=<資產名>` → 規則必須限定 `when_command`。
4. 純標準庫的長度前綴猜測會抓錯（TextAsset 的 m_Script 前不是單純 4-byte 長度）→ 直接用 UnityPy。

## 翻譯階段的坑
- **模型會丟 `<param#her_name>`**（名字當主詞時特別容易，5/1947），fix_text 退回、重翻仍可能再丟；最後 1 條手動補譯。
- **退回的條目必須同時從 `.agt_checkpoint.json` 移除**，否則下次 translate.py 會把壞譯文原封套回（fix_text 現在會做）。
- 字面 `\n`：`Data_SystemMessage` 原文就用字面 `\n`，`Data_Event` 用真換行 → profile 用 `convert_if_original_lacks`（原文沒有字面 `\n` 才轉成真換行）。
- 模型會把 みなみ 譯成「南」，但名字牌（Name=，speaker 未翻）與 `<param#her_name>` 預設值（C# 常數）仍是 みなみ → 名字一致性要先決定。
- 偶發退化輸出（「好大啊啊啊啊…」重複到吃掉 `</size>`）：check_codes 的富文本標籤／控制碼檢查會攔到。

## 交付紀錄
- RJ01483219 v1（2026-09-11）：dialog/choice/system/database 100%，名字牌未翻 → 實機通過。
- v1b（2026-09-12）：加名字牌 1318 條 → 實機通過，**最終版**。使用者決定不處理 `<param#her_name>` 預設值（遊戲無改名功能、C# 常數仍是 みなみ）與標題選單假名 UI。

## 實機驗收
- 遊戲開得起來（重新序列化的 resources.assets 被接受）——最大未知數
- 開場對話顯示中文、不是方框（內建 NotoSansJP SDF 字型圖集缺字風險；缺字請回報是哪些字）
- `<param#her_name>` 有被換成名字；多行台詞沒有超出訊息框；`<size>` 標籤沒有字面顯示
- 第二階段：level0/level1 的 TextMeshProUGUI 標籤（122+4 個，raw 位移 88 起為 `m_text`）、bundle 內 MonoBehaviour（有 type tree）

## 第二例：RJ01657316《騙され呑みニケーション》v1.0.2（おうち開発室，2026-09-12，兩站接力）

同引擎、不同作者，三個假設全部翻掉：**單檔 `data.unity3d` bundle、Mono、文本在 ScriptableObject**。轉接器因此改成「容器／文本來源／腳本後端」三層各自判斷。

### 辨識特徵
- `*_Data/` 只有 `data.unity3d`（UnityFS v8，標頭 64 bytes 內有 `6000.4.1f1`）、`*.resource`、`Managed/*.dll`、`boot.config`；沒有 `globalgamemanagers` 散檔。
- `Managed/ProjectRuntime.dll`＝遊戲程式（沒有 Assembly-CSharp）；無 `GameAssembly.dll` → Mono。
- `agt detect` 信心 0.6（bundle 內容看不到 JSON 表），evidence 會說「文本在哪由 rules/<專案名>.json 決定」；`init` 照常。

### 資料格式
- bundle 內：`globalgamemanagers`、`globalgamemanagers.assets`（2276 個 MonoScript 都在這）、`sharedassets0–2.assets`、`level0–2`、`resources.assets`（4744 物件）、
  三個 `.resS`（`resources.assets.resS` 解壓後 **1.7 GB**：整包 LZ4HC 壓成 164 MB）。
- 文本：`resources.assets` 的 `TopicCatalog`（ScriptableObject，path_id 3706）：
  `mTopics[62]{mTopicId, mLabel(話題標題), mIconName, mIsInitial, mNeedDrunkLevel, mLines[]}`，
  `mLines[1510]{mType, mLabel, mSpeaker(後輩／あなた／店員), mPortrait(立繪鍵), mText, mJumpTo, mVoice(語音鍵)}`；
  `mType` 0＝台詞、1＝選項（`mJumpTo` 是目標）、2＝指令（`mText`=`unlock:topic_001`）、3＝演出（`mPortrait`=`シーン1_カットイン_注文_*`）。
  換行是 **`\r\n`**（CSV 匯入的痕跡），譯文要保持 `\r\n`。
- UI：`TextMeshProUGUI.m_text`（118 個，66 個含日文；level0 同意畫面、level1/2 與 resources 的 prefab 重複各一份）。
- 沒有 type tree：`Managed/*.dll` → `TypeTreeGeneratorAPI`（`unity_tables.typetree_generator`），`TopicCatalog` 與 118 個 TMP 物件 read→save raw 全部相同。
  `ImageCatalog`／`AudioCatalog`／`UniversalRenderPipelineGlobalSettings` 的 type tree 讀到底會 `read_str out of bounds`——不在規則內就不讀。
- 位址：`source_file = data.unity3d#resources.assets/TopicCatalog@3706`、`location = mTopics[3].mLines[12].mText`；UI 是 `data.unity3d#level0/TextMeshProUGUI@131` + `m_text`。
- 規則檔 `rules/RJ01657316.json` 的 `monobehaviours` 區塊：`path`（`[*]`＝陣列每個元素）、`context`、`speaker_from`（同層欄位）、`when`（同層欄位值，`{"mType":[0]}`）。
- 導出 2840 條：dialog 1334、speaker 1329、choice 111（話題標題 40 + 選項 71）、ui 66。

### 絕不導出
- `mCsvFolder`、`mTopicId`、`mIconName`、`mLines[].mLabel`／`mJumpTo`（跳躍標籤）、`mPortrait`（立繪鍵）、`mVoice`（語音鍵）、`mType 2/3` 列。
- `ImageCatalog`（18,089 個日文字元全是圖片鍵）、`AudioCatalog`（SE 名 くぱぁ／嚥下）、`SlotLabel`／`GenreSlotTable`／`ViewManager`／`Scene2HelpView`（編輯器分類標籤）。
- G3 抽樣用 grep 確認：導出裡沒有 `シーン\d_`、`^[a-z]\d{2}_\d$`、`unlock:` 樣式的字串（0 條）。

### 控制碼
- 沒有 `<param#…>`；富文本標籤規則沿用。`\r\n` 換行：validate 會對「原文 `\r\n`、譯文只有 `\n`」給警告，fix_text／翻譯端請保持 `\r\n`。
- speaker：`後輩`／`あなた`／`店員`（各 665／661／2）＋ 1 條 `あなた 後輩`；用 glossary 固定對照，不交給模型。

### 補丁步驟
- `import` 只重寫整個 `data.unity3d`（`save(packer="lz4")`，約 40 秒、165 MB；原檔 LZ4HC，UnityPy 沒有 HC 編碼器）；`verify` 展開 bundle 逐內部檔比對：
  未涵蓋物件 raw 相同、規則涵蓋的 MonoBehaviour 只有規則路徑上的字串葉節點可以不同、`.resS` 雜湊相同。
- `breakage`：刪掉 `mTopics[0].mLines` 最後一個元素 → verify 報「不在規則內的欄位被改了（長度 33 → 32）」✓。
- 交付物：`騙され呑みニケーション_Data/data.unity3d`（165–169 MB）→ zip 放 `<handoff_dir>/RJ01657316/`；安裝說明備份行 `ren data.unity3d data.unity3d.orig`。
- 字型（見下）：`profile.patch.font_inject` 在 `package` 時自動跑 `inject_font.py`，字型檔在 `projects/RJ01657316/font/NotoSansJP-Regular.otf`
  （用 `extract_font.py` 從 RJ01483219 抽出，不進 git）。

### 字型
- 三套 TMP 靜態圖集 NotoSansJP-Bold／Medium（sharedassets0）、KiwiMaru-Medium（resources）各 7129 字＝JIS 一二級，4096×8192 串流在 bundle 內的 `.resS`。
  對 Big5 常用字 **81.7%（缺 989）**：你／她／嗎／說／溫／戶／喔／啊／呢 全缺——不處理就沒法翻。
- 內嵌 Font 只有 `LiberationSans`（902，350 KB）與 `PerfectDOSVGA437`，**沒有 CJK 字型檔**，所以第一例的「靜態圖集動態化」沒有來源可指。
- 對策 A（`inject_font.py`，單一變數）：`LiberationSans.m_FontData` ← NotoSansJP-Regular.otf（4.5 MB，16,734 字，對 Big5 常用字 97.7%）；
  Unity 內建的 `LiberationSans SDF - Fallback`（3693，動態、多圖集、來源＝902）跟著變成 CJK 動態字型，更新其 `m_FaceInfo`；
  `TMP Settings.m_fallbackFontAssets = [3693]`。靜態圖集完全不動。剩下 122 字（嗯／喔…）用 `charset_map.json`（沿用 `charsets/NotoSansJP-Regular.map.json`）替字。
- 對策 B（未做）：`tmp_font_dynamic.py` 改 type tree 版並支援 bundle 內 `.resS`，把對話用的那套靜態圖集動態化（+32 MB）。A 出 □ 才做。

### 踩過的坑
1. `script_classes` 自己解 `m_Script` 指標（offset 12）全錯：實際 offset 16（`m_Enabled` 對齊到 4），且 fileID=1 指向 `globalgamemanagers.assets` 的 external。
   改用 UnityPy 基底解析＋PPtr，但要在掛 type tree 產生器之前（或暫時拿掉）呼叫，否則 `obj.read()` 走 type tree 炸在 `ImageCatalog`。
2. 資源區塊 1.7 GB：比對用 memoryview 雜湊（`resource_digests`），不複製 bytes；roundtrip 兩個 env 同時在記憶體約 4 GB，筆電 32 GB 沒問題。
3. Windows 上 UnityPy 開著的散檔 `unlink` 會 PermissionError（RJ01483219 迴歸時撞到）；roundtrip 不刪暫存檔。
4. `packer="original"` 對 LZ4HC 是 NotImplemented → 明確 `"lz4"`。

### 實機驗收
- 原版 playtest 15 s 存活；V0（假譯文 12 條，只重存 bundle）20 s 存活；A（V0 + 字型注入）20 s 存活，無 crash.dmp／Player.log（2026-09-12 20:33）。
- **使用者目視變體 A 通過（2026-09-12 20:45）**：開場旁白中文正常，你／她／嗎／戶／溫／另 全部畫出——重存的 bundle 遊戲吃、TopicCatalog 譯文生效、備援字型注入生效。
  瑕疵：備援字是 Noto **Regular**，對話主字型是 NotoSansJP-**Bold** 靜態圖集，缺字部分肉眼可見細一號；要一致得注入 Bold 版字型檔（TMP 備援不會套粗體）。
  同意畫面（level0 的 TextMeshProUGUI）這次沒出現——推測首次開原版時已回答過、狀態存在 LocalLow/Unity/ 之下；UI 譯文是否顯示要等清除狀態或翻譯端 smoke 再看。
  已 `mark user_boot_ok`；翻譯端可依 CLAUDE.md §6 例外自行 mark 直接進 G7。
