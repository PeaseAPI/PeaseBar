#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccnative：bid 匹配规则与侧车读写（离线单测，不碰真实 plist/侧车）。"""
import os
import tempfile
import unittest
from unittest import mock

from peasebar import ccnative, sections


class TestMatchBid(unittest.TestCase):
    KNOWN = {"com.macpaw.CleanMyMac5", "com.example.app",
             "com.example.app.helper", "com.other"}

    def test_精确命中优先(self):
        self.assertEqual(ccnative.match_bid("com.example.app", self.KNOWN),
                         "com.example.app")

    def test_盘点bid带子路径落到安装主体(self):
        """CleanMyMac 菜单宿主带子路径，系统记录挂在大 bundle 名下（真机形态）。"""
        self.assertEqual(ccnative.match_bid("com.macpaw.CleanMyMac5.Menu",
                                           self.KNOWN),
                         "com.macpaw.CleanMyMac5")

    def test_分段边界不误配(self):
        """com.a.b 不得匹配 com.a.bc：前缀必须落在分段点上（双向同规）。"""
        self.assertIsNone(ccnative.match_bid("com.example.appx", self.KNOWN))
        self.assertIsNone(ccnative.match_bid("com.example.appx",
                                            {"com.example.app"}))

    def test_多命中取最短(self):
        """bid 是两条记录的共同前缀时，取最短的（最贴近的安装主体）。"""
        got = ccnative.match_bid(
            "com.example", {"com.example.app", "com.example.app.helper"})
        self.assertEqual(got, "com.example.app")

    def test_无命中返回None(self):
        self.assertIsNone(ccnative.match_bid("com.none.here", self.KNOWN))


