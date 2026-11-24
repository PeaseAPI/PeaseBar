#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板原生隐藏补格：native_hidden_items 的筛选规则（纯函数，离线单测）。

配置「弹窗显示」的图标被 isAllowed=false 藏掉后不进 AX 盘点，面板必须从
配置反推补格子，否则用户会看到「面板里没有、菜单栏也没有」的凭空消失。
不碰 AppKit 与真实 plist：ccnative 的两个读口打桩。
"""
import unittest
from unittest import mock
import types
from types import SimpleNamespace

from peasebar import ccnative, panel, sections


def _seen_item(bid):
    """盘点里出现的真项（最小字段集，panel._collect 口径）。"""
    return SimpleNamespace(owner_bundle_id=bid, label="x", key_part="x",
                           owner_app="x", owner_pid=1, stashed=False,
                           notched=False, frame=None, el=None,
                           is_stash_button=False)


class TestNativeHiddenItems(unittest.TestCase):
    CFG = {"sections": {
        "com.example.app|main": sections.SECTION_HIDDEN,
        "com.example.app|extra": sections.SECTION_HIDDEN,
        "com.example.gone|main": sections.SECTION_HIDDEN,
        "com.example.live|main": sections.SECTION_ALWAYS_HIDDEN,
        "com.apple.something|main": sections.SECTION_HIDDEN,
        "com.example.visible|main": sections.SECTION_HIDDEN,
    }}

    def _run(self, items, now_hidden, unman=()):
        """打桩 hidden_bids_now / last_hidden / unmanageable_set 后跑补格。"""
        with mock.patch.object(ccnative, "hidden_bids_now", return_value=set(now_hidden)), \
             mock.patch.object(ccnative, "last_hidden", return_value=[]), \
             mock.patch.object(ccnative, "unmanageable_set",
                               return_value=set(unman)):
            return panel.native_hidden_items(items, self.CFG)

    def test_盘点里没有的配置隐藏项被补进面板(self):
        """原生藏起的 App（不在盘点、isAllowed=false）必须出现在面板格子集里。"""
        out = self._run([], {"com.example.app", "com.example.gone"})
        self.assertEqual({m.owner_bundle_id for m in out},
                         {"com.example.app", "com.example.gone"})
        # 伪项自述：点击分流与 tooltip 靠它
        self.assertTrue(all(m.native_hidden for m in out))
        # 同 App 多图标（同 bid 多配置键）各占一格
        self.assertEqual([m.label for m in out if m.owner_bundle_id
                          == "com.example.app"], ["main", "extra"])

    def test_还在盘点里的不补(self):
        """仍画在栏上（⌘-拖回退路径下的 stashed 项）由面板旧逻辑管，不重复补。"""
        out = self._run([_seen_item("com.example.visible")],
                        {"com.example.app", "com.example.gone"})
        self.assertNotIn("com.example.visible", {m.owner_bundle_id for m in out})

    def test_受保护与未藏的不补(self):
        """PeaseBar 自己/com.apple.* 永不触碰；没被藏的（App 没在跑等）无事可做。"""
        out = self._run([], {"com.example.app", "com.example.gone"})
        self.assertNotIn("com.apple.something", {m.owner_bundle_id for m in out})
        self.assertNotIn("com.example.live", {m.owner_bundle_id for m in out})

    def test_侧车记录也算隐藏证据(self):
        """reconcile 中途崩溃没来得及写 isAllowed 时，侧车记录兜底识别。"""
        with mock.patch.object(ccnative, "hidden_bids_now", return_value=set()), \
             mock.patch.object(ccnative, "last_hidden",
                               return_value=["com.example.app"]), \
             mock.patch.object(ccnative, "unmanageable_set", return_value=set()):
            out = panel.native_hidden_items([], self.CFG)
        self.assertIn("com.example.app", {m.owner_bundle_id for m in out})
    
    def test_不可控项已被系统藏掉必须补进弹窗(self):
        """报障（2026-11-24 OneDrive/ToDesk/Synology）：名单里若有项其实
        已被系统藏掉（不在栏上），它就不再「不可控」，必须补回弹窗，否则
        「既不在栏上、又进不了弹窗」两头消失。旧代码无条件减名单正犯了这条。"""
        out = self._run([], {"com.example.app", "com.example.gone"},
                        unman={"com.example.gone"})
        # gone 虽在不可控名单，但此刻不在盘点（items=[]）→ 仍要补
        self.assertEqual({m.owner_bundle_id for m in out},
                         {"com.example.app", "com.example.gone"})

    def test_不可控项真在栏上不补伪项(self):
        """QQ 案例（2026-11-24）：系统藏不掉的 bid 真项就在盘点里，
        再补伪项就是「栏上有、格子却标成原生隐藏」的鬼影——靠 seen 实况去重挡掉。"""
        out = self._run([_seen_item("com.example.gone")],
                        {"com.example.app", "com.example.gone"},
                        unman={"com.example.gone"})
        self.assertEqual({m.owner_bundle_id for m in out}, {"com.example.app"})

    def test_伪项按配置order排序(self):
        """布局页拖完的顺序要立刻在面板生效（2026-11-25 用户反馈「顺序没变」的
        真根因：伪项原先按 sections 字典插入序输出，而拖动写的是 order）。"""
        cfg = {"sections": {"com.example.app|main": sections.SECTION_HIDDEN,
                            "com.example.gone|main": sections.SECTION_HIDDEN},
               "order": ["com.example.gone|main", "com.example.app|main"]}
        with mock.patch.object(ccnative, "hidden_bids_now",
                               return_value={"com.example.app", "com.example.gone"}), \
             mock.patch.object(ccnative, "last_hidden", return_value=[]), \
             mock.patch.object(ccnative, "unmanageable_set", return_value=set()):
            out = panel.native_hidden_items([], cfg)
        self.assertEqual([sections.item_key(m) for m in out],
                         ["com.example.gone|main", "com.example.app|main"])

    def test_伪项字段满足渲染与触发口径(self):
        """格子渲染要 label/key_part；触发链路要 owner_bundle_id/frame=None。"""
        out = self._run([], {"com.example.app"})
        m = out[0]
        self.assertEqual(sections.item_key(m), "com.example.app|main")
        self.assertIsNone(m.frame)  # capture.image_for_item 对 None frame 走兜底
        self.assertFalse(m.is_stash_button)
        self.assertGreater(len(m.owner_bundle_id.rsplit(".", 1)[-1]), 0)


class TestNativeTileClickGuards(unittest.TestCase):
    """点「原生隐藏」格的守门：不该闪菜单栏的情形绝不进显回链路
    （2026-11-24 用户报障：点格子菜单栏白闪两下、图标还不回去）。"""

    BID = "com.example.app"

    def _click(self, online, running, found=None, prefer_menu=False,
               learned=None, reopen_hit=False):
        """同步跑 open_native_hidden_async，返回 (写盘调用, 触发记录)。

        learned=None → 默认该 bid 已学过「reopen 不行」（聚焦显回链本身）；
        learned=dict 可预置学习表；reopen_hit 控 try_reopen 桩的成败。"""
        calls, trig = [], []
        launches = []   # 报障②：未启动 App 的 open -b 启动记录
        # 假时钟：每次 time() 走 1s，保证空等循环能自然结束
        clock = {"t": 0.0}

        def _list_items():
            # 守门①先拿一次（看图标在不在栏上），进入显回后的轮询才拿 found
            _list_items.n += 1
            return (found or [], []) if _list_items.n > 1 else (online, [])

        _list_items.n = 0

        class _SyncThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        def _allowed(bids, allowed, hard=True):
            calls.append((tuple(bids), allowed, hard))
            return set(bids)

        learned = {self.BID: False} if learned is None else learned

        with mock.patch.object(panel.inventory, "list_items", _list_items), \
             mock.patch.object(panel, "_app_running", return_value=running), \
             mock.patch.object(panel, "_reopen_learned", learned), \
             mock.patch.object(panel, "try_reopen",
                               lambda bid, settle=1.6: reopen_hit), \
             mock.patch.object(panel.ccnative, "set_apps_allowed", _allowed), \
             mock.patch.object(panel.ccnative, "schedule_hard_apply",
                               lambda *a: calls.append(("兜底",))), \
             mock.patch.object(panel.trigger, "open_item",
                               side_effect=lambda m, prefer_menu=False:
                               (trig.append((m, prefer_menu)),
                                ("AXPress", True))[1]), \
             mock.patch.object(panel.threading, "Thread", _SyncThread), \
             mock.patch("subprocess.run",
                        side_effect=lambda cmd, **k:
                        launches.append(tuple(cmd))), \
             mock.patch.object(panel, "time", types.SimpleNamespace(
                 sleep=lambda _s: None,
                 time=lambda: clock.__setitem__("t", clock["t"] + 1.0)
                 or clock["t"])):
            panel.open_native_hidden_async(self.BID, prefer_menu=prefer_menu)
        return calls, trig, launches

    def test_图标就在栏上时直接触发零闪断(self):
        """不可控名单/快照过期：真项就在盘点里 → 不碰 plist、不重启 Agent。"""
        calls, trig, _ = self._click([_seen_item(self.BID)], running=True)
        self.assertEqual(calls, [])            # 零写盘 = 零闪断
        self.assertEqual(len(trig), 1)          # 但图标照样能触发

    def test_App没在跑时不白闪(self):
        """显回变不出不存在的图标（实测空等 8s）：不白闪、不写盘。报障
        十一：左键会改为 open -b 启动 App（launches 非空），但不进显回链。"""
        calls, trig, launches = self._click([], running=False)
        self.assertEqual(calls, [])            # 零写盘 = 零闪断
        self.assertEqual(trig, [])             # 不走显回触发链
        self.assertEqual(launches, [("open", "-b", self.BID)])  # 左键启动了 App

    def test_右键遇未启动App不启动只告知(self):
        """右键要弹菜单：App 没跑无从弹，不擅自启动（区别于左键），零写盘。"""
        calls, trig, launches = self._click([], running=False, prefer_menu=True)
        self.assertEqual(calls, [])
        self.assertEqual(trig, [])
        self.assertEqual(launches, [])         # 右键不启动

    def test_真藏着的显回与收回都是硬生效(self):
        """只有这种才付闪断：显回 hard，收回也 hard（图标当场回去，
        不再软写赖到 15s 兜底），也不另排兜底定时器。"""
        calls, trig, _ = self._click([], running=True,
                                    found=[_seen_item(self.BID)])
        self.assertEqual([(c[1], c[2]) for c in calls],
                         [(True, True), (False, True)])
        self.assertNotIn(("兜底",), calls)
        self.assertEqual(len(trig), 1)
    
    def test_右键守门直通也透传弹菜单语义(self):
        """图标就在栏上 + 右键：直接触发那份要把 prefer_menu 递到 trigger。"""
        calls, trig, _ = self._click([_seen_item(self.BID)], running=True,
                                    prefer_menu=True)
        self.assertEqual(calls, [])
        self.assertEqual([prefer for _m, prefer in trig], [True])
    
    def test_右键显回后的触发同样prefer_menu(self):
        """真藏着的：显回→触发那一步右键语义不能丢（两段链路同一个开关）。"""
        calls, trig, _ = self._click([], running=True,
                                    found=[_seen_item(self.BID)],
                                    prefer_menu=True)
        self.assertEqual([prefer for _m, prefer in trig], [True])


class TestReopenFastPath(unittest.TestCase):
    """左键 reopen 直达捷径（报障九，2026-11-24）：命中即零写盘零闪断；
    落空只学一次，以后直接走显回链不白等；右键不走（语义不对）。"""

    BID = "com.example.app"

    def _click(self, learned, reopen_hit, prefer_menu=False):
        calls, done = [], []
        n = {"i": 0}

        def _list_items():
            # 守门①时不在栏上（逼出 ③）；显回后的轮询才拿到重连的图标
            n["i"] += 1
            return (([_seen_item(self.BID)], []) if n["i"] > 1 else ([], []))

        clock = {"t": 0.0}

        class _SyncThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        with mock.patch.object(panel.inventory, "list_items", _list_items), \
             mock.patch.object(panel, "_app_running", return_value=True), \
             mock.patch.object(panel, "_reopen_learned", learned), \
             mock.patch.object(panel, "try_reopen",
                               lambda bid, settle=1.6: reopen_hit), \
             mock.patch.object(panel.ccnative, "set_apps_allowed",
                               lambda bids, allowed, hard=True:
                               calls.append((allowed, hard)) or set(bids)), \
             mock.patch.object(panel.trigger, "open_item",
                               side_effect=lambda m, prefer_menu=False:
                               ("chain", False)), \
             mock.patch.object(panel.threading, "Thread", _SyncThread), \
             mock.patch.object(panel, "time", types.SimpleNamespace(
                 sleep=lambda _s: None,
                 time=lambda: clock.__setitem__("t", clock["t"] + 1.0)
                 or clock["t"])):
            panel.open_native_hidden_async(
                self.BID, lambda how, seen: done.append((how, seen)),
                prefer_menu=prefer_menu)
        return calls, done

    def test_首试命中即零写盘并记住(self):
        learned = {}
        calls, done = self._click(learned, reopen_hit=True)
        self.assertEqual(calls, [])           # 没碰 plist = 没闪断
        self.assertTrue(done and done[0][1])   # 且如实报告「开窗了」
        self.assertTrue(learned[self.BID])     # 学会了：这家用 reopen

    def test_学过的再命中仍零写盘(self):
        calls, done = self._click({self.BID: True}, reopen_hit=True)
        self.assertEqual(calls, [])
        self.assertTrue(done[0][1])

    def test_落空只学一次并回退显回链(self):
        learned = {self.BID: True}             # 曾经过，今天 reopen 失灵
        calls, _done = self._click(learned, reopen_hit=False)
        self.assertEqual(learned[self.BID], False)  # 改正学习表，下次不白试
        self.assertEqual(calls, [(True, True), (False, True)])  # 照常走链

    def test_右键不走reopen捷径(self):
        """reopen 开的是主窗口（左键语义），弹不了状态菜单——右键必须继续
        走显回链把图标请回栏上再投。"""
        calls, _done = self._click({self.BID: True}, reopen_hit=True,
                                   prefer_menu=True)
        self.assertEqual(calls, [(True, True), (False, True)])  # 显回+收回


class TestReentry(unittest.TestCase):
    """连点防重入（报障九「点了半天」诱因）：同一 bid 链未走完时不叠第二条。"""

    BID = "com.example.app"

    def test_上一发进行中就早退(self):
        calls = []
        panel._inflight.add(self.BID)
        self.addCleanup(panel._inflight.discard, self.BID)

        class _NoThread:
            def __init__(self, target=None, daemon=None):
                raise AssertionError("早退应发生在开线程之前")

        with mock.patch.object(panel, "threading", types.SimpleNamespace(
                Thread=_NoThread)):
            panel.open_native_hidden_async(self.BID,
                                           lambda h, s: calls.append(s))
        self.assertEqual(calls, [False])  # 只回调了「不叠加」，没进任何链路


class TestTryReopenActivation(unittest.TestCase):
    """try_reopen 双判据（报障十）：reopen 没开新窗但把 App 提到前台也算命中，
    不能只数新窗口——QQ/微信这类已有主窗、reopen 只激活，旧版误判落空又走显回链。"""

    BID = "com.example.qq"

    class _App:
        def __init__(self, pid, bid):
            self._p, self._b = pid, bid

        def bundleIdentifier(self):
            return self._b

        def processIdentifier(self):
            return self._p

    def _run(self, front_pid, opened):
        import AppKit
        ws = mock.MagicMock()
        ws.runningApplications.return_value = [self._App(4242, self.BID)]
        ws.frontmostApplication.return_value = self._App(front_pid, "x")
        clock = {"t": 0.0}
        with mock.patch.object(AppKit, "NSWorkspace") as NSW, \
             mock.patch("subprocess.run"), \
             mock.patch.object(panel.trigger, "_snapshot", lambda: {}), \
             mock.patch.object(panel.trigger, "_opened_since",
                               lambda b, p: opened), \
             mock.patch.object(panel, "time", types.SimpleNamespace(
                 sleep=lambda _s: None,
                 time=lambda: clock.__setitem__("t", clock["t"] + 1.0)
                 or clock["t"])):
            NSW.sharedWorkspace.return_value = ws
            return panel.try_reopen(self.BID)

    def test_无新窗但前台激活算命中(self):
        self.assertTrue(self._run(4242, opened=[]))

    def test_无新窗又没激活则落空(self):
        self.assertFalse(self._run(9999, opened=[]))

    def test_冒新窗也算命中(self):
        self.assertTrue(self._run(9999, opened=[(1, 2, (0, 0, 100, 100))]))


class TestMenuUnsupportedLearning(unittest.TestCase):
    """右键弹不出菜单的学习与直通（报障十 QQ 右键白闪两下）：无可操作 AX
    元素的 App 首弹学过之后，右键不再白走显回→收回，零闪如实告知。"""

    BID = "com.example.qq"

    def _click(self, unsupported):
        calls, done = [], []
        n = {"i": 0}

        def _list_items():
            # 守门①不在栏上（逼出③）；显回后轮询才拿到重连图标
            n["i"] += 1
            return (([_seen_item(self.BID)], []) if n["i"] > 1 else ([], []))

        clock = {"t": 0.0}

        class _SyncThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        with mock.patch.object(panel.inventory, "list_items", _list_items), \
             mock.patch.object(panel, "_app_running", return_value=True), \
             mock.patch.object(panel, "_reopen_learned", {self.BID: False}), \
             mock.patch.object(panel, "_menu_unsupported", unsupported), \
             mock.patch.object(panel.ccnative, "set_apps_allowed",
                               lambda bids, allowed, hard=True:
                               calls.append((allowed, hard)) or set(bids)), \
             mock.patch.object(panel.trigger, "open_item",
                               side_effect=lambda m, prefer_menu=False:
                               ("链上弹不了", False)), \
             mock.patch.object(panel.threading, "Thread", _SyncThread), \
             mock.patch.object(panel, "time", types.SimpleNamespace(
                 sleep=lambda _s: None,
                 time=lambda: clock.__setitem__("t", clock["t"] + 1.0)
                 or clock["t"])):
            panel.open_native_hidden_async(
                self.BID, lambda how, seen: done.append((how, seen)),
                prefer_menu=True)
        return calls, done

    def test_首弹落空学到bid(self):
        unsupported = set()
        calls, _done = self._click(unsupported)
        self.assertEqual(calls, [(True, True), (False, True)])  # 首弹仍显回+收回
        self.assertIn(self.BID, unsupported)                     # 但学到了

    def test_学过之后右键直通零闪零写盘(self):
        calls, done = self._click({self.BID})
        self.assertEqual(calls, [])          # 不再碰 plist = 零闪断
        self.assertTrue(done and done[0][1] is False)


if __name__ == "__main__":
    unittest.main()
