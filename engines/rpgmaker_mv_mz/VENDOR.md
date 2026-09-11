# VENDOR.md — rpgmaker_mv_mz

原樣搬入，**不得修改**。要改行為請改 `../adapter.py` 或 `../profile.json`；真的必須改 vendor 時，先用 `vendor/Game` 示範資料做回歸，再更新本檔的 md5。

| 項目 | 值 |
|---|---|
| 來源 | `/raid/home/jimhsieh/GalTransl-RPGmaker`（GitHub: https://github.com/st70712/GalTransl-RPGmaker） |
| commit | `be164a40d7913caaf8586122476c7f01c0955479`（2026-07-15） |
| 搬入日期 | 2026-09-11 |
| 腳本 | 從工作樹複製（與 HEAD 相同） |
| `Game/www/data` | `git archive HEAD Game`（工作樹的示範資料已被清空，不能用） |
| 未搬入 | `exported/`、`Game_translated/`、`Game_backup.zip`（真實遊戲產物）、`environment.yaml` |

## md5

```
6e830e400b0d626b8066006ece4b8e4b  ./export_script.py
cc7856c4a363b180d160f75d8484e9e4  ./Game/www/data/Actors.json
e5406c8eaef23bff3dab999ca8b6eee3  ./Game/www/data/Animations.json
19680b9339c4749cfb090c4c0c25543c  ./Game/www/data/Armors.json
1224aea9f71c9717ec9ee153285f1d7d  ./Game/www/data/Classes.json
e14c1e20a3e85df27f9f77bed89ef875  ./Game/www/data/CommonEvents.json
7044cffc44fe505852763a1b1cca5206  ./Game/www/data/Enemies.json
39642edf8d1c50e692dd1763cd2ade42  ./Game/www/data/Items.json
20728434e4518e4f6b8f404604a1a127  ./Game/www/data/Map001.json
46c1df07e52d81196c0932cfacb306a3  ./Game/www/data/Map002.json
78969737322e574e4f05cc02be081894  ./Game/www/data/Map003.json
0ba6e69d6303aa81af450941f6703136  ./Game/www/data/MapInfos.json
0c10f4e556239652501b6a0db14945b8  ./Game/www/data/Skills.json
add1dbd1feb875009da9aa28f601f7b0  ./Game/www/data/States.json
4cfe7c61f1a69b55fa48428a3fa3b79f  ./Game/www/data/System.json
801e2a6838620d7074485e982673b46f  ./Game/www/data/Tilesets.json
db47e0a6d830c75803620ef74a45dca4  ./Game/www/data/Troops.json
49cf5553e1a10276bc82a0e1102321d8  ./Game/www/data/Weapons.json
3448eb97b2bf45190b8d6560ea085b28  ./.github/copilot-instructions.md
eb67c88236d342b89641baeed54b30f6  ./import_script.py
1c90a3e0b719326a1218b43b982276a8  ./make_demo_data.py
28b4fb21a8e191efcda2f7d157e390a2  ./README.md
```
