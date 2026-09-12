---
name: new-game
description: 使用者放了一款新遊戲進來、要開始做中文補丁時，從建立專案到 smoke build 一路跑到 G6 為止（兩站流程在實機端跑到 G5 交接）。
---

# /new-game

## 觸發
使用者說「幫我翻譯這款遊戲」「工作區有一個遊戲 XXX」，或給了遊戲目錄。**在有遊戲檔的站點跑**（實機端或單機）。

## 輸入
- 遊戲目錄路徑（`original`）；專案名建議用 RJ 編號或遊戲短名（**兩站流程兩邊要用同一個名字**）。

## 步驟
```bash
$PY agt.py env                                     # 我是哪一站；$PY 見 CLAUDE.md §3（dgxluna: conda galtransl；Windows: python）
$PY agt.py detect <遊戲目錄>                       # G0：看證據，不只看第一名（給 zip 會提示先解壓）
$PY agt.py init <game> --original <遊戲目錄>       # 建 projects/<game>/，寫 agt.json（Windows 沒 symlink 權限會退回 junction）
$PY agt.py gates <game>                            # G1–G5：prepare→roundtrip→export→零翻譯導入→verify→breakage
$PY agt.py status <game>
```
1. `detect` 信心不足或兩個引擎接近 → 先走 `/identify-engine`；沒有轉接器 → `/new-adapter`。
2. `prepare` 後**先量測**：封包儲存形式分布、字串數、各 context 分布、**字型覆蓋率**，抽 5 條看看。字元集存 `projects/<game>/font_charset.txt`。
3. `gates` 任一關失敗就停下修（多半是引擎版本差異），不要硬跳。
4. 全過後：
   - **實機端（兩站流程）**：填 `HANDOFF.md`（量測數字、字型對策、smoke 樣本 `--filter`）→ commit+push → `/handoff` 交給翻譯端翻 20 條。
   - **單機**：G6 smoke build：`/translate --limit 20` → `/deliver-patch`，**交給使用者實機開啟**。

## 輸出
- `projects/<game>/` 完整佈局、`exported/script.json`、gates 全綠的 `agt.json`；單機再加一份 smoke build 的 `out/`，兩站則是交接包 #1。

## 停下來問使用者
- smoke build 做好後（G6）——一定要等實機回報再 `mark <game> user_boot_ok`。
- 封包形式／長度敏感檔不確定時。

詳見 `CLAUDE.md` 第 5 節、`docs/workflow.md`、`docs/two-site.md`。
