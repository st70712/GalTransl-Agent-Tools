"""profile.json 載入與「防漂移」：wolf profile 的正則必須與 vendored 原始碼一字不差。"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.profile import list_profiles, load_profile  # noqa: E402

WOLF_VENDOR = REPO / "engines" / "wolf_rpg" / "vendor"


def _regex_arg(source: Path, target_name: str) -> str:
    """抓 ``NAME = re.compile(<字串>)`` 的字串常數（相鄰字串會被 parser 合併）。"""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == target_name for t in node.targets
        ):
            value = node.value
            if isinstance(value, ast.Call):
                value = value.args[0]
            return ast.literal_eval(value)
    raise AssertionError(f"{source} 裡找不到 {target_name}")


class ProfileLoading(unittest.TestCase):
    def test_all_profiles_load(self):
        names = [p.parent.name for p in list_profiles()]
        self.assertIn("wolf_rpg", names)
        self.assertIn("rpgmaker_mv_mz", names)
        for p in list_profiles():
            prof = load_profile(p)
            self.assertEqual(prof.name, p.parent.name)
            self.assertTrue(prof.contexts, f"{prof.name} 沒有 contexts")
            for ctx in prof.contexts.values():
                self.assertIn(ctx.default, ("translate", "optional", "skip"))

    def test_alias_lookup(self):
        self.assertEqual(load_profile("wolf").name, "wolf_rpg")
        self.assertEqual(load_profile("rpgmaker").name, "rpgmaker_mv_mz")
        with self.assertRaises(FileNotFoundError):
            load_profile("no-such-engine")

    def test_policies(self):
        wolf = load_profile("wolf_rpg")
        self.assertEqual(wolf.priority("dialog"), 1)
        self.assertIn("debug", wolf.default_skip_contexts())
        self.assertIn("game_title", wolf.default_skip_contexts())
        self.assertEqual(wolf.optional_contexts(), {"string_var", "condition"})
        self.assertEqual(wolf.counterpart_contexts(), {"condition"})
        self.assertEqual(wolf.variant("2.x")["target_encoding"], "cp950")
        self.assertEqual(wolf.variant("3.x")["target_encoding"], "utf-8")
        rm = load_profile("rpgmaker_mv_mz")
        self.assertTrue(rm.codes.case_insensitive)
        self.assertIn("debug_name", rm.default_skip_contexts())


class WolfRegexDrift(unittest.TestCase):
    """profile 的正則是從 vendored 腳本抄來的；任何一邊改了都要一起改。"""

    def test_value_and_style_match_fix_cp950(self):
        wolf = load_profile("wolf_rpg")
        src = WOLF_VENDOR / "fix_cp950.py"
        self.assertEqual(wolf.codes.value_pattern, _regex_arg(src, "VALUE_CODE_RE"))
        self.assertEqual(wolf.codes.style_pattern, _regex_arg(src, "STYLE_CODE_RE"))

    def test_leading_matches_translate_wolf(self):
        wolf = load_profile("wolf_rpg")
        src = WOLF_VENDOR / "translate_wolf.py"
        code = _regex_arg(src, "_WOLF_CODE")
        self.assertEqual(wolf.codes.leading_pattern, "^(?:" + code + ")+")

    def test_symbol_map_matches_fix_cp950(self):
        wolf = load_profile("wolf_rpg")
        tree = ast.parse((WOLF_VENDOR / "fix_cp950.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SYMBOL_MAP" for t in node.targets
            ):
                self.assertEqual(wolf.symbol_map, ast.literal_eval(node.value))
                return
        self.fail("fix_cp950.py 裡找不到 SYMBOL_MAP")


if __name__ == "__main__":
    unittest.main()
