---
name: new-game
description: 使用者放了一款新遊戲進來、要開始做中文補丁時，從建立專案到 smoke build 一路跑到 G6 為止。
---

# /new-game

## 觸發
使用者說「幫我翻譯這款遊戲」「工作區有一個遊戲 XXX」，或給了遊戲目錄。

## 輸入
- 遊戲目錄路徑（`original`）；專案名建議用 RJ 編號或遊戲短名。

## 步驟
```bash
PY=/raid/home/jimhsieh/miniconda3/envs/galtransl/bin/python
$PY agt.py detect <遊戲目錄>                       # G0：看證據，不只看第一名
$PY agt.py init <game> --original <遊戲目錄>       # 建 projects/<game>/，寫 agt.json
$PY agt.py gates <game>                            # G1–G5：prepare→roundtrip→export→零翻譯導入→verify→breakage
$PY agt.py status <game>
```
1. `detect` 信心不足或兩個引擎接近 → 先走 `/identify-engine`；沒有轉接器 → `/new-adapter`。
2. `prepare` 後**先量測**：封包儲存形式分布、字串數、各 context 分布，抽 5 條看看。
3. `gates` 任一關失敗就停下修（多半是引擎版本差異），不要硬跳。
4. 全過後做 G6 smoke build：`/translate --limit 20` → `/deliver-patch`，**交給使用者實機開啟**。

## 輸出
- `projects/<game>/` 完整佈局、`exported/script.json`、gates 全綠的 `agt.json`、一份 smoke build 的 `out/`。

## 停下來問使用者
- smoke build 做好後（G6）——一定要等實機回報再 `mark <game> user_boot_ok`。
- 封包形式／長度敏感檔不確定時。

詳見 `CLAUDE.md` 第 4 節、`docs/workflow.md`。
