# bishop_bsx — Bishop 引擎（BSXScript）：目前只有指標，尚未接入

既有工具在 GitHub：https://github.com/st70712/GalTransl-BISO（repo 名叫 BISO，內部文件稱 GalTransl-BGI／Bishop 引擎）。
本 repo 沒有搬入，因為還沒有第二款 Bishop 遊戲需要；要用時照 `docs/new-adapter.md` 接。

## 已知的格式事實（來自該 repo）

| 項目 | 內容 |
|---|---|
| 封包 | `*.bsa`，簽章 `BSArc`，版本 1–3，階層式目錄；`extract_bsa.py` 只解不包（GARbro 移植） |
| 圖片 | `BSG`（`BSS-Graphics`）BGRA32/BGR32/Indexed8，None/RLE/LZ；`convert_bsg.py`（需 PIL+numpy，選用） |
| 腳本 | `bsxx.dat`，magic `BSXScript 3.1`，文字 **UTF-16LE**，雙 NUL 結尾 |
| 表格位移 | 由檔頭 0x88–0xA4 讀：名字索引表／名字字串表／對話索引表／對話字串表各 (offset, size)，索引以**字元**為單位（uint32）；資料區指標在 0x80。**要動態讀，不能寫死**（v1/v2 寫死過，v3 才改對） |
| script.json | 同信封，但條目是 `{index, offset, original, translated, context}`：**鍵是 `offset`**（字串在原檔的位元組位移），沒有 `source_file/location/speaker`；`context` ∈ `name/dialog/other`（導出端啟發式，導入端依 offset 落在哪張表重新分類） |
| 導入 | 複製 `[0, name_index_offset)` 原樣（檔頭與程式碼區不動）→ 重建名字索引表與字串表 → 對話同 → `struct.pack_into` 回寫四組 offset/size 與 0x80。檔案可以變長 |
| check | magic 相同、程式碼區逐位元組相同、檔頭指標連續、索引表可解析、抽樣對話、檔案大小合理 |
| 控制碼 | 沒有處理任何控制碼／換行；字串原樣進出 |
| 編碼／字型／打包 | 無 cp932/cp950 處理、無字型替換、無 BSA 重新打包（交付物是改過的 `bsxx.dat` + `.bak`） |

## 接入時要做的事

1. 把該 repo 的 `extract_bsa.py`、`export_script.py`、`import_script.py`（v3）、`check_script.py`、`doc/` 搬進 `vendor/`，寫 `VENDOR.md`（commit、md5）。
2. `import_script.py` 的子命令是 `import / validate / check`，不是 `verify`：adapter 覆寫 `verify()` 呼叫 `check`。
3. script.json 少了 `source_file/location`：在 adapter 的 `export()` 後補 `source_file="bsxx.dat"`、`location=f"off{offset}"`，讓 `core/` 與 translate.py 的檢查點能用；導入前再去掉或讓 vendored 導入只看 `offset`。
4. 往返：零翻譯導入後檔案應與原檔相同（索引表重建後 offset 不變）；若不同，先查是否有 gap。
5. profile：`control_codes` 先留空（沒有已知碼），`contexts` 用 `name`（優先 1）、`dialog`（2）、`other`（optional）。
6. 破壞攔截：改壞一個索引或截斷字串表，`check` 必須失敗。
7. 交付：BSA 不能重打包，確認遊戲會讀散檔的 `bsxx.dat`（要實機驗證！Wolf 的教訓是散檔不生效）；不行就得寫 BSA 打包器。
