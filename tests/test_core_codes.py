"""core.codes：翻譯器已知的七種失敗型態，兩個 profile 都要抓得到／放得過。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import codes, merge  # noqa: E402
from core.profile import load_profile  # noqa: E402


class WolfCodes(unittest.TestCase):
    def setUp(self):
        self.p = load_profile("wolf_rpg")

    def check(self, o, t):
        return codes.check_entry(self.p, o, t)

    def test_clean(self):
        r = self.check("\\E冒険は順調だ…\\c[2]大丈夫\\c[0]", "\\E冒險很順利…\\c[2]沒問題\\c[0]")
        self.assertTrue(r.clean)

    def test_lost_value_code(self):
        r = self.check("\\cself[8]のダメージ！", "造成了傷害！")
        self.assertEqual(r.lost_value, ["\\cself[8]"])
        self.assertTrue(r.fatal)

    def test_extra_value_code(self):
        r = self.check("はい", "\\cself[9]是")
        self.assertEqual(r.extra_value, ["\\cself[9]"])
        self.assertTrue(r.fatal)

    def test_lost_style_only_warns(self):
        r = self.check("\\c[2]注意\\c[0]", "注意")
        self.assertFalse(r.fatal)
        self.assertEqual(r.lost_style, ["\\c[2]", "\\c[0]"])
        self.assertTrue(r.warnings)

    def test_stray_escape_inside_code(self):
        r = self.check("\\EBADEND", "\\xEBADEND")
        self.assertIn("\\x", r.stray)
        self.assertTrue(r.fatal)

    def test_stray_allowed_when_original_uses_it(self):
        # 原文本身就用字面 \n 換行的 4 條台詞：譯文照用不算錯
        r = self.check("一行目\\n二行目", "第一行\\n第二行")
        self.assertFalse(r.fatal)
        self.assertFalse(r.literal_newline)

    def test_literal_newline_policy_convert_is_not_fatal(self):
        r = self.check("一行目\n二行目", "第一行\\n第二行")
        self.assertTrue(r.literal_newline)
        self.assertFalse(r.literal_newline_fatal)   # wolf: convert_if_original_lacks
        self.assertFalse(r.fatal)

    def test_multi_letter_codes_not_split(self):
        # \cself[8] 不能被切成 \c；\sp[24] 不能被切成 \s
        got = self.p.codes.any_re.findall("\\cself[8]\\sp[24]\\c[3]")
        self.assertEqual(got, ["\\cself[8]", "\\sp[24]", "\\c[3]"])

    def test_leading_prefix(self):
        m = self.p.codes.leading_re.match("\\E\\f[12]台詞\\E")
        self.assertEqual(m.group(0), "\\E\\f[12]")

    def test_untranslated_is_clean(self):
        self.assertTrue(self.check("\\v[1]", "").clean)


class RpgMakerCodes(unittest.TestCase):
    def setUp(self):
        self.p = load_profile("rpgmaker_mv_mz")

    def check(self, o, t):
        return codes.check_entry(self.p, o, t)

    def test_deleted_variable(self):
        r = self.check("セラに\\v[61]ダメージ！", "對塞拉造成了傷害！")
        self.assertEqual(r.lost_value, ["\\v[61]"])
        self.assertTrue(r.fatal)

    def test_letter_changed_v_to_n(self):
        # \V[74]（變數值）→ \N[74]（角色名）：同時是 lost + extra
        r = self.check("レベル\\V[74]になった", "升到\\n[74]級了")
        self.assertEqual(r.lost_value, ["\\v[74]"])
        self.assertEqual(r.extra_value, ["\\n[74]"])
        self.assertTrue(r.fatal)
        self.assertEqual(r.stray, [])       # \n[74] 是合法碼，不是 stray

    def test_hardcoded_number(self):
        r = self.check("\\V[75]級", "75級")
        self.assertTrue(r.fatal)

    def test_case_insensitive_ok(self):
        r = self.check("\\N[1]は\\C[2]勇者\\C[0]", "\\n[1]是\\c[2]勇者\\c[0]")
        self.assertTrue(r.clean)

    def test_literal_newline_is_fatal(self):
        r = self.check("一行目\n二行目", "第一行\\n第二行")
        self.assertTrue(r.literal_newline_fatal)
        self.assertTrue(r.fatal)

    def test_placeholder_lost(self):
        r = self.check("%1は%2を受けた", "受到了攻擊")
        self.assertEqual(sorted(r.lost_placeholder), ["%1", "%2"])
        self.assertTrue(r.fatal)

    def test_line_count_warns(self):
        r = self.check("一行目\n二行目", "只有一行")
        self.assertEqual(r.line_count, (2, 1))
        self.assertFalse(r.fatal)

    def test_summary_report(self):
        entries = [
            {"index": 0, "source_file": "a", "location": "x", "context": "dialog",
             "original": "\\v[1]", "translated": "1"},
            {"index": 1, "source_file": "a", "location": "y", "context": "dialog",
             "original": "ok", "translated": "好"},
        ]
        s = codes.report(self.p, entries)
        self.assertEqual((s.checked, s.fatal), (2, 1))
        self.assertIn("帶值控制碼遺失", codes.format_summary(s))


class MergeRules(unittest.TestCase):
    def test_by_location(self):
        new = [{"source_file": "a", "location": "1", "original": "x", "translated": ""},
               {"source_file": "a", "location": "2", "original": "changed", "translated": ""}]
        old = [{"source_file": "a", "location": "1", "original": "x", "translated": "X"},
               {"source_file": "a", "location": "2", "original": "y", "translated": "Y"},
               {"source_file": "b", "location": "9", "original": "z", "translated": "Z"}]
        self.assertEqual(merge.by_location(new, old), (1, 2))
        self.assertEqual(new[0]["translated"], "X")
        self.assertEqual(new[1]["translated"], "")

    def test_by_text_rejects_code_changes(self):
        p = load_profile("wolf_rpg")
        src = [{"context": "dialog", "original": "はい", "translated": "是"},
               {"context": "dialog", "original": "\\v[1]個", "translated": "個"},
               {"context": "dialog", "original": "優しい", "translated": "溫柔"}]
        tgt = [{"context": "choice", "original": "はい", "translated": ""},
               {"context": "dialog", "original": "\\v[1]個", "translated": ""},
               {"context": "condition", "original": "優しい", "translated": ""},
               {"context": "game_title", "original": "はい", "translated": ""}]
        st = merge.by_text(tgt, src, p)
        self.assertEqual(st["套用"], 1)
        self.assertEqual(tgt[0]["translated"], "是")
        self.assertEqual(tgt[1]["translated"], "")          # 帶值碼遺失
        self.assertEqual(tgt[2]["translated"], "")          # condition 孤兒
        self.assertEqual(tgt[3]["translated"], "")          # game_title 不套


if __name__ == "__main__":
    unittest.main()