class TestSidecar(unittest.TestCase):
    """record_hidden/last_hidden：读写全走临时目录，不碰真实 config.json.cc。"""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        p = mock.patch.object(
            sections, "config_path",
            lambda: os.path.join(tmp, "config.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_记录去重保序且滤保护bid(self):
        ccnative.record_hidden({"com.a.one", "com.apple.system"})
        ccnative.record_hidden({"com.a.one", "com.b.two"})
        self.assertEqual(ccnative.last_hidden(), ["com.a.one", "com.b.two"])

    def test_无记录返回空表(self):
        self.assertEqual(ccnative.last_hidden(), [])


class TestInputMenu(unittest.TestCase):
    """输入法菜单通道（搜狗宿主 com.apple.TextInputMenuAgent 的 visible 键）：
    读解析与写动作全走临时文件 + 桩 subprocess，不碰真机偏好、不重启进程。"""

    def setUp(self):
        self.plist = os.path.join(tempfile.mkdtemp(), "TextInputMenu.plist")
        p = mock.patch.object(ccnative, "input_menu_plist_path",
                              lambda: self.plist)
        p.start()
        self.addCleanup(p.stop)
        self.runs = []  # 记录 subprocess 调用（defaults/killall），不真执行
        sp = mock.patch.object(ccnative.subprocess, "run",
                               lambda cmd, **kw: self.runs.append(cmd))
        sp.start()
        self.addCleanup(sp.stop)
        sl = mock.patch.object(ccnative.time, "sleep", lambda _s: None)
        sl.start()
        self.addCleanup(sl.stop)

    def _write(self, visible):
        import plistlib
        with open(self.plist, "wb") as f:
            plistlib.dump({"visible": visible}, f)

    def test_读解析形态(self):
        self.assertTrue(ccnative.input_menu_visible())  # 文件不在 → 系统默认显示
        self._write(1)
        self.assertTrue(ccnative.input_menu_visible())
        self._write(0)
        self.assertFalse(ccnative.input_menu_visible())

    def test_同值幂等零动作(self):
        """值已一致：不 defaults 不 killall（60s 周期核对反复调用零打扰）。"""
        self._write(0)
        self.assertFalse(ccnative.set_input_menu_visible(False))
        self.assertEqual(self.runs, [])

    def test_异值写盘并重启进程(self):
        self._write(1)
        self.assertTrue(ccnative.set_input_menu_visible(False))
        self.assertEqual(len(self.runs), 2)
        self.assertEqual(self.runs[0][:4],
                         ["defaults", "write", ccnative.INPUT_MENU_DOMAIN,
                          "visible"])
        self.assertEqual(self.runs[0][-1], "0")
        self.assertEqual(self.runs[1], ["killall", ccnative.INPUT_MENU_AGENT])


class TestCCFormat(unittest.TestCase):
    """CC plist 写格式守卫：trackedApplications 必须落成系统原生 data（嵌套 bplist）。

    2026-11-24 真机事故两连回归：①内容被写坏成 int 数组的字节拆解形态，
    系统 ControlCenter 解不开 → 全部 isAllowed 失效；②一度实验裸数组直写，
    系统同样不认（会把状态改写成解不开的中间态）。历史取证
    （tmp/layout_table_full.json）铁证：系统原生格式是 data（嵌套 bplist 数组）。
    这里锁死：写出去必须是 data 且内容解得回 dict 数组；各种坏形态要救要修。
    全部走临时文件 + 桩 killall/sleep，不碰真机。"""

    def setUp(self):
        self.plist = os.path.join(tempfile.mkdtemp(), "cc.plist")
        p = mock.patch.object(ccnative, "CC_PLIST", self.plist)
        p.start()
        self.addCleanup(p.stop)
        sp = mock.patch.object(ccnative.subprocess, "run", lambda cmd, **kw: None)
        sp.start()
        self.addCleanup(sp.stop)
        sl = mock.patch.object(ccnative.time, "sleep", lambda _s: None)
        sl.start()
        self.addCleanup(sl.stop)

    @staticmethod
    def _rec(bid, allowed):
        return {"bundle": {"_0": bid}, "isAllowed": allowed}

    def _write_outer(self, tracked):
        import plistlib
        with open(self.plist, "wb") as f:
            plistlib.dump({"trackedApplications": tracked}, f)

    def _read_tracked(self):
        import plistlib
        with open(self.plist, "rb") as f:
            return plistlib.load(f).get("trackedApplications")

    def test_写后落成原生data且值生效(self):
        import plistlib
        self._write_outer([self._rec("com.acme.app", True)])
        got = ccnative.set_apps_allowed({"com.acme.app"}, False)
        self.assertEqual(got, {"com.acme.app"})
        tracked = self._read_tracked()
        self.assertIsInstance(tracked, bytes)  # 原生 data 形态
        recs = plistlib.loads(tracked)
        self.assertIsInstance(recs, list)
        self.assertFalse(recs[0]["isAllowed"])

    def test_原生data且值一致时幂等不重写(self):
        """合法 data 形态 + 目标态一致：不重写（60s tick 反复调用零打扰）。"""
        import plistlib
        data = plistlib.dumps([self._rec("com.acme.app", False)],
                              fmt=plistlib.FMT_BINARY)
        self._write_outer(data)
        got = ccnative.set_apps_allowed({"com.acme.app"}, False)
        self.assertEqual(got, set())
        self.assertEqual(self._read_tracked(), data)  # 磁盘原样未动

    def test_裸数组被修回原生data(self):
        """裸 dict 数组系统不认（真机实证会被改写成解不开的中间态），
        哪怕值一致也要把格式修回 data。"""
        import plistlib
        self._write_outer([self._rec("com.acme.app", False)])
        got = ccnative.set_apps_allowed({"com.acme.app"}, False)
        self.assertEqual(got, set())  # 值一致，无实际改动
        tracked = self._read_tracked()
        self.assertIsInstance(tracked, bytes)  # 但格式被修回 data
        self.assertFalse(plistlib.loads(tracked)[0]["isAllowed"])

    def test_int拆解数组救援并写回data(self):
        """事故中间态：一份 bplist 的字节流被逐字节拆成 int 数组——
        拼回字节流能救出真记录，写回统一落 data。"""
        import plistlib
        bomb = list(plistlib.dumps([self._rec("com.acme.app", False)],
                                   fmt=plistlib.FMT_BINARY))
        self._write_outer(bomb)
        _, recs = ccnative._load()
        self.assertEqual(ccnative.record_bid(recs[0]), "com.acme.app")  # 救援成功
        got = ccnative.set_apps_allowed({"com.acme.app"}, False)
        self.assertEqual(got, set())
        tracked = self._read_tracked()
        self.assertIsInstance(tracked, bytes)
        self.assertFalse(plistlib.loads(tracked)[0]["isAllowed"])

    def test_彻底坏档清空重建(self):
        """连 int 拼回都救不回的形态：清空重建，不抛异常。"""
        self._write_outer("垃圾")
        _, recs = ccnative._load()
        self.assertEqual(recs, [])


if __name__ == "__main__":
    unittest.main()
