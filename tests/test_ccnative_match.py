#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccnative：bid 匹配规则与侧车读写（离线单测，不碰真实 plist/侧车）。"""
import os
import tempfile
import time
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


class TestSoftApply(unittest.TestCase):
    """软生效（hard=False）与兜底重画：收回不闪的通道与去抖合并。

    背景（用户报障 2026-11-24）：hard apply 重启 MenuBarAgent 是整条菜单栏
    的渲染宿主，重启即全栏清空一下。面板点击后的收回改走软写：只清
    cfprefsd 缓存零闪断，真正抹平靠下一次 hard apply 或超时兜底。
    subprocess/Timer/sleep 全桩，不真杀进程不真等定时器线程。"""

    class _FakeTimer:
        """假 threading.Timer：只记录 start/cancel，到期手动 fire。"""

        def __init__(self, delay, fn):
            self.delay, self.fn = delay, fn
            self.started = False
            self.cancelled = False

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    def setUp(self):
        self.plist = os.path.join(tempfile.mkdtemp(), "cc.plist")
        p = mock.patch.object(ccnative, "CC_PLIST", self.plist)
        p.start()
        self.addCleanup(p.stop)
        self.runs = []  # 记录 subprocess.run（killall 清单），不真执行
        sp = mock.patch.object(ccnative.subprocess, "run",
                               lambda cmd, **kw: self.runs.append(list(cmd)))
        sp.start()
        self.addCleanup(sp.stop)
        sl = mock.patch.object(ccnative.time, "sleep", lambda _s: None)
        sl.start()
        self.addCleanup(sl.stop)
        self.timers = []
        tm = mock.patch.object(ccnative.threading, "Timer",
                               self._mk_timer)
        tm.start()
        self.addCleanup(tm.stop)
        pf = mock.patch.object(ccnative, "_pending_soft", False)
        pf.start()
        self.addCleanup(pf.stop)
        pt = mock.patch.object(ccnative, "_soft_timer", None)
        pt.start()
        self.addCleanup(pt.stop)
        st = mock.patch.object(ccnative, "_soft_targets", {})
        st.start()
        self.addCleanup(st.stop)
        self._write_rec("com.acme.app", True)

    def _mk_timer(self, delay, fn):
        t = self._FakeTimer(delay, fn)
        self.timers.append(t)
        return t

    def _write_rec(self, bid, allowed):
        import plistlib
        with open(self.plist, "wb") as f:
            plistlib.dump({"trackedApplications": plistlib.dumps(
                [{"bundle": {"_0": bid}, "isAllowed": allowed}],
                fmt=plistlib.FMT_BINARY)}, f)

    def killed(self):
        return [c[1] for c in self.runs if c[0] == "killall"]

    def test_软写只清缓存不重启菜单栏(self):
        got = ccnative.set_apps_allowed({"com.acme.app"}, False, hard=False)
        self.assertEqual(got, {"com.acme.app"})
        self.assertEqual(self.killed(), ["cfprefsd"])  # 绝不能碰 MenuBarAgent
        self.assertTrue(ccnative._pending_soft)
        # 软写目标要登记进免检清单（周期核对/自检据此不把它当漂移）
        self.assertEqual(ccnative.soft_pending_bids(), {"com.acme.app"})

    def test_hard写重启全部并抹平pending(self):
        ccnative.set_apps_allowed({"com.acme.app"}, False, hard=False)
        del self.runs[:]
        ccnative.set_apps_allowed({"com.acme.app"}, True)  # 默认 hard
        self.assertEqual(self.killed(), ["cfprefsd", "MenuBarAgent"])
        self.assertFalse(ccnative._pending_soft)  # hard apply 顺带抹平软写
        self.assertEqual(ccnative.soft_pending_bids(), set())

    def test_schedule去抖只留最后一个(self):
        ccnative.schedule_hard_apply(delay=15.0)
        ccnative.schedule_hard_apply(delay=15.0)
        self.assertEqual(len(self.timers), 2)
        self.assertTrue(self.timers[0].cancelled)   # 前一个被取消
        self.assertFalse(self.timers[1].cancelled)
        self.assertTrue(self.timers[1].started)

    def test_apply_now取消兜底定时器(self):
        ccnative.schedule_hard_apply(delay=15.0)
        t = self.timers[-1]
        ccnative.apply_now()
        self.assertTrue(t.cancelled)  # 硬 apply 已把软写一并生效，不再自闪
        self.assertFalse(ccnative._pending_soft)

    def test_到期有pending则后台重画(self):
        ccnative._pending_soft = True
        ccnative.schedule_hard_apply(delay=0.01)
        time.sleep(0.3)  # 真等假 timer 不可能自己 fire，手动补一发
        self.timers[-1].fn()
        self.assertIn("MenuBarAgent", self.killed())
        self.assertFalse(ccnative._pending_soft)

    def test_到期pending已被抹平则零动作(self):
        """期间其它 hard apply 已合并抹平：兜底不得自找闪断。"""
        ccnative._pending_soft = False
        ccnative.schedule_hard_apply(delay=15.0)
        self.timers[-1].fn()  # 模拟到期回调
        self.assertEqual(self.runs, [])

    def test_兜底到期先补写盘再重画(self):
        """软写窗口里系统把旧值回写覆盖：兜底必须补写目标态再重画，
        否则只是把旧态重画回去，图标赖在栏上不收（报障#5 同源）。"""
        import plistlib
        ccnative.set_apps_allowed({"com.acme.app"}, False, hard=False)
        self._write_rec("com.acme.app", True)  # 模拟系统回写覆盖盘上值
        del self.runs[:]
        ccnative.schedule_hard_apply(delay=15.0)
        self.timers[-1].fn()  # 模拟到期
        # 补写一轮 cfprefsd + apply_now 的 cfprefsd/MenuBarAgent
        self.assertEqual(self.killed(),
                         ["cfprefsd", "cfprefsd", "MenuBarAgent"])
        self.assertFalse(plistlib.loads(
            plistlib.load(open(self.plist, "rb"))["trackedApplications"]
        )[0]["isAllowed"])
        self.assertFalse(ccnative._pending_soft)
        self.assertEqual(ccnative.soft_pending_bids(), set())


