# rpgmaker_mv_mz — RPG Maker MV / MZ

工具來自 `GalTransl-RPGmaker`（`vendor/`，commit `be164a4`），已用於實際遊戲（GalTransl-Angle 專案，2026-07）。
完整說明在 `vendor/README.md`、`vendor/.github/copilot-instructions.md`。

## 辨識特徵

| | MV | MZ |
|---|---|---|
| 資料 | `www/data/*.json` | `data/*.json` |
| 核心 | `www/js/rpg_core.js`、`www/index.html`、`package.json`（NW.js） | `js/rmmz_core.js`、`index.html` |
| 執行檔 | `Game.exe`（nw.exe 改名） | 同 |

`export_script.py` 先找 `www/data`，沒有再找 `data`。不支援 VX Ace（`rvdata2`）。

## 資料格式

- 純 JSON；導入後以 minified（`separators=(',',':')`）寫回，所以往返用 **JSON 相等** 而非位元組（`StandardCliAdapter.roundtrip_mode = "json"`）。
- 位址 `(source_file, location)`：`Event{id}/Page{n}/Cmd{i}`（對話錨在 101）、`…/Choice{k}`、`CE{id}/Cmd{i}`、`ID{item}/{field}`、`terms/messages/{key}`、`gameTitle`、`displayName`。
- 對話 = 101（speaker 取 faceName）+ 連續 401 合併成一條（`\n` 分行）。導入時行數可多可少：覆寫既有 401、多的清空、不夠的**插入新 401**（複製 indent、追蹤 offset）。
- 選項 102：`if(s[240])` 條件只在判斷可翻性時去掉，`original` 保留；譯文若掉了，導入會補回。
- 231 圖片名只在含假名／漢字時導出（`picture_name`）；356 插件指令只在含 CJK 時導出；**MZ 357 插件指令**自 `be164a4` 起支援。
- **已知不抽取**：402、108/408（註解）、355/655（腳本）、320/324（改名）、沒有前導 101 的裸 401。
- `System.json`：gameTitle、currencyUnit、armorTypes/equipTypes/skillTypes/weaponTypes/elements、switches/variables（`debug_name`）、terms.basic/commands/params/messages。
- DB 欄位：Actors `name,nickname,profile`；Classes `name`；Skills `name,description,message1,message2`；Items/Weapons/Armors `name,description`；Enemies `name`；States `name,message1..4`。
- 導出同時產生 `format_specification.json`（`FormatSpecificationBuilder`）：給翻譯代理讀的合約。

## 絕不導出

素材檔名（`.png/.jpg/.ogg/.m4a/.wav/.mp3`）、純數字、插件參數樣式（`^[A-Z_]+\s+\d+`、`P_CALL_CE`、`MSGSE`…）、`if(s[`、ALL_CAPS 代號。
`picture_name` 翻了必須同時改圖片檔名，預設 optional；`event_name`/`common_event_name` 開發者參考用；`debug_name` 玩家看不到。

## 控制碼

不分大小寫。帶值：`\N[n]`（角色名）`\P[n]`（隊員名）`\V[n]`（變數值）`\G`（貨幣）`\I[n]`（圖標）；純表現：`\C[n] \FS[n] \PX[n] \PY[n] \{ \} \$ \. \| \! \> \< \^`。
`terms.messages` 的 `%1 %2` 是佔位符，遺失視同帶值碼遺失。
vendored 工具**不在程式裡檢查控制碼**（只寫在 spec 給模型看），所以 `tools/check_codes.py` 是必經關卡。

## 補丁步驟（`agt package`）

1. `copy_changed_json`：只複製 `translated/` 中與 `extracted/` 不同的 JSON 到 `out/www/data/`（或 `out/data/`）。
2. `write_install_notes`：`out/安裝說明.txt`——覆蓋前把原 `data/` 目錄整個備份（改名 `data.orig`）。
- 字型：MV 在 `fonts/gamefont.css`，MZ 在 `System.json` `advanced.mainFontFilename`。先量缺字再決定要不要換；本 repo 尚未自動化。
- verify：非 401 指令逐一比對（數量、code、位置）、231 圖片 ID 與參數、譯文圖片名含「」且原文沒有 → 錯誤、102 選項數、356 「」外洩警告、indent 警告、DB 不可翻欄位不變。

## 踩過的坑

1. **檢查點以位置序號為鍵**（2026-07-15）：導出範圍從 1520 增為 1816 條（補上 357）後沒刪 `.script_checkpoint.json`，545 條譯文靜默錯位（`防御バフ_自分`→「攻擊增益_塞拉」），checkpoint 新舊編號混雜。本專案的 `.agt_checkpoint.json` 以 `(source_file, location)` 為鍵並記原文；看到舊式檔案一律刪；改導出範圍前備份 `script.json`。
2. **翻譯器系統性破壞控制碼**（8683 條中 188 條）：`\v[61]` 整個消失、`\v[74]`→`\n[74]`（變數值變角色名）、`\v[75]`→字面 `75`。verify 抓不到；導入前必跑 `check_codes`。文本樣板化（188 條只 9 種句型），依句型機械修復不需重譯。
3. **專有名詞不統一**：セラ→塞拉／賽拉／賽菈／瑟拉。全域統一前確認沒有同形近似的其他角色，並防中文跨詞邊界誤命中（「比賽拉開序幕」含「賽拉」）。用 `glossary.txt` 從一開始就釘住。
4. **`Failed to load: img/pictures/…`**：對話文字被寫進圖片名欄位。verify 會攔；看到就是導入位址錯了。
5. 導入到 `-o` 新目錄時不會動原始遊戲、不建 backup；就地導入才會建 `Game/backup/`（本專案一律 `-o translated/`）。
6. vendored 工作樹的 `Game/www/data` 曾被清空，示範資料要拿 git HEAD 的版本（見 `VENDOR.md`）。
7. 使用者慣用 `translate_rpgmaker.py --priority 7`（翻到 actor 為止），對應本專案 `--priority 7`。

## 實機驗收

- 遊戲開得起來、沒有 Loading Error
- 對話、選項中文正常；多行對話沒被截斷（訊息框 4 行）
- `\N[n]`／`\V[n]` 顯示的是名字／數值不是字面碼；等級訊息數字會變
- 選單指令、道具／技能名稱與說明、戰鬥訊息（`%1`）
- 字型缺字
