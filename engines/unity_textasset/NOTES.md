# Unity（JSON 表格 TextAsset）NOTES

首例：RJ01483219《秘密のシェアハウスせいかつ》v1.07（OneUp／いぬすく圈，2026-09-11）。
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
- `speaker`（`Name=みなみ／あなた／メシア`）標為 optional+risky：不確定遊戲是否也拿它查角色資產，實機確認前不翻

## 補丁步驟
- 交付物只有 `<標題>_Data/resources.assets`（覆蓋，原檔改 `.orig`）。
- **UnityPy 重新序列化的 SerializedFile 不逐位元組相同**（本例 10,407,440 → 10,384,064 bytes；標頭／對齊不同，
  5710 個物件 raw 全部相同）。G2 往返因此定義為「逐物件相同 + 15/15 表重新 dump 與原文相同」，
  遊戲吃不吃要靠 smoke build 實機確認。
- import 只重寫「有譯文變動」的 asset 檔；零翻譯導入不會產生任何檔案（verify 視為通過）。

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

## 實機驗收
- 遊戲開得起來（重新序列化的 resources.assets 被接受）——最大未知數
- 開場對話顯示中文、不是方框（內建 NotoSansJP SDF 字型圖集缺字風險；缺字請回報是哪些字）
- `<param#her_name>` 有被換成名字；多行台詞沒有超出訊息框；`<size>` 標籤沒有字面顯示
- 第二階段：level0/level1 的 TextMeshProUGUI 標籤（122+4 個，raw 位移 88 起為 `m_text`）、bundle 內 MonoBehaviour（有 type tree）
