---
name: identify-engine
description: 不確定遊戲是哪個引擎、或 agt detect 信心不足時，用執行檔字串、封包 magic 與目錄結構把引擎與版本確認下來。
---

# /identify-engine

## 觸發
`agt detect` 沒有 ≥0.5 的結果、兩個引擎分數接近、或使用者的說法與資料長相不合。**在有遊戲檔的站點跑**（實機端或單機）。

## 輸入
- 遊戲目錄（給 zip 時 `agt detect` 會提示先解壓）。

## 步驟
```bash
# $PY 見 CLAUDE.md §3；Windows 的 Git Bash 也有 strings / xxd / find
$PY agt.py detect <遊戲目錄>                 # 列出每個引擎的證據
ls -la <遊戲目錄>; find <遊戲目錄> -maxdepth 2 -type d | head
strings -n 8 <遊戲目錄>/*.exe | grep -iE "version|rpg|wolf|dxlib|unity|kirikiri|tyrano" | head
for f in <遊戲目錄>/*.wolf <遊戲目錄>/**/*.xp3 <遊戲目錄>/*.bsa; do xxd -l 16 "$f"; done 2>/dev/null
```
1. 對照 `docs/engines.md` 的特徵表；記下**版本**（Wolf 2.x/3.x、MV/MZ）與**字串編碼**，它們決定 profile 的 variant。
2. 上次的教訓：使用者說是 RPG Maker，實際是 Wolf——**以資料為準，不以描述為準**。
3. 確認後：`$PY agt.py init <game> --original <dir> --engine <name> --variant <v>`（有轉接器）或走 `/new-adapter`。

## 輸出
- 一段結論：引擎、版本、編碼、證據清單；寫進 `agt.json`（`init` 會做）；兩站流程也寫進 `HANDOFF.md` 專案摘要。

## 停下來問使用者
- 引擎確認是「指標」狀態（Bishop、TyranoScript、KiriKiri、Ren'Py…）時，先說明要新寫轉接器的工作量再開始。
- 需要同引擎的官方多語版本來對照時。
