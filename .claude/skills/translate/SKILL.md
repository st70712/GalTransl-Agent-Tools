---
name: translate
description: 對已導出的 script.json 跑本機 Sakura 自動翻譯（G6 小樣本或 G7 大量），再整理譯文、檢查控制碼、驗證。
---

# /translate

## 觸發
G6（smoke build 的 20 條）或 G7（實機確認後的大量翻譯）；或使用者說「開始翻譯」。

## 輸入
- `projects/<game>/exported/script.json`（有 `.agt.json` sidecar 才知道引擎；沒有就加 `--engine`）。
- 選用 `projects/<game>/glossary.txt`（自動載入）或 `--dict`。

## 步驟
```bash
PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python
PYT=/raid/home/jimhsieh/miniconda3/envs/nllb-env/bin/python
S=projects/<game>/exported/script.json
$PY  tools/translate.py -i $S --dry-run --limit 20        # 不連線：看篩選／去重／prefix 拆分是否合理
bash tools/llama_server.sh status || bash tools/llama_server.sh start
$PYT tools/translate.py -i $S --limit 20 --log projects/<game>/logs/translate.log   # G6 小樣本
# --- 使用者實機確認、mark user_boot_ok 之後 ---
$PYT tools/translate.py -i $S --log projects/<game>/logs/translate.log             # G7，用 run_in_background 跑
$PYT tools/fix_text.py $S                                  # s2twp、符號表、統一譯法、控制碼退回
$PY  tools/check_codes.py $S                               # 任何 fatal → exit 1，先修再導入
$PY  agt.py validate <game>
```
1. 沒有 `user_boot_ok` 又沒給 `--limit`，translate.py 會拒絕（`--force` 可越過，但不該用）。
2. 大量翻譯用 `run_in_background`，等完成通知；期間做準備工作。每批日誌有時間戳與吞吐（約 3 條/秒）。
3. 中斷可重跑，檢查點 `.agt_checkpoint.json` 以 `(source_file, location)` 為鍵；看到舊式 `.script_checkpoint.json` 要先刪。
4. `--priority N` 只翻優先級 ≤ N 的 context；`--include-optional` 才翻 risky 的（Wolf `string_var/condition`、RPG Maker `picture_name`…）。

## 輸出
- 填好 `translated` 的 `script.json`、`translate.log`、控制碼報告；`fix_text` 前的備份 `script.backup-<ts>.json`。

## 停下來問使用者
- G6 小樣本導入打包後（見 `/deliver-patch`）。
- 失敗率異常（>5%）或譯文明顯不對時，先查 endpoint／模型再重跑。

詳見 `docs/translation-quality.md`。
