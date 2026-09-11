# VENDOR.md — wolf_rpg

原樣搬入，**不得修改**。要改行為請改 `../adapter.py` 或 `../profile.json`；真的必須改 vendor 時，先用 `roundtrip_test.py` 與原專案資料做回歸，再更新本檔的 md5。

| 項目 | 值 |
|---|---|
| 來源 | `/raid/home/jimhsieh/GalTransl-sister`（非 git 倉庫；最後修改 2026-08-12 16:09:46） |
| 搬入日期 | 2026-09-11 |
| 搬入內容 | 10 支 `.py`、`wolfrpg/`、`README.md` |
| 未搬入 | `Data*/`、`RJ*/`、`exported*/`、`out/`、`name/`、`translate.log`（遊戲資料與產物，GB 級） |
| 新流程不呼叫 | `translate_wolf.py`（由 `tools/translate.py` 取代）、`fix_cp950.py`（由 `tools/fix_text.py` 取代）；保留作對照 |

## md5

```
20ba1569277b9f87a1b8fe40b3c727df  ./export_script.py
63247b2a5346846e7061d0236a97ac73  ./extract_wolf.py
23b8a791e0401aafafc61b304a7250da  ./fix_cp950.py
b112a76b7fd6a7ad3935d478f3ddf98f  ./import_script.py
e85ac77cd19336beb2007d78db872105  ./merge_by_text.py
366dacf27fb0aee5722ed1ac3e4b97e3  ./README.md
2a39633d000dbc13b70e380826157395  ./repack_wolf.py
4416929aa4904fdf97cf2229e8be384c  ./roundtrip_test.py
77c94bb12a333e82ef7e5f90f0796fc8  ./set_font.py
d5e263e52701e429a70136a31977ebdd  ./set_game_lang.py
a143b3f5e959e1e477cfc87958d04613  ./translate_wolf.py
325d2c8cc28f6242884bb21600872ea2  ./wolfrpg/command.py
edbc9c64def7adf42dc880b6c873601d  ./wolfrpg/common_events.py
db004c7e17f0157067347a3b40d9f99c  ./wolfrpg/database.py
8cfabfebadb382e2b623a08c7949f7f0  ./wolfrpg/dxa.py
e97a509fd38c33ad7e9a16ce96e6ec8b  ./wolfrpg/filecoder.py
7a03c0608f40d27c84be926504c25f7b  ./wolfrpg/game_dat.py
d41d8cd98f00b204e9800998ecf8427e  ./wolfrpg/__init__.py
b691549c32dd6c8f0dc9643971924e01  ./wolfrpg/map.py
5fe080ac4141c96021cd9c682efdb266  ./wolfrpg/textio.py
2b10f3173ad7368e3ff86aeab3049fce  ./wolfrpg/textnorm.py
```
