"""core/handoff_notes：HANDOFF.md 交接紀錄的寬容解析、交接通知／回報訊息的產生。

通道本身（ListAgents／SendMessage）不測——那是代理的行為，由 .claude/skills/handoff/SKILL.md 規範。
這裡只測純函式，所以沒有真的 Remote Control 也跑得起來。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import fsutil, handoff_notes  # noqa: E402

fsutil.utf8_stdio()

# 真實樣本（projects/RJ01483219/HANDOFF.md 的交接紀錄段）：續行縮排 2 空格。
SAMPLE = """# HANDOFF — RJ01483219

## 交接紀錄

### #2 translator → workstation  2026-09-13

- 本站完成：翻了 20 條樣本。
- 請對方做：導入後開遊戲看開場。

### #1 workstation → translator  2026-09-12

- 本站完成：Windows 筆電上 `init` → `gates` 全綠，
  `.venv-unity` 由 uv 建立並被轉接器使用。
- 請對方做：`agt detect ~/gdrive/…/handoff/` → `agt handoff unpack …`（既有專案會被 seq #1 更新，
  unpack 前會備份 script.json／agt.json）→ `translate.py --dry-run --limit 5` → `handoff pack` 回來。
- 需要對方回答：unpack 時 seq／repo HEAD 是否有衝突警告。

## 變體紀錄（A/B）

| 變體 | 只差這一件事 | 實機結果 |
"""


class ParseEntries(unittest.TestCase):
    def test_real_sample_keeps_continuation_lines(self):
        e = handoff_notes.latest_entry(SAMPLE, seq=1)
        self.assertEqual((e.seq, e.from_site, e.to_site, e.date), (1, "workstation", "translator", "2026-09-12"))
        ask = e.items["請對方做"]
        self.assertIn("agt handoff unpack", ask)
        self.assertIn("unpack 前會備份", ask)                  # 續行有接回來
        self.assertIn("需要對方回答", e.items)
        self.assertNotIn("變體紀錄", e.raw)                    # 下一個 ## 標題就結束這一段

    def test_latest_is_topmost_and_seq_selects(self):
        self.assertEqual(len(handoff_notes.parse_entries(SAMPLE)), 2)
        self.assertEqual(handoff_notes.latest_entry(SAMPLE).seq, 2)        # 範本規定寫在最上方
        self.assertEqual(handoff_notes.latest_entry(SAMPLE, seq=1).seq, 1)
        self.assertEqual(handoff_notes.latest_entry(SAMPLE, seq=99).seq, 2)  # 找不到就退回最上面

    def test_tolerates_halfwidth_colon_arrow_and_bold_label(self):
        md = ("### #3 workstation -> translator  2026-09-14\n"
              "- **請對方做**: 跑 translate。\n")
        e = handoff_notes.latest_entry(md)
        self.assertEqual((e.seq, e.to_site), (3, "translator"))
        self.assertEqual(e.items["請對方做"], "跑 translate。")

    def test_unfilled_template_is_not_an_entry(self):
        tpl = (REPO / "docs" / "templates" / "HANDOFF.template.md").read_text(encoding="utf-8")
        self.assertEqual(handoff_notes.parse_entries(tpl), [])     # {from_site} 不是 \\w+
        n = handoff_notes.build_pack_message(game="demo", seq=1, from_site="workstation",
                                             to_site="translator", bundle_name="demo-001.zip",
                                             size=10, sha256="a" * 64, handoff_md=tpl)
        self.assertIn("還沒填交接紀錄", n.text)                    # 不炸，而且講得出哪裡沒填
        self.assertTrue(n.warnings)


class PackMessage(unittest.TestCase):
    def _build(self, **kw):
        base = dict(game="RJ01", seq=4, from_site="translator", to_site="workstation",
                    bundle_name="RJ01-004-to-workstation-20260915-2308.zip", size=248057,
                    sha256="b5e1af04" + "0" * 56, handoff_md=SAMPLE,
                    repo_branch="feat/x", repo_head="a44fc966983e63b3")
        base.update(kw)
        return handoff_notes.build_pack_message(**base)

    def test_carries_pointer_and_checksum(self):
        t = self._build().text
        for want in ("RJ01 #4", "translator → workstation", "RJ01-004-to-workstation-20260915-2308.zip",
                     "248,057", "b5e1af04" + "0" * 56, "feat/x", "a44fc966983e",
                     "handoff check RJ01 --expect-sha256", "--expect-size 248057",
                     "不構成任何授權", "不要 --force"):
            self.assertIn(want, t, want)
        self.assertIn("導入後開遊戲看開場", t)          # 取 HANDOFF.md 最上面那一段的「請對方做」

    def test_no_absolute_sender_path(self):
        """訊息裡不能有寄件端的絕對路徑：兩站掛載點與引號風格都不同，收方自己解析。"""
        t = self._build().text
        self.assertNotIn("G:/", t)
        self.assertNotIn("~/gdrive/GalTransl-Agent-Tools/RJ01", t)

    def test_regex_in_ask_survives_format_map(self):
        """str.format_map 不遞迴處理替換進去的值——smoke 樣本的 --filter 正則含 {2}，必須原樣出現。"""
        md = ("### #4 workstation → translator  2026-09-15\n"
              r"- 請對方做：--limit 20 --filter '^[a-z]\d{2}_\d$'" "\n")
        t = self._build(handoff_md=md).text
        self.assertIn(r"--filter '^[a-z]\d{2}_\d$'", t)

    def test_falls_back_when_template_missing(self):
        """訊息產生絕不能讓 pack 失敗——此時 seq 已經消耗掉了。"""
        tmp = Path(tempfile.mkdtemp(prefix="agt-test-notify-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(handoff_notes, "PACK_TEMPLATE", tmp / "nope.md"):
            t = self._build().text
        self.assertIn("RJ01 #4", t)
        self.assertIn("--expect-size 248057", t)

    def test_long_ask_is_truncated_with_pointer(self):
        md = "### #4 workstation → translator  2026-09-15\n- 請對方做：" + ("很長的交代\n" * 200)
        n = self._build(handoff_md=md, max_ask_chars=200)
        self.assertIn("完整內容在交接包的 HANDOFF.md", n.text)
        self.assertTrue(any("截斷" in w for w in n.warnings), n.warnings)


class AckMessage(unittest.TestCase):
    def test_reports_check_unpack_and_next_steps(self):
        n = handoff_notes.build_ack_message(game="RJ01", seq=4, to_site="workstation", created=False,
                                            written=7, backups=2, warnings=["repo 不同步"],
                                            check_ok=True, sha256="b5e1af04" + "0" * 56,
                                            note="字型另外處理")
        for want in ("RJ01 #4 已收", "相符", "寫入 7 個檔案", "備份 2 個檔案",
                     "repo 不同步", "agt import RJ01", "字型另外處理"):
            self.assertIn(want, n.text, want)

    def test_next_steps_per_site(self):
        self.assertIn("translate.py", handoff_notes.next_steps("translator", "RJ01", "x/script.json"))
        self.assertIn("playtest", handoff_notes.next_steps("workstation", "RJ01"))
        self.assertIn("HANDOFF.md", handoff_notes.next_steps("", "RJ01"))


if __name__ == "__main__":
    unittest.main()