class TestUnmanageable(unittest.TestCase):
    """不可控名单（2026-11-24 新增）：写后仍在线的 bid 免检免重试，
    重启出名单重试一次；protected 永不进名单。通用设计：不预设任何 App，
    发布给所有用户运行时自适应。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")
        self._orig = (ccnative._unmanageable, ccnative._unmanageable_loaded,
                      sections.config_path)
        sections.config_path = lambda: self.path
        ccnative.clear_unmanageable()
        self.addCleanup(self._restore)
        self.addCleanup(self.dir.cleanup)

    def _restore(self):
        (ccnative._unmanageable, ccnative._unmanageable_loaded,
         sections.config_path) = self._orig

    def test_mark落盘与读回(self):
        ccnative.mark_unmanageable({"com.x.y", "com.z.w"})
        self.assertTrue(ccnative.is_unmanageable("com.x.y"))
        self.assertTrue(os.path.exists(self.path + ".cc_unmanageable"))
        # 模拟新进程：清内存后从盘读回
        ccnative._unmanageable_loaded = False
        ccnative._unmanageable = set()
        self.assertTrue(ccnative.is_unmanageable("com.z.w"))

    def test_protected永不进名单(self):
        ccnative.mark_unmanageable({"com.pease.peasebar", "com.apple.clock"})
        self.assertEqual(ccnative.unmanageable_set(), set())

    def test_clear出名单重试(self):
        """启动清名单：上次被标的 bid 重新获得一次探测机会。"""
        ccnative.mark_unmanageable({"com.x.y"})
        ccnative.clear_unmanageable()
        self.assertFalse(ccnative.is_unmanageable("com.x.y"))

    def test_set是快照外部改动不污染(self):
        ccnative.mark_unmanageable({"com.x.y"})
        snap = ccnative.unmanageable_set()
        snap.add("com.evil")
        self.assertNotIn("com.evil", ccnative.unmanageable_set())


if __name__ == "__main__":
    unittest.main()
