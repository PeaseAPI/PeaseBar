#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbrprefs：TrailingItemPreferredPositions 权重表的纯函数与写路径（离线单测，
全走临时文件与打桩，不碰真实 plist、不 killall）。"""
import os
import plistlib
import tempfile
import unittest
from unittest import mock

from peasebar import ccnative, mbrprefs, sections
from peasebar.settings import SettingsController


def _match(bid, known):
    """借真 ccnative.match_bid 的分段前缀规则（与线上同一口径）。"""
    return ccnative.match_bid(bid, known)


class TestKeyParse(unittest.TestCase):
    def test_status键解出bundle(self):
        self.assertEqual(
            mbrprefs.bundle_of_key("status:com.tencent.qq::Item-0"),
            "com.tencent.qq")

    def test_module与异形键返回None(self):
        self.assertIsNone(mbrprefs.bundle_of_key("module:Clock"))
        self.assertIsNone(mbrprefs.bundle_of_key("status:nocolon"))
        self.assertIsNone(mbrprefs.bundle_of_key("status::x"))


class TestReorderWeights(unittest.TestCase):
    TABLE = {
        "status:com.a.one::Item-0": 570.5,
        "status:com.b.two::Item-0": 532.5,
        "status:com.c.three::Item-0": 492.5,
        "module:Clock": 0.0,
    }

    def test_按目标序置换权重(self):
        new = mbrprefs.reorder_weights(
            self.TABLE, ["com.b.two", "com.a.one", "com.c.three"], _match)
        # 权重值集合不变，只在参与键之间重新发牌
        self.assertEqual(new["status:com.b.two::Item-0"], 570.5)
        self.assertEqual(new["status:com.a.one::Item-0"], 532.5)
        self.assertEqual(new["status:com.c.three::Item-0"], 492.5)
        # 未参与键原值不动
        self.assertEqual(new["module:Clock"], 0.0)

    def test_已是目标序幂等返回原表(self):
        got = mbrprefs.reorder_weights(
            self.TABLE, ["com.a.one", "com.b.two", "com.c.three"], _match)
        self.assertIs(got, self.TABLE)

    def test_表里没有的项跳过不发明权重(self):
        got = mbrprefs.reorder_weights(
            self.TABLE, ["com.unknown.x", "com.a.one", "com.b.two"], _match)
        self.assertEqual(got["status:com.a.one::Item-0"], 570.5)
        self.assertEqual(got["status:com.b.two::Item-0"], 532.5)

    def test_前缀差异落到表内键(self):
        """盘点 bid 带子路径（.Menu），表键挂安装主体——match_bid 同规则。"""
        table = {"status:com.macpaw.CleanMyMac5::Item-0": 100.0,
                 "status:com.other.x::Item-0": 200.0}
        got = mbrprefs.reorder_weights(
            table, ["com.other.x", "com.macpaw.CleanMyMac5.Menu"], _match)
        self.assertEqual(got["status:com.other.x::Item-0"], 200.0)
        self.assertEqual(got["status:com.macpaw.CleanMyMac5::Item-0"], 100.0)

    def test_同bundle多键按键名序参与(self):
        table = {"status:com.a.one::Item-0": 300.0,
                 "status:com.a.one::Item-1": 200.0,
                 "status:com.b.two::Item-0": 100.0}
        got = mbrprefs.reorder_weights(
            table, ["com.b.two", "com.a.one"], _match)
        # b 拿最大权重；a 的两键保持内部相对序（Item-0 在 Item-1 前）
        self.assertEqual(got["status:com.b.two::Item-0"], 300.0)
        self.assertEqual(got["status:com.a.one::Item-0"], 200.0)
        self.assertEqual(got["status:com.a.one::Item-1"], 100.0)

    def test_少于两键返回原表(self):
        got = mbrprefs.reorder_weights(self.TABLE, ["com.a.one"], _match)
        self.assertIs(got, self.TABLE)


class TestApplyVisibleOrder(unittest.TestCase):
    """写路径：临时 plist + 打桩 killall，验证原子写与幂等跳过。"""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.path = os.path.join(tmp, "com.apple.MenuBar.plist")
        self.data = {"TrailingItemPreferredPositions": {
            "status:com.a.one::Item-0": 570.5,
            "status:com.b.two::Item-0": 532.5,
        }}
        with open(self.path, "wb") as f:
            plistlib.dump(self.data, f)
        p1 = mock.patch.object(mbrprefs, "PLIST_PATH", self.path)
        p2 = mock.patch("subprocess.run")
        self.run_mock = p2.start()
        p1.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def _table(self):
        with open(self.path, "rb") as f:
            return plistlib.load(f)[mbrprefs.TABLE_KEY]

    def test_改序写盘并清缓存(self):
        r = mbrprefs.apply_visible_order(["com.b.two", "com.a.one"], _match)
        self.assertEqual(r["error"], None)
        self.assertGreater(r["changed"], 0)
        t = self._table()
        self.assertEqual(t["status:com.b.two::Item-0"], 570.5)
        self.assertEqual(t["status:com.a.one::Item-0"], 532.5)
        # 写完必须立即清 cfprefsd 缓存（agent 重启前旧值还在缓存里）
        killed = [c.args[0][1] for c in self.run_mock.call_args_list]
        self.assertIn("cfprefsd", killed)

    def test_目标序即现状时不写盘(self):
        r = mbrprefs.apply_visible_order(["com.a.one", "com.b.two"], _match)
        self.assertEqual(r["changed"], 0)
        self.run_mock.assert_not_called()

    def test_表形态异常只报告不抛(self):
        with open(self.path, "wb") as f:
            plistlib.dump({"TrailingItemPreferredPositions": "坏了"}, f)
        r = mbrprefs.apply_visible_order(["com.a.one", "com.b.two"], _match)
        self.assertEqual(r["changed"], 0)
        self.assertIn("异常", r["error"])


class TestBarOrderTarget(unittest.TestCase):
    """应用改动的目标序提取：只收 visible 区第三方 bid，去重保序。"""

    def _target(self, cfg):
        fake = mock.Mock(real_bar=True)
        return SettingsController._bar_order_target(fake, cfg)

    def test_按order表取visible区bid(self):
        cfg = {"order": ["com.a.one|Item-0", "com.b.two|Item-0",
                         "com.c.three|Item-0"],
               "sections": {"com.c.three|Item-0": sections.SECTION_HIDDEN}}
        self.assertEqual(self._target(cfg), ["com.a.one", "com.b.two"])

    def test_去重保序且滤保护bid(self):
        cfg = {"order": ["com.a.one|Item-0", "com.a.one|Item-1",
                         "com.pease.peasebar|x", "com.b.two|Item-0"],
               "sections": {}}
        self.assertEqual(self._target(cfg), ["com.a.one", "com.b.two"])

    def test_不足两项返回空(self):
        cfg = {"order": ["com.a.one|Item-0"], "sections": {}}
        self.assertEqual(self._target(cfg), [])


if __name__ == "__main__":
    unittest.main()
