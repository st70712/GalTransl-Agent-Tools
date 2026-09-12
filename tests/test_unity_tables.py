"""engines/unity_textasset/vendor/unity_tables.py 的純標準庫部分：位址格式、規則路徑走訪、type tree 差異、規則檔解析。
（UnityPy 是延遲載入，這些函式不需要 .venv-unity。）"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "engines" / "unity_textasset" / "vendor"


def _load():
    spec = importlib.util.spec_from_file_location("unity_tables", VENDOR / "unity_tables.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unity_tables"] = mod
    spec.loader.exec_module(mod)
    return mod


ut = _load()

TREE = {
    "m_Name": "TopicCatalog",
    "mCsvFolder": "Assets/x",
    "mTopics": [
        {"mTopicId": "event_001", "mLabel": "導入", "mLines": [
            {"mType": 0, "mSpeaker": "", "mPortrait": "", "mText": "ここは、\r\n飲み屋街。", "mVoice": ""},
            {"mType": 1, "mSpeaker": "", "mPortrait": "", "mText": "まだ続ける！", "mVoice": ""},
            {"mType": 2, "mSpeaker": "", "mPortrait": "", "mText": "unlock:topic_001", "mVoice": ""},
            {"mType": 0, "mSpeaker": "後輩", "mPortrait": "シーン1_顔", "mText": "「あの…」", "mVoice": "b10_3"},
        ]},
        {"mTopicId": "event_002", "mLabel": "注文後", "mLines": []},
    ],
}

RULES = {
    "monobehaviours": {
        "TopicCatalog": [
            {"path": "mTopics[*].mLabel", "context": "choice"},
            {"path": "mTopics[*].mLines[*].mSpeaker", "context": "speaker"},
            {"path": "mTopics[*].mLines[*].mText", "context": "dialog", "speaker_from": "mSpeaker", "when": {"mType": [0]}},
            {"path": "mTopics[*].mLines[*].mText", "context": "choice", "when": {"mType": [1]}},
        ]
    }
}


class FakeObj:
    path_id = 3706

    def __init__(self):
        self.saved = None

    def save_typetree(self, tree):
        self.saved = tree


class SourceAddressTests(unittest.TestCase):
    def test_mb_source_roundtrip(self):
        s = ut.mb_source("data.unity3d", "resources.assets", "TopicCatalog", 3706)
        self.assertEqual(s, "data.unity3d#resources.assets/TopicCatalog@3706")
        self.assertEqual(ut.parse_mb_source(s), ("data.unity3d", "resources.assets", "TopicCatalog", 3706))
        self.assertTrue(ut.is_mb_source(s))
        s2 = ut.mb_source("resources.assets", None, "TextMeshProUGUI", 131)
        self.assertEqual(ut.parse_mb_source(s2), ("resources.assets", None, "TextMeshProUGUI", 131))

    def test_table_source_is_not_mb(self):
        self.assertFalse(ut.is_mb_source("resources.assets#Data_Event"))
        self.assertFalse(ut.is_mb_source("data.unity3d#resources.assets/Data_Event"))
        self.assertEqual(ut.table_source("data.unity3d", "resources.assets", "Data_Event"), "data.unity3d#resources.assets/Data_Event")
        self.assertEqual(ut.table_source("resources.assets", None, "Data_Event"), "resources.assets#Data_Event")


class PathWalkTests(unittest.TestCase):
    def test_walk_path_yields_concrete_locations(self):
        locs = [loc for loc, _, _ in ut.walk_path(TREE, "mTopics[*].mLines[*].mText")]
        self.assertEqual(locs, ["mTopics[0].mLines[0].mText", "mTopics[0].mLines[1].mText",
                                "mTopics[0].mLines[2].mText", "mTopics[0].mLines[3].mText"])
        self.assertEqual([loc for loc, _, _ in ut.walk_path(TREE, "mTopics[*].mLabel")], ["mTopics[0].mLabel", "mTopics[1].mLabel"])
        self.assertEqual(list(ut.walk_path(TREE, "nope[*].x")), [])

    def test_resolve_location(self):
        parent, key = ut.resolve_location(TREE, "mTopics[0].mLines[3].mText")
        self.assertEqual(parent[key], "「あの…」")
        with self.assertRaises(IndexError):
            ut.resolve_location(TREE, "mTopics[0].mLines[9].mText")
        with self.assertRaises(KeyError):
            ut.resolve_location(TREE, "mTopics[0].mNope")

    def test_rule_regex_matches_concrete(self):
        r = ut.MBRule(cls="T", path="mTopics[*].mLines[*].mText", context="dialog")
        self.assertTrue(r.regex().match("mTopics[12].mLines[3].mText"))
        self.assertFalse(r.regex().match("mTopics[12].mLines[3].mVoice"))
        self.assertFalse(r.regex().match("mTopics[12].mLabel"))


class EntriesAndApplyTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rules.json"
            p.write_text(json.dumps(RULES), encoding="utf-8")
            self.rules = ut.load_rules(p)
        self.mbo = ut.MBObject(obj=FakeObj(), cls="TopicCatalog", inner="resources.assets", tree=json.loads(json.dumps(TREE)))

    def test_entries_respect_when_and_skip_keys(self):
        entries = ut.entries_for_mb("data.unity3d#resources.assets/TopicCatalog@3706", self.mbo, self.rules)
        by_loc = {e["location"]: e for e in entries}
        self.assertEqual(by_loc["mTopics[0].mLines[0].mText"]["context"], "dialog")
        self.assertEqual(by_loc["mTopics[0].mLines[1].mText"]["context"], "choice")
        self.assertNotIn("mTopics[0].mLines[2].mText", by_loc)       # mType 2 是指令，且不含日文
        self.assertEqual(by_loc["mTopics[0].mLines[3].mText"]["speaker"], "後輩")
        self.assertEqual(by_loc["mTopics[0].mLines[3].mSpeaker"]["context"], "speaker")
        self.assertNotIn("mTopics[0].mLines[3].mPortrait", by_loc)   # 立繪鍵絕不導出
        self.assertNotIn("mTopics[0].mLines[3].mVoice", by_loc)
        self.assertEqual(by_loc["mTopics[0].mLabel"]["context"], "choice")
        self.assertEqual(len(entries), 6)

    def test_apply_and_diff(self):
        ok, warn = ut.apply_mb_entry(self.mbo, "mTopics[0].mLines[0].mText", "這裡是，\r\n飲酒街。")
        self.assertTrue(ok and not warn)
        ok, _ = ut.apply_mb_entry(self.mbo, "mTopics[0].mLines[0].mText", "這裡是，\r\n飲酒街。")
        self.assertFalse(ok)                                          # 相同譯文 = 沒變動
        ok, msg = ut.apply_mb_entry(self.mbo, "mTopics[0].mLines[0].mType", "x")
        self.assertFalse(ok)
        self.assertIn("不是字串", msg)
        diffs = ut.tree_diff(TREE, self.mbo.tree)
        self.assertEqual([d[0] for d in diffs], ["mTopics[0].mLines[0].mText"])
        broken = json.loads(json.dumps(self.mbo.tree))
        del broken["mTopics"][0]["mLines"][-1]
        self.assertEqual(ut.tree_diff(TREE, broken)[0][0], "mTopics[0].mLines")


class MarkersTests(unittest.TestCase):
    def test_bundle_marker_known_to_handoff(self):
        sys.path.insert(0, str(ROOT))
        from core import handoff
        self.assertTrue(any(m == "_Data/data.unity3d" for m, _ in handoff.GAME_MARKERS))


if __name__ == "__main__":
    unittest.main()
