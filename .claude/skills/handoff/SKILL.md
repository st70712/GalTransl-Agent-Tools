---
name: handoff
description: 兩站接力（實機端 Windows ↔ 翻譯端 dgxluna）的交接：打包交接包給另一站、或收對方的交接包，含 HANDOFF.md 與 git 同步。
---

# /handoff

## 觸發
- 實機端：G5 全綠（gates 全過）、smoke build 實機 OK 後 `mark user_boot_ok`、或使用者要求「交給 dgxluna 翻」。
- 翻譯端：20 條樣本翻完 fix_text／check_codes／validate 過、G8 收尾完成、或使用者說「翻好了交回筆電」。
- 任一站：使用者拿來一個 zip／資料夾說「這是另一台傳來的」→ 先 `agt detect`。
協定全文：`CLAUDE.md` 第 6 節、`docs/two-site.md`。

## 輸入
- `projects/<game>/`（送方）；交接包 zip 或放交接包的資料夾（收方）。`config.local.yaml` 的 `site`、`handoff_dir`。

## 步驟：送方（pack）
```bash
$PY agt.py env                                   # 確認站點；$PY 見 CLAUDE.md §3（Windows: python）
$PY agt.py status <game>                         # 「交接:」那行：持棒方必須是本站（或還沒交接過）
# 1. 更新 projects/<game>/HANDOFF.md：交接紀錄最上方加一段（本站完成／請對方做／需要對方回答／實機回報）
# 2. 程式碼同步：git add -A && git commit -m "..." && git push        （pack 發現 dirty 會拒絕）
$PY agt.py handoff pack <game> [--to translator|workstation]     # seq+1；有 handoff_dir 自動複製過去
```
1. 印出的本機路徑（`projects/<game>/handoff/<game>-NNN-to-<site>-<時間>.zip`）與共用資料夾路徑都告訴使用者；
   rclone／Drive 桌面版是非同步上傳，`ls -la` 確認大小一致再說「可以收了」。
2. pack 之後**本站不再改 `exported/script.json`**，直到收到回包。
3. 實機端第一次 pack（#1）的 HANDOFF.md 一定要有：量測數字、字型對策、smoke 樣本的 `--filter` 正則。

## 步驟：收方（unpack）
```bash
git pull                                         # 先拿到對方的程式碼變更
$PY agt.py detect <zip 或資料夾>                 # 來料判斷：交接包／一堆交接包／遊戲 zip／既有專案
$PY agt.py handoff unpack <zip 或資料夾>         # 拒收舊 seq；覆蓋前備份；agt.json 合併；印下一步
$PY agt.py status <game>
```
1. 先讀 `projects/<game>/HANDOFF.md` 最新一段「請對方做」再動手。
2. 翻譯端收到的是骨架專案（沒 `original/`）：只能 translate／fix_text／check-codes／validate，`import`／`package` 會被擋。
3. 警告「repo 不同步」→ `git pull` 後重跑；「seq 不比本地新」→ 對照兩邊 `agt status`，確定才 `--force`。

## 輸出
- 送方：交接包 zip、更新過的 `agt.json.handoff`（seq、holder）、HANDOFF.md。
- 收方：`projects/<game>/` 建立或更新、備份檔、合併後的 `agt.json`。

## 停下來問使用者
- 沒設 `handoff_dir`：把 zip 路徑給使用者，等他搬到另一站。
- seq 衝突、repo 不同步、兩邊都改了 script.json（違反一棒制，救法見 `docs/two-site.md` §10）。
- 專案名兩站不一致（`unpack --game` 警告）：問使用者要統一成哪個。
