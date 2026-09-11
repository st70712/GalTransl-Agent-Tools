# `script.json` 格式

所有引擎共用同一種信封（envelope），與 GalTransl-RPGmaker、GalTransl-sister 完全相同，
所以同一支 `tools/translate.py`、`fix_text.py`、`check_codes.py` 通吃。

```json
{
  "info": {
    "game_title": "妹！せいかつ～ファンタジー～",
    "engine": "WOLF RPG Editor",          // 選用；RPG Maker 的導出工具沒有這欄
    "encoding": "utf-8",                  // 選用；來源編碼
    "version": "1.0",
    "source_dir": "Data_full",            // 選用
    "string_count": 22768                 // 必須等於 strings 長度（CI 會 assert）
  },
  "strings": [
    {
      "index": 17,                        // 顯示序號，重新導出後會變，不要拿來當鍵
      "source_file": "MapData/SampleMapA.mps",
      "location": "Ev3/Pg0/Cmd12/Str0",   // 引擎自訂的位址語法，導出與導入用同一套走訪產生
      "original": "\\E冒険は順調だ…",
      "translated": "\\E冒險很順利…",       // 空字串 = 未翻譯，導入時跳過
      "context": "dialog",
      "speaker": "",                      // 與 GalTransl 相容；Wolf 一律空字串
      "code": 101                         // 引擎指令 ID；資料庫欄位用 -1 或 0
    }
  ]
}
```

## 規則

- **對應鍵是 `(source_file, location)`**。`index` 只是顯示用；改了導出規則 index 會全部位移，位址不會。
- **不要修改** `index`、`source_file`、`location`、`original`。導入工具會拒絕原文對不上的條目（stale）。
- `translated` 為空 → 跳過；填了才寫回。所以部分翻譯永遠安全。
- 控制碼、換行結構、佔位符（`%1`）都要原樣保留，`tools/check_codes.py` 會查。
- 導出工具同時寫出 `format_specification.json`：欄位說明、context 表、控制碼表、`ai_agent_guidelines`——那是給翻譯代理讀的合約。

## 位址語法範例

| 引擎 | location |
|---|---|
| RPG Maker | `Event1/Page0/Cmd5`、`Event1/Page0/Cmd5/Choice2`、`CE3/Cmd12`、`ID7/description`、`terms/messages/actorDamage`、`gameTitle` |
| Wolf | `Ev3/Pg0/Cmd12/Str0`（地圖）、`CEv12/Cmd40/Str1`（公共事件）、`Type2/Data5/Field3`（資料庫）、`title`（Game.dat） |

## Sidecar `exported/.agt.json`

`agt export` 在導出後寫，讓 `tools/*` 不用猜引擎：

```json
{"engine": "wolf_rpg", "variant": "3.x", "source_encoding": "utf-8", "target_encoding": "utf-8",
 "data_root": ".../extracted/Data", "exported_at": "2026-09-11 15:30:00", "string_count": 22768}
```

profile 的決定順序：`--engine` > sidecar > `info.engine`；三者皆無就報錯。

## 相關檔案

- `exported/untranslated.json`：`validate -u` 輸出的未翻譯子集，結構相同，填好可直接 import。
- `exported/.agt_checkpoint.json`：translate.py 的檢查點，鍵是 `source_file\tlocation` 並記原文；原文變了就丟棄。
- `exported/script.backup-<ts>.json`：fix_text.py 寫檔前的備份。
- 舊式 `.script_checkpoint.json`（位置序號為鍵）：**看到就刪**，它曾靜默錯位 545 條譯文。
