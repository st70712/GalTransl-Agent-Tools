---
name: deliver-patch
description: 譯文整理完成後，導入、結構驗證、打包成 out/，填好安裝說明並交給使用者實機驗收（實機端可先 playtest 抓崩潰）；驗收後回寫文件。
---

# /deliver-patch

## 觸發
G6（smoke build）或 G8/G9（最終補丁）；`check_codes` 0 條 fatal、`validate` 全過之後。**在有遊戲檔的站點跑**（實機端或單機）。

## 輸入
- `projects/<game>/exported/script.json`（已翻譯、已 fix_text、已 check_codes）。
  兩站流程：先 `git pull` → `$PY agt.py handoff unpack <交接包>`（翻譯端寄來的 #2 或 #4），讀 `HANDOFF.md`。

## 步驟
```bash
$PY agt.py import  <game>          # 內建先跑 check_codes；translated/ 整個重建；vendored 腳本會自動 verify
$PY agt.py verify  <game>          # 0 錯誤才往下
$PY agt.py package <game>          # 依 profile.patch.steps；永遠從 original/ 的原始封包出發
ls -la projects/<game>/out/
# 實機端：照 out/安裝說明.txt 把補丁裝進遊戲（原檔改 .orig），然後
$PY agt.py playtest <game> [--wait 20] [--kill]   # 啟動、等、列 crash.dmp／Player.log；目視仍是使用者
```
1. `package` 會用 `docs/templates/安裝說明.template.txt` 產 `out/安裝說明.txt`；把佔位符填實：翻譯率、**刻意保留日文的條目與原因**（condition 孤兒、控制碼退回、模型失敗）、已知小瑕疵（掉顏色碼）、5 項實機驗收清單、本機已驗證項目。
2. Wolf 額外注意：`Game.dat` 用回原始檔再原地改（長度必須「未改變」）；2.x 才設語言標記；封包解開逐檔比對要全部一致。
3. 不確定的地方出**兩個變體**（A 主要 / B 備援）讓使用者比，並在說明裡寫清楚差異（記進 `HANDOFF.md` 變體表）。
4. 交付後等回報：`$PY agt.py mark <game> user_boot_ok`（smoke）或 `mark <game> user_final_ok`（最終）。
   兩站流程：smoke OK 後 `/handoff` pack #3 交回翻譯端大量翻譯；最終 OK 後最後一次 pack 同步 `agt.json`／`HANDOFF.md`。
5. 最終驗收通過後回寫：`engines/<x>/NOTES.md` 踩過的坑、`docs/lessons-learned.md`、memory；確認沒有殘留背景行程（`playtest` 沒 `--kill` 時遊戲還開著）。

## 輸出
- `projects/<game>/out/`（補丁檔 + `安裝說明.txt`）、更新後的 `agt.json` 與文件。

## 停下來問使用者
- 每次交付都要停：畫面只有使用者看得到，請他回報精確的 A/B 結果；`playtest` 只能說「沒崩潰」。
- 打包後封包比對不一致、`Game.dat` 長度改變——不要交付，先修。
