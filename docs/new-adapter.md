# 新增引擎轉接器

順序不能跳。每一步都是關卡，過了才做下一步；上一次的教訓是「翻完才發現格式理解錯」，回頭補救比翻譯本身還久。

## 0. 準備

```bash
cp -r engines/_template engines/<engine>
$PY agt.py init <game> --original <遊戲目錄> --engine <engine>
```

`_template/` 內容：`adapter.py`（繼承 `StandardCliAdapter`，留 `detect/prepare/package/breakage_test` TODO）、
`profile.json`（全欄位骨架）、`NOTES.md`（固定標題）、`vendor/{export_script,import_script,roundtrip_test}.py`（標準 CLI 骨架）。

## 1. 解包（prepare）

- 能把封包解成檔案樹；每個檔案用檔頭 magic（PNG/OGG/TTF…）驗證解得對。
- **統計儲存形式分布**（未壓縮／Huffman／LZ…各幾個）。之後打包要照原樣，規格允許 ≠ 這個 exe 支援。
- 只解含文字的部分即可，但要知道其他檔案在哪。
- 參考：`engines/wolf_rpg/vendor/extract_wolf.py`、`wolfrpg/dxa.py`。

## 2. 解析

- 字串在解析器裡**保持 raw bytes**，只在導出邊界 decode、導入邊界 encode。沒動到的資料才會位元組相同。
- 不認得的指令 ID／欄位要**報錯而不是猜**。
- 版本差異用「讀到什麼寫回什麼」處理，不要 fork 兩份解析器（Wolf 2.x/3.x 的 `verify_variant()` 手法）。
- 參考：`wolfrpg/filecoder.py`、`map.py`、`common_events.py`、`database.py`。

## 3. 往返驗證（硬關卡）

`vendor/roundtrip_test.py DATA`：解析 → dump → 逐位元組比對，印第一個不同位元組的位置與前後 8 bytes。
JSON 類引擎可以沒有這支，`StandardCliAdapter.roundtrip()` 會改用零翻譯導入 + JSON 相等。
**沒有 100% 不准往下。**

## 4. 導出

`vendor/export_script.py DATA -o OUT [-e ENC] [-s]` 產出 `script.json` + `format_specification.json`（格式見 `docs/script-json.md`）。

- 導出與導入走**同一個 slot 走訪**（一個 `collect_slots()` 產生 `(source_file, location, get, set)`），位址才不會兩邊不一致。
- 每個 context 一個名字，與 profile 的 `contexts` 對齊。
- 「絕不導出」：素材路徑、標籤、事件名、非字串欄位、註解；但**流程指令的字串引數可能是顯示文字**，逐個確認。
- 抽樣：每個 context 印 5 條看。

## 5. 零翻譯導入

`vendor/import_script.py import DATA SCRIPT -o OUT [-e ENC]`。把 `translated` 全清空導入，輸出必須與原資料相同（`agt gates` 會做）。
導入要：只寫 `translated` 非空的；原文對不上就拒絕（stale）；只列出實際變動的檔案。

## 6. verify + 破壞攔截

`vendor/import_script.py verify DATA OUT`：比對「不該變的東西」——指令數／ID／縮排／整數參數、標籤、檔名、選項數、地圖尺寸、資料庫數值欄位。
然後在 `adapter.breakage_test()` 刻意弄壞複本（改一個標籤、把檔名塞日文、刪一個選項），verify **必須失敗**；沒失敗代表安全網有洞。

## 7. profile.json

照 `docs/profile-schema.md`。控制碼精確列舉、分帶值／純表現；contexts 的 `default` 與 `risky` 要對得上「絕不導出」與「會改變行為」的判斷。

## 8. adapter.py

```python
from core.adapter import EngineMatch, Project, StandardCliAdapter, StepResult

class MyEngine(StandardCliAdapter):
    name = "<engine>"
    roundtrip_mode = "bytes"          # 或 "json"

    @classmethod
    def detect(cls, game_dir): ...    # 回 EngineMatch(engine, confidence, evidence, variant, source_encoding, target_encoding)
    def prepare(self, p, m): ...      # 解包到 p.extracted
    def data_dir(self, root): ...     # 資料樹不在 root 時覆寫（Wolf: root/"Data"）
    def encoding_args(self, m, which): ...   # 要傳 -e 時覆寫；which 是 "source"/"target"
    def breakage_test(self, p): ...
    def package(self, p): ...         # 依 profile.patch.steps；永遠從 p.original 的原始封包出發；寫 out/安裝說明.txt
```

`export / validate / import_ / verify / roundtrip / zero_import` 由 `StandardCliAdapter` 提供，只要 vendored 腳本符合標準 CLI 形狀：

```
export_script.py DATA -o OUT [-e ENC]
import_script.py validate SCRIPT [-e ENC] [...]
import_script.py import   DATA SCRIPT -o OUT [-e ENC] [...]
import_script.py verify   DATA OUT [-e ENC]
roundtrip_test.py DATA                      # 選用
```

`self.run(cmd, log_name=..., logs_dir=p.logs)` 會印指令、串流輸出、寫 log。

## 9. 關卡 → smoke build → 大量翻譯

```bash
$PY agt.py gates <game>        # 全綠
# /translate --limit 20 → /deliver-patch → 使用者實機 → mark user_boot_ok → 大量翻譯
```

## 10. 文件

- `engines/<engine>/NOTES.md`：辨識特徵／資料格式／絕不導出／控制碼／補丁步驟／踩過的坑／實機驗收
- `engines/<engine>/VENDOR.md`：來源、日期、md5（自己寫的也記，方便之後判斷有沒有被改）
- `docs/engines.md` 加一列
- 若有可公開的示範資料，加 `tests/test_<engine>_pipeline.py`（照 `tests/test_rpgmaker_pipeline.py`）
